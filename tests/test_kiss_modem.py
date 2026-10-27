"""The KISS TNC mode: KissModem over a fake TNC, and the main window."""

import os
import sys
import threading

import pytest

from ax25 import kiss
from ax25.frame import FrameType
from conftest import pump
from fake_tnc import FakeKissTnc, FAST


def wait(cond, timeout=10.0):
    from PyQt6.QtWidgets import QApplication
    return pump(QApplication.instance(), until=cond, timeout=timeout)


class Rec:
    def __init__(self, m):
        self.states, self.data, self.errors, self.events, self.tnc = [], [], [], [], []
        self.connected, self.disconnected = [], []
        m.state_changed.connect(lambda s: self.states.append(s.name))
        m.data_received.connect(self.data.append)
        m.error_signal.connect(self.errors.append)
        m.command_event.connect(self.events.append)
        m.tnc_status.connect(self.tnc.append)
        m.rf_connected.connect(self.connected.append)
        m.rf_disconnected.connect(lambda: self.disconnected.append(True))


@pytest.fixture
def tnc():
    t = FakeKissTnc()
    yield t
    t.stop()


def _modem(port, **kw):
    from tnc.transports import TcpTransport
    from vara.kiss_modem import KissModem
    m = KissModem(TcpTransport("127.0.0.1", port), FAST, **kw)
    m.rec = Rec(m)
    return m


def _open_and_call(m, me="N0CALL", target="KK4ODA-7", via=()):
    m.connect_to_modem()
    assert wait(lambda: m.state.name == "MODEM_CONNECTED"), m.rec.errors
    m.initialize_modem(me)
    m.rf_connect(me, target, *via)


def test_session_over_a_kiss_tnc(qapp, tnc):
    m = _modem(tnc.port)
    try:
        _open_and_call(m)
        assert wait(lambda: m.state.name == "CONNECTED"), m.rec.errors
        assert m.rec.connected == ["N0CALL KK4ODA-7"]
        assert wait(lambda: "".join(m.rec.data) == "Welcome to KK4ODA-7, N0CALL\r\n> ")
        m.send_data("H\r\n")
        assert wait(lambda: "Help: L R S B" in "".join(m.rec.data))
        m.send_data("B\r\n")                       # the BBS hangs up
        assert wait(lambda: m.rec.disconnected == [True])
        assert m.state.name == "MODEM_CONNECTED"
        assert bytes(tnc.received) == b"H\r\nB\r\n"
    finally:
        m.disconnect_from_modem()


def test_tnc_parameters_and_init_go_out_first(qapp, tnc):
    setup = b"KISS ON\r" + kiss.tnc_parameters(250, 63, 100)
    m = _modem(tnc.port, tnc_setup=setup)
    try:
        m.connect_to_modem()
        assert wait(lambda: bytes(tnc.raw).startswith(setup))
    finally:
        m.disconnect_from_modem()


def test_long_text_is_split_into_packets(qapp, tnc):
    m = _modem(tnc.port)
    try:
        _open_and_call(m)
        assert wait(lambda: m.state.name == "CONNECTED")
        text = "".join(f"Line {i:03d} of a long message for the BBS\r\n" for i in range(40))
        m.send_data(text)
        assert wait(lambda: bytes(tnc.received) == text.encode(), timeout=20)
        sizes = [len(f.info) for f in tnc.frames if f.type is FrameType.I]
        assert max(sizes) <= FAST.paclen and len(sizes) >= len(text) // FAST.paclen
    finally:
        m.disconnect_from_modem()


def test_we_hang_up(qapp, tnc):
    m = _modem(tnc.port)
    try:
        _open_and_call(m)
        assert wait(lambda: m.state.name == "CONNECTED")
        m.rf_disconnect()
        assert wait(lambda: m.rec.disconnected == [True])
        assert any(f.type is FrameType.DISC for f in tnc.frames)
        assert wait(lambda: not tnc.bbs.is_connected)
    finally:
        m.disconnect_from_modem()


def test_digipeater_path_goes_in_the_frames(qapp, tnc):
    m = _modem(tnc.port)
    try:
        _open_and_call(m, via=("WD5EMA-4", ""))
        assert wait(lambda: m.state.name == "CONNECTED")
        assert m.connected_via == ["WD5EMA-4"]
        assert [str(d) for d in tnc.frames[0].digis] == ["WD5EMA-4"]
    finally:
        m.disconnect_from_modem()


