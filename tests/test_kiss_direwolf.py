"""KISS TNC mode over a real modem: Direwolf, 1200 baud AFSK.

    Aether Term ─KISS/TCP─ Direwolf A ─audio─ Direwolf B ─AGWPE─ station

The station is Direwolf's own AX.25 stack answering for a callsign an
AGWPE client registered, and in the last test the real Aether BBS on a
Soundmodem instance.  So Aether Term's AX.25 link layer is tested against
independent implementations, through real modulation.

Skipped without direwolf (Linux; apt install direwolf).  The Aether BBS
test also needs a BBS checkout (see test_local_test_bbs.py).
"""

import time

import pytest

import direwolf_air
from conftest import pump

pytestmark = pytest.mark.skipif(not direwolf_air.available(),
                                reason="needs direwolf (apt install direwolf)")


@pytest.fixture
def air():
    a = direwolf_air.DirewolfAir()
    yield a
    a.stop()


def test_call_a_direwolf_station(qapp, air):
    from tnc.transports import TcpTransport
    from vara.agwpe import AGWPEClient
    from vara.kiss_modem import KissModem
    from ax25.link import LinkParams

    heard = []
    agw = AGWPEClient("127.0.0.1", air.agw_port, on_frame=heard.append)
    assert agw.connect(5)
    agw.register_callsign("N0BBS-10")
    m = KissModem(TcpTransport("127.0.0.1", air.kiss_port),
                  LinkParams(paclen=128, maxframe=4, frack=4.0, retries=6))
    got = []
    m.data_received.connect(got.append)
    errors = []
    m.error_signal.connect(errors.append)
    try:
        m.connect_to_modem()
        assert pump(qapp, until=lambda: m.state.name == "MODEM_CONNECTED", timeout=10), errors
        m.initialize_modem("N0CALL")
        m.rf_connect("N0CALL", "N0BBS-10")
        assert pump(qapp, until=lambda: m.state.name == "CONNECTED", timeout=60), \
            f"{errors}\n{air.logs()}"
        assert any(f.data_kind == "C" for f in heard)
        m.send_data("Hello from Aether Term\r")
        assert pump(qapp, until=lambda: any(f.data_kind == "D" for f in heard), timeout=60)
        assert b"".join(f.data for f in heard if f.data_kind == "D") == b"Hello from Aether Term\r"
        reply = "".join(f"Line {i:02d} from the station, long enough for several frames\r"
                        for i in range(10))
        agw.send_connected_data("N0BBS-10", "N0CALL", reply.encode())
        assert pump(qapp, until=lambda: "".join(got) == reply, timeout=90), \
            f"{len(''.join(got))} of {len(reply)}\n{air.logs()}"
        m.rf_disconnect()
        assert pump(qapp, until=lambda: any(f.data_kind == "d" for f in heard), timeout=60)
    finally:
        m.disconnect_from_modem()
        agw.disconnect()


def test_session_with_the_real_bbs_over_direwolf(qapp, air, home, monkeypatch, tmp_path):
    """The window in KISS TNC mode, the Aether BBS on the far side: HMAC
    login, ;TRANSPORT?, a command and Bye, all over 1200 baud AFSK."""
    import test_local_test_bbs as bbs_tests
    if bbs_tests.BBS_DIR is None:
        pytest.skip("no Aether BBS checkout")
    from config import Config
    from passwords import PasswordStore
    from gui.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "_check_omnirig", lambda self: None)
    import passwords
    monkeypatch.setattr(passwords, "HAS_KEYRING", False)

    bbs = bbs_tests.BBS(air.agw_port, 0, tmp_path, user="N0CALL", password="s3cret-pw")
    try:
        assert bbs.state() == "STATE IDLE WRONG=0", bbs.log[-3000:]
        cfg = Config()
        cfg.set("my_callsign", "N0CALL")
        cfg.set("vara_mode", "KISS TNC")
        cfg.set("kiss_link", "tcp")
        cfg.set("kiss_tcp_port", air.kiss_port)
        cfg.set("kiss_send_params", False)
        w = MainWindow(cfg, PasswordStore(cfg.app_data_dir))
        w.passwords.set_password("N0BBS-10", "s3cret-pw", operator="N0CALL")
        w.target_input.setCurrentText("N0BBS-10")

        def text():
            return w.terminal.display.toPlainText()
        try:
            t0 = time.time()
            w._on_connect()
            assert pump(qapp, until=lambda: "CONNECTED to N0BBS-10" in text(), timeout=90), \
                text()[-800:] + air.logs()
            assert pump(qapp, until=lambda: "Authentication successful" in text(), timeout=240), \
                text()[-1500:] + "\n" + bbs.log[-3000:] + air.logs()
            assert pump(qapp, until=lambda: text().endswith("\n> "), timeout=240), text()[-800:]
            assert w.transport_label.text().startswith("BBS link: SOUNDMODEM")
            assert ";TRANSPORT" not in text() and ";AUTH" not in text()
            w._send_text("B")
            assert pump(qapp, until=lambda: "*** DISCONNECTED ***" in text(), timeout=120), text()[-800:]
            assert pump(qapp, until=lambda: w.connect_btn.isEnabled(), timeout=20)
            assert "WRONG" not in bbs.log
            print(f"session over 1200 baud took {time.time() - t0:.0f} s")
        finally:
            w.close()
            pump(qapp, 0.3)
    finally:
        bbs.stop()
