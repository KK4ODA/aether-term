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
    assert pump(qapp, until=lambda: "Not connecting" in text(win)), text(win)[-600:]
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
    win._set_via(win.via1_input, "n4xyz-7")
    win._set_via(win.via2_input, "K4ABC-1")
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5 via" in text(win), timeout=15)
    assert "CONNECT KK4ODA W1AW-5 VIA N4XYZ-7 K4ABC-1" in win.fake.commands
    assert "*** CONNECTED to W1AW-5 via N4XYZ-7, K4ABC-1 ***" in text(win)
    assert win.bw_label.text() == "BW: WIDE"


@pytest.mark.parametrize("via1,expected", [
    ("N4XYZ-7", "supported with VARA FM and Soundmodem"),   # Aether HF can't digipeat
    ("N4XYZ-99", "not a valid digipeater callsign"),
])
def test_bad_digipeater_path_stops_the_call(qapp, win, monkeypatch, via1, expected):
    from gui import main_window
    shown = []
    monkeypatch.setattr(main_window.QMessageBox, "warning",
                        lambda *a, **k: shown.append(a[2]))
    win._set_via(win.via1_input, via1)
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


def _sent(win):
    return b"".join(win.fake.data)


def test_aether_bbs_gets_cr_lf_and_transport_query(qapp, win):
    """The Aether BBS (CR LF lines) is asked ;TRANSPORT? and gets CR LF."""
    win._on_connect()
    assert pump(qapp, until=lambda: "Welcome to the test BBS" in text(win), timeout=15)
    assert pump(qapp, until=lambda: b";TRANSPORT?\r\n" in _sent(win))
    win._send_text("H")
    assert pump(qapp, until=lambda: b"H\r\n" in _sent(win))


def test_bpq_node_gets_bare_cr_and_no_transport_query(qapp, win):
    """A BPQ node ends lines with a bare CR, and reads an LF after the CR
    as the start of the next command: answer it in its own convention."""
    win.fake.state["bbs"] = "bpq"
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(win), timeout=15)
    pump(qapp, 1.5)                       # the old fixed-delay query fired at 1 s
    assert _sent(win) == b""              # nothing unasked-for went to the node
    win._send_text("H")                   # node silent so far: bare CR
    assert pump(qapp, until=lambda: "Help file not found" in text(win))
    win._send_text("?")
    win._send_text("CHAT")
    assert pump(qapp, until=lambda: _sent(win).endswith(b"CHAT\r"))
    assert _sent(win) == b"H\r?\rCHAT\r"
    assert b";TRANSPORT?" not in _sent(win)


@pytest.mark.parametrize("chunks,eol", [
    ([], None),                                               # nothing yet: bare CR
    (["STONEM:KE4QCM-7} Help file not found\r"], "\r"),      # BPQ reply
    (["STONEM:KE4QCM-7} Help\rnext"], "\r"),
    (["line\r", "\nnext"], "\r\n"),                         # CR LF split across chunks
    (["Welcome\r\n", "prompt\r"], "\r\n"),                 # CR LF evidence is final
    (["line\r", "next\r"], "\r"),
    (["line\n"], "\n"),
])
def test_line_end_detection(qapp, win, chunks, eol):
    win._remote_eol = ""
    win._transport_query_pending = False
    for c in chunks:
        win._on_data_received(c)
    assert (win._remote_eol or None) == eol
    assert win._line_end() == ("\r\n" if eol in ("\r\n", "\n") else "\r")


def test_prompt_without_line_end_is_shown_after_a_pause(qapp, win):
    """BPQ apps wait at prompts like '4 Back:' with no line end."""
    win._on_data_received("1 Check in  2 Ch")
    win._on_data_received("eck out  3 Roster  4 Back:")
    assert "4 Back:" not in text(win)          # not before the BBS goes quiet
    assert pump(qapp, until=lambda: "4 Back:" in text(win), timeout=3)
    win._on_data_received("\rReturned to Node STONEM:KE4QCM-7\r")
    shown = text(win)
    assert "1 Check in  2 Check out  3 Roster  4 Back:\nReturned to Node" in shown
    assert shown.count("4 Back:") == 1


