"""The AX.25 connected-mode data link, between two stations on a simulated channel."""

import pytest

from ax25.frame import Address, FrameType
from ax25.link import LinkState
from ax25_air import Air, FAST


@pytest.fixture
def air():
    a = Air()
    yield a
    a.stop()


def _connect(air, digis=None):
    me, my = air.station("N0CALL")
    bbs, theirs = air.station("KK4ODA-7", accept=True)
    me.connect(Address.parse("KK4ODA-7"), [Address.parse(d) for d in (digis or [])])
    assert my.wait(lambda: "connected" in my.kinds())
    assert theirs.wait(lambda: "connected" in theirs.kinds())
    return me, my, bbs, theirs


def test_connect_and_disconnect(air):
    me, my, bbs, theirs = _connect(air)
    assert my.events[0] == ("connected", "KK4ODA-7", [])
    assert theirs.events[0] == ("connected", "N0CALL", [])
    assert [f.type for f in air.sent[:2]] == [FrameType.SABM, FrameType.UA]
    me.disconnect()
    assert theirs.wait(lambda: "disconnected" in theirs.kinds())
    assert my.wait(lambda: "disconnected" in my.kinds())
    assert me.state is LinkState.DISCONNECTED and bbs.state is LinkState.DISCONNECTED


def test_the_other_side_hangs_up(air):
    me, my, bbs, theirs = _connect(air)
    bbs.disconnect()
    assert my.wait(lambda: ("disconnected", "KK4ODA-7 disconnected") in my.events)


def test_data_both_ways_in_order_across_many_frames(air):
    me, my, bbs, theirs = _connect(air)
    up = bytes(range(256)) * 3                 # 768 bytes: 24 frames of 32
    down = b"".join(b"line %03d of the welcome\r\n" % i for i in range(40))
    me.send(up)
    bbs.send(down)
    assert theirs.wait(lambda: bytes(theirs.data) == up)
    assert my.wait(lambda: bytes(my.data) == down)
    sent_i = [f for f in air.sent if f.type is FrameType.I and str(f.src) == "N0CALL"]
    assert all(len(f.info) <= FAST.paclen for f in sent_i)
    assert me.state is LinkState.CONNECTED


def test_never_more_than_maxframe_unacknowledged(air):
    me, my, bbs, theirs = _connect(air)
    air.drop = lambda f: str(f.src) == "KK4ODA-7"     # no acknowledgements at all
    me.send(b"x" * FAST.paclen * 10)
    my.wait(lambda: False, timeout=0.4)
    first = [f for f in air.sent if f.type is FrameType.I and str(f.src) == "N0CALL"]
    assert len({f.ns for f in first}) == FAST.maxframe
    air.drop = lambda f: False
    assert theirs.wait(lambda: len(theirs.data) == FAST.paclen * 10)


def test_lost_i_frame_is_recovered_by_reject(air):
    me, my, bbs, theirs = _connect(air)
    dropped = []

    def drop_second_i(f):
        if f.type is FrameType.I and str(f.src) == "N0CALL" and f.ns == 1 and not dropped:
            dropped.append(f)
            return True
        return False
    air.drop = drop_second_i
    data = b"".join(b"%02d" % i for i in range(60))
    me.send(data)
    assert theirs.wait(lambda: bytes(theirs.data) == data)
    assert dropped
    assert any(f.type is FrameType.REJ for f in air.sent)


