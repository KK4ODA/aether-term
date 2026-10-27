"""
tnc/ble.py — a KISS TNC over Bluetooth Low Energy.

TNCs that offer KISS over BLE in the Mobilinkd way (the Mobilinkd TNC3
and TNC4; reportedly also Benshi-family radios such as the BTech UV-Pro
and Vero VR-N76 / VR-N7600, not yet confirmed) carry the KISS byte
stream on one GATT service with two characteristics: one the TNC sends on
(notifications) and one we write to.  Which is which is read from the
characteristics' properties, so only the service UUID matters.

Bleak is asynchronous; it runs on its own thread with its own event
loop (on Windows that also keeps its WinRT calls off the Qt thread).
Writes are cut to the size the link allows (often 20 bytes).

NOT YET TESTED WITH A RADIO.  The logic is tested against a simulated
Bleak client (tests/test_tnc_transports.py).
"""

import asyncio
import logging
import threading
from typing import List, Optional, Tuple

from tnc.transports import OnBytes, OnLost, Transport, TransportError

log = logging.getLogger(__name__)

# The KISS-over-BLE service (Mobilinkd's, also used by Benshi radios)
KISS_SERVICE_UUID = "00000001-ba2a-46c9-ae49-01b0961f68bb"

CONNECT_TIMEOUT = 20.0
DEFAULT_WRITE_SIZE = 20          # the BLE minimum, if the link does not say


def _bleak():
    try:
        import bleak
        return bleak
    except ImportError:
        raise TransportError("Bluetooth LE needs the bleak package "
                             "(pip install bleak)")


class _Loop:
    """An asyncio event loop on a thread of its own."""

    def __init__(self, name: str):
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever,
                                        daemon=True, name=name)
        self._thread.start()

    def run(self, coro, timeout: Optional[float] = None):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=2)


class BleTransport(Transport):
    def __init__(self, address: str, service_uuid: Optional[str] = None):
        self.address = (address or "").strip()
        self.service_uuid = (service_uuid or KISS_SERVICE_UUID).lower()
        self._loop: Optional[_Loop] = None
        self._client = None
        self._rx_char = None            # we write here
        self._write_size = DEFAULT_WRITE_SIZE
        self._write_response = False
        self._closing = False
        self._lock = threading.Lock()
        self._on_lost: OnLost = lambda why: None

    def describe(self) -> str:
        return f"BLE {self.address}"

    # ── open ───────────────────────────────────────────────────────

    def open(self, on_bytes: OnBytes, on_lost: OnLost) -> None:
        bleak = _bleak()
        if not self.address:
            raise TransportError("no Bluetooth LE device chosen (Settings → "
                                 "Modem Configuration → KISS TNC → Scan)")
        self._on_lost = on_lost
        self._closing = False
        self._loop = _Loop("TNC-BLE")
        try:
            self._loop.run(self._connect(bleak, on_bytes), CONNECT_TIMEOUT + 10)
        except TransportError:
            self._shutdown()
            raise
        except Exception as e:                       # noqa: BLE001
            self._shutdown()
            raise TransportError(f"cannot connect to {self.address} over "
                                 f"Bluetooth LE: {e or type(e).__name__}")
        log.info("TNC: %s connected (write size %d)", self.describe(), self._write_size)

    async def _connect(self, bleak, on_bytes: OnBytes) -> None:
        client = bleak.BleakClient(self.address, disconnected_callback=self._disconnected,
                                   timeout=CONNECT_TIMEOUT)
        await client.connect()
        self._client = client
        service = next((s for s in client.services
                        if str(s.uuid).lower() == self.service_uuid), None)
        if service is None:
            await client.disconnect()
            raise TransportError(
                f"{self.address} has no KISS TNC service ({self.service_uuid}). "
                "Is its KISS TNC turned on?")
        notify = writable = None
        for ch in service.characteristics:
            props = set(ch.properties)
            if notify is None and props & {"notify", "indicate"}:
                notify = ch
            if writable is None and props & {"write", "write-without-response"}:
                writable = ch
        if notify is None or writable is None:
            await client.disconnect()
            raise TransportError(f"{self.address}: the KISS service has no "
                                 "notify and write characteristics")
        self._rx_char = writable
        self._write_response = "write-without-response" not in writable.properties
        size = getattr(writable, "max_write_without_response_size", 0) or 0
        self._write_size = max(DEFAULT_WRITE_SIZE, int(size))

        def got(_ch, data: bytearray) -> None:
            try:
                on_bytes(bytes(data))
            except Exception:
                log.exception("TNC data handler failed")
        await client.start_notify(notify, got)

    def _disconnected(self, _client) -> None:
        if not self._closing:
            log.warning("TNC: %s disconnected", self.describe())
            self._closing = True
            self._on_lost("the Bluetooth LE link dropped")

    # ── write / close ─────────────────────────────────────────────

    def write(self, data: bytes) -> None:
        with self._lock:
            if self._client is None or self._loop is None:
                raise OSError("Bluetooth LE TNC not connected")
            self._loop.run(self._write(bytes(data)), 30)

    async def _write(self, data: bytes) -> None:
        n = self._write_size
        for i in range(0, len(data), n):
            await self._client.write_gatt_char(self._rx_char, data[i:i + n],
                                               response=self._write_response)

    def close(self) -> None:
        self._closing = True
        self._shutdown()

    def _shutdown(self) -> None:
        client, self._client = self._client, None
        loop, self._loop = self._loop, None
        if loop is None:
            return
        if client is not None:
            try:
                loop.run(client.disconnect(), 10)
            except Exception:
                pass
        loop.stop()


def scan(timeout: float = 6.0) -> List[Tuple[str, str, bool]]:
    """(address, name, offers KISS) for the Bluetooth LE devices nearby,
    the ones advertising the KISS service first.  Raises TransportError."""
    bleak = _bleak()
    loop = _Loop("BLE-scan")
    try:
        found = loop.run(bleak.BleakScanner.discover(timeout=timeout, return_adv=True),
                         timeout + 15)
    except Exception as e:                          # noqa: BLE001
        raise TransportError(f"Bluetooth LE scan failed: {e or type(e).__name__}")
    finally:
        loop.stop()
    out = []
    for device, adv in found.values():
        uuids = {u.lower() for u in (getattr(adv, "service_uuids", None) or [])}
        name = getattr(adv, "local_name", None) or device.name or ""
        out.append((device.address, name, KISS_SERVICE_UUID in uuids))
    out.sort(key=lambda d: (not d[2], not d[1], d[1].lower(), d[0]))
    return out
