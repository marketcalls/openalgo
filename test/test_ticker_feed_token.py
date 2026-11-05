import inspect
from types import SimpleNamespace

import pandas as pd
from flask import Flask

from restx_api import ticker


def _ticker_get():
    return inspect.unwrap(ticker.Ticker.get)


def test_ticker_passes_feed_token_to_broker_data(monkeypatch):
    captured = {}

    class FakeBrokerData:
        def __init__(self, auth_token, feed_token=None):
            captured["auth_token"] = auth_token
            captured["feed_token"] = feed_token

        def get_history(self, *_args):
            return pd.DataFrame(
                [{"timestamp": 1_799_000_000, "open": 1, "high": 2, "low": 1, "close": 2, "volume": 10}]
            )

    monkeypatch.setattr(
        ticker,
        "get_auth_token_broker",
        lambda key, include_feed_token=False: (
            "auth-token",
            "feed-token",
            "xtsbroker",
        ),
    )
    monkeypatch.setattr(
        ticker, "import_broker_module", lambda _broker: SimpleNamespace(BrokerData=FakeBrokerData)
    )

    url = "/api/v1/ticker/NSE:SBIN?apikey=test-key&interval=D&from=2026-09-01&to=2026-09-20"
    with Flask(__name__).test_request_context(url):
        response = _ticker_get()(ticker.Ticker(), "NSE:SBIN")

    assert response.status_code == 200
    assert captured == {"auth_token": "auth-token", "feed_token": "feed-token"}


def test_ticker_initializes_response_format_before_handling_early_errors():
    url = "/api/v1/ticker/invalid?format=txt"
    with Flask(__name__).test_request_context(url):
        response, status = _ticker_get()(ticker.Ticker(), 123)

    assert status == 500
    assert response.get_data(as_text=True) == "An unexpected error occurred"