def test_lost_acknowledgement_is_recovered_by_polling(air):
    me, my, bbs, theirs = _connect(air)
    lost = []

    def drop_acks(f):
        if f.type is FrameType.RR and str(f.src) == "KK4ODA-7" and not f.pf and len(lost) < 3:
            lost.append(f)
            return True
        return False
    air.drop = drop_acks
    me.send(b"hello")
    assert theirs.wait(lambda: bytes(theirs.data) == b"hello")
    # our T1 runs out, we poll (RR P=1), the answer (F=1) acknowledges
    assert my.wait(lambda: me.unacked == 0 and me.state is LinkState.CONNECTED, timeout=5)
    polls = [f for f in air.sent if str(f.src) == "N0CALL" and f.type is FrameType.RR and f.pf]
    assert polls
    assert bytes(theirs.data) == b"hello"           # not delivered twice


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_frames_lost_at_random(air, seed):
    """Lose a fifth of all frames, both ways: all data still arrives, once,
    in order.  (Random: a fixed every-5th pattern can line up with the
    retransmission cycle and lose the same frame every time.)"""
    import random
    me, my, bbs, theirs = _connect(air)
    rnd = random.Random(seed)
    air.drop = lambda f: rnd.random() < 0.2
    up = b"".join(b"<%03d>" % i for i in range(120))
    down = b"".join(b"[%03d]" % i for i in range(120))
    me.send(up)
    bbs.send(down)
    assert theirs.wait(lambda: len(theirs.data) >= len(up), timeout=30), len(theirs.data)
    assert my.wait(lambda: len(my.data) >= len(down), timeout=30), len(my.data)
    assert bytes(theirs.data) == up and bytes(my.data) == down


def test_no_answer_gives_up_after_the_retries(air):
    me, my = air.station("N0CALL")
    me.connect(Address.parse("NOBODY"))
    assert my.wait(lambda: "failed" in my.kinds(), timeout=10)
    assert my.events[-1] == ("failed", f"no answer from NOBODY after {FAST.retries} tries")
    sabms = [f for f in air.sent if f.type is FrameType.SABM]
    assert len(sabms) == FAST.retries + 1


def test_station_not_accepting_answers_dm(air):
    me, my = air.station("N0CALL")
    air.station("BUSY1")                          # not accepting calls
    me.connect(Address.parse("BUSY1"))
    assert my.wait(lambda: "failed" in my.kinds())
    assert "busy or refused" in my.events[-1][1]


def test_link_lost_mid_session(air):
    me, my, bbs, theirs = _connect(air)
    bbs.stop()                                    # the other station goes off the air
    air.drop = lambda f: str(f.src) == "KK4ODA-7"
    me.send(b"anyone there?")
    assert my.wait(lambda: "disconnected" in my.kinds(), timeout=15)
    assert "link lost" in my.events[-1][1]


def test_cancel_a_call_in_progress(air):
    me, my = air.station("N0CALL")
    me.connect(Address.parse("NOBODY"))
    my.wait(lambda: False, timeout=0.1)
    me.disconnect()
    assert my.wait(lambda: ("failed", "call cancelled") in my.events)
    assert my.wait(lambda: me.state is LinkState.DISCONNECTED, timeout=10)
    assert "disconnected" not in my.kinds()       # the window hears of it once


def test_digipeater_path_is_used_both_ways(air):
    me, my, bbs, theirs = _connect(air, digis=["WD5EMA-4", "RELAY"])
    assert theirs.events[0] == ("connected", "N0CALL", ["RELAY", "WD5EMA-4"])
    bbs.send(b"hi")
    assert my.wait(lambda: bytes(my.data) == b"hi")
    replies = [f for f in air.sent if str(f.src) == "KK4ODA-7"]
    assert all([str(d) for d in f.digis] == ["RELAY", "WD5EMA-4"] for f in replies)


def test_frames_not_yet_through_the_digipeaters_are_ignored(air):
    me, my = air.station("N0CALL")
    from ax25.frame import Frame
    sabm = Frame(Address.parse("N0CALL"), Address.parse("KK4ODA-7"), FrameType.SABM,
                 pf=True, digis=[Address.parse("WD5EMA-4")], repeated=[False])
    me.accept_incoming = True
    me.receive(sabm)                               # heard direct, before the digi
    my.wait(lambda: False, timeout=0.2)
    assert "connected" not in my.kinds()


def test_stranger_is_told_we_are_busy(air):
    me, my, bbs, theirs = _connect(air)
    other, oth = air.station("W1AW")
    other.connect(Address.parse("KK4ODA-7"))      # KK4ODA-7 already has a link
    assert oth.wait(lambda: "failed" in oth.kinds())
    assert bbs.is_connected and bbs.remote == Address.parse("N0CALL")
