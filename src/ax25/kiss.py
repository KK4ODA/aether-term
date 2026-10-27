"""
ax25/kiss.py — KISS framing between the computer and a TNC.

Each frame goes as FEND, a command byte (high nibble the TNC port, low
nibble the command: 0 data, 1 TXDELAY, 2 persistence, 3 slot time,
4 TX tail, 5 full duplex), the payload with FEND and FESC escaped, and
FEND.  ``C0 FF C0`` takes the TNC out of KISS mode.
"""

from typing import Callable, List

FEND, FESC, TFEND, TFESC = 0xC0, 0xDB, 0xDC, 0xDD

CMD_DATA = 0x00
CMD_TXDELAY = 0x01
CMD_PERSISTENCE = 0x02
CMD_SLOTTIME = 0x03
CMD_TXTAIL = 0x04
CMD_FULLDUPLEX = 0x05
CMD_RETURN = 0xFF

MAX_FRAME = 2048          # a frame longer than this is noise, not AX.25


def escape(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b == FEND:
            out += bytes((FESC, TFEND))
        elif b == FESC:
            out += bytes((FESC, TFESC))
        else:
            out.append(b)
    return bytes(out)


def encode(payload: bytes, port: int = 0, command: int = CMD_DATA) -> bytes:
    """One KISS frame."""
    return bytes((FEND, ((port & 0x0F) << 4) | (command & 0x0F))) + escape(payload) + bytes((FEND,))


def encode_param(command: int, value: int, port: int = 0) -> bytes:
    return encode(bytes((value & 0xFF,)), port, command)


def tnc_parameters(txdelay_ms: int, persistence: int, slottime_ms: int,
                   port: int = 0) -> bytes:
    """The KISS parameter frames for a channel-access setup (10 ms units)."""
    return (encode_param(CMD_TXDELAY, max(0, min(255, round(txdelay_ms / 10))), port)
            + encode_param(CMD_PERSISTENCE, max(0, min(255, persistence)), port)
            + encode_param(CMD_SLOTTIME, max(0, min(255, round(slottime_ms / 10))), port))


RETURN_FROM_KISS = bytes((FEND, CMD_RETURN, FEND))


class Decoder:
    """Turns a byte stream from the TNC into (port, payload) data frames.

    Bytes can arrive in any pieces (a Bluetooth link hands them over a
    few at a time); call ``feed`` with each piece.  Non-data frames from
    the TNC are ignored.
    """

    def __init__(self, on_frame: Callable[[int, bytes], None]):
        self._on_frame = on_frame
        self._buf = bytearray()
        self._in_frame = False
        self._escape = False

    def feed(self, data: bytes) -> None:
        for b in data:
            if b == FEND:
                if self._in_frame and self._buf:
                    self._deliver(bytes(self._buf))
                self._buf.clear()
                self._in_frame = True
                self._escape = False
                continue
            if not self._in_frame:
                continue                    # noise before the first FEND
            if self._escape:
                self._escape = False
                if b == TFEND:
                    b = FEND
                elif b == TFESC:
                    b = FESC
                # anything else after FESC: protocol error, keep the byte
            elif b == FESC:
                self._escape = True
                continue
            self._buf.append(b)
            if len(self._buf) > MAX_FRAME:
                self._buf.clear()
                self._in_frame = False

    def _deliver(self, frame: bytes) -> None:
        cmd = frame[0]
        if cmd & 0x0F != CMD_DATA:
            return
        self._on_frame(cmd >> 4, frame[1:])


def decode_all(data: bytes) -> List[bytes]:
    """All data payloads in *data* (tests and tools)."""
    out: List[bytes] = []
    Decoder(lambda _port, p: out.append(p)).feed(data)
    return out
