"""
tnc/transports.py — the byte link between Aether Term and a KISS TNC.

A transport opens, hands every byte it receives to ``on_bytes`` (on its
own thread, in whatever pieces they come), writes bytes, and calls
``on_lost`` once if the link goes away by itself (radio switched off,
out of Bluetooth range, cable pulled).

    SerialTransport  a COM port: a USB cable, or a Bluetooth Classic radio
                     once paired in Windows (the TH-D74/D75 appear as
                     "Standard Serial over Bluetooth link (COMn)")
    TcpTransport     KISS over TCP: Direwolf (port 8001), network TNCs
    BleTransport     Bluetooth Low Energy (tnc/ble.py)
"""

import logging
import socket
import threading
from typing import Callable, List, Optional, Tuple

log = logging.getLogger(__name__)

OnBytes = Callable[[bytes], None]
OnLost = Callable[[str], None]


class TransportError(Exception):
    """The link to the TNC could not be opened."""


class Transport:
    def open(self, on_bytes: OnBytes, on_lost: OnLost) -> None:
        raise NotImplementedError

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def describe(self) -> str:
        raise NotImplementedError


class _ThreadedReader(Transport):
    """Shared by the serial and TCP links: a reader thread, a write lock."""

    def __init__(self):
        self._lock = threading.Lock()
        self._closing = False
        self._thread: Optional[threading.Thread] = None
        self._on_bytes: OnBytes = lambda b: None
        self._on_lost: OnLost = lambda why: None

    def _start_reader(self, on_bytes: OnBytes, on_lost: OnLost) -> None:
        self._on_bytes, self._on_lost = on_bytes, on_lost
        self._closing = False
        self._thread = threading.Thread(target=self._read_loop, daemon=True,
                                        name=f"TNC-{self.describe()}")
        self._thread.start()

    def _read_loop(self) -> None:
        why = "closed"
        while not self._closing:
            try:
                data = self._read()
            except Exception as e:                  # noqa: BLE001 — any I/O failure ends the link
                why = str(e) or type(e).__name__
                break
            if data is None:
                why = "the other end closed the connection"
                break
            if data:
                try:
                    self._on_bytes(data)
                except Exception:
                    log.exception("TNC data handler failed")
        if not self._closing:
            log.warning("TNC link %s lost: %s", self.describe(), why)
            self._on_lost(why)

    def _read(self) -> Optional[bytes]:
        """Bytes (b"" when none yet), or None at end of stream."""
        raise NotImplementedError


class SerialTransport(_ThreadedReader):
    def __init__(self, port: str, baud: int = 9600):
        super().__init__()
        self.port, self.baud = port, int(baud)
        self._ser = None

    def describe(self) -> str:
        return self.port

    def open(self, on_bytes: OnBytes, on_lost: OnLost) -> None:
        if not self.port:
            raise TransportError("no serial port chosen (Settings → Modem "
                                 "Configuration → KISS TNC)")
        try:
            import serial
        except ImportError:
            raise TransportError("pyserial is not installed (pip install pyserial)")
        try:
            # Bluetooth serial ports can take several seconds to open
            self._ser = serial.Serial(self.port, self.baud, timeout=0.2,
                                      write_timeout=10)
        except (serial.SerialException, OSError, ValueError) as e:
            raise TransportError(f"cannot open {self.port}: {e}")
        self._start_reader(on_bytes, on_lost)
        log.info("TNC: %s open at %d baud", self.port, self.baud)

    def _read(self) -> Optional[bytes]:
        ser = self._ser
        if ser is None:
            return None
        return ser.read(ser.in_waiting or 1)

    def write(self, data: bytes) -> None:
        with self._lock:
            if self._ser is None:
                raise OSError("serial port not open")
            self._ser.write(data)

    def close(self) -> None:
        self._closing = True
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)


class TcpTransport(_ThreadedReader):
    def __init__(self, host: str = "127.0.0.1", port: int = 8001):
        super().__init__()
        self.host, self.port = host or "127.0.0.1", int(port)
        self._sock: Optional[socket.socket] = None

    def describe(self) -> str:
        return f"{self.host}:{self.port}"

    def open(self, on_bytes: OnBytes, on_lost: OnLost) -> None:
        try:
            s = socket.create_connection((self.host, self.port), timeout=10)
        except OSError as e:
            raise TransportError(f"cannot connect to the TNC at {self.describe()}: {e}")
        s.settimeout(0.5)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = s
        self._start_reader(on_bytes, on_lost)
        log.info("TNC: connected to %s", self.describe())

    def _read(self) -> Optional[bytes]:
        s = self._sock
        if s is None:
            return None
        try:
            data = s.recv(4096)
        except socket.timeout:
            return b""
        return data or None

    def write(self, data: bytes) -> None:
        with self._lock:
            if self._sock is None:
                raise OSError("TNC connection not open")
            self._sock.sendall(data)

    def close(self) -> None:
        self._closing = True
        s, self._sock = self._sock, None
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            s.close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)


def list_serial_ports() -> List[Tuple[str, str]]:
    """(device, description) for each serial port, Bluetooth ones included."""
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    ports = []
    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        ports.append((p.device, p.description or p.device))
    return ports


# The ``kiss_link`` setting
LINK_SERIAL = "serial"
LINK_BLE = "ble"
LINK_TCP = "tcp"


def make_transport(config) -> Transport:
    """The transport the KISS TNC settings ask for."""
    link = config.get("kiss_link", LINK_SERIAL)
    if link == LINK_TCP:
        return TcpTransport(config.get("kiss_tcp_host", "127.0.0.1"),
                            config.get("kiss_tcp_port", 8001))
    if link == LINK_BLE:
        from tnc.ble import BleTransport
        return BleTransport(config.get("kiss_ble_address", ""),
                            service_uuid=config.get("kiss_ble_service", "") or None)
    return SerialTransport(config.get("kiss_serial_port", ""),
                           config.get("kiss_serial_baud", 9600))
