"""VARA HF end to end against the fake modem, and the PTT controller.

VARA HF leaves keying to the host program: Aether Term must key the radio
on PTT ON, unkey it on PTT OFF in the same order, and never leave it keyed
when a call ends, fails, or the modem disappears.
"""

import threading
import time

import pytest

from conftest import pump


class FakeRig:
    """Stands in for OmniRig: records PTT commands, optionally slow to key."""

    def __init__(self, key_delay: float = 0.0):
        self.calls: list[bool] = []
        self.key_delay = key_delay
        self.is_started = True
        self.stopped = False

    def set_ptt(self, on: bool) -> bool:
        if on and self.key_delay:
            time.sleep(self.key_delay)
        self.calls.append(on)
        return True

    def stop(self):
        self.stopped = True

    @property
    def keyed(self) -> bool:
        return bool(self.calls) and self.calls[-1]


def _controller(rig):
    from vara.ptt import PTTController
    c = PTTController()
    c._omnirig = rig
    c._backend = "omnirig"
    c._enabled = True
    return c


# ── PTT controller ──────────────────────────────────────────────────────

def test_keying_runs_in_the_order_the_modem_asked(qapp):
    """A slow PTT ON must not be overtaken by the PTT OFF behind it."""
    rig = FakeRig(key_delay=0.3)
    c = _controller(rig)
    c.on_ptt_event(True)
    c.on_ptt_event(False)
    assert c.wait_idle(3)
    assert rig.calls == [True, False]
    assert not rig.keyed


def test_rapid_keying_ends_unkeyed(qapp):
    rig = FakeRig(key_delay=0.01)
    c = _controller(rig)
    for _ in range(20):
        c.on_ptt_event(True)
        c.on_ptt_event(False)
    assert c.wait_idle(5)
    assert rig.calls == [True, False] * 20


def test_watchdog_unkeys_after_a_lost_ptt_off(qapp, monkeypatch):
    import vara.ptt as ptt
    monkeypatch.setattr(ptt, "WATCHDOG_TIMEOUT", 0.2)
    rig = FakeRig()
    c = _controller(rig)
    errors = []
    c.ptt_error.connect(errors.append)
    c.on_ptt_event(True)
    assert pump(qapp, until=lambda: rig.calls == [True, False], timeout=3)
    assert not c.ptt_on
    assert any("watchdog" in e for e in errors)


def test_stop_unkeys_and_closes_the_rig(qapp):
    rig = FakeRig()
    c = _controller(rig)
    c.on_ptt_event(True)
    c.stop()
    assert rig.calls == [True, False] and rig.stopped
    assert not c.is_enabled


# ── VARA HF session ─────────────────────────────────────────────────────

@pytest.fixture
def hf(qapp, home, aetherd, monkeypatch):
    """Main window in VARA HF mode, OmniRig PTT replaced by a FakeRig."""
    from config import Config
    from passwords import PasswordStore
    from gui.main_window import MainWindow
    from vara.ptt import PTTController
    import passwords

    monkeypatch.setattr(MainWindow, "_check_omnirig", lambda self: None)
    monkeypatch.setattr(passwords, "HAS_KEYRING", False)
    rig = FakeRig()

    def fake_start(self, rig_number=1):
        self._omnirig = rig
        self._backend = "omnirig"
        self._enabled = True
        return True
    monkeypatch.setattr(PTTController, "start", fake_start)

    cfg = Config()
    cfg.set("my_callsign", "KK4ODA")
    cfg.set("vara_mode", "VARA HF")
    cfg.set("hf_ptt_method", "OmniRig")
    cfg.set("hf_bandwidth", 500)
    cfg.set("vara_hf_cmd_port", aetherd.cmd_port)
    cfg.set("vara_hf_data_port", aetherd.data_port)
    w = MainWindow(cfg, PasswordStore(cfg.app_data_dir))
    w.target_input.setCurrentText("W1AW-5")
    w.fake, w.rig = aetherd, rig
    yield w
    w.close()
    pump(qapp, 0.2)


def text(w):
    return w.terminal.display.toPlainText()


def _connect(qapp, w):
    w._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(w), timeout=15), \
        text(w)[-600:]


def test_vara_hf_session(qapp, hf):
    _connect(qapp, hf)
    cmds = hf.fake.commands
    assert "MYCALL KK4ODA" in cmds and "BW500" in cmds
    assert "P2P SESSION" in cmds                       # BBS calls are P2P
    assert cmds.index("P2P SESSION") < cmds.index("CONNECT KK4ODA W1AW-5")
    assert "VERSION" not in cmds                       # Aether HF only
    # The modem's PTT ON / PTT OFF keyed and unkeyed the radio, in order
    assert pump(qapp, until=lambda: hf.rig.calls[:2] == [True, False])
    assert pump(qapp, until=lambda: hf.bw_label.text() == "BW: 2300 Hz")
    hf.fake.push_event("PTT ON")
    assert pump(qapp, until=lambda: hf.rig.keyed)
    assert "TX" in hf.ptt_label.text()
    hf._on_disconnect()
    from vara.connection import ConnectionState
    assert pump(qapp, until=lambda: hf.modem.state == ConnectionState.DISCONNECTED)
    assert not hf.rig.keyed and hf.rig.stopped
    assert not hf.ptt.is_enabled


def test_winlink_gateway_session_setting(qapp, hf):
    hf.config.set("hf_session", "WINLINK")
    _connect(qapp, hf)
    assert "WINLINK SESSION" in hf.fake.commands
    assert "P2P SESSION" not in hf.fake.commands


def test_modem_crash_while_keyed_releases_ptt(qapp, hf):
    """VARA dies mid-transmission: unkey now, not after the 90 s watchdog."""
    _connect(qapp, hf)
    hf.fake.push_event("PTT ON")
    assert pump(qapp, until=lambda: hf.rig.keyed)
    hf.fake.drop_link()
    assert pump(qapp, until=lambda: not hf.rig.keyed and hf.rig.stopped, timeout=5), \
        hf.rig.calls
    assert not hf.ptt.is_enabled


def test_refused_hf_call_releases_the_rig(qapp, hf):
    hf.fake.state["answer_connect"] = False
    hf._on_connect()
    assert pump(qapp, until=lambda: "failed" in text(hf), timeout=15)
    assert pump(qapp, until=lambda: hf.rig.stopped, timeout=5)
    assert not hf.rig.keyed and not hf.ptt.is_enabled


def test_rejected_hf_connect_releases_the_rig(qapp, hf):
    hf.fake.state["reject_connect"] = True
    hf._on_connect()
    assert pump(qapp, until=lambda: "Command rejected: WRONG" in text(hf), timeout=15)
    assert pump(qapp, until=lambda: hf.rig.stopped, timeout=5)
    assert not hf.ptt.is_enabled


def test_fm_and_aether_send_no_session_command(qapp, home):
    from config import Config
    cfg = Config()
    for mode in ("VARA FM", "Aether HF", "AGWPE"):
        cfg.set("vara_mode", mode)
        assert cfg.vara_session == ""
    cfg.set("vara_mode", "VARA HF")
    cfg.set("hf_session", "bogus")
    assert cfg.vara_session == "P2P"
