"""
vara/omnirig.py — Thread-safe OmniRig client for Aether Term (HF PTT control).

All COM calls run on a single dedicated thread to avoid cross-apartment
proxy issues.  This is used only for VARA HF, where the modem sends
PTT ON/PTT OFF events and expects the application to key the radio.

VARA FM handles PTT internally — no OmniRig needed for FM.

Adapted from the VARA BBS OmniRig module.

Usage:
    client = OmniRigClient(rig_number=1)
    client.start()          # spawns COM thread, connects to OmniRig

    client.set_ptt(True)    # thread-safe — queued to COM thread
    freq = client.get_freq()

    client.stop()           # releases PTT, disconnects, joins thread
"""

import logging
import queue
import threading
import time
from typing import Any, Optional

log = logging.getLogger(__name__)

# OmniRig PTT constants
PM_RX = 0x00200000   # receive (PTT off)
PM_TX = 0x00400000   # transmit (PTT on)

# OmniRig status constants
ST_NOTCONFIGURED = 0
ST_DISABLED      = 1
ST_PORTBUSY      = 2
ST_NOTRESPONDING = 3
ST_ONLINE        = 4
ST_TRANSCEIVE    = 5

STATUS_NAMES = {
    0: "NOT_CONFIGURED",
    1: "DISABLED",
    2: "PORT_BUSY",
    3: "NOT_RESPONDING",
    4: "ONLINE",
    5: "TRANSCEIVE",
}


class _Cmd:
    """A command to be executed on the COM thread."""
    __slots__ = ("action", "args", "result", "done")

    def __init__(self, action: str, args: Any = None):
        self.action = action
        self.args = args
        self.result: Any = None
        self.done = threading.Event()