def test_password_prompt_stays_hidden_during_auto_auth(qapp, win):
    """The slow-link partial display (1.1.3) bypassed the auth check, so
    "Enter password:" showed during automatic HMAC login."""
    win._target = "W1AW-5"
    win.passwords.set_password("W1AW-5", "secret", operator=win._effective_callsign())
    win._on_data_received(";AUTH HMAC-SHA256 " + "ab" * 16 + "\r\n")
    win._on_data_received("Enter password: ")
    pump(qapp, 1.5)                            # past the partial-line delay
    assert "Enter password" not in text(win)
    assert "Challenge received" in text(win)


def test_short_prompt_is_shown_at_once_and_completed(qapp, win):
    win._on_data_received("Callsign:")
    assert text(win).endswith("Callsign:")     # no wait for a short prompt
    win._on_data_received(" KK4ODA\r")
    shown = text(win)
    assert shown.endswith("Callsign: KK4ODA\n")
    assert shown.count("Callsign:") == 1


def test_line_split_across_frames_reads_as_one_line(qapp, win):
    """VARA splits lines at frame boundaries; a slow second half must
    continue the screen line, not start a new one or repeat the first."""
    win._on_data_received("*** Connec")
    pump(qapp, 1.3)                            # slow link: first half shown
    assert "*** Connec" in text(win)
    win._on_data_received("ted to ARES        \r====\r")
    shown = text(win)
    assert "*** Connected to ARES        \n====\n" in shown
    assert shown.count("*** Connec") == 1


def test_protocol_lines_are_never_shown_half_way(qapp, win):
    win._on_data_received(";TACTICAL O")
    pump(qapp, 1.3)
    assert ";TACTICAL" not in text(win)
    win._on_data_received("K W1AW-5\r\n")
    assert "Address activated: W1AW-5" in text(win)


# ── The answer to ;TRANSPORT? ────────────────────────────────────────

def _expect_transport_reply(win):
    """As if ;TRANSPORT? had just gone out."""
    win._transport_reply_until = time.monotonic() + 20


def test_transport_reply_is_hidden_and_the_prompt_shown_once(qapp, win):
    """The BBS answers ;TRANSPORT? after its "> " prompt, then prompts again:
    the screen showed "> ;TRANSPORT VARA_FM", a blank line and "> "."""
    win.fake.state["prompt"] = True
    win.fake.state["transport_reply"] = [b";TRANSPORT AET", b"HER_HF\r", b"\n\r", b"\n", b"> "]
    win._on_connect()
    assert pump(qapp, until=lambda: "Welcome to the test BBS" in text(win), timeout=15)
    assert pump(qapp, until=lambda: win.transport_label.text() == "BBS link: AETHER_HF")
    pump(qapp, 0.3)
    shown = text(win)
    assert ";TRANSPORT" not in shown
    assert shown.endswith("Welcome to the test BBS\n> ")
    win._send_text("H")
    assert pump(qapp, until=lambda: "Help: L R S B" in text(win))
    tail = text(win).split("Welcome to the test BBS")[-1]
    assert tail.count("> ") == 2, tail          # the prompt, and the echo of H


def test_transport_reply_in_one_read_with_other_text(qapp, win):
    win._on_data_received("Welcome\r\n> ")
    _expect_transport_reply(win)
    win._on_data_received(";TRANSPORT VARA_FM\r\n\r\n> ")
    assert text(win).endswith("Welcome\n> ")
    assert win.transport_label.text() == "BBS link: VARA_FM"
    # Text either side of the hidden line still shows
    win._on_data_received("before\r\n")
    _expect_transport_reply(win)
    win._on_data_received("News 1\r\n;TRANSPORT VARA_FM\r\nNews 2\r\n")
    shown = text(win)
    assert shown.endswith("> before\nNews 1\nNews 2\n")
    assert ";TRANSPORT" not in shown


