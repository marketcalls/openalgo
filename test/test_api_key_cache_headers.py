"""Regression tests for cache headers on API-key responses."""

import pytest
from flask import Flask

import blueprints.apikey as apikey_blueprint
import blueprints.playground as playground_blueprint
import blueprints.websocket_example as websocket_blueprint
import database.auth_db as auth_db


@pytest.fixture
def app(monkeypatch):
    """Create a minimal app with an authenticated API-key route."""
    monkeypatch.setenv("DISABLE_SESSION_EXPIRY", "true")

    app = Flask(__name__)
    app.secret_key = "test-secret-not-real"  # pragma: allowlist secret
    app.register_blueprint(apikey_blueprint.api_key_bp)
    app.register_blueprint(playground_blueprint.playground_bp)
    app.register_blueprint(websocket_blueprint.websocket_bp)
    return app


@pytest.fixture
def client(app):
    """Return a client with a locally authenticated test session."""
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["user"] = "test-user"
            session["logged_in"] = True
            session["login_time"] = "2026-01-01T00:00:00+05:30"
        yield client


def test_apikey_get_prevents_caching_credentials(client, monkeypatch):
    """The JSON response containing an existing key must not be cached."""
    monkeypatch.setattr(
        apikey_blueprint,
        "get_api_key_for_tradingview",
        lambda username: "test-token-not-real",
    )
    monkeypatch.setattr(apikey_blueprint, "get_order_mode", lambda username: "auto")

    response = client.get("/apikey", headers={"Accept": "application/json"})

    assert response.status_code == 200
    assert response.get_json()["api_key"] == "test-token-not-real"  # pragma: allowlist secret
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"


def test_apikey_post_prevents_caching_new_credentials(client, monkeypatch):
    """A newly generated key must not be cached."""
    monkeypatch.setattr(
        apikey_blueprint,
        "generate_api_key",
        lambda: "new-test-token-not-real",
    )
    monkeypatch.setattr(apikey_blueprint, "upsert_api_key", lambda user_id, api_key: 42)

    response = client.post("/apikey", json={"user_id": "test-user"})

    assert response.status_code == 200
    assert (
        response.get_json()["api_key"] == "new-test-token-not-real"  # pragma: allowlist secret
    )
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"


def test_apikey_html_response_prevents_caching_credentials(client, monkeypatch, tmp_path):
    """The legacy HTML page, which embeds the current key, must not be cached."""
    monkeypatch.setattr(apikey_blueprint, "FRONTEND_DIST", tmp_path)
    monkeypatch.setattr(
        apikey_blueprint,
        "get_api_key_for_tradingview",
        lambda username: "test-token-not-real",
    )
    monkeypatch.setattr(apikey_blueprint, "get_order_mode", lambda username: "auto")
    monkeypatch.setattr(apikey_blueprint, "render_template", lambda *args, **kwargs: "key page")

    response = client.get("/apikey")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"


def test_playground_api_key_prevents_caching_credentials(client, monkeypatch):
    """The playground key endpoint must not be cached."""
    monkeypatch.setattr(
        playground_blueprint,
        "get_api_key_for_tradingview",
        lambda username: "test-token-not-real",
    )

    response = client.get("/playground/api-key")

    assert response.status_code == 200
    assert response.get_json()["api_key"] == "test-token-not-real"  # pragma: allowlist secret
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"


def test_websocket_api_key_prevents_caching_credentials(client, monkeypatch):
    """The WebSocket authentication key endpoint must not be cached."""
    monkeypatch.setattr(
        auth_db,
        "get_api_key_for_tradingview",
        lambda username: "test-token-not-real",
    )

    response = client.get("/api/websocket/apikey")

    assert response.status_code == 200
    assert response.get_json()["api_key"] == "test-token-not-real"  # pragma: allowlist secret
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"


def test_non_sensitive_api_key_mode_response_is_unchanged(client, monkeypatch):
    """The no-store helper must remain scoped to responses carrying credentials."""
    monkeypatch.setattr(apikey_blueprint, "update_order_mode", lambda user_id, mode: True)

    response = client.post(
        "/apikey/mode",
        json={"user_id": "test-user", "mode": "auto"},
    )

    assert response.status_code == 200
    assert "no-store" not in response.headers.get("Cache-Control", "")
    assert "Pragma" not in response.headers
