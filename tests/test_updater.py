"""The release-mode updater (installed builds), against a local fake API."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.mark.parametrize("remote,local,newer", [
    ("v1.1.0", "1.0.3", True),
    ("v1.1.0", "1.1.0", False),
    ("v1.0.9", "1.1.0", False),
    ("v1.10.0", "1.9.0", True),
    ("", "1.0.0", False),
    ("nightly", "1.0.0", False),
])
def test_is_newer(remote, local, newer):
    from updater import is_newer
    assert is_newer(remote, local) is newer


@pytest.fixture
def releases_api():
    reply = {"code": 200, "body": {}, "asset": b""}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.endswith("/asset"):
                self.send_response(200)
                self.send_header("Content-Length", str(len(reply["asset"])))
                self.end_headers()
                self.wfile.write(reply["asset"])
                return
            raw = json.dumps(reply["body"]).encode()
            self.send_response(reply["code"])
            self.end_headers()
            self.wfile.write(raw)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/latest", reply
    srv.shutdown()


def _updater(tmp_path, api, version):
    from updater import Updater
    return Updater({}, repo_dir=tmp_path, current_version=version, releases_api=api)


def test_installed_build_uses_release_mode(qapp, tmp_path, releases_api):
    api, _ = releases_api
    assert _updater(tmp_path, api, "1.1.0").mode == "release"


def test_newer_release_is_offered(qapp, tmp_path, releases_api):
    api, reply = releases_api
    reply["body"] = {"tag_name": "v1.2.0", "name": "Aether Term 1.2.0",
                     "body": "- things", "html_url": "https://example/rel"}
    up = _updater(tmp_path, api, "1.1.0")
    seen = []
    up.update_available.connect(seen.append)
    r = up.check_for_updates()
    assert r.update_available and r.mode == "release"
    assert r.release_url == "https://example/rel" and r.label == "UPDATE v1.2.0"
    assert seen == [r]


def test_same_release_is_not_offered(qapp, tmp_path, releases_api):
    api, reply = releases_api
    reply["body"] = {"tag_name": "v1.1.0"}
    r = _updater(tmp_path, api, "1.1.0").check_for_updates()
    assert not r.update_available and r.error is None


def test_no_release_yet_is_not_an_error(qapp, tmp_path, releases_api):
    api, reply = releases_api
    reply["code"] = 404
    r = _updater(tmp_path, api, "1.1.0").check_for_updates()
    assert not r.update_available and r.error is None


def test_apply_is_refused_in_release_mode(qapp, tmp_path, releases_api):
    api, _ = releases_api
    res = _updater(tmp_path, api, "1.1.0").apply_update()
    assert not res.success and "release" in res.error


def _release_with_installer(api, payload, digest=None, size=None):
    import hashlib
    base = api.rsplit("/", 1)[0]
    return {"tag_name": "v1.2.0", "html_url": "https://example/rel", "assets": [
        {"name": "Aether_Term_Portable_1.2.0.zip", "size": 1,
         "browser_download_url": base + "/zip"},
        {"name": "Aether_Term_Setup_1.2.0.exe",
         "size": len(payload) if size is None else size,
         "digest": digest if digest is not None
         else "sha256:" + hashlib.sha256(payload).hexdigest(),
         "browser_download_url": base + "/asset"},
    ]}


def test_check_finds_the_installer_and_reports_every_check(qapp, tmp_path, releases_api):
    api, reply = releases_api
    reply["body"] = _release_with_installer(api, b"setup")
    up = _updater(tmp_path, api, "1.1.0")
    finished = []
    up.check_finished.connect(finished.append)
    r = up.check_for_updates()
    assert r.installer_name == "Aether_Term_Setup_1.2.0.exe"
    assert r.installer_url.endswith("/asset") and r.installer_size == 5
    assert len(r.installer_sha256) == 64
    assert r.version_key == "v1.2.0"
    assert finished == [r]
    reply["body"] = {"tag_name": "v1.1.0"}
    up.check_for_updates()
    assert len(finished) == 2 and not finished[1].update_available


def test_download_installer(qapp, tmp_path, releases_api):
    api, reply = releases_api
    reply["asset"] = b"x" * 200_000
    reply["body"] = _release_with_installer(api, reply["asset"])
    up = _updater(tmp_path, api, "1.1.0")
    r = up.check_for_updates()
    seen = []
    path = up.download_installer(r, progress=lambda d, t: seen.append((d, t)),
                                 dest_dir=tmp_path)
    assert path.name == "Aether_Term_Setup_1.2.0.exe"
    assert path.read_bytes() == reply["asset"]
    assert seen[-1] == (200_000, 200_000)


@pytest.mark.parametrize("kwargs,message", [
    ({"digest": "sha256:" + "0" * 64}, "checksum"),
    ({"size": 999}, "incomplete"),
])
def test_bad_download_is_refused(qapp, tmp_path, releases_api, kwargs, message):
    api, reply = releases_api
    reply["asset"] = b"setup program"
    reply["body"] = _release_with_installer(api, reply["asset"], **kwargs)
    up = _updater(tmp_path, api, "1.1.0")
    r = up.check_for_updates()
    with pytest.raises(RuntimeError, match=message):
        up.download_installer(r, dest_dir=tmp_path)
    assert not list(tmp_path.glob("*.exe"))     # nothing half-checked is left


def test_update_dialog_downloads_runs_installer_and_quits(qapp, tmp_path, releases_api,
                                                         monkeypatch, home):
    from conftest import pump
    from config import Config
    from gui.update_dialog import UpdateDialog
    api, reply = releases_api
    reply["asset"] = b"setup program"
    reply["body"] = _release_with_installer(api, reply["asset"])
    up = _updater(tmp_path, api, "1.1.0")
    r = up.check_for_updates()
    launched, quit_ = [], []
    monkeypatch.setattr(type(up), "launch_installer",
                        staticmethod(lambda p: launched.append(p)))
    dlg = UpdateDialog(r, up, lambda: None, config=Config(),
                       quit_callback=lambda: quit_.append(1), can_install=True)
    assert dlg._update_btn.text() == "Download && Install"
    dlg._update_btn.click()
    assert pump(qapp, until=lambda: quit_, timeout=10)
    assert launched and launched[0].read_bytes() == b"setup program"


def test_update_dialog_without_installer_opens_page(qapp, tmp_path, releases_api, home):
    from config import Config
    from gui.update_dialog import UpdateDialog
    api, reply = releases_api
    reply["body"] = {"tag_name": "v1.2.0", "html_url": "https://example/rel"}
    up = _updater(tmp_path, api, "1.1.0")
    r = up.check_for_updates()
    dlg = UpdateDialog(r, up, lambda: None, config=Config(), can_install=True)
    assert dlg._update_btn.text() == "Open Download Page"


def test_skip_this_version(qapp, tmp_path, releases_api, home):
    from config import Config
    from gui.update_dialog import UpdateDialog
    api, reply = releases_api
    reply["body"] = {"tag_name": "v1.2.0"}
    r = _updater(tmp_path, api, "1.1.0").check_for_updates()
    cfg = Config()
    dlg = UpdateDialog(r, None, lambda: None, config=cfg, can_install=False)
    dlg._skip_btn.click()
    assert cfg.get("skipped_update_version") == "v1.2.0"


# ── Git mode (a clone run from source) ──────────────────────────────────

def _git(cwd, *args):
    import subprocess
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def clone(tmp_path):
    """An origin repo with one commit on main, and a clone of it."""
    import shutil
    if not shutil.which("git"):
        pytest.skip("git not installed")
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    (origin / "a.txt").write_text("1")
    _git(origin, "add", ".")
    _git(origin, "commit", "-q", "-m", "one")
    _git(tmp_path, "clone", "-q", str(origin), "clone")
    return origin, tmp_path / "clone"


def _git_updater(path):
    from updater import Updater
    return Updater({}, repo_dir=path, current_version="1.0.0")


def test_git_clone_behind_origin_is_offered_the_commits(qapp, clone):
    origin, local = clone
    (origin / "a.txt").write_text("2")
    _git(origin, "commit", "-q", "-am", "two")
    r = _git_updater(local).check_for_updates()
    assert r.update_available and [c.subject for c in r.commits] == ["two"]


def test_git_clone_ahead_of_origin_has_no_update(qapp, clone):
    """Hashes differing used to mean "update available", so local work
    (or another branch) was always offered origin/main."""
    _, local = clone
    (local / "b.txt").write_text("mine")
    _git(local, "add", ".")
    _git(local, "commit", "-q", "-m", "local work")
    r = _git_updater(local).check_for_updates()
    assert not r.update_available and not r.error


def test_failed_pull_gives_local_changes_back(qapp, clone):
    """A pull that fails used to leave the user's changes in the stash."""
    origin, local = clone
    (origin / "a.txt").write_text("2")
    _git(origin, "commit", "-q", "-am", "two")
    (local / "c.txt").write_text("x")              # local commit: no fast-forward
    _git(local, "add", ".")
    _git(local, "commit", "-q", "-m", "diverge")
    (local / "a.txt").write_text("uncommitted edit")
    result = _git_updater(local).apply_update()
    assert not result.success
    assert (local / "a.txt").read_text() == "uncommitted edit"
    import subprocess
    stash = subprocess.run(["git", "stash", "list"], cwd=local,
                           capture_output=True, text=True).stdout
    assert stash == ""


def test_restart_uses_an_absolute_script_path(qapp, monkeypatch, tmp_path):
    """Launched as "py src\\main.py", the restarted process used to look for
    src\\src\\main.py and never came back after a git update."""
    import os
    import sys
    from gui.main_window import MainWindow
    started = []
    monkeypatch.setattr("subprocess.Popen", lambda args, cwd=None: started.append((args, cwd)))
    monkeypatch.setattr(sys, "argv", [os.path.join("src", "main.py")])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("PyQt6.QtWidgets.QApplication.quit", lambda self=None: None)
    MainWindow._restart(None)
    args, cwd = started[0]
    script = args[1]
    assert os.path.isabs(script) and script.endswith(os.path.join("src", "main.py"))
