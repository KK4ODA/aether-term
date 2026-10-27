"""A simulated radio channel for AX.25 link tests.

Stations attached to an Air hear every frame any other station sends,
after it has gone through KISS and AX.25 encoding and back.  Frames can
be dropped on purpose; digipeaters named in a frame's path are simulated
by setting their "has been repeated" bits before delivery.
"""

import threading
from typing import Callable, List

from ax25 import kiss
from ax25.frame import Address, Frame
from ax25.link import DataLink, LinkListener, LinkParams

FAST = LinkParams(paclen=32, maxframe=3, frack=0.25, retries=6, resp_delay=0.05, t3=5.0)


class Recorder(LinkListener):
    def __init__(self):
        self.events: List[tuple] = []
        self.data = bytearray()
        self.heard: List[Frame] = []
        self._cond = threading.Condition()

    def _add(self, *e):
        with self._cond:
            self.events.append(e)
            self._cond.notify_all()

    def link_connected(self, remote, digis):
        self._add("connected", str(remote), [str(d) for d in digis])

    def link_data(self, data):
        with self._cond:
            self.data += data
            self._cond.notify_all()

    def link_disconnected(self, reason):
        self._add("disconnected", reason)

    def link_failed(self, reason):
        self._add("failed", reason)

    def frame_heard(self, frame):
        self.heard.append(frame)

    def wait(self, cond, timeout=10.0) -> bool:
        with self._cond:
            return self._cond.wait_for(cond, timeout)

    def kinds(self):
        return [e[0] for e in self.events]


class Air:
    def __init__(self):
        self.stations: List[DataLink] = []
        self.sent: List[Frame] = []
        self.drop: Callable[[Frame], bool] = lambda f: False
        self._lock = threading.Lock()

    def station(self, call: str, accept=False, params=FAST) -> "tuple[DataLink, Recorder]":
        rec = Recorder()
        link = DataLink(Address.parse(call), lambda f, me=call: self._transmit(me, f),
                        rec, params, accept_incoming=accept)
        self.stations.append(link)
        link.start()
        return link, rec

    def _transmit(self, sender: str, frame: Frame) -> None:
        raw = kiss.encode(frame.encode())
        with self._lock:
            self.sent.append(frame)
            if self.drop(frame):
                return
        for payload in kiss.decode_all(raw):
            heard = Frame.decode(payload)
            heard.repeated = [True] * len(heard.digis)   # the digipeaters did their job
            for st in self.stations:
                if str(st.me) != sender:
                    st.receive(heard)

    def stop(self):
        for st in self.stations:
            st.stop()
