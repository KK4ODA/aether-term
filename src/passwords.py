"""
passwords.py — Secure password storage for Aether Term.

Stores per-station passwords encrypted with Fernet (AES-128-CBC)
derived from a master passphrase.  Optionally uses the OS keyring
for the master key if the `keyring` module is installed.
"""

import json
import base64
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from config import atomic_write, set_aside

log = logging.getLogger(__name__)

# Try to import keyring (optional)
try:
    import keyring as _keyring
    HAS_KEYRING = True
except ImportError:
    HAS_KEYRING = False

# Fernet from cryptography
try:
    from cryptography.fernet import Fernet
    HAS_FERNET = True
except ImportError:
    HAS_FERNET = False


# These identifiers predate the rename to Aether Term.  They are part of the
# key derivation and the OS keyring lookup, so changing them would make every
# saved station password unreadable.  Keep them as they are.
_SERVICE_NAME = "VARA Term"
_KEYRING_KEY = "vterm_master_key"


def _derive_fernet_key(passphrase: str) -> bytes:
    """Derive a Fernet-compatible 32-byte URL-safe base64 key from a passphrase."""
    raw = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"),
                               b"VTermSalt2026", 100_000)
    return base64.urlsafe_b64encode(raw)


class PasswordStore:
    """Encrypted per-station password storage.

    Passwords are stored as {callsign: {password, auth_mode, last_used}}
    encrypted in a JSON file using Fernet.
    """

    def __init__(self, data_dir: Path, master_passphrase: str = "VARATermDefault"):
        self._path = data_dir / "passwords.enc"
        self._passwords: Dict[str, dict] = {}
        self._fernet: Optional[object] = None
        self.load_error = ""      # set when passwords.enc could not be read

        # Resolve the master key
        master = self._get_or_create_master(master_passphrase)
        if HAS_FERNET:
            self._fernet = Fernet(_derive_fernet_key(master))
        else:
            log.warning("cryptography not installed — passwords stored in PLAINTEXT")

        self._load()

    def _get_or_create_master(self, default: str) -> str:
        """Try to retrieve/store the master key in the OS keyring."""
        if HAS_KEYRING:
            try:
                stored = _keyring.get_password(_SERVICE_NAME, _KEYRING_KEY)
                if stored:
                    return stored
                # First run: store the default passphrase
                _keyring.set_password(_SERVICE_NAME, _KEYRING_KEY, default)
                return default
            except Exception as e:
                log.warning(f"Keyring access failed: {e}")
        return default

    def _load(self):
        if not self._path.exists():
            self._passwords = {}
            return
        try:
            raw = self._path.read_bytes()
            if self._fernet:
                data = self._fernet.decrypt(raw)
                self._passwords = json.loads(data.decode("utf-8"))
            else:
                self._passwords = json.loads(raw.decode("utf-8"))
            if not isinstance(self._passwords, dict):
                raise ValueError("not a password table")
            log.info(f"Loaded {len(self._passwords)} saved passwords")
        except Exception as e:      # InvalidToken, bad JSON, missing cryptography...
            # The next save would replace the file with only the new
            # entry: move it aside so the saved passwords can be recovered.
            self._passwords = {}
            kept = set_aside(self._path)
            self.load_error = (f"Saved passwords could not be read ({e or type(e).__name__}); "
                               f"kept as {kept.name}")
            log.error(self.load_error)

    def _save(self):
        try:
            data = json.dumps(self._passwords, indent=2).encode("utf-8")
            if self._fernet:
                data = self._fernet.encrypt(data)
            atomic_write(self._path, data)
        except OSError as e:
            log.error(f"Failed to save passwords: {e}")

    # ── Public API ──────────────────────────────────────────────────

    @staticmethod
    def _make_key(callsign: str, operator: str = "") -> str:
        """Build the storage key.

        With *operator*: ``"KK2ODA@KK4ODA-5"`` (per-operator composite).
        Without:          ``"KK4ODA-5"``        (legacy / shared).
        """
        target = callsign.upper().strip()
        if operator:
            return f"{operator.upper().strip()}@{target}"
        return target

    def _find(self, callsign: str, operator: str = "") -> Optional[dict]:
        """The stored entry for a target and operator, or None.

        Lookup order (first match wins):
          1. OPERATOR@TARGET, then OPERATOR@BASE_TARGET
          2. the same with the operator's base call (no SSID), then any
             other SSID of it: the BBS knows the operator by base call
          3. BASE_TARGET, then TARGET  (legacy, no operator)
        """
        target = callsign.upper().strip()
        base_target = target.split("-")[0]
        targets = [target] if base_target == target else [target, base_target]

        if operator:
            op = operator.upper().strip()
            base_op = op.split("-")[0]
            ops = [op] if base_op == op else [op, base_op]
            for o in ops:
                for t in targets:
                    entry = self._passwords.get(f"{o}@{t}")
                    if entry:
                        return entry
            for t in targets:
                for key in sorted(self._passwords):
                    o, sep, kt = key.partition("@")
                    if sep and kt == t and o.split("-")[0] == base_op:
                        return self._passwords[key]

        for t in reversed(targets):          # legacy: base first
            entry = self._passwords.get(t)
            if entry:
                return entry
        return None

    def get_password(self, callsign: str,
                     operator: str = "") -> Optional[str]:
        """Return the stored password for a callsign, or None (see _find)."""
        entry = self._find(callsign, operator)
        return entry.get("password") if entry else None

    def set_password(self, callsign: str, password: str,
                     auth_mode: str = "HMAC-SHA256",
                     operator: str = ""):
        """Store or update a password for a callsign."""
        key = self._make_key(callsign, operator)
        self._passwords[key] = {
            "password": password,
            "auth_mode": auth_mode,
            "last_used": "",
        }
        self._save()
        log.info(f"Password saved for {key}")

    def remove_by_key(self, key: str):
        """Remove a password by its raw storage key (used by the dialog)."""
        if key in self._passwords:
            del self._passwords[key]
            self._save()

    def update_last_used(self, callsign: str, operator: str = ""):
        """Update the last-used timestamp of the entry get_password uses."""
        entry = self._find(callsign, operator)
        if entry:
            entry["last_used"] = datetime.now(timezone.utc).isoformat()
            self._save()

    def get_all(self) -> Dict[str, dict]:
        """Return all stored entries {key: {password, auth_mode, last_used}}.

        Keys may be ``"TARGET"`` (legacy) or ``"OPERATOR@TARGET"``
        (composite).
        """
        return dict(self._passwords)
