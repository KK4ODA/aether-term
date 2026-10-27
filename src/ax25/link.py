"""
ax25/link.py — AX.25 v2.0 connected mode (the data link), modulo 8.

What Soundmodem or a TNC2 does for a terminal: set up a connection
(SABM / UA), carry numbered I frames with a send window and
acknowledgements, recover lost frames (REJ, and polling on the T1 timer),
keep an idle link checked (T3), and take it down (DISC / UA, DM).

One DataLink is one connection between this station and one other.  It
runs on its own thread: frames heard, calls from the window and timer
expiries all go through one queue, so the state needs no locks.  It
sends frames through ``send_frame`` and reports through a LinkListener.

Timers:
    T1  retry timer: an unacknowledged frame, or a call or DISC with no
        answer.  ``frack`` seconds, times (2 x digipeaters + 1).
    T2  response delay: an I frame is acknowledged after this, so a
        burst of frames gets one RR, unless an I frame of ours carries
        the acknowledgement first.
    T3  idle check: a quiet link is polled after this.
"""

import logging
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional

from ax25.frame import Address, Frame, FrameType

log = logging.getLogger(__name__)


class LinkState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"          # SABM sent, waiting for UA
    CONNECTED = "connected"
    TIMER_RECOVERY = "timer recovery"  # polled the other side, waiting for F=1
    DISCONNECTING = "disconnecting"    # DISC sent, waiting for UA / DM


@dataclass
class LinkParams:
    paclen: int = 128          # bytes of text per I frame
    maxframe: int = 4          # k: I frames sent before an acknowledgement
    frack: float = 7.0         # T1 base, seconds
    retries: int = 10          # N2
    resp_delay: float = 1.5    # T2, seconds
    t3: float = 180.0          # idle check, seconds

    def t1(self, digis: int) -> float:
        return self.frack * (2 * digis + 1)


class LinkListener:
    """What a DataLink reports (called on the link's thread)."""

    def link_connected(self, remote: Address, digis: List[Address]) -> None: ...
    def link_data(self, data: bytes) -> None: ...
    def link_disconnected(self, reason: str) -> None: ...
    def link_failed(self, reason: str) -> None: ...      # a call that never connected
    def frame_heard(self, frame: Frame) -> None: ...     # every frame (monitor)


def _mod8(x: int) -> int:
    return x & 7


