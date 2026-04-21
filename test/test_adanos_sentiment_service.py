import os
import sys
from unittest.mock import Mock

import httpx
import pytest
from flask import Blueprint, Flask
from flask_restx import Api

os.environ.setdefault("API_KEY_PEPPER", "a" * 64)
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["LOG_FORMAT"] = "[%(asctime)s] %(levelname)s in %(module)s: %(message)s"
os.environ["LOG_COLORS"] = "False"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import adanos_sentiment_service as sentiment_service


@pytest.fixture()
def market_sentiment_client():
    from limiter import limiter
    from restx_api.market_sentiment import api as market_sentiment_ns

    app = Flask(__name__)
    app.config["TESTING"] = True

    limiter.init_app(app)

    blueprint = Blueprint("test_api_v1", __name__, url_prefix="/api/v1")
    api = Api(blueprint, doc=False)
    api.add_namespace(market_sentiment_ns, path="/market/sentiment")
    app.register_blueprint(blueprint)

    return app.test_client()


def test_normalize_tickers_deduplicates_and_filters_invalid_values():
    assert sentiment_service.normalize_tickers(
        ["$tsla", "TSLA", " msft ", "bad ticker", "123", "AAPL"]
    ) == ["TSLA", "MSFT", "AAPL"]


def test_get_market_sentiment_returns_403_for_invalid_openalgo_apikey(monkeypatch):
    monkeypatch.setattr(sentiment_service, "verify_api_key", lambda _: None)

    success, response, status_code = sentiment_service.get_market_sentiment(
        api_key="bad-key",
        tickers=["TSLA"],
    )

    assert success is False
    assert status_code == 403
    assert response["message"] == "Invalid openalgo apikey"


def test_get_market_sentiment_fails_open_when_adanos_key_missing(monkeypatch):
    monkeypatch.setattr(sentiment_service, "verify_api_key", lambda _: "demo-user")
    monkeypatch.delenv("ADANOS_API_KEY", raising=False)

    get_client = Mock(side_effect=AssertionError("HTTP client should not be created"))
    monkeypatch.setattr(sentiment_service, "get_httpx_client", get_client)

    success, response, status_code = sentiment_service.get_market_sentiment(
        api_key="valid-openalgo-key",
        tickers=["TSLA", "AAPL"],
        source="all",
        days=7,
    )

    assert success is True
    assert status_code == 200
    assert response["data"]["enabled"] is False
    assert response["data"]["tickers"] == ["TSLA", "AAPL"]
    assert "disabled" in response["data"]["summary"].lower()


def test_get_market_sentiment_fetches_and_normalizes_compare_rows(monkeypatch):
    monkeypatch.setattr(sentiment_service, "verify_api_key", lambda _: "demo-user")
    monkeypatch.setenv("ADANOS_API_KEY", "adanos-test-key")
    monkeypatch.setenv("ADANOS_API_BASE_URL", "https://api.adanos.org")
    monkeypatch.setenv("ADANOS_SENTIMENT_DEFAULT_DAYS", "7")
    monkeypatch.setenv("ADANOS_API_TIMEOUT_MS", "9000")

    calls = []

    class FakeClient:
        def get(self, url, headers=None, params=None, timeout=None):
            calls.append(
                {
                    "url": url,
                    "headers": headers,
                    "params": params,
                    "timeout": timeout,
                }
            )
            return httpx.Response(
                200,
                json={
                    "stocks": [
                        {
                            "ticker": "TSLA",
                            "company_name": "Tesla, Inc.",
                            "sentiment_score": "0.31",
                            "buzz_score": "71.2",
                            "mentions": "140",
                            "trend": "rising",
                        }
                    ]
                },
            )

    monkeypatch.setattr(sentiment_service, "get_httpx_client", lambda: FakeClient())

    success, response, status_code = sentiment_service.get_market_sentiment(
        api_key="valid-openalgo-key",
        tickers=["$tsla", "bad ticker"],
        source="reddit",
        days=5,
    )

    assert success is True
    assert status_code == 200
    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.adanos.org/reddit/stocks/v1/compare"
    assert calls[0]["params"] == {"tickers": "TSLA", "days": 5}
    assert calls[0]["headers"]["X-API-Key"] == "adanos-test-key"
    assert calls[0]["timeout"] == 9
    assert response["data"]["enabled"] is True
    assert response["data"]["tickers"] == ["TSLA"]
    assert response["data"]["snapshots"][0]["stocks"][0]["buzz_score"] == 71.2
    assert "reddit: TSLA (Tesla, Inc.): sentiment=0.31, buzz=71.2, mentions=140, trend=rising" in response["data"]["summary"]


def test_get_market_sentiment_rejects_invalid_source(monkeypatch):
    monkeypatch.setattr(sentiment_service, "verify_api_key", lambda _: "demo-user")

    success, response, status_code = sentiment_service.get_market_sentiment(
        api_key="valid-openalgo-key",
        tickers=["TSLA"],
        source="finviz",
    )

    assert success is False
    assert status_code == 400
    assert "Invalid source" in response["message"]


def test_get_market_sentiment_clamps_days_for_internal_callers(monkeypatch):
    monkeypatch.setattr(sentiment_service, "verify_api_key", lambda _: "demo-user")
    monkeypatch.setenv("ADANOS_API_KEY", "adanos-test-key")
    monkeypatch.setenv("ADANOS_API_BASE_URL", "https://api.adanos.org")

    calls = []

    class FakeClient:
        def get(self, url, headers=None, params=None, timeout=None):
            calls.append(params)
            return httpx.Response(200, json={"stocks": []})

    monkeypatch.setattr(sentiment_service, "get_httpx_client", lambda: FakeClient())

    success, response, status_code = sentiment_service.get_market_sentiment(
        api_key="valid-openalgo-key",
        tickers=["TSLA"],
        source="reddit",
        days=99,
    )

    assert success is True
    assert status_code == 200
    assert response["data"]["days"] == 30
    assert calls[0] == {"tickers": "TSLA", "days": 30}


def test_market_sentiment_endpoint_rejects_non_json_requests(market_sentiment_client):
    response = market_sentiment_client.post(
        "/api/v1/market/sentiment/",
        data="apikey=test",
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 415
    assert response.get_json()["message"] == "Content-Type must be application/json"


def test_market_sentiment_endpoint_rejects_malformed_json_requests(market_sentiment_client):
    response = market_sentiment_client.post(
        "/api/v1/market/sentiment/",
        data='{"apikey":',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert response.get_json()["message"] == "Invalid or malformed JSON payload"