def test_no_answer_is_reported(qapp):
    t = FakeKissTnc(answer=False)
    t.drop = lambda f: True                       # nobody on the air
    m = _modem(t.port)
    try:
        _open_and_call(m, target="NOBODY")
        assert wait(lambda: any("no answer from NOBODY" in e for e in m.rec.errors), timeout=15)
        assert m.state.name == "MODEM_CONNECTED"
    finally:
        m.disconnect_from_modem()
        t.stop()


def test_tnc_lost_mid_session(qapp, tnc):
    m = _modem(tnc.port)
    try:
        _open_and_call(m)
        assert wait(lambda: m.state.name == "CONNECTED")
        tnc.kill_link()
        assert wait(lambda: m.state.name == "DISCONNECTED")
        assert m.rec.disconnected == [True]
        assert any("Lost the TNC" in e for e in m.rec.errors)
        assert m.rec.tnc[-1] == "TNC: not connected"
    finally:
        m.disconnect_from_modem()


def test_tnc_not_there(qapp):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    m = _modem(port)
    m.connect_to_modem()
    assert wait(lambda: m.rec.errors)
    assert "cannot connect to the TNC" in m.rec.errors[0]
    assert m.state.name == "DISCONNECTED"


def test_bad_callsign_is_refused(qapp, tnc):
    m = _modem(tnc.port)
    try:
        m.connect_to_modem()
        assert wait(lambda: m.state.name == "MODEM_CONNECTED")
        m.initialize_modem("N0CALL")
        m.rf_connect("N0CALL", "NOT A CALL")
        assert wait(lambda: m.rec.errors)
        assert "not an AX.25 callsign" in m.rec.errors[0]
    finally:
        m.disconnect_from_modem()


# ── Serial ports (a pty stands in for a COM port) ──────────────────

@pytest.mark.skipif(sys.platform == "win32", reason="needs a pty")
def test_serial_transport_over_a_pty():
    from tnc.transports import SerialTransport
    master, slave = os.openpty()
    got, lost = bytearray(), []
    t = SerialTransport(os.ttyname(slave), 9600)
    t.open(got.extend, lost.append)
    try:
        t.write(b"\xc0\x00hello\xc0")
        assert os.read(master, 100) == b"\xc0\x00hello\xc0"
        os.write(master, b"\xc0\x00back\xc0")
        ev = threading.Event()
        for _ in range(50):
            if bytes(got) == b"\xc0\x00back\xc0":
                break
            ev.wait(0.05)
        assert bytes(got) == b"\xc0\x00back\xc0"
    finally:
        t.close()
        os.close(master)
        os.close(slave)
    assert lost == []                               # a close we asked for is not a loss


def test_serial_port_must_be_chosen():
    from tnc.transports import SerialTransport, TransportError
    with pytest.raises(TransportError, match="no serial port chosen"):
        SerialTransport("").open(lambda b: None, lambda w: None)


def test_make_transport_follows_the_settings():
    from tnc.transports import SerialTransport, TcpTransport, make_transport
    assert isinstance(make_transport({"kiss_link": "tcp", "kiss_tcp_port": 8001}), TcpTransport)
    t = make_transport({"kiss_link": "serial", "kiss_serial_port": "COM7"})
    assert isinstance(t, SerialTransport) and t.port == "COM7"
    from tnc.ble import BleTransport, KISS_SERVICE_UUID
    b = make_transport({"kiss_link": "ble", "kiss_ble_address": "AA:BB"})
    assert isinstance(b, BleTransport) and b.service_uuid == KISS_SERVICE_UUID


def test_modem_from_settings(qapp):
    from vara.kiss_modem import KissModem
    cfg = {"kiss_link": "tcp", "kiss_tcp_port": 9999, "kiss_init": r"KISS ON\rRESTART",
           "kiss_txdelay": 400, "kiss_port": 1, "ax25_paclen": 200, "ax25_maxframe": 7}
    m = KissModem.from_config(cfg)
    assert m.transport.describe() == "127.0.0.1:9999"
    assert m.tnc_setup.startswith(b"KISS ON\rRESTART\r")
    assert kiss.encode_param(kiss.CMD_TXDELAY, 40, 1) in m.tnc_setup
    assert (m.params.paclen, m.params.maxframe, m.kiss_port) == (200, 7, 1)
    m2 = KissModem.from_config({"kiss_link": "tcp", "kiss_send_params": False})
    assert m2.tnc_setup == b""


