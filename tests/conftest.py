"""Shared fixtures: an offscreen Qt app, a sandboxed home, and a fake modem."""

import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parent.parent / "src"
TESTS = Path(__file__).resolve().parent
for p in (str(SRC), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def home(tmp_path, monkeypatch):
    """APPDATA/LOCALAPPDATA/home moved into a temp dir — no real settings touched."""
    roaming = tmp_path / "Roaming"
    local = tmp_path / "Local"
    user = tmp_path / "home"
    for d in (roaming, local, user):
        d.mkdir()
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("USERPROFILE", str(user))
    monkeypatch.setenv("HOME", str(user))
    return tmp_path


@pytest.fixture
def aetherd():
    from fake_aetherd import FakeAetherd
    fake = FakeAetherd().start()
    yield fake
    fake.stop()


def pump(app, seconds=0.0, until=None, timeout=10.0):
    """Process Qt events for ``seconds``, or until ``until()`` is true."""
    from PyQt6.QtCore import QEventLoop
    end = time.time() + (timeout if until else seconds)
    while time.time() < end:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        if until and until():
            return True
        time.sleep(0.01)
    return bool(until and until())
