"""
vara/hamlib.py — Thread-safe Hamlib (rigctld) client for Aether Term.

Communicates with Hamlib's rigctld daemon over TCP using the "Extended
Response Protocol" for reliable parsing.  Provides CAT control: frequency,
mode, PTT, and status queries.

Architecture mirrors OmniRig: all network I/O happens on a single dedicated
thread; public methods are thread-safe, queueing commands and blocking
until the I/O thread completes them.

rigctld can be launched automatically by Aether Term or managed externally.

Usage:
    client = HamlibClient(host="127.0.0.1", port=4532)
    client.start()

    client.set_freq(14_074_000)
    client.set_mode("USB", 2800)
    client.set_ptt(True)
    freq = client.get_freq()

    client.stop()
"""

import logging
import os
import queue
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional, Tuple

log = logging.getLogger(__name__)

# rigctld default port
DEFAULT_RIGCTLD_PORT = 4532

# Hamlib error codes
RIG_OK = 0

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


class _Cmd:
    """A command to be executed on the I/O thread."""
    __slots__ = ("action", "args", "result", "error", "done")

    def __init__(self, action: str, args: Any = None):
        self.action = action
        self.args = args
        self.result: Any = None
        self.error: Optional[str] = None
        self.done = threading.Event()


class HamlibClient:
    """Thread-safe Hamlib rigctld client.

    A single daemon thread owns the TCP connection to rigctld.
    All public methods are safe to call from any thread — they queue
    commands and (for getters) block until the I/O thread completes them.
    """

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
        self._host = host
        self._port = port
        self._rig_model = rig_model
        self._device = device
        self._serial_speed = serial_speed
        self._auto_launch = auto_launch
        self._rigctld_path = rigctld_path
        self._extra_args = extra_args

        self._queue: queue.Queue[Optional[_Cmd]] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._rigctld_proc: Optional[subprocess.Popen] = None
        self._ready = threading.Event()
        self._error: Optional[str] = None
        self._started = False
        self._sock: Optional[socket.socket] = None

    # ── Lifecycle ─────────────────────────────────────────────────

    def start(self) -> None:
        """Optionally launch rigctld, then connect.

        Blocks until the connection is established or fails.
        Raises RuntimeError on failure.
        """
        if self._started:
            return

        # Auto-launch rigctld if configured
        if self._auto_launch:
            self._launch_rigctld()

        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(
            target=self._run,
            name="Hamlib-IO",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=15.0)
        if self._error:
            self._kill_rigctld()
            raise RuntimeError(self._error)
        self._started = True

    def stop(self) -> None:
        """Release PTT, disconnect, and join the I/O thread."""
        if not self._started:
            return
        self._queue.put(None)  # poison pill
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._kill_rigctld()
        self._started = False

    @property
    def is_started(self) -> bool:
        return self._started

    # ── Thread-safe public API ────────────────────────────────────

    def set_ptt(self, on: bool) -> bool:
        """Key (True) or unkey (False) the radio.  Returns True on success."""
        return self._exec("SET_PTT", 1 if on else 0)

    def set_freq(self, freq_hz: int) -> bool:
        """Set VFO frequency in Hz.  Returns True on success."""
        return self._exec("SET_FREQ", freq_hz)

    def set_mode(self, mode: str, passband: int = 0) -> bool:
        """Set mode (e.g. 'USB', 'LSB', 'CW', 'FM', 'AM').
        passband=0 means use rig default.  Returns True on success.
        """
        return self._exec("SET_MODE", (mode, passband))

    def get_freq(self) -> int:
        """Read current VFO frequency in Hz.  Returns 0 on failure."""
        return self._exec_get("GET_FREQ")

    def get_mode(self) -> Tuple[str, int]:
        """Read current mode and passband.  Returns ('', 0) on failure."""
        result = self._exec_get("GET_MODE")
        if isinstance(result, tuple):
            return result
        return ("", 0)

    def get_ptt(self) -> bool:
        """Read current PTT state.  Returns False on failure."""
        result = self._exec_get("GET_PTT")
        return result == 1

    def get_info(self) -> str:
        """Read rig info string.  Returns '' on failure."""
        result = self._exec_get("GET_INFO")
        return result if isinstance(result, str) else ""

    def get_strength(self) -> int:
        """Read signal strength in dB.  Returns 0 on failure."""
        return self._exec_get("GET_STRENGTH")

    # ── Internal helpers ──────────────────────────────────────────

    def _exec(self, action: str, args: Any = None) -> bool:
        if not self._started:
            return False
        cmd = _Cmd(action, args)
        self._queue.put(cmd)
        cmd.done.wait(timeout=5.0)
        return cmd.result is True

    def _exec_get(self, action: str) -> Any:
        if not self._started:
            return 0
        cmd = _Cmd(action)
        self._queue.put(cmd)
        cmd.done.wait(timeout=5.0)
        return cmd.result if cmd.result is not None else 0

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
        """Launch rigctld as a subprocess."""
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
        try:
            # CREATE_NO_WINDOW on Windows to avoid console popup
            kwargs = {}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            self._rigctld_proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                **kwargs,
            )
            # Give rigctld time to start listening
            time.sleep(1.5)

            if self._rigctld_proc.poll() is not None:
                stderr = self._rigctld_proc.stderr.read().decode(errors="replace")
                log.error(f"rigctld exited immediately: {stderr}")
                self._rigctld_proc = None
            else:
                log.info(f"rigctld launched (PID {self._rigctld_proc.pid})")
        except FileNotFoundError:
            log.error(f"rigctld executable not found at: {exe}")
        except Exception as e:
            log.error(f"Failed to launch rigctld: {e}")

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

    def _run(self) -> None:
        """I/O thread main loop — owns the TCP connection to rigctld."""
        # Connect to rigctld
        retries = 3
        for attempt in range(retries):
            try:
                self._sock = socket.create_connection(
                    (self._host, self._port), timeout=5.0)
                self._sock.settimeout(5.0)
                break
            except OSError as e:
                if attempt < retries - 1:
                    log.info(f"rigctld connect attempt {attempt+1} failed, retrying...")
                    time.sleep(1.0)
                else:
                    self._error = (
                        f"Cannot connect to rigctld at {self._host}:{self._port}. "
                        f"Is rigctld running? Error: {e}"
                    )
                    self._ready.set()
                    return

        # Verify connection with a simple query
        try:
            info = self._send_rigctld_cmd("\\dump_state")
            if info is None:
                self._error = "rigctld did not respond to initial query"
                self._ready.set()
                return
            log.info(f"Connected to rigctld at {self._host}:{self._port}")
        except Exception as e:
            self._error = f"rigctld communication error: {e}"
            self._ready.set()
            return

        # Try to get initial frequency
        try:
            resp = self._send_rigctld_cmd("\\get_freq")
            if resp:
                freq_str = resp.strip().split("\n")[0]
                try:
                    freq = int(float(freq_str))
                    log.info(f"Hamlib: Radio freq = {freq/1000:.1f} kHz")
                except ValueError:
                    log.info(f"Hamlib: Connected (freq response: {freq_str})")
        except Exception:
            pass

        self._ready.set()

        # -- Command loop --
        try:
            while True:
                try:
                    cmd = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue

                if cmd is None:
                    # Poison pill — release PTT and shut down
                    try:
                        self._send_rigctld_cmd("\\set_ptt 0")
                    except Exception:
                        pass
                    break

                try:
                    self._dispatch(cmd)
                except Exception as e:
                    log.error(f"Hamlib {cmd.action} error: {e}")
                    cmd.result = None
                    cmd.error = str(e)
                finally:
                    cmd.done.set()

        finally:
            try:
                self._send_rigctld_cmd("\\set_ptt 0")
            except Exception:
                pass
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
            log.info("Hamlib I/O thread exited")

    def _dispatch(self, cmd: _Cmd):
        """Execute a command on the I/O thread."""
        if cmd.action == "SET_PTT":
            resp = self._send_rigctld_cmd(f"\\set_ptt {cmd.args}")
            cmd.result = self._check_ok(resp)

        elif cmd.action == "SET_FREQ":
            resp = self._send_rigctld_cmd(f"\\set_freq {cmd.args}")
            cmd.result = self._check_ok(resp)

        elif cmd.action == "SET_MODE":
            mode, passband = cmd.args
            resp = self._send_rigctld_cmd(f"\\set_mode {mode} {passband}")
            cmd.result = self._check_ok(resp)

        elif cmd.action == "GET_FREQ":
            resp = self._send_rigctld_cmd("\\get_freq")
            if resp:
                try:
                    cmd.result = int(float(resp.strip().split("\n")[0]))
                except (ValueError, IndexError):
                    cmd.result = 0
            else:
                cmd.result = 0

        elif cmd.action == "GET_MODE":
            resp = self._send_rigctld_cmd("\\get_mode")
            if resp:
                lines = resp.strip().split("\n")
                mode = lines[0] if len(lines) >= 1 else ""
                try:
                    passband = int(lines[1]) if len(lines) >= 2 else 0
                except ValueError:
                    passband = 0
                cmd.result = (mode, passband)
            else:
                cmd.result = ("", 0)

        elif cmd.action == "GET_PTT":
            resp = self._send_rigctld_cmd("\\get_ptt")
            if resp:
                try:
                    cmd.result = int(resp.strip().split("\n")[0])
                except (ValueError, IndexError):
                    cmd.result = 0
            else:
                cmd.result = 0

        elif cmd.action == "GET_INFO":
            resp = self._send_rigctld_cmd("\\get_info")
            cmd.result = resp.strip() if resp else ""

        elif cmd.action == "GET_STRENGTH":
            resp = self._send_rigctld_cmd("\\get_level STRENGTH")
            if resp:
                try:
                    cmd.result = int(float(resp.strip().split("\n")[0]))
                except (ValueError, IndexError):
                    cmd.result = 0
            else:
                cmd.result = 0

        else:
            cmd.result = None

    # ── rigctld wire protocol ─────────────────────────────────────

    def _send_rigctld_cmd(self, cmd: str) -> Optional[str]:
        """Send a command to rigctld and return the response.

        Uses the "extended response" protocol prefix (+) for
        reliable error detection.
        """
        if not self._sock:
            return None

        # Use extended response protocol for parseable results
        wire_cmd = f"+{cmd}\n"
        try:
            self._sock.sendall(wire_cmd.encode("ascii"))
        except OSError as e:
            log.error(f"rigctld send error: {e}")
            return None

        # Read response until we see RPRT (return code line)
        buf = ""
        try:
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    return None
                buf += chunk.decode("ascii", errors="replace")
                if "RPRT" in buf:
                    break
        except socket.timeout:
            log.warning(f"rigctld response timeout for: {cmd}")
            return buf if buf else None
        except OSError as e:
            log.error(f"rigctld recv error: {e}")
            return None

        return buf

    @staticmethod
    def _check_ok(resp: Optional[str]) -> bool:
        """Check if a rigctld response indicates success (RPRT 0)."""
        if not resp:
            return False
        return "RPRT 0" in resp
