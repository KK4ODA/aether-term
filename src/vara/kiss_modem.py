"""
vara/kiss_modem.py — a KISS TNC as Aether Term's modem.

For a radio with a built-in KISS TNC (Kenwood TH-D74/D75 over Bluetooth
or USB, Bluetooth LE radios and TNCs, Direwolf over TCP).  A KISS TNC
only sends and receives single AX.25 frames, so the connection itself —
the call, numbered frames, acknowledgements, retries — is run here by
ax25.link.DataLink, the way Soundmodem runs it for the Soundmodem mode.

It has the VARAModem methods and signals, so the session code above it
(login, ;TRANSPORT, macros, profiles, digipeaters) is the same as for
every other mode.  Extra signal:
    tnc_status(str)   — the link to the TNC, for the status bar
"""

import codecs
import logging
import threading
from typing import List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from ax25 import kiss
from ax25.frame import Address, Frame, FrameError
from ax25.link import DataLink, LinkListener, LinkParams, LinkState
from tnc.transports import Transport, TransportError
from vara.connection import ConnectionState

log = logging.getLogger(__name__)
frames_log = logging.getLogger("ax25.frames")


def link_params(config) -> LinkParams:
    return LinkParams(
        paclen=max(16, min(256, int(config.get("ax25_paclen", 128)))),
        maxframe=max(1, min(7, int(config.get("ax25_maxframe", 4)))),
        frack=max(1.0, float(config.get("ax25_frack", 7))),
        retries=max(1, min(30, int(config.get("ax25_retries", 10)))),
    )