class OmniRigClient:
    """Thread-safe OmniRig client.

    Spawns a single daemon thread that owns the COM connection.
    All public methods are safe to call from any thread — they enqueue
    commands and (for getters) block until the COM thread completes them.
    """

    def __init__(self, rig_number: int = 1):
        if rig_number not in (1, 2):
            raise ValueError("rig_number must be 1 or 2")
        self._rig_number = rig_number
        self._queue: queue.Queue[Optional[_Cmd]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._error: Optional[str] = None
        self._started = False

    # -- Lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Spawn the COM thread and connect to OmniRig.

        Blocks until the connection is established or fails.
        Raises RuntimeError on failure.
        """
        if self._started:
            return
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"OmniRig-Rig{self._rig_number}",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=15.0)
        if self._error:
            raise RuntimeError(self._error)
        self._started = True

    def stop(self) -> None:
        """Release PTT, disconnect, and join the COM thread."""
        if not self._started:
            return
        self._queue.put(None)  # poison pill
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._started = False

    @property
    def is_started(self) -> bool:
        return self._started

    # -- Thread-safe public API --------------------------------------------

    def set_ptt(self, on: bool) -> bool:
        """Key (True) or unkey (False) the radio.  Returns True on success."""
        target = PM_TX if on else PM_RX
        return self._exec("SET_PTT", target)

    def set_freq(self, freq_hz: int) -> bool:
        """Set VFO-A frequency in Hz.  Returns True on success."""
        return self._exec("SET_FREQ", freq_hz)

    def set_mode(self, mode_val: int) -> bool:
        """Set mode using OmniRig mode constant.  Returns True on success."""
        return self._exec("SET_MODE", mode_val)

    def get_freq(self) -> int:
        """Read current VFO-A frequency in Hz.  Returns 0 on failure."""
        return self._exec_get("GET_FREQ")

    def get_status(self) -> int:
        """Read OmniRig rig status word.  Returns 0 on failure."""
        return self._exec_get("GET_STATUS")

    def get_tx(self) -> int:
        """Read current Tx state.  Returns 0 on failure."""
        return self._exec_get("GET_TX")

    def get_status_name(self) -> str:
        """Return human-readable status string."""
        status = self.get_status()
        return STATUS_NAMES.get(status, f"UNKNOWN({status})")

    # -- Internal helpers --------------------------------------------------

    def _exec(self, action: str, args: Any = None) -> bool:
        if not self._started:
            return False
        cmd = _Cmd(action, args)
        self._queue.put(cmd)
        cmd.done.wait(timeout=5.0)
        return cmd.result is True

    def _exec_get(self, action: str) -> Any:
        if not self._started:
            return 0
        cmd = _Cmd(action)
        self._queue.put(cmd)
        cmd.done.wait(timeout=5.0)
        return cmd.result if cmd.result is not None else 0

    # -- COM thread --------------------------------------------------------

    def _run(self) -> None:
        """COM thread main loop — owns the single OmniRig connection.

        Uses STA (Single-Threaded Apartment) with message pumping.
        """
        rig_num = self._rig_number

        try:
            import win32com.client
            import pythoncom
        except ImportError:
            self._error = (
                "pywin32 is required for OmniRig PTT. "
                "Install with: pip install pywin32"
            )
            self._ready.set()
            return

        try:
            pythoncom.CoInitialize()
        except Exception:
            pass

        try:
            omnirig = win32com.client.Dispatch("OmniRig.OmniRigX")
        except Exception as e:
            self._error = (
                f"Cannot connect to OmniRig COM server. "
                f"Is OmniRig installed and running? Error: {e}"
            )
            self._ready.set()
            return

        rig = omnirig.Rig1 if rig_num == 1 else omnirig.Rig2

        # Wait for OmniRig to establish radio communication
        log.info(f"OmniRig Rig{rig_num}: waiting for radio to come online...")
        last_status = -1
        online = False
        for _ in range(50):  # up to ~5 seconds
            pythoncom.PumpWaitingMessages()
            try:
                status = rig.Status
                if status != last_status:
                    sname = STATUS_NAMES.get(status, f"UNKNOWN({status})")
                    log.info(f"OmniRig Rig{rig_num} status: {sname}")
                    last_status = status
                if status >= ST_ONLINE:
                    online = True
                    break
            except Exception as e:
                log.warning(f"OmniRig Rig{rig_num} status poll: {e}")
            time.sleep(0.1)

        if online:
            try:
                freq = rig.FreqA
                log.info(f"OmniRig Rig{rig_num} ONLINE — freq={freq/1000:.1f} kHz")
            except Exception:
                pass
        else:
            log.warning(
                f"OmniRig Rig{rig_num} not online after 5s. "
                f"Check OmniRig setup: rig type, COM port, baud rate."
            )

        self._ready.set()

        # -- Command loop --------------------------------------------------
        try:
            while True:
                pythoncom.PumpWaitingMessages()

                try:
                    cmd = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                if cmd is None:
                    # Poison pill — shut down
                    try:
                        rig.Tx = PM_RX
                        pythoncom.PumpWaitingMessages()
                    except Exception:
                        pass
                    break

                try:
                    if cmd.action == "SET_PTT":
                        rig.Tx = cmd.args
                        pythoncom.PumpWaitingMessages()
                        time.sleep(0.05)
                        pythoncom.PumpWaitingMessages()
                        log.info(f"OmniRig Rig{rig_num} PTT -> 0x{cmd.args:08X}")
                        cmd.result = True

                    elif cmd.action == "SET_FREQ":
                        rig.FreqA = cmd.args
                        pythoncom.PumpWaitingMessages()
                        cmd.result = True

                    elif cmd.action == "SET_MODE":
                        rig.Mode = cmd.args
                        pythoncom.PumpWaitingMessages()
                        cmd.result = True

                    elif cmd.action == "GET_FREQ":
                        cmd.result = rig.FreqA
                    elif cmd.action == "GET_STATUS":
                        cmd.result = rig.Status
                    elif cmd.action == "GET_TX":
                        cmd.result = rig.Tx
                    else:
                        cmd.result = None
                except Exception as e:
                    log.error(f"OmniRig Rig{rig_num} {cmd.action} error: {e}")
                    cmd.result = None
                finally:
                    cmd.done.set()

        finally:
            try:
                rig.Tx = PM_RX  # safety release
            except Exception:
                pass
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
            log.info(f"OmniRig Rig{rig_num} COM thread exited")
