"""Regression tests for OpenAlgo login broker-session resume."""

import atexit
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_auth_resume.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ["LOG_FORMAT"] = "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
os.environ["LOG_TO_FILE"] = "False"
os.environ.setdefault("API_KEY_PEPPER", "a" * 64)
os.environ.setdefault("FERNET_SALT", "b" * 32)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

import blueprints.auth as auth_bp_module  # noqa: E402
import database.auth_db as auth_db  # noqa: E402
import utils.auth_utils as auth_utils  # noqa: E402


@pytest.fixture()
def app_context():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    with app.test_request_context("/auth/login", method="POST"):
        yield


def _auth_record(broker="dhan"):
    return SimpleNamespace(
        auth="encrypted-token",
        feed_token=None,
        broker=broker,
        user_id="client-id",
        is_revoked=False,
    )


def test_resume_rejects_broker_test_auth_failure(monkeypatch, app_context):
    """Dhan-style test_auth_token failure must force broker login."""
    session["user"] = "rajandran"

    fake_funds = SimpleNamespace(
        test_auth_token=lambda token: (False, "Client ID or token is invalid or expired"),
        get_margin_data=lambda token: pytest.fail("get_margin_data should not run"),
    )

    monkeypatch.setattr(auth_db, "get_auth_token_dbquery", lambda username: _auth_record())
    monkeypatch.setattr(auth_db, "decrypt_token", lambda token: "plain-token")
    monkeypatch.setattr(importlib, "import_module", lambda module_path: fake_funds)
    monkeypatch.setattr(
        auth_utils,
        "handle_auth_success",
        lambda **kwargs: pytest.fail("expired broker token must not resume session"),
    )

    assert auth_bp_module._try_resume_broker_session("rajandran") is None
    assert session.get("logged_in") is not True


def test_resume_rejects_structured_funds_error(monkeypatch, app_context):
    """Brokers without test_auth_token still cannot resume on error payloads."""
    session["user"] = "rajandran"

    fake_funds = SimpleNamespace(
        get_margin_data=lambda token: {"status": "error", "message": "token expired"}
    )

    monkeypatch.setattr(auth_db, "get_auth_token_dbquery", lambda username: _auth_record("zerodha"))
    monkeypatch.setattr(auth_db, "decrypt_token", lambda token: "plain-token")
    monkeypatch.setattr(importlib, "import_module", lambda module_path: fake_funds)
    monkeypatch.setattr(
        auth_utils,
        "handle_auth_success",
        lambda **kwargs: pytest.fail("error funds response must not resume session"),
    )

    assert auth_bp_module._try_resume_broker_session("rajandran") is None
    assert session.get("logged_in") is not True


def test_resume_accepts_valid_broker_validation(monkeypatch, app_context):
    """A genuinely valid broker token can still skip broker login."""
    session["user"] = "rajandran"

    fake_funds = SimpleNamespace(
        test_auth_token=lambda token: (True, None),
        get_margin_data=lambda token: {"availablecash": "100.00"},
    )

    def fake_auth_success(**kwargs):
        session["logged_in"] = True
        session["broker"] = kwargs["broker"]

    monkeypatch.setattr(auth_db, "get_auth_token_dbquery", lambda username: _auth_record())
    monkeypatch.setattr(auth_db, "decrypt_token", lambda token: "plain-token")
    monkeypatch.setattr(importlib, "import_module", lambda module_path: fake_funds)
    monkeypatch.setattr(auth_utils, "handle_auth_success", fake_auth_success)

    response, status_code = auth_bp_module._try_resume_broker_session("rajandran")

    assert status_code == 200
    assert response.get_json()["message"] == "Broker session resumed"
    assert session["logged_in"] is True
    assert session["broker"] == "dhan"


def test_login_clears_expired_existing_session_before_password_flow(monkeypatch):
    """A stale browser session on /auth/login must not redirect to dashboard."""
    app = Flask(__name__)
    app.secret_key = "test-secret"

    user = SimpleNamespace(is_totp_required_for=lambda purpose: False)
    revoked = {"called": False}

    monkeypatch.setattr(auth_bp_module, "find_user_by_username", lambda: object())
    monkeypatch.setattr(auth_bp_module, "is_session_valid", lambda: False)
    monkeypatch.setattr(auth_bp_module, "revoke_user_tokens", lambda: revoked.update(called=True))
    monkeypatch.setattr(auth_bp_module, "authenticate_user", lambda username, password: True)
    monkeypatch.setattr(auth_bp_module, "find_user_by_exact_username", lambda username: user)
    monkeypatch.setattr(auth_bp_module, "_try_resume_broker_session", lambda username: None)
    monkeypatch.setattr(auth_db, "log_login_attempt", lambda *args, **kwargs: None)

    with app.test_request_context(
        "/auth/login",
        method="POST",
        data={"username": "rajandran", "password": "password"},
    ):
        session["user"] = "rajandran"
        session["logged_in"] = True
        session["broker"] = "dhan"

        response, status_code = auth_bp_module.login()

        assert revoked["called"] is True
        assert status_code == 200
        payload = response.get_json()
        assert payload["status"] == "success"
        assert "redirect" not in payload
        assert session["user"] == "rajandran"
        assert session.get("logged_in") is not True


def test_login_get_clears_expired_existing_session(monkeypatch):
    """Direct /auth/login requests should also clear stale full sessions."""
    app = Flask(__name__)
    app.secret_key = "test-secret"

    revoked = {"called": False}

    monkeypatch.setattr(auth_bp_module, "find_user_by_username", lambda: object())
    monkeypatch.setattr(auth_bp_module, "is_session_valid", lambda: False)
    monkeypatch.setattr(auth_bp_module, "revoke_user_tokens", lambda: revoked.update(called=True))

    with app.test_request_context("/auth/login", method="GET"):
        session["user"] = "rajandran"
        session["logged_in"] = True
        session["broker"] = "dhan"

        response = auth_bp_module.login()

        assert revoked["called"] is True
        assert response.status_code == 302
        assert response.location == "/login"
        assert "user" not in session


def test_zerodha_callback_formats_auth_token_with_broker_api_key(monkeypatch):
    import blueprints.brlogin as brlogin_module

    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.broker_auth_functions = {
        "zerodha_auth": lambda request_token: ("raw-access-token", None),
    }

    captured = {}

    def fake_handle_auth_success(auth_token, user_session_key, broker, feed_token=None, user_id=None):
        captured.update(
            {
                "auth_token": auth_token,
                "user_session_key": user_session_key,
                "broker": broker,
                "feed_token": feed_token,
                "user_id": user_id,
            }
        )
        return {"status": "ok"}, 200

    monkeypatch.setenv("BROKER_API_KEY", "kite-key")
    monkeypatch.setattr(brlogin_module, "BROKER_API_KEY", "stale-module-key", raising=False)
    monkeypatch.setattr(brlogin_module, "handle_auth_success", fake_handle_auth_success)

    with app.test_request_context("/zerodha/callback?request_token=request-token", method="GET"):
        session["user"] = "admin"
        response, status_code = brlogin_module.broker_callback("zerodha")

    assert status_code == 200
    assert response == {"status": "ok"}
    assert captured == {
        "auth_token": "kite-key:raw-access-token",
        "user_session_key": "admin",
        "broker": "zerodha",
        "feed_token": None,
        "user_id": None,
    }
