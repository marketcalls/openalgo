import logging
import os
import sys
import atexit
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ["LOG_FORMAT"] = "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
os.environ["LOG_TO_FILE"] = "False"
TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_internal_broker_token_api.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ.setdefault("API_KEY_PEPPER", "a" * 64)
os.environ.setdefault("FERNET_SALT", "b" * 32)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from broker.zerodha.api import auth_api as zerodha_auth_api
import utils.auth_utils as auth_utils


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


def test_activate_broker_auth_token_upserts_and_starts_download(monkeypatch):
    calls = []

    monkeypatch.setattr(
        auth_utils,
        "upsert_auth",
        lambda name, auth_token, broker, feed_token=None, user_id=None: calls.append(
            ("upsert", name, auth_token, broker, feed_token, user_id)
        )
        or 42,
    )
    monkeypatch.setattr(
        auth_utils,
        "init_broker_status",
        lambda broker: calls.append(("init_status", broker)),
    )
    monkeypatch.setattr(
        auth_utils,
        "should_download_master_contract",
        lambda broker: (True, "No previous download found"),
    )

    class FakeThread:
        def __init__(self, target, args, daemon):
            calls.append(("thread", target.__name__, args, daemon))

        def start(self):
            calls.append(("thread_started",))

    monkeypatch.setattr(auth_utils, "Thread", FakeThread)

    inserted_id = auth_utils.activate_broker_auth_token(
        "kite-key:raw-access-token",
        "admin",
        "zerodha",
    )

    assert inserted_id == 42
    assert calls == [
        ("upsert", "admin", "kite-key:raw-access-token", "zerodha", None, None),
        ("init_status", "zerodha"),
        ("thread", "async_master_contract_download", ("zerodha",), True),
        ("thread_started",),
    ]


def test_activate_broker_auth_token_loads_existing_contract_when_fresh(monkeypatch):
    calls = []

    monkeypatch.setattr(auth_utils, "upsert_auth", lambda *args, **kwargs: 43)
    monkeypatch.setattr(
        auth_utils, "init_broker_status", lambda broker: calls.append(("init", broker))
    )
    monkeypatch.setattr(
        auth_utils,
        "should_download_master_contract",
        lambda broker: (False, "Already downloaded today"),
    )

    class FakeThread:
        def __init__(self, target, args, daemon):
            calls.append(("thread", target.__name__, args, daemon))

        def start(self):
            calls.append(("started",))

    monkeypatch.setattr(auth_utils, "Thread", FakeThread)

    assert auth_utils.activate_broker_auth_token("token", "admin", "zerodha") == 43
    assert calls == [
        ("init", "zerodha"),
        ("thread", "load_existing_master_contract", ("zerodha",), True),
        ("started",),
    ]
