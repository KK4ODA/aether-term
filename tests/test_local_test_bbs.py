"""Local test mode against the real Aether BBS (github.com/KK4ODA/aether-bbs).

Skipped unless a checkout is found: $AETHER_BBS_DIR, or aether-bbs next
to this repository.  The BBS runs in its own Python (tests/bbs_harness.py):
it has a ``vara`` package of its own.
"""

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import test_local_test
from conftest import pump

win = test_local_test.win          # the main window in local test mode
text = test_local_test.text

HERE = Path(__file__).resolve().parent


def _find_bbs():
    candidates = [os.environ.get("AETHER_BBS_DIR", ""),
                  HERE.parent.parent / "aether-bbs",
                  HERE.parent.parent / "kk4oda" / "aether-bbs"]
    for c in candidates:
        if c and (Path(c) / "vara" / "interface.py").is_file():
            return Path(c)
    return None


BBS_DIR = _find_bbs()
if BBS_DIR is None:
    pytest.skip("no Aether BBS checkout (set AETHER_BBS_DIR)", allow_module_level=True)
if subprocess.run([sys.executable, "-I", "-c", "import pydantic, tomli_w"],
                  capture_output=True).returncode:
    pytest.skip("the Aether BBS needs pydantic and tomli-w", allow_module_level=True)


class BBS:
    """The real BBS in a child process."""

    def __init__(self, cmd_port, data_port, work, user="", password=""):
        args = [sys.executable, "-I", str(HERE / "bbs_harness.py"), str(BBS_DIR),
                str(cmd_port), str(data_port), str(work)]
        if user:
            args += [user, password]
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
        self.out, self.err = [], []
        for stream, into in ((self.proc.stdout, self.out), (self.proc.stderr, self.err)):
            threading.Thread(target=lambda s=stream, i=into: i.extend(iter(s.readline, "")),
                             daemon=True).start()

    def state(self, timeout=40):
        end = time.time() + timeout
        while time.time() < end and not any(l.startswith("STATE") for l in self.out):
            time.sleep(0.1)
        return next((l.strip() for l in self.out if l.startswith("STATE")), None)

    @property
    def log(self):
        return "".join(self.err)

    def stop(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


@pytest.fixture
def bbs_factory(tmp_path):
    started = []

    def start(cmd_port, data_port, **kw):
        b = BBS(cmd_port, data_port, tmp_path, **kw)
        started.append(b)
        return b
    yield start
    for b in started:
        b.stop()


def test_bbs_instance_reaches_listening_with_no_wrong(qapp, bbs_factory):
    from vara.local_test import LocalTestModem
    m = LocalTestModem()
    m.listen(0, 0)
    try:
        bbs = bbs_factory(m.cmd_port, m.data_port)
        assert bbs.state() == "STATE LISTENING WRONG=0", bbs.log[-3000:]
        assert "WRONG" not in bbs.log
        assert m.bbs_call == "N0BBS-10" and m.bbs_listening
    finally:
        m.shutdown()


def test_session_with_the_real_bbs(qapp, win, bbs_factory):
    """Connect, HMAC login, ;TRANSPORT?, a command and Bye — the BBS's own
    session code on one side, Aether Term's on the other."""
    win.passwords.set_password("N0BBS-10", "s3cret-pw", operator="KK4ODA")
    bbs = bbs_factory(win.modem.cmd_port, win.modem.data_port,
                      user="KK4ODA", password="s3cret-pw")
    assert bbs.state() == "STATE LISTENING WRONG=0", bbs.log[-3000:]
    assert pump(qapp, until=lambda: "N0BBS-10 attached" in win.modem_status_label.text())
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to N0BBS-10" in text(win), timeout=15)
    assert pump(qapp, until=lambda: "Authentication successful" in text(win), timeout=20), \
        text(win)[-1500:] + bbs.log[-3000:]
    assert pump(qapp, until=lambda: win.transport_label.text() == "BBS link: VARA_FM",
                timeout=20), text(win)[-1500:]
    # (the BBS checks its internet link before its first prompt)
    assert pump(qapp, until=lambda: text(win).endswith("\n> "), timeout=30), text(win)[-800:]
    shown = text(win)
    assert ";TRANSPORT" not in shown and ";AUTH" not in shown
    assert "Enter password" not in shown
    assert "> \n\n> " not in shown and "> > " not in shown, shown[-800:]
    win._send_text("H")
    assert pump(qapp, until=lambda: text(win).count("\n> ") >= 2
                and text(win).endswith("\n> "), timeout=20), text(win)[-800:]
    assert ";TRANSPORT" not in text(win)
    win._send_text("B")
    assert pump(qapp, until=lambda: "*** DISCONNECTED ***" in text(win), timeout=20), \
        text(win)[-1500:]
    assert pump(qapp, until=lambda: win.connect_btn.isEnabled())
    assert "WRONG" not in bbs.log, bbs.log[-3000:]


def test_stranger_gets_the_bbs_guest_session(qapp, win, bbs_factory):
    win.config.set("local_test_callsign", "N0CALL")
    bbs = bbs_factory(win.modem.cmd_port, win.modem.data_port)
    assert bbs.state() == "STATE LISTENING WRONG=0", bbs.log[-3000:]
    assert pump(qapp, until=lambda: "N0BBS-10 attached" in win.modem_status_label.text())
    win._on_connect()
    assert pump(qapp, until=lambda: "CONNECTED to N0BBS-10" in text(win), timeout=15)
    # the BBS took the caller from CONNECTED, and treats it as a stranger
    assert pump(qapp, until=lambda: "RF session connected: N0CALL" in bbs.log,
                timeout=15), bbs.log[-2000:]
    assert pump(qapp, until=lambda: text(win).endswith("\n> ")
                or text(win).endswith(": "), timeout=20), text(win)[-1200:]
    assert "Authentication" not in text(win)
    assert "WRONG" not in bbs.log
