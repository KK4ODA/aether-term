"""
vara/rig_client.py — Shared plumbing for the radio PTT clients.

OmniRig, Hamlib (rigctld) and FLrig each talk to the radio from one
dedicated I/O thread: OmniRig's COM objects must stay on the thread that
created them, and a single thread keeps commands to a socket in order.
``set_ptt`` may be called from any thread; it is queued to the I/O
thread and waits for the result.

A subclass supplies the protocol:
    _open()      connect (on the I/O thread); raise to fail start()
    _key(on)     key or unkey the radio; return True on success
    _close()     unkey and disconnect (on the I/O thread; always run, also
                 after a failed _open, so it must cope with a half-open link)
    _idle()      optional work between commands (OmniRig pumps COM messages)
"""

import logging
import queue
import threading
from typing import Optional

log = logging.getLogger(__name__)


class _Cmd:
    __slots__ = ("on", "result", "done")

    def __init__(self, on: bool):
        self.on = on
        self.result = False
        self.done = threading.Event()


class RigClient:
    NAME = "Rig"
    START_TIMEOUT = 15.0     # longest _open() may take
    CMD_TIMEOUT = 5.0        # longest a PTT command may take
    POLL = 0.2               # how often _idle() runs while waiting

    def __init__(self):
        self._queue: "queue.Queue[Optional[_Cmd]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._error: Optional[str] = None
        self._started = False

    # ── Lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        """Connect on the I/O thread.  Blocks until connected or failed.

        Raises RuntimeError on failure — including a connection that takes
        longer than START_TIMEOUT, which is not taken as success.
        """
        if self._started:
            return
        self._queue = queue.Queue()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._run, name=f"{self.NAME}-IO", daemon=True)
        self._thread.start()
        if not self._ready.wait(self.START_TIMEOUT):
            self._queue.put(None)    # the thread ends once it gets this far
            raise RuntimeError(
                f"{self.NAME} did not answer within {self.START_TIMEOUT:.0f} s")
        if self._error:
            raise RuntimeError(self._error)
        self._started = True

    def stop(self) -> None:
        """Unkey, disconnect, and end the I/O thread."""
        if not self._started:
            return
        self._started = False
        self._queue.put(None)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.CMD_TIMEOUT)

    @property
    def is_started(self) -> bool:
        return self._started

    def set_ptt(self, on: bool) -> bool:
        """Key (True) or unkey (False) the radio.  True on success."""
        if not self._started:
            return False
        cmd = _Cmd(on)
        self._queue.put(cmd)
        return cmd.done.wait(self.CMD_TIMEOUT) and cmd.result

    # ── I/O thread ────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            try:
                self._open()
            except Exception as e:
                self._error = str(e)
                return
            finally:
                self._ready.set()
            while True:
                self._idle()
                try:
                    cmd = self._queue.get(timeout=self.POLL)
                except queue.Empty:
                    continue
                if cmd is None:
                    break
                try:
                    cmd.result = bool(self._key(cmd.on))
                except Exception as e:
                    log.error(f"{self.NAME} PTT {'ON' if cmd.on else 'OFF'} error: {e}")
                finally:
                    cmd.done.set()
        finally:
            try:
                self._close()
            except Exception as e:
                log.warning(f"{self.NAME}: release on exit failed: {e}")
            log.info(f"{self.NAME} I/O thread exited")

    # ── Protocol hooks ────────────────────────────────────────────

    def _open(self) -> None:
        raise NotImplementedError

    def _key(self, on: bool) -> bool:
        raise NotImplementedError

    def _close(self) -> None:
        raise NotImplementedError

    def _idle(self) -> None:
        pass
