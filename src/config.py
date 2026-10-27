"""
config.py — Configuration management for Aether Term.

Loads/saves settings from a JSON file in the user's app data directory.
"""

import copy
import json
import os
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

log = logging.getLogger(__name__)

APP_NAME = "Aether Term"

# The name this application shipped under before the rebrand. Settings,
# passwords and downloaded Hamlib binaries are carried over from its data
# directory the first time Aether Term starts.
LEGACY_APP_NAME = "VARA Term"

# Transport modes (the ``vara_mode`` setting)
MODE_VARA_FM = "VARA FM"
MODE_VARA_HF = "VARA HF"
MODE_AETHER_HF = "Aether HF"
MODE_AGWPE = "AGWPE"
MODE_LOCAL_TEST = "Local test"   # play VARA FM for a BBS on this PC, no radio
MODE_KISS = "KISS TNC"           # a KISS TNC: Bluetooth / USB radio, BLE, Direwolf

# HF PTT methods (the ``hf_ptt_method`` setting), as shown in Settings
PTT_VOX = "None (VOX)"
PTT_OMNIRIG = "OmniRig"
PTT_HAMLIB = "Hamlib (rigctld)"
PTT_FLRIG = "FLrig"
PTT_METHODS = (PTT_VOX, PTT_OMNIRIG, PTT_HAMLIB, PTT_FLRIG)


def _read_version() -> str:
    """Read version from version.txt at the project root.

    Tries parent of this file's directory (src/ → project root),
    then the file's own directory (for frozen builds where files
    may be flattened), then falls back to a default.
    """
    for base in (Path(__file__).parent.parent, Path(__file__).parent):
        vf = base / "version.txt"
        if vf.is_file():
            try:
                return vf.read_text(encoding="utf-8").strip()
            except Exception:
                pass
    return "0.0.0"


APP_VERSION = _read_version()

def _app_data_base() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return Path.home() / ".config"


def _app_data_dir() -> Path:
    """Return the platform-appropriate app data directory.

    On first run after the rebrand, the old VARA Term data directory
    (settings, encrypted passwords, Hamlib download) is copied across so
    nothing has to be configured again.  The old directory is left alone.
    """
    base = _app_data_base()
    d = base / APP_NAME
    legacy = base / LEGACY_APP_NAME
    if not d.exists() and legacy.is_dir():
        try:
            shutil.copytree(legacy, d)
            log.info(f"Migrated settings from {legacy} to {d}")
        except Exception as e:
            log.warning(f"Could not migrate settings from {legacy}: {e}")
    d.mkdir(parents=True, exist_ok=True)
    return d