def test_other_text_after_a_hidden_reply_is_kept(qapp, win):
    win._on_data_received("> ")
    _expect_transport_reply(win)
    win._on_data_received(";TRANSPORT VARA_FM\r\n")
    win._on_data_received("\r")
    win._on_data_received("\nNew mail\r\n> ")
    assert text(win).endswith("> \nNew mail\n> ")
    assert ";TRANSPORT" not in text(win)


def test_transport_line_later_in_the_session_is_shown(qapp, win):
    win._on_data_received("> ")
    _expect_transport_reply(win)
    win._on_data_received(";TRANSPORT VARA_FM\r\n\r\n> ")
    win._on_data_received("\r\n;TRANSPORT VARA_HF\r\n")    # the first was the answer
    assert ";TRANSPORT VARA_HF" in text(win)
    _expect_transport_reply(win)
    win._transport_reply_until = time.monotonic() - 1        # asked too long ago
    win._on_data_received(";TRANSPORT AETHER_HF\r\n")
    assert ";TRANSPORT AETHER_HF" in text(win)
    assert ";TRANSPORT VARA_FM" not in text(win)
    assert win.transport_label.text() == "BBS link: VARA_FM"


def test_transport_reply_while_the_password_prompt_is_up(qapp, win):
    """Logging in, the BBS answers ;TRANSPORT? after its "> " and sends
    no new prompt; ;AUTH OK follows."""
    win._target = "W1AW-5"
    win.passwords.set_password("W1AW-5", "secret", operator=win._effective_callsign())
    win._on_data_received(";AUTH HMAC-SHA256 " + "ab" * 16 + "\r\n"
                          "Enter password (or HMAC client will respond automatically):\r\n")
    win._on_data_received("> ")
    _expect_transport_reply(win)
    win._on_data_received(";TRANSPORT VA")
    pump(qapp, 1.3)
    win._on_data_received("RA_FM\r\n")
    pump(qapp, 1.3)
    win._on_data_received(";AUTH OK\r\nWelcome, KK4ODA\r\n> ")
    shown = text(win)
    assert "Authentication successful" in shown
    assert ";TRANSPORT" not in shown and ";AUTH" not in shown
    assert "Enter password" not in shown
    assert shown.endswith("Welcome, KK4ODA\n> ")
    assert win.transport_label.text() == "BBS link: VARA_FM"


def test_transport_reply_in_the_same_read_as_the_password_prompt(qapp, win):
    """Local test mode has no radio in between: the BBS's "> " and its
    answer to ;TRANSPORT? came in one read, and showed as
    "> ;TRANSPORT VARA_FM".  No password saved here, so the prompt shows."""
    win._target = "KK4ODA-7"
    _expect_transport_reply(win)
    win._on_data_received(";AUTH HMAC-SHA256 " + "01" * 16 + "\r\n"
                          "Enter password (or HMAC client will respond automatically):\r\n"
                          "> ;TRANSPORT VARA_FM\r\n")
    shown = text(win)
    assert ";TRANSPORT" not in shown
    assert shown.endswith("automatically):\n> ")
    assert "No password saved for station KK4ODA-7 with operator KK4ODA" in shown
    assert win.transport_label.text() == "BBS link: VARA_FM"


def test_login_result_in_the_same_read_as_the_hidden_prompt(qapp, win):
    win._target = "W1AW-5"
    win.passwords.set_password("W1AW-5", "secret", operator=win._effective_callsign())
    _expect_transport_reply(win)
    win._on_data_received(";AUTH HMAC-SHA256 " + "ab" * 16 + "\r\n"
                          "Enter password (or HMAC client will respond automatically):\r\n"
                          "> ;TRANSPORT VARA_FM\r\n")
    win._on_data_received(";AUTH OK\r\nWelcome\r\n> ")    # (the BBS sends no new prompt)
    shown = text(win)
    assert "Authentication successful" in shown
    assert ";AUTH" not in shown and ";TRANSPORT" not in shown and "Enter password" not in shown
    assert shown.endswith("Welcome\n> ")


