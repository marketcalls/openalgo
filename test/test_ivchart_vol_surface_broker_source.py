"""Broker resolution for the IV Chart / Vol Surface analytics routes.

The apikey_or_session decorator surfaces the verified credential as
``g.openalgo_apikey`` regardless of where it arrived (JSON body, ?apikey
query parameter, X-API-Key header). The routes must resolve the broker
from THAT credential and fall back to the session only for browser
logins — reading session['broker'] first left apikey-only clients with a
spurious 400 "Broker not set in session" (cubic review, 2026-09-06).
"""

import types
from datetime import datetime

import pytest
import pytz
from flask import Flask, jsonify
from flask_wtf.csrf import CSRFProtect, generate_csrf

import blueprints.ivchart as ivchart_module
import blueprints.vol_surface as vol_surface_module
import database.auth_db as auth_db_module
from blueprints.ivchart import ivchart_bp
from blueprints.vol_surface import vol_surface_bp


@pytest.fixture()
def app(monkeypatch):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret-key"
    app.config["TESTING"] = True

    csrf = CSRFProtect(app)
    csrf.exempt(ivchart_bp)
    csrf.exempt(vol_surface_bp)
    app.register_blueprint(ivchart_bp)
    app.register_blueprint(vol_surface_bp)

    @app.route("/_test/csrf")
    def _csrf_token():
        return jsonify({"token": generate_csrf()})

    username_for_key = lambda key: "testuser" if key == "valid-key" else None  # noqa: E731
    monkeypatch.setattr(auth_db_module, "get_username_by_apikey", username_for_key)
    # Broker lookup: patched per-test via _patch_broker_capture(); the routes
    # resolve the broker from the decorator's VERIFIED USERNAME (g.openalgo_user,
    # never the raw key), so default to a registered broker for the known user.
    monkeypatch.setattr(
        ivchart_module, "get_broker_name_for_user", lambda user: "zerodha" if user else None
    )
    monkeypatch.setattr(
        vol_surface_module, "get_broker_name_for_user", lambda user: "zerodha" if user else None
    )
    monkeypatch.setattr(ivchart_module, "get_auth_token", lambda user: "tok-testuser")
    monkeypatch.setattr(vol_surface_module, "get_auth_token", lambda user: "tok-testuser")
    monkeypatch.setattr(ivchart_module, "get_api_key_for_tradingview", lambda user: "sk-test")
    monkeypatch.setattr(vol_surface_module, "get_api_key_for_tradingview", lambda user: "sk-test")
    monkeypatch.setattr(
        ivchart_module,
        "get_iv_chart_data",
        lambda **kwargs: (True, {"status": "success", "data": []}, 200),
    )
    monkeypatch.setattr(
        vol_surface_module,
        "get_vol_surface_data",
        lambda **kwargs: (True, {"status": "success", "data": []}, 200),
    )
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


IV_PARAMS = {"underlying": "NIFTY", "exchange": "NFO", "expiry_date": "15OCT26"}
VS_PARAMS = {"underlying": "NIFTY", "exchange": "NFO", "expiry_dates": ["15OCT26"]}


def _login(client):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["user"] = "testuser"
        sess["broker"] = "zerodha"  # stored by the real login flow
        sess["login_time"] = datetime.now(pytz.timezone("Asia/Kolkata")).isoformat()


def _csrf_token(client):
    return client.get("/_test/csrf").get_json()["token"]


def _patch_broker_capture(monkeypatch, source="ivchart"):
    """Capture which identity get_broker_name_for_user is called with."""
    module = ivchart_module if source == "ivchart" else vol_surface_module
    captured = {}

    def _spy(username):
        captured["username"] = username
        return "zerodha" if username else None

    monkeypatch.setattr(module, "get_broker_name_for_user", _spy)
    return captured


