"""
aether/control.py — Client for the Aether HF modem's control API.

Aether Term talks to Aether HF through two interfaces:

* the VARA-compatible host port (TCP 8300/8301), handled by
  ``vara.modem.VARAModem`` exactly as for VARA HF — that carries the
  session and the BBS traffic;
* the modem's own control API (HTTP ``POST /v1/<method>`` on 8515),
  handled here — that tells the operator what the modem is doing and why
  it refused something, which the VARA command set has no words for.

Spec: https://github.com/KK4ODA/aether-hf/blob/master/docs/spec/control-api.md

Only read-only methods are used (``status``, ``capabilities``, and
``config.get`` to learn who keys the radio).  A loopback connection needs no
token; nothing here changes the modem's settings.
"""

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 2.0   # seconds — the API is local and answers at once
POLL_INTERVAL = 2.0     # seconds between status polls while watched

AETHER_RELEASES_URL = "https://github.com/KK4ODA/aether-hf/releases"
AETHER_HOST_GUIDE_URL = (
    "https://github.com/KK4ODA/aether-hf/blob/master/docs/user/host-programs.md")


class AetherControlError(Exception):
    """The control API could not be reached or refused the request."""


def default_exe_paths() -> List[str]:
    """Where the Aether HF desktop application is installed by default.

    The Windows installer is per-user, under ``%LOCALAPPDATA%\\Aether HF``.
    """
    paths = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        paths.append(str(Path(local) / "Aether HF" / "aether-hf.exe"))
    paths.append(str(Path.home() / "AppData" / "Local" / "Aether HF" / "aether-hf.exe"))
    return paths


def find_aether_exe(configured: str = "") -> str:
    """Return the configured path if it exists, else the default install path."""
    if configured and os.path.isfile(configured):
        return configured
    for p in default_exe_paths():
        if os.path.isfile(p):
            return p
    return configured


# ── Status snapshot ────────────────────────────────────────────────

