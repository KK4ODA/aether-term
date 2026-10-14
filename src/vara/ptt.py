"""
vara/ptt.py — PTT control for Aether Term.

VARA HF (and Aether HF set to "host program" keying) sends "PTT ON" /
"PTT OFF" on the command port and expects the connecting program to key
the radio.  VARA FM, Soundmodem and Aether HF otherwise key it themselves.

Supported methods (the ``hf_ptt_method`` setting):
  - OmniRig  (Windows COM automation)
  - Hamlib   (rigctld over TCP)
  - FLrig    (XML-RPC, port 12345)
  - VOX      (nothing to do: the radio keys itself on audio)

PTTController keys the chosen rig client on the modem's PTT events, in
the order they came, and releases the radio if the modem goes quiet
while keyed (watchdog) or when it is stopped.
"""

import logging
import queue
import threading
import time
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

# Watchdog: VARA HF sends IAMALIVE every ~60s.  If we haven't received
# a PTT OFF within 90s of keying, force-release as a safety measure.
WATCHDOG_TIMEOUT = 90.0


def _make_rig(method: str, config):
    """The rig client for an ``hf_ptt_method`` setting (not yet started)."""
    from config import PTT_FLRIG, PTT_HAMLIB, PTT_OMNIRIG
    if method == PTT_OMNIRIG:
        from vara.omnirig import OmniRigClient
        return OmniRigClient(rig_number=config.get("omnirig_rig_number", 1))
    if method == PTT_HAMLIB:
        from vara.hamlib import HamlibClient
        return HamlibClient(
            host=config.get("hamlib_rigctld_host", "127.0.0.1"),
            port=config.get("hamlib_rigctld_port", 4532),
            rig_model=config.get("hamlib_rig_model", 1),
            device=config.get("hamlib_device", ""),
            serial_speed=config.get("hamlib_serial_speed", 0),
            auto_launch=config.get("hamlib_auto_launch", True),
            rigctld_path=config.get("hamlib_rigctld_path", ""),
            extra_args=config.get("hamlib_extra_args", ""),
        )
    if method == PTT_FLRIG:
        from vara.flrig import FLrigClient
        return FLrigClient(host=config.get("flrig_host", "127.0.0.1"),
                           port=config.get("flrig_port", 12345))
    raise ValueError(f"Unknown PTT method: {method}")


