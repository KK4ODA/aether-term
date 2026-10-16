"""
vara/local_test.py — Local test mode: talk to the BBS on this PC, no radio.

The Aether BBS reaches VARA FM through VARA's TCP host interface: it
connects to the modem's command and data ports.  In local test mode
Aether Term plays that modem.  It listens on 127.0.0.1 only, and a BBS
instance set up for local test (Transport VARA FM, Host 127.0.0.1, these
ports) attaches to it.  Pressing Connect then reports an inbound call
from you to the BBS, and the session runs over the data port exactly as
it would over the air.

To the main window this is one more modem: it has the VARAModem methods
and signals, so the session code above it is the same.

On the command port (ASCII lines; VARA ends its own with CR, the BBS's
may end in CR, LF or CR LF):
    BBS → us                      us → BBS
    MYCALL <call>                 OK            (the BBS's callsign noted)
    VERSION                       VERSION Aether Term local test
    DISCONNECT / ABORT            DISCONNECTED  (in a session, else OK)
    anything else                 OK            (never WRONG: the BBS
                                                 logs that as an error)
    Connect pressed:              CONNECTED <mycall> <bbscall> 25000
    data from the BBS:            BUFFER 0      (VARA reports its buffer)
    Disconnect pressed:           DISCONNECTED
"""

import codecs
import logging
import os
import select
import socket
import threading
from typing import List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from vara.connection import ConnectionState

log = logging.getLogger(__name__)

LISTEN_HOST = "127.0.0.1"          # never reachable from another machine
VERSION_REPLY = "VERSION Aether Term local test"
LINK_BANDWIDTH = "25000"           # what VARA FM wide reports with CONNECTED
POLL = 0.5                         # how often blocked threads check for stop