class TestIvchartBrokerSource:
    def test_body_apikey_gets_broker(self, client, monkeypatch):
        # The documented primary source: apikey in the JSON body (the first
        # source the decorator checks).
        captured = _patch_broker_capture(monkeypatch, "ivchart")
        resp = client.post("/ivchart/api/iv-data", json={"apikey": "valid-key", **IV_PARAMS})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"
        assert captured["username"] == "testuser"

    def test_apikey_only_client_gets_broker(self, client, monkeypatch):
        # The P1: an X-API-Key client authenticated fine but the route read
        # the broker from the empty session and returned 400.
        captured = _patch_broker_capture(monkeypatch, "ivchart")
        resp = client.post("/ivchart/api/iv-data", json=IV_PARAMS, headers={"X-API-Key": "valid-key"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"
        # The broker was resolved from the decorator's verified identity, and
        # the raw key never entered broker_cache.
        assert captured["username"] == "testuser"
        assert "valid-key" not in auth_db_module.broker_cache

    def test_query_param_apikey_gets_broker(self, client, monkeypatch):
        captured = _patch_broker_capture(monkeypatch, "ivchart")
        resp = client.post("/ivchart/api/iv-data?apikey=valid-key", json=IV_PARAMS)
        assert resp.status_code == 200
        assert captured["username"] == "testuser"

    def test_session_client_skips_apikey_lookup(self, client, monkeypatch):
        captured = _patch_broker_capture(monkeypatch, "ivchart")
        _login(client)
        resp = client.post(
            "/ivchart/api/iv-data",
            json=IV_PARAMS,
            headers={"X-CSRFToken": _csrf_token(client)},
        )
        assert resp.status_code == 200
        # Browser sessions carry the broker name directly: get_broker_name
        # must not be consulted at all on the session path.
        assert captured == {}

    def test_broker_lookup_failure_still_returns_400(self, client, monkeypatch):
        # A credential that authenticates but has no broker registered (or a
        # lookup failure) must keep failing closed with the same 400.
        monkeypatch.setattr(ivchart_module, "get_broker_name_for_user", lambda user: None)
        resp = client.post("/ivchart/api/iv-data", json=IV_PARAMS, headers={"X-API-Key": "valid-key"})
        assert resp.status_code == 400
        assert resp.get_json()["message"] == "Broker not set in session"


class TestBrokerUsernameCache:
    """get_broker_name_for_user caches by verified username (cubic round 3:
    chart polling must not hit the database per request, and broker_cache
    must never key on the raw API key)."""

    def test_caches_by_username_never_by_key(self, monkeypatch):
        calls = {"n": 0}

        class _FakeQuery:
            def filter_by(self, **kwargs):
                calls["n"] += 1
                return self

            def first(self):
                return types.SimpleNamespace(is_revoked=False, broker="zerodha")

        class _FakeAuth:
            query = _FakeQuery()

        monkeypatch.setattr(auth_db_module, "Auth", _FakeAuth)
        auth_db_module.broker_cache.clear()
        try:
            assert auth_db_module.get_broker_name_for_user("testuser") == "zerodha"
            assert auth_db_module.get_broker_name_for_user("testuser") == "zerodha"
            assert calls["n"] == 1  # second call served from the cache
            assert auth_db_module.broker_cache["testuser"] == "zerodha"
            assert "valid-key" not in auth_db_module.broker_cache
        finally:
            auth_db_module.broker_cache.clear()


class TestVolSurfaceBrokerSource:
    def test_body_apikey_gets_broker(self, client, monkeypatch):
        captured = _patch_broker_capture(monkeypatch, "vol_surface")
        resp = client.post(
            "/volsurface/api/surface-data", json={"apikey": "valid-key", **VS_PARAMS}
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"
        assert captured["username"] == "testuser"

    def test_apikey_only_client_gets_broker(self, client, monkeypatch):
        captured = _patch_broker_capture(monkeypatch, "vol_surface")
        resp = client.post(
            "/volsurface/api/surface-data", json=VS_PARAMS, headers={"X-API-Key": "valid-key"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"
        assert captured["username"] == "testuser"
        assert "valid-key" not in auth_db_module.broker_cache

    def test_query_param_apikey_gets_broker(self, client, monkeypatch):
        captured = _patch_broker_capture(monkeypatch, "vol_surface")
        resp = client.post("/volsurface/api/surface-data?apikey=valid-key", json=VS_PARAMS)
        assert resp.status_code == 200
        assert captured["username"] == "testuser"

    def test_session_client_skips_apikey_lookup(self, client, monkeypatch):
        captured = _patch_broker_capture(monkeypatch, "vol_surface")
        _login(client)
        resp = client.post(
            "/volsurface/api/surface-data",
            json=VS_PARAMS,
            headers={"X-CSRFToken": _csrf_token(client)},
        )
        assert resp.status_code == 200
        # Browser sessions carry the broker name directly: get_broker_name
        # must not be consulted at all on the session path.
        assert captured == {}

    def test_broker_lookup_failure_still_returns_400(self, client, monkeypatch):
        monkeypatch.setattr(vol_surface_module, "get_broker_name_for_user", lambda user: None)
        resp = client.post(
            "/volsurface/api/surface-data", json=VS_PARAMS, headers={"X-API-Key": "valid-key"}
        )
        assert resp.status_code == 400
        assert resp.get_json()["message"] == "Broker not set in session"
