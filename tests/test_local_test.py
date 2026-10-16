"""Local test mode: Aether Term plays VARA FM for a BBS on this PC."""

import socket
import time

import pytest

from conftest import pump
from fake_bbs import FakeBBS


def free_ports(n=2):
    socks = []
    for _ in range(n):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        socks.append(s)
    ports = [s.getsockname()[1] for s in socks]
    for s in socks:
        s.close()
    return ports


def wait(cond, timeout=5.0):
    """Until cond() — running Qt's event loop: the modem's signals come
    from its threads, queued."""
    from PyQt6.QtWidgets import QApplication
    return pump(QApplication.instance(), until=cond, timeout=timeout)


class Recorder:
    """The modem's signals, as lists (emitted from its threads)."""

    def __init__(self, modem):
        self.states, self.data, self.errors, self.status = [], [], [], []
        self.connected, self.disconnected = [], []
        modem.state_changed.connect(self.states.append)
        modem.data_received.connect(self.data.append)
        modem.error_signal.connect(self.errors.append)
        modem.bbs_status.connect(lambda a, t: self.status.append((a, t)))
        modem.rf_connected.connect(self.connected.append)
        modem.rf_disconnected.connect(lambda: self.disconnected.append(True))


@pytest.fixture
def lt(qapp):
    from vara.local_test import LocalTestModem
    m = LocalTestModem()
    m.rec = Recorder(m)
    m.listen(0, 0)
    bbs = []
    m.attach = lambda **kw: bbs.append(FakeBBS(m.cmd_port, m.data_port, **kw)) or bbs[-1]
    yield m
    for b in bbs:
        b.close()
    m.shutdown()
    # No reference cycle left: the cyclic GC could free the QObject on
    # whichever thread it happens to run in, and crash Qt
    m.attach = None


def _call(m, me="KK4ODA"):
    m.connect_to_modem()
    m.initialize_modem(me)
    m.rf_connect(me, "N0BBS-10")


@pytest.mark.parametrize("eol", ["\r", "\n", "\r\n"])
def test_bbs_init_sequence_gets_ok_every_time(lt, eol):
    bbs = lt.attach(eol=eol)
    replies = bbs.init(["MYCALL N0BBS-10", "COMPRESSION OFF", "BW2300",
                        "VERSION", "LISTEN ON"])
    assert replies == ["OK", "OK", "OK", "VERSION Aether Term local test", "OK"]
    assert lt.bbs_call == "N0BBS-10" and lt.bbs_listening
    assert wait(lambda: (True, f"Local test: N0BBS-10 attached on "
                               f"{lt.cmd_port}/{lt.data_port}") in lt.rec.status)


def test_other_commands_get_ok_never_wrong(lt):
    bbs = lt.attach()
    replies = bbs.init(["P2P SESSION", "CHAT ON", "PUBLIC ON", "FOO BAR",
                        "DISCONNECT", "ABORT", "LISTEN OFF", "CONNECT N0BBS-10 W1AW"])
    assert replies == ["OK"] * 8
    assert "WRONG" not in bbs.events


def test_listens_on_localhost_only(lt):
    for srv in lt._servers:
        assert srv.getsockname()[0] == "127.0.0.1"


def test_port_in_use_is_an_error(lt):
    from vara.local_test import LocalTestModem
    other = LocalTestModem()
    with pytest.raises(OSError):
        other.listen(lt.cmd_port, 0)
    assert not other.is_listening


def test_connect_before_the_bbs_attaches_is_refused(lt):
    lt.connect_to_modem()
    assert lt.rec.errors and "has not attached" in lt.rec.errors[0]
    assert lt.state.name == "DISCONNECTED"


def test_connect_reports_an_inbound_call_to_the_bbs(lt):
    bbs = lt.attach()
    bbs.init()
    _call(lt)
    assert bbs.wait(lambda: "CONNECTED KK4ODA N0BBS-10 25000" in bbs.events)
    assert lt.state.name == "CONNECTED"
    assert lt.rec.connected == ["KK4ODA N0BBS-10"]


def test_data_passes_both_ways(lt):
    bbs = lt.attach()
    bbs.init()
    _call(lt)
    lt.send_data(";TRANSPORT?\r\n")
    lt.send_data("H\r\n")
    assert bbs.wait(lambda: bytes(bbs.received) == b";TRANSPORT?\r\nH\r\n")
    welcome = "73 de N0BBS-10 — Grüße\r\n> ".encode()
    cut = welcome.index("ü".encode()) + 1         # inside a UTF-8 character
    bbs.send_data(welcome[:cut])
    time.sleep(0.1)
    bbs.send_data(welcome[cut:])
    assert wait(lambda: "".join(lt.rec.data) == welcome.decode())
    assert bbs.wait(lambda: bbs.events.count("BUFFER 0") == 2)