def test_password_typed_at_the_login_prompt_is_masked(qapp, win):
    win.auth.process_line(";AUTH HMAC-SHA256 " + "01" * 16, None)   # nothing saved
    from vara.connection import ConnectionState
    win.modem._state = ConnectionState.CONNECTED
    sent = []
    win.modem.send_data = sent.append
    win._send_text("hunter2")
    assert sent == ["hunter2\r"]
    assert "hunter2" not in text(win) and "> ********" in text(win)


def test_quoted_protocol_line_in_a_message_is_just_text(qapp, win):
    win._on_data_received("> ")
    win._on_data_received("\r\nMsg 12 from W1XYZ:\r\n> ;AUTH OK\r\n> ;TRANSPORT VARA_FM\r\n")
    shown = text(win)
    assert "> ;AUTH OK\n> ;TRANSPORT VARA_FM\n" in shown
    assert "Authentication successful" not in shown


def test_auth_result_straight_after_the_hidden_prompt_is_understood(qapp, win):
    """The "> " after the password prompt waits without a line end, so
    ";AUTH OK" arrived as "> ;AUTH OK": shown raw, login never noted."""
    win._target = "W1AW-5"
    win.passwords.set_password("W1AW-5", "secret", operator=win._effective_callsign())
    win._on_data_received(";AUTH HMAC-SHA256 " + "ab" * 16 + "\r\n"
                          "Enter password (or HMAC client will respond automatically):\r\n> ")
    pump(qapp, 1.3)
    win._on_data_received(";AUTH OK\r\n")
    shown = text(win)
    assert "Authentication successful" in shown
    assert ";AUTH OK" not in shown


def _reopen(qapp, win):
    """A second window on the same settings — what the next start sees."""
    from passwords import PasswordStore
    from gui.main_window import MainWindow
    w2 = MainWindow(win.config, PasswordStore(win.config.app_data_dir))
    return w2


def test_via_dropdowns_offer_none_first(qapp, win):
    for cb in (win.via1_input, win.via2_input):
        assert cb.itemText(0) == "None"
        assert cb.currentText() == "None"
        assert win._via_value(cb) == ""


def test_via_choice_and_history_are_remembered(qapp, win):
    """The last call's digipeaters come back next start, and stay in the
    dropdowns after None is chosen."""
    win._set_via(win.via1_input, "wd5ema-4")
    win._set_via(win.via2_input, "")
    win._remember_via("WD5EMA-4", "")
    w2 = _reopen(qapp, win)
    try:
        assert w2.via1_input.currentText() == "WD5EMA-4"
        assert w2.via2_input.currentText() == "None"
        assert [w2.via1_input.itemText(i) for i in range(w2.via1_input.count())] \
            == ["None", "WD5EMA-4"]
        assert w2.via2_input.findText("WD5EMA-4") >= 0     # offered in both boxes
    finally:
        w2.close()
    # A direct call (None) is remembered too, and the digipeater stays listed
    win._remember_via("", "")
    w3 = _reopen(qapp, win)
    try:
        assert w3.via1_input.currentText() == "None"
        assert w3.via1_input.findText("WD5EMA-4") >= 0
    finally:
        w3.close()


def test_connect_records_the_via_choice(qapp, win):
    """A real call saves what was chosen — here None, on the Aether HF path."""
    win.config.set("last_via1", "WD5EMA-4")
    win._set_via(win.via1_input, "")
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(win), timeout=15)
    assert win.config.get("last_via1") == ""


def test_via_history_is_capped_and_most_recent_first(qapp, win):
    from gui.main_window import MAX_VIA_HISTORY
    for i in range(MAX_VIA_HISTORY + 3):
        win._remember_via(f"DIGI{i}-1", "")
    hist = win.config.get("via_history")
    assert len(hist) == MAX_VIA_HISTORY
    assert hist[0] == f"DIGI{MAX_VIA_HISTORY + 2}-1"


@pytest.fixture
def agwpe():
    from fake_agwpe import FakeAGWPE
    fake = FakeAGWPE().start()
    yield fake
    fake.stop()


