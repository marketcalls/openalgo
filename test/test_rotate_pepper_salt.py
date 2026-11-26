"""upgrade/rotate_pepper.py derives the auth_db key the way the app does.

database/auth_db.py derives its Fernet key from API_KEY_PEPPER and the
install's own FERNET_SALT, falling back to a legacy static salt only when the
install has none. rotate_pepper.py used the static salt always. On an install
with its own salt it therefore could not decrypt any auth_db ciphertext: the
broker token was reported as "cannot decrypt" and left under the old pepper,
and the TOTP secret, a column that may still hold plaintext, was taken for
plaintext and encrypted a second time. The new pepper was then written to .env
and every one of those values became unreadable.
"""

from __future__ import annotations

import base64
import os
import sqlite3
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

REPO_ROOT = Path(__file__).resolve().parent.parent
OLD_PEPPER, NEW_PEPPER = "e" * 64, "f" * 64
TOKEN = "broker-access-token"
TOTP = "JBSWY3DPEHPK3PXP"


def _fernet(pepper: str, salt: bytes) -> Fernet:
    """The key database/auth_db.py derives for this pepper and salt."""
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(pepper.encode())))


@pytest.fixture
def rotate_pepper():
    sys.path.insert(0, str(REPO_ROOT / "upgrade"))
    try:
        import rotate_pepper as module
    finally:
        sys.path.remove(str(REPO_ROOT / "upgrade"))
    return module


def _install(db_file: Path, key: Fernet) -> None:
    """A database holding a broker token and a TOTP secret under ``key``."""
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE auth (id INTEGER PRIMARY KEY, auth TEXT, feed_token TEXT, "
            "secret_api_key TEXT)"
        )
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, totp_secret TEXT)")
        conn.execute(
            "INSERT INTO auth (id, auth) VALUES (1, ?)", (key.encrypt(TOKEN.encode()).decode(),)
        )
        conn.execute(
            "INSERT INTO users (id, totp_secret) VALUES (1, ?)",
            (key.encrypt(TOTP.encode()).decode(),),
        )


def _rotate(rotate_pepper, db_file: Path) -> dict:
    with sqlite3.connect(db_file) as conn:
        rotator = rotate_pepper.Rotator(conn, OLD_PEPPER, NEW_PEPPER)
        rotator.rotate_all()
        conn.commit()
    return rotator.stats


def _stored(db_file: Path) -> tuple[str, str]:
    with sqlite3.connect(db_file) as conn:
        token = conn.execute("SELECT auth FROM auth").fetchone()[0]
        totp = conn.execute("SELECT totp_secret FROM users").fetchone()[0]
    return token, totp


def test_an_install_with_its_own_salt_is_rotated(tmp_path, monkeypatch, rotate_pepper):
    salt = os.urandom(16)
    monkeypatch.setenv("FERNET_SALT", salt.hex())
    db_file = tmp_path / "openalgo.db"
    _install(db_file, _fernet(OLD_PEPPER, salt))

    stats = _rotate(rotate_pepper, db_file)

    token, totp = _stored(db_file)
    new_key = _fernet(NEW_PEPPER, salt)
    assert new_key.decrypt(token.encode()).decode() == TOKEN
    # Decrypted once and encrypted once: not the old ciphertext encrypted again.
    assert new_key.decrypt(totp.encode()).decode() == TOTP
    assert stats["auth.auth"] == 1
    assert stats["users.totp_secret_plaintext_promoted"] == 0


def test_an_install_without_its_own_salt_still_uses_the_static_one(
    tmp_path, monkeypatch, rotate_pepper
):
    monkeypatch.delenv("FERNET_SALT", raising=False)
    db_file = tmp_path / "openalgo.db"
    _install(db_file, _fernet(OLD_PEPPER, b"openalgo_static_salt"))

    _rotate(rotate_pepper, db_file)

    token, totp = _stored(db_file)
    new_key = _fernet(NEW_PEPPER, b"openalgo_static_salt")
    assert new_key.decrypt(token.encode()).decode() == TOKEN
    assert new_key.decrypt(totp.encode()).decode() == TOTP


@pytest.mark.parametrize("salt", ["", "not-hex-at-all-but-long-enough-to-pass-32", "abcd"])
def test_a_missing_or_malformed_salt_falls_back_like_the_app(monkeypatch, rotate_pepper, salt):
    """The same rule as database/auth_db._resolve_fernet_salt()."""
    monkeypatch.setenv("FERNET_SALT", salt)

    assert rotate_pepper._auth_db_salt() == b"openalgo_static_salt"
