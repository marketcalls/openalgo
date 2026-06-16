import logging
import os
import sys
from types import SimpleNamespace

import pytest

os.environ["LOG_FORMAT"] = "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
os.environ["LOG_TO_FILE"] = "False"
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker.zerodha.api import auth_api as zerodha_auth_api


def test_zerodha_format_auth_token_uses_clean_env_api_key(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "'kite-key'")

    assert zerodha_auth_api.format_auth_token('"raw-access-token"') == "kite-key:raw-access-token"


def test_zerodha_format_auth_token_rejects_missing_api_key(monkeypatch):
    monkeypatch.delenv("BROKER_API_KEY", raising=False)

    with pytest.raises(ValueError, match="zerodha_broker_api_key_missing"):
        zerodha_auth_api.format_auth_token("raw-access-token")


def test_zerodha_format_auth_token_rejects_blank_access_token(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "kite-key")

    with pytest.raises(ValueError, match="zerodha_access_token_missing"):
        zerodha_auth_api.format_auth_token("  ")


def test_zerodha_validate_access_token_calls_profile(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "kite-key")
    calls = []

    class FakeClient:
        def get(self, url, headers):
            calls.append((url, headers))
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"status": "success", "data": {"user_name": "Admin"}},
            )

    monkeypatch.setattr(zerodha_auth_api, "get_httpx_client", lambda: FakeClient())

    is_valid, reason = zerodha_auth_api.validate_access_token("raw-access-token")

    assert is_valid is True
    assert reason is None
    assert calls == [
        (
            "https://api.kite.trade/user/profile",
            {
                "Authorization": "token kite-key:raw-access-token",
                "X-Kite-Version": "3",
            },
        )
    ]


def test_zerodha_validate_access_token_rejects_profile_failure(monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "kite-key")

    class FakeClient:
        def get(self, url, headers):
            return SimpleNamespace(
                status_code=403,
                json=lambda: {"status": "error", "message": "Token is invalid"},
            )

    monkeypatch.setattr(zerodha_auth_api, "get_httpx_client", lambda: FakeClient())

    is_valid, reason = zerodha_auth_api.validate_access_token("raw-access-token")

    assert is_valid is False
    assert reason == "zerodha_profile_rejected"
