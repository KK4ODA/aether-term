"""
vara/hamlib.py — Hamlib (rigctld) PTT client for Aether Term.

Talks to Hamlib's rigctld daemon over TCP with the "Extended Response
Protocol" (``+\\cmd``, answered with ``RPRT <code>``).  rigctld can be
launched by Aether Term or run separately.
"""

import logging
import os
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from vara.rig_client import RigClient

log = logging.getLogger(__name__)

# rigctld default port
DEFAULT_RIGCTLD_PORT = 4532
SOCKET_TIMEOUT = 4.0       # under RigClient.CMD_TIMEOUT, so a late reply is not misread

# Common Hamlib rig model numbers (subset — full list at
# https://github.com/Hamlib/Hamlib/wiki/Supported-Radios)
COMMON_RIG_MODELS = {
    1:    "Hamlib Dummy (test)",
    2:    "Hamlib NET rigctl",
    # Icom
    3001: "Icom IC-7300",
    3073: "Icom IC-7610",
    3070: "Icom IC-9700",
    3060: "Icom IC-705",
    # Yaesu
    1035: "Yaesu FT-991A",
    1037: "Yaesu FTdx101D",
    1036: "Yaesu FTdx10",
    1024: "Yaesu FT-817/818",
    1038: "Yaesu FT-710",
    # Kenwood / Elecraft
    2048: "Kenwood TS-890S",
    2044: "Kenwood TS-590SG",
    2028: "Elecraft K3",
    2045: "Elecraft KX3",
    2047: "Elecraft K4",
    # FlexRadio
    2036: "Flex 6000 series",
}


