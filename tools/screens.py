#!/usr/bin/env python3
"""
tools/screens.py — screenshots of Aether Term for the README and radiopost.org.

    python tools/screens.py [--bbs DIR]

Needs Aether BBS checked out beside this repository (or --bbs, or
AETHER_BBS_DIR): the pictures show a real session with it.

Runs both programs offscreen (Qt's offscreen platform: no window is
shown), each with sample data in a throw-away folder, and saves PNGs to
docs/screenshots/.  Your own settings, passwords and logs are never read
or written.  Nothing is transmitted.

Aether Term runs in local test mode: it plays the VARA FM modem on
127.0.0.1.  The board is the BBS's own tools/screens.py --serve, which
starts the real Aether BBS with one instance attached to those ports, as
it would attach to VARA FM.  Term then calls the board (N0CALL-10) as
N1TEST, answers its login challenge (term-login.png), lists its messages
(L), reads one (R 1: term-session.png) and says Bye.  The board's script takes its own pictures when told
to, so its dashboard shows the session while it is up; they go to its
docs/screenshots/ (or --bbs-out).

The callsigns are in a form the FCC never issues: N0CALL-10 (the board),
N0CALL (its sysop), N1TEST (the caller), K2TEST and W3TEST.
"""

import argparse
import os
import queue
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SIZE = (1000, 780)          # the window, logical pixels (the program opens at 950 x 700)
SCALE = "2"                 # device pixels per logical pixel

STATION = "N0CALL-10"
USER, USER_PASSWORD = "N1TEST", "sample-password-1"   # the board's script sets the same


def _isolate(base: Path):
    """Every per-user folder into the throw-away one, before any module of
    the program is imported."""
    for sub, vars_ in (("Roaming", ("APPDATA",)), ("Local", ("LOCALAPPDATA",)),
                       ("home", ("HOME", "USERPROFILE"))):
        d = base / sub
        d.mkdir(parents=True, exist_ok=True)
        for v in vars_:
            os.environ[v] = str(d)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = SCALE


def _ports():
    """Local test's own ports, 8500 and 8501, when they are free (the
    pictures then match the manual); else any two free ones."""
    socks = []
    try:
        for p in (8500, 8501):
            s = socket.socket()
            socks.append(s)
            s.bind(("127.0.0.1", p))
        return [8500, 8501]
    except OSError:
        pass
    finally:
        for s in socks:
            s.close()
    socks = []
    for _ in range(2):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        socks.append(s)
    ports = [s.getsockname()[1] for s in socks]
    for s in socks:
        s.close()
    return ports


def _find_bbs(given: str | None) -> Path | None:
    for c in (given or "", os.environ.get("AETHER_BBS_DIR", ""), ROOT.parent / "aether-bbs"):
        if c and (Path(c) / "tools" / "screens.py").is_file():
            return Path(c).resolve()
    return None


