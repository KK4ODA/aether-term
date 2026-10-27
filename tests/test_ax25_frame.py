"""AX.25 frame encoding and KISS framing."""

import pytest

from ax25 import kiss
from ax25.frame import Address, Frame, FrameError, FrameType


def test_address_bytes_follow_the_spec():
    # "N0CALL" shifted left, SSID 5, reserved bits set, no C bit, last
    raw = Address("N0CALL", 5).encode(False, True)
    assert raw == bytes([ord(c) << 1 for c in "N0CALL"]) + bytes([0x60 | (5 << 1) | 1])
    # short calls are padded with spaces
    assert Address("W1AW").encode(True, False)[4:6] == bytes([0x40, 0x40])
    assert Address.decode(raw) == (Address("N0CALL", 5), False, True)


@pytest.mark.parametrize("text,call,ssid", [("kk4oda-7", "KK4ODA", 7), ("W1AW", "W1AW", 0),
                                            ("N0CALL-15", "N0CALL", 15)])
def test_address_parse(text, call, ssid):
    a = Address.parse(text)
    assert (a.call, a.ssid) == (call, ssid)
    assert str(a) == text.upper()


@pytest.mark.parametrize("bad", ["", "TOOLONG1", "N0CALL-16", "N0 CALL", "KK4ODA-"])
def test_bad_callsigns_are_refused(bad):
    with pytest.raises(ValueError):
        Address.parse(bad)


@pytest.mark.parametrize("ftype,ctl", [
    (FrameType.SABM, 0x3F), (FrameType.DISC, 0x53), (FrameType.UA, 0x73),
    (FrameType.DM, 0x1F), (FrameType.UI, 0x13)])
def test_u_frame_control_bytes_with_poll(ftype, ctl):
    f = Frame(Address("W1AW"), Address("N0CALL"), ftype, pf=True)
    assert f.control() == ctl


def test_i_and_s_frame_control_bytes():
    me, you = Address("N0CALL"), Address("W1AW")
    assert Frame(you, me, FrameType.I, ns=3, nr=5, pf=True).control() == (5 << 5) | 0x10 | (3 << 1)
    assert Frame(you, me, FrameType.RR, nr=2).control() == (2 << 5) | 0x01
    assert Frame(you, me, FrameType.RNR, nr=7).control() == (7 << 5) | 0x05
    assert Frame(you, me, FrameType.REJ, nr=0, pf=True).control() == 0x10 | 0x09


def test_command_and_response_bits():
    me, you = Address("N0CALL"), Address("W1AW")
    cmd = Frame(you, me, FrameType.SABM, command=True).encode()
    assert cmd[6] & 0x80 and not cmd[13] & 0x80
    rsp = Frame(you, me, FrameType.UA, command=False).encode()
    assert not rsp[6] & 0x80 and rsp[13] & 0x80
    assert Frame.decode(cmd).command and not Frame.decode(rsp).command


def test_round_trip_with_digipeaters():
    f = Frame(Address("KK4ODA", 7), Address("N0CALL"), FrameType.I, ns=6, nr=1,
              info=b"Hello\r", digis=[Address("WD5EMA", 4), Address("RELAY")],
              repeated=[True, False])
    g = Frame.decode(f.encode())
    assert (g.dest, g.src, g.type, g.ns, g.nr, g.info) == (f.dest, f.src, FrameType.I, 6, 1, b"Hello\r")
    assert g.digis == f.digis and g.repeated == [True, False]
    assert not g.path_complete
    g.repeated = [True, True]
    assert g.path_complete
    assert "N0CALL>KK4ODA-7 via WD5EMA-4*,RELAY*" in str(g)


@pytest.mark.parametrize("raw", [b"", b"\x00" * 10, bytes(14) + b"\x01",
                                 Address("A").encode(True, True) + bytes(8)])
def test_garbage_is_a_frame_error(raw):
    with pytest.raises(FrameError):
        Frame.decode(raw)


def test_kiss_escapes_fend_and_fesc():
    payload = bytes([1, kiss.FEND, 2, kiss.FESC, 3])
    enc = kiss.encode(payload)
    assert enc == bytes([kiss.FEND, 0, 1, kiss.FESC, kiss.TFEND, 2,
                         kiss.FESC, kiss.TFESC, 3, kiss.FEND])
    assert kiss.decode_all(enc) == [payload]


def test_kiss_decoder_takes_bytes_in_any_pieces():
    frames = [bytes(range(256)), b"\xc0\xdb" * 10, b"x"]
    stream = b"noise" + b"".join(kiss.encode(f, port=1) for f in frames)
    got = []
    d = kiss.Decoder(lambda port, p: got.append((port, p)))
    for i in range(0, len(stream), 3):               # three bytes at a time
        d.feed(stream[i:i + 3])
    assert got == [(1, f) for f in frames]


def test_kiss_ignores_non_data_frames_and_empty_frames():
    stream = kiss.encode_param(kiss.CMD_TXDELAY, 30) + bytes([kiss.FEND, kiss.FEND]) + kiss.encode(b"ok")
    assert kiss.decode_all(stream) == [b"ok"]


def test_kiss_parameters_in_10ms_units():
    out = kiss.decode_all  # (not data frames: inspect the bytes)
    raw = kiss.tnc_parameters(txdelay_ms=300, persistence=63, slottime_ms=100)
    assert raw == (bytes([0xC0, 0x01, 30, 0xC0]) + bytes([0xC0, 0x02, 63, 0xC0])
                   + bytes([0xC0, 0x03, 10, 0xC0]))
    assert out(raw) == []
