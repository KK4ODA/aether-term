"""The VARA-protocol event parser, with Aether HF's and VARA's lines."""

import pytest

from vara.connection import ConnectionState


@pytest.fixture
def modem(qapp):
    from vara.modem import VARAModem
    m = VARAModem()
    got = {}
    for name in ("rf_connected", "rf_disconnected", "sn_report", "bitrate_report",
                 "session_bandwidth", "version_report", "pending_signal",
                 "busy_signal", "ptt_event", "command_event"):
        sig = getattr(m, name)
        sig.connect(lambda *a, n=name: got.setdefault(n, []).append(a))
    m.got = got
    return m


def test_aether_connected_carries_bandwidth(modem):
    modem._handle_event("CONNECTED KK4ODA W1AW-5 2300")
    assert modem.got["rf_connected"] == [("KK4ODA W1AW-5",)]
    assert modem.got["session_bandwidth"] == [("2300",)]
    assert modem.state == ConnectionState.CONNECTED


def test_vara_connected_without_bandwidth(modem):
    modem._handle_event("CONNECTED W1AW-5 KK4ODA")
    assert modem.got["rf_connected"] == [("W1AW-5 KK4ODA",)]
    assert "session_bandwidth" not in modem.got


def test_vara_fm_connected_via_digipeaters(modem):
    modem._handle_event("CONNECTED KK4ODA W1AW-5 via N4XYZ-7 K4ABC-1 WIDE")
    assert modem.got["rf_connected"] == [("KK4ODA W1AW-5",)]
    assert modem.connected_via == ["N4XYZ-7", "K4ABC-1"]
    assert modem.got["session_bandwidth"] == [("WIDE",)]
    modem._handle_event("DISCONNECTED")
    assert modem.connected_via == []


def test_vara_fm_connected_via_one_digipeater(modem):
    modem._handle_event("CONNECTED KK4ODA W1AW-5 via N4XYZ-7 NARROW")
    assert modem.connected_via == ["N4XYZ-7"]
    assert modem.got["session_bandwidth"] == [("NARROW",)]


@pytest.mark.parametrize("via1,via2,expected", [
    ("", "", []),
    ("n4xyz-7", "", ["N4XYZ-7"]),
    ("N4XYZ-7", "K4ABC-1", ["N4XYZ-7", "K4ABC-1"]),
    ("", "K4ABC-1", ["K4ABC-1"]),               # Via 2 alone is still a path
    ("N4XYZ-7,K4ABC-1", "", ["N4XYZ-7", "K4ABC-1"]),
    (" N4XYZ-7  K4ABC-1 ", "", ["N4XYZ-7", "K4ABC-1"]),
])
def test_parse_digipeaters(via1, via2, expected):
    from vara.modem import parse_digipeaters
    assert parse_digipeaters(via1, via2) == expected


@pytest.mark.parametrize("via1,via2", [
    ("N4XYZ-7,K4ABC-1", "W1AW-2"),   # three hops
    ("N4XYZ-16", ""),                # bad SSID
    ("AB", ""),                      # too short
    ("N4XYZ/7", ""),
])
def test_parse_digipeaters_rejects(via1, via2):
    from vara.modem import parse_digipeaters
    with pytest.raises(ValueError):
        parse_digipeaters(via1, via2)


class _Sock:
    def __init__(self):
        self.sent = b""

    def sendall(self, b):
        self.sent += b


@pytest.mark.parametrize("via,expected", [
    ((), b"CONNECT KK4ODA W1AW-5\r"),
    (("N4XYZ-7",), b"CONNECT KK4ODA W1AW-5 VIA N4XYZ-7\r"),
    (("N4XYZ-7", "K4ABC-1"), b"CONNECT KK4ODA W1AW-5 VIA N4XYZ-7 K4ABC-1\r"),
    (("", "K4ABC-1"), b"CONNECT KK4ODA W1AW-5 VIA K4ABC-1\r"),
])
def test_rf_connect_command(modem, via, expected):
    """The VARA TNC reference: CONNECT Source Destination VIA Digi1 Digi2<cr>."""
    modem._cmd_sock = _Sock()
    modem.rf_connect("KK4ODA", "W1AW-5", *via)
    assert modem._cmd_sock.sent == expected


def test_bitrate(modem):
    modem._handle_event("BITRATE (9) 1450 BPS")
    assert modem.got["bitrate_report"] == [("1450 bps (mode 9)",)]


def test_version(modem):
    modem._handle_event("VERSION Aether HF 0.2.0-beta.102")
    assert modem.got["version_report"] == [("Aether HF 0.2.0-beta.102",)]


def test_sn_and_ptt(modem):
    modem._handle_event("SN 7")
    modem._handle_event("PTT ON")
    modem._handle_event("PTT OFF")
    assert modem.got["sn_report"] == [("7",)]
    assert modem.got["ptt_event"] == [(True,), (False,)]


def test_busy_on_off_is_not_remote_busy(modem):
    """Aether HF's channel-busy lines are not VARA's 'remote station busy'."""
    modem._handle_event("BUSY ON")
    modem._handle_event("BUSY OFF")
    assert "busy_signal" not in modem.got
    modem._handle_event("BUSY")
    assert modem.got["busy_signal"] == [()]


@pytest.mark.parametrize("line", ["OK", "WRONG", "DISCONNECTED", "PTT OFF"])
def test_init_cleanup_absorbs_replies(modem, line):
    import threading
    modem._init_cleanup = True
    modem._init_ack = threading.Event()
    modem._handle_event(line)
    assert modem._init_ack.is_set()
    assert "command_event" not in modem.got
    assert "rf_disconnected" not in modem.got


@pytest.mark.parametrize("line", ["BUFFER 0", "IAMALIVE", "ENCRYPTION DISABLED",
                                  "LINK REGISTERED", "REGISTERED KK4ODA"])
def test_informational_lines_change_nothing(modem, line):
    modem._handle_event(line)
    assert modem.state == ConnectionState.DISCONNECTED
    assert set(modem.got) <= {"command_event"}
