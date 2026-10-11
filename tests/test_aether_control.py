"""The control-API client, against the fake daemon."""

import socket
import time

import pytest

from conftest import pump


def test_snapshot_reads_status(aetherd):
    from aether.control import AetherControl
    client = AetherControl(aetherd.control_url)
    st = client.snapshot(client.rung_names())
    assert st.reachable
    assert st.version == "0.2.0-beta.102"
    assert st.bandwidth_hz == 2300
    assert st.host_enabled
    assert st.rung_name == "BPSK-1/3"            # mode 7
    assert st.problems == []
    assert st.summary == "Aether 0.2.0-beta.102 · 2300 Hz"


@pytest.mark.parametrize("change,expected", [
    ({"host_enabled": False}, "host interface is off"),
    ({"policy": "unset"}, "No rules are chosen"),
    ({"policy": "broken"}, "regulatory profile would not load"),
    ({"verdict": "blocked"}, "Rules: FCC: blocked"),
    ({"ptt_fault": "COM3 is in use"}, "Keying: COM3 is in use"),
    ({"audio_fault": "USB CODEC unplugged"}, "Sound card: USB CODEC unplugged"),
])
def test_problems(aetherd, change, expected):
    from aether.control import AetherControl
    aetherd.state.update(change)
    st = AetherControl(aetherd.control_url).snapshot()
    assert any(expected in p for p in st.problems), st.problems


def test_refused_method_raises_with_message(aetherd):
    from aether.control import AetherControl, AetherControlError
    with pytest.raises(AetherControlError, match="No method nope"):
        AetherControl(aetherd.control_url).call("nope")


def test_unreachable():
    from aether.control import AetherControl
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    st = AetherControl(f"http://127.0.0.1:{port}").snapshot()
    assert not st.reachable and st.problems == []
    assert st.summary == "Aether: offline"


def test_query_does_not_block_the_caller(qapp, aetherd):
    from aether.control import AetherQuery
    aetherd.state["status_delay"] = 1.0
    q = AetherQuery()
    got = []
    t0 = time.time()
    q.snapshot(aetherd.control_url, got.append)
    assert time.time() - t0 < 0.2
    assert pump(qapp, until=lambda: got, timeout=5)
    assert got[0].reachable and q.pending == 0


def test_monitor_emits_status(qapp, aetherd):
    from aether.control import AetherMonitor
    m = AetherMonitor()
    got = []
    m.status_updated.connect(got.append)
    m.start(aetherd.control_url)
    try:
        assert pump(qapp, until=lambda: got, timeout=5)
        assert got[0].rung_name == "BPSK-1/3"
    finally:
        m.stop()


def test_find_aether_exe_default_location(home):
    from aether.control import find_aether_exe
    exe = home / "Local" / "Aether HF" / "aether-hf.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert find_aether_exe("") == str(exe)
    assert find_aether_exe(r"C:\nowhere\aether-hf.exe") == str(exe)
