"""A minimal AGWPE server (Soundmodem / Direwolf stand-in) for the tests.

Speaks the binary AGWPE frame protocol on a local port:
* ``X`` register callsign → answered ``X`` with success;
* ``C`` connect, or ``v`` connect via digipeaters → answered ``C`` from
  the remote station (link up); the digipeaters of a ``v`` are recorded;
* ``D`` connected data → recorded; ``H\\r`` is answered with a help line,
  in a node's bare-CR style;
* ``d`` disconnect → answered ``d``.
"""

import socket
import struct
import threading

from vara.agwpe import AGWPEFrame, HEADER_SIZE, decode_frame, encode_frame


class FakeAGWPE:
    def __init__(self, answer_connect: bool = True):
        self.answer_connect = answer_connect
        self.frames: list[AGWPEFrame] = []
        self.via: list[str] = []            # digipeaters of the last 'v' connect
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen()
        self.port = self._srv.getsockname()[1]
        self._conns: list[socket.socket] = []

    def start(self) -> "FakeAGWPE":
        threading.Thread(target=self._accept, daemon=True, name="FakeAGWPE").start()
        return self

    def stop(self):
        """Close everything, as Soundmodem quitting would."""
        for s in [self._srv] + self._conns:
            try:
                s.shutdown(socket.SHUT_RDWR)   # wakes our reader, sends FIN
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass

    def kinds(self) -> str:
        return "".join(f.data_kind for f in self.frames)

    def data_sent(self) -> bytes:
        return b"".join(f.data for f in self.frames if f.data_kind == "D")

    # ── internals ───────────────────────────────────────────────────

    def _accept(self):
        while True:
            try:
                c, _ = self._srv.accept()
            except OSError:
                return
            self._conns.append(c)
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    @staticmethod
    def _recv_exact(c: socket.socket, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = c.recv(n - len(buf))
            if not chunk:
                raise OSError("closed")
            buf += chunk
        return buf

    def _serve(self, c: socket.socket):
        try:
            while True:
                header = self._recv_exact(c, HEADER_SIZE)
                n = struct.unpack_from("<I", header, 28)[0]
                data = self._recv_exact(c, n) if n else b""
                f = decode_frame(header, data)
                self.frames.append(f)
                self._answer(c, f)
        except OSError:
            return

    def _send(self, c, kind, call_from, call_to, data=b""):
        c.sendall(encode_frame(AGWPEFrame(port=0, data_kind=kind, pid=0xF0,
                                          call_from=call_from, call_to=call_to,
                                          data=data)))

    def _answer(self, c, f: AGWPEFrame):
        if f.data_kind == "X":
            self._send(c, "X", f.call_from, "", b"\x01")
        elif f.data_kind == "v":
            n = f.data[0]
            self.via = [f.data[1 + 10 * i: 11 + 10 * i].split(b"\x00", 1)[0].decode()
                        for i in range(n)]
            if self.answer_connect:
                self._send(c, "C", f.call_to, f.call_from,
                           f"*** CONNECTED With Station {f.call_to}\r".encode())
        elif f.data_kind == "C" and self.answer_connect:
            self._send(c, "C", f.call_to, f.call_from,
                       f"*** CONNECTED With Station {f.call_to}\r".encode())
        elif f.data_kind == "D" and f.data.strip().upper() == b"H":
            self._send(c, "D", f.call_to, f.call_from,
                       b"W1AW-5} Help: BBS CHAT NODES BYE\r")
        elif f.data_kind == "d":
            self._send(c, "d", f.call_to, f.call_from)
