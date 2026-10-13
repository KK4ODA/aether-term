"""
vara/agwpe_modem.py

Qt wrapper around AGWPEClient that exposes the same signal interface as
VARAModem.  MainWindow can use either transport transparently — just swap
the modem object and reconnect signals.
"""

import logging
import threading
import time
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from vara.connection import ConnectionState
from vara.agwpe import AGWPEClient, AGWPEFrame

log = logging.getLogger(__name__)


class AGWPEModem(QObject):
    """AGWPE/Soundmodem transport with VARAModem-compatible signals."""

    # Signals — same names and types as VARAModem
    state_changed = pyqtSignal(object)        # ConnectionState
    data_received = pyqtSignal(str)            # decoded text from BBS
    raw_data_received = pyqtSignal(bytes)      # raw bytes
    command_event = pyqtSignal(str)            # protocol events
    sn_report = pyqtSignal(str)                # not used for AGWPE
    error_signal = pyqtSignal(str)             # error message
    modem_connected = pyqtSignal()
    rf_connected = pyqtSignal(str)             # remote callsign
    rf_disconnected = pyqtSignal()
    pending_signal = pyqtSignal()
    busy_signal = pyqtSignal()
    ptt_event = pyqtSignal(bool)               # not used for AGWPE

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client: Optional[AGWPEClient] = None
        self._state = ConnectionState.DISCONNECTED
        self._my_call = ""
        self._target = ""
        self._rf_connected = False

    @property
    def state(self) -> ConnectionState:
        return self._state

    def _set_state(self, state: ConnectionState):
        self._state = state
        self.state_changed.emit(state)

    # ── Connection interface (matches VARAModem) ─────────────────────

    def connect_to_modem(self, host: str, cmd_port: int, data_port: int = 0):
        """Connect to the AGWPE server.

        *cmd_port* is the AGWPE TCP port.  *data_port* is ignored
        (AGWPE uses a single TCP connection for everything).
        """
        threading.Thread(
            target=self._do_connect,
            args=(host, cmd_port),
            daemon=True,
            name="AGWPE-Connect",
        ).start()

    def _do_connect(self, host: str, port: int):
        # No DISCONNECTED announcement here: the window reads DISCONNECTED as
        # "the call failed", which cleared its connect-in-progress flag and
        # let the idle-link cleanup race the RF connect.
        client = AGWPEClient(
            host=host, port=port, on_frame=self._on_frame,
        )
        if client.connect(timeout=10.0):
            self._client = client
            self._set_state(ConnectionState.MODEM_CONNECTED)
            self.modem_connected.emit()
            self.command_event.emit(f"AGWPE connected to {host}:{port}")
        else:
            self.error_signal.emit(f"Cannot connect to Soundmodem at {host}:{port}")
            self._set_state(ConnectionState.DISCONNECTED)

    def initialize_modem(self, callsign: str, is_hf: bool = False,
                         bandwidth: int = 0, query_version: bool = False):
        """Register callsign with the TNC.

        Takes the same arguments as ``VARAModem.initialize_modem``;
        *is_hf*, *bandwidth* and *query_version* mean nothing to AGWPE.
        Like the VARA modem it reports INITIALIZING, then MODEM_CONNECTED
        when done — the main window sends the RF connect on that.
        """
        self._set_state(ConnectionState.INITIALIZING)
        self._my_call = callsign.upper()
        if self._client:
            self._client.register_callsign(self._my_call)
            self.command_event.emit(f"Registered callsign {self._my_call}")
        self._set_state(ConnectionState.MODEM_CONNECTED)

    def rf_connect(self, my_call: str, target: str,
                   via1: str = "", via2: str = ""):
        """Initiate AX.25 connection to a remote station.

        *via1* and *via2* are ignored — AGWPE routing uses its own
        digipeater configuration.
        """
        self._my_call = my_call.upper()
        self._target = target.upper()
        self._set_state(ConnectionState.CONNECTING)
        self.pending_signal.emit()
        self.command_event.emit(f"CONNECT {self._my_call} {self._target}")

        if self._client:
            self._client.connect_station(self._my_call, self._target)

        # Timeout thread — if no 'C' frame in 30s, fail
        threading.Thread(
            target=self._connect_timeout,
            daemon=True,
            name="AGWPE-Timeout",
        ).start()

    def _connect_timeout(self):
        time.sleep(30.0)
        if self._state == ConnectionState.CONNECTING:
            self.error_signal.emit("AGWPE connection timeout (30s)")
            self._set_state(ConnectionState.MODEM_CONNECTED)

    def rf_disconnect(self):
        """Disconnect the AX.25 session."""
        if self._client and self._rf_connected:
            self._client.disconnect_station(self._my_call, self._target)
            self._set_state(ConnectionState.DISCONNECTING)
            self.command_event.emit("DISCONNECT sent")

    def send_data(self, text: str):
        """Send text data over the AX.25 connection."""
        if self._client and self._rf_connected:
            data = text.encode("utf-8")
            self._client.send_connected_data(
                self._my_call, self._target, data,
            )

    def send_data_bytes(self, data: bytes):
        """Send raw bytes over the AX.25 connection."""
        if self._client and self._rf_connected:
            self._client.send_connected_data(
                self._my_call, self._target, data,
            )

    def disconnect_from_modem(self):
        """Close the entire AGWPE TCP connection."""
        if self._client:
            if self._rf_connected:
                self._client.disconnect_station(self._my_call, self._target)
            self._client.unregister_callsign(self._my_call)
            self._client.disconnect()
            self._client = None
        self._rf_connected = False
        self._set_state(ConnectionState.DISCONNECTED)

    # ── Frame handler ────────────────────────────────────────────────

    def _on_frame(self, frame: AGWPEFrame):
        """Called from the AGWPE reader thread for every received frame."""
        if frame.data_kind == "C" and not self._rf_connected:
            # AX.25 connection established
            self._rf_connected = True
            remote = frame.call_from if frame.call_from != self._my_call else frame.call_to
            self._target = remote
            self._set_state(ConnectionState.CONNECTED)
            self.rf_connected.emit(remote)
            self.command_event.emit(f"CONNECTED {self._my_call} {remote}")
            log.info(f"AGWPE connected to {remote}")

        elif frame.data_kind == "D":
            # Data from remote station
            text = frame.data.decode("utf-8", errors="replace")
            self.data_received.emit(text)
            self.raw_data_received.emit(frame.data)

        elif frame.data_kind == "d":
            # Remote station disconnected
            self._rf_connected = False
            self._set_state(ConnectionState.MODEM_CONNECTED)
            self.rf_disconnected.emit()
            self.command_event.emit("DISCONNECTED")
            log.info("AGWPE RF session disconnected")

        elif frame.data_kind == "g":
            # Port info response
            info = frame.data.decode("utf-8", errors="replace")
            self.command_event.emit(f"Port info: {info}")
