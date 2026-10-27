"""
ax25/frame.py — AX.25 v2.0 frames: addresses, control field, encode/decode.

Only what a terminal needs: modulo-8 I, S and U frames and UI frames.
The frame here is the AX.25 frame as a KISS TNC passes it, with no flags
and no FCS (the TNC adds and checks those).

Address field: destination, source, then up to 8 digipeaters, 7 bytes
each.  Each callsign character is shifted left one bit and padded with
spaces to 6; the 7th byte is 0b CRRSSSS E — C the command/response bit
(H, "has been repeated", for a digipeater), RR reserved (sent as 11),
SSSS the SSID, E set on the last address.
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List

PID_NO_LAYER3 = 0xF0

_CALL_RE = re.compile(r"^([A-Z0-9]{1,6})(?:-(\d{1,2}))?$")


class FrameError(ValueError):
    """Bytes that are not a frame we can read."""


@dataclass(frozen=True)
class Address:
    call: str
    ssid: int = 0

    @classmethod
    def parse(cls, text: str) -> "Address":
        """``"KK4ODA-7"`` → Address("KK4ODA", 7).  Raises ValueError."""
        m = _CALL_RE.match(text.strip().upper())
        if not m or int(m.group(2) or 0) > 15:
            raise ValueError(f"not an AX.25 callsign: {text!r}")
        return cls(m.group(1), int(m.group(2) or 0))

    def __str__(self) -> str:
        return f"{self.call}-{self.ssid}" if self.ssid else self.call

    def encode(self, cr_or_h: bool, last: bool) -> bytes:
        chars = bytes((ord(c) << 1) for c in self.call.ljust(6))
        b = 0x60 | (self.ssid << 1) | (0x80 if cr_or_h else 0) | (1 if last else 0)
        return chars + bytes([b])

    @classmethod
    def decode(cls, raw: bytes) -> "tuple[Address, bool, bool]":
        """(address, C/H bit, last-address bit) from 7 bytes."""
        if len(raw) != 7:
            raise FrameError("short address")
        call = "".join(chr(b >> 1) for b in raw[:6]).rstrip()
        if not call or not all(c.isalnum() for c in call):
            raise FrameError(f"bad callsign bytes {raw[:6].hex()}")
        b = raw[6]
        return cls(call.upper(), (b >> 1) & 0x0F), bool(b & 0x80), bool(b & 1)


class FrameType(Enum):
    I = "I"
    RR = "RR"
    RNR = "RNR"
    REJ = "REJ"
    SABM = "SABM"
    DISC = "DISC"
    DM = "DM"
    UA = "UA"
    FRMR = "FRMR"
    UI = "UI"


_S_CODES = {FrameType.RR: 0x01, FrameType.RNR: 0x05, FrameType.REJ: 0x09}
_U_CODES = {FrameType.SABM: 0x2F, FrameType.DISC: 0x43, FrameType.DM: 0x0F,
            FrameType.UA: 0x63, FrameType.FRMR: 0x87, FrameType.UI: 0x03}
_S_BY_CODE = {v: k for k, v in _S_CODES.items()}
_U_BY_CODE = {v: k for k, v in _U_CODES.items()}


@dataclass
class Frame:
    dest: Address
    src: Address
    type: FrameType
    command: bool = True            # command (else response)
    pf: bool = False                # poll / final bit
    ns: int = 0                     # I frames
    nr: int = 0                     # I and S frames
    info: bytes = b""
    pid: int = PID_NO_LAYER3
    digis: List[Address] = field(default_factory=list)
    repeated: List[bool] = field(default_factory=list)   # H bit per digi

    # ── encode ────────────────────────────────────────────────────

    def control(self) -> int:
        pf = 0x10 if self.pf else 0
        if self.type is FrameType.I:
            return ((self.nr & 7) << 5) | pf | ((self.ns & 7) << 1)
        if self.type in _S_CODES:
            return ((self.nr & 7) << 5) | pf | _S_CODES[self.type]
        return _U_CODES[self.type] | pf

    def encode(self) -> bytes:
        if len(self.digis) > 8:
            raise ValueError("at most 8 digipeaters")
        out = bytearray()
        out += self.dest.encode(self.command, False)
        out += self.src.encode(not self.command, not self.digis)
        repeated = self.repeated or [False] * len(self.digis)
        for i, d in enumerate(self.digis):
            out += d.encode(repeated[i], i == len(self.digis) - 1)
        out.append(self.control())
        if self.type in (FrameType.I, FrameType.UI):
            out.append(self.pid)
            out += self.info
        elif self.type is FrameType.FRMR:
            out += self.info
        return bytes(out)

    # ── decode ────────────────────────────────────────────────────

    @classmethod
    def decode(cls, raw: bytes) -> "Frame":
        if len(raw) < 15:
            raise FrameError("frame too short")
        dest, dest_c, last = Address.decode(raw[0:7])
        if last:
            raise FrameError("no source address")
        src, src_c, last = Address.decode(raw[7:14])
        pos = 14
        digis: List[Address] = []
        repeated: List[bool] = []
        while not last:
            if len(digis) == 8 or pos + 7 > len(raw):
                raise FrameError("bad digipeater path")
            d, h, last = Address.decode(raw[pos:pos + 7])
            digis.append(d)
            repeated.append(h)
            pos += 7
        if pos >= len(raw):
            raise FrameError("no control field")
        ctl = raw[pos]
        pos += 1
        # AX.25 v2: command has dest C=1, src C=0; v1 frames (both equal)
        # are taken as commands
        command = dest_c or not src_c
        pf = bool(ctl & 0x10)
        f = cls(dest, src, FrameType.UI, command=command, pf=pf,
                digis=digis, repeated=repeated)
        if ctl & 1 == 0:                                  # I frame
            if pos >= len(raw):
                raise FrameError("I frame without PID")
            f.type = FrameType.I
            f.ns = (ctl >> 1) & 7
            f.nr = (ctl >> 5) & 7
            f.pid = raw[pos]
            f.info = bytes(raw[pos + 1:])
        elif ctl & 3 == 1:                                # S frame
            t = _S_BY_CODE.get(ctl & 0x0F)
            if t is None:
                raise FrameError(f"unknown S frame {ctl:#04x}")
            f.type = t
            f.nr = (ctl >> 5) & 7
        else:                                             # U frame
            t = _U_BY_CODE.get(ctl & ~0x10 & 0xFF)
            if t is None:
                raise FrameError(f"unknown U frame {ctl:#04x}")
            f.type = t
            if t is FrameType.UI:
                if pos >= len(raw):
                    raise FrameError("UI frame without PID")
                f.pid = raw[pos]
                f.info = bytes(raw[pos + 1:])
            elif t is FrameType.FRMR:
                f.info = bytes(raw[pos:])
        return f

    # ── helpers ───────────────────────────────────────────────────

    @property
    def path_complete(self) -> bool:
        """Every digipeater has repeated it (or there are none)."""
        return all(self.repeated) if self.digis else True

    def __str__(self) -> str:
        via = (" via " + ",".join(f"{d}{'*' if h else ''}"
                                  for d, h in zip(self.digis, self.repeated))
               if self.digis else "")
        cr = "C" if self.command else "R"
        bits = f" P/F={int(self.pf)}" if self.pf else ""
        seq = ""
        if self.type is FrameType.I:
            seq = f" NS={self.ns} NR={self.nr}"
        elif self.type in _S_CODES:
            seq = f" NR={self.nr}"
        info = f" {len(self.info)}B" if self.info else ""
        return f"{self.src}>{self.dest}{via} {self.type.value}{cr}{seq}{bits}{info}"


def parse_path(digis: List[str]) -> List[Address]:
    """Digipeater callsigns (strings) as addresses; raises ValueError."""
    return [Address.parse(d) for d in digis if d and d.strip()]