@dataclass
class AetherStatus:
    """The parts of the modem's ``status`` that Aether Term shows."""

    reachable: bool = False
    error: str = ""
    version: str = ""
    state: str = ""                  # idle / connecting / connected / disconnecting
    callsign: str = ""
    remote: str = ""
    mode: Optional[int] = None       # rung index of the running ladder
    rung_name: str = ""
    bandwidth_hz: Optional[int] = None
    host_enabled: bool = False       # the VARA-compatible port is switched on
    host_connected: bool = False     # a host program holds it
    answering: bool = True
    transmitting: bool = False
    channel_busy: bool = False
    ptt: str = ""
    ptt_fault: str = ""
    audio_fault: str = ""
    regulatory_policy: str = ""      # rules / none / unset / broken
    regulatory_verdict: str = ""     # legal / warning / blocked
    regulatory_summary: str = ""
    host_port: Optional[int] = None  # the port the host interface listens on
    host_callsigns: List[str] = field(default_factory=list)  # held by the attached program
    air: str = ""                    # "hf" or "fm" (Aether FM, later); "" = not said
    mismatch: Dict[str, Any] = field(default_factory=dict)   # status.bandwidth.mismatch
    ptt_kind: str = ""               # [ptt] kind from config.get: host, cat, … ("" unknown)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def host_keyed(self) -> Optional[bool]:
        """Whether Aether HF leaves keying to the host program (None = unknown)."""
        if self.ptt_kind:
            return self.ptt_kind == "host"
        if self.ptt:
            # The daemon's own description of host keying (ptt.rs, HostKeyed)
            return self.ptt.lower().startswith("the host program")
        return None

    @property
    def problems(self) -> List[str]:
        """Operator-facing reasons the modem would not connect or transmit."""
        out = []
        if not self.reachable:
            return out
        if self.air and self.air != "hf":
            out.append(
                f"This Aether modem runs the \"{self.air}\" air, not HF. "
                "Aether Term's Aether HF mode needs Aether HF.")
        if not self.host_enabled:
            out.append(
                "The VARA-compatible host interface is off. In Aether HF, "
                "Setup step 5, turn on \"Host programs\" (port 8300).")
        if self.regulatory_policy == "unset":
            out.append(
                "No rules are chosen, so Aether HF transmits nothing. "
                "Complete Setup step 1 in Aether HF.")
        elif self.regulatory_policy == "broken":
            out.append("Aether HF's regulatory profile would not load — "
                       "nothing is transmitted. See its Setup step 1.")
        elif self.regulatory_verdict == "blocked":
            out.append(f"Rules: {self.regulatory_summary or 'TX blocked at this dial'}")
        if self.ptt_fault:
            out.append(f"Keying: {self.ptt_fault}")
        if self.audio_fault:
            out.append(f"Sound card: {self.audio_fault}")
        return out

    @property
    def summary(self) -> str:
        """One line for the status bar."""
        if not self.reachable:
            return "Aether: offline"
        parts = [f"Aether {self.version}".strip()]
        if self.bandwidth_hz:
            parts.append(f"{self.bandwidth_hz} Hz")
        if self.state and self.state != "idle":
            parts.append(self.state)
        if self.state == "connected" and self.rung_name:
            parts.append(self.rung_name)
        if self.regulatory_verdict == "blocked":
            parts.append("TX BLOCKED")
        elif self.ptt_fault or self.audio_fault:
            parts.append("FAULT")
        return " · ".join(parts)

    @classmethod
    def from_status(cls, st: Dict[str, Any],
                    rung_names: Optional[Dict[int, str]] = None) -> "AetherStatus":
        host = st.get("host") or {}
        bw = st.get("bandwidth") or {}
        reg = st.get("regulatory") or {}
        indicator = reg.get("indicator") or {}
        mode = st.get("mode")
        rung_name = ""
        if isinstance(mode, int) and rung_names:
            rung_name = rung_names.get(mode, "")
        host_port = None
        address = str(host.get("command_address") or "")
        if address.rpartition(":")[2].isdigit():
            host_port = int(address.rpartition(":")[2])     # "127.0.0.1:8300", "[::1]:8300"
        host_calls: List[str] = []
        for claim in st.get("claims") or []:
            if isinstance(claim, dict) and claim.get("kind") == "host":
                host_calls += [str(c) for c in claim.get("callsigns") or []]
        mismatch = bw.get("mismatch")
        return cls(
            reachable=True,
            version=str(st.get("version") or ""),
            state=str(st.get("state") or ""),
            callsign=str(st.get("callsign") or ""),
            remote=str(st.get("remote") or ""),
            mode=mode if isinstance(mode, int) else None,
            rung_name=rung_name,
            bandwidth_hz=bw.get("bandwidth_hz"),
            host_enabled=bool(host.get("enabled", False)),
            host_connected=bool(host.get("connected", False)),
            answering=bool(st.get("answering", True)),
            transmitting=bool(st.get("transmitting", False)),
            channel_busy=bool(st.get("channel_busy", False)),
            ptt=str(st.get("ptt") or ""),
            ptt_fault=str(st.get("ptt_fault") or ""),
            audio_fault=str(st.get("audio_fault") or ""),
            regulatory_policy=str(reg.get("policy") or ""),
            regulatory_verdict=str(indicator.get("verdict") or ""),
            regulatory_summary=str(indicator.get("summary") or ""),
            host_port=host_port,
            host_callsigns=host_calls,
            air=str(st.get("air") or "").lower(),
            mismatch=mismatch if isinstance(mismatch, dict) else {},
            raw=st,
        )


def setup_mismatches(st: AetherStatus, cmd_port: int, host_ptt: bool,
                     local: bool = True) -> List[str]:
    """Where Aether Term's settings disagree with the modem's, so a call
    would fail (or go out with nothing keying the radio).

    *cmd_port* and *host_ptt* are Aether Term's command port and its
    "Aether HF keying is host program" box; *local* is whether the modem is
    reached on this computer, where its own host address can be compared.
    """
    out = []
    if not st.reachable:
        return out
    if local and st.host_enabled and st.host_port and st.host_port != cmd_port:
        # Aether HF's Winlink-program finder sets the port a program
        # already used, so it is not always 8300
        out.append(
            f"Aether HF's host port is {st.host_port}, but Aether Term is set "
            f"to {cmd_port}. Set Command Port to {st.host_port} in Settings → "
            "Modem Configuration → Aether HF.")
    if st.host_keyed and not host_ptt:
        out.append(
            "Aether HF is set to let the host program key the radio (its "
            "Setup step 2: host program), but Aether Term is not set to key "
            "it, so nothing would key the radio. Tick \"Aether HF keying is "
            "host program\" in Settings → Modem Configuration, or let Aether "
            "HF key the radio itself.")
    return out


