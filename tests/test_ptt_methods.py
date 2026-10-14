"""HF PTT through Hamlib rigctld and FLrig, and Connect when PTT is down.

VARA HF leaves keying to Aether Term. Each PTT method in Settings must key
a real (fake) rig server, and Connect must stop, without calling the modem,
when the chosen method can't reach the radio: the call would otherwise go
out with the radio never keyed.
"""

import pytest

from conftest import pump
from fake_rigs import FakeFLrig, FakeRigctld, closed_port


@pytest.fixture
def rigctld():
    fake = FakeRigctld().start()
    yield fake
    fake.stop()


@pytest.fixture
def flrig():
    fake = FakeFLrig().start()
    yield fake
    fake.stop()


def _cfg(home, **values):
    from config import Config
    cfg = Config()
    for k, v in values.items():
        cfg.set(k, v)
    return cfg


# ── PTTController.start_method ──────────────────────────────────────────

def test_hamlib_ptt_keys_rigctld(qapp, home, rigctld):
    from vara.ptt import PTTController
    cfg = _cfg(home, hamlib_rigctld_port=rigctld.port, hamlib_auto_launch=False)
    c = PTTController()
    assert c.start_method("Hamlib (rigctld)", cfg), c.last_error
    c.on_ptt_event(True)
    assert c.wait_idle(5) and rigctld.ptt == [1]
    c.on_ptt_event(False)
    assert c.wait_idle(5) and rigctld.ptt == [1, 0]
    c.on_ptt_event(True)
    c.stop()                                    # releases the radio on the way out
    assert not rigctld.keyed and not c.is_enabled


def test_flrig_ptt_keys_flrig(qapp, home, flrig):
    from vara.ptt import PTTController
    cfg = _cfg(home, flrig_port=flrig.port)
    c = PTTController()
    assert c.start_method("FLrig", cfg), c.last_error
    c.on_ptt_event(True)
    assert c.wait_idle(5) and flrig.ptt == [1]
    c.on_ptt_event(False)
    assert c.wait_idle(5) and flrig.ptt == [1, 0]
    c.on_ptt_event(True)
    c.stop()
    assert not flrig.keyed and not c.is_enabled


@pytest.mark.parametrize("method, key, expected", [
    ("Hamlib (rigctld)", "hamlib_rigctld_port", "rigctld"),
    ("FLrig", "flrig_port", "FLrig"),
])
def test_unreachable_method_reports_why(qapp, home, method, key, expected):
    from vara.ptt import PTTController
    cfg = _cfg(home, hamlib_auto_launch=False, **{key: closed_port()})
    c = PTTController()
    assert not c.start_method(method, cfg)
    assert expected in c.last_error and not c.is_enabled


def test_switching_methods_uses_the_new_backend(qapp, home, rigctld, flrig):
    from vara.ptt import PTTController
    cfg = _cfg(home, hamlib_rigctld_port=rigctld.port, hamlib_auto_launch=False,
               flrig_port=flrig.port)
    c = PTTController()
    assert c.start_method("Hamlib (rigctld)", cfg)
    assert c.start_method("FLrig", cfg)          # the Hamlib link is closed first
    c.on_ptt_event(True)
    assert c.wait_idle(5)
    assert flrig.ptt == [1] and 1 not in rigctld.ptt
    c.stop()


# ── Connect ─────────────────────────────────────────────────────────────

@pytest.fixture
def window(qapp, home, aetherd, monkeypatch):
    """A VARA HF main window on the fake modem; set ``hf_ptt_method`` per test."""
    from passwords import PasswordStore
    from gui import main_window
    from gui.main_window import MainWindow
    import passwords

    monkeypatch.setattr(MainWindow, "_check_omnirig", lambda self: None)
    monkeypatch.setattr(passwords, "HAS_KEYRING", False)
    warnings = []
    monkeypatch.setattr(main_window.QMessageBox, "warning",
                        lambda parent, title, msg, *a: warnings.append((title, msg)))
    cfg = _cfg(home, my_callsign="KK4ODA", vara_mode="VARA HF",
               hamlib_auto_launch=False,
               vara_hf_cmd_port=aetherd.cmd_port,
               vara_hf_data_port=aetherd.data_port)
    w = MainWindow(cfg, PasswordStore(cfg.app_data_dir))
    w.target_input.setCurrentText("W1AW-5")
    w.fake, w.warnings = aetherd, warnings
    yield w
    w.close()
    pump(qapp, 0.2)


def text(w):
    return w.terminal.display.toPlainText()


def test_vara_hf_session_with_flrig_ptt(qapp, window, flrig):
    from vara.connection import ConnectionState
    window.config.set("hf_ptt_method", "FLrig")
    window.config.set("flrig_port", flrig.port)
    window._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(window),
                timeout=15), text(window)[-600:]
    assert "FLrig PTT connected" in text(window)
    # The fake modem sent PTT ON / PTT OFF while connecting
    assert pump(qapp, until=lambda: flrig.ptt[:2] == [1, 0])
    window.fake.push_event("PTT ON")
    assert pump(qapp, until=lambda: flrig.keyed)
    window._on_disconnect()
    assert pump(qapp, until=lambda: window.modem.state == ConnectionState.DISCONNECTED)
    assert pump(qapp, until=lambda: not flrig.keyed)
    assert not window.ptt.is_enabled


