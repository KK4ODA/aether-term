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

Only read-only methods are used (``status``, ``capabilities``).  A loopback
connection needs no token; nothing here changes the modem's settings.
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
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def problems(self) -> List[str]:
        """Operator-facing reasons the modem would not connect or transmit."""
        out = []
        if not self.reachable:
            return out
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
            raw=st,
        )


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

    def snapshot(self, rung_names: Optional[Dict[int, str]] = None) -> AetherStatus:
        try:
            return AetherStatus.from_status(self.status(), rung_names)
        except AetherControlError as e:
            return AetherStatus(reachable=False, error=str(e))


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
