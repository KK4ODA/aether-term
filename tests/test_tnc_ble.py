"""KISS over Bluetooth LE, against a simulated Bleak library.

No radio here: the fake client stands in for a BLE TNC with the
KISS-over-BLE service.  It splits what it sends into 20-byte
notifications as a real BLE link does.
"""

import asyncio
import types

import pytest

from ax25 import kiss
from ax25.frame import Address, Frame
from ax25.link import DataLink, LinkListener
from conftest import pump
from fake_tnc import FAST
from tnc import ble
from tnc.transports import TransportError

SVC = ble.KISS_SERVICE_UUID
TX_UUID = "00000002-ba2a-46c9-ae49-01b0961f68bb"
RX_UUID = "00000003-ba2a-46c9-ae49-01b0961f68bb"


class Char:
    def __init__(self, uuid, props, size=0):
        self.uuid, self.properties, self.max_write_without_response_size = uuid, props, size


class Service:
    def __init__(self, uuid, chars):
        self.uuid, self.characteristics = uuid, chars


class FakeClient:
    instances = []
    services_offered = None
    write_size = 0
    fail_connect = None

    def __init__(self, address, disconnected_callback=None, timeout=30, **_):
        self.address = address
        self.on_disc = disconnected_callback
        self.writes = []
        self.notify_cb = None
        self.connected = False
        self.peer = None                    # bytes we write go here too
        FakeClient.instances.append(self)
        self.services = (FakeClient.services_offered if FakeClient.services_offered is not None
                         else [Service("0000180a-0000-1000-8000-00805f9b34fb", []),
                               Service(SVC, [Char(TX_UUID, ["notify"]),
                                             Char(RX_UUID, ["write-without-response", "write"],
                                                  FakeClient.write_size)])])

    async def connect(self):
        if FakeClient.fail_connect:
            raise FakeClient.fail_connect
        self.connected = True

    async def start_notify(self, ch, cb):
        assert {"notify", "indicate"} & set(ch.properties)
        self.notify_cb = cb

    async def write_gatt_char(self, ch, data, response=None):
        self.writes.append((ch.uuid, bytes(data), response))
        if self.peer:
            self.peer(bytes(data))

    async def disconnect(self):
        self.connected = False

    def push(self, data: bytes, size=20):
        """The TNC sends, in notifications of *size* bytes."""
        for i in range(0, len(data), size):
            self.notify_cb(None, bytearray(data[i:i + size]))

    def drop(self):
        self.on_disc(self)


class FakeScanner:
    @staticmethod
    async def discover(timeout=5.0, return_adv=False):
        def dev(addr, name):
            return types.SimpleNamespace(address=addr, name=name)

        def adv(name, uuids):
            return types.SimpleNamespace(local_name=name, service_uuids=uuids)
        return {"1": (dev("11:11", "Headphones"), adv("Headphones", [])),
                "2": (dev("22:22", None), adv("VR-N76", [SVC])),
                "3": (dev("33:33", None), adv(None, []))}


@pytest.fixture(autouse=True)
def fake_bleak(monkeypatch):
    FakeClient.instances.clear()
    FakeClient.services_offered = None
    FakeClient.write_size = 0
    FakeClient.fail_connect = None
    mod = types.SimpleNamespace(BleakClient=FakeClient, BleakScanner=FakeScanner)
    monkeypatch.setattr(ble, "_bleak", lambda: mod)
    return mod


def _open(address="22:22"):
    got, lost = bytearray(), []
    t = ble.BleTransport(address)
    t.open(got.extend, lost.append)
    return t, got, lost, FakeClient.instances[-1]


def test_writes_are_cut_to_the_link_size_without_response():
    t, got, lost, c = _open()
    try:
        frame = kiss.encode(bytes(range(50)))
        t.write(frame)
        assert [len(w[1]) for w in c.writes] == [20, 20, len(frame) - 40]
        assert b"".join(w[1] for w in c.writes) == frame
        assert all(w[0] == RX_UUID and w[2] is False for w in c.writes)
    finally:
        t.close()


def test_a_larger_link_size_is_used_when_offered():
    FakeClient.write_size = 180
    t, got, lost, c = _open()
    try:
        t.write(bytes(300))
        assert [len(w[1]) for w in c.writes] == [180, 120]
    finally:
        t.close()


