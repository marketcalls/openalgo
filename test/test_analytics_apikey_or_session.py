"""Auth matrix for the analytics apikey_or_session decorator.

The analytics blueprints are CSRF-exempt at registration (headless apikey
clients carry no token, and a bearer credential in the body is not
CSRF-able), so the decorator must re-enforce CSRF on the session fallback
branch itself — otherwise the exemption would drop the token check that
these routes enforced before the apikey path existed (PR #1990 review
finding).

Uses a real registered analytics blueprint (oitracker) with the heavy data
calls patched out: the layer under test is authentication, not the
analytics math.
"""

from datetime import datetime, timedelta

import pytest
import pytz
from flask import Flask, jsonify
from flask_wtf.csrf import CSRFProtect, generate_csrf

import blueprints.oitracker as oitracker_module
import database.auth_db as auth_db_module
from blueprints.oitracker import oitracker_bp

VALID_PARAMS = {"underlying": "NIFTY", "exchange": "NFO", "expiry_date": "15OCT26"}


def _oi_data_success(**kwargs):
    return True, {"status": "success", "data": []}, 200


@pytest.fixture()
def app(monkeypatch):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret-key"
    app.config["TESTING"] = True

    csrf = CSRFProtect(app)
    # Mirror app.py: the analytics blueprints are registered CSRF-exempt.
    csrf.exempt(oitracker_bp)
    app.register_blueprint(oitracker_bp)

    @app.route("/_test/csrf")
    def _csrf_token():
        return jsonify({"token": generate_csrf()})

    # check_session_validity parity: the unauthenticated non-AJAX branch
    # redirects to auth.login, which the real app provides.
    @app.route("/login", endpoint="auth.login")
    def _login_page():
        return "login page", 200

    # Patch the credential lookups and the data call; the auth layer must
    # be exercised through the real decorator and real blueprint routes.
    monkeypatch.setattr(
        auth_db_module,
        "get_username_by_apikey",
        lambda key: "testuser" if key == "valid-key" else None,
    )
    monkeypatch.setattr(oitracker_module, "get_api_key_for_tradingview", lambda user: "sk-test")
    monkeypatch.setattr(oitracker_module, "get_oi_data", _oi_data_success)
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


def _login(client, login_time=None):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["user"] = "testuser"
        sess["login_time"] = login_time or datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()


def _csrf_token(client):
    return client.get("/_test/csrf").get_json()["token"]


class TestApikeyPath:
    def test_valid_apikey_authenticates_without_csrf_token(self, client):
        # Headless clients have no CSRF token; a bearer apikey must not need one.
        resp = client.post("/oitracker/api/oi-data", json={"apikey": "valid-key", **VALID_PARAMS})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_invalid_apikey_rejected(self, client):
        resp = client.post("/oitracker/api/oi-data", json={"apikey": "wrong-key", **VALID_PARAMS})
        assert resp.status_code == 401
        assert resp.get_json()["message"] == "Invalid openalgo apikey"


class TestSessionPath:
    def test_missing_auth_rejected(self, client):
        # Mirrors check_session_validity: JSON requests get the
        # session_expired contract instead of a bare message.
        resp = client.post("/oitracker/api/oi-data", json=VALID_PARAMS)
        assert resp.status_code == 401
        body = resp.get_json()
        assert body["error"] == "session_expired"
        assert body["status"] == "error"

    def test_missing_auth_non_ajax_redirects_to_login(self, client):
        # Non-AJAX callers get the same redirect check_session_validity
        # produced before the apikey path existed.
        resp = client.post(
            "/oitracker/api/oi-data",
            data="",
            content_type="text/plain",
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_expired_session_rejected(self, client):
        expired = datetime.now(pytz.timezone("Asia/Kolkata")) - timedelta(days=2)
        _login(client, login_time=expired.isoformat())
        resp = client.post("/oitracker/api/oi-data", json=VALID_PARAMS)
        assert resp.status_code == 401

    def test_valid_session_without_csrf_token_rejected(self, client):
        # THE review finding: the blueprint exemption must not remove the
        # token check for browser users — the decorator re-applies it.
        _login(client)
        resp = client.post("/oitracker/api/oi-data", json=VALID_PARAMS)
        assert resp.status_code == 400

    def test_valid_session_with_csrf_token_accepted(self, client):
        _login(client)
        token = _csrf_token(client)
        resp = client.post(
            "/oitracker/api/oi-data",
            json=VALID_PARAMS,
            headers={"X-CSRFToken": token},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"

    def test_csrf_disabled_allows_session_post_without_token(self, client, app, monkeypatch):
        # CSRF_ENABLED=FALSE deployments: protect() must no-op, not hard-fail.
        monkeypatch.setitem(app.config, "WTF_CSRF_ENABLED", False)
        _login(client)
        resp = client.post("/oitracker/api/oi-data", json=VALID_PARAMS)
        assert resp.status_code == 200


class TestApikeySources:
    """The apikey may arrive in the JSON body, the query string, or the
    X-API-Key header (needed for the GET endpoints, e.g. the interval
    lists, which cannot carry a JSON body)."""

    def _patch_capture(self, monkeypatch):
        from flask import g

        import blueprints.oitracker as oitracker_module

        captured = {}

        def _capture(**kwargs):
            captured["user"] = getattr(g, "openalgo_user", None)
            captured["apikey"] = getattr(g, "openalgo_apikey", None)
            return True, {"status": "success", "data": []}, 200

        monkeypatch.setattr(oitracker_module, "get_oi_data", _capture)
        return captured

    def test_apikey_from_query_param(self, client, monkeypatch):
        captured = self._patch_capture(monkeypatch)
        resp = client.post(
            "/oitracker/api/oi-data?apikey=valid-key", json=VALID_PARAMS
        )
        assert resp.status_code == 200
        assert captured["user"] == "testuser"
        assert captured["apikey"] == "valid-key"

    def test_apikey_from_header(self, client, monkeypatch):
        captured = self._patch_capture(monkeypatch)
        resp = client.post(
            "/oitracker/api/oi-data",
            json=VALID_PARAMS,
            headers={"X-API-Key": "valid-key"},
        )
        assert resp.status_code == 200
        assert captured["user"] == "testuser"
        assert captured["apikey"] == "valid-key"

    def test_invalid_apikey_from_header_rejected(self, client):
        resp = client.post(
            "/oitracker/api/oi-data",
            json=VALID_PARAMS,
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401
        assert resp.get_json()["message"] == "Invalid openalgo apikey"