class HamlibClient(RigClient):
    NAME = "Hamlib"
    # three connect attempts of up to 5 s each, 1 s apart
    START_TIMEOUT = 20.0

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = DEFAULT_RIGCTLD_PORT,
        rig_model: int = 0,
        device: str = "",
        serial_speed: int = 0,
        auto_launch: bool = False,
        rigctld_path: str = "",
        extra_args: str = "",
    ):
        super().__init__()
        self._host = host
        self._port = port
        self._rig_model = rig_model
        self._device = device
        self._serial_speed = serial_speed
        self._auto_launch = auto_launch
        self._rigctld_path = rigctld_path
        self._extra_args = extra_args
        self._rigctld_proc: Optional[subprocess.Popen] = None
        self._sock: Optional[socket.socket] = None

    # ── Lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        """Launch rigctld if configured, then connect (see RigClient.start)."""
        if self._started:
            return
        if self._auto_launch:
            self._launch_rigctld()
        try:
            super().start()
        except RuntimeError:
            self._kill_rigctld()
            raise

    def stop(self) -> None:
        super().stop()
        self._kill_rigctld()

    # ── rigctld process management ────────────────────────────────

    def _find_rigctld(self) -> str:
        """Locate rigctld executable."""
        # 1. Explicit path from settings
        if self._rigctld_path and os.path.isfile(self._rigctld_path):
            return self._rigctld_path

        if os.name == "nt":
            candidates = []

            # 2. Aether Term's own download directory (%APPDATA%/Aether Term/hamlib/bin)
            appdata = os.environ.get("APPDATA", "")
            if appdata:
                candidates.append(
                    Path(appdata) / "Aether Term" / "hamlib" / "bin" / "rigctld.exe")

            # 3. Aether Term exe subdirectory (portable installs)
            try:
                from _frozen import EXE_DIR
                candidates.append(EXE_DIR / "hamlib" / "bin" / "rigctld.exe")
            except ImportError:
                candidates.append(
                    Path(__file__).parent.parent / "hamlib" / "bin" / "rigctld.exe")

            # 4. Program Files — check exact "Hamlib" and wildcard "hamlib-w64-*"
            for env_var in ("ProgramFiles", "ProgramFiles(x86)"):
                pf = Path(os.environ.get(env_var, ""))
                if not pf.exists():
                    continue
                # Exact name
                candidates.append(pf / "Hamlib" / "bin" / "rigctld.exe")
                # Versioned name: hamlib-w64-4.7.0, hamlib-w32-4.6, etc.
                try:
                    for d in pf.iterdir():
                        if d.is_dir() and d.name.lower().startswith("hamlib"):
                            candidates.append(d / "bin" / "rigctld.exe")
                except OSError:
                    pass

            # 5. LOCALAPPDATA
            localappdata = os.environ.get("LOCALAPPDATA", "")
            if localappdata:
                candidates.append(
                    Path(localappdata) / "Hamlib" / "bin" / "rigctld.exe")

            for p in candidates:
                if p.exists():
                    log.info(f"Found rigctld at: {p}")
                    return str(p)

        # Unix — try PATH
        import shutil
        found = shutil.which("rigctld")
        if found:
            return found

        log.warning("rigctld not found in any search path")
        return ""

    def _launch_rigctld(self):
        """Launch rigctld as a subprocess.  Raises RuntimeError if it exits
        at once (bad model, port or serial device)."""
        exe = self._find_rigctld()
        if not exe:
            log.warning("rigctld not found — cannot auto-launch. "
                        "Ensure Hamlib is installed or set path in settings.")
            return

        args = [exe, "-T", self._host, "-t", str(self._port)]
        if self._rig_model:
            args += ["-m", str(self._rig_model)]
        if self._device:
            args += ["-r", self._device]
        if self._serial_speed:
            args += ["-s", str(self._serial_speed)]
        if self._extra_args:
            args += self._extra_args.split()

        log.info(f"Launching rigctld: {' '.join(args)}")
        # rigctld's messages go to a temporary file: a pipe nobody reads
        # would fill up and stall rigctld (and with it, PTT).
        errors = tempfile.TemporaryFile()
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW   # no console popup
        try:
            self._rigctld_proc = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=errors, **kwargs)
        except OSError as e:
            errors.close()
            raise RuntimeError(f"Cannot start rigctld ({exe}): {e}")
        time.sleep(1.5)            # give rigctld time to start listening
        if self._rigctld_proc.poll() is not None:
            errors.seek(0)
            msg = errors.read().decode(errors="replace").strip()
            errors.close()
            self._rigctld_proc = None
            raise RuntimeError(f"rigctld exited at once: {msg or 'no message'}")
        errors.close()             # rigctld keeps its own handle
        log.info(f"rigctld launched (PID {self._rigctld_proc.pid})")

    def _kill_rigctld(self):
        """Terminate the rigctld subprocess if we launched it."""
        if self._rigctld_proc and self._rigctld_proc.poll() is None:
            log.info(f"Terminating rigctld (PID {self._rigctld_proc.pid})")
            try:
                if os.name == "nt":
                    self._rigctld_proc.terminate()
                else:
                    self._rigctld_proc.send_signal(signal.SIGTERM)
                self._rigctld_proc.wait(timeout=3.0)
            except Exception:
                try:
                    self._rigctld_proc.kill()
                except Exception:
                    pass
            self._rigctld_proc = None

    # ── I/O thread ────────────────────────────────────────────────

    def _open(self) -> None:
        for attempt in range(3):
            try:
                self._sock = socket.create_connection(
                    (self._host, self._port), timeout=5.0)
                break
            except OSError as e:
                if attempt == 2:
                    raise RuntimeError(
                        f"Cannot connect to rigctld at {self._host}:{self._port}. "
                        f"Is rigctld running? Error: {e}")
                log.info(f"rigctld connect attempt {attempt + 1} failed, retrying...")
                time.sleep(1.0)
        self._sock.settimeout(SOCKET_TIMEOUT)
        if self._send("\\dump_state") is None:
            raise RuntimeError("rigctld did not respond to initial query")
        log.info(f"Connected to rigctld at {self._host}:{self._port}")

    def _key(self, on: bool) -> bool:
        return self._check_ok(self._send(f"\\set_ptt {1 if on else 0}"))

    def _close(self) -> None:
        if self._sock:
            self._send("\\set_ptt 0")         # never raises
        if self._sock:
            self._sock.close()
            self._sock = None

    # ── rigctld wire protocol ─────────────────────────────────────

    def _send(self, cmd: str) -> Optional[str]:
        """Send a command; return the reply through its RPRT line, or None.

        A reply that does not arrive in time is not waited for any longer:
        the link is reopened, so that late reply cannot be read as the
        answer to the next command.
        """
        if not self._sock:
            try:
                self._sock = socket.create_connection(
                    (self._host, self._port), timeout=SOCKET_TIMEOUT)
            except OSError as e:
                log.error(f"rigctld reconnect failed: {e}")
                return None
        try:
            self._sock.sendall(f"+{cmd}\n".encode("ascii"))
            buf = ""
            while "RPRT" not in buf:
                chunk = self._sock.recv(4096)
                if not chunk:
                    raise OSError("rigctld closed the connection")
                buf += chunk.decode("ascii", errors="replace")
            return buf
        except OSError as e:          # includes socket.timeout
            log.error(f"rigctld {cmd}: {e}")
            self._sock.close()
            self._sock = None
            return None

    @staticmethod
    def _check_ok(resp: Optional[str]) -> bool:
        """Check if a rigctld response indicates success (RPRT 0)."""
        return bool(resp) and "RPRT 0" in resp
