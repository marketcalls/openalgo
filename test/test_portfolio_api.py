import importlib.util
from pathlib import Path

import pytest
from flask import Flask
from flask_restx import Api

from limiter import limiter

_MODULE_PATH = Path(__file__).parents[1] / "restx_api" / "portfolio.py"
_SPEC = importlib.util.spec_from_file_location("portfolio_api_under_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
portfolio_api = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(portfolio_api)


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    monkeypatch.setattr(limiter, "enabled", False)
    rest_api = Api(app)
    rest_api.add_namespace(portfolio_api.api, path="/portfolio")
    return app.test_client()


def backtest_body(**overrides):
    body = {
        "apikey": "key",
        "holdings": [{"symbol": "INFY", "exchange": "NSE", "weight": 100}],
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "source": "db",
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/portfolio/backtest", backtest_body()),
        ("/portfolio/tearsheet", backtest_body()),
        ("/portfolio/holdings", {"apikey": "key", "source": "db"}),
    ],
)
def test_every_endpoint_rejects_an_invalid_api_key(client, monkeypatch, path, body):
    monkeypatch.setattr(portfolio_api, "verify_api_key", lambda _key: None)

    response = client.post(path, json=body)

    assert response.status_code == 403
    assert response.get_json()["message"] == "Invalid openalgo apikey"


def test_backtest_propagates_feed_token(client, monkeypatch):
    monkeypatch.setattr(portfolio_api, "verify_api_key", lambda _key: "user")

    def credentials(_key, *, include_feed_token=False):
        assert include_feed_token is True
        return "auth", "feed", "xts-broker"

    captured = {}

    def run(**kwargs):
        captured.update(kwargs)
        return True, {"status": "success"}, 200

    monkeypatch.setattr(portfolio_api, "get_auth_token_broker", credentials)
    monkeypatch.setattr(portfolio_api, "run_portfolio_backtest", run)

    response = client.post(
        "/portfolio/backtest",
        json=backtest_body(source="api"),
    )

    assert response.status_code == 200
    assert captured["auth_token"] == "auth"
    assert captured["feed_token"] == "feed"
    assert captured["broker"] == "xts-broker"


def test_tearsheet_propagates_feed_token(client, monkeypatch):
    monkeypatch.setattr(portfolio_api, "verify_api_key", lambda _key: "user")

    def credentials(_key, *, include_feed_token=False):
        assert include_feed_token is True
        return "auth", "feed", "xts-broker"

    captured = {}

    def generate(**kwargs):
        captured.update(kwargs)
        return True, "<html>report</html>", 200

    monkeypatch.setattr(portfolio_api, "get_auth_token_broker", credentials)
    monkeypatch.setattr(portfolio_api, "generate_tearsheet", generate)

    response = client.post(
        "/portfolio/tearsheet",
        json=backtest_body(
            source="api",
            cost_model="indian_equity",
            cost_exchange="BSE",
            charges={"brokerage": {"flat": 12.0}},
            gst_rate=0.2,
            slippage=0.001,
        ),
    )

    assert response.status_code == 200
    assert captured["auth_token"] == "auth"
    assert captured["feed_token"] == "feed"
    assert captured["broker"] == "xts-broker"
    assert captured["cost_model"] == "indian_equity"
    assert captured["cost_exchange"] == "BSE"
    assert captured["charge_overrides"] == {"brokerage": {"flat": 12.0}}
    assert captured["gst_rate"] == 0.2
    assert captured["slippage"] == 0.001


def test_holdings_history_propagates_feed_token(client, monkeypatch):
    monkeypatch.setattr(portfolio_api, "verify_api_key", lambda _key: "user")

    def credentials(_key, *, include_feed_token=False):
        assert include_feed_token is True
        return "auth", "feed", "xts-broker"

    captured = {}

    def analyse(**kwargs):
        captured.update(kwargs)
        return True, {"status": "success"}, 200

    monkeypatch.setattr(portfolio_api, "get_auth_token_broker", credentials)
    monkeypatch.setattr(portfolio_api, "analyse_live_holdings", analyse)

    response = client.post(
        "/portfolio/holdings",
        json={"apikey": "key", "source": "api"},
    )

    assert response.status_code == 200
    assert captured["auth_token"] == "auth"
    assert captured["feed_token"] == "feed"
    assert captured["broker"] == "xts-broker"


@pytest.mark.parametrize(
    ("path", "service_name", "message", "body"),
    [
        (
            "/portfolio/backtest",
            "run_portfolio_backtest",
            "Backtest failed.",
            backtest_body(),
        ),
        (
            "/portfolio/tearsheet",
            "generate_tearsheet",
            "Tearsheet generation failed.",
            backtest_body(),
        ),
        (
            "/portfolio/holdings",
            "analyse_live_holdings",
            "Analysis failed.",
            {"apikey": "key"},
        ),
    ],
)
def test_server_errors_never_leak_exception_text(
    client,
    monkeypatch,
    path,
    service_name,
    message,
    body,
):
    sentinel = "SECRET-SENTINEL-EXCEPTION"
    monkeypatch.setattr(portfolio_api, "verify_api_key", lambda _key: "user")
    monkeypatch.setattr(
        portfolio_api,
        "get_auth_token_broker",
        lambda _key, **_kwargs: ("auth", "feed", "broker"),
    )

    def explode(**_kwargs):
        raise RuntimeError(sentinel)

    monkeypatch.setattr(portfolio_api, service_name, explode)

    response = client.post(path, json=body)

    assert response.status_code == 500
    assert sentinel not in response.get_data(as_text=True)
    assert response.get_json()["message"] == message


def test_negative_nested_charge_is_a_schema_error(client, monkeypatch):
    def should_not_verify(_key):
        raise AssertionError("invalid request reached authentication")

    monkeypatch.setattr(portfolio_api, "verify_api_key", should_not_verify)

    response = client.post(
        "/portfolio/backtest",
        json=backtest_body(charges={"stt": {"rate": -0.01}}),
    )

    assert response.status_code == 400