class LocalTestModem(QObject):
    """A VARA FM host interface for a BBS on this PC (local test mode).

    Signals (emitted from background threads — connect with
    Qt.QueuedConnection), the VARAModem ones plus:
        bbs_status(bool, str)   — the BBS attached (True) or not, and a
                                  one-line description for the status bar
    """

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
    bbs_status = pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = ConnectionState.DISCONNECTED
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._servers: List[socket.socket] = []
        self._thread: Optional[threading.Thread] = None
        self._cmd: Optional[socket.socket] = None     # the attached BBS
        self._data: Optional[socket.socket] = None
        self._my_call = ""
        self.bbs_call = ""             # from the BBS's MYCALL
        self.bbs_listening = False     # the BBS sent LISTEN ON
        self.cmd_port = 0
        self.data_port = 0
        self.connected_via: List[str] = []    # never digipeated

    # ── Listening (while local test mode is selected) ────────────────

    def listen(self, cmd_port: int, data_port: int):
        """Open the two ports on 127.0.0.1 and wait for the BBS.

        Raises OSError when a port cannot be opened (in use, most often).
        Port 0 picks a free port (tests); ``cmd_port`` / ``data_port``
        then say which.
        """
        self.shutdown()
        servers = []
        try:
            for port in (cmd_port, data_port):
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                servers.append(srv)
                # Reopening the ports soon after closing them (leaving local
                # test and coming back) must not fail on connections still
                # in TIME_WAIT.  Linux needs SO_REUSEADDR for that; on
                # Windows the default already allows it, and SO_REUSEADDR
                # there would let a second program bind the same port.
                if os.name != "nt":
                    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind((LISTEN_HOST, port))
                srv.listen(1)
        except OSError:
            for srv in servers:
                srv.close()
            raise
        self._servers = servers
        self.cmd_port = servers[0].getsockname()[1]
        self.data_port = servers[1].getsockname()[1]
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True,
                                        name="LocalTest")
        self._thread.start()
        log.info(f"Local test: listening on {LISTEN_HOST}:"
                 f"{self.cmd_port}/{self.data_port}")
        self.bbs_status.emit(False, self._waiting_text())

    @property
    def is_listening(self) -> bool:
        return bool(self._servers)

    @property
    def bbs_attached(self) -> bool:
        return self._cmd is not None

    def shutdown(self):
        """Stop listening and let go of the BBS (leaving local test mode)."""
        self._stop.set()
        for srv in self._servers:
            try:
                srv.close()
            except OSError:
                pass
        self._servers = []
        self._hang_up()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None

    def _ports_text(self) -> str:
        return f"{self.cmd_port}/{self.data_port}"

    def _waiting_text(self) -> str:
        return f"Local test: waiting for the BBS on {self._ports_text()}"

    def _attached_text(self) -> str:
        who = self.bbs_call or "BBS"
        return f"Local test: {who} attached on {self._ports_text()}"

    def _serve(self):
        """Accept the BBS (both ports), serve it until it goes, repeat."""
        while not self._stop.is_set():
            pair = self._accept_pair()
            if pair is None:
                return
            cmd, data = pair
            with self._lock:
                self._cmd, self._data = cmd, data
                self.bbs_call = ""
                self.bbs_listening = False
            log.info("Local test: BBS attached")
            self.bbs_status.emit(True, self._attached_text())
            reader = threading.Thread(target=self._data_reader, args=(data, cmd),
                                      daemon=True, name="LocalTestData")
            reader.start()
            self._cmd_reader(cmd)
            reader.join(timeout=2)
            self._bbs_gone(cmd)

    def _accept_pair(self):
        """Wait for the BBS to connect to both ports (in either order)."""
        got = {}
        servers = list(self._servers)
        while not self._stop.is_set() and len(got) < 2:
            waiting = [s for s in servers if s not in got]
            try:
                ready, _, _ = select.select(waiting, [], [], POLL)
            except (OSError, ValueError):
                break                           # closed by shutdown()
            for srv in ready:
                try:
                    conn, addr = srv.accept()
                except OSError:
                    continue
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                log.info(f"Local test: connection on port "
                         f"{srv.getsockname()[1]} from {addr[0]}")
                got[srv] = conn
        if len(got) < 2:
            for conn in got.values():
                conn.close()
            return None
        return got[servers[0]], got[servers[1]]

    def _bbs_gone(self, cmd: socket.socket):
        """The BBS closed a port (or we hung up): end any session, wait again."""
        with self._lock:
            if self._cmd is not cmd:
                return
            in_session = self._state == ConnectionState.CONNECTED
            self._hang_up()
        if self._stop.is_set():
            return
        log.info("Local test: BBS detached")
        if in_session:
            self.rf_disconnected.emit()
        if self._state != ConnectionState.DISCONNECTED:
            self._set_state(ConnectionState.DISCONNECTED)
        self.bbs_status.emit(
            False, f"Local test: BBS detached — waiting for it on {self._ports_text()}")

    def _hang_up(self):
        with self._lock:
            socks = (self._cmd, self._data)
            self._cmd = self._data = None
            self.bbs_listening = False
        for sock in socks:
            if sock is None:
                continue
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    # ── The BBS's side: command and data ports ───────────────────────

    def _cmd_reader(self, sock: socket.socket):
        buf = ""
        while not self._stop.is_set():
            try:
                chunk = sock.recv(1024)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk.decode("ascii", errors="replace")
            buf = buf.replace("\r\n", "\n").replace("\r", "\n")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if line:
                    self._on_bbs_command(line, sock)

    def _on_bbs_command(self, line: str, sock: socket.socket):
        log.info(f"Local test: BBS> {line}")
        upper = line.upper()
        if upper.startswith("MYCALL"):
            parts = line.split()
            if len(parts) > 1:
                self.bbs_call = parts[1].upper()
            self._reply(sock, "OK")
            self.bbs_status.emit(True, self._attached_text())
        elif upper == "VERSION":
            self._reply(sock, VERSION_REPLY)
        elif upper in ("DISCONNECT", "ABORT", "DIRTYDISCONNECT"):
            if self._state == ConnectionState.CONNECTED:
                self._reply(sock, "DISCONNECTED")
                self._end_session()
            else:
                self._reply(sock, "OK")
        else:
            if upper == "LISTEN ON":
                self.bbs_listening = True
            elif upper == "LISTEN OFF":
                self.bbs_listening = False
            self._reply(sock, "OK")

    def _reply(self, sock: Optional[socket.socket], line: str):
        if sock is None:
            return
        try:
            sock.sendall(line.encode("ascii") + b"\r")
            log.info(f"Local test: <BBS {line}")
        except OSError as e:
            log.warning(f"Local test: command port send failed: {e}")

    def _data_reader(self, data: socket.socket, cmd: socket.socket):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while not self._stop.is_set():
            try:
                chunk = data.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            if self._state != ConnectionState.CONNECTED:
                log.warning(f"Local test: {len(chunk)} bytes from the BBS "
                            "outside a session, dropped")
                continue
            log.info(f"Local test: data from BBS {len(chunk)} bytes: {chunk[:80]!r}")
            text = decoder.decode(chunk)
            if text:
                self.data_received.emit(text)
            self._reply(cmd, "BUFFER 0")
        # A port closed: wake the command reader so the BBS counts as gone
        try:
            cmd.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    # ── The terminal's side: what VARAModem offers the window ────────

    @property
    def state(self) -> ConnectionState:
        return self._state

    def _set_state(self, new_state: ConnectionState):
        self._state = new_state
        self.state_changed.emit(new_state)

    def connect_to_modem(self, *_args, **_kwargs):
        """Begin a call: the "modem" is up if the BBS has attached."""
        if not self.bbs_attached:
            self.error_signal.emit(
                f"Local test: the BBS has not attached to ports {self._ports_text()} "
                "yet. Start its local test instance (BBS Settings → Instances).")
            self._set_state(ConnectionState.DISCONNECTED)
            return
        self._set_state(ConnectionState.MODEM_CONNECTED)
        self.modem_connected.emit()

    def initialize_modem(self, callsign: str, *_args, **_kwargs):
        """Note the callsign to call as (nothing to set up: we are the modem)."""
        self._my_call = callsign.upper()
        self._set_state(ConnectionState.INITIALIZING)
        self._set_state(ConnectionState.MODEM_CONNECTED)

    def rf_connect(self, my_call: str, target: str, *_via):
        """Tell the BBS a call from *my_call* has come in."""
        with self._lock:
            cmd = self._cmd
        if cmd is None:
            self.error_signal.emit("Local test: the BBS has detached")
            self._set_state(ConnectionState.DISCONNECTED)
            return
        if not self.bbs_call:
            self.error_signal.emit(
                "Local test: the BBS has not sent its callsign (MYCALL) yet. "
                "Wait for it to finish starting, then connect again.")
            self._set_state(ConnectionState.MODEM_CONNECTED)
            return
        my_call = my_call.upper()
        self._my_call = my_call
        if target and target.upper() != self.bbs_call:
            log.info(f"Local test: calling the attached BBS {self.bbs_call} "
                     f"(target box says {target})")
        # The session is up before the BBS hears of it, so nothing it
        # sends back is taken for data outside a session.
        self._set_state(ConnectionState.CONNECTING)
        self._set_state(ConnectionState.CONNECTED)
        self.rf_connected.emit(f"{my_call} {self.bbs_call}")
        self._reply(cmd, f"CONNECTED {my_call} {self.bbs_call} {LINK_BANDWIDTH}")

    def rf_disconnect(self):
        """Hang up the session (Disconnect pressed)."""
        if self._state != ConnectionState.CONNECTED:
            self._set_state(ConnectionState.MODEM_CONNECTED)
            return
        self._reply(self._cmd, "DISCONNECTED")
        self._end_session()

    def _end_session(self):
        self._set_state(ConnectionState.MODEM_CONNECTED)
        self.rf_disconnected.emit()

    def send_data(self, text: str):
        """Send what the user typed to the BBS (its data port)."""
        with self._lock:
            data_sock = self._data
        if data_sock is None or self._state != ConnectionState.CONNECTED:
            log.warning("Local test: send_data outside a session")
            return
        data = text.encode("utf-8")
        try:
            data_sock.sendall(data)
            log.info(f"Local test: data to BBS {len(data)} bytes: {data[:80]!r}")
        except OSError as e:
            self.error_signal.emit(f"Data send error: {e}")

    def disconnect_from_modem(self):
        """End the call; the BBS stays attached for the next one."""
        if self._state == ConnectionState.CONNECTED:
            self._reply(self._cmd, "DISCONNECTED")
            self.rf_disconnected.emit()
        if self._state != ConnectionState.DISCONNECTED:
            self._set_state(ConnectionState.DISCONNECTED)
