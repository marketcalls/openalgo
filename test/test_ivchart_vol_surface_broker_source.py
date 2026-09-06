"""Broker resolution for the IV Chart / Vol Surface analytics routes.

The apikey_or_session decorator surfaces the verified credential as
``g.openalgo_apikey`` regardless of where it arrived (JSON body, ?apikey
query parameter, X-API-Key header). The routes must resolve the broker
from THAT credential and fall back to the session only for browser
logins — reading session['broker'] first left apikey-only clients with a
spurious 400 "Broker not set in session" (cubic review, 2026-09-06).
"""

import pytest
from flask import Flask, jsonify
from flask_wtf.csrf import CSRFProtect, generate_csrf
from datetime import datetime

import pytz

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

    monkeypatch.setattr(
        auth_db_module,
        "get_username_by_apikey",
        lambda key: "testuser" if key == "valid-key" else None,
    )
    # Broker lookup: patched per-test via _patch_broker(); default to a
    # registered broker for both the apikey and session credentials.
    monkeypatch.setattr(ivchart_module, "get_broker_name", lambda key: "zerodha" if key else None)
    monkeypatch.setattr(
        vol_surface_module, "get_broker_name", lambda key: "zerodha" if key else None
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
    """Capture which credential get_broker_name is called with."""
    module = ivchart_module if source == "ivchart" else vol_surface_module
    captured = {}

    def _spy(key):
        captured["key"] = key
        return "zerodha" if key else None

    monkeypatch.setattr(module, "get_broker_name", _spy)
    return captured


class TestIvchartBrokerSource:
    def test_apikey_only_client_gets_broker(self, client, monkeypatch):
        # The P1: an X-API-Key client authenticated fine but the route read
        # the broker from the empty session and returned 400.
        captured = _patch_broker_capture(monkeypatch, "ivchart")
        resp = client.post("/ivchart/api/iv-data", json=IV_PARAMS, headers={"X-API-Key": "valid-key"})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"
        # The broker was resolved from the decorator's verified apikey.
        assert captured["key"] == "valid-key"

    def test_query_param_apikey_gets_broker(self, client, monkeypatch):
        captured = _patch_broker_capture(monkeypatch, "ivchart")
        resp = client.post("/ivchart/api/iv-data?apikey=valid-key", json=IV_PARAMS)
        assert resp.status_code == 200
        assert captured["key"] == "valid-key"

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

    def test_unknown_apikey_still_rejected_by_broker_check(self, client, monkeypatch):
        # A credential that authenticates but has no broker registered (or a
        # lookup failure) must keep failing closed with the same 400.
        monkeypatch.setattr(ivchart_module, "get_broker_name", lambda key: None)
        resp = client.post("/ivchart/api/iv-data", json=IV_PARAMS, headers={"X-API-Key": "valid-key"})
        assert resp.status_code == 400
        assert resp.get_json()["message"] == "Broker not set in session"


class TestVolSurfaceBrokerSource:
    def test_apikey_only_client_gets_broker(self, client, monkeypatch):
        captured = _patch_broker_capture(monkeypatch, "vol_surface")
        resp = client.post(
            "/volsurface/api/surface-data", json=VS_PARAMS, headers={"X-API-Key": "valid-key"}
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"
        assert captured["key"] == "valid-key"

    def test_query_param_apikey_gets_broker(self, client, monkeypatch):
        captured = _patch_broker_capture(monkeypatch, "vol_surface")
        resp = client.post("/volsurface/api/surface-data?apikey=valid-key", json=VS_PARAMS)
        assert resp.status_code == 200
        assert captured["key"] == "valid-key"

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

    def test_unknown_apikey_still_rejected_by_broker_check(self, client, monkeypatch):
        monkeypatch.setattr(vol_surface_module, "get_broker_name", lambda key: None)
        resp = client.post(
            "/volsurface/api/surface-data", json=VS_PARAMS, headers={"X-API-Key": "valid-key"}
        )
        assert resp.status_code == 400
        assert resp.get_json()["message"] == "Broker not set in session"