class Board:
    """Aether BBS's tools/screens.py --serve, in its own Python: the BBS has
    a ``vara`` package of its own, so it cannot share this process."""

    def __init__(self, bbs: Path, ports, out: Path | None):
        args = [sys.executable, str(bbs / "tools" / "screens.py"),
                "--serve", f"{ports[0]},{ports[1]}"]
        if out:
            args += ["--out", str(out)]
        env = {k: v for k, v in os.environ.items() if k != "QT_SCALE_FACTOR"}
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, env=env)
        self.lines: queue.Queue = queue.Queue()
        self.log: list[str] = []
        threading.Thread(target=lambda: [self.lines.put(x.strip()) for x in self.proc.stdout],
                         daemon=True).start()
        threading.Thread(target=lambda: self.log.extend(self.proc.stderr), daemon=True).start()

    def expect(self, prefix: str, pump, timeout=60.0) -> str:
        end = time.time() + timeout
        while time.time() < end:
            pump(0.05)
            try:
                line = self.lines.get_nowait()
            except queue.Empty:
                continue
            if line.startswith(prefix):
                return line
        raise SystemExit(f"the board never said {prefix!r}:\n" + "".join(self.log[-40:]))

    def shot(self, name: str, pump) -> str:
        self.proc.stdin.write(f"SHOT {name}\n")
        self.proc.stdin.flush()
        return self.expect(f"SHOT {name} ", pump).split(" ", 2)[2]

    def quit(self):
        try:
            self.proc.stdin.write("QUIT\n")
            self.proc.stdin.close()
            self.proc.wait(timeout=30)
        except Exception:
            self.proc.kill()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "screenshots")
    ap.add_argument("--bbs", help="the Aether BBS checkout (default: beside this one)")
    ap.add_argument("--bbs-out", type=Path, help="where the board's pictures go "
                    "(default: its own docs/screenshots)")
    a = ap.parse_args()
    bbs = _find_bbs(a.bbs)
    if bbs is None:
        sys.exit("Aether BBS is not beside this checkout: pass --bbs DIR or set AETHER_BBS_DIR.")
    a.out = a.out.resolve()
    a.out.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="aether-term-screens-"))
    _isolate(tmp)
    sys.path.insert(0, str(ROOT / "src"))

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QEventLoop
    qt = QApplication.instance() or QApplication([sys.argv[0]])
    qt.setApplicationName("Aether Term")

    def pump(seconds=0.0, until=None, timeout=30.0):
        end = time.time() + (timeout if until else seconds)
        while time.time() < end:
            qt.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            if until and until():
                return True
            time.sleep(0.01)
        return bool(until and until())

    import passwords
    passwords.HAS_KEYRING = False          # never the system's keyring
    from config import Config
    from passwords import PasswordStore
    from gui.main_window import MainWindow
    MainWindow._check_omnirig = lambda self: None

    cmd_port, data_port = _ports()
    cfg = Config()
    cfg.set("my_callsign", USER)
    cfg.set("vara_mode", "Local test")
    cfg.set("local_test_cmd_port", cmd_port)
    cfg.set("local_test_data_port", data_port)
    cfg.set("check_updates_on_startup", False)
    win = MainWindow(cfg, PasswordStore(cfg.app_data_dir))
    win.passwords.set_password(STATION, USER_PASSWORD, operator=USER)
    win.resize(*SIZE)
    win.show()

    def text():
        return win.terminal.display.toPlainText()

    def prompt(n):
        return lambda: text().count("\n> ") >= n and text().endswith("\n> ")

    def say(line, n):
        win._send_text(line)
        if not pump(until=prompt(n), timeout=30):
            raise SystemExit(f"no prompt after {line!r}:\n{text()[-1500:]}")

    def grab(name):
        pump(0.6)
        path = a.out / f"term-{name}.png"
        win.grab().save(str(path))
        print(path)

    board = Board(bbs, (cmd_port, data_port), a.bbs_out)
    try:
        board.expect("READY", pump)
        if not pump(until=lambda: f"{STATION} attached" in win.modem_status_label.text()):
            raise SystemExit("the board did not attach")
        win._on_connect()
        if not pump(until=lambda: "Authentication successful" in text(), timeout=30):
            raise SystemExit(f"no login:\n{text()[-1500:]}")
        # (the board checks its internet link before its first prompt)
        if not pump(until=prompt(1), timeout=40):
            raise SystemExit(f"no prompt:\n{text()[-1500:]}")
        grab("login")
        say("L", 2)
        say("R 1", 3)
        grab("session")
        print(board.shot("dashboard", pump))
        win._send_text("B")
        if not pump(until=lambda: "*** DISCONNECTED ***" in text(), timeout=30):
            raise SystemExit(f"no disconnect:\n{text()[-1500:]}")
        pump(until=lambda: win.connect_btn.isEnabled())
        for name in ("messages", "bulletins"):
            print(board.shot(name, pump))
    finally:
        board.quit()
        win.hide()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