def test_connect_stops_when_ptt_is_unavailable(qapp, window):
    window.config.set("hf_ptt_method", "Hamlib (rigctld)")
    window.config.set("hamlib_rigctld_port", closed_port())
    window._on_connect()
    pump(qapp, 0.5)
    assert window.warnings and window.warnings[0][0] == "PTT Unavailable"
    assert "Cannot connect to rigctld" in window.warnings[0][1]
    assert "Connect stopped" in text(window)
    assert window.fake.commands == []           # the modem was never called
    assert not window._connect_in_progress
    assert window.connect_btn.isEnabled()


def test_vox_connects_without_starting_ptt(qapp, window, monkeypatch):
    from vara.ptt import PTTController

    def no_start(*a, **k):
        raise AssertionError("PTT started in VOX mode")
    monkeypatch.setattr(PTTController, "start_method", no_start)
    window.config.set("hf_ptt_method", "None (VOX)")
    window._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(window),
                timeout=15), text(window)[-600:]
    assert not window.warnings


def test_vara_fm_never_starts_ptt(qapp, window, monkeypatch):
    """VARA FM keys the radio itself, whatever the HF PTT setting says."""
    from vara.ptt import PTTController

    def no_start(*a, **k):
        raise AssertionError("PTT started for VARA FM")
    monkeypatch.setattr(PTTController, "start_method", no_start)
    window.config.set("vara_mode", "VARA FM")
    window.config.set("hf_ptt_method", "FLrig")
    window.config.set("flrig_port", closed_port())
    assert window._start_host_ptt()
    assert not window.warnings


# ── Settings ────────────────────────────────────────────────────────────

def test_settings_offer_every_ptt_method(qapp, window):
    from gui.settings_dialog import SettingsDialog
    dlg = SettingsDialog(window.config, window)
    items = [dlg.hf_ptt_method.itemText(i) for i in range(dlg.hf_ptt_method.count())]
    assert items == ["None (VOX)", "OmniRig", "Hamlib (rigctld)", "FLrig"]

    def shown(widget):
        return dlg.ptt_form.isRowVisible(widget)

    dlg.hf_ptt_method.setCurrentText("FLrig")
    assert shown(dlg.flrig_port) and not shown(dlg.hamlib_group)
    assert not shown(dlg.omnirig_rig_spin)
    dlg.hf_ptt_method.setCurrentText("Hamlib (rigctld)")
    assert shown(dlg.hamlib_group) and not shown(dlg.flrig_port)
    dlg.hf_ptt_method.setCurrentText("OmniRig")
    assert shown(dlg.omnirig_rig_spin) and not shown(dlg.hamlib_group)

    dlg.hf_ptt_method.setCurrentText("FLrig")
    dlg.flrig_port.setValue(12346)
    dlg.hamlib_group.rigctld_port.setValue(4533)
    dlg._save_and_close()
    assert window.config.get("hf_ptt_method") == "FLrig"
    assert window.config.get("flrig_port") == 12346
    assert window.config.get("hamlib_rigctld_port") == 4533

    again = SettingsDialog(window.config, window)
    assert again.hf_ptt_method.currentText() == "FLrig"
    assert again.flrig_port.value() == 12346
    assert again.ptt_form.isRowVisible(again.flrig_port)


# ── Slow and hung rigs ──────────────────────────────────────────────────

def test_a_rig_that_does_not_answer_in_time_is_not_started(qapp):
    """start() used to report success when its wait ran out while the
    I/O thread was still trying, and the call went out unkeyed."""
    import time
    from vara.rig_client import RigClient

    class SlowRig(RigClient):
        NAME = "Slow"
        START_TIMEOUT = 0.3

        def _open(self):
            time.sleep(1.0)

        def _key(self, on):
            return True

        def _close(self):
            pass

    rig = SlowRig()
    with pytest.raises(RuntimeError, match="did not answer"):
        rig.start()
    assert not rig.is_started and not rig.set_ptt(True)


def test_silent_rigctld_fails_to_start(qapp, home):
    from vara.ptt import PTTController
    fake = FakeRigctld(silent=True).start()
    try:
        cfg = _cfg(home, hamlib_rigctld_port=fake.port, hamlib_auto_launch=False)
        c = PTTController()
        assert not c.start_method("Hamlib (rigctld)", cfg)
        assert "did not respond" in c.last_error
    finally:
        fake.stop()


def test_late_rigctld_reply_is_not_read_as_the_next_answer(qapp, home, rigctld):
    """A reply that comes after the timeout must not be taken as the answer
    to the next command (a late "RPRT 0" for PTT ON passing as PTT OFF)."""
    from vara.hamlib import HamlibClient
    client = HamlibClient(port=rigctld.port)
    client.start()
    try:
        rigctld.ptt_delay = 4.5                   # past the 4 s socket timeout
        assert not client.set_ptt(True)
        assert client.set_ptt(False)              # on a fresh connection
        assert rigctld.ptt[-1] == 0
    finally:
        client.stop()
