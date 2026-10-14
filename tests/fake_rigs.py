"""Stand-ins for Hamlib's rigctld and FLrig, for the PTT tests.

* ``FakeRigctld`` speaks rigctld's TCP protocol in the extended-response form
  Aether Term uses (``+\\cmd`` lines, answered with ``RPRT 0``) and records
  every ``set_ptt`` value.
* ``FakeFLrig`` serves FLrig's XML-RPC methods (``main.get_version``,
  ``rig.get_vfo``, ``rig.set_ptt``, ``rig.get_ptt``) and records ``set_ptt``.
"""

import socket
import threading
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer


def closed_port() -> int:
    """A local port with nothing listening on it."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class FakeRigctld:
    def __init__(self):
        self.ptt: list[int] = []
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen()
        self.port = self._srv.getsockname()[1]
        self._conns: list[socket.socket] = []

    def start(self) -> "FakeRigctld":
        threading.Thread(target=self._accept, daemon=True, name="FakeRigctld").start()
        return self

    def stop(self):
        for s in [self._srv] + self._conns:
            try:
                s.close()
            except OSError:
                pass

    @property
    def keyed(self) -> bool:
        return bool(self.ptt) and self.ptt[-1] == 1

    def _accept(self):
        while True:
            try:
                c, _ = self._srv.accept()
            except OSError:
                return
            self._conns.append(c)
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c: socket.socket):
        buf = b""
        while True:
            try:
                chunk = c.recv(1024)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode().lstrip("+").lstrip("\\").strip()
                name, _, arg = cmd.partition(" ")
                if name == "set_ptt":
                    self.ptt.append(int(arg))
                body = "Frequency: 7103000\n" if name == "get_freq" else ""
                try:
                    c.sendall(f"{name}: {arg}\n{body}RPRT 0\n".encode())
                except OSError:
                    return


class FakeFLrig:
    def __init__(self):
        self.ptt: list[int] = []
        self._state = 0

        class Quiet(SimpleXMLRPCRequestHandler):
            def log_message(self, *a):
                pass

        self._srv = SimpleXMLRPCServer(("127.0.0.1", 0), requestHandler=Quiet,
                                       allow_none=True, logRequests=False)
        self.port = self._srv.server_address[1]
        self._srv.register_function(lambda: "2.0.05", "main.get_version")
        self._srv.register_function(lambda: "7103000", "rig.get_vfo")
        self._srv.register_function(self._set_ptt, "rig.set_ptt")
        self._srv.register_function(lambda: self._state, "rig.get_ptt")

    def _set_ptt(self, on):
        self._state = int(on)
        self.ptt.append(int(on))
        return 0

    def start(self) -> "FakeFLrig":
        threading.Thread(target=self._srv.serve_forever, daemon=True,
                         name="FakeFLrig").start()
        return self

    def stop(self):
        self._srv.shutdown()
        self._srv.server_close()

    @property
    def keyed(self) -> bool:
        return bool(self.ptt) and self.ptt[-1] == 1
