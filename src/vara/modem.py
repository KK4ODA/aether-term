"""
vara/modem.py — VARA-protocol modem TCP interface for Aether Term (client side).

Manages the two TCP connections (command + data) to a modem speaking the
published VARA TCP host interface: VARA FM, VARA HF, or Aether HF (whose
VARA-compatible port is the same command set — see
https://github.com/KK4ODA/aether-hf/blob/master/docs/spec/host-interfaces.md).
Uses Qt signals to communicate events back to the GUI thread.
"""

import re
import socket
import logging
import threading
import time
from typing import List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from vara.connection import ConnectionState

log = logging.getLogger(__name__)

CONNECT_TIMEOUT = 10  # seconds

# VARA FM routes through at most two digipeaters
# ("CONNECT Source Destination VIA Digi1 Digi2<cr>" in the VARA TNC
# command reference).  Calls are 3-7 of A-Z/0-9 with an optional SSID
# of -1..-15, -T or -R.
MAX_DIGIPEATERS = 2
_CALLSIGN_RE = re.compile(r"^[A-Z0-9]{3,7}(-([1-9]|1[0-5]|T|R))?$")


def parse_digipeaters(*fields: str) -> List[str]:
    """Turn the Via entry fields into a validated digipeater list.

    Each field may hold one call or several separated by spaces or
    commas ("W1AW-5,K1ABC"); empty fields are skipped, so a call typed
    only in Via 2 still lands in the path.  Raises ValueError with an
    operator-facing message for a bad call or too many hops.
    """
    digis = []
    for field in fields:
        digis += [t for t in re.split(r"[\s,]+", (field or "").upper()) if t]
    for call in digis:
        if not _CALLSIGN_RE.match(call):
            raise ValueError(f"'{call}' is not a valid digipeater callsign.")
    if len(digis) > MAX_DIGIPEATERS:
        raise ValueError(
            f"At most {MAX_DIGIPEATERS} digipeaters (Via 1 and Via 2) "
            f"— {len(digis)} given.")
    return digis