class KissModem(QObject, LinkListener):
    state_changed = pyqtSignal(object)
    data_received = pyqtSignal(str)
    command_event = pyqtSignal(str)
    sn_report = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    modem_connected = pyqtSignal()
    rf_connected = pyqtSignal(str)
    rf_disconnected = pyqtSignal()
    pending_signal = pyqtSignal()
    busy_signal = pyqtSignal()
    ptt_event = pyqtSignal(bool)
    tnc_status = pyqtSignal(str)

    def __init__(self, transport: Transport, params: Optional[LinkParams] = None,
                 kiss_port: int = 0, tnc_setup: bytes = b"", parent=None):
        super().__init__(parent)
        self.transport = transport
        self.params = params or LinkParams()
        self.kiss_port = kiss_port
        self.tnc_setup = tnc_setup             # bytes sent once the TNC link is open
        self._state = ConnectionState.DISCONNECTED
        self._link: Optional[DataLink] = None
        self._open = False
        self._write_lock = threading.Lock()
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._kiss = kiss.Decoder(self._on_kiss_frame)
        self._my_call = ""
        self.connected_via: List[str] = []

    @classmethod
    def from_config(cls, config) -> "KissModem":
        from tnc.transports import make_transport
        setup = b""
        init = str(config.get("kiss_init", "")).strip()
        if init:
            # Text commands that put a TNC2-style TNC into KISS mode
            setup += init.replace("\\r", "\r").replace("\n", "\r").encode("ascii", "replace")
            if not setup.endswith(b"\r"):
                setup += b"\r"
        port = int(config.get("kiss_port", 0))
        if config.get("kiss_send_params", True):
            setup += kiss.tnc_parameters(int(config.get("kiss_txdelay", 300)),
                                         int(config.get("kiss_persistence", 63)),
                                         int(config.get("kiss_slottime", 100)), port)
        return cls(make_transport(config), link_params(config), port, setup)

    @property
    def state(self) -> ConnectionState:
        return self._state

    def _set_state(self, state: ConnectionState) -> None:
        self._state = state
        self.state_changed.emit(state)

    # ── the link to the TNC ────────────────────────────────────────

    def connect_to_modem(self, *_args, **_kwargs) -> None:
        threading.Thread(target=self._open_tnc, daemon=True, name="TNC-open").start()

    def _open_tnc(self) -> None:
        what = self.transport.describe()
        self.tnc_status.emit(f"TNC: opening {what}...")
        try:
            self.transport.open(self._on_bytes, self._on_lost)
        except TransportError as e:
            self.tnc_status.emit("TNC: not connected")
            self.error_signal.emit(f"TNC: {e}")
            self._set_state(ConnectionState.DISCONNECTED)
            return
        self._open = True
        try:
            if self.tnc_setup:
                self._write(self.tnc_setup)
        except OSError as e:
            log.warning("TNC setup not sent: %s", e)
        self.tnc_status.emit(f"TNC: {what}")
        self.command_event.emit(f"TNC open: {what}")
        self._set_state(ConnectionState.MODEM_CONNECTED)
        self.modem_connected.emit()

    def _write(self, data: bytes) -> None:
        with self._write_lock:
            self.transport.write(data)

    def _on_bytes(self, data: bytes) -> None:
        self._kiss.feed(data)

    def _on_kiss_frame(self, port: int, payload: bytes) -> None:
        if port != self.kiss_port:
            return
        try:
            frame = Frame.decode(payload)
        except FrameError as e:
            frames_log.debug("RX undecodable frame (%s): %s", e, payload[:40].hex())
            return
        frames_log.info("RX %s", frame)
        link = self._link
        if link is not None:
            link.receive(frame)

    def _send_frame(self, frame: Frame) -> None:
        frames_log.info("TX %s", frame)
        try:
            self._write(kiss.encode(frame.encode(), self.kiss_port))
        except OSError as e:
            log.warning("TNC write failed: %s", e)

    def _on_lost(self, why: str) -> None:
        """The TNC link went away by itself."""
        self._open = False
        was_up = self._state == ConnectionState.CONNECTED
        self._stop_link()
        self.tnc_status.emit("TNC: not connected")
        self.error_signal.emit(f"Lost the TNC ({self.transport.describe()}): {why}")
        if was_up:
            self.rf_disconnected.emit()
        self._set_state(ConnectionState.DISCONNECTED)

    # ── the call (VARAModem interface) ─────────────────────────────

    def initialize_modem(self, callsign: str, *_args, **_kwargs) -> None:
        self._set_state(ConnectionState.INITIALIZING)
        try:
            me = Address.parse(callsign)
        except ValueError as e:
            self.error_signal.emit(f"TNC: {e}")
            self._set_state(ConnectionState.MODEM_CONNECTED)
            return
        self._my_call = str(me)
        self._stop_link()
        self._link = DataLink(me, self._send_frame, self, self.params)
        self._link.start()
        self._set_state(ConnectionState.MODEM_CONNECTED)

    def rf_connect(self, my_call: str, target: str, via1: str = "", via2: str = "") -> None:
        link = self._link
        try:
            remote = Address.parse(target)
            digis = [Address.parse(d) for d in (via1, via2) if d]
        except ValueError as e:
            self.error_signal.emit(f"TNC: {e}")
            self._set_state(ConnectionState.MODEM_CONNECTED)
            return
        if link is None or not self._open:
            self.error_signal.emit("TNC: not connected")
            self._set_state(ConnectionState.DISCONNECTED)
            return
        self.connected_via = [str(d) for d in digis]
        self._decoder.reset()
        self._set_state(ConnectionState.CONNECTING)
        self.pending_signal.emit()
        path = f" VIA {' '.join(self.connected_via)}" if digis else ""
        self.command_event.emit(f"CONNECT {link.me} {remote}{path}")
        link.connect(remote, digis)

    def rf_disconnect(self) -> None:
        link = self._link
        if link is not None and self._state in (ConnectionState.CONNECTED,
                                                ConnectionState.CONNECTING):
            self._set_state(ConnectionState.DISCONNECTING)
            link.disconnect()

    def send_data(self, text: str) -> None:
        link = self._link
        if link is None or self._state != ConnectionState.CONNECTED:
            log.warning("TNC: data not sent (no link): %r", text[:80])
            return
        link.send(text.encode("utf-8"))

    def disconnect_from_modem(self) -> None:
        link = self._link
        busy = (LinkState.CONNECTED, LinkState.TIMER_RECOVERY, LinkState.CONNECTING)
        if link is not None and link.state in busy:
            # A call in progress is ended too: the other station may have
            # answered it.  Let the DISC go out before the TNC link closes.
            link.disconnect()
            for _ in range(20):
                if link.state not in busy:
                    break
                threading.Event().wait(0.05)
        self._stop_link()
        if self._open:
            self._open = False
            try:
                self.transport.close()
            except Exception as e:                       # noqa: BLE001
                log.warning("TNC close failed: %s", e)
            self.tnc_status.emit("TNC: not connected")
        if self._state != ConnectionState.DISCONNECTED:
            self._set_state(ConnectionState.DISCONNECTED)

    def _stop_link(self) -> None:
        link, self._link = self._link, None
        if link is not None:
            link.stop()

    # ── the data link's reports (its thread) ───────────────────────

    def link_connected(self, remote: Address, digis: List[Address]) -> None:
        self.connected_via = [str(d) for d in digis]
        self._set_state(ConnectionState.CONNECTED)
        self.rf_connected.emit(f"{self._my_call} {remote}")
        self.command_event.emit(f"CONNECTED {self._my_call} {remote}")

    def link_data(self, data: bytes) -> None:
        text = self._decoder.decode(data)
        if text:
            self.data_received.emit(text)

    def link_disconnected(self, reason: str) -> None:
        self.command_event.emit(f"DISCONNECTED ({reason})")
        if self._state != ConnectionState.DISCONNECTED:
            self._set_state(ConnectionState.MODEM_CONNECTED)
        self.rf_disconnected.emit()

    def link_failed(self, reason: str) -> None:
        if reason != "call cancelled":
            self.error_signal.emit(f"TNC: {reason}")
        if self._state != ConnectionState.DISCONNECTED:
            self._set_state(ConnectionState.MODEM_CONNECTED)