class PTTController(QObject):
    """Keys a rig client (OmniRig, Hamlib or FLrig) on the modem's PTT events.

    Signals:
        ptt_changed(bool)   — PTT state changed (for the GUI indicator)
        ptt_error(str)      — a rig could not be started or keyed
    """

    ptt_changed = pyqtSignal(bool)
    ptt_error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rig = None                 # a started RigClient, or None
        self._name = ""
        self._ptt_on = False
        self.last_error = ""             # why the last start_method() failed
        self._watchdog: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        # Radio keying runs on one worker thread, in the order the modem
        # asked: a thread per event let a slow PTT ON run after the PTT OFF
        # that followed it, leaving the transmitter keyed.
        self._keying: "queue.Queue[bool]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None

    @property
    def is_enabled(self) -> bool:
        return self._rig is not None

    @property
    def ptt_on(self) -> bool:
        return self._ptt_on

    def start_method(self, method: str, config) -> bool:
        """Start the rig client for an ``hf_ptt_method`` setting.

        Returns True when the radio can be keyed, False when it cannot
        (``last_error`` and ``ptt_error`` say why).  A rig left running
        from an earlier call is stopped first.
        """
        self.stop()
        self.last_error = ""
        try:
            rig = _make_rig(method, config)
            rig.start()
        except (ImportError, RuntimeError, ValueError) as e:
            self.last_error = str(e) or f"{method} unavailable"
            log.error(f"{method} PTT start failed: {self.last_error}")
            self.ptt_error.emit(self.last_error)
            return False
        self.use_rig(rig, method)
        return True

    def use_rig(self, rig, name: str):
        """Key *rig*, an already started rig client, from now on."""
        self._rig = rig
        self._name = name
        log.info(f"PTT controller started ({name})")

    def stop(self):
        """Release PTT and close the rig client."""
        self._cancel_watchdog()
        rig = self._rig
        if rig is None:
            return
        self._rig = None                 # keying still queued is dropped
        while True:
            try:
                self._keying.get_nowait()
                self._keying.task_done()
            except queue.Empty:
                break
        self.wait_idle(timeout=3.0)      # let a command already running finish
        with self._lock:
            self._ptt_on = False
        # Unkey whatever the last command did (the rig clients unkey on
        # close too; this one is in order behind the command just run)
        try:
            rig.set_ptt(False)
        except Exception as e:
            log.warning(f"Failed to release PTT during stop: {e}")
        try:
            rig.stop()
        except Exception as e:
            log.warning(f"{self._name} stop failed: {e}")
        log.info("PTT controller stopped")

    def on_ptt_event(self, ptt_on: bool):
        """The modem sent PTT ON (True) or PTT OFF (False)."""
        if self._rig is None:
            log.debug(f"PTT {'ON' if ptt_on else 'OFF'} ignored (controller disabled)")
            return

        with self._lock:
            self._ptt_on = ptt_on

        log.info(f"PTT {'KEYING' if ptt_on else 'UNKEYING'} radio via {self._name}")
        self._queue_keying(ptt_on)
        self.ptt_changed.emit(ptt_on)

        if ptt_on:
            self._start_watchdog()
        else:
            self._cancel_watchdog()

    def _queue_keying(self, ptt_on: bool):
        """Key or unkey the radio on the worker thread, in order."""
        with self._lock:
            if self._worker is None:
                # One long-lived worker: one that quit when idle could miss
                # a command queued just as it was leaving.
                self._worker = threading.Thread(
                    target=self._keying_loop, name="PTT-keying", daemon=True)
                self._worker.start()
        self._keying.put(ptt_on)

    def _keying_loop(self):
        while True:
            ptt_on = self._keying.get()
            try:
                self._do_ptt(ptt_on)
            finally:
                self._keying.task_done()

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """Wait until queued keying commands have run (shutdown, tests)."""
        end = time.time() + timeout
        while self._keying.unfinished_tasks:
            if time.time() > end:
                return False
            time.sleep(0.01)
        return True

    def _do_ptt(self, ptt_on: bool):
        """Key the radio (worker thread)."""
        rig, name = self._rig, self._name
        if rig is None:
            return                       # stopped meanwhile; stop() unkeys
        try:
            if not rig.is_started:
                log.warning(f"{name} not connected — PTT command dropped")
                self.ptt_error.emit(f"{name} not connected")
            elif not rig.set_ptt(ptt_on):
                log.warning(f"{name} set_ptt({ptt_on}) failed")
                self.ptt_error.emit(f"{name} PTT command failed")
        except Exception as e:
            log.error(f"PTT error: {e}")
            self.ptt_error.emit(str(e))

    def _start_watchdog(self):
        """Start or reset the PTT safety watchdog."""
        self._cancel_watchdog()
        self._watchdog = threading.Timer(WATCHDOG_TIMEOUT, self._watchdog_expired)
        self._watchdog.daemon = True
        self._watchdog.start()

    def _cancel_watchdog(self):
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None

    def _watchdog_expired(self):
        """Safety cutoff — release PTT if modem hasn't sent PTT OFF."""
        with self._lock:
            if not self._ptt_on:
                return
            self._ptt_on = False

        log.warning(
            f"PTT WATCHDOG: forcibly releasing PTT after {WATCHDOG_TIMEOUT:.0f}s. "
            f"Check VARA HF modem status!"
        )
        self._queue_keying(False)           # behind anything already queued
        self.ptt_changed.emit(False)
        self.ptt_error.emit("PTT watchdog: forced release after timeout")