def test_soundmodem_session(qapp, win, agwpe):
    """Soundmodem (AGWPE): connect, talk, disconnect — without the window
    crashing (1.1.0–1.1.4 aborted when the TNC link came up) and without the
    call stalling before the AX.25 connect went out."""
    from vara.agwpe_modem import AGWPEModem
    from vara.connection import ConnectionState
    win.mode_combo.setCurrentIndex(3)
    pump(qapp, 0.1)
    assert win.config.mode == "AGWPE"
    win.config.set("soundmodem_port", agwpe.port)
    win._on_connect()
    ok = pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(win), timeout=15)
    assert ok, f"frames={agwpe.kinds()!r}\n" + text(win)[-700:]
    assert isinstance(win.modem, AGWPEModem)
    assert agwpe.kinds().startswith("XC")          # registered, then connected
    win._send_text("H")
    assert pump(qapp, until=lambda: "Help: BBS CHAT NODES BYE" in text(win))
    assert agwpe.data_sent() == b"H\r"
    win._on_disconnect()
    assert pump(qapp, until=lambda: win.modem.state == ConnectionState.DISCONNECTED)


def test_soundmodem_digipeater_session(qapp, win, agwpe):
    """Via 1 / Via 2 in Soundmodem mode go out as an AGWPE 'v' connect;
    Soundmodem's own Digi settings don't set the path of our calls."""
    win.mode_combo.setCurrentIndex(3)
    pump(qapp, 0.1)
    win.config.set("soundmodem_port", agwpe.port)
    win._set_via(win.via1_input, "WD5EMA-4")
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5 via WD5EMA-4" in text(win),
                timeout=15), f"frames={agwpe.kinds()!r}\n" + text(win)[-600:]
    assert "v" in agwpe.kinds() and "C" not in agwpe.kinds()
    assert agwpe.via == ["WD5EMA-4"]
    assert "VARA license" not in text(win)          # that note is VARA FM's


def test_via_boxes_fit_a_full_callsign(qapp, win):
    """1.1.4's boxes were squeezed until "None" read "one"."""
    win.show()
    pump(qapp, 0.2)
    for cb in (win.via1_input, win.via2_input):
        need = cb.fontMetrics().horizontalAdvance("WD5EMA-15")
        assert cb.lineEdit().width() >= need, (cb.lineEdit().width(), need)


def test_agwpe_modem_takes_the_vara_init_arguments(qapp):
    """The main window calls initialize_modem the same way for every modem."""
    from vara.agwpe_modem import AGWPEModem
    from vara.connection import ConnectionState
    m = AGWPEModem()
    states = []
    m.state_changed.connect(states.append)
    m.initialize_modem("KK4ODA", False, 2300, query_version=False)
    assert states == [ConnectionState.INITIALIZING, ConnectionState.MODEM_CONNECTED]


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


# ── Modem programs follow the mode ──────────────────────────────────────

@pytest.fixture
def launches(win, tmp_path, monkeypatch):
    """Record modem programs started and stopped instead of running them."""
    from gui.main_window import MainWindow
    log = []

    class Proc:
        def __init__(self, label):
            self.label, self.pid, self.alive = label, 1, True

        def poll(self):
            return None if self.alive else 0

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            self.alive = False
            log.append(f"stop {self.label}")

    def fake_start(self, exe, label):
        log.append(f"start {label}")
        p = Proc(label)
        self._modem_procs.append(p)
        return p
    monkeypatch.setattr(MainWindow, "_start_modem_exe", fake_start)
    monkeypatch.setattr("os.name", "posix")      # terminate(), not taskkill
    for key, name in (("vara_fm_exe_path", "VARAFM.exe"),
                      ("soundmodem_exe_path", "soundmodem.exe")):
        exe = tmp_path / name
        exe.write_text("")
        win.config.set(key, str(exe))
    win.config.set("soundmodem_auto_launch", True)
    win.config.set("vara_fm_auto_launch", True)
    return log


