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
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

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
            log.info(f"Loaded {len(self._passwords)} saved passwords")
        except Exception as e:
            log.warning(f"Failed to load passwords: {e}")
            self._passwords = {}

    def _save(self):
        try:
            data = json.dumps(self._passwords, indent=2).encode("utf-8")
            if self._fernet:
                data = self._fernet.encrypt(data)
            self._path.write_bytes(data)
        except Exception as e:
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

    def get_password(self, callsign: str,
                     operator: str = "") -> Optional[str]:
        """Return the stored password for a callsign, or None.

        Lookup order (first match wins):
          1. OPERATOR@TARGET       (composite, exact target)
          2. OPERATOR@BASE_TARGET  (composite, SSID-stripped target)
          3. BASE_TARGET           (legacy, SSID-stripped)
          4. TARGET                (legacy, exact)
        """
        target = callsign.upper().strip()
        base_target = target.split("-")[0]

        if operator:
            op = operator.upper().strip()
            # 1. composite exact
            entry = self._passwords.get(f"{op}@{target}")
            if entry:
                return entry.get("password")
            # 2. composite base
            if base_target != target:
                entry = self._passwords.get(f"{op}@{base_target}")
                if entry:
                    return entry.get("password")

        # 3. legacy base
        entry = self._passwords.get(base_target)
        if entry:
            return entry.get("password")
        # 4. legacy exact
        if base_target != target:
            entry = self._passwords.get(target)
            if entry:
                return entry.get("password")
        return None

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

    def remove_password(self, callsign: str, operator: str = ""):
        key = self._make_key(callsign, operator)
        if key in self._passwords:
            del self._passwords[key]
            self._save()

    def remove_by_key(self, key: str):
        """Remove a password by its raw storage key (used by the dialog)."""
        if key in self._passwords:
            del self._passwords[key]
            self._save()

    def update_last_used(self, callsign: str, operator: str = ""):
        """Update last-used timestamp, searching composite then legacy keys."""
        target = callsign.upper().strip()
        base_target = target.split("-")[0]

        entry = None
        if operator:
            op = operator.upper().strip()
            entry = self._passwords.get(f"{op}@{target}")
            if not entry and base_target != target:
                entry = self._passwords.get(f"{op}@{base_target}")
        if not entry:
            entry = self._passwords.get(base_target)
        if not entry and base_target != target:
            entry = self._passwords.get(target)

        if entry:
            entry["last_used"] = datetime.now(timezone.utc).isoformat()
            self._save()

    def get_all(self) -> Dict[str, dict]:
        """Return all stored entries {key: {password, auth_mode, last_used}}.

        Keys may be ``"TARGET"`` (legacy) or ``"OPERATOR@TARGET"``
        (composite).
        """
        return dict(self._passwords)

    def has_password(self, callsign: str, operator: str = "") -> bool:
        return self.get_password(callsign, operator) is not None
