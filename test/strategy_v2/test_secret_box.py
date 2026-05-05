"""Unit tests for utils/secret_box.py."""

import os

import pytest
from cryptography.fernet import InvalidToken

from utils import secret_box


@pytest.fixture(autouse=True)
def _set_app_key(monkeypatch):
    """Each test gets a deterministic APP_KEY and resets the cached Fernet."""
    monkeypatch.setenv("APP_KEY", "test_app_key_for_secret_box_unit_tests_only_32b")
    # Reset the module-level cache so each test re-derives.
    secret_box._fernet = None
    secret_box._cached_app_key = None
    yield
    secret_box._fernet = None
    secret_box._cached_app_key = None


def test_roundtrip_encrypt_decrypt():
    plain = "tradingview-secret-1f9c4a8b2e3d4f50"
    enc = secret_box.encrypt_at_rest(plain)
    assert enc != plain
    assert enc.startswith("fern1:")
    assert secret_box.decrypt_at_rest(enc) == plain


def test_none_passes_through():
    assert secret_box.encrypt_at_rest(None) is None
    assert secret_box.decrypt_at_rest(None) is None


def test_empty_string_passes_through():
    assert secret_box.encrypt_at_rest("") == ""
    assert secret_box.decrypt_at_rest("") == ""


def test_legacy_plaintext_returned_as_is():
    # Backward-compatibility path: a value missing the version tag is treated
    # as legacy plaintext and returned unchanged.
    assert secret_box.decrypt_at_rest("plain-old-value") == "plain-old-value"


def test_is_encrypted_flag():
    enc = secret_box.encrypt_at_rest("hello")
    assert secret_box.is_encrypted(enc) is True
    assert secret_box.is_encrypted("hello") is False
    assert secret_box.is_encrypted("") is False
    assert secret_box.is_encrypted(None) is False


def test_decrypt_with_changed_app_key_raises(monkeypatch):
    enc = secret_box.encrypt_at_rest("hello")
    # Rotate APP_KEY mid-test
    monkeypatch.setenv("APP_KEY", "different-app-key-causes-fernet-mismatch")
    secret_box._fernet = None
    secret_box._cached_app_key = None
    with pytest.raises(InvalidToken):
        secret_box.decrypt_at_rest(enc)


def test_missing_app_key_raises(monkeypatch):
    monkeypatch.delenv("APP_KEY", raising=False)
    secret_box._fernet = None
    secret_box._cached_app_key = None
    with pytest.raises(secret_box.SecretBoxConfigError):
        secret_box.encrypt_at_rest("hello")


def test_ciphertexts_differ_each_call():
    """Fernet uses a random IV — same plaintext should produce different ciphertexts."""
    a = secret_box.encrypt_at_rest("repeat me")
    b = secret_box.encrypt_at_rest("repeat me")
    assert a != b
    # But both decrypt to the same plaintext
    assert secret_box.decrypt_at_rest(a) == secret_box.decrypt_at_rest(b) == "repeat me"
