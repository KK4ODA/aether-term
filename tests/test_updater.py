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
    reply = {"code": 200, "body": {}}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
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
