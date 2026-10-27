"""Two Direwolf soundcard modems joined by software audio: a radio channel
for tests, with no radio.

    Direwolf A ──(1200 baud AFSK over UDP)── Direwolf B
    KISS TCP port                             AGWPE port

Each Direwolf receives audio on a UDP port and transmits through an ALSA
"file" device that pipes to a small relay; the relay sends the samples
to the other's UDP port as a steady real-time stream (silence between
packets, so carrier detect sees the channel go quiet).

Needs ``direwolf`` on the PATH and ALSA (Linux).  ``available()`` says
whether this machine has them.
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time

RELAY = textwrap.dedent('''
    import array, socket, sys, threading, time
    port = int(sys.argv[1]); RATE, MS = 44100, 10
    chunk = RATE * MS // 1000 * 2
    buf = bytearray(); lock = threading.Lock()
    def reader():
        r = sys.stdin.buffer
        while True:
            b = r.read1(4096)
            if not b: break
            a = array.array("h"); a.frombytes(b[: len(b) // 2 * 2])
            for i in range(len(a)): a[i] = a[i] // 4
            with lock: buf.extend(a.tobytes())
    threading.Thread(target=reader, daemon=True).start()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    nxt = time.monotonic()
    while True:
        with lock:
            out = bytes(buf[:chunk]); del buf[:chunk]
        out += bytes(chunk - len(out))
        s.sendto(out, ("127.0.0.1", port))
        nxt += MS / 1000
        time.sleep(max(0, nxt - time.monotonic()))
''')


def available() -> bool:
    return sys.platform.startswith("linux") and shutil.which("direwolf") is not None


def _free_port(kind=socket.SOCK_STREAM) -> int:
    """A free port below 32768 (Direwolf refuses higher AGWPE ports)."""
    import random
    for _ in range(200):
        port = random.randint(20000, 32000)
        s = socket.socket(socket.AF_INET, kind)
        try:
            s.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            s.close()
    raise RuntimeError("no free port")


def _wait_port(port: int, timeout: float = 40.0) -> bool:
    # (as root Direwolf first spends ~15 s warning about it)
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return True
        except OSError:
            time.sleep(0.2)
    return False


class DirewolfAir:
    def __init__(self, call_a: str = "N0CALL", call_b: str = "N0BBS-10"):
        self.dir = tempfile.mkdtemp(prefix="dwair-")
        self.kiss_port = _free_port()
        self.agw_port = _free_port()
        udp_a, udp_b = _free_port(socket.SOCK_DGRAM), _free_port(socket.SOCK_DGRAM)
        relay = os.path.join(self.dir, "relay.py")
        with open(relay, "w") as f:
            f.write(RELAY)
        py = sys.executable
        with open(os.path.join(self.dir, ".asoundrc"), "w") as f:
            f.write(f'pcm.toa {{ type file; slave.pcm "null"; file "|{py} {relay} {udp_a}"; format "raw" }}\n'
                    f'pcm.tob {{ type file; slave.pcm "null"; file "|{py} {relay} {udp_b}"; format "raw" }}\n')
        common = "ARATE 44100\nACHANNELS 1\nCHANNEL 0\nMODEM 1200\n"
        confs = {
            "a": f"ADEVICE udp:{udp_a} tob\n{common}MYCALL {call_a}\nAGWPORT 0\nKISSPORT {self.kiss_port}\n",
            "b": f"ADEVICE udp:{udp_b} toa\n{common}MYCALL {call_b}\nAGWPORT {self.agw_port}\nKISSPORT 0\n",
        }
        env = dict(os.environ, HOME=self.dir)
        self.procs = []
        for name, conf in confs.items():
            path = os.path.join(self.dir, f"dw-{name}.conf")
            with open(path, "w") as f:
                f.write(conf)
            log = open(os.path.join(self.dir, f"dw-{name}.log"), "w")
            self.procs.append(subprocess.Popen(
                ["direwolf", "-c", path, "-t", "0"], cwd=self.dir, env=env,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True))
        if not (_wait_port(self.kiss_port) and _wait_port(self.agw_port)):
            logs = self.logs()
            self.stop()
            raise RuntimeError("Direwolf did not start:\n" + logs)

    def logs(self) -> str:
        out = []
        for name in ("a", "b"):
            try:
                with open(os.path.join(self.dir, f"dw-{name}.log")) as f:
                    out.append(f"--- direwolf {name}\n" + f.read()[-3000:])
            except OSError:
                pass
        return "\n".join(out)

    def stop(self):
        import signal
        for p in self.procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)       # direwolf and its relay
            except OSError:
                pass
        for p in self.procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
        shutil.rmtree(self.dir, ignore_errors=True)
