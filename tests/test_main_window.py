"""The main window in Aether HF mode, end to end against the fake daemon."""

import time

import pytest

from conftest import pump


@pytest.fixture
def win(qapp, home, aetherd, monkeypatch):
    from config import Config
    from passwords import PasswordStore
    from gui.main_window import MainWindow

    # Don't talk to a real OmniRig (COM) on the machine running the tests
    monkeypatch.setattr(MainWindow, "_check_omnirig", lambda self: None)
    # ...nor the OS keyring, where the real master key lives
    import passwords
    monkeypatch.setattr(passwords, "HAS_KEYRING", False)

    cfg = Config()
    cfg.set("my_callsign", "KK4ODA")
    cfg.set("vara_mode", "Aether HF")
    cfg.set("aether_cmd_port", aetherd.cmd_port)
    cfg.set("aether_data_port", aetherd.data_port)
    cfg.set("aether_control_port", aetherd.control_port)
    w = MainWindow(cfg, PasswordStore(cfg.app_data_dir))
    w.target_input.setCurrentText("W1AW-5")
    w.fake = aetherd
    yield w
    w.close()
    pump(qapp, 0.2)


def text(w):
    return w.terminal.display.toPlainText()


def test_status_bar_shows_aether(qapp, win):
    assert win.mode_combo.currentText() == "Aether HF"
    assert pump(qapp, until=lambda: "2300 Hz" in win.aether_label.text())
    assert "0.2.0-beta.102" in win.aether_label.text()


@pytest.mark.parametrize("change,expected", [
    ({"host_enabled": False}, "host interface is off"),
    ({"policy": "unset"}, "No rules are chosen"),
    ({"ptt_fault": "COM3 is in use"}, "Keying: COM3 is in use"),
])
def test_preflight_stops_the_call(qapp, win, change, expected):
    win.fake.state.update(change)
    win._on_connect()
    assert pump(qapp, until=lambda: "Not connecting" in text(win))
    assert expected in text(win)
    assert win.fake.commands == []
    assert win.connect_btn.isEnabled()


def test_preflight_does_not_freeze_the_window(qapp, win):
    win.fake.state["status_delay"] = 1.5
    t0 = time.time()
    win._on_connect()
    assert time.time() - t0 < 0.3
    assert not win.connect_btn.isEnabled()      # no double connect meanwhile
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(win), timeout=15)


def test_full_session(qapp, win):
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(win), timeout=15)
    cmds = win.fake.commands
    assert "MYCALL KK4ODA" in cmds and "BW2300" in cmds and "VERSION" in cmds
    assert "CONNECT KK4ODA W1AW-5" in cmds
    assert pump(qapp, until=lambda: "Welcome to the test BBS" in text(win))
    assert pump(qapp, until=lambda: win.speed_label.text() == "Speed: 1450 bps (mode 9)")
    assert win.bw_label.text() == "BW: 2300 Hz"
    assert "Aether HF 0.2.0-beta.102" in win.modem_status_label.text()
    assert "WRONG" not in text(win)

    win._send_text("H")
    assert pump(qapp, until=lambda: "Help: L R S B" in text(win))

    win._on_disconnect()
    assert pump(qapp, until=lambda: "DISCONNECTED" in text(win))


def test_commands_end_in_bare_cr(qapp, win):
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(win), timeout=15)
    raw = bytes(win.fake.raw_commands)
    assert b"CONNECT KK4ODA W1AW-5\r" in raw
    assert b"\n" not in raw


def test_vara_fm_digipeater_session(qapp, win):
    """VARA FM sends the VIA path and shows it once the link is up."""
    cfg = win.config
    win.mode_combo.setCurrentIndex(0)
    pump(qapp, 0.1)
    assert cfg.mode == "VARA FM"
    cfg.set("vara_fm_cmd_port", win.fake.cmd_port)
    cfg.set("vara_fm_data_port", win.fake.data_port)
    assert cfg.cmd_port == win.fake.cmd_port
    win.via1_input.setText("n4xyz-7")
    win.via2_input.setText("K4ABC-1")
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5 via" in text(win), timeout=15)
    assert "CONNECT KK4ODA W1AW-5 VIA N4XYZ-7 K4ABC-1" in win.fake.commands
    assert "*** CONNECTED to W1AW-5 via N4XYZ-7, K4ABC-1 ***" in text(win)
    assert win.bw_label.text() == "BW: WIDE"


@pytest.mark.parametrize("via1,expected", [
    ("N4XYZ-7", "only supported in VARA FM"),        # Aether HF can't digipeat
    ("N4XYZ-99", "not a valid digipeater callsign"),
])
def test_bad_digipeater_path_stops_the_call(qapp, win, monkeypatch, via1, expected):
    from gui import main_window
    shown = []
    monkeypatch.setattr(main_window.QMessageBox, "warning",
                        lambda *a, **k: shown.append(a[2]))
    win.via1_input.setText(via1)
    win._on_connect()
    pump(qapp, 0.5)
    assert shown and expected in shown[0]
    assert win.fake.commands == []