def double_keying(st: AetherStatus, host_ptt: bool) -> str:
    """A warning when both Aether HF and Aether Term would key the radio."""
    if host_ptt and st.host_keyed is False and st.ptt_kind not in ("", "none"):
        return (f"Aether HF keys the radio itself ({st.ptt or st.ptt_kind}), and "
                "Aether Term is also set to key it on PTT ON. Only one program "
                "should key the radio: untick \"Aether HF keying is host "
                "program\" in Settings unless Aether HF's Setup step 2 says "
                "host program.")
    return ""


# ── Client ─────────────────────────────────────────────────────────

class AetherControl:
    """Synchronous one-shot client for ``POST /v1/<method>``."""

    def __init__(self, base_url: str, token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.token = token

    def call(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        body = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/v1/{method}", data=body, method="POST",
            headers={"Content-Type": "application/json"})
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 400 carries the same error object as a WebSocket refusal
            try:
                payload = json.loads(e.read().decode("utf-8"))
            except Exception:
                raise AetherControlError(f"HTTP {e.code} from Aether HF") from e
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise AetherControlError(f"Aether HF control API not reachable: {e}") from e
        if not payload.get("ok", False):
            err = payload.get("error") or {}
            raise AetherControlError(err.get("message") or err.get("code") or "refused")
        return payload.get("result")

    def status(self) -> Dict[str, Any]:
        return self.call("status") or {}

    def rung_names(self) -> Dict[int, str]:
        caps = self.call("capabilities") or {}
        names = {}
        for m in caps.get("modes", []) or []:
            idx = m.get("index")
            if isinstance(idx, int):
                names[idx] = str(m.get("name", ""))
        return names

    def ptt_kind(self) -> str:
        """``[ptt] kind`` from ``config.get`` (read-only): "host", "cat", …

        "" when the modem will not say (a daemon run without a configuration
        file answers ``unsupported``).
        """
        try:
            cfg = (self.call("config.get") or {}).get("config") or {}
        except AetherControlError:
            return ""
        return str((cfg.get("ptt") or {}).get("kind") or "").lower()

    def snapshot(self, rung_names: Optional[Dict[int, str]] = None,
                 with_keying: bool = False) -> AetherStatus:
        try:
            st = AetherStatus.from_status(self.status(), rung_names)
        except AetherControlError as e:
            return AetherStatus(reachable=False, error=str(e))
        if with_keying:
            st.ptt_kind = self.ptt_kind()
        return st


class AetherQuery(QObject):
    """One-shot status queries off the GUI thread.

    ``snapshot(url, callback)`` asks the modem on a worker thread and calls
    ``callback(AetherStatus)`` back on the thread this object lives in (the
    GUI thread), so a slow or unreachable modem never freezes the window.
    The one-shot snapshot also reads who keys the radio (``config.get``).
    """

    _done = pyqtSignal(int, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._callbacks: Dict[int, Any] = {}
        self._next = 0
        self._done.connect(self._dispatch)

    def snapshot(self, base_url: str, callback) -> None:
        self._next += 1
        token = self._next
        self._callbacks[token] = callback

        def work():
            self._done.emit(token, AetherControl(base_url).snapshot(with_keying=True))

        threading.Thread(target=work, daemon=True, name="AetherQuery").start()

    @property
    def pending(self) -> int:
        return len(self._callbacks)

    def _dispatch(self, token: int, status: "AetherStatus"):
        cb = self._callbacks.pop(token, None)
        if cb is not None:
            cb(status)


class AetherMonitor(QObject):
    """Polls the modem's status in a background thread while running.

    Signals are emitted from the polling thread — connect with
    ``Qt.QueuedConnection``.
    """

    status_updated = pyqtSignal(object)   # AetherStatus

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client: Optional[AetherControl] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._rung_names: Dict[int, str] = {}
        self._rung_bw: Optional[int] = None

    def start(self, base_url: str):
        self.stop()
        self._client = AetherControl(base_url)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="AetherMonitor")
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and not self._stop.is_set()

    def _run(self):
        client = self._client
        stop = self._stop
        while not stop.is_set():
            snap = client.snapshot(self._rung_names)
            if snap.reachable and snap.bandwidth_hz != self._rung_bw:
                # The ladder depends on the bandwidth; fetch it again on a move
                try:
                    self._rung_names = client.rung_names()
                    self._rung_bw = snap.bandwidth_hz
                    if snap.mode is not None:
                        snap.rung_name = self._rung_names.get(snap.mode, "")
                except AetherControlError:
                    pass
            if not stop.is_set():
                self.status_updated.emit(snap)
            stop.wait(POLL_INTERVAL)
