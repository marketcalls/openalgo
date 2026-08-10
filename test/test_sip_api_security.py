"""Security enforcement on the SIP endpoints.

Asserts the guarantees, not the happy path: an unauthenticated caller must not
reach the service, no input may arrive unvalidated, and an internal failure
must not leak its detail to the caller.

Loads the resource module by path, matching test_portfolio_api.py -- importing
it as a package pulls in a chain that `test/sandbox/` shadows under pytest.
"""

import importlib.util
from pathlib import Path

import pytest
from flask import Flask
from flask_restx import Api
from marshmallow import ValidationError

from limiter import limiter

_MODULE_PATH = Path(__file__).parents[1] / "restx_api" / "sip.py"
_SPEC = importlib.util.spec_from_file_location("sip_api_under_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
sip_api = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sip_api)


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    monkeypatch.setattr(limiter, "enabled", False)
    rest_api = Api(app)
    rest_api.add_namespace(sip_api.api, path="/sip")
    return app.test_client()


def body(**overrides):
    out = {
        "apikey": "key", "symbol": "INFY", "exchange": "NSE",
        "start_date": "2020-01-01", "end_date": "2024-01-01",
        "amount": 5000, "source": "db",
    }
    out.update(overrides)
    return out


# --------------------------------------------------------------- authentication


@pytest.mark.parametrize("source", ["db", "api"])
def test_an_invalid_api_key_is_rejected_for_every_source(client, monkeypatch, source):
    """A source='db' run needs no broker session, but local history is still
    the user's data. Skipping the key check there would leave it readable by
    anyone who can reach the endpoint."""
    monkeypatch.setattr(sip_api, "verify_api_key", lambda _k: None)

    response = client.post("/sip/backtest", json=body(source=source))

    assert response.status_code == 403
    assert response.get_json()["message"] == "Invalid openalgo apikey"


def test_the_service_is_never_called_without_a_valid_key(client, monkeypatch):
    """The strongest form: prove execution stops before the service."""
    called = []
    monkeypatch.setattr(sip_api, "verify_api_key", lambda _k: None)
    monkeypatch.setattr(
        sip_api, "run_sip_backtest",
        lambda **kw: called.append(kw) or (True, {}, 200),
    )

    client.post("/sip/backtest", json=body())

    assert called == [], "the service ran despite an invalid API key"


def test_source_api_requires_a_broker_session(client, monkeypatch):
    monkeypatch.setattr(sip_api, "verify_api_key", lambda _k: "user")
    monkeypatch.setattr(
        sip_api, "get_auth_token_broker",
        lambda _k, include_feed_token=False: (None, None, None),
    )

    response = client.post("/sip/backtest", json=body(source="api"))

    assert response.status_code == 403
    assert "No broker session" in response.get_json()["message"]


def test_source_db_does_not_require_a_broker_session(client, monkeypatch):
    """Backtesting at the weekend is the normal case."""
    monkeypatch.setattr(sip_api, "verify_api_key", lambda _k: "user")
    monkeypatch.setattr(sip_api, "run_sip_backtest",
                        lambda **kw: (True, {"status": "success"}, 200))

    assert client.post("/sip/backtest", json=body(source="db")).status_code == 200


def test_credentials_are_passed_through_for_source_api(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(sip_api, "verify_api_key", lambda _k: "user")

    def creds(_key, *, include_feed_token=False):
        assert include_feed_token is True
        return ("auth", "feed", "zerodha")

    monkeypatch.setattr(sip_api, "get_auth_token_broker", creds)
    monkeypatch.setattr(sip_api, "run_sip_backtest",
                        lambda **kw: seen.update(kw) or (True, {}, 200))

    client.post("/sip/backtest", json=body(source="api"))

    assert seen["auth_token"] == "auth"
    assert seen["feed_token"] == "feed"
    assert seen["broker"] == "zerodha"


# ------------------------------------------------------------------- validation


@pytest.mark.parametrize("field,bad", [
    ("exchange", "NFO"),           # derivatives cannot be SIP'd
    ("exchange", "NSE_INDEX"),     # an index cannot be bought
    ("frequency", "daily"),
    ("day_of_month", 31),          # does not exist in every month
    ("day_of_month", 0),
    ("amount", 0),
    ("amount", -100),
    ("step_up_percent", -5),
    ("brokerage_percent", 99),
    ("source", "s3"),
    ("benchmark_exchange", "NSE"), # must be an index exchange
    ("symbol", "A" * 500),
])
def test_bad_input_is_rejected_with_400(client, monkeypatch, field, bad):
    monkeypatch.setattr(sip_api, "verify_api_key", lambda _k: "user")
    called = []
    monkeypatch.setattr(sip_api, "run_sip_backtest",
                        lambda **kw: called.append(kw) or (True, {}, 200))

    response = client.post("/sip/backtest", json=body(**{field: bad}))

    assert response.status_code == 400
    assert called == [], f"{field}={bad!r} reached the service unvalidated"


def test_missing_apikey_is_a_400_not_a_crash(client):
    payload = body()
    del payload["apikey"]
    assert client.post("/sip/backtest", json=payload).status_code == 400


def test_defaults_are_safe():
    d = sip_api.backtest_schema.load(body())
    assert d["source"] == "db", "must not default to hitting the broker API"
    assert d["frequency"] == "monthly"
    assert d["step_up_percent"] == 0.0
    assert d["brokerage_percent"] == 0.0
    assert d["benchmark"] is None


def test_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        sip_api.backtest_schema.load(body(sneaky_field="x"))


# ------------------------------------------------------------ failure disclosure


def test_an_internal_error_does_not_leak_details(client, monkeypatch):
    monkeypatch.setattr(sip_api, "verify_api_key", lambda _k: "user")

    def boom(**_kw):
        raise RuntimeError("/opt/secret/path exploded with token abc123")

    monkeypatch.setattr(sip_api, "run_sip_backtest", boom)

    response = client.post("/sip/backtest", json=body())

    assert response.status_code == 500
    message = response.get_json()["message"]
    assert message == "SIP backtest failed."
    assert "secret" not in message and "abc123" not in message


def test_both_endpoints_are_rate_limited():
    """A full run performs hundreds of simulations, so an unlimited endpoint
    is a denial-of-service vector against the user's own instance.

    Reads the file rather than using inspect.getsource: a module loaded via
    spec_from_file_location reports its classes as built-ins.
    """
    src = _MODULE_PATH.read_text(encoding="utf-8")
    for cls in ("class SipBacktest(", "class SipFrequencies("):
        start = src.index(cls)
        # The decorator sits just above the method inside the class body.
        block = src[start:start + 600]
        assert "@limiter.limit(API_RATE_LIMIT)" in block, f"{cls} is not rate limited"
