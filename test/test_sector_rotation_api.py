"""Security enforcement on the sector rotation endpoints.

Asserts the guarantees, not the happy path: an unauthenticated caller must not
reach the service, no input may arrive unvalidated, a broker-sourced map needs
a broker session, and an internal failure must not leak its detail.

Loads the resource module by path, matching test_sip_api_security.py.
"""

import importlib.util
from pathlib import Path

import pytest
from flask import Flask
from flask_restx import Api

from limiter import limiter

_MODULE_PATH = Path(__file__).parents[1] / "restx_api" / "sector_rotation.py"
_SPEC = importlib.util.spec_from_file_location("sector_rotation_api_under_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
rotation_api = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rotation_api)


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    monkeypatch.setattr(limiter, "enabled", False)
    rest_api = Api(app)
    rest_api.add_namespace(rotation_api.api, path="/sectorrotation")
    return app.test_client()


def body(**overrides):
    out = {"apikey": "key", "benchmark": "NIFTY", "timeframe": "daily", "source": "db"}
    out.update(overrides)
    return out


@pytest.mark.parametrize("source", ["db", "api"])
def test_an_invalid_api_key_never_reaches_the_service(client, monkeypatch, source):
    called = []
    monkeypatch.setattr(rotation_api, "verify_api_key", lambda _k: None)
    monkeypatch.setattr(
        rotation_api,
        "compute_sector_rotation",
        lambda **kw: called.append(kw) or (True, {}, 200),
    )

    response = client.post("/sectorrotation", json=body(source=source))

    assert response.status_code == 403
    assert called == []


def test_broker_source_requires_a_broker_session(client, monkeypatch):
    monkeypatch.setattr(rotation_api, "verify_api_key", lambda _k: "user")
    monkeypatch.setattr(rotation_api, "get_auth_token_broker", lambda *_a, **_k: (None, None, None))

    response = client.post("/sectorrotation", json=body(source="api"))

    assert response.status_code == 403
    assert "broker login" in response.get_json()["message"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"benchmark": "DOWJONES"},
        {"timeframe": "monthly"},
        {"source": "csv"},
        {"instruments": [{"symbol": "NIFTY30OCT26FUT", "exchange": "NFO"}]},
        {"instruments": [{"exchange": "NSE"}]},
        {"instruments": [{"symbol": f"S{i}", "exchange": "NSE"} for i in range(41)]},
    ],
)
def test_invalid_input_is_refused_before_the_service(client, monkeypatch, overrides):
    called = []
    monkeypatch.setattr(rotation_api, "verify_api_key", lambda _k: "user")
    monkeypatch.setattr(
        rotation_api,
        "compute_sector_rotation",
        lambda **kw: called.append(kw) or (True, {}, 200),
    )

    response = client.post("/sectorrotation", json=body(**overrides))

    assert response.status_code == 400
    assert called == []


def test_valid_request_passes_the_instrument_list_through(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(rotation_api, "verify_api_key", lambda _k: "user")

    def fake(**kw):
        seen.update(kw)
        return True, {"status": "success", "data": {}}, 200

    monkeypatch.setattr(rotation_api, "compute_sector_rotation", fake)

    response = client.post(
        "/sectorrotation",
        json=body(instruments=[{"symbol": "RELIANCE", "exchange": "NSE"}]),
    )

    assert response.status_code == 200
    assert seen["instruments"] == [{"symbol": "RELIANCE", "exchange": "NSE", "label": None}]
    assert seen["auth_token"] is None


def test_an_internal_failure_does_not_leak_detail(client, monkeypatch):
    monkeypatch.setattr(rotation_api, "verify_api_key", lambda _k: "user")

    def boom(**_kw):
        raise RuntimeError("duckdb path C:/secret/historify.duckdb is locked")

    monkeypatch.setattr(rotation_api, "compute_sector_rotation", boom)

    response = client.post("/sectorrotation", json=body())

    assert response.status_code == 500
    assert "secret" not in response.get_data(as_text=True)


def test_options_lists_sectors_benchmarks_and_exchanges(client):
    response = client.get("/sectorrotation/options")

    data = response.get_json()["data"]
    assert response.status_code == 200
    assert {"NIFTY", "SENSEX"} <= {b["symbol"] for b in data["benchmarks"]}
    assert "NIFTYIT" in {s["symbol"] for s in data["sectors"]}
    assert "NFO" not in data["exchanges"]