def _add_profile(win, mode):
    win.config.add_profile({"name": mode, "mode": mode,
                            "target_callsign": "KE4QCM-7"})
    win._refresh_profiles()
    return len(win.config.get_profiles())        # its index in the combo


def test_profile_switch_swaps_the_modem_program(qapp, win, launches):
    """Choosing a profile in another mode closes the old modem program and
    starts the new one, as the mode dropdown does."""
    win.mode_combo.setCurrentIndex(3)            # Soundmodem
    assert pump(qapp, until=lambda: launches == ["start Soundmodem"])
    idx = _add_profile(win, "VARA FM")
    win.profile_combo.setCurrentIndex(idx)
    assert pump(qapp, until=lambda: launches[-1] == "start VARA FM")
    assert launches == ["start Soundmodem", "stop Soundmodem", "start VARA FM"]
    assert win.config.mode == "VARA FM"
    assert win.mode_combo.currentText() == win.mode_combo.itemText(0)
    assert win.target_input.currentText() == "KE4QCM-7"


def test_profile_in_the_same_mode_leaves_the_modem_running(qapp, win, launches):
    win.mode_combo.setCurrentIndex(3)
    assert pump(qapp, until=lambda: launches == ["start Soundmodem"])
    win.profile_combo.setCurrentIndex(_add_profile(win, "AGWPE"))
    pump(qapp, 0.5)
    assert launches == ["start Soundmodem"]


def test_profile_connect_waits_for_a_new_modem(qapp, win, launches, monkeypatch):
    from gui import main_window
    monkeypatch.setattr(main_window, "MODEM_START_DELAY_MS", 600)
    calls = []
    monkeypatch.setattr(win, "_on_connect", lambda: calls.append(1))
    win._connect_from_profile({"mode": "AGWPE", "target_callsign": "KE4QCM-7"})
    pump(qapp, 0.4)
    assert not calls                             # still waiting for Soundmodem
    assert pump(qapp, until=lambda: calls, timeout=3)
    assert "start Soundmodem" in launches


def test_profiles_and_mode_are_locked_during_a_call(qapp, win):
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(win), timeout=15)
    assert not win.profile_combo.isEnabled() and not win.mode_combo.isEnabled()
    assert not win._switch_mode("VARA FM")
    assert win.config.mode == "Aether HF"
    assert "Disconnect before switching" in text(win)


def test_connect_from_profiles_window_keeps_the_profile(qapp, win, monkeypatch):
    """Closing the Profiles window rebuilt the dropdown, which reset the
    profile just connected: the call went out under the global callsign."""
    from gui import main_window
    profile = {"name": "ARES", "mode": "Aether HF", "my_callsign": "N0CALL",
               "my_ssid": 7, "target_callsign": "KE4QCM-7"}
    win.config.add_profile(dict(profile))

    class FakeDialog:
        def __init__(self, config, parent):
            from PyQt6.QtCore import QObject, pyqtSignal

            class S(QObject):
                profile_connect = pyqtSignal(dict)
            self._s = S()
            self.profile_connect = self._s.profile_connect

        def exec(self):
            self.profile_connect.emit(dict(profile))   # its Connect button

    monkeypatch.setattr(main_window, "ProfileDialog", FakeDialog)
    calls = []
    monkeypatch.setattr(win, "_on_connect", lambda: calls.append(win._effective_callsign()))
    win._open_profiles()
    assert pump(qapp, until=lambda: calls, timeout=3)
    assert calls == ["N0CALL-7"]
    assert win.profile_combo.currentIndex() == 1


def test_profile_sets_fm_bandwidth_on_connect_too(qapp, win, monkeypatch):
    monkeypatch.setattr(win, "_on_connect", lambda: None)
    win.config.set("fm_bandwidth", "WIDE")
    win._connect_from_profile({"mode": "VARA FM", "fm_bandwidth": "NARROW",
                               "target_callsign": "KE4QCM-7"})
    assert win.config.get("fm_bandwidth") == "NARROW"


