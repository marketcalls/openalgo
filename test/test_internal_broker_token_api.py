import logging
import os
import sys
import atexit
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask

os.environ["LOG_FORMAT"] = "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
os.environ["LOG_TO_FILE"] = "False"
TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_internal_broker_token_api.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB.as_posix()}"
os.environ.setdefault("API_KEY_PEPPER", "a" * 64)
os.environ.setdefault("FERNET_SALT", "b" * 32)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from blueprints import internal_broker_token as internal_broker_token_module
from blueprints.internal_broker_token import internal_broker_token_bp
from broker.zerodha.api import auth_api as zerodha_auth_api
from limiter import limiter
from services import broker_token_import_service as import_service
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


def test_import_broker_token_rejects_invalid_apikey(monkeypatch):
    monkeypatch.setattr(import_service, "verify_api_key", lambda apikey: None)

    with pytest.raises(import_service.InvalidApiKeyError) as exc:
        import_service.import_broker_token("bad-api-key", "zerodha", "raw-access-token")

    assert exc.value.status_code == 403


def test_import_broker_token_rejects_unsupported_broker(monkeypatch):
    with pytest.raises(import_service.UnsupportedBrokerError) as exc:
        import_service.import_broker_token("openalgo-api-key", "dhan", "raw-access-token")

    assert exc.value.status_code == 400


def test_import_broker_token_rejects_blank_access_token(monkeypatch):
    with pytest.raises(import_service.InvalidAccessTokenError) as exc:
        import_service.import_broker_token("openalgo-api-key", "zerodha", " ")

    assert exc.value.status_code == 400


def test_import_broker_token_validation_failure_does_not_activate(monkeypatch):
    activated = {"called": False}

    monkeypatch.setattr(import_service, "verify_api_key", lambda apikey: "admin")
    monkeypatch.setattr(import_service, "format_auth_token", lambda token: "kite-key:raw-access-token")
    monkeypatch.setattr(
        import_service,
        "validate_access_token",
        lambda token: (False, "zerodha_profile_rejected"),
    )
    monkeypatch.setattr(
        import_service,
        "activate_broker_auth_token",
        lambda *args, **kwargs: activated.update(called=True),
    )

    with pytest.raises(import_service.InvalidAccessTokenError):
        import_service.import_broker_token("openalgo-api-key", "zerodha", "raw-access-token")

    assert activated["called"] is False


def test_import_broker_token_success_activates_formatted_token(monkeypatch):
    calls = []

    monkeypatch.setattr(import_service, "verify_api_key", lambda apikey: "admin")
    monkeypatch.setattr(import_service, "format_auth_token", lambda token: "kite-key:raw-access-token")
    monkeypatch.setattr(import_service, "validate_access_token", lambda token: (True, None))
    monkeypatch.setattr(import_service, "get_auth_token", lambda user_id, bypass_cache=False: None)
    monkeypatch.setattr(
        import_service,
        "activate_broker_auth_token",
        lambda auth_token, user_session_key, broker: calls.append(
            (auth_token, user_session_key, broker)
        )
        or 42,
    )

    result = import_service.import_broker_token("openalgo-api-key", "zerodha", "raw-access-token")

    assert result.broker == "zerodha"
    assert result.user_id == "admin"
    assert result.updated is True
    assert calls == [("kite-key:raw-access-token", "admin", "zerodha")]


def test_import_broker_token_unchanged_skips_activation(monkeypatch):
    activated = {"called": False}

    monkeypatch.setattr(import_service, "verify_api_key", lambda apikey: "admin")
    monkeypatch.setattr(import_service, "format_auth_token", lambda token: "kite-key:raw-access-token")
    monkeypatch.setattr(import_service, "validate_access_token", lambda token: (True, None))
    monkeypatch.setattr(
        import_service,
        "get_auth_token",
        lambda user_id, bypass_cache=False: "kite-key:raw-access-token",
    )
    monkeypatch.setattr(
        import_service,
        "activate_broker_auth_token",
        lambda *args, **kwargs: activated.update(called=True),
    )

    result = import_service.import_broker_token("openalgo-api-key", "zerodha", "raw-access-token")

    assert result.updated is False
    assert activated["called"] is False


