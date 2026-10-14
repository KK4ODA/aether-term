"""
vara/agwpe_modem.py

Qt wrapper around AGWPEClient that exposes the same signal interface as
VARAModem.  MainWindow can use either transport transparently — just swap
the modem object and reconnect signals.
"""

import codecs
import logging
import threading
from typing import Optional

from PyQt6.QtCore import QObject, pyqtSignal

from vara.connection import ConnectionState
from vara.agwpe import AGWPEClient, AGWPEFrame

log = logging.getLogger(__name__)

# How long an AX.25 connect may take before it is cancelled.  A call
# through a digipeater at 1200 baud, with retries, can take a while.
CONNECT_TIMEOUT = 60.0


class AGWPEModem(QObject):
    """AGWPE/Soundmodem transport with VARAModem-compatible signals."""

    # Signals — same names and types as VARAModem
    state_changed = pyqtSignal(object)        # ConnectionState
    data_received = pyqtSignal(str)            # decoded text from BBS
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
        self.connected_via: list = []      # digipeaters of the current call
        self._call_id = 0                  # which connect a timeout belongs to
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

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
            on_lost=self._on_link_lost,
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
                         bandwidth: int = 0, query_version: bool = False,
                         **_unused):
        """Register callsign with the TNC.

        Takes the same arguments as ``VARAModem.initialize_modem``;
        *is_hf*, *bandwidth* and *query_version* mean nothing to AGWPE.
        Like the VARA modem it reports INITIALIZING, then MODEM_CONNECTED
        when done — the main window sends the RF connect on that.
        """
        self._set_state(ConnectionState.INITIALIZING)
        self._my_call = callsign.upper()
        client = self._client
        if client:
            client.register_callsign(self._my_call)
            self.command_event.emit(f"Registered callsign {self._my_call}")
        self._set_state(ConnectionState.MODEM_CONNECTED)

    def rf_connect(self, my_call: str, target: str,
                   via1: str = "", via2: str = ""):
        """Initiate an AX.25 connection to a remote station.

        With *via1* / *via2* the call goes through those digipeaters
        (AGWPE 'v' frame); Soundmodem's own Digi settings are for it
        acting as a digipeater, not for the path of our calls.
        """
        self._my_call = my_call.upper()
        self._target = target.upper()
        digis = [d.upper() for d in (via1, via2) if d]
        self.connected_via = digis
        self._set_state(ConnectionState.CONNECTING)
        self.pending_signal.emit()
        path = f" VIA {' '.join(digis)}" if digis else ""
        self.command_event.emit(f"CONNECT {self._my_call} {self._target}{path}")

        client = self._client
        if client:
            if digis:
                client.connect_station_via(self._my_call, self._target, digis)
            else:
                client.connect_station(self._my_call, self._target)

        # No 'C' frame in time: cancel the call.  The timer belongs to this
        # call only — a later call must not be failed by it.
        self._call_id += 1
        timer = threading.Timer(CONNECT_TIMEOUT, self._connect_timeout,
                                args=(self._call_id,))
        timer.daemon = True
        timer.start()

    def _connect_timeout(self, call_id: int):
        if call_id != self._call_id or self._state != ConnectionState.CONNECTING:
            return
        # Stop Soundmodem calling on the air, then give up
        client = self._client
        if client:
            client.disconnect_station(self._my_call, self._target)
        self.error_signal.emit(
            f"No answer from {self._target} in {CONNECT_TIMEOUT:.0f} s — call cancelled")
        self._set_state(ConnectionState.MODEM_CONNECTED)

    def _on_link_lost(self):
        """Soundmodem closed the TCP link (it quit or crashed)."""
        self._client = None
        self._rf_connected = False
        self._call_id += 1
        self._set_state(ConnectionState.DISCONNECTED)
        self.error_signal.emit("Lost connection to Soundmodem")

    def rf_disconnect(self):
        """Disconnect the AX.25 session."""
        client = self._client
        if client and self._rf_connected:
            client.disconnect_station(self._my_call, self._target)
            self._set_state(ConnectionState.DISCONNECTING)
            self.command_event.emit("DISCONNECT sent")

    def send_data(self, text: str):
        """Send text data over the AX.25 connection."""
        client = self._client
        if client and self._rf_connected:
            client.send_connected_data(
                self._my_call, self._target, text.encode("utf-8"))
        else:
            log.warning(f"AGWPE data not sent (no link): {text[:80]!r}")

    def disconnect_from_modem(self):
        """Close the entire AGWPE TCP connection."""
        # Taken once: the reader thread clears _client if Soundmodem goes away
        client, self._client = self._client, None
        if client:
            # Also a call still being placed: Soundmodem would go on
            # calling on the air, and might connect with nobody here.
            if self._rf_connected or self._state == ConnectionState.CONNECTING:
                client.disconnect_station(self._my_call, self._target)
            client.unregister_callsign(self._my_call)
            client.disconnect()
        self._rf_connected = False
        self._call_id += 1
        self._set_state(ConnectionState.DISCONNECTED)

    # ── Frame handler ────────────────────────────────────────────────

    def _on_frame(self, frame: AGWPEFrame):
        """Called from the AGWPE reader thread for every received frame."""
        if frame.data_kind == "C" and not self._rf_connected:
            # AX.25 connection established
            self._rf_connected = True
            self._decoder.reset()
            remote = frame.call_from if frame.call_from != self._my_call else frame.call_to
            self._target = remote
            self._set_state(ConnectionState.CONNECTED)
            self.rf_connected.emit(remote)
            self.command_event.emit(f"CONNECTED {self._my_call} {remote}")
            log.info(f"AGWPE connected to {remote}")

        elif frame.data_kind == "D":
            # Data from remote station
            # A UTF-8 character can be split between two AX.25 frames
            text = self._decoder.decode(frame.data)
            if text:
                self.data_received.emit(text)

        elif frame.data_kind == "d":
            # Remote station disconnected
            self._rf_connected = False
            self._set_state(ConnectionState.MODEM_CONNECTED)
            self.rf_disconnected.emit()
            self.command_event.emit("DISCONNECTED")
            log.info("AGWPE RF session disconnected")
