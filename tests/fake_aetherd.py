"""
A stand-in for Aether HF's daemon, for tests.

Serves the two interfaces Aether Term uses, with the shapes aetherd uses
(see docs/AETHER_HF.md):

* the VARA-compatible host port — command port + data port (= command + 1),
  CR-terminated lines, ``BUFFER 0`` on attach, ``VERSION Aether HF <v>``,
  and ``CONNECT`` answered with ``CONNECTED <caller> <called> <bw>``;
* the control API — ``POST /v1/status`` and ``/v1/capabilities``.

Behaviour is steered through the ``state`` dict.
"""

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.2.0-beta.102"
RUNGS = ["tone-24", "tone-36", "tone50-51", "tone50-102", "tone100-102",
         "tone100-153", "BPSK-1/5", "BPSK-1/3", "QPSK-1/3", "QPSK-1/2"]


def _listen(port: int = 0) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", port))
    s.listen(1)
    return s


def _adjacent_listeners():
    """Bind a command port and command + 1, as aetherd requires."""
    for _ in range(50):
        cmd = _listen(0)
        port = cmd.getsockname()[1]
        try:
            data = _listen(port + 1)
            return cmd, data
        except OSError:
            cmd.close()
    raise RuntimeError("could not find two adjacent free ports")


class FakeAetherd:
    def __init__(self):
        self.state = {
            "host_enabled": True,
            "policy": "rules",           # rules / none / unset / broken
            "verdict": "legal",
            "ptt_fault": None,
            "audio_fault": None,
            "state": "idle",
            "remote": None,
            "answer_connect": True,      # False: refuse with DISCONNECTED
            "version_reply": f"VERSION Aether HF {VERSION}",
            "status_delay": 0.0,         # seconds before /v1/status answers
        }
        self.commands: list[str] = []
        self.data: list[bytes] = []
        self._cmd_srv, self._data_srv = _adjacent_listeners()
        self.cmd_port = self._cmd_srv.getsockname()[1]
        self.data_port = self.cmd_port + 1
        self._http = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.control_port = self._http.server_address[1]
        self._stop = threading.Event()
        self._conns: list[socket.socket] = []

    @property
    def control_url(self) -> str:
        return f"http://127.0.0.1:{self.control_port}"

    # ── lifecycle ───────────────────────────────────────────────────

    def start(self):
        threading.Thread(target=self._http.serve_forever, daemon=True).start()
        threading.Thread(target=self._host_loop, daemon=True).start()
        return self

    def stop(self):
        self._stop.set()
        self._http.shutdown()
        self._http.server_close()
        for s in [self._cmd_srv, self._data_srv, *self._conns]:
            try:
                s.close()
            except OSError:
                pass

    # ── control API ─────────────────────────────────────────────────

    def status(self) -> dict:
        st = self.state
        return {
            "state": st["state"], "role": "none", "callsign": "KK4ODA",
            "remote": st["remote"], "mode": 7, "version": VERSION,
            "transmitting": False, "channel_busy": False, "ptt": "CAT on COM3",
            "ptt_fault": st["ptt_fault"], "audio_fault": st["audio_fault"],
            "answering": True,
            "host": {"enabled": st["host_enabled"], "connected": bool(self._conns)},
            "bandwidth": {"bandwidth_hz": 2300, "home_hz": 2300, "host_hz": None},
            "regulatory": {"policy": st["policy"],
                           "indicator": {"verdict": st["verdict"],
                                         "summary": f"FCC: {st['verdict']} at 7.103 MHz"}},
        }

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                method = self.path.rsplit("/", 1)[-1]
                if method == "status":
                    time.sleep(fake.state["status_delay"])
                    body = {"ok": True, "result": fake.status()}
                elif method == "capabilities":
                    body = {"ok": True, "result": {
                        "bandwidth_hz": 2300,
                        "modes": [{"index": i, "name": n} for i, n in enumerate(RUNGS)]}}
                else:
                    body = {"ok": False, "error": {"code": "unknown_method",
                                                   "message": f"No method {method}"}}
                raw = json.dumps(body).encode()
                self.send_response(200 if body["ok"] else 400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        return Handler

    # ── VARA-compatible host port ───────────────────────────────────

    def _host_loop(self):
        while not self._stop.is_set():
            try:
                c, _ = self._cmd_srv.accept()
                d, _ = self._data_srv.accept()
            except OSError:
                return
            self._conns[:] = [c, d]
            c.sendall(b"BUFFER 0\r")
            threading.Thread(target=self._data_loop, args=(d,), daemon=True).start()
            self._cmd_loop(c, d)
            self._conns.clear()
            for s in (c, d):
                try:
                    s.close()
                except OSError:
                    pass

    def _data_loop(self, d: socket.socket):
        while True:
            try:
                b = d.recv(4096)
            except OSError:
                return
            if not b:
                return
            self.data.append(b)
            if b.strip().upper() == b"H":
                d.sendall(b"Help: L R S B\r\n")

    def _cmd_loop(self, c: socket.socket, d: socket.socket):
        buf = b""
        while True:
            try:
                b = c.recv(1024)
            except OSError:
                return
            if not b:
                return
            buf += b
            while b"\r" in buf:
                raw, buf = buf.split(b"\r", 1)
                line = raw.strip().decode("ascii", "replace")
                if line:
                    self.commands.append(line)
                    self._answer(line, c, d)

    def _answer(self, line: str, c: socket.socket, d: socket.socket):
        up = line.upper()
        if up == "VERSION":
            c.sendall(self.state["version_reply"].encode() + b"\r")
        elif up.startswith("CONNECT "):
            c.sendall(b"OK\r")
            parts = line.split()
            if self.state["answer_connect"]:
                me, them = parts[1], parts[2]
                self.state.update(state="connected", remote=them)
                c.sendall(b"PTT ON\rPTT OFF\rSN 7\r")
                c.sendall(f"CONNECTED {me} {them} 2300\r".encode())
                c.sendall(b"ENCRYPTION DISABLED\rLINK REGISTERED\r")
                c.sendall(b"BITRATE (9) 1450 BPS\r")
                d.sendall(b"Welcome to the test BBS\r\n")
            else:
                c.sendall(b"DISCONNECTED\r")
        elif up == "DISCONNECT":
            c.sendall(b"OK\r")
            if self.state["state"] == "connected":
                self.state.update(state="idle", remote=None)
                c.sendall(b"DISCONNECTED\r")
        else:
            c.sendall(b"OK\r")