def test_max_retries_setting_reaches_the_modem(qapp, win, monkeypatch):
    """Settings → Max Retries was saved but the modem always tried 5 times."""
    from vara.modem import VARAModem
    from conftest import pump
    tries = []
    monkeypatch.setattr(VARAModem, "_do_connect",
                        lambda self, host, c, d, n: tries.append(n))
    win.config.set("max_retries", 2)
    win._on_connect()
    assert pump(qapp, until=lambda: tries, timeout=5)
    assert tries == [2]


def test_macro_buttons_are_built_once_and_rebuilt(qapp, win):
    labels = [b.text() for b in win.macro_buttons]
    assert labels == [m["label"] for m in win.config.get_macros()]
    win.macro_buttons[0].click()                 # not connected: refused, said so
    assert "Not connected — command not sent." in text(win)
    win.config.set_macros([{"label": "Mine", "command": "L"}])
    win._refresh_macros()
    assert [b.text() for b in win.macro_buttons] == ["Mine"]
    assert win.macro_frame.layout().count() == 3  # "Quick:", Mine, stretch


# ── 1.1.11: no second call on top of a live one ────────────────────

def test_connect_is_refused_during_a_session(qapp, win):
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(win), timeout=15)
    assert not win.connect_action.isEnabled()
    connects = win.fake.commands.count("CONNECT KK4ODA W1AW-5")
    win.connect_action.trigger()                # File → Connect / Ctrl+Shift+C
    pump(qapp, 1.0)
    assert win.fake.commands.count("CONNECT KK4ODA W1AW-5") == connects
    assert text(win).count("Connecting to W1AW-5") == 1
    win._on_disconnect()
    assert pump(qapp, until=lambda: win.connect_action.isEnabled(), timeout=15)


def test_settings_cannot_change_the_mode_during_a_session(qapp, win, monkeypatch):
    from gui import main_window
    seen = {}

    class Dialog(main_window.SettingsDialog):
        def exec(self):
            seen["locked"] = [b.isEnabled() for b in self.mode_group.buttons()]
            return 0
    monkeypatch.setattr(main_window, "SettingsDialog", Dialog)
    win._open_settings()
    assert seen["locked"] and all(seen["locked"])        # free while idle
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to W1AW-5" in text(win), timeout=15)
    win._open_settings()
    assert not any(seen["locked"])


# ── 1.1.11: saved passwords and the operator's SSID ───────────────

@pytest.mark.parametrize("saved_as,connect_as", [
    ("KK4ODA-7", "KK4ODA-2"),
    ("KK4ODA-7", "KK4ODA"),
    ("KK4ODA", "KK4ODA-2"),
])
def test_password_is_found_for_any_ssid_of_the_operator(home, saved_as, connect_as):
    from passwords import PasswordStore
    from config import Config
    store = PasswordStore(Config().app_data_dir)
    store.set_password("W1AW-5", "pw", operator=saved_as)
    assert store.get_password("W1AW-5", connect_as) == "pw"
    assert store.get_password("W1AW-5", "N0CALL") is None


def test_exact_operator_entry_wins_over_another_ssid(home):
    from passwords import PasswordStore
    from config import Config
    store = PasswordStore(Config().app_data_dir)
    store.set_password("W1AW-5", "seven", operator="KK4ODA-7")
    store.set_password("W1AW-5", "two", operator="KK4ODA-2")
    store.set_password("W1AW-5", "base", operator="KK4ODA")
    assert store.get_password("W1AW-5", "KK4ODA-2") == "two"
    assert store.get_password("W1AW-5", "KK4ODA-9") == "base"


def test_auto_login_off_says_so_and_shows_the_prompt(qapp, win):
    win.config.set("auto_respond_hmac", False)
    win._target = "W1AW-5"
    win.passwords.set_password("W1AW-5", "secret", operator=win._effective_callsign())
    win._on_data_received(";AUTH HMAC-SHA256 " + "ab" * 16 + "\r\n")
    win._on_data_received("Enter password: ")
    pump(qapp, 1.5)
    assert "Automatic login is off" in text(win)
    assert "No saved password" not in text(win)
    assert "Enter password" in text(win)