class DataLink:
    def __init__(self, me: Address, send_frame: Callable[[Frame], None],
                 listener: Optional[LinkListener] = None,
                 params: Optional[LinkParams] = None,
                 accept_incoming: bool = False):
        self.me = me
        self.params = params or LinkParams()
        self.accept_incoming = accept_incoming
        self._send_frame = send_frame
        self._listener = listener or LinkListener()
        self._q: "queue.Queue[tuple]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._timers: Dict[str, float] = {}
        self._reset_link()
        self._calling_cancelled = False      # a call cancelled before it connected
        self.state = LinkState.DISCONNECTED
        self.remote: Optional[Address] = None
        self.digis: List[Address] = []

    # ── public: any thread ─────────────────────────────────────────

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name=f"AX25-{self.me}")
            self._thread.start()

    def stop(self) -> None:
        if self._thread is not None:
            self._q.put(("stop",))
            if self._thread is not threading.current_thread():
                self._thread.join(timeout=2)
            self._thread = None

    def connect(self, remote: Address, digis: Optional[List[Address]] = None) -> None:
        self._q.put(("connect", remote, list(digis or [])))

    def disconnect(self) -> None:
        self._q.put(("disconnect",))

    def send(self, data: bytes) -> None:
        if data:
            self._q.put(("send", bytes(data)))

    def receive(self, frame: Frame) -> None:
        """A frame heard from the TNC."""
        self._q.put(("frame", frame))

    @property
    def is_connected(self) -> bool:
        return self.state in (LinkState.CONNECTED, LinkState.TIMER_RECOVERY)

    @property
    def unacked(self) -> int:
        return _mod8(self._vs - self._va)

    @property
    def pending(self) -> int:
        """Bytes given to send and not yet acknowledged."""
        return sum(map(len, self._out)) + sum(len(i) for i in self._sent.values())

    # ── the link's thread ──────────────────────────────────────────

    def _run(self) -> None:
        while True:
            wait = None
            if self._timers:
                wait = max(0.0, min(self._timers.values()) - time.monotonic())
            try:
                item = self._q.get(timeout=wait)
            except queue.Empty:
                item = None
            if item is not None:
                if item[0] == "stop":
                    return
                try:
                    getattr(self, "_on_" + item[0])(*item[1:])
                except Exception:
                    log.exception("AX.25 link: %s failed", item[0])
            now = time.monotonic()
            for name, due in sorted(self._timers.items(), key=lambda kv: kv[1]):
                if due <= now and self._timers.get(name) == due:
                    del self._timers[name]
                    try:
                        getattr(self, "_" + name + "_expired")()
                    except Exception:
                        log.exception("AX.25 link: %s expiry failed", name)

    def _start_timer(self, name: str, seconds: float) -> None:
        self._timers[name] = time.monotonic() + seconds

    def _stop_timer(self, name: str) -> None:
        self._timers.pop(name, None)

    def _t1(self) -> float:
        return self.params.t1(len(self.digis))

    def _reset_link(self) -> None:
        self._vs = self._va = self._vr = 0
        self._rc = 0
        self._sent: Dict[int, bytes] = {}          # N(S) → info, unacknowledged
        self._out: "deque[bytes]" = deque()        # waiting for the window
        self._peer_busy = False
        self._reject_sent = False
        self._timers.clear()

    # ── frames out ─────────────────────────────────────────────────

    def _frame(self, ftype: FrameType, command: bool, pf: bool = False,
               **kw) -> None:
        f = Frame(self.remote, self.me, ftype, command=command, pf=pf,
                  digis=list(self.digis), repeated=[False] * len(self.digis), **kw)
        log.debug("AX.25 TX %s", f)
        self._send_frame(f)

    def _reply(self, to: Frame, ftype: FrameType, final: bool) -> None:
        """A response to *to* from a station we may have no link with."""
        digis = list(reversed(to.digis))
        f = Frame(to.src, self.me, ftype, command=False, pf=final,
                  digis=digis, repeated=[False] * len(digis))
        log.debug("AX.25 TX %s", f)
        self._send_frame(f)

    def _send_rr(self, command: bool, pf: bool) -> None:
        self._stop_timer("t2")
        self._frame(FrameType.RR, command, pf, nr=self._vr)

    # ── requests from the window ───────────────────────────────────

    def _on_connect(self, remote: Address, digis: List[Address]) -> None:
        if self.state is not LinkState.DISCONNECTED:
            log.warning("AX.25 connect ignored: link is %s", self.state.value)
            return
        self._reset_link()
        self.remote, self.digis = remote, digis
        self.state = LinkState.CONNECTING
        self._frame(FrameType.SABM, True, True)
        self._start_timer("t1", self._t1())

    def _on_disconnect(self) -> None:
        if self.state in (LinkState.CONNECTED, LinkState.TIMER_RECOVERY,
                          LinkState.CONNECTING):
            was_calling = self.state is LinkState.CONNECTING
            self._out.clear()
            self._timers.clear()
            self._rc = 0
            self.state = LinkState.DISCONNECTING
            self._frame(FrameType.DISC, True, True)
            self._start_timer("t1", self._t1())
            if was_calling:
                # nobody connected: say so now, the DISC only stops the call
                self._listener.link_failed("call cancelled")
                self._calling_cancelled = True

    def _on_send(self, data: bytes) -> None:
        if not self.is_connected:
            log.warning("AX.25 send dropped: link is %s", self.state.value)
            return
        n = self.params.paclen
        for i in range(0, len(data), n):
            self._out.append(data[i:i + n])
        self._push()

    def _push(self) -> None:
        """Send queued text while the window allows."""
        if self.state is not LinkState.CONNECTED or self._peer_busy:
            return
        while self._out and self.unacked < self.params.maxframe:
            info = self._out.popleft()
            ns = self._vs
            self._sent[ns] = info
            self._vs = _mod8(ns + 1)
            self._stop_timer("t2")              # this frame carries the ack
            self._frame(FrameType.I, True, False, ns=ns, nr=self._vr, info=info)
            if "t1" not in self._timers:
                self._stop_timer("t3")
                self._start_timer("t1", self._t1())

    def _retransmit_from(self, nr: int) -> None:
        ns = nr
        while ns != self._vs:
            info = self._sent.get(ns)
            if info is None:
                break
            self._frame(FrameType.I, True, False, ns=ns, nr=self._vr, info=info)
            ns = _mod8(ns + 1)
        self._stop_timer("t2")
        self._stop_timer("t3")
        self._start_timer("t1", self._t1())

    # ── frames in ──────────────────────────────────────────────────

    def _on_frame(self, f: Frame) -> None:
        try:
            self._listener.frame_heard(f)
        except Exception:
            log.exception("frame_heard listener failed")
        if f.dest != self.me or not f.path_complete:
            return
        if f.type is FrameType.UI:
            return
        log.debug("AX.25 RX %s", f)
        if self.remote is None or f.src != self.remote or self.state is LinkState.DISCONNECTED:
            self._from_stranger(f)
            return
        handler = {
            LinkState.CONNECTING: self._rx_connecting,
            LinkState.CONNECTED: self._rx_connected,
            LinkState.TIMER_RECOVERY: self._rx_connected,
            LinkState.DISCONNECTING: self._rx_disconnecting,
        }[self.state]
        handler(f)

    def _from_stranger(self, f: Frame) -> None:
        """A frame for us from a station we have no link with."""
        if f.type is FrameType.SABM:
            if self.state is LinkState.DISCONNECTED and self.accept_incoming:
                self._reset_link()
                self.remote = f.src
                self.digis = list(reversed(f.digis))
                self.state = LinkState.CONNECTED
                self._reply(f, FrameType.UA, f.pf)
                self._start_timer("t3", self.params.t3)
                self._listener.link_connected(self.remote, self.digis)
            else:
                self._reply(f, FrameType.DM, f.pf)      # busy / not accepting
        elif f.type is FrameType.DISC:
            self._reply(f, FrameType.DM, f.pf)
        elif f.command and f.pf and f.type not in (FrameType.DM, FrameType.UA):
            self._reply(f, FrameType.DM, True)

    def _rx_connecting(self, f: Frame) -> None:
        if f.type is FrameType.UA:
            self._stop_timer("t1")
            self._vs = self._va = self._vr = 0
            self.state = LinkState.CONNECTED
            self._start_timer("t3", self.params.t3)
            self._listener.link_connected(self.remote, self.digis)
        elif f.type is FrameType.DM:
            self._timers.clear()
            self.state = LinkState.DISCONNECTED
            self._listener.link_failed(f"{self.remote} is busy or refused the call")
        elif f.type is FrameType.SABM:
            # both called at once: answer, and count us connected
            self._reply(f, FrameType.UA, f.pf)
            self._rx_connecting(Frame(self.me, self.remote, FrameType.UA))
        elif f.type is FrameType.DISC:
            self._reply(f, FrameType.DM, f.pf)

    def _rx_disconnecting(self, f: Frame) -> None:
        if f.type in (FrameType.UA, FrameType.DM):
            self._down("disconnected")
        elif f.type is FrameType.DISC:
            self._reply(f, FrameType.UA, f.pf)
            self._down("disconnected")
        elif f.type is FrameType.SABM:
            self._reply(f, FrameType.DM, f.pf)
        elif f.command and f.pf:
            self._reply(f, FrameType.DM, True)

    def _rx_connected(self, f: Frame) -> None:
        t = f.type
        if t is FrameType.DISC:
            self._reply(f, FrameType.UA, f.pf)
            self._down(f"{self.remote} disconnected")
            return
        if t is FrameType.DM:
            self._down(f"{self.remote} ended the link (DM)")
            return
        if t is FrameType.SABM:
            # The other side reset the link: start numbering again
            self._reply(f, FrameType.UA, f.pf)
            self._reset_link()
            self.state = LinkState.CONNECTED
            self._start_timer("t3", self.params.t3)
            return
        if t is FrameType.FRMR:
            log.warning("AX.25 FRMR from %s: %s", f.src, f.info.hex())
            self._frame(FrameType.DISC, True, True)
            self._down(f"{self.remote} reported a protocol error (FRMR)")
            return
        if t is FrameType.UA:
            return                                   # stray
        if t is FrameType.I:
            self._rx_iframe(f)
        elif t in (FrameType.RR, FrameType.RNR, FrameType.REJ):
            self._rx_sframe(f)

    def _nr_ok(self, nr: int) -> bool:
        return _mod8(nr - self._va) <= _mod8(self._vs - self._va)

    def _ack_through(self, nr: int) -> bool:
        """Frames up to N(R)-1 are acknowledged.  True if any newly were."""
        moved = nr != self._va
        while self._va != nr:
            self._sent.pop(self._va, None)
            self._va = _mod8(self._va + 1)
        if moved:
            self._rc = 0
        return moved

    def _after_ack(self, moved: bool) -> None:
        if self.state is not LinkState.CONNECTED:
            return
        if self._va == self._vs:
            self._stop_timer("t1")
            self._start_timer("t3", self.params.t3)
        elif moved:
            self._start_timer("t1", self._t1())

    def _rx_iframe(self, f: Frame) -> None:
        if not f.command:
            return                                   # I frames are commands
        if not self._nr_ok(f.nr):
            self._nr_error(f.nr)
            return
        moved = self._ack_through(f.nr)
        if self.state is LinkState.CONNECTED:
            self._after_ack(moved)
        if f.ns == self._vr:
            self._vr = _mod8(self._vr + 1)
            self._reject_sent = False
            try:
                self._listener.link_data(f.info)
            except Exception:
                log.exception("link_data listener failed")
            if f.pf:
                self._send_rr(False, True)
            elif "t2" not in self._timers:
                self._start_timer("t2", self.params.resp_delay)
        else:
            if not self._reject_sent:
                self._reject_sent = True
                self._stop_timer("t2")
                self._frame(FrameType.REJ, False, f.pf, nr=self._vr)
            elif f.pf:
                self._send_rr(False, True)
        if self.state is LinkState.CONNECTED:
            self._push()

    def _rx_sframe(self, f: Frame) -> None:
        if f.command and f.pf:
            self._send_rr(False, True)              # answer the poll
        if not self._nr_ok(f.nr):
            self._nr_error(f.nr)
            return
        self._peer_busy = f.type is FrameType.RNR
        if self.state is LinkState.TIMER_RECOVERY:
            self._ack_through(f.nr)
            if not f.command and f.pf:
                # the answer to our poll: back to normal
                self._stop_timer("t1")
                self.state = LinkState.CONNECTED
                self._rc = 0
                if self._va != self._vs and not self._peer_busy:
                    self._retransmit_from(self._va)
                elif self._va == self._vs:
                    self._start_timer("t3", self.params.t3)
                else:
                    self._start_timer("t1", self._t1())
            return
        moved = self._ack_through(f.nr)
        if f.type is FrameType.REJ and self._va != self._vs:
            self._retransmit_from(self._va)
        else:
            self._after_ack(moved)
        self._push()

    def _nr_error(self, nr: int) -> None:
        log.warning("AX.25: N(R)=%d outside V(A)=%d..V(S)=%d; resetting link",
                    nr, self._va, self._vs)
        # Re-establish: the other side's numbering no longer matches ours
        lost = self.pending
        self._reset_link()
        self.state = LinkState.CONNECTING
        self._frame(FrameType.SABM, True, True)
        self._start_timer("t1", self._t1())
        if lost:
            log.warning("AX.25: %d bytes not acknowledged were dropped", lost)

    # ── timers ─────────────────────────────────────────────────────

    def _t1_expired(self) -> None:
        n2 = self.params.retries
        if self.state is LinkState.CONNECTING:
            self._rc += 1
            if self._rc > n2:
                self.state = LinkState.DISCONNECTED
                self._timers.clear()
                self._listener.link_failed(
                    f"no answer from {self.remote} after {n2} tries")
                return
            self._frame(FrameType.SABM, True, True)
            self._start_timer("t1", self._t1())
        elif self.state is LinkState.DISCONNECTING:
            self._rc += 1
            if self._rc > n2:
                self._down("disconnected (no answer to DISC)")
                return
            self._frame(FrameType.DISC, True, True)
            self._start_timer("t1", self._t1())
        elif self.state is LinkState.CONNECTED:
            self._rc = 1
            self.state = LinkState.TIMER_RECOVERY
            self._send_rr(True, True)                # "where are you?"
            self._start_timer("t1", self._t1())
        elif self.state is LinkState.TIMER_RECOVERY:
            if self._rc >= n2:
                self._frame(FrameType.DISC, True, True)
                self._down(f"link lost: no answer from {self.remote} after {n2} polls")
                return
            self._rc += 1
            self._send_rr(True, True)
            self._start_timer("t1", self._t1())

    def _t2_expired(self) -> None:
        if self.is_connected:
            self._send_rr(False, False)

    def _t3_expired(self) -> None:
        if self.state is LinkState.CONNECTED:
            self._rc = 0
            self.state = LinkState.TIMER_RECOVERY
            self._send_rr(True, True)
            self._start_timer("t1", self._t1())

    # ── end of a link ──────────────────────────────────────────────

    def _down(self, reason: str) -> None:
        cancelled, self._calling_cancelled = self._calling_cancelled, False
        self._reset_link()
        self.state = LinkState.DISCONNECTED
        if not cancelled:
            self._listener.link_disconnected(reason)