def test_write_with_response_when_that_is_all_the_tnc_offers():
    FakeClient.services_offered = [Service(SVC, [Char(TX_UUID, ["indicate"]),
                                                 Char(RX_UUID, ["write"])])]
    t, got, lost, c = _open()
    try:
        t.write(b"x")
        assert c.writes[0][2] is True
    finally:
        t.close()


def test_notifications_arrive_as_bytes():
    t, got, lost, c = _open()
    try:
        c.push(b"\xc0\x00" + bytes(range(60)) + b"\xc0")
        assert bytes(got) == b"\xc0\x00" + bytes(range(60)) + b"\xc0"
    finally:
        t.close()


def test_link_dropping_is_reported_once_and_close_is_not_a_loss():
    t, got, lost, c = _open()
    c.drop()
    c.drop()
    assert lost == ["the Bluetooth LE link dropped"]
    t.close()
    t2, got2, lost2, c2 = _open()
    t2.close()
    assert lost2 == []


def test_device_without_the_kiss_service_is_refused():
    FakeClient.services_offered = [Service("0000180a-0000-1000-8000-00805f9b34fb", [])]
    with pytest.raises(TransportError, match="no KISS TNC service"):
        _open()
    assert not FakeClient.instances[-1].connected


def test_a_different_service_uuid_can_be_set():
    other = "0000aaaa-0000-1000-8000-00805f9b34fb"
    FakeClient.services_offered = [Service(other.upper(), [Char("a", ["notify"]),
                                                           Char("b", ["write"])])]
    t = ble.BleTransport("22:22", service_uuid=other)
    t.open(lambda b: None, lambda w: None)
    t.close()


def test_connect_failure_and_no_device():
    FakeClient.fail_connect = asyncio.TimeoutError()
    with pytest.raises(TransportError, match="cannot connect to 22:22"):
        _open()
    with pytest.raises(TransportError, match="no Bluetooth LE device chosen"):
        ble.BleTransport("").open(lambda b: None, lambda w: None)


def test_bleak_missing_is_explained(monkeypatch):
    monkeypatch.undo()
    import builtins
    real = builtins.__import__

    def no_bleak(name, *a, **k):
        if name == "bleak":
            raise ImportError("no bleak")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_bleak)
    with pytest.raises(TransportError, match="pip install bleak"):
        ble.BleTransport("22:22").open(lambda b: None, lambda w: None)


def test_scan_lists_kiss_tncs_first():
    found = ble.scan(timeout=0.1)
    assert found[0] == ("22:22", "VR-N76", True)
    assert ("11:11", "Headphones", False) in found
    assert found[-1] == ("33:33", "", False)


# ── A whole session over (simulated) Bluetooth LE ──────────────────

class _Answer(LinkListener):
    def __init__(self):
        self.text = bytearray()

    def link_connected(self, remote, digis):
        self.link.send(b"Welcome over BLE\r\n> ")

    def link_data(self, data):
        self.text += data


def test_session_through_a_ble_tnc(qapp):
    from vara.kiss_modem import KissModem
    answer = _Answer()
    holder = {}

    def to_modem(frame: Frame):
        holder["client"].push(kiss.encode(frame.encode()))      # 20-byte notifications

    bbs = DataLink(Address.parse("KK4ODA-7"), to_modem, answer, FAST, accept_incoming=True)
    answer.link = bbs
    bbs.start()
    dec = kiss.Decoder(lambda port, p: bbs.receive(Frame.decode(p)))
    m = KissModem(ble.BleTransport("22:22"), FAST)
    got, states = [], []
    m.data_received.connect(got.append)
    m.state_changed.connect(lambda s: states.append(s.name))
    try:
        m.connect_to_modem()
        assert pump(qapp, until=lambda: m.state.name == "MODEM_CONNECTED", timeout=10)
        client = FakeClient.instances[-1]
        client.peer = dec.feed                 # what the modem writes reaches the BBS
        holder["client"] = client
        m.initialize_modem("N0CALL")
        m.rf_connect("N0CALL", "KK4ODA-7")
        assert pump(qapp, until=lambda: "".join(got) == "Welcome over BLE\r\n> ", timeout=10)
        m.send_data("x" * 300 + "\r\n")
        assert pump(qapp, until=lambda: len(answer.text) == 302, timeout=10)
        assert all(len(w[1]) <= 20 for w in client.writes)
    finally:
        m.disconnect_from_modem()
        bbs.stop()