def atomic_write(path: Path, data: bytes):
    """Write *data* to *path* through a temporary file, so a crash or a
    full disk mid-write leaves the old file instead of half a new one."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def set_aside(path: Path) -> Path:
    """Rename a file that could not be read out of the way, so the next
    save does not overwrite it.  Returns where it went."""
    dest = path.with_name(f"{path.name}.unreadable-{datetime.now():%Y%m%d-%H%M%S}")
    path.replace(dest)
    return dest


def _logs_dir() -> Path:
    d = Path.home() / APP_NAME / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULT_MACROS: List[Dict[str, str]] = [
    {"label": "Help", "command": "H"},
    {"label": "List Mine", "command": "L"},
    {"label": "Read New", "command": "N"},
    {"label": "List Bull", "command": "LB"},
    {"label": "List Files", "command": "FL"},
    {"label": "Bye", "command": "B"},
]


DEFAULT_SETTINGS: Dict[str, Any] = {
    # Identity
    "my_callsign": "",
    "my_ssid": 0,

    # Transport mode: "VARA FM", "VARA HF", "Aether HF", "AGWPE" or
    # "Local test"
    "vara_mode": "VARA FM",

    # VARA FM modem
    "vara_fm_host": "127.0.0.1",
    "vara_fm_cmd_port": 8300,
    "vara_fm_data_port": 8301,
    "vara_fm_auto_launch": True,
    "vara_fm_exe_path": r"C:\VARA FM\VARAFM.exe",

    # VARA HF modem
    "vara_hf_host": "127.0.0.1",
    "vara_hf_cmd_port": 8300,
    "vara_hf_data_port": 8301,
    "vara_hf_auto_launch": True,
    "vara_hf_exe_path": r"C:\VARA HF\VARA HF.exe",

    # Aether HF modem (https://github.com/KK4ODA/aether-hf) — its
    # VARA-compatible host port, plus its own control API for status
    "aether_host": "127.0.0.1",
    "aether_cmd_port": 8300,
    "aether_data_port": 8301,
    "aether_control_port": 8515,
    "aether_auto_launch": False,
    "aether_exe_path": "",          # empty = look in the default install folder
    "aether_bandwidth": 2300,       # 500 / 2300 — both stations must match
    "aether_host_ptt": False,       # True when Aether's keying is "host program"

    # RF settings
    "hf_bandwidth": 500,  # 500 / 2300 / 2750
    # VARA HF retry cycle: "P2P" for calls to a BBS or station (VARA's
    # reference: P2P SESSION "must be used for P2P connections"),
    # "WINLINK" for Winlink gateways (VARA's own default)
    "hf_session": "P2P",
    "fm_bandwidth": "WIDE",  # NARROW / WIDE
    "max_retries": 5,

    # Soundmodem (AGWPE) — alternative transport
    "soundmodem_host": "127.0.0.1",
    "soundmodem_port": 8000,
    "soundmodem_auto_launch": False,
    "soundmodem_exe_path": "",

    # Local test (no radio): Aether Term listens on 127.0.0.1 as a VARA FM
    # modem for a BBS instance on this PC.  Not 8300/8301: VARA uses those.
    "local_test_cmd_port": 8500,
    "local_test_data_port": 8501,
    "local_test_callsign": "",      # who to connect as; "" = my callsign

    # KISS TNC: a radio's built-in TNC (TH-D74/D75 ...) or any KISS TNC.
    # Aether Term runs the AX.25 connection itself.
    "kiss_link": "serial",          # serial (USB / Bluetooth COM port) / ble / tcp
    "kiss_serial_port": "",         # e.g. COM5
    "kiss_serial_baud": 9600,
    "kiss_ble_address": "",         # Bluetooth LE device address
    "kiss_ble_name": "",            # its name, for display
    "kiss_ble_service": "",         # "" = the standard KISS-over-BLE service
    "kiss_tcp_host": "127.0.0.1",
    "kiss_tcp_port": 8001,          # Direwolf's KISS port
    "kiss_port": 0,                 # TNC port (radio port) number
    "kiss_send_params": True,       # send TXDELAY / persistence / slot time
    "kiss_txdelay": 300,            # ms
    "kiss_persistence": 63,
    "kiss_slottime": 100,           # ms
    "kiss_init": "",                # text commands sent first (TNC2-style TNCs)
    "ax25_paclen": 128,             # bytes per frame
    "ax25_maxframe": 4,             # frames sent before an acknowledgement
    "ax25_frack": 7,                # retry timer, seconds (x path length)
    "ax25_retries": 10,

    # PTT (HF only — FM handles PTT internally)
    "hf_ptt_method": "OmniRig",  # one of PTT_METHODS
    "omnirig_rig_number": 1,  # OmniRig Rig 1 or 2
    "flrig_host": "127.0.0.1",
    "flrig_port": 12345,

    # Terminal appearance
    "font_family": "Consolas",
    "font_size": 11,

    # Auth
    "auto_respond_hmac": True,
    "show_auth_protocol": False,

    # Session
    "session_logging": True,
    "show_ptt_events": False,  # hide PTT ON/OFF from terminal by default
    "target_history": [],  # recently connected callsigns (most recent first)
    "via_history": [],     # digipeaters used before (most recent first)
    "last_via1": "",       # Via 1 / Via 2 of the last call ("" = None)
    "last_via2": "",

    # Macros
    "macros": DEFAULT_MACROS,

    # Connection profiles
    "profiles": [],

    # Software updates
    "check_updates_on_startup": True,
    "update_branch": "main",
}


class Config:
    """Application configuration backed by a JSON file."""

    def __init__(self):
        self._dir = _app_data_dir()
        self._path = self._dir / "settings.json"
        # Deep copy: the default lists (profiles, macros) must not be shared
        self._data: Dict[str, Any] = copy.deepcopy(DEFAULT_SETTINGS)
        self.load_error = ""      # set when settings.json could not be read
        self.load()

    # ── persistence ─────────────────────────────────────────────────

    def load(self):
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if not isinstance(saved, dict):
                    raise ValueError("not a settings object")
                # Merge saved over defaults so new keys get defaults
                for k, v in saved.items():
                    self._data[k] = v
                log.info(f"Config loaded from {self._path}")
                log.debug(f"Loaded target_history: {self._data.get('target_history', [])}")
            except (OSError, ValueError) as e:
                # Starting from defaults is unavoidable; overwriting the
                # user's file with them at the next save is not.
                kept = set_aside(self._path)
                self.load_error = f"Settings could not be read ({e}); kept as {kept.name}"
                log.error(self.load_error)
        self._migrate()

    def save(self):
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            atomic_write(self._path, json.dumps(self._data, indent=2).encode("utf-8"))
            log.info(f"Config saved to {self._path}")
        except OSError as e:
            log.error(f"Failed to save config to {self._path}: {e}")

    def _migrate(self):
        """Apply one-time config migrations for new defaults."""
        changed = False

        # v1.0 → v1.1: auto-launch defaults changed from False/empty to
        # True/path.  Once only: a path the user clears later stays cleared.
        if not self._data.get("exe_paths_migrated"):
            for modem in ("vara_fm", "vara_hf"):
                if not self._data.get(f"{modem}_exe_path"):
                    self._data[f"{modem}_exe_path"] = DEFAULT_SETTINGS[f"{modem}_exe_path"]
                    self._data[f"{modem}_auto_launch"] = True
            self._data["exe_paths_migrated"] = True
            changed = True

        # v1.0.1 → v1.0.2: fix macro commands to match BBS help output
        _MACRO_CMD_FIX = {"LM": "L", "RM": "N", "LF": "FL", "BYE": "B"}
        macros = self._data.get("macros", [])
        for macro in macros:
            old_cmd = macro.get("command", "")
            if old_cmd in _MACRO_CMD_FIX:
                macro["command"] = _MACRO_CMD_FIX[old_cmd]
                changed = True

        # v1.1 → v1.2: add operator identity fields to existing profiles
        for profile in self._data.get("profiles", []):
            if "my_callsign" not in profile:
                profile["my_callsign"] = ""
                profile["my_ssid"] = 0
                changed = True
            if "tactical_callsign" not in profile:
                profile["tactical_callsign"] = ""
                changed = True
            if "fm_bandwidth" not in profile:
                profile["fm_bandwidth"] = "WIDE"
                changed = True

        if changed:
            log.info("Config migrated with updated defaults")
            self.save()

    # ── access ──────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        self._data[key] = value

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any):
        self._data[key] = value

    # ── helpers ─────────────────────────────────────────────────────

    @property
    def full_callsign(self) -> str:
        call = self._data.get("my_callsign", "").upper().strip()
        ssid = self._data.get("my_ssid", 0)
        if ssid and ssid != 0:
            return f"{call}-{ssid}"
        return call

    def profile_full_callsign(self, profile: dict) -> str:
        """Return the effective operator callsign for a profile.

        Falls back to the global ``full_callsign`` when the profile does
        not specify its own operator identity.
        """
        call = profile.get("my_callsign", "").upper().strip()
        if not call:
            return self.full_callsign
        ssid = profile.get("my_ssid", 0)
        if ssid and ssid != 0:
            return f"{call}-{ssid}"
        return call

    @property
    def mode(self) -> str:
        return self._data.get("vara_mode", MODE_VARA_FM)

    @property
    def is_hf(self) -> bool:
        """True for VARA HF only (Aether HF is reported by ``is_aether``)."""
        return self.mode == MODE_VARA_HF

    @property
    def is_aether(self) -> bool:
        return self.mode == MODE_AETHER_HF

    @property
    def is_kiss(self) -> bool:
        return self.mode == MODE_KISS

    @property
    def is_local_test(self) -> bool:
        return self.mode == MODE_LOCAL_TEST

    @property
    def is_hf_band(self) -> bool:
        """True for either HF modem — VARA HF or Aether HF."""
        return self.is_hf or self.is_aether

    @property
    def session_bandwidth(self) -> int:
        """The HF bandwidth to request from the modem (BW500/BW2300/...)."""
        if self.is_aether:
            return int(self._data.get("aether_bandwidth", 2300))
        return int(self._data.get("hf_bandwidth", 500))

    @property
    def vara_session(self) -> str:
        """"P2P" or "WINLINK" for VARA HF (sent as "<x> SESSION"); "" otherwise."""
        if not self.is_hf:
            return ""
        s = str(self._data.get("hf_session", "P2P")).upper()
        return s if s in ("P2P", "WINLINK") else "P2P"

    @property
    def needs_host_ptt(self) -> bool:
        """Whether Aether Term must key the radio on the modem's PTT ON.

        VARA HF always leaves keying to the host. Aether HF keys the radio
        itself unless its keying is set to "host program".
        """
        if self.is_aether:
            return bool(self._data.get("aether_host_ptt", False))
        return self.is_hf

    def _prefix(self) -> str:
        if self.is_aether:
            return "aether"
        return "vara_hf" if self.is_hf else "vara_fm"

    @property
    def modem_host(self) -> str:
        return self._data.get(f"{self._prefix()}_host", "127.0.0.1")

    @property
    def cmd_port(self) -> int:
        return int(self._data.get(f"{self._prefix()}_cmd_port", 8300))

    @property
    def data_port(self) -> int:
        return int(self._data.get(f"{self._prefix()}_data_port", 8301))

    @property
    def aether_control_url(self) -> str:
        host = self._data.get("aether_host", "127.0.0.1")
        port = int(self._data.get("aether_control_port", 8515))
        return f"http://{host}:{port}"

    @property
    def logs_dir(self) -> Path:
        return _logs_dir()

    @property
    def app_data_dir(self) -> Path:
        return self._dir

    # ── profiles ────────────────────────────────────────────────────

    def get_profiles(self) -> List[Dict[str, Any]]:
        return self._data.get("profiles", [])

    def add_profile(self, profile: Dict[str, Any]):
        profiles = self.get_profiles()
        profiles.append(profile)
        self._data["profiles"] = profiles

    def remove_profile(self, index: int):
        profiles = self.get_profiles()
        if 0 <= index < len(profiles):
            profiles.pop(index)
            self._data["profiles"] = profiles

    # ── macros ──────────────────────────────────────────────────────

    def get_macros(self) -> List[Dict[str, str]]:
        return self._data.get("macros", DEFAULT_MACROS)

    def set_macros(self, macros: List[Dict[str, str]]):
        self._data["macros"] = macros
