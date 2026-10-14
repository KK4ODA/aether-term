"""
vara/flrig.py — FLrig PTT client for Aether Term.

Talks to FLrig's XML-RPC server (default port 12345), which FLrig shares
between programs.  FLrig must be running before Aether Term connects.
"""

import http.client
import logging
import time
import xmlrpc.client
from typing import Optional

from vara.rig_client import RigClient

log = logging.getLogger(__name__)

# FLrig default XML-RPC port
DEFAULT_FLRIG_PORT = 12345
CALL_TIMEOUT = 4.0     # per XML-RPC call; under RigClient.CMD_TIMEOUT


class _TimeoutTransport(xmlrpc.client.Transport):
    """An XML-RPC transport whose connections time out.

    (The alternative, socket.setdefaulttimeout, is process-wide.)
    """

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = CALL_TIMEOUT
        return conn


class FLrigClient(RigClient):
    NAME = "FLrig"
    # three attempts of up to CALL_TIMEOUT each, 1 s apart
    START_TIMEOUT = 16.0

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_FLRIG_PORT):
        super().__init__()
        self._host = host
        self._port = port
        self._proxy: Optional[xmlrpc.client.ServerProxy] = None

    def _open(self) -> None:
        url = f"http://{self._host}:{self._port}"
        for attempt in range(3):
            try:
                self._proxy = xmlrpc.client.ServerProxy(
                    url, allow_none=True, transport=_TimeoutTransport())
                version = self._proxy.main.get_version()
                log.info(f"Connected to FLrig at {url} (version: {version})")
                return
            except (OSError, http.client.HTTPException, xmlrpc.client.Error) as e:
                self._proxy = None
                if attempt == 2:
                    raise RuntimeError(
                        f"Cannot connect to FLrig at {url}. "
                        f"Is FLrig running?  Error: {e}")
                log.info(f"FLrig connect attempt {attempt + 1} failed, retrying...")
                time.sleep(1.0)

    def _key(self, on: bool) -> bool:
        self._proxy.rig.set_ptt(int(on))
        log.info(f"FLrig rig.set_ptt({int(on)})")
        # Read the state back to confirm the rig followed
        try:
            actual = int(self._proxy.rig.get_ptt())
        except (OSError, http.client.HTTPException, xmlrpc.client.Error) as e:
            log.warning(f"FLrig PTT read-back failed: {e}")
            return True
        if actual != int(on):
            log.warning(f"FLrig PTT verify: expected {int(on)}, got {actual}")
            return False
        return True

    def _close(self) -> None:
        if self._proxy is not None:
            try:
                self._proxy.rig.set_ptt(0)
            finally:
                self._proxy = None