def test_bbs_disconnect_gets_disconnected(lt):
    bbs = lt.attach()
    bbs.init()
    for n, cmd in enumerate(("DISCONNECT", "ABORT"), 1):
        _call(lt)
        assert bbs.wait(lambda: sum(e.startswith("CONNECTED") for e in bbs.events) == n)
        mark = len(bbs.events)
        bbs.send_cmd(cmd)
        assert bbs.wait(lambda: bbs.events[mark:] == ["DISCONNECTED"]), bbs.events
        assert wait(lambda: lt.state.name == "MODEM_CONNECTED")
    assert lt.rec.disconnected == [True, True]
    assert lt.bbs_attached                         # still there for the next call


def test_terminal_disconnect_tells_the_bbs(lt):
    bbs = lt.attach()
    bbs.init()
    _call(lt)
    lt.rf_disconnect()
    assert bbs.wait(lambda: bbs.events[-1:] == ["DISCONNECTED"])
    assert lt.rec.disconnected == [True]
    lt.send_data("late\r\n")                       # not in a session: not sent
    time.sleep(0.2)
    assert b"late" not in bbs.received


def test_data_outside_a_session_is_dropped(lt):
    bbs = lt.attach()
    bbs.init()
    bbs.send_data(b"nobody is connected\r\n")
    time.sleep(0.3)
    assert lt.rec.data == []


@pytest.mark.parametrize("drop", ["cmd", "data"])
def test_dropped_socket_returns_to_waiting(lt, drop):
    bbs = lt.attach()
    bbs.init()
    _call(lt)
    assert wait(lambda: lt.state.name == "CONNECTED")
    bbs.drop(drop)
    assert wait(lambda: not lt.bbs_attached)
    assert wait(lambda: lt.rec.status[-1] == (
        False, f"Local test: BBS detached — waiting for it on {lt.cmd_port}/{lt.data_port}"))
    assert lt.rec.disconnected == [True]           # the session ended with it
    assert lt.state.name == "DISCONNECTED"
    bbs.close()
    # ...and the BBS can attach again
    again = lt.attach()
    assert again.init() == ["OK", "OK", "VERSION Aether Term local test", "OK"]
    assert wait(lambda: lt.bbs_attached)


def test_shutdown_frees_the_ports(lt):
    bbs = lt.attach()
    bbs.init()
    from vara.local_test import LocalTestModem
    ports = (lt.cmd_port, lt.data_port)
    lt.shutdown()
    again = LocalTestModem()
    again.listen(*ports)                             # the ports are free again
    again.shutdown()


# ── In the main window ──────────────────────────────────────────────

@pytest.fixture
def win(qapp, home, monkeypatch):
    from config import Config
    from passwords import PasswordStore
    from gui.main_window import MainWindow
    monkeypatch.setattr(MainWindow, "_check_omnirig", lambda self: None)
    import passwords
    monkeypatch.setattr(passwords, "HAS_KEYRING", False)
    launched = []
    monkeypatch.setattr(MainWindow, "_start_modem_exe",
                        lambda self, exe, label: launched.append(label))
    cmd_port, data_port = free_ports()
    cfg = Config()
    cfg.set("my_callsign", "KK4ODA")
    cfg.set("vara_mode", "Local test")
    cfg.set("local_test_cmd_port", cmd_port)
    cfg.set("local_test_data_port", data_port)
    w = MainWindow(cfg, PasswordStore(cfg.app_data_dir))
    w.launched = launched
    w.bbs = []
    w.attach = lambda **kw: w.bbs.append(FakeBBS(cmd_port, data_port, **kw)) or w.bbs[-1]
    yield w
    for b in w.bbs:
        b.close()
    w.attach = None                                 # (see lt)
    w.close()
    pump(qapp, 0.2)


def text(w):
    return w.terminal.display.toPlainText()


def test_window_shows_it_is_local_test(qapp, win):
    assert "LOCAL TEST" in win.windowTitle() and "not on the air" in win.windowTitle()
    assert win.mode_combo.currentText() == "Local test"
    assert pump(qapp, until=lambda: "waiting for the BBS" in win.modem_status_label.text())
    assert "nothing is transmitted" in text(win)
    bbs = win.attach()
    bbs.init()
    assert pump(qapp, until=lambda: win.modem_status_label.text() ==
                f"Local test: N0BBS-10 attached on {win.modem.cmd_port}/{win.modem.data_port}")
    pump(qapp, 0.6)
    assert win.launched == []                      # no modem program started


