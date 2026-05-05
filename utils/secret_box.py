"""Encryption-at-rest helpers for sensitive strategy fields.

Used to protect webhook_secret and webhook_hmac_key on strategies_v2 rows.
Plaintext only ever appears in memory at:
  - strategy creation (one-time UI display)
  - secret rotation
  - signature verification on incoming webhook

Key derivation:
    The Fernet key is derived from APP_KEY using HKDF-SHA256 with a fixed,
    application-scoped info string. APP_KEY is already the platform's
    cryptographic root (signs Flask sessions, CSRF tokens) and is rotated
    via the existing utils/env_check.py flow on platform upgrades.

Format:
    encrypt_at_rest('hello') → 'fern1:gAAAAAB...'
    The 'fern1:' prefix is a version tag — future key rotations can be
    transparently introduced by accepting older prefixes during a migration
    window.

Why module-level lazy init:
    HKDF derivation costs ~0.1ms; we cache the derived Fernet instance after
    first use. APP_KEY changes require an app restart anyway, so caching is
    safe.
"""

from __future__ import annotations

import os
import threading
from base64 import urlsafe_b64encode
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Application-scoped HKDF info string. Changing this would invalidate every
# encrypted value already stored in the DB — treat as a constant.
_HKDF_INFO = b"openalgo.strategy.v2.secret_box.fern1"

# Salt for HKDF. Static is acceptable here because the input keying material
# (APP_KEY) is already a high-entropy hex string of 32 bytes (per the install
# scripts that generate it via secrets.token_hex(32)).
_HKDF_SALT = b"openalgo-fern1-salt"

_VERSION_TAG = "fern1:"

_lock = threading.Lock()
_fernet: Optional[Fernet] = None
_cached_app_key: Optional[str] = None


class SecretBoxConfigError(RuntimeError):
    """Raised when APP_KEY is missing or unusable."""


def _derive_fernet() -> Fernet:
    """Return a Fernet instance keyed off the current process's APP_KEY.

    Caches per-process; recomputes if APP_KEY changes (which only happens at
    app restart in normal operation).
    """
    global _fernet, _cached_app_key

    app_key = os.getenv("APP_KEY")
    if not app_key:
        raise SecretBoxConfigError(
            "APP_KEY environment variable is required to encrypt strategy secrets at rest"
        )

    with _lock:
        if _fernet is not None and _cached_app_key == app_key:
            return _fernet

        # HKDF-SHA256 produces a 32-byte key; Fernet wants url-safe base64 of 32 bytes.
        kdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_HKDF_SALT,
            info=_HKDF_INFO,
        )
        derived = kdf.derive(app_key.encode("utf-8"))
        _fernet = Fernet(urlsafe_b64encode(derived))
        _cached_app_key = app_key
        return _fernet


def encrypt_at_rest(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt a string for storage in a VARCHAR column.

    None and empty-string pass through unchanged so callers can safely encrypt
    optional fields. Returns the version-tagged ciphertext.
    """
    if plaintext is None or plaintext == "":
        return plaintext
    f = _derive_fernet()
    token = f.encrypt(plaintext.encode("utf-8"))
    return _VERSION_TAG + token.decode("ascii")


def decrypt_at_rest(stored: Optional[str]) -> Optional[str]:
    """Decrypt a value previously written by encrypt_at_rest.

    Accepts plaintext (no version tag) for backward compatibility — useful when
    rolling out encryption to an existing column. Raises InvalidToken on
    tampering or an APP_KEY mismatch.
    """
    if stored is None or stored == "":
        return stored
    if not stored.startswith(_VERSION_TAG):
        # Unencrypted legacy value — return as-is. Caller should re-encrypt.
        return stored
    f = _derive_fernet()
    body = stored[len(_VERSION_TAG):].encode("ascii")
    try:
        return f.decrypt(body).decode("utf-8")
    except InvalidToken:
        # Re-raise with a clearer message; the underlying exception is opaque.
        raise InvalidToken(
            "Failed to decrypt secret. Possible causes: APP_KEY changed, "
            "ciphertext tampered, or row written by a different deployment."
        )


def is_encrypted(stored: Optional[str]) -> bool:
    """Return True if the stored value carries the version tag."""
    return bool(stored) and stored.startswith(_VERSION_TAG)
