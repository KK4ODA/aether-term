"""A fake KISS TNC on TCP, with a BBS station on the far side of the "air".

Aether Term's KissModem connects to it as it would to Direwolf's KISS
port.  Frames it sends are handed (after KISS and AX.25 decoding) to a
DataLink that accepts calls as the BBS station; that station's frames
come back the same way.  The BBS answers like Aether BBS: a welcome and
"> ", ;TRANSPORT? with ";TRANSPORT KISS", H with help, B with 73 and a
disconnect.
"""

import socket
import threading
from typing import List

from ax25 import kiss
from ax25.frame import Address, Frame
from ax25.link import DataLink, LinkListener, LinkParams

FAST = LinkParams(paclen=64, maxframe=4, frack=0.4, retries=4, resp_delay=0.05, t3=30)


class _Bbs(LinkListener):
    def __init__(self, tnc: "FakeKissTnc"):
        self.tnc = tnc
        self.buf = b""
        self.callers: List[str] = []

    def link_connected(self, remote, digis):
        self.callers.append(str(remote))
        self.tnc.bbs.send(f"Welcome to {self.tnc.bbs.me}, {remote}\r\n> ".encode())

    def link_data(self, data):
        self.tnc.received += data
        self.buf += data
        while b"\r\n" in self.buf:
            line, self.buf = self.buf.split(b"\r\n", 1)
            cmd = line.decode().strip()
            if cmd == ";TRANSPORT?":
                self.tnc.bbs.send(b";TRANSPORT KISS\r\n")
                self.tnc.bbs.send(b"\r\n> ")
            elif cmd.upper() == "H":
                self.tnc.bbs.send(b"Help: L R S B\r\n\r\n> ")
            elif cmd.upper() == "B":
                self.tnc.bbs.send(b"73!\r\n")
                threading.Timer(0.3, self.tnc.bbs.disconnect).start()


class FakeKissTnc:
    def __init__(self, bbs_call: str = "KK4ODA-7", params: LinkParams = FAST,
                 answer: bool = True):
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.client = None
        self.raw = bytearray()                # everything the modem wrote
        self.frames: List[Frame] = []         # AX.25 frames the modem sent
        self.received = bytearray()           # text the BBS received
        self.drop = lambda frame: False       # lose a frame on the air
        self.bbs_handler = _Bbs(self)
        self.bbs = DataLink(Address.parse(bbs_call), self._bbs_transmit,
                            self.bbs_handler, params, accept_incoming=answer)
        self.bbs.start()
        self._dec = kiss.Decoder(self._from_modem)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        try:
            c, _ = self.srv.accept()
        except OSError:
            return
        self.client = c
        while True:
            try:
                data = c.recv(4096)
            except OSError:
                return
            if not data:
                return
            self.raw += data
            self._dec.feed(data)

    def _from_modem(self, port, payload):
        f = Frame.decode(payload)
        self.frames.append(f)
        if not self.drop(f):
            f.repeated = [True] * len(f.digis)
            self.bbs.receive(f)

    def _bbs_transmit(self, frame: Frame):
        if self.drop(frame) or self.client is None:
            return
        frame.repeated = [True] * len(frame.digis)    # the digipeaters did their job
        try:
            self.client.sendall(kiss.encode(frame.encode()))
        except OSError:
            pass

    def kill_link(self):
        """The TNC goes away (radio switched off, out of range)."""
        c, self.client = self.client, None
        if c is not None:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.close()

    def stop(self):
        self.bbs.stop()
        self.kill_link()
        self.srv.close()
