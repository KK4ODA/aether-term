"""
gui/main_window.py — Main application window for Aether Term.

Ties together the terminal, connection bar, macro buttons, status bar,
modem interface (VARA FM/HF, Aether HF, AGWPE), the Aether HF status
monitor, and the authentication interceptor.
"""

import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QComboBox, QStatusBar,
    QFrame, QMessageBox, QInputDialog,
    QStyle, QStyleOptionComboBox,
)
from PyQt6.QtGui import QAction, QDesktopServices
from PyQt6.QtCore import Qt, QRect, QTimer, QUrl, pyqtSlot

from config import (Config, APP_NAME, APP_VERSION, MODE_VARA_FM,
                    MODE_VARA_HF, MODE_AETHER_HF, MODE_AGWPE, PTT_OMNIRIG, PTT_VOX)
from aether.control import (AetherMonitor, AetherQuery, AetherStatus,
                            find_aether_exe, AETHER_RELEASES_URL,
                            AETHER_HOST_GUIDE_URL)
from passwords import PasswordStore
from auth import AuthInterceptor
from vara.modem import VARAModem, parse_digipeaters
from vara.connection import ConnectionState, STATE_LABELS, STATE_COLORS
from vara.ptt import PTTController
from gui.theme import C, STATE_HEX, build_stylesheet, macro_btn_style, \
    macro_frame_style, macro_label_style, connection_bar_style
from gui.terminal_widget import TerminalWidget
from gui.sn_graph import SNGraph
from gui.settings_dialog import SettingsDialog
from gui.password_dialog import PasswordDialog
from gui.profile_dialog import ProfileDialog

log = logging.getLogger(__name__)

# Signals the window connects on a modem (VARA or AGWPE); disconnected
# when a modem is swapped out.
_MODEM_SIGNALS = (
    "state_changed", "data_received", "command_event", "sn_report",
    "error_signal", "modem_connected", "rf_connected", "rf_disconnected",
    "pending_signal", "busy_signal", "ptt_event",
    "bitrate_report", "session_bandwidth", "version_report",
)

# Via 1 / Via 2 dropdowns: the "no digipeater" entry, and how many
# digipeaters they remember.
VIA_NONE = "None"
MAX_VIA_HISTORY = 10
VIA_WIDTH_SAMPLE = "WD5EMA-15"     # the widest call the boxes must show

# How long the BBS must be quiet before an unfinished line (a prompt
# without a line end) is shown.  VARA hands data over a frame at a time,
# often mid-line, a second or more apart on a slow link.
PARTIAL_LINE_DELAY_MS = 1000

# Connecting from a profile that switched modes: time for the modem program
# just launched to open its ports.
MODEM_START_DELAY_MS = 5000

APP_TAGLINE = "BBS Terminal Client for VARA and Aether HF"

# Toolbar mode combo: (label, config value), in index order
_MODES = [
    ("VARA FM", MODE_VARA_FM),
    ("VARA HF", MODE_VARA_HF),
    ("Aether HF", MODE_AETHER_HF),
    ("Soundmodem", MODE_AGWPE),
]
_MODE_INDEX = {value: i for i, (_, value) in enumerate(_MODES)}
_MODE_LABEL = {MODE_AGWPE: "Soundmodem (AGWPE)"}