def test_window_session_with_the_bbs(qapp, win):
    bbs = win.attach(session=True)
    bbs.init()
    win.target_input.setCurrentText("")            # the attached BBS is called
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to N0BBS-10" in text(win), timeout=10)
    assert bbs.caller == "KK4ODA"
    # Same session code as on the air: ;TRANSPORT? goes out, its answer
    # is hidden and the prompt shows once
    assert pump(qapp, until=lambda: win.transport_label.text() == "BBS link: VARA_FM")
    pump(qapp, 0.3)
    assert ";TRANSPORT" not in text(win)
    assert text(win).endswith("Welcome to N0BBS-10, KK4ODA\n> ")
    win._send_text("H")
    assert pump(qapp, until=lambda: "Help: L R S B" in text(win))
    assert bytes(bbs.received) == b";TRANSPORT?\r\nH\r\n"
    # The BBS hangs up (B): DISCONNECT is answered and the session ends
    win._send_text("B")
    assert pump(qapp, until=lambda: "*** DISCONNECTED ***" in text(win))
    assert pump(qapp, until=lambda: win.connect_btn.isEnabled())
    assert "DISCONNECTED" in bbs.events
    assert "WRONG" not in bbs.events
    # Still attached: connect again
    win._on_connect()
    assert pump(qapp, until=lambda: text(win).count("CONNECTED to N0BBS-10") == 2)


def test_connect_as_another_callsign(qapp, win):
    win.config.set("local_test_callsign", "N0CALL")
    win._update_title()
    assert "as N0CALL" in win.windowTitle()
    bbs = win.attach(session=True)
    bbs.init()
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to N0BBS-10" in text(win))
    assert bbs.caller == "N0CALL"
    assert "CONNECTED N0CALL N0BBS-10 25000" in bbs.events


def test_disconnect_button_tells_the_bbs(qapp, win):
    bbs = win.attach(session=True)
    bbs.init()
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to N0BBS-10" in text(win))
    win._on_disconnect()
    assert bbs.wait(lambda: bbs.events[-1:] == ["DISCONNECTED"])
    assert pump(qapp, until=lambda: win.connect_btn.isEnabled())


def test_bbs_detaching_mid_session(qapp, win):
    bbs = win.attach(session=True)
    bbs.init()
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to N0BBS-10" in text(win))
    bbs.close()
    assert pump(qapp, until=lambda: "BBS detached" in text(win))
    assert pump(qapp, until=lambda: win.connect_btn.isEnabled())
    assert "*** DISCONNECTED ***" in text(win)
    again = win.attach()
    again.init()
    assert pump(qapp, until=lambda: "N0BBS-10 attached" in win.modem_status_label.text())


def test_connect_without_a_bbs_says_so(qapp, win):
    win.target_input.setCurrentText("N0BBS-10")
    win._on_connect()
    assert pump(qapp, until=lambda: "has not attached" in text(win))
    assert pump(qapp, until=lambda: win.connect_btn.isEnabled())


def test_leaving_local_test_stops_listening(qapp, win):
    from vara.modem import VARAModem
    ports = (win.modem.cmd_port, win.modem.data_port)
    win._switch_mode("VARA FM")
    assert isinstance(win.modem, VARAModem)
    assert "LOCAL TEST" not in win.windowTitle()
    for port in ports:
        s = socket.socket()
        s.bind(("127.0.0.1", port))
        s.close()
    win._switch_mode("Local test")
    assert win.modem.is_listening and (win.modem.cmd_port, win.modem.data_port) == ports


def test_settings_round_trip(qapp, win):
    from gui.settings_dialog import SettingsDialog
    win.config.set("local_test_callsign", "KK4ODA-9")
    dlg = SettingsDialog(win.config, win)
    assert dlg.local_test_radio.isChecked()
    assert dlg.local_test_call.text() == "KK4ODA-9"
    assert dlg.local_test_cmd_port.value() == win.config.get("local_test_cmd_port")
    dlg.local_test_cmd_port.setValue(8600)
    dlg.local_test_data_port.setValue(8600)        # the same port twice
    dlg._save_and_close()
    assert win.config.get("local_test_cmd_port") == 8600
    assert win.config.get("local_test_data_port") == 8601
    assert win.config.mode == "Local test"


def test_local_test_defaults():
    from config import DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["local_test_cmd_port"] == 8500
    assert DEFAULT_SETTINGS["local_test_data_port"] == 8501