class VARAModem(QObject):
    """Client-side VARA-protocol modem interface (VARA FM/HF, Aether HF).

    Signals (all emitted from background threads — connect with Qt.QueuedConnection):
        state_changed(ConnectionState)
        data_received(str)          — decoded text from data socket
        command_event(str)          — raw event line from command socket
        sn_report(str)              — S/N value string
        error(str)                  — error message
        modem_connected()           — TCP link to modem established
        rf_connected(str)           — RF session established (remote callsign)
        rf_disconnected()           — RF session dropped
        pending()                   — connect attempt pending
        bitrate_report(str)         — link speed, from BITRATE (<mode>) <bps> BPS
        session_bandwidth(str)      — bandwidth reported with CONNECTED (Aether HF)
        version_report(str)         — the modem's answer to VERSION
    """

    state_changed = pyqtSignal(object)        # ConnectionState
    data_received = pyqtSignal(str)            # decoded text from BBS
    command_event = pyqtSignal(str)            # raw VARA event
    sn_report = pyqtSignal(str)                # S/N dB value
    error_signal = pyqtSignal(str)             # error message
    modem_connected = pyqtSignal()
    rf_connected = pyqtSignal(str)             # remote callsign
    rf_disconnected = pyqtSignal()
    pending_signal = pyqtSignal()
    busy_signal = pyqtSignal()
    ptt_event = pyqtSignal(bool)               # PTT ON (True) / PTT OFF (False) — HF only
    bitrate_report = pyqtSignal(str)           # e.g. "1234 bps (mode 9)"
    session_bandwidth = pyqtSignal(str)        # e.g. "2300"
    version_report = pyqtSignal(str)           # e.g. "Aether HF 0.2.0-beta.102"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cmd_sock: Optional[socket.socket] = None
        self._data_sock: Optional[socket.socket] = None
        self._state = ConnectionState.DISCONNECTED
        self._stop = threading.Event()
        self._cmd_buf = ""
        self._init_cleanup = False       # True while sending cleanup DISCONNECT
        self._init_ack: Optional[threading.Event] = None  # set when VARA acks cleanup
        self._last_cmd: Optional[str] = None  # most recent command sent (for WRONG correlation)
        self.connected_via: List[str] = []  # digipeaters named in the last CONNECTED

    @property
    def state(self) -> ConnectionState:
        return self._state

    def _set_state(self, new_state: ConnectionState):
        self._state = new_state
        self.state_changed.emit(new_state)

    # ── Connect to modem TCP ports ─────────────────────────────────

    def connect_to_modem(self, host: str, cmd_port: int, data_port: int):
        """Connect TCP sockets to the VARA modem. Runs in a background thread."""
        self._stop.clear()
        t = threading.Thread(target=self._do_connect,
                             args=(host, cmd_port, data_port),
                             daemon=True, name="ModemConnect")
        t.start()

    def _do_connect(self, host: str, cmd_port: int, data_port: int,
                    max_retries: int = 5, retry_delay: float = 2.0):
        log.info(f"Connecting to modem at {host}:{cmd_port}/{data_port}")
        for attempt in range(1, max_retries + 1):
            if self._stop.is_set():
                return
            try:
                self._cmd_sock = socket.create_connection(
                    (host, cmd_port), timeout=CONNECT_TIMEOUT)
                self._data_sock = socket.create_connection(
                    (host, data_port), timeout=CONNECT_TIMEOUT)
                self._cmd_sock.settimeout(None)
                self._data_sock.settimeout(None)
                log.info("TCP connection to modem established")
                self._set_state(ConnectionState.MODEM_CONNECTED)
                self.modem_connected.emit()
                self._start_reader_threads()
                return
            except OSError as e:
                if attempt < max_retries:
                    log.warning(
                        f"Modem connect attempt {attempt}/{max_retries} "
                        f"failed: {e} — retry in {retry_delay:.0f}s"
                    )
                    self._stop.wait(timeout=retry_delay)
                else:
                    msg = f"Cannot connect to modem at {host}:{cmd_port} — {e}"
                    log.error(msg)
                    self.error_signal.emit(msg)
                    self._set_state(ConnectionState.DISCONNECTED)

    def _start_reader_threads(self):
        threading.Thread(target=self._cmd_reader, daemon=True,
                         name="CmdReader").start()
        threading.Thread(target=self._data_reader, daemon=True,
                         name="DataReader").start()

    # ── Initialization sequence ────────────────────────────────────

    def initialize_modem(self, callsign: str, is_hf: bool,
                         bandwidth: int = 500, query_version: bool = False,
                         session: str = "", **_unused):
        """Send the VARA initialization commands. Call after modem_connected.

        *session* ("P2P" / "WINLINK") goes out as ``<session> SESSION``
        (VARA HF only).  Unknown keyword arguments are ignored, so the
        window can pass every modem the same ones.
        """
        t = threading.Thread(target=self._do_init,
                             args=(callsign, is_hf, bandwidth, query_version,
                                   session),
                             daemon=True, name="ModemInit")
        t.start()

    def _do_init(self, callsign: str, is_hf: bool, bandwidth: int,
                 query_version: bool = False, session: str = ""):
        self._set_state(ConnectionState.INITIALIZING)
        try:
            time.sleep(0.3)

            # 0. Cleanup — abort any leftover connection state from a prior
            #    session.  VARA will respond with WRONG (if nothing pending),
            #    DISCONNECTED, or PTT OFF; Aether HF answers OK and ends
            #    nothing it did not start.  All are harmless and suppressed
            #    by the _init_cleanup flag so they don't confuse the UI.
            self._init_cleanup = True
            self._init_ack = threading.Event()
            try:
                self._send_cmd("DISCONNECT")
                self._init_ack.wait(timeout=2.0)
            finally:
                self._init_cleanup = False
                self._init_ack = None

            # 1. Register callsign
            self._send_cmd(f"MYCALL {callsign}")
            time.sleep(1.0)

            # 2. Disable compression
            self._send_cmd("COMPRESSION OFF")
            time.sleep(1.0)

            # 3. HF bandwidth
            if is_hf and bandwidth in (500, 2300, 2750):
                self._send_cmd(f"BW{bandwidth}")
                time.sleep(1.0)

            # 3b. VARA HF retry cycle: P2P for a BBS/station, WINLINK for
            #     a Winlink gateway (VARA's TNC command reference)
            if session:
                self._send_cmd(f"{session} SESSION")
                time.sleep(0.3)

            # 4. Ask which modem this is — Aether HF answers
            #    "VERSION Aether HF <version>", so a VARA modem left on the
            #    same port is caught before anything is transmitted.
            if query_version:
                self._send_cmd("VERSION")
                time.sleep(0.3)

            self._set_state(ConnectionState.MODEM_CONNECTED)
            log.info("Modem initialized successfully")
        except Exception as e:
            log.error(f"Init failed: {e}")
            self.error_signal.emit(f"Modem initialization failed: {e}")

    # ── RF Connect / Disconnect ────────────────────────────────────

    def rf_connect(self, my_call: str, target: str,
                   via1: str = "", via2: str = ""):
        """Initiate an RF connection to the target station.

        Digipeaters (VARA FM only) go out as
        ``CONNECT <my_call> <target> VIA <digi1> [<digi2>]``.
        """
        cmd = f"CONNECT {my_call} {target}"
        digis = parse_digipeaters(via1, via2)
        if digis:
            cmd += " VIA " + " ".join(digis)
        self._set_state(ConnectionState.CONNECTING)
        self._send_cmd(cmd)

    def rf_disconnect(self):
        """Request RF disconnection."""
        self._set_state(ConnectionState.DISCONNECTING)
        self._send_cmd("DISCONNECT")

    # ── Send data over RF ──────────────────────────────────────────

    def send_data(self, text: str):
        """Send text data on the data socket (goes over RF)."""
        if self._data_sock is None:
            log.warning("send_data called but data socket not connected")
            return
        try:
            data = text.encode("utf-8")
            self._data_sock.sendall(data)
            log.info(f"Data TX: {len(data)} bytes -> data socket: {data[:80]!r}")
        except OSError as e:
            log.error(f"Data send error: {e}")
            self.error_signal.emit(f"Data send error: {e}")

    # ── Disconnect from modem ──────────────────────────────────────

    def disconnect_from_modem(self):
        """Cleanly close all TCP connections to the modem."""
        self._stop.set()
        # If RF session is active, send DISCONNECT first
        if self._state == ConnectionState.CONNECTED:
            try:
                self._send_cmd("DISCONNECT")
                time.sleep(0.3)
            except Exception:
                pass
        self._close_sockets()
        self._set_state(ConnectionState.DISCONNECTED)

    def _close_sockets(self):
        for sock in (self._cmd_sock, self._data_sock):
            if sock:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    sock.close()
                except Exception:
                    pass
        self._cmd_sock = None
        self._data_sock = None

    # ── Internal: command sending ──────────────────────────────────

    def _send_cmd(self, cmd: str):
        if self._cmd_sock is None:
            log.warning(f"send_cmd called but not connected: {cmd}")
            return
        try:
            self._last_cmd = cmd
            # VARA commands end in a bare CR ("<cr>" in the TNC command
            # reference); a trailing LF would lead the next command.
            self._cmd_sock.sendall((cmd + "\r").encode("ascii"))
            log.info(f"CMD> {cmd}")
        except OSError as e:
            log.error(f"Command send error: {e}")
            self._handle_tcp_error()

    # ── Internal: background readers ───────────────────────────────

    def _cmd_reader(self):
        """Read and parse events from the command socket."""
        while not self._stop.is_set():
            try:
                chunk = self._cmd_sock.recv(1024)
                if not chunk:
                    break
                self._cmd_buf += chunk.decode("ascii", errors="replace")
                self._cmd_buf = self._cmd_buf.replace("\r\n", "\n").replace("\r", "\n")
                while "\n" in self._cmd_buf:
                    line, self._cmd_buf = self._cmd_buf.split("\n", 1)
                    line = line.strip()
                    if line:
                        log.debug(f"EVT< {line}")
                        self._handle_event(line)
            except OSError:
                break
        if not self._stop.is_set():
            self._handle_tcp_error()

    def _data_reader(self):
        """Read data from the data socket and emit signals."""
        while not self._stop.is_set():
            try:
                data = self._data_sock.recv(4096)
                if not data:
                    break
                try:
                    text = data.decode("utf-8", errors="replace")
                    self.data_received.emit(text)
                except Exception:
                    pass
            except OSError:
                break

    # ── Event parsing ──────────────────────────────────────────────

    def _handle_event(self, event: str):
        """Parse a VARA modem event and emit appropriate signals."""
        upper = event.upper()

        # During init cleanup, suppress the expected WRONG/DISCONNECTED/PTT
        # responses from the cleanup DISCONNECT command.
        if self._init_cleanup:
            if upper in ("WRONG", "DISCONNECTED", "OK") or upper.startswith("PTT"):
                log.debug(f"Init cleanup — suppressed: {event}")
                if self._init_ack:
                    self._init_ack.set()
                return

        self.command_event.emit(event)

        if upper.startswith("CONNECTED"):
            parts = event.split()
            # VARA may send "CONNECTED <call1> <call2> [WIDE]"; Aether HF
            # sends "CONNECTED <caller> <called> <bandwidth>"; VARA FM
            # through digipeaters sends
            # "CONNECTED <src> <dst> via <digi1> [<digi2>] <bw>".
            # The order of local/remote varies between VARA versions.
            # We store both and let the main window figure out which is
            # the remote based on our own callsign.
            call1 = parts[1] if len(parts) >= 2 else "UNKNOWN"
            call2 = parts[2] if len(parts) >= 3 else ""
            rest = parts[3:]
            bw = ""
            if rest and (rest[-1].isdigit()
                         or rest[-1].upper() in ("WIDE", "NARROW")):
                bw = rest.pop()
            if rest and rest[0].upper() == "VIA":
                rest = rest[1:]
            self.connected_via = rest[:MAX_DIGIPEATERS]
            if bw:
                self.session_bandwidth.emit(bw)
            self._set_state(ConnectionState.CONNECTED)
            self.rf_connected.emit(f"{call1} {call2}".strip())
            log.info(f"RF session connected: {call1} {call2}")

        elif upper.startswith("DISCONNECTED"):
            self.connected_via = []
            self._set_state(ConnectionState.MODEM_CONNECTED)
            self.rf_disconnected.emit()
            log.info("RF session disconnected")

        elif upper == "PENDING":
            self.pending_signal.emit()
            log.info("Connection pending...")

        elif upper == "CANCELPENDING":
            self._set_state(ConnectionState.MODEM_CONNECTED)
            log.info("Connection attempt cancelled")

        elif upper == "BUSY":
            self.busy_signal.emit()
            log.info("Remote station busy")

        elif upper.startswith("BITRATE"):
            # "BITRATE (<mode>) <bps> BPS"
            parts = event.replace("(", " ").replace(")", " ").split()
            nums = [p for p in parts[1:] if p.isdigit()]
            if len(nums) >= 2:
                self.bitrate_report.emit(f"{nums[1]} bps (mode {nums[0]})")
            elif nums:
                self.bitrate_report.emit(f"{nums[0]} bps")

        elif upper.startswith("VERSION"):
            self.version_report.emit(event[len("VERSION"):].strip())

        elif upper == "PTT ON":
            self.ptt_event.emit(True)
            log.debug("PTT ON event from modem")

        elif upper == "PTT OFF":
            self.ptt_event.emit(False)
            log.debug("PTT OFF event from modem")

        elif upper.startswith("SN"):
            parts = event.split()
            if len(parts) >= 2:
                self.sn_report.emit(parts[1])

        elif upper == "WRONG":
            cmd_hint = f" (cmd: {self._last_cmd})" if self._last_cmd else ""
            log.warning(f"Modem rejected command with WRONG{cmd_hint}")
            # A rejected CONNECT never gets a DISCONNECTED — end the
            # attempt here so the app does not sit in CONNECTING.
            if (self._state == ConnectionState.CONNECTING
                    and (self._last_cmd or "").upper().startswith("CONNECT")):
                self._set_state(ConnectionState.MODEM_CONNECTED)

        elif upper == "OK":
            log.debug("Modem acknowledged command OK")

        elif upper == "IAMALIVE":
            pass  # keepalive, ignore

    def _handle_tcp_error(self):
        """Handle TCP connection loss to the modem."""
        log.error("Lost TCP connection to modem")
        self._close_sockets()
        self._set_state(ConnectionState.DISCONNECTED)
        self.error_signal.emit("Lost connection to modem")