class MainWindow(QMainWindow):
    """Aether Term main application window."""

    def __init__(self, config: Config, password_store: PasswordStore):
        super().__init__()
        self.config = config
        self.passwords = password_store
        self.modem = VARAModem()
        self.auth = AuthInterceptor()
        self.ptt = PTTController()
        self._modem_procs: list = []   # tracked modem subprocesses
        self._connect_in_progress = False  # True while connect sequence is running
        self._cleanup_timer = QTimer(self)  # cancellable modem cleanup timer
        self._cleanup_timer.setSingleShot(True)
        self._cleanup_timer.setInterval(500)
        self._cleanup_timer.timeout.connect(self._cleanup_modem_connection)
        # Text that waits without a line end (a menu prompt such as
        # "4 Back:") is shown once the BBS goes quiet; the rest of that
        # line, when it comes, continues on the same screen line.
        self._partial_timer = QTimer(self)
        self._partial_timer.setSingleShot(True)
        self._partial_timer.setInterval(PARTIAL_LINE_DELAY_MS)
        self._partial_timer.timeout.connect(self._show_partial_line)
        self._partial_shown = ""           # part of the current line already on screen
        self._session_log_file = None
        self._session_start: Optional[datetime] = None
        self._data_buffer = ""
        self._data_ended_cr = False       # last data chunk ended in CR
        self._remote_eol = ""             # BBS line end once seen: "\r\n", "\r" or "\n"
        self._transport_query_pending = False
        self._active_profile: Optional[dict] = None
        self._rf_session_up = False    # a CONNECTED was seen for this call
        self._target = ""              # the station being called
        self._via: list = []           # its digipeater path
        self._prev_state = ConnectionState.DISCONNECTED

        # Aether HF control-API status monitor (only runs in Aether HF mode)
        self.aether = AetherMonitor(self)
        self.aether_query = AetherQuery(self)   # one-shot checks, off the GUI thread
        self._preflight_pending = False

        self.setWindowTitle(f"{APP_NAME} — {APP_TAGLINE}")
        self.setMinimumSize(800, 600)
        self.resize(950, 700)

        # Apply global stylesheet (arrow SVGs are embedded in theme.py)
        self.setStyleSheet(build_stylesheet())

        self._build_menus()
        self._build_toolbar()
        self._build_central()
        self._build_macros()
        self._build_status_bar()

        self._connect_signals()

        # Session duration timer
        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1000)
        self._duration_timer.timeout.connect(self._update_duration)

        self._fit_via_boxes()
        self._update_ui_state()
        self._show_welcome()

        self.aether.status_updated.connect(
            self._on_aether_status, Qt.ConnectionType.QueuedConnection)
        self._sync_aether_monitor()

        # Auto-launch the selected modem at startup
        QTimer.singleShot(500, self._launch_modem_processes)

    # ── Build UI ───────────────────────────────────────────────────

    def _build_menus(self):
        menubar = self.menuBar()

        # File
        file_menu = menubar.addMenu("&File")
        connect_action = QAction("&Connect", self)
        connect_action.setShortcut("Ctrl+Shift+C")
        connect_action.triggered.connect(self._on_connect)
        file_menu.addAction(connect_action)

        disconnect_action = QAction("&Disconnect", self)
        disconnect_action.triggered.connect(self._on_disconnect)
        file_menu.addAction(disconnect_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Settings
        settings_menu = menubar.addMenu("&Settings")
        terminal_action = QAction("&Terminal Setup...", self)
        terminal_action.triggered.connect(self._open_settings)
        settings_menu.addAction(terminal_action)

        modem_action = QAction("&Modem Configuration...", self)
        modem_action.triggered.connect(lambda: self._open_settings(tab=1))
        settings_menu.addAction(modem_action)

        passwords_action = QAction("&Security / Passwords...", self)
        passwords_action.triggered.connect(self._open_passwords)
        settings_menu.addAction(passwords_action)

        settings_menu.addSeparator()

        profiles_action = QAction("Connection &Profiles...", self)
        profiles_action.triggered.connect(self._open_profiles)
        settings_menu.addAction(profiles_action)

        # Aether HF
        aether_menu = menubar.addMenu("&Aether HF")
        ae_status = QAction("Modem &Status...", self)
        ae_status.triggered.connect(self._show_aether_status)
        aether_menu.addAction(ae_status)
        ae_panel = QAction("Open Station &Panel in Browser", self)
        ae_panel.triggered.connect(self._open_aether_panel)
        aether_menu.addAction(ae_panel)
        aether_menu.addSeparator()
        ae_guide = QAction("Host Program Setup &Guide", self)
        ae_guide.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(AETHER_HOST_GUIDE_URL)))
        aether_menu.addAction(ae_guide)
        ae_dl = QAction("&Download Aether HF", self)
        ae_dl.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(AETHER_RELEASES_URL)))
        aether_menu.addAction(ae_dl)

        # Help
        help_menu = menubar.addMenu("&Help")
        about_action = QAction(f"&About {APP_NAME}", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        commands_action = QAction("BBS &Commands Reference", self)
        commands_action.triggered.connect(self._show_commands_ref)
        help_menu.addAction(commands_action)

        help_menu.addSeparator()

        update_action = QAction("Check for &Updates...", self)
        update_action.triggered.connect(self._check_for_updates)
        help_menu.addAction(update_action)

    def _build_toolbar(self):
        """Build two-row connection bar replacing the old single-row QToolBar.

        Row 1: Target, Via 1, Via 2, Connect, Disconnect
        Row 2: Mode combo, status dot, (spacer), Profile combo
        """
        bar = QFrame()
        bar.setObjectName("connectionBar")
        bar.setStyleSheet(connection_bar_style())
        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(8, 6, 8, 6)
        bar_layout.setSpacing(4)

        # ── Row 1: Connection controls ────────────────────────────
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        row1.addWidget(QLabel("Target:"))

        self.target_input = QComboBox()
        self.target_input.setEditable(True)
        self.target_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.target_input.lineEdit().setPlaceholderText("BBS Callsign (e.g. KK4ODA-5)")
        self.target_input.setMinimumWidth(160)
        self.target_input.setDuplicatesEnabled(False)
        # Load saved history
        saved_history = self.config.get("target_history", [])
        log.debug(f"Loading target history: {saved_history}")
        for call in saved_history:
            if call and isinstance(call, str):
                self.target_input.addItem(call.upper().strip())
        if self.target_input.count() > 0:
            self.target_input.setCurrentIndex(0)
        else:
            self.target_input.setCurrentText("")
        row1.addWidget(self.target_input, stretch=1)

        # Via 1 / Via 2: "None" or a digipeater used before (or type a new
        # one); the last call's choice comes back next time.
        row1.addWidget(QLabel("Via 1:"))
        self.via1_input = self._make_via_combo(
            "First digipeater in the path (VARA FM or Soundmodem).\n"
            "None for a direct connection.\n"
            "VARA FM needs a registered VARA license to use digipeaters.",
            self.config.get("last_via1", ""))
        row1.addWidget(self.via1_input)

        row1.addWidget(QLabel("Via 2:"))
        self.via2_input = self._make_via_combo(
            "Second digipeater in the path (VARA FM or Soundmodem).\n"
            "Only needed for two-hop routes.",
            self.config.get("last_via2", ""))
        row1.addWidget(self.via2_input)

        self.connect_btn = QPushButton("  Connect  ")
        self.connect_btn.setObjectName("connectBtn")
        self.connect_btn.clicked.connect(self._on_connect)
        row1.addWidget(self.connect_btn)

        self.disconnect_btn = QPushButton("  Disconnect  ")
        self.disconnect_btn.setObjectName("disconnectBtn")
        self.disconnect_btn.clicked.connect(self._on_disconnect)
        row1.addWidget(self.disconnect_btn)

        clear_btn = QPushButton("  Clear  ")
        clear_btn.setToolTip("Clear the terminal output window")
        clear_btn.clicked.connect(self._clear_terminal)
        row1.addWidget(clear_btn)

        bar_layout.addLayout(row1)

        # ── Row 2: Mode, status, profile ──────────────────────────
        row2 = QHBoxLayout()
        row2.setSpacing(6)

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("modeCombo")
        self.mode_combo.setToolTip(
            "Switch between VARA FM, VARA HF, Aether HF and\n"
            "Soundmodem (AGWPE) transport modes.")
        self.mode_combo.addItems([label for label, _ in _MODES])
        self.mode_combo.setCurrentIndex(_MODE_INDEX.get(self.config.mode, 0))
        self.mode_combo.currentIndexChanged.connect(self._on_mode_switched)
        row2.addWidget(self.mode_combo)

        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("statusDot")
        self.status_dot.setToolTip("Connection state indicator.\nGreen = connected, Red = disconnected.")
        self.status_dot.setStyleSheet(
            f"color: {STATE_HEX.get('red', C['error'])}; font-size: 14pt;")
        row2.addWidget(self.status_dot)

        row2.addStretch()

        row2.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(140)
        self.profile_combo.addItem("(none)")
        self._refresh_profiles()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        row2.addWidget(self.profile_combo)

        bar_layout.addLayout(row2)

        self._connection_bar = bar

    def _build_central(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 0, 6, 2)
        layout.setSpacing(4)

        # Connection bar at top (flush against menu bar)
        layout.addWidget(self._connection_bar)

        # Terminal (display + input)
        self.terminal = TerminalWidget()
        self.terminal.command_entered.connect(self._on_command)
        layout.addWidget(self.terminal, stretch=1)

        # S/N graph is added AFTER macros (in _build_macros)
        self.sn_graph = SNGraph()

    _MACRO_BTN_STYLE = macro_btn_style()

    def _build_macros(self):
        """Build macro button bar below the terminal input."""
        # We add the macro bar to the central widget layout
        central_layout = self.centralWidget().layout()

        self.macro_frame = QFrame()
        self.macro_frame.setStyleSheet(macro_frame_style())
        macro_layout = QHBoxLayout(self.macro_frame)
        macro_layout.setContentsMargins(8, 4, 8, 4)
        macro_layout.setSpacing(6)

        # Label
        lbl = QLabel("Quick:")
        lbl.setStyleSheet(macro_label_style())
        macro_layout.addWidget(lbl)

        self.macro_buttons = []
        for macro in self.config.get_macros():
            btn = QPushButton(macro.get("label", ""))
            btn.setStyleSheet(self._MACRO_BTN_STYLE)
            cmd = macro.get("command", "")
            btn.clicked.connect(lambda checked, c=cmd: self._send_macro(c))
            macro_layout.addWidget(btn)
            self.macro_buttons.append(btn)

        macro_layout.addStretch()
        central_layout.addWidget(self.macro_frame)

        # S/N graph goes below macros
        central_layout.addWidget(self.sn_graph)

    def _build_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.state_label = QLabel("DISCONNECTED")
        self.state_label.setStyleSheet(f"color: {C['error']}; font-weight: bold;")
        self.status_bar.addWidget(self.state_label)

        self.status_bar.addWidget(self._sep())

        self.sn_label = QLabel("S/N: —")
        self.sn_label.setToolTip("Signal-to-Noise ratio reported by the modem.\nHigher values = better signal quality.")
        self.status_bar.addWidget(self.sn_label)

        self.status_bar.addWidget(self._sep())

        self.bw_label = QLabel("BW: —")
        self.bw_label.setToolTip("Current session bandwidth in Hz.")
        self.status_bar.addWidget(self.bw_label)

        self.status_bar.addWidget(self._sep())

        self.speed_label = QLabel("Speed: —")
        self.speed_label.setToolTip("Link speed reported by the modem (BITRATE).")
        self.status_bar.addWidget(self.speed_label)

        self.status_bar.addWidget(self._sep())

        self.duration_label = QLabel("Duration: 00:00:00")
        self.status_bar.addWidget(self.duration_label)

        self.status_bar.addWidget(self._sep())

        self.modem_status_label = QLabel("Modem: Not connected")
        self.status_bar.addPermanentWidget(self.modem_status_label)

        # Aether HF status from its control API (hidden in other modes)
        self.aether_label = QLabel("")
        self.aether_label.setToolTip("Aether HF modem status (control API).\nClick for details.")
        self.aether_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.aether_label.mousePressEvent = lambda _ev: self._show_aether_status()
        self.aether_label.hide()
        self.status_bar.addPermanentWidget(self.aether_label)

        self.ptt_label = QLabel("")
        self.ptt_label.setStyleSheet("font-weight: bold;")
        self.ptt_label.setToolTip("Push-to-Talk indicator.\nShown during HF transmission.")
        self.status_bar.addPermanentWidget(self.ptt_label)

        # Update-available indicator (clickable, hidden by default)
        self._update_label = QLabel("")
        self._update_label.setStyleSheet(
            f"color: {C['warning']}; font-weight: bold;"
        )
        self._update_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_label.setToolTip("Click to view available update")
        self._update_label.hide()
        self._update_label.mousePressEvent = lambda _ev: self._show_update_dialog()
        self.status_bar.addPermanentWidget(self._update_label)
        self._updater = None
        self._pending_update = None

        # Chat room indicator
        self._chat_label = QLabel("")
        self._chat_label.setStyleSheet(f"color: {C['info']}; font-weight: bold;")
        self._chat_label.hide()
        self.status_bar.addPermanentWidget(self._chat_label)
        self._chat_room = ""

    @staticmethod
    def _sep() -> QLabel:
        sep = QLabel("│")
        sep.setStyleSheet(f"color: {C['border_light']}; padding: 0 4px;")
        return sep

    # ── Signal connections ─────────────────────────────────────────

    def _connect_signals(self):
        self.modem.state_changed.connect(self._on_state_changed, Qt.ConnectionType.QueuedConnection)
        self.modem.data_received.connect(self._on_data_received, Qt.ConnectionType.QueuedConnection)
        self.modem.command_event.connect(self._on_command_event, Qt.ConnectionType.QueuedConnection)
        self.modem.sn_report.connect(self._on_sn_report, Qt.ConnectionType.QueuedConnection)
        self.modem.error_signal.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
        self.modem.modem_connected.connect(self._on_modem_connected, Qt.ConnectionType.QueuedConnection)
        self.modem.rf_connected.connect(self._on_rf_connected, Qt.ConnectionType.QueuedConnection)
        self.modem.rf_disconnected.connect(self._on_rf_disconnected, Qt.ConnectionType.QueuedConnection)
        self.modem.pending_signal.connect(
            lambda: self.terminal.display.append_system("Connection pending..."),
            Qt.ConnectionType.QueuedConnection)
        self.modem.busy_signal.connect(
            lambda: self.terminal.display.append_warning("Remote station is busy"),
            Qt.ConnectionType.QueuedConnection)
        # VARA-protocol extras (absent on the AGWPE modem)
        if hasattr(self.modem, "bitrate_report"):
            self.modem.bitrate_report.connect(
                lambda v: self.speed_label.setText(f"Speed: {v}"),
                Qt.ConnectionType.QueuedConnection)
            self.modem.session_bandwidth.connect(
                lambda bw: self.bw_label.setText(
                    f"BW: {bw} Hz" if bw.isdigit() else f"BW: {bw}"),
                Qt.ConnectionType.QueuedConnection)
            self.modem.version_report.connect(
                self._on_version_report, Qt.ConnectionType.QueuedConnection)
        # HF PTT: modem emits ptt_event → PTT controller keys/unkeys radio
        self.modem.ptt_event.connect(self.ptt.on_ptt_event,
                                      Qt.ConnectionType.QueuedConnection)
        # The PTT controller outlives modem swaps: wire it once
        if not getattr(self, "_ptt_wired", False):
            self._ptt_wired = True
            self.ptt.ptt_changed.connect(self._on_ptt_changed,
                                          Qt.ConnectionType.QueuedConnection)
            self.ptt.ptt_error.connect(
                lambda msg: self.terminal.display.append_warning(f"[PTT] {msg}"),
                Qt.ConnectionType.QueuedConnection)

    # ── Actions ────────────────────────────────────────────────────

    def _on_connect(self):
        """Initiate a connection to the target BBS."""
        callsign = self._effective_callsign()
        if not callsign:
            QMessageBox.warning(self, "Configuration Error",
                                "Please set your callsign in Settings → Terminal Setup.")
            self._open_settings()
            return

        target = self.target_input.currentText().upper().strip()
        if not target:
            QMessageBox.warning(self, "Missing Target",
                                "Please enter the target BBS callsign.")
            self.target_input.setFocus()
            return

        if self._preflight_pending:
            return

        if not self._check_digipeaters():
            return

        if self.config.is_aether:
            # Ask the modem first, on a worker thread; the connect continues
            # in _on_aether_preflight once it answers (or does not).
            self._preflight_pending = True
            self._update_ui_state()
            self.terminal.display.append_system("[AETHER] Checking the modem...")
            self.aether_query.snapshot(
                self.config.aether_control_url,
                lambda st: self._on_aether_preflight(st, callsign, target))
            return

        self._begin_connect(callsign, target)

    def _on_aether_preflight(self, st: AetherStatus, callsign: str, target: str):
        self._preflight_pending = False
        if self.config.is_aether and self._aether_preflight_ok(st):
            self._begin_connect(callsign, target)
        self._update_ui_state()

    def _check_digipeaters(self) -> bool:
        """Validate the Via fields; False (after telling the user) to stop.

        VARA FM and Soundmodem (AGWPE) route through digipeaters; VARA HF
        and Aether HF would otherwise silently call direct.
        """
        try:
            digis = parse_digipeaters(self._via_value(self.via1_input),
                                      self._via_value(self.via2_input))
        except ValueError as e:
            QMessageBox.warning(self, "Digipeater Path", str(e))
            self.via1_input.setFocus()
            return False
        if digis and self.config.mode not in (MODE_VARA_FM, MODE_AGWPE):
            QMessageBox.warning(
                self, "Digipeater Path",
                "Digipeaters are supported with VARA FM and Soundmodem.\n\n"
                f"Set Via 1 / Via 2 to None to call direct with "
                f"{_MODE_LABEL.get(self.config.mode, self.config.mode)}, "
                "or switch modes.")
            return False
        return True

    def _begin_connect(self, callsign: str, target: str):
        """Open the modem link and start the call (after any preflight)."""
        mode = self.config.mode
        is_agwpe = (mode == MODE_AGWPE)
        if not self._start_host_ptt():
            return

        # Store target and digipeater path for later use
        self._target = target
        via1 = self._via_value(self.via1_input)
        via2 = self._via_value(self.via2_input)
        self._via = parse_digipeaters(via1, via2)
        self._remember_via(via1, via2)
        path = f" via {', '.join(self._via)}" if self._via else ""
        self.terminal.display.append_system(
            f"Connecting to {target}{path} as {callsign} using {mode}...")
        if self._via and mode == MODE_VARA_FM:
            self.terminal.display.append_system(
                "Note: VARA FM needs a registered VARA license to connect "
                "through digipeaters.")
        self._connect_in_progress = True
        self._rf_session_up = False
        # The BBS's line ends are learned afresh for each call.  ;TRANSPORT?
        # is an Aether BBS extension: it goes out only once the BBS shows
        # CR LF line ends — a BPQ node (bare CR) would take it as a bad
        # command.
        self._remote_eol = ""
        self._transport_query_pending = True
        self.speed_label.setText("Speed: —")
        self._cleanup_timer.stop()  # cancel any stale cleanup timer

        # Save target to recent stations history immediately
        self._add_to_target_history(target)

        if is_agwpe:
            # Switch to AGWPE modem
            self._swap_modem_agwpe()
            host = self.config.get("soundmodem_host", "127.0.0.1")
            port = self.config.get("soundmodem_port", 8000)
            self.terminal.display.append_system(
                f"Soundmodem (AGWPE): {host}:{port}")
            self.modem.connect_to_modem(host, port)
        else:
            # Ensure we're using VARAModem
            self._swap_modem_vara()
            host = self.config.modem_host
            cmd_port = self.config.cmd_port
            data_port = self.config.data_port
            self.terminal.display.append_system(
                f"{mode} modem: {host}:{cmd_port}/{data_port}")
            self.modem.connect_to_modem(host, cmd_port, data_port,
                                        self.config.get("max_retries", 5))

    def _start_host_ptt(self) -> bool:
        """Start radio keying when this program keys the radio (VARA HF, or
        Aether HF set to "host program" keying).

        False, after telling the user, when the chosen PTT method can't
        reach the radio: the call would go out with the radio never keyed.
        """
        if not self.config.needs_host_ptt:
            return True
        method = self.config.get("hf_ptt_method", PTT_VOX)
        if method == PTT_VOX:
            return True
        self.terminal.display.append_system(f"Starting {method} PTT...")
        if self.ptt.start_method(method, self.config):
            self.terminal.display.append_success(f"{method} PTT connected")
            return True
        self.terminal.display.append_error(
            f"Connect stopped: {method} PTT can't key the radio")
        QMessageBox.warning(
            self, "PTT Unavailable",
            f"{method} PTT can't key the radio:\n\n{self.ptt.last_error}\n\n"
            f"Start {method}, or choose another method in Settings → Modem "
            "Configuration → HF PTT Control. Choose \"None (VOX)\" if the "
            "radio keys itself on audio.")
        return False

    @pyqtSlot()
    def _on_modem_connected(self):
        """TCP link to modem is up — now initialize it."""
        self.terminal.display.append_system("TCP connection to modem established")
        self.modem_status_label.setText("Modem: Connected")
        self.modem_status_label.setStyleSheet(f"color: {C['success']};")

        # RF CONNECT is sent when init completes (state → MODEM_CONNECTED).
        # A one-shot connection avoids the old fixed-timer race where
        # CONNECT fired before BW was sent on HF.  Listen *before* starting
        # init, so a modem that finishes at once (Soundmodem) is not missed.
        self.modem.state_changed.connect(
            self._on_init_complete, Qt.ConnectionType.QueuedConnection)

        callsign = self._effective_callsign()
        self.modem.initialize_modem(
            callsign, self.config.is_hf_band, self.config.session_bandwidth,
            query_version=self.config.is_aether,
            session=self.config.vara_session)

    @pyqtSlot(object)
    def _on_init_complete(self, new_state):
        """Fired on every modem state change; send RF CONNECT once init is done."""
        if new_state != ConnectionState.MODEM_CONNECTED:
            return
        # Disconnect so this doesn't fire again on later state transitions
        try:
            self.modem.state_changed.disconnect(self._on_init_complete)
        except TypeError:
            pass
        # Small delay for modem to settle, then connect
        QTimer.singleShot(500, self._send_rf_connect)

    def _send_rf_connect(self):
        """Send the CONNECT command to initiate the RF link."""
        if self.modem.state != ConnectionState.MODEM_CONNECTED:
            return
        target = self._target
        via = self._via
        callsign = self._effective_callsign()

        self.terminal.display.append_system(f"Initiating RF connection to {target}...")
        self.modem.rf_connect(callsign, target, *via)

    @pyqtSlot(str)
    def _on_rf_connected(self, calls_str: str):
        """RF session is now active.  Resolve which call is the remote."""
        parts = calls_str.split()
        my_call = self._effective_callsign().upper()

        # Figure out which is the remote call
        if len(parts) == 2:
            if parts[0].upper() == my_call:
                remote = parts[1]
            elif parts[1].upper() == my_call:
                remote = parts[0]
            else:
                # Neither matches exactly — use the target we requested
                remote = self._target or parts[0]
        elif len(parts) == 1:
            remote = parts[0]
        else:
            remote = self._target or 'UNKNOWN'

        self._rf_session_up = True
        via = getattr(self.modem, "connected_via", [])
        path = f" via {', '.join(via)}" if via else ""
        self.terminal.display.append_success(f"*** CONNECTED to {remote}{path} ***")
        self.terminal.set_input_enabled(True)
        self.terminal.input.setFocus()

        # Also save the resolved remote callsign (may differ from
        # what the user typed if routed via digipeaters)
        self._add_to_target_history(remote)

        # Reset auth state
        self.auth.reset()
        self._data_buffer = ""
        self._data_ended_cr = False
        self._partial_shown = ""

        # Start session timer
        self._session_start = datetime.now(timezone.utc)
        self._duration_timer.start()

        # Start session log
        if self.config.get("session_logging"):
            self._start_session_log(remote)

        # ;TRANSPORT? is sent by _note_line_ending once the BBS shows CR LF
        # line ends (set up in _begin_connect).

    @pyqtSlot()
    def _on_rf_disconnected(self):
        """RF session has ended."""
        self.terminal.display.append_warning("*** DISCONNECTED ***")
        if self.config.is_aether and not self._rf_session_up:
            self._explain_aether_no_session()
        self._rf_session_up = False
        self.terminal.set_input_enabled(False)
        self._duration_timer.stop()
        self._close_session_log()
        self.auth.reset()
        self.sn_graph.clear_data()
        self._chat_room = ""
        self._chat_label.hide()
        # Release PTT (HF safety)
        if self.ptt.is_enabled:
            self.ptt.stop()
            self.ptt_label.setText("")
        # Modem TCP cleanup is handled by _on_state_changed when
        # state transitions to MODEM_CONNECTED with no connect in progress.

    def _cleanup_modem_connection(self):
        """Close TCP sockets to modem after RF session ends."""
        # Safety: don't kill an active connect sequence
        if self._connect_in_progress:
            log.debug("Cleanup skipped — connect in progress")
            return
        if self.modem.state != ConnectionState.DISCONNECTED:
            log.info("Cleaning up modem TCP connection")
            self.modem.disconnect_from_modem()

    def _on_disconnect(self):
        """User requested disconnect."""
        self._connect_in_progress = False
        self._cleanup_timer.stop()

        # PTT stays with the modem until the link is down: VARA HF keys
        # the radio to send its disconnect frames.  It is released on
        # DISCONNECTED (_on_rf_disconnected / _on_state_changed).
        if self.modem.state == ConnectionState.CONNECTED:
            self.terminal.display.append_system("Disconnecting...")
            self.modem.rf_disconnect()
            # _on_rf_disconnected will handle the rest asynchronously
        elif self.modem.state != ConnectionState.DISCONNECTED:
            self.modem.disconnect_from_modem()

    def _clear_terminal(self):
        """Clear the terminal output window."""
        self.terminal.display.clear_terminal()

    def _send_text(self, text: str):
        """Send a line of text over RF, echo locally, and log."""
        if self.modem.state != ConnectionState.CONNECTED:
            self.terminal.display.append_warning(
                "Not connected — command not sent.")
            return
        self.terminal.display.append_text(f"> {text}\n", "dim")
        self.modem.send_data(text + self._line_end())
        self._log_line(f"> {text}")

    def _line_end(self) -> str:
        """Line end for what the user types: the BBS's own convention.

        BPQ nodes (and most packet BBSes) end lines with a bare CR and read
        an LF after it as the start of the next command; the Aether BBS
        uses CR LF.  A BPQ node says nothing until spoken to, so before the
        BBS has sent a line end the answer is a bare CR; a BBS that greets
        first (the Aether BBS) has shown its CR LF by the time you type.
        """
        return "\r\n" if self._remote_eol in ("\r\n", "\n") else "\r"

    def _note_line_ending(self, text: str):
        """Learn the BBS's line end from the data it sends.

        CR LF evidence (in one chunk, or a CR ending one chunk and an LF
        starting the next) is final.  A bare CR — inside a chunk, or ending
        one, as BPQ's replies do — means CR until CR LF evidence turns up.
        """
        if "\r\n" in text or (self._data_ended_cr and text.startswith("\n")):
            eol = "\r\n"
        elif self._remote_eol == "\r\n":
            return
        elif "\r" in text or self._data_ended_cr:
            eol = "\r"
        elif "\n" in text and not self._remote_eol:
            eol = "\n"
        else:
            return
        if eol == self._remote_eol:
            return
        self._remote_eol = eol
        log.info("BBS line ends: %s", {"\r\n": "CR LF", "\r": "CR", "\n": "LF"}[eol])
        if eol == "\r\n" and self._transport_query_pending:
            self._transport_query_pending = False
            QTimer.singleShot(0, self._query_transport)

    def _on_command(self, text: str):
        """User typed a command in the input bar."""
        if not text.strip():
            return
        self._send_text(text)

    # ── Data handling ──────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_data_received(self, text: str):
        """Process incoming data from the BBS.

        Lines may end in CR LF, LF, or a bare CR — BPQ nodes and most
        packet BBSes send CR only.  A CR LF split across two chunks counts
        as one line end.
        """
        self._note_line_ending(text)
        if self._data_ended_cr and text.startswith("\n"):
            text = text[1:]
        self._data_ended_cr = text.endswith("\r")
        self._data_buffer += text.replace("\r\n", "\n").replace("\r", "\n")

        # Process complete lines
        while "\n" in self._data_buffer:
            line, self._data_buffer = self._data_buffer.split("\n", 1)
            shown, self._partial_shown = self._partial_shown, ""
            self._process_line(line, shown)

        # An unfinished line: a short prompt ("> ", "Callsign:") is shown
        # at once; anything else once the BBS has been quiet for a moment —
        # VARA hands data over a radio frame at a time, often mid-line.
        buf = self._data_buffer
        if buf and len(buf) < 10 and buf.rstrip().endswith((">", ":")):
            self._partial_timer.stop()
            self._show_partial_line()
        elif buf:
            self._partial_timer.start()
        else:
            self._partial_timer.stop()

    def _show_partial_line(self):
        """Show the unfinished line the BBS has stopped at (a prompt).

        The text stays in the buffer: when the rest of the line comes, the
        whole line is processed and only the new part is displayed.
        """
        buf = self._data_buffer
        if not buf or buf.startswith(";") or buf == self._partial_shown:
            return                          # ;protocol lines stay hidden
        if self.auth.process_line(
                buf, self.passwords.get_password(self._target, self._effective_callsign()),
                self.config.get("auto_respond_hmac", True),
                self.config.get("show_auth_protocol", False)).suppress:
            return                          # the password prompt during auto-auth
        self.terminal.display.append_text(buf[len(self._partial_shown):], "normal")
        self._partial_shown = buf

    def _process_line(self, line: str, shown: str = ""):
        """Process a single complete line from the BBS.

        *shown* is the start of the line already on screen (an unfinished
        line shown while the BBS paused); only the rest is displayed.
        """
        if shown and not line.startswith(shown):
            shown = ""
        if shown and line == shown:
            # Nothing new: just end the screen line
            self.terminal.display.append_text("\n", "normal")
            self._log_line(line)
            return
        # Transport auto-detection (suppress from display)
        if self._handle_transport_response(line):
            self._log_line(line)
            return

        # Tactical address response (suppress protocol lines from display)
        if self._handle_tactical_response(line):
            self._log_line(line)
            return

        # Chat mode detection
        self._check_chat_enter(line)
        self._check_chat_exit(line)

        target = self._target
        password = self.passwords.get_password(target, self._effective_callsign())

        action = self.auth.process_line(
            line,
            password,
            self.config.get("auto_respond_hmac", True),
            self.config.get("show_auth_protocol", False),
        )

        # Send auth response if needed — delay briefly to let VARA FM
        # finish receiving before we transmit (half-duplex turnaround)
        if action.send_response:
            response = action.send_response
            QTimer.singleShot(1500, lambda: self._send_auth_response(response))

        # Handle WLREG challenge — prompt locally for Winlink password
        if action.wlreg_nonce:
            self._handle_wlreg_challenge(action.wlreg_nonce, password)

        # Display handling
        if action.suppress and not action.display_text:
            # Completely suppressed
            pass
        elif action.display_text:
            # Custom display text, on a line of its own
            if shown:
                self.terminal.display.append_text("\n", "normal")
            if action.is_success:
                self.terminal.display.append_success(action.display_text)
                self.passwords.update_last_used(target, self._effective_callsign())
                self._send_tactical_if_configured()
            elif action.is_error:
                self.terminal.display.append_error(action.display_text)
            elif action.is_warning:
                self.terminal.display.append_warning(action.display_text)
            else:
                self.terminal.display.append_system(action.display_text)
        elif shown:
            # Finish the screen line the partial display started
            self.terminal.display.append_line(line[len(shown):], "normal")
        else:
            # Normal line — display as-is
            self.terminal.display.append_line(line, "normal")

        # Log
        self._log_line(line)

    def _handle_wlreg_challenge(self, nonce: str, bbs_password: Optional[str]):
        """Handle a ;WLREG NONCE challenge from the BBS.

        Prompts the user locally for their Winlink password, encrypts it
        using the shared BBS password + nonce, and sends the encrypted
        response. The Winlink password never appears in plaintext over RF.
        """
        from auth import encrypt_wlreg_password

        if not bbs_password:
            self.terminal.display.append_error(
                "[WLREG] No BBS password saved — cannot encrypt Winlink password")
            self.modem.send_data("CANCEL\r\n")
            return

        # Prompt locally (not over RF)
        wl_pw, ok = QInputDialog.getText(
            self, "Winlink Registration",
            "Enter your Winlink password:\n"
            "(encrypted before sending — never sent in clear over RF)",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not wl_pw.strip():
            self.terminal.display.append_warning("[WLREG] Registration cancelled")
            self.modem.send_data("CANCEL\r\n")
            return

        # Encrypt using shared BBS password + nonce
        encrypted_hex = encrypt_wlreg_password(bbs_password, nonce, wl_pw.strip())
        self.modem.send_data(f";WLREG {encrypted_hex}\r\n")
        self.terminal.display.append_system(
            "[WLREG] Encrypted Winlink password sent")

    # ── State management ───────────────────────────────────────────

    @pyqtSlot(object)
    def _on_state_changed(self, state: ConnectionState):
        label = STATE_LABELS.get(state, "UNKNOWN")
        color = STATE_COLORS.get(state, "red")

        hex_color = STATE_HEX.get(color, C["text"])
        self.state_label.setText(label)
        self.state_label.setStyleSheet(
            f"color: {hex_color}; font-weight: bold;")
        self.status_dot.setStyleSheet(
            f"color: {hex_color}; font-size: 14pt;")

        # Clear the connect flag only at terminal states — the full
        # connect sequence is: MODEM_CONNECTED → INITIALIZING →
        # MODEM_CONNECTED → CONNECTING → CONNECTED.  The flag must
        # stay True until we reach CONNECTED (success) or
        # DISCONNECTED (total failure).
        if state in (ConnectionState.CONNECTED,
                     ConnectionState.DISCONNECTED):
            self._connect_in_progress = False
        # The modem link is gone (closed, failed call cleaned up, or the
        # modem crashed / dropped TCP): never leave the radio keyed or the
        # rig link open waiting for a PTT OFF that cannot come.
        if state == ConnectionState.DISCONNECTED and self.ptt.is_enabled:
            log.info("Modem link closed — releasing PTT")
            self.ptt.stop()
            self.ptt_label.setText("")
        # Falling back to MODEM_CONNECTED from a call (refused, timed out,
        # CANCELPENDING, rejected CONNECT, or a session that ended) is the
        # end of that connect sequence too — unlike the INITIALIZING →
        # MODEM_CONNECTED step that precedes the CONNECT.
        prev, self._prev_state = self._prev_state, state
        if (state == ConnectionState.MODEM_CONNECTED
                and prev in (ConnectionState.CONNECTING,
                             ConnectionState.CONNECTED,
                             ConnectionState.DISCONNECTING)):
            if prev == ConnectionState.CONNECTING and self._connect_in_progress:
                self.terminal.display.append_warning(
                    f"Connection to {self._target} failed "
                    "— closing the modem link.")
            self._connect_in_progress = False

        # If we've fallen back to MODEM_CONNECTED and we're NOT in a
        # connect sequence, it means the RF session ended (DISCONNECTED
        # from BBS, CANCELPENDING, etc). Close the modem TCP sockets
        # so the state returns to DISCONNECTED and buttons re-enable.
        if (state == ConnectionState.MODEM_CONNECTED
                and not self._connect_in_progress):
            self._cleanup_timer.start()  # 500ms, cancellable

        self._update_ui_state()

    def _update_ui_state(self):
        """Enable/disable buttons based on connection state."""
        state = self.modem.state
        connected = state == ConnectionState.CONNECTED
        disconnected = state == ConnectionState.DISCONNECTED

        self.connect_btn.setEnabled(disconnected and not self._preflight_pending)
        self.disconnect_btn.setEnabled(not disconnected)
        self.target_input.setEnabled(disconnected)
        self.via1_input.setEnabled(disconnected)
        self.via2_input.setEnabled(disconnected)
        self.terminal.set_input_enabled(connected)

        # Lock mode switching while any connection activity is happening
        self.mode_combo.setEnabled(disconnected and not self._preflight_pending)
        self.profile_combo.setEnabled(disconnected and not self._preflight_pending)

        # Sync combo selection with config (e.g. after Settings dialog)
        expected_idx = _MODE_INDEX.get(self.config.mode, 0)
        if self.mode_combo.currentIndex() != expected_idx:
            self.mode_combo.blockSignals(True)
            try:
                self.mode_combo.setCurrentIndex(expected_idx)
            finally:
                self.mode_combo.blockSignals(False)

        # Update bandwidth label (a CONNECTED line may refine it later)
        if not connected:
            if self.config.is_hf_band:
                self.bw_label.setText(f"BW: {self.config.session_bandwidth} Hz")
            elif self.config.mode == MODE_AGWPE:
                self.bw_label.setText("BW: —")
            else:
                self.bw_label.setText(f"BW: {self.config.get('fm_bandwidth', 'NARROW')}")

    @pyqtSlot(str)
    def _on_command_event(self, event: str):
        """Show relevant modem events in terminal."""
        upper = event.upper()
        if upper.startswith("CONNECTED") or upper.startswith("DISCONNECTED"):
            pass  # handled by specific signals
        elif upper == "PENDING":
            pass
        elif upper == "BUSY":
            pass
        elif upper == "WRONG":
            last_cmd = getattr(self.modem, "_last_cmd", None)
            cmd_hint = f" (cmd: {last_cmd})" if last_cmd else ""
            self.terminal.display.append_warning(
                f"[MODEM] Command rejected: WRONG{cmd_hint}")
        elif upper == "CANCELPENDING":
            self.terminal.display.append_warning("[MODEM] Connection attempt cancelled")
        elif upper == "LINK UNREGISTERED" and self._via:
            self.terminal.display.append_warning(
                "[MODEM] VARA reports this link as unregistered — VARA FM "
                "requires a VARA license to connect through digipeaters.")
        elif upper == "MISSING SOUNDCARD":
            self.terminal.display.append_error(
                "[MODEM] The modem's sound card would not open — it can neither "
                "hear nor transmit. Check the audio device in the modem's setup.")
        elif upper.startswith("PTT"):
            # PTT events are noisy during normal operation — only show
            # if the user has opted in via settings
            if self.config.get("show_ptt_events", False):
                self.terminal.display.append_text(
                    f"[MODEM] {event}\n", "dim")

    @pyqtSlot(str)
    def _on_sn_report(self, value: str):
        try:
            sn = float(value)
            self.sn_label.setText(f"S/N: {sn:.0f} dB")
            self.sn_graph.add_value(sn)
        except ValueError:
            self.sn_label.setText(f"S/N: {value}")

    @pyqtSlot(str)
    def _on_error(self, msg: str):
        self.terminal.display.append_error(f"[ERROR] {msg}")
        # If this looks like a modem TCP connection failure, hint about mode
        if "Cannot connect to modem" in msg:
            mode = self.config.mode
            self.terminal.display.append_warning(
                f"  Tip: {APP_NAME} is set to {mode}. Make sure the {mode}\n"
                f"  modem is running. Switch modes in the toolbar if needed.")
            if self.config.is_aether:
                self.terminal.display.append_warning(
                    "  Aether HF's host port is off by default: in Aether HF,\n"
                    "  Setup step 5, turn on \"Host programs\" (port 8300).")
        self.modem_status_label.setText("Modem: Error")
        self.modem_status_label.setStyleSheet(f"color: {C['error']};")
        self._connect_in_progress = False

    @pyqtSlot(bool)
    def _on_ptt_changed(self, ptt_on: bool):
        """Update the PTT indicator in the status bar."""
        if ptt_on:
            self.ptt_label.setText("● TX")
            self.ptt_label.setStyleSheet(f"color: {C['error']}; font-weight: bold;")
        else:
            self.ptt_label.setText("")

    def _update_duration(self):
        if self._session_start:
            elapsed = (datetime.now(timezone.utc) - self._session_start).total_seconds()
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            s = int(elapsed % 60)
            self.duration_label.setText(f"Duration: {h:02d}:{m:02d}:{s:02d}")

    # ── Macros ─────────────────────────────────────────────────────

    def _send_macro(self, command: str):
        self._send_text(command)

    def _refresh_macros(self):
        """Rebuild macro buttons from config."""
        for btn in self.macro_buttons:
            btn.deleteLater()
        self.macro_buttons.clear()

        layout = self.macro_frame.layout()
        # Remove all except the "Quick:" label at index 0
        while layout.count() > 1:
            item = layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()

        for macro in self.config.get_macros():
            btn = QPushButton(macro.get("label", ""))
            btn.setStyleSheet(self._MACRO_BTN_STYLE)
            cmd = macro.get("command", "")
            btn.clicked.connect(lambda checked, c=cmd: self._send_macro(c))
            layout.addWidget(btn)
            self.macro_buttons.append(btn)
        layout.addStretch()

    # ── Profiles ───────────────────────────────────────────────────

    def _effective_callsign(self) -> str:
        """Return the active operator callsign.

        Uses the selected profile's identity if one is set, otherwise
        falls back to the global ``my_callsign``/``my_ssid`` in config.
        This never mutates the persisted config.
        """
        if self._active_profile:
            return self.config.profile_full_callsign(self._active_profile)
        return self.config.full_callsign

    def _update_title(self):
        call = self._effective_callsign()
        if call:
            self.setWindowTitle(f"{APP_NAME} — {call}")
        else:
            self.setWindowTitle(f"{APP_NAME} — {APP_TAGLINE}")

    def _refresh_profiles(self):
        """Rebuild the profile dropdown after the Profiles window.

        Without selecting anything: a profile connected from that window
        is already active, and the rebuild must not reset it.
        """
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("(none)")
        for i, p in enumerate(self.config.get_profiles(), 1):
            parts = []
            # Operator → Target
            my_call = p.get("my_callsign", "")
            if my_call:
                ssid = p.get("my_ssid", 0)
                op = f"{my_call}-{ssid}" if ssid else my_call
            else:
                op = ""
            target = p.get("target_callsign", "")
            if op and target:
                parts.append(f"{op} → {target}")
            elif target:
                parts.append(target)
            elif op:
                parts.append(op)
            # Transport + bandwidth
            mode = p.get("mode", "VARA FM")
            if mode == MODE_VARA_HF:
                bw = p.get("bandwidth", 500)
                parts.append(f"VARA HF/{bw}")
            elif mode == MODE_AETHER_HF:
                bw = 500 if int(p.get("bandwidth", 2300)) == 500 else 2300
                parts.append(f"Aether HF/{bw}")
            elif mode == MODE_AGWPE:
                parts.append("Soundmodem")
            else:
                fm_bw = p.get("fm_bandwidth", "WIDE")
                parts.append(f"VARA FM/{fm_bw}")
            # Tactical
            tactical = p.get("tactical_callsign", "")
            if tactical:
                parts.append(f"[{tactical}]")
            label = f"{i}: {' | '.join(parts)}"
            self.profile_combo.addItem(label)
            if p == self._active_profile:
                self.profile_combo.setCurrentIndex(i)
        self.profile_combo.blockSignals(False)

    def _on_profile_selected(self, index: int):
        profiles = self.config.get_profiles()
        if 0 < index <= len(profiles):
            self._apply_profile(profiles[index - 1])
        else:
            self._active_profile = None
            self._update_title()

    def _apply_profile(self, p: dict) -> Optional[bool]:
        """Make *p* the active profile: operator, target, path, mode and
        bandwidth.  Returns whether the mode changed, or None when it
        could not change (a call is under way)."""
        mode = p.get("mode", MODE_VARA_FM)
        switched = self._switch_mode(mode)
        if mode != self.config.mode:
            return None
        self._active_profile = p
        self._update_title()
        self.target_input.setCurrentText(p.get("target_callsign", ""))
        self._set_via(self.via1_input, p.get("via1", ""))
        self._set_via(self.via2_input, p.get("via2", ""))
        self._apply_profile_bandwidth(p)
        self._sync_aether_monitor()
        self._update_ui_state()
        return switched

    # ── Session logging ────────────────────────────────────────────

    def _start_session_log(self, remote: str):
        try:
            logs_dir = self.config.logs_dir
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            filename = f"{timestamp}_{remote}.log"
            self._session_log_file = open(logs_dir / filename, "w", encoding="utf-8")
            self._session_log_file.write(
                f"{APP_NAME} Session Log\n"
                f"Date: {datetime.now().isoformat()}\n"
                f"Station: {self._effective_callsign()}\n"
                f"Remote: {remote}\n"
                f"Mode: {self.config.get('vara_mode')}\n"
                f"{'─' * 60}\n\n"
            )
            log.info(f"Session log started: {filename}")
        except Exception as e:
            log.error(f"Failed to start session log: {e}")

    def _log_line(self, text: str):
        if self._session_log_file:
            try:
                ts = datetime.now().strftime("%H:%M:%S")
                self._session_log_file.write(f"[{ts}] {text}\n")
                self._session_log_file.flush()
            except Exception:
                pass

    def _close_session_log(self):
        if self._session_log_file:
            try:
                self._session_log_file.write(
                    f"\n{'─' * 60}\n"
                    f"Session ended: {datetime.now().isoformat()}\n"
                )
            except Exception:
                pass
            finally:
                try:
                    self._session_log_file.close()
                except Exception:
                    pass
                self._session_log_file = None

    # ── Target history ────────────────────────────────────────────

    # ── Via (digipeater) dropdowns ─────────────────────────────────

    def _make_via_combo(self, tooltip: str, current: str) -> QComboBox:
        cb = QComboBox()
        cb.setEditable(True)
        cb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # Its minimum width is set by _fit_via_boxes once it is styled.
        cb.setToolTip(tooltip)
        self._fill_via_combo(cb)
        self._set_via(cb, current)
        return cb

    def _fit_via_boxes(self):
        """Give each Via box room for a full call with SSID ("WD5EMA-15").

        1.1.4 set only a maximum width and the toolbar squeezed the boxes
        until "None" read "one".  The style is asked where the text field
        sits inside the box — the stylesheet's padding and the drop-down
        included — so the width holds on Windows and Fusion alike.
        """
        for cb in (self.via1_input, self.via2_input):
            cb.ensurePolished()
            opt = QStyleOptionComboBox()
            cb.initStyleOption(opt)
            opt.rect = QRect(0, 0, 300, 30)
            field = cb.style().subControlRect(
                QStyle.ComplexControl.CC_ComboBox, opt,
                QStyle.SubControl.SC_ComboBoxEditField, cb)
            overhead = 300 - field.width()
            text = cb.fontMetrics().horizontalAdvance(VIA_WIDTH_SAMPLE)
            cb.setMinimumWidth(text + overhead + 12)   # + the line edit's own margins

    def _fill_via_combo(self, cb: QComboBox):
        cb.clear()
        cb.addItem(VIA_NONE)
        for call in self.config.get("via_history", []):
            if call and isinstance(call, str):
                cb.addItem(call.upper().strip())

    @staticmethod
    def _via_value(cb: QComboBox) -> str:
        """The digipeater in a Via box, "" for None."""
        text = cb.currentText().strip().upper()
        return "" if text in ("", VIA_NONE.upper()) else text

    @staticmethod
    def _set_via(cb: QComboBox, value: str):
        value = (value or "").strip().upper()
        if not value:
            cb.setCurrentIndex(0)           # None
        else:
            i = cb.findText(value)
            if i >= 0:
                cb.setCurrentIndex(i)
            else:
                cb.setCurrentText(value)

    def _remember_via(self, via1: str, via2: str):
        """Keep this call's Via choices (None too) and add new digipeaters
        to both dropdowns, most recent first."""
        history = list(self.config.get("via_history", []))
        for call in (via2, via1):           # via1 ends up first
            if call:
                if call in history:
                    history.remove(call)
                history.insert(0, call)
        self.config.set("via_history", history[:MAX_VIA_HISTORY])
        self.config.set("last_via1", via1)
        self.config.set("last_via2", via2)
        self.config.save()
        for cb, value in ((self.via1_input, via1), (self.via2_input, via2)):
            self._fill_via_combo(cb)
            self._set_via(cb, value)

    def _add_to_target_history(self, callsign: str):
        """Add a callsign to the target dropdown history."""
        try:
            callsign = callsign.upper().strip()
            if not callsign:
                return

            # Get current history (copy to avoid mutating config directly)
            history = list(self.config.get("target_history", []))

            # Move to front if already present, otherwise prepend
            if callsign in history:
                history.remove(callsign)
            history.insert(0, callsign)

            # Cap at 20 entries
            history = history[:20]

            self.config.set("target_history", history)
            self.config.save()
            log.info(f"Target history saved: {history}")

            # Refresh the combo box
            self.target_input.blockSignals(True)
            current = self.target_input.currentText()
            self.target_input.clear()
            for call in history:
                self.target_input.addItem(call)
            self.target_input.setCurrentText(current)
            self.target_input.blockSignals(False)
        except Exception as e:
            log.error(f"Failed to save target history: {e}")
            import traceback
            log.error(traceback.format_exc())

    # ── Modem process management ──────────────────────────────────

    # Common VARA install locations (tried in order)
    _VARA_FM_PATHS = [
        r"C:\VARA FM\VARAFM.exe",
        r"C:\VARA FM\VARA FM.exe",
        r"C:\Program Files\VARA FM\VARAFM.exe",
        r"C:\Program Files (x86)\VARA FM\VARAFM.exe",
    ]
    _VARA_HF_PATHS = [
        r"C:\VARA HF\VARA HF.exe",
        r"C:\VARA\VARA.exe",
        r"C:\Program Files\VARA\VARA.exe",
        r"C:\Program Files (x86)\VARA\VARA.exe",
    ]

    def _find_vara_exe(self, configured_path: str, search_paths: list) -> str:
        """Return a valid exe path: configured path if it exists,
        otherwise try common install locations."""
        if configured_path and os.path.isfile(configured_path):
            return configured_path
        for path in search_paths:
            if os.path.isfile(path):
                log.info(f"Auto-detected VARA at: {path}")
                return path
        return configured_path  # return whatever was configured (for error msg)

    def _on_mode_switched(self, index: int):
        """User changed transport mode via the toolbar combo."""
        new_mode = _MODES[index][1] if 0 <= index < len(_MODES) else MODE_VARA_FM
        self._switch_mode(new_mode)

    def _switch_mode(self, new_mode: str) -> bool:
        """Change the transport mode: close the old modem's link and
        program, start the new one (toolbar combo and profiles alike).

        Returns True if the mode changed, False if it was already
        ``new_mode`` or a call is under way (after telling the user).
        """
        old_mode = self.config.mode
        if new_mode == old_mode:
            return False
        if self.modem.state != ConnectionState.DISCONNECTED or self._preflight_pending:
            self.terminal.display.append_warning(
                f"Disconnect before switching to "
                f"{_MODE_LABEL.get(new_mode, new_mode)}.")
            return False

        # 1. Clean up the old modem connection (TCP sockets + state)
        self._connect_in_progress = False
        self._cleanup_timer.stop()
        self.modem.disconnect_from_modem()
        self.ptt.stop()

        # 2. Persist the new mode
        self.config.set("vara_mode", new_mode)
        self.config.save()

        # 3. Terminate old modem process and launch the new one
        self._terminate_modem_processes()
        label = _MODE_LABEL.get(new_mode, new_mode)
        self.terminal.display.append_system(f"Switched to {label}")
        QTimer.singleShot(300, self._launch_modem_processes)

        self._sync_aether_monitor()
        self._update_ui_state()
        return True

    def _launch_modem_processes(self):
        """Launch the modem executable matching the selected mode."""
        if any(p.poll() is None for p in self._modem_procs):
            return          # already started (a mode switch beat the startup launch)
        mode = self.config.mode

        if mode == MODE_AETHER_HF:
            if not self.config.get("aether_auto_launch", False):
                return
            self.aether_query.snapshot(self.config.aether_control_url,
                                       self._launch_aether_unless_running)
            return

        if mode == MODE_AGWPE:
            should_launch = self.config.get("soundmodem_auto_launch", False)
            configured_path = self.config.get("soundmodem_exe_path", "")
            search_paths = []  # no common default paths for soundmodem
            path_key = "soundmodem_exe_path"
            mode_label = "Soundmodem"
        elif mode == MODE_VARA_HF:
            should_launch = self.config.get("vara_hf_auto_launch", True)
            configured_path = self.config.get("vara_hf_exe_path", "")
            search_paths = self._VARA_HF_PATHS
            path_key = "vara_hf_exe_path"
            mode_label = "VARA HF"
        else:
            should_launch = self.config.get("vara_fm_auto_launch", True)
            configured_path = self.config.get("vara_fm_exe_path", "")
            search_paths = self._VARA_FM_PATHS
            path_key = "vara_fm_exe_path"
            mode_label = "VARA FM"

        if not should_launch:
            return

        exe = self._find_vara_exe(configured_path, search_paths)
        proc = self._start_modem_exe(exe, mode_label)
        if proc:
            self.terminal.display.append_system(
                f"Launched {mode_label} modem")
            # Save the working path back to config
            if exe != configured_path:
                self.config.set(path_key, exe)
        else:
            self.terminal.display.append_warning(
                f"{mode_label} modem not found.\n"
                "  Set the executable path in Settings > Modem Configuration.")

    def _launch_aether_unless_running(self, st: AetherStatus):
        """Start Aether HF unless its control API already answers."""
        if not self.config.is_aether:
            return
        if st.reachable:
            self.terminal.display.append_system(
                "Aether HF is already running — not starting another")
            return
        configured = self.config.get("aether_exe_path", "")
        exe = find_aether_exe(configured)
        proc = self._start_modem_exe(exe, "Aether HF")
        if proc:
            self.terminal.display.append_system("Launched Aether HF")
            if exe != configured:
                self.config.set("aether_exe_path", exe)
        else:
            self.terminal.display.append_warning(
                "Aether HF not found.\n"
                "  Install it from " + AETHER_RELEASES_URL + "\n"
                "  or set its path in Settings > Modem Configuration.")

    def _start_modem_exe(self, exe_path: str, label: str) -> Optional[subprocess.Popen]:
        """Start a modem executable and track the process."""
        if not exe_path:
            return None
        if not os.path.exists(exe_path):
            self.terminal.display.append_warning(
                f"{label} executable not found: {exe_path}")
            return None
        try:
            proc = subprocess.Popen([exe_path], shell=False)
            self._modem_procs.append(proc)
            log.info(f"Launched {label}: {exe_path} (PID {proc.pid})")
            return proc
        except Exception as e:
            self.terminal.display.append_error(
                f"Failed to launch {label}: {e}")
            return None

    def _terminate_modem_processes(self):
        """Terminate all modem processes we launched.

        Uses ``taskkill /F /T`` on Windows to kill the entire process
        tree, since VARA FM/HF may spawn child processes that survive
        a simple ``proc.terminate()``.
        """
        for proc in self._modem_procs:
            if proc.poll() is None:  # still running
                try:
                    pid = proc.pid
                    log.info(f"Terminating modem process PID {pid}")
                    if os.name == "nt":
                        # Kill entire process tree on Windows
                        subprocess.call(
                            ["taskkill", "/F", "/T", "/PID", str(pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                    else:
                        proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        log.warning(
                            f"Modem PID {pid} did not exit, killing")
                        proc.kill()
                except Exception as e:
                    log.error(f"Error terminating modem PID {proc.pid}: {e}")
        self._modem_procs.clear()

    # ── Dialogs ────────────────────────────────────────────────────

    def _open_settings(self, tab: int = 0):
        old_mode = self.config.mode
        dlg = SettingsDialog(self.config, self)
        if hasattr(dlg, 'tabs'):
            dlg.tabs.setCurrentIndex(tab)
        if dlg.exec():
            # Apply font changes
            self.terminal.set_font_size(self.config.get("font_size", 11))
            self.terminal.display.set_font_family(
                self.config.get("font_family", "Consolas"))
            self._refresh_macros()

            # If mode changed in settings, relaunch the modem
            new_mode = self.config.get("vara_mode", "VARA FM")
            if new_mode != old_mode:
                self._terminate_modem_processes()
                self.terminal.display.append_system(f"Switched to {new_mode}")
                QTimer.singleShot(300, self._launch_modem_processes)

            self._sync_aether_monitor(restart=True)
            self._update_ui_state()

    def _open_passwords(self):
        dlg = PasswordDialog(
            self.passwords, self,
            effective_callsign=self._effective_callsign(),
        )
        dlg.exec()

    def _open_profiles(self):
        dlg = ProfileDialog(self.config, self)
        dlg.profile_connect.connect(self._connect_from_profile)
        dlg.exec()
        self._refresh_profiles()

    def _connect_from_profile(self, profile: dict):
        switched = self._apply_profile(profile)
        if switched is None:
            return                          # a call is under way
        delay = 200
        if switched and self._auto_launch_on():
            # The modem program just launched needs a few seconds to listen
            delay = MODEM_START_DELAY_MS
            self.terminal.display.append_system(
                f"Waiting {MODEM_START_DELAY_MS // 1000} s for the modem to start...")
        QTimer.singleShot(delay, self._on_connect)

    def _auto_launch_on(self) -> bool:
        """Whether Aether Term starts the current mode's modem program."""
        key, default = {
            MODE_AETHER_HF: ("aether_auto_launch", False),
            MODE_AGWPE: ("soundmodem_auto_launch", False),
            MODE_VARA_HF: ("vara_hf_auto_launch", True),
        }.get(self.config.mode, ("vara_fm_auto_launch", True))
        return bool(self.config.get(key, default))

    def _show_about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
            f"<h2>{APP_NAME} v{APP_VERSION}</h2>"
            f"<p>{APP_TAGLINE}</p>"
            f"<p>A modern terminal for connecting to amateur radio BBS systems "
            f"over VARA FM, VARA HF, the open-source Aether HF modem, "
            f"and AGWPE packet TNCs.</p>"
            f"<p><b>Features:</b><br>"
            f"• HMAC-SHA256 challenge-response authentication<br>"
            f"• Password never transmitted over RF<br>"
            f"• Aether HF integration: live modem status, rules and fault checks<br>"
            f"• VARA FM and HF support with digipeater routing<br>"
            f"• Connection profiles and macro buttons</p>"
            f"<p>Formerly <i>VARA Term</i>. "
            f"<a href='https://github.com/KK4ODA/aether-term'>github.com/KK4ODA/aether-term</a></p>"
            f"<p>Built with Python and PyQt6.</p>"
        )

    def _show_commands_ref(self):
        QMessageBox.information(self, "BBS Commands Reference",
            "<h3>Messages</h3>"
            "<table>"
            "<tr><td><b>L</b></td><td>List messages</td></tr>"
            "<tr><td><b>R #</b></td><td>Read message by number</td></tr>"
            "<tr><td><b>S call</b></td><td>Send local message (RF pickup)</td></tr>"
            "<tr><td><b>SW call</b></td><td>Send via Winlink CMS</td></tr>"
            "<tr><td><b>S user@addr</b></td><td>Send email via Winlink</td></tr>"
            "<tr><td><b>K #</b></td><td>Delete message</td></tr>"
            "<tr><td><b>KA</b></td><td>Delete ALL messages (sysop)</td></tr>"
            "<tr><td><b>U</b></td><td>Your messages</td></tr>"
            "<tr><td><b>N</b></td><td>New messages</td></tr>"
            "</table>"
            "<h3>Bulletins</h3>"
            "<table>"
            "<tr><td><b>LB</b></td><td>List bulletins</td></tr>"
            "<tr><td><b>RB #</b></td><td>Read bulletin</td></tr>"
            "<tr><td><b>SB group</b></td><td>Post bulletin</td></tr>"
            "</table>"
            "<h3>Files</h3>"
            "<table>"
            "<tr><td><b>FL</b></td><td>List files</td></tr>"
            "<tr><td><b>FG area file</b></td><td>Download file</td></tr>"
            "<tr><td><b>FP area file</b></td><td>Upload file</td></tr>"
            "</table>"
            "<h3>Winlink</h3>"
            "<table>"
            "<tr><td><b>WL</b></td><td>Check Winlink CMS for mail</td></tr>"
            "<tr><td><b>WLREG</b></td><td>Register for Winlink email</td></tr>"
            "<tr><td><b>WLOFF</b></td><td>Unregister from Winlink</td></tr>"
            "<tr><td><b>TACTICAL addr</b></td><td>Set tactical address for WL/send</td></tr>"
            "</table>"
            "<h3>Other</h3>"
            "<table>"
            "<tr><td><b>H</b></td><td>Help</td></tr>"
            "<tr><td><b>I</b></td><td>Station info</td></tr>"
            "<tr><td><b>MH</b></td><td>Heard stations</td></tr>"
            "<tr><td><b>CH</b></td><td>Chat with sysop</td></tr>"
            "<tr><td><b>B</b></td><td>Disconnect</td></tr>"
            "</table>"
        )

    def _send_auth_response(self, response: str):
        """Send auth response after a brief delay for VARA FM turnaround."""
        if self.modem.state == ConnectionState.CONNECTED:
            self.modem.send_data(response)
            log.info("Sent HMAC auth response (after turnaround delay)")
        else:
            log.warning("Auth response not sent — no longer connected")

    # ── Aether HF ──────────────────────────────────────────────────

    def _apply_profile_bandwidth(self, profile: dict):
        """Set the HF bandwidth a profile asks for, for its modem."""
        mode = profile.get("mode", MODE_VARA_FM)
        if mode == MODE_VARA_FM:
            self.config.set("fm_bandwidth", profile.get("fm_bandwidth", "WIDE"))
        elif mode == MODE_VARA_HF:
            self.config.set("hf_bandwidth", profile.get("bandwidth", 500))
        elif mode == MODE_AETHER_HF:
            bw = 500 if int(profile.get("bandwidth", 2300)) == 500 else 2300
            self.config.set("aether_bandwidth", bw)

    def _sync_aether_monitor(self, restart: bool = False):
        """Run the status monitor only while Aether HF is the selected modem."""
        if self.config.is_aether:
            if restart or not self.aether.running:
                self.aether.start(self.config.aether_control_url)
            self.aether_label.setText("Aether: checking...")
            self.aether_label.show()
        else:
            self.aether.stop()
            self.aether_label.hide()

    @pyqtSlot(object)
    def _on_aether_status(self, st: AetherStatus):
        if not self.config.is_aether:
            return
        self.aether_label.setText(st.summary)
        if not st.reachable:
            color = C["text_dim"]
        elif st.problems:
            color = C["error"]
        elif st.transmitting:
            color = C["warning"]
        else:
            color = C["success"]
        self.aether_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def _aether_preflight_ok(self, st: AetherStatus) -> bool:
        """Check Aether HF can take the call. Returns False to stop here.

        The VARA command set cannot say *why* a modem refuses a call, so
        the control API is asked first: a host port that is switched off,
        no rules chosen, or a keying fault are reported in plain words
        before anything is sent.
        """
        if not st.reachable:
            self.terminal.display.append_warning(
                "[AETHER] Control API not reachable at "
                f"{self.config.aether_control_url} — connecting over the "
                "host port without status checks.")
            return True
        self.terminal.display.append_system(f"[AETHER] {st.summary}")
        if st.state in ("connecting", "connected", "disconnecting"):
            self.terminal.display.append_warning(
                f"[AETHER] The modem is busy ({st.state}"
                f"{' with ' + st.remote if st.remote else ''}) — "
                "a session started from its own panel is not this program's to end.")
        stop = False
        for problem in st.problems:
            self.terminal.display.append_error(f"[AETHER] {problem}")
            stop = True
        if stop:
            self.terminal.display.append_warning(
                "[AETHER] Not connecting. Fix the above in Aether HF and try again.")
            self._connect_in_progress = False
        return not stop

    def _explain_aether_no_session(self):
        """The call ended without a session — say why, if the modem knows."""
        target = self._target or "the target"
        self.aether_query.snapshot(
            self.config.aether_control_url,
            lambda st: self._explain_aether_no_session_with(st, target))

    def _explain_aether_no_session_with(self, st: AetherStatus, target: str):
        problems = st.problems if st.reachable else []
        if problems:
            for p in problems:
                self.terminal.display.append_error(f"[AETHER] {p}")
            return
        self.terminal.display.append_warning(
            f"[AETHER] No session with {target}. Aether HF talks only to other\n"
            "  Aether HF stations, on the same bandwidth and link protocol\n"
            "  version. Its log (Log tab) has the reason for every refused call.")

    @pyqtSlot(str)
    def _on_version_report(self, version: str):
        self.modem_status_label.setText(f"Modem: {version}")
        if self.config.is_aether and "aether" not in version.lower():
            self.terminal.display.append_warning(
                f"[AETHER] The modem on this port reports \"{version}\", not "
                "Aether HF. Close it, or point Aether Term at Aether HF's port.")
        elif self.config.is_aether:
            self.terminal.display.append_success(f"[AETHER] Modem: {version}")

    def _show_aether_status(self):
        self.aether_query.snapshot(self.config.aether_control_url,
                                   self._show_aether_status_with)

    def _show_aether_status_with(self, st: AetherStatus):
        url = self.config.aether_control_url
        if not st.reachable:
            QMessageBox.information(
                self, "Aether HF",
                f"<p>Aether HF is not reachable at <code>{url}</code>.</p>"
                f"<p>Start Aether HF, or download it from "
                f"<a href='{AETHER_RELEASES_URL}'>{AETHER_RELEASES_URL}</a>.</p>")
            return
        rows = [
            ("Version", st.version),
            ("State", st.state + (f" with {st.remote}" if st.remote else "")),
            ("Callsign", st.callsign or "(none)"),
            ("Bandwidth", f"{st.bandwidth_hz} Hz" if st.bandwidth_hz else "?"),
            ("Rung", st.rung_name or (str(st.mode) if st.mode is not None else "—")),
            ("Host port", ("on" if st.host_enabled else "OFF")
             + (", in use" if st.host_connected else "")),
            ("Keying", st.ptt or "?"),
            ("Rules", f"{st.regulatory_policy or '?'} — "
                      f"{st.regulatory_summary or st.regulatory_verdict or ''}"),
            ("Channel", "busy" if st.channel_busy else "clear"),
        ]
        html = "<table>" + "".join(
            f"<tr><td><b>{k}</b>&nbsp;&nbsp;</td><td>{v}</td></tr>" for k, v in rows
        ) + "</table>"
        if st.problems:
            html += "<p><b>Needs attention:</b><br>" + "<br>".join(
                f"• {p}" for p in st.problems) + "</p>"
        QMessageBox.information(self, "Aether HF Status", html)

    def _open_aether_panel(self):
        QDesktopServices.openUrl(QUrl(self.config.aether_control_url + "/"))

    # ── Transport switching ─────────────────────────────────────────

    def _swap_modem_agwpe(self):
        """Replace the current modem with an AGWPEModem if not already."""
        from vara.agwpe_modem import AGWPEModem
        if isinstance(self.modem, AGWPEModem):
            return
        self._retire_modem()
        self.modem = AGWPEModem()
        self._connect_signals()

    def _swap_modem_vara(self):
        """Replace the current modem with a VARAModem if not already."""
        if isinstance(self.modem, VARAModem):
            return
        self._retire_modem()
        self.modem = VARAModem()
        self._connect_signals()

    def _retire_modem(self):
        """Close the modem being replaced, without its signals reaching us.

        Its last "disconnected" would otherwise arrive after the new modem
        has started a call, clear the connect-in-progress flag, and let the
        cleanup close the new link (switching to Soundmodem and pressing
        Connect did exactly that).
        """
        old = self.modem
        for name in _MODEM_SIGNALS:
            sig = getattr(old, name, None)
            if sig is not None:
                try:
                    sig.disconnect()
                except TypeError:
                    pass                    # nothing connected
        old.disconnect_from_modem()

    # ── Transport detection ──────────────────────────────────────────

    def _query_transport(self):
        """Send ;TRANSPORT? to detect the BBS transport type."""
        self.modem.send_data(";TRANSPORT?\r\n")

    def _handle_transport_response(self, line: str) -> bool:
        """Check if a line is a ;TRANSPORT response.  Returns True if handled."""
        if line.startswith(";TRANSPORT "):
            self.terminal.display.append_system(
                f"BBS transport: {line[11:].strip()}")
            return True
        return False

    # ── Tactical address ──────────────────────────────────────────────

    def _send_tactical_if_configured(self):
        """Send ;TACTICAL <call> after auth success if profile has one."""
        tactical = ""
        if self._active_profile:
            tactical = self._active_profile.get("tactical_callsign", "").upper().strip()
        if not tactical:
            tactical = self.config.get("tactical_callsign", "").upper().strip()
        if tactical:
            cmd = f";TACTICAL {tactical}\r\n"
            QTimer.singleShot(2000, lambda: self._send_tactical_cmd(cmd))

    def _send_tactical_cmd(self, cmd: str):
        if self.modem.state == ConnectionState.CONNECTED:
            self.modem.send_data(cmd)
            log.info(f"Sent tactical address command: {cmd.strip()}")

    def _handle_tactical_response(self, line: str) -> bool:
        """Check if a line is a ;TACTICAL response.  Returns True if handled."""
        if line.startswith(";TACTICAL OK"):
            detail = line[12:].strip()
            if detail and detail.lower() != "cleared":
                self.terminal.display.append_success(
                    f"[TACTICAL] Address activated: {detail}")
            else:
                self.terminal.display.append_system("[TACTICAL] Address cleared")
            return True
        if line.startswith(";TACTICAL FAIL"):
            reason = line[14:].strip()
            self.terminal.display.append_warning(
                f"[TACTICAL] Rejected: {reason}")
            return True
        return False

    # ── Chat / converse mode indicator ────────────────────────────────

    def _check_chat_enter(self, line: str):
        """Detect entry into a chat room and show indicator."""
        if "Joined room" in line and "Type /EXIT" in line:
            # Extract room name: "Joined room ROOMNAME. N user(s) here."
            try:
                room = line.split("Joined room")[1].split(".")[0].strip()
            except (IndexError, ValueError):
                room = "CHAT"
            self._chat_room = room
            self._chat_label.setText(f"CHAT: {room}")
            self._chat_label.show()

    def _check_chat_exit(self, line: str):
        """Detect exit from a chat room and clear indicator."""
        if self._chat_room and ("left the room" in line.lower()
                                or "Chat ended" in line
                                or line.strip().startswith("*** Left")):
            self._chat_room = ""
            self._chat_label.hide()

    # ── Software update ────────────────────────────────────────────

    def set_updater(self, updater):
        """Called by main.py after construction to wire the updater."""
        self._updater = updater
        self._manual_update_check = False
        self._updater.update_available.connect(
            self._on_update_available, Qt.ConnectionType.QueuedConnection,
        )
        self._updater.check_finished.connect(
            self._on_update_check_finished, Qt.ConnectionType.QueuedConnection,
        )

    def start_update_check(self, manual: bool = False):
        """Check for a newer version in the background.

        At startup (manual=False) a found update is offered in a dialog
        unless the user skipped that version; a manual check also reports
        "up to date" and errors.
        """
        if not self._updater:
            return
        self._manual_update_check = manual
        self._updater.check_once_async()

    def _on_update_available(self, check_result):
        self._pending_update = check_result
        self._update_label.setText(check_result.label)
        self._update_label.show()

    def _on_update_check_finished(self, result):
        manual = self._manual_update_check
        self._manual_update_check = False
        if result.update_available:
            skipped = self.config.get("skipped_update_version", "")
            if manual:
                self._show_update_dialog()
            elif (result.version_key != skipped
                  and self.modem.state == ConnectionState.DISCONNECTED):
                # Don't interrupt a session; the status-bar label stays
                self._show_update_dialog()
        elif manual:
            if result.error:
                QMessageBox.warning(self, "Software Update",
                                    f"Could not check for updates:\n{result.error}")
            else:
                QMessageBox.information(
                    self, "Software Update",
                    f"Aether Term {APP_VERSION} is the latest version.")

    def _show_update_dialog(self):
        if not self._updater or not self._pending_update:
            return
        from gui.update_dialog import UpdateDialog
        dlg = UpdateDialog(
            self._pending_update,
            self._updater,
            self._restart,
            parent=self,
            config=self.config,
            quit_callback=self._quit_for_update,
        )
        dlg.exec()

    def _check_for_updates(self):
        """Manual 'Check for Updates' from Help menu."""
        if not self._updater:
            QMessageBox.information(self, "Updates", "Updater not available.")
            return
        self.status_bar.showMessage("Checking for updates...", 5000)
        self.start_update_check(manual=True)

    def _quit_for_update(self):
        """Close so the installer can replace the program files."""
        self._on_disconnect()
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _restart(self):
        """Graceful restart: launch a new process and exit."""
        import subprocess as _sp
        args = [sys.executable] + sys.argv
        _sp.Popen(args, cwd=os.path.dirname(os.path.abspath(sys.argv[0])))
        from PyQt6.QtWidgets import QApplication
        QApplication.instance().quit()

    # ── Welcome ────────────────────────────────────────────────────

    def _show_welcome(self):
        self.terminal.display.append_text(
            "\n"
            f"  {APP_NAME}  --  {APP_TAGLINE}\n"
            f"  Version {APP_VERSION}\n"
            "  -----------------------------------\n"
            "\n",
            "cyan"
        )
        self.terminal.display.append_text(
            "  Configure your callsign in Settings > Terminal Setup\n"
            "  Enter the target BBS callsign above and click Connect\n"
            "\n"
            "  HMAC-SHA256 authentication is automatic when\n"
            "  a password is saved for the target station.\n"
            "\n",
            "normal"
        )

        for problem in (self.config.load_error, self.passwords.load_error):
            if problem:
                self.terminal.display.append_error(f"  {problem}\n")

        if not self.config.get("my_callsign"):
            self.terminal.display.append_warning(
                "  No callsign configured. Go to Settings > Terminal Setup.\n")

        # Show loaded target history for diagnostics
        history = self.config.get("target_history", [])
        if history:
            self.terminal.display.append_text(
                f"  Recent stations: {', '.join(history)}\n\n", "dim")

        # Check OmniRig availability (when it is the HF PTT method)
        self._check_omnirig()

    def _check_omnirig(self):
        """Check OmniRig availability at startup when it is the PTT method."""
        if self.config.get("hf_ptt_method") != PTT_OMNIRIG:
            return
        try:
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()
            try:
                omnirig = win32com.client.Dispatch("OmniRig.OmniRigX")
                ver = getattr(omnirig, "SoftwareVersion", "")
                self.terminal.display.append_success(
                    f"  OmniRig detected{f' (v{ver})' if ver else ''} — HF PTT ready\n")
            except Exception:
                self.terminal.display.append_warning(
                    "  OmniRig not running — start OmniRig for HF PTT control\n")
            finally:
                pythoncom.CoUninitialize()
        except ImportError:
            self.terminal.display.append_warning(
                "  pywin32 not installed — OmniRig PTT unavailable\n"
                "  Install with: pip install pywin32\n")

    # ── Cleanup ────────────────────────────────────────────────────

    def closeEvent(self, event):
        """Clean up on window close."""
        self._cleanup_timer.stop()
        self.aether.stop()
        if self.ptt.is_enabled:
            self.ptt.stop()
        if self.modem.state != ConnectionState.DISCONNECTED:
            self.modem.disconnect_from_modem()
        self._close_session_log()
        self._terminate_modem_processes()
        self.config.save()
        event.accept()
