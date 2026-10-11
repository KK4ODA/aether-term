"""
vara/ptt.py — PTT control for Aether Term (VARA HF only).

VARA FM controls PTT internally through its own settings.
VARA HF sends "PTT ON" / "PTT OFF" events on the command port and
expects the connecting application to physically key the radio.

Supported HF PTT methods:
  - OmniRig  (Windows COM automation)
  - Hamlib   (rigctld over TCP)
  - FLrig    (XML-RPC, port 12345)
  - VOX      (no-op fallback)

This module provides a PTTController that listens for PTT signals
from the VARAModem and delegates to the configured backend.  Includes
a safety watchdog that releases PTT if the modem stops communicating.
"""

import logging
import threading
import time
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

# Watchdog: VARA HF sends IAMALIVE every ~60s.  If we haven't received
# a PTT OFF within 90s of keying, force-release as a safety measure.
WATCHDOG_TIMEOUT = 90.0


class PTTController(QObject):
    """Bridges VARA HF PTT events to OmniRig radio control.

    Signals:
        ptt_changed(bool)   — emitted when PTT state changes (for GUI indicator)
        ptt_error(str)      — emitted on PTT hardware errors
    """

    ptt_changed = pyqtSignal(bool)
    ptt_error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._omnirig = None
        self._hamlib = None
        self._flrig = None
        self._backend = "omnirig"  # "omnirig", "hamlib", or "flrig"
        self._ptt_on = False
        self._enabled = False
        self._shared_hamlib = False  # True if hamlib client is owned externally
        self._shared_flrig = False   # True if flrig client is owned externally
        self._rig_number = 1
        self._watchdog: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def ptt_on(self) -> bool:
        return self._ptt_on

    def start(self, rig_number: int = 1) -> bool:
        """Connect to OmniRig and prepare for PTT control.

        Returns True on success, False if OmniRig is unavailable.
        """
        self._rig_number = rig_number

        try:
            from vara.omnirig import OmniRigClient
            self._omnirig = OmniRigClient(rig_number=rig_number)
            self._omnirig.start()
            self._enabled = True
            log.info(f"PTT controller started (OmniRig Rig{rig_number})")
            return True
        except ImportError:
            log.warning("pywin32 not installed — OmniRig PTT unavailable")
            self.ptt_error.emit(
                "OmniRig requires pywin32. Install with: pip install pywin32")
            return False
        except RuntimeError as e:
            log.error(f"OmniRig start failed: {e}")
            self.ptt_error.emit(str(e))
            return False

    def start_hamlib(self, config) -> bool:
        """Connect to Hamlib rigctld for PTT control.

        Returns True on success, False if Hamlib is unavailable.
        """
        try:
            from vara.hamlib import HamlibClient
            self._hamlib = HamlibClient(
                host=config.get("hamlib_rigctld_host", "127.0.0.1"),
                port=config.get("hamlib_rigctld_port", 4532),
                rig_model=config.get("hamlib_rig_model", 1),
                device=config.get("hamlib_device", ""),
                serial_speed=config.get("hamlib_serial_speed", 0),
                auto_launch=config.get("hamlib_auto_launch", True),
                rigctld_path=config.get("hamlib_rigctld_path", ""),
                extra_args=config.get("hamlib_extra_args", ""),
            )
            self._hamlib.start()
            self._backend = "hamlib"
            self._enabled = True
            self._shared_hamlib = False
            log.info("PTT controller started (Hamlib rigctld)")
            return True
        except ImportError as e:
            log.warning(f"Hamlib module not available: {e}")
            self.ptt_error.emit(f"Hamlib module error: {e}")
            return False
        except RuntimeError as e:
            log.error(f"Hamlib start failed: {e}")
            self.ptt_error.emit(str(e))
            return False

    def use_hamlib_client(self, client) -> None:
        """Share an existing HamlibClient for PTT (avoids double-launching rigctld).

        The caller owns the client lifecycle — stop() will NOT be called
        on it by the PTT module.
        """
        self._hamlib = client
        self._backend = "hamlib"
        self._enabled = True
        self._shared_hamlib = True
        log.info("PTT controller using shared Hamlib client")

    def start_flrig(self, config) -> bool:
        """Connect to FLrig's XML-RPC server for PTT control.

        Returns True on success, False if FLrig is unavailable.
        """
        try:
            from vara.flrig import FLrigClient
            self._flrig = FLrigClient(
                host=config.get("flrig_host", "127.0.0.1"),
                port=config.get("flrig_port", 12345),
            )
            self._flrig.start()
            self._backend = "flrig"
            self._enabled = True
            self._shared_flrig = False
            log.info("PTT controller started (FLrig XML-RPC)")
            return True
        except ImportError as e:
            log.warning(f"FLrig module not available: {e}")
            self.ptt_error.emit(f"FLrig module error: {e}")
            return False
        except RuntimeError as e:
            log.error(f"FLrig start failed: {e}")
            self.ptt_error.emit(str(e))
            return False

    def use_flrig_client(self, client) -> None:
        """Share an existing FLrigClient for PTT (avoids double-connecting).

        The caller owns the client lifecycle — stop() will NOT be called
        on it by the PTT module.
        """
        self._flrig = client
        self._backend = "flrig"
        self._enabled = True
        self._shared_flrig = True
        log.info("PTT controller using shared FLrig client")

    def stop(self):
        """Release PTT and disconnect from the active backend."""
        import traceback
        caller = ''.join(traceback.format_stack()[-3:-1]).strip()
        log.info(f"PTT stop() called from:\n{caller}")

        self._cancel_watchdog()
        with self._lock:
            if self._ptt_on:
                try:
                    if self._backend == "flrig" and self._flrig:
                        self._flrig.set_ptt(False)
                    elif self._backend == "hamlib" and self._hamlib:
                        self._hamlib.set_ptt(False)
                    elif self._omnirig:
                        self._omnirig.set_ptt(False)
                except Exception as e:
                    log.warning(f"Failed to release PTT during stop: {e}")
                self._ptt_on = False

        if self._omnirig:
            try:
                self._omnirig.stop()
            except Exception:
                pass
            self._omnirig = None

        if self._hamlib:
            if not self._shared_hamlib:
                try:
                    self._hamlib.stop()
                except Exception:
                    pass
            self._hamlib = None
            self._shared_hamlib = False

        if self._flrig:
            if not self._shared_flrig:
                try:
                    self._flrig.stop()
                except Exception:
                    pass
            self._flrig = None
            self._shared_flrig = False

        self._enabled = False
        log.info("PTT controller stopped")

    def on_ptt_event(self, ptt_on: bool):
        """Called when VARA HF sends a PTT ON or PTT OFF event.

        This is connected to the modem's ptt_event signal via
        DirectConnection — runs on the reader thread, not the main
        thread.  Dispatches the actual radio keying to a background
        thread so the reader is never blocked.
        """
        if not self._enabled:
            log.debug(f"PTT {'ON' if ptt_on else 'OFF'} ignored (controller disabled)")
            return

        with self._lock:
            self._ptt_on = ptt_on

        action = "KEYING" if ptt_on else "UNKEYING"
        log.info(f"PTT {action} radio via {self._backend}")

        # Dispatch to background thread
        t = threading.Thread(
            target=self._do_ptt, args=(ptt_on,),
            name="PTT-dispatch", daemon=True)
        t.start()

        self.ptt_changed.emit(ptt_on)

        # Watchdog management
        if ptt_on:
            self._start_watchdog()
        else:
            self._cancel_watchdog()

    def _do_ptt(self, ptt_on: bool):
        """Execute PTT command on a background thread."""
        try:
            if self._backend == "flrig":
                if self._flrig and self._flrig.is_started:
                    log.info(f"Sending set_ptt({ptt_on}) to FLrig...")
                    ok = self._flrig.set_ptt(ptt_on)
                    log.info(f"FLrig set_ptt({ptt_on}) → {'OK' if ok else 'FAILED'}")
                    if not ok:
                        self.ptt_error.emit("FLrig PTT command failed")
                else:
                    started = self._flrig.is_started if self._flrig else 'no client'
                    log.warning(f"FLrig not connected (started={started}) "
                                f"— PTT command dropped")
                    self.ptt_error.emit("FLrig not connected")
            elif self._backend == "hamlib":
                if self._hamlib and self._hamlib.is_started:
                    log.info(f"Sending set_ptt({ptt_on}) to rigctld...")
                    ok = self._hamlib.set_ptt(ptt_on)
                    log.info(f"rigctld set_ptt({ptt_on}) → {'OK' if ok else 'FAILED'}")
                    if not ok:
                        self.ptt_error.emit("Hamlib PTT command failed")
                else:
                    started = self._hamlib.is_started if self._hamlib else 'no client'
                    log.warning(f"Hamlib not connected (started={started}) "
                                f"— PTT command dropped")
                    self.ptt_error.emit("Hamlib rigctld not connected")
            else:
                if self._omnirig and self._omnirig.is_started:
                    log.info(f"Sending set_ptt({ptt_on}) to OmniRig...")
                    ok = self._omnirig.set_ptt(ptt_on)
                    log.info(f"OmniRig set_ptt({ptt_on}) → {'OK' if ok else 'FAILED'}")
                    if not ok:
                        self.ptt_error.emit("OmniRig PTT command failed")
                else:
                    log.warning("OmniRig not connected — PTT command dropped")
                    self.ptt_error.emit("OmniRig not connected")
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
        try:
            if self._backend == "flrig" and self._flrig and self._flrig.is_started:
                self._flrig.set_ptt(False)
            elif self._backend == "hamlib" and self._hamlib and self._hamlib.is_started:
                self._hamlib.set_ptt(False)
            elif self._omnirig and self._omnirig.is_started:
                self._omnirig.set_ptt(False)
        except Exception as e:
            log.error(f"PTT watchdog release error: {e}")

        self.ptt_changed.emit(False)
        self.ptt_error.emit("PTT watchdog: forced release after timeout")

    def get_status_text(self) -> str:
        """Return a human-readable status string for the GUI."""
        if not self._enabled:
            return "PTT: Disabled"
        if self._backend == "flrig":
            if self._flrig and self._flrig.is_started:
                return "PTT: FLrig (XML-RPC)"
            return "PTT: FLrig (not connected)"
        if self._backend == "hamlib":
            if self._hamlib and self._hamlib.is_started:
                return "PTT: Hamlib (rigctld)"
            return "PTT: Hamlib (not connected)"
        else:
            if self._omnirig and self._omnirig.is_started:
                status_name = self._omnirig.get_status_name()
                return f"PTT: OmniRig Rig{self._rig_number} ({status_name})"
            return "PTT: Not connected"