# ── In the main window ──────────────────────────────────────────────

@pytest.fixture
def win(qapp, home, monkeypatch, tnc):
    from config import Config
    from passwords import PasswordStore
    from gui.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "_check_omnirig", lambda self: None)
    import passwords
    monkeypatch.setattr(passwords, "HAS_KEYRING", False)
    launched = []
    monkeypatch.setattr(MainWindow, "_start_modem_exe",
                        lambda self, exe, label: launched.append(label))
    import vara.kiss_modem as km
    monkeypatch.setattr(km, "link_params", lambda config: FAST)
    cfg = Config()
    cfg.set("my_callsign", "N0CALL")
    cfg.set("vara_mode", "KISS TNC")
    cfg.set("kiss_link", "tcp")
    cfg.set("kiss_tcp_port", tnc.port)
    w = MainWindow(cfg, PasswordStore(cfg.app_data_dir))
    w.target_input.setCurrentText("KK4ODA-7")
    w.launched = launched
    yield w
    w.close()
    pump(qapp, 0.2)


def text(w):
    return w.terminal.display.toPlainText()


def test_window_session_over_a_kiss_tnc(qapp, win, tnc):
    assert win.mode_combo.currentText() == "KISS TNC"
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to KK4ODA-7" in text(win), timeout=15), text(win)[-600:]
    assert win.modem_status_label.text() == f"TNC: 127.0.0.1:{tnc.port}"
    # Same session code as every mode: ;TRANSPORT? goes out, its answer is hidden
    assert pump(qapp, until=lambda: win.transport_label.text() == "BBS link: KISS")
    pump(qapp, 0.3)
    assert ";TRANSPORT" not in text(win)
    assert text(win).endswith("Welcome to KK4ODA-7, N0CALL\n> ")
    win._send_text("H")
    assert pump(qapp, until=lambda: "Help: L R S B" in text(win))
    win._send_text("B")
    assert pump(qapp, until=lambda: "*** DISCONNECTED ***" in text(win), timeout=10)
    assert pump(qapp, until=lambda: win.connect_btn.isEnabled())
    assert win.modem_status_label.text() == "TNC: not connected"
    assert win.launched == []                      # no modem program for a KISS TNC
    assert tnc.bbs_handler.callers == ["N0CALL"]


def test_window_disconnect_button(qapp, win, tnc):
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to KK4ODA-7" in text(win), timeout=15)
    win._on_disconnect()
    assert pump(qapp, until=lambda: win.connect_btn.isEnabled(), timeout=10)
    assert any(f.type is FrameType.DISC for f in tnc.frames)


def test_window_digipeaters_allowed_for_kiss(qapp, win, tnc):
    win._set_via(win.via1_input, "WD5EMA-4")
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to KK4ODA-7 via WD5EMA-4" in text(win), timeout=15)


def test_kiss_settings_round_trip(qapp, win):
    from gui.settings_dialog import SettingsDialog
    win.config.set("kiss_link", "ble")
    win.config.set("kiss_ble_address", "AA:BB:CC:DD:EE:FF")
    win.config.set("kiss_ble_name", "VR-N76")
    dlg = SettingsDialog(win.config, win)
    g = dlg.kiss_group
    assert dlg.kiss_radio.isChecked()
    assert g.link.currentData() == "ble"
    assert g.ble_device.currentText() == "VR-N76 — AA:BB:CC:DD:EE:FF"
    g.link.setCurrentIndex(g.link.findData("serial"))
    g.serial_port.setEditText("COM7")
    g.paclen.setValue(200)
    g.init.setText(r"KISS ON\rRESTART")
    dlg._save_and_close()
    c = win.config
    assert (c.get("kiss_link"), c.get("kiss_serial_port"), c.get("ax25_paclen")) == ("serial", "COM7", 200)
    assert c.get("kiss_ble_address") == "AA:BB:CC:DD:EE:FF"     # kept for later
    assert c.get("kiss_init") == r"KISS ON\rRESTART"
    assert c.mode == "KISS TNC"
