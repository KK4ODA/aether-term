"""
vara/omnirig.py — OmniRig PTT client for Aether Term (Windows).

All COM calls run on the client's I/O thread (a single-threaded
apartment, with its messages pumped) to avoid cross-apartment proxy
issues.  Used when Aether Term keys the radio: VARA HF, or Aether HF set
to "host program" keying.

Adapted from the VARA BBS OmniRig module.
"""

import logging
import time

from vara.rig_client import RigClient

log = logging.getLogger(__name__)

# OmniRig PTT constants
PM_RX = 0x00200000   # receive (PTT off)
PM_TX = 0x00400000   # transmit (PTT on)

ST_ONLINE = 4        # rig status at or above this: radio answering
STATUS_NAMES = {
    0: "NOT_CONFIGURED",
    1: "DISABLED",
    2: "PORT_BUSY",
    3: "NOT_RESPONDING",
    4: "ONLINE",
    5: "TRANSCEIVE",
}


class OmniRigClient(RigClient):
    START_TIMEOUT = 15.0
    POLL = 0.1

    def __init__(self, rig_number: int = 1):
        if rig_number not in (1, 2):
            raise ValueError("rig_number must be 1 or 2")
        super().__init__()
        self._rig_number = rig_number
        self.NAME = f"OmniRig-Rig{rig_number}"
        self._pythoncom = None
        self._rig = None

    def _open(self) -> None:
        rig_num = self._rig_number
        try:
            import win32com.client
            import pythoncom
        except ImportError:
            raise RuntimeError("pywin32 is required for OmniRig PTT. "
                               "Install with: pip install pywin32")
        pythoncom.CoInitialize()
        self._pythoncom = pythoncom
        try:
            omnirig = win32com.client.Dispatch("OmniRig.OmniRigX")
        except Exception as e:
            raise RuntimeError(
                "Cannot connect to OmniRig COM server. "
                f"Is OmniRig installed and running? Error: {e}")
        self._rig = omnirig.Rig1 if rig_num == 1 else omnirig.Rig2

        # Wait for OmniRig to establish radio communication
        log.info(f"OmniRig Rig{rig_num}: waiting for radio to come online...")
        last_status = -1
        for _ in range(50):  # up to ~5 seconds
            pythoncom.PumpWaitingMessages()
            try:
                status = self._rig.Status
                if status != last_status:
                    log.info(f"OmniRig Rig{rig_num} status: "
                             f"{STATUS_NAMES.get(status, f'UNKNOWN({status})')}")
                    last_status = status
                if status >= ST_ONLINE:
                    log.info(f"OmniRig Rig{rig_num} ONLINE")
                    return
            except Exception as e:
                log.warning(f"OmniRig Rig{rig_num} status poll: {e}")
            time.sleep(0.1)
        log.warning(f"OmniRig Rig{rig_num} not online after 5s. "
                    "Check OmniRig setup: rig type, COM port, baud rate.")

    def _idle(self) -> None:
        self._pythoncom.PumpWaitingMessages()

    def _key(self, on: bool) -> bool:
        value = PM_TX if on else PM_RX
        self._rig.Tx = value
        self._pythoncom.PumpWaitingMessages()
        time.sleep(0.05)
        self._pythoncom.PumpWaitingMessages()
        log.info(f"OmniRig Rig{self._rig_number} PTT -> 0x{value:08X}")
        return True

    def _close(self) -> None:
        if self._pythoncom is None:
            return
        try:
            if self._rig is not None:
                self._rig.Tx = PM_RX            # safety release
                self._pythoncom.PumpWaitingMessages()
        finally:
            self._rig = None
            self._pythoncom.CoUninitialize()
            self._pythoncom = None