@pytest.mark.parametrize("chunks", [
    ["KE4QCM-7} Welcome to the node\rCMD:\r"],              # BPQ: bare CR
    ["KE4QCM-7} Welcome to the node\r", "\nCMD:\r\n"],       # CR LF split across chunks
    ["KE4QCM-7} Welcome to the node\nCMD:\n"],               # bare LF
    ["KE4QCM-7} Wel", "come to the node\r\n", "CMD:\r"],
])
def test_incoming_lines_end_in_cr_lf_or_both(qapp, win, chunks):
    for c in chunks:
        win._on_data_received(c)
    shown = text(win)
    assert "KE4QCM-7} Welcome to the node" in shown
    assert "CMD:" in shown
    # A CR LF never turns into an extra blank line
    assert "node\n\n" not in shown
    assert win._data_buffer == ""


def test_wrong_modem_on_port_is_reported(qapp, win):
    win.fake.state["version_reply"] = "VERSION VARA HF 4.8.7"
    win._on_connect()
    assert pump(qapp, until=lambda: "not Aether HF" in text(win), timeout=15)


def test_refused_call_is_explained(qapp, win):
    win.fake.state["answer_connect"] = False
    win._on_connect()
    assert pump(qapp, until=lambda: "No session with W1AW-5" in text(win), timeout=15)


def test_failed_call_closes_the_modem_link(qapp, win):
    """A refused call ends on its own — no Disconnect click needed."""
    from vara.connection import ConnectionState
    win.fake.state["answer_connect"] = False
    win._on_connect()
    assert pump(qapp, until=lambda: "Connection to W1AW-5 failed" in text(win),
                timeout=15)
    assert pump(qapp, until=lambda: win.modem.state == ConnectionState.DISCONNECTED)
    pump(qapp, 0.2)
    assert win.connect_btn.isEnabled() and not win.disconnect_btn.isEnabled()


def test_rejected_connect_command_closes_the_modem_link(qapp, win):
    from vara.connection import ConnectionState
    win.fake.state["reject_connect"] = True
    win._on_connect()
    assert pump(qapp, until=lambda: "Command rejected: WRONG" in text(win), timeout=15)
    assert pump(qapp, until=lambda: win.modem.state == ConnectionState.DISCONNECTED)
    pump(qapp, 0.2)
    assert win.connect_btn.isEnabled()


def test_session_end_still_closes_the_modem_link(qapp, win):
    from vara.connection import ConnectionState
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(win), timeout=15)
    win._on_disconnect()
    assert pump(qapp, until=lambda: win.modem.state == ConnectionState.DISCONNECTED)
    assert "failed" not in text(win)


@pytest.mark.parametrize("manual,skipped,connected,prompted", [
    (False, "", False, True),           # startup: ask
    (False, "v1.2.0", False, False),    # startup: user skipped this version
    (True, "v1.2.0", False, True),      # Help → Check for Updates: always ask
    (False, "", True, False),           # never interrupt a session
])
def test_startup_update_prompt(qapp, win, monkeypatch, manual, skipped, connected, prompted):
    from updater import UpdateCheckResult
    from vara.connection import ConnectionState
    shown = []
    monkeypatch.setattr(win, "_show_update_dialog", lambda: shown.append(1))
    win.config.set("skipped_update_version", skipped)
    if connected:
        monkeypatch.setattr(type(win.modem), "state",
                            property(lambda self: ConnectionState.CONNECTED))
    r = UpdateCheckResult(update_available=True, mode="release", release_tag="v1.2.0")
    win._manual_update_check = manual
    win._on_update_available(r)
    win._on_update_check_finished(r)
    assert bool(shown) == prompted
    assert win._update_label.text() == "UPDATE v1.2.0"


def test_mode_switching(qapp, win):
    cfg = win.config
    for idx, mode in [(1, "VARA HF"), (3, "AGWPE"), (0, "VARA FM"), (2, "Aether HF")]:
        win.mode_combo.setCurrentIndex(idx)
        pump(qapp, 0.1)
        assert cfg.mode == mode
        assert win.aether_label.isVisibleTo(win) == (mode == "Aether HF")


def test_settings_dialog_round_trip(qapp, win):
    from gui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(win.config, win)
    assert dlg.aether_radio.isChecked()
    dlg._test_aether()
    assert pump(qapp, until=lambda: "Aether HF 0.2.0" in dlg.aether_test_result.text())
    dlg.aether_bw_combo.setCurrentText("500")
    dlg._save_and_close()
    assert win.config.get("aether_bandwidth") == 500
    assert win.config.mode == "Aether HF"


def test_profiles_keep_every_mode(qapp, win):
    from gui.profile_dialog import ProfileDialog
    pd = ProfileDialog(win.config, win)
    for mode in ("VARA FM", "VARA HF", "Aether HF", "AGWPE"):
        assert pd.mode_combo.findData(mode) >= 0