def test_import_broker_token_persistence_failure_maps_to_500(monkeypatch):
    monkeypatch.setattr(import_service, "verify_api_key", lambda apikey: "admin")
    monkeypatch.setattr(import_service, "format_auth_token", lambda token: "kite-key:raw-access-token")
    monkeypatch.setattr(import_service, "validate_access_token", lambda token: (True, None))
    monkeypatch.setattr(import_service, "get_auth_token", lambda user_id, bypass_cache=False: None)
    monkeypatch.setattr(import_service, "activate_broker_auth_token", lambda *args, **kwargs: None)

    with pytest.raises(import_service.BrokerTokenPersistenceError) as exc:
        import_service.import_broker_token("openalgo-api-key", "zerodha", "raw-access-token")

    assert exc.value.status_code == 500


@pytest.fixture()
def internal_token_client():
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        RATELIMIT_ENABLED=False,
    )
    limiter.init_app(app)
    app.register_blueprint(internal_broker_token_bp, url_prefix="/internal")
    return app.test_client()


def _post_broker_token(client, header_secret="shared-secret", payload=None):
    headers = {}
    if header_secret is not None:
        headers["X-OpenAlgo-Token-Service-Secret"] = header_secret
    return client.post(
        "/internal/broker-token",
        json=payload
        or {
            "apikey": "openalgo-api-key",
            "broker": "zerodha",
            "access_token": "raw-access-token",
        },
        headers=headers,
    )


def test_internal_broker_token_secret_unset_returns_404(
    monkeypatch,
    internal_token_client,
):
    monkeypatch.delenv("OPENALGO_TOKEN_SERVICE_SECRET", raising=False)

    response = _post_broker_token(internal_token_client)

    assert response.status_code == 404


def test_internal_broker_token_missing_secret_header_returns_403(
    monkeypatch,
    internal_token_client,
):
    monkeypatch.setenv("OPENALGO_TOKEN_SERVICE_SECRET", "shared-secret")

    response = _post_broker_token(internal_token_client, header_secret=None)

    assert response.status_code == 403


def test_internal_broker_token_bad_secret_header_returns_403(
    monkeypatch,
    internal_token_client,
):
    monkeypatch.setenv("OPENALGO_TOKEN_SERVICE_SECRET", "shared-secret")

    response = _post_broker_token(internal_token_client, header_secret="wrong-secret")

    assert response.status_code == 403


def test_internal_broker_token_success_response(
    monkeypatch,
    internal_token_client,
):
    monkeypatch.setenv("OPENALGO_TOKEN_SERVICE_SECRET", "shared-secret")

    monkeypatch.setattr(
        internal_broker_token_module,
        "import_broker_token",
        lambda **kwargs: import_service.BrokerTokenImportResult(
            broker="zerodha",
            user_id="admin",
            updated=True,
        ),
    )

    response = _post_broker_token(internal_token_client)

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "data": {"broker": "zerodha", "user_id": "admin", "updated": True},
    }


def test_internal_broker_token_service_error_response(
    monkeypatch,
    internal_token_client,
):
    monkeypatch.setenv("OPENALGO_TOKEN_SERVICE_SECRET", "shared-secret")

    def fail_import(**kwargs):
        raise import_service.UnsupportedBrokerError("unsupported_broker")

    monkeypatch.setattr(internal_broker_token_module, "import_broker_token", fail_import)

    response = _post_broker_token(
        internal_token_client,
        payload={
            "apikey": "openalgo-api-key",
            "broker": "dhan",
            "access_token": "raw-access-token",
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {"status": "error", "message": "unsupported_broker"}
