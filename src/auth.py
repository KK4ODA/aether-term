"""
auth.py — HMAC-SHA256 authentication for Aether Term.

Monitors the incoming data stream for BBS auth challenges and
automatically computes + sends the HMAC response.
"""

import hashlib
import hmac
import logging
import re
from enum import Enum, auto
from typing import Optional

log = logging.getLogger(__name__)

# Regex for the auth challenge line
AUTH_CHALLENGE_RE = re.compile(
    r"^;AUTH\s+HMAC-SHA256\s+([0-9a-fA-F]{32})\s*$"
)
AUTH_OK_RE = re.compile(r"^;AUTH\s+OK", re.IGNORECASE)
AUTH_FAIL_RE = re.compile(r"^;AUTH\s+FAIL", re.IGNORECASE)

# Regex for Winlink registration challenge
WLREG_NONCE_RE = re.compile(
    r"^;WLREG\s+NONCE\s+([0-9a-fA-F]{32})\s*$"
)


class AuthState(Enum):
    IDLE = auto()
    AWAITING_RESULT = auto()


def encrypt_wlreg_password(bbs_password: str, nonce_hex: str,
                           winlink_password: str) -> str:
    """Encrypt a Winlink password for the WLREG protocol.

    Uses the shared BBS password + nonce to derive a key, then XOR.
    Returns the encrypted password as a hex string.
    """
    key = hashlib.sha256(
        (bbs_password + nonce_hex).encode("utf-8")
    ).digest()
    pw_bytes = winlink_password.encode("utf-8")
    full_key = key * ((len(pw_bytes) // len(key)) + 1)
    encrypted = bytes(pb ^ kb for pb, kb in zip(pw_bytes, full_key))
    return encrypted.hex()


def compute_hmac_response(password: str, nonce_hex: str) -> str:
    """Compute HMAC-SHA256(password, nonce_bytes).

    Args:
        password:  Plaintext password (stored locally, never transmitted)
        nonce_hex: 32-char hex nonce from the ;AUTH HMAC-SHA256 line

    Returns:
        64-char lowercase hex string
    """
    nonce_bytes = bytes.fromhex(nonce_hex)
    return hmac.new(
        password.encode("utf-8"),
        nonce_bytes,
        hashlib.sha256,
    ).hexdigest()


class AuthInterceptor:
    """Scans incoming lines for BBS auth protocol messages.

    Usage:
        interceptor = AuthInterceptor(password_store)
        for each incoming line:
            action = interceptor.process_line(line, target_callsign)
            if action.send_response:
                send action.response_text on data socket
            if action.suppress:
                don't display this line in terminal
            if action.display_text:
                show action.display_text instead
    """

    def __init__(self):
        self._state = AuthState.IDLE

    def reset(self):
        self._state = AuthState.IDLE

    def process_line(self, line: str, password: Optional[str],
                     auto_respond: bool = True,
                     show_protocol: bool = False
                     ) -> "AuthAction":
        """Process one line of incoming BBS data.

        Returns an AuthAction describing what the caller should do.
        """
        stripped = line.strip()

        # ── Check for challenge ────────────────────────────────────
        match = AUTH_CHALLENGE_RE.match(stripped)
        if match:
            nonce = match.group(1)
            log.info(f"Auth challenge received, nonce={nonce[:8]}...")

            if password and auto_respond:
                # Compute and auto-respond
                hmac_response = compute_hmac_response(password, nonce)
                self._state = AuthState.AWAITING_RESULT
                return AuthAction(
                    suppress=not show_protocol,
                    send_response=f";AUTH {hmac_response}\r\n",
                    display_text="[AUTH] Challenge received — responding automatically..." if not show_protocol else None,
                    is_auth_event=True,
                )
            else:
                # No password — show challenge, let user type manually
                self._state = AuthState.AWAITING_RESULT
                return AuthAction(
                    suppress=False,
                    display_text=f"[AUTH] No saved password — manual auth required\n{line}",
                    is_auth_event=True,
                    is_warning=True,
                )

        # ── Check for "Enter password" prompt (suppress during auto-auth)
        if self._state == AuthState.AWAITING_RESULT:
            if "Enter password" in stripped or stripped == "> " or stripped == ">":
                return AuthAction(
                    suppress=not show_protocol and password is not None,
                    is_auth_event=True,
                )

        # ── Check for auth result ──────────────────────────────────
        if AUTH_OK_RE.match(stripped):
            self._state = AuthState.IDLE
            return AuthAction(
                suppress=False,
                display_text="[AUTH] Authentication successful ✓",
                is_auth_event=True,
                is_success=True,
            )

        if AUTH_FAIL_RE.match(stripped):
            self._state = AuthState.IDLE
            return AuthAction(
                suppress=False,
                display_text="[AUTH] Authentication FAILED ✗ — check saved password",
                is_auth_event=True,
                is_error=True,
            )

        # ── Check for WLREG challenge ─────────────────────────────
        wlreg_match = WLREG_NONCE_RE.match(stripped)
        if wlreg_match:
            wlreg_nonce = wlreg_match.group(1)
            log.info(f"WLREG challenge received, nonce={wlreg_nonce[:8]}...")
            return AuthAction(
                suppress=True,
                display_text="[WLREG] Winlink registration challenge received",
                is_auth_event=True,
                wlreg_nonce=wlreg_nonce,
            )

        # ── Not an auth line ───────────────────────────────────────
        return AuthAction()


class AuthAction:
    """Describes what the caller should do after processing a line."""

    def __init__(self, *,
                 suppress: bool = False,
                 send_response: Optional[str] = None,
                 display_text: Optional[str] = None,
                 is_auth_event: bool = False,
                 is_success: bool = False,
                 is_error: bool = False,
                 is_warning: bool = False,
                 wlreg_nonce: Optional[str] = None):
        self.suppress = suppress
        self.send_response = send_response
        self.display_text = display_text
        self.is_auth_event = is_auth_event
        self.is_success = is_success
        self.is_error = is_error
        self.is_warning = is_warning
        self.wlreg_nonce = wlreg_nonce  # set when BBS sends ;WLREG NONCE
