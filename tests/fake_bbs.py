"""A fake Aether BBS instance for local test mode: the modem's client side.

Connects to the terminal's command and data ports as the BBS's
VARAFMInterface does (bbs/vara/interface.py), sends its init sequence,
and records what comes back.  With ``session=True`` it also answers as
the BBS's session does: a welcome and "> " on CONNECTED, ;TRANSPORT? and
H on the data port, DISCONNECT on B.
"""

import socket
import threading
import time

INIT = ["MYCALL N0BBS-10", "COMPRESSION OFF", "VERSION", "LISTEN ON"]


class FakeBBS:
    def __init__(self, cmd_port: int, data_port: int, call: str = "N0BBS-10",
                 eol: str = "\r\n", session: bool = False):
        self.call = call
        self.eol = eol
        self.session = session
        self.cmd = socket.create_connection(("127.0.0.1", cmd_port), timeout=5)
        self.data = socket.create_connection(("127.0.0.1", data_port), timeout=5)
        self.events: list = []          # command-port lines from the "modem"
        self.received = bytearray()     # data-port bytes from the terminal
        self.caller = None
        self._stop = threading.Event()
        threading.Thread(target=self._cmd_loop, daemon=True).start()
        threading.Thread(target=self._data_loop, daemon=True).start()

    # ── what the test does ────────────────────────────────────────

    def send_cmd(self, line: str):
        try:
            self.cmd.sendall((line + self.eol).encode("ascii"))
        except OSError:
            if not self._stop.is_set():
                raise

    def init(self, commands=None, pause: float = 0.05):
        """The BBS's init sequence; returns the replies, one per command."""
        replies = []
        for line in commands or [c.replace("N0BBS-10", self.call) for c in INIT]:
            mark = len(self.events)
            self.send_cmd(line)
            assert self.wait(lambda: len(self.events) > mark), f"no reply to {line}"
            replies.append(self.events[mark])
            time.sleep(pause)
        return replies

    def send_data(self, data: bytes):
        try:
            self.data.sendall(data)
        except OSError:
            if not self._stop.is_set():
                raise                   # (after close(): the test is done)

    def wait(self, cond, timeout: float = 5.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return True
            time.sleep(0.02)
        return cond()

    def drop(self, which: str):
        """Close the "cmd" or "data" connection, as a BBS that died would."""
        sock = getattr(self, which)
        try:
            sock.shutdown(socket.SHUT_RDWR)   # close() alone leaves the
        except OSError:                       # reader thread holding it open
            pass
        sock.close()

    def close(self):
        self._stop.set()
        for which in ("cmd", "data"):
            self.drop(which)

    # ── the BBS side ──────────────────────────────────────────────

    def _cmd_loop(self):
        buf = b""
        while not self._stop.is_set():
            try:
                b = self.cmd.recv(1024)
            except OSError:
                return
            if not b:
                return
            buf += b
            while b"\r" in buf:
                raw, buf = buf.split(b"\r", 1)
                line = raw.decode("ascii")
                self.events.append(line)
                if line.startswith("CONNECTED "):
                    self.caller = line.split()[1]
                    if self.session:
                        time.sleep(0.1)
                        self.send_data(f"Welcome to {self.call}, {self.caller}\r\n> "
                                       .encode())

    def _data_loop(self):
        buf = b""
        while not self._stop.is_set():
            try:
                b = self.data.recv(4096)
            except OSError:
                return
            if not b:
                return
            self.received += b
            if not self.session:
                continue
            buf += b
            while b"\r\n" in buf:
                raw, buf = buf.split(b"\r\n", 1)
                cmd = raw.decode().strip()
                if cmd == ";TRANSPORT?":
                    self.send_data(b";TRANSPORT VARA_FM\r\n")
                    self.send_data(b"\r\n> ")
                elif cmd.upper() == "H":
                    self.send_data(b"Help: L R S B\r\n\r\n> ")
                elif cmd.upper() == "B":
                    self.send_data(b"73!\r\n")
                    time.sleep(0.1)
                    self.send_cmd("DISCONNECT")
