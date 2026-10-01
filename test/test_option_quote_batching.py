"""Regression tests for option-symbol quote batching at broker boundaries."""

import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from broker.dhan.api import data as dhan_data  # noqa: E402
from broker.fyers.api import data as fyers_data  # noqa: E402
from broker.zebu.api import data as zebu_data  # noqa: E402
from services import option_symbol_service as oss  # noqa: E402


def test_only_dhan_uses_the_single_upstream_request_batch(monkeypatch):
    def broker_for_key(_api_key):
        return "auth-token", "dhan"

    monkeypatch.setattr(oss, "get_auth_token_broker", broker_for_key)
    assert oss._get_option_symbol_quote_batch_limit("test-api-key") == 1000

    for broker in ("fyers", "zebu"):
        monkeypatch.setattr(
            oss,
            "get_auth_token_broker",
            lambda _api_key, broker=broker: ("auth-token", broker),
        )
        assert oss._get_option_symbol_quote_batch_limit("test-api-key") == 1


def test_dhan_multiquote_batch_makes_one_upstream_request(monkeypatch):
    symbols = [
        {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
        {"symbol": "NIFTY28OCT2523500CE", "exchange": "NFO"},
    ]
    security_ids = {symbols[0]["symbol"]: "101", symbols[1]["symbol"]: "202"}
    upstream_calls = []

    monkeypatch.setattr(
        dhan_data,
        "get_token",
        lambda symbol, exchange: security_ids[symbol],
    )

    def fake_get_api_response(endpoint, auth, method="POST", payload="", retry_count=0):
        upstream_calls.append((endpoint, auth, method, payload))
        request = json.loads(payload)
        response_data = {
            segment: {
                str(security_id): {
                    "last_price": 100.0,
                    "ohlc": {"open": 99.0, "high": 101.0, "low": 98.0, "close": 99.5},
                    "depth": {},
                }
                for security_id in security_ids_for_segment
            }
            for segment, security_ids_for_segment in request.items()
        }
        return {"status": "success", "data": response_data}

    monkeypatch.setattr(dhan_data, "get_api_response", fake_get_api_response)

    results = dhan_data.BrokerData("auth-token").get_multiquotes(symbols)

    assert len(upstream_calls) == 1
    assert upstream_calls[0][0] == "/v2/marketfeed/quote"
    assert len(results) == len(symbols)


def test_fyers_derivative_multiquote_adds_one_depth_request_per_symbol(monkeypatch):
    symbols = [
        {"symbol": "NIFTY28OCT2523500CE", "exchange": "NFO"},
        {"symbol": "NIFTY28OCT2523500PE", "exchange": "NFO"},
    ]
    upstream_calls = []

    def fake_get_br_symbol(symbol, exchange):
        return f"{exchange}:{symbol}"

    monkeypatch.setattr(fyers_data, "get_br_symbol", fake_get_br_symbol)

    def fake_get_api_response(endpoint, auth, method="GET", payload="", _retry_count=0):
        upstream_calls.append(endpoint)
        if endpoint.startswith("/data/quotes?symbols="):
            encoded_symbols = endpoint.split("=", 1)[1]
            broker_symbols = urllib.parse.unquote(encoded_symbols).split(",")
            return {
                "s": "ok",
                "d": [
                    {"s": "ok", "n": broker_symbol, "v": {"lp": 100.0}}
                    for broker_symbol in broker_symbols
                ],
            }

        if endpoint.startswith("/data/depth?symbol="):
            encoded_symbol = endpoint.split("?symbol=", 1)[1].split("&", 1)[0]
            broker_symbol = urllib.parse.unquote(encoded_symbol)
            return {"s": "ok", "d": {broker_symbol: {"oi": 7}}}

        raise AssertionError(f"Unexpected Fyers endpoint: {endpoint}")

    monkeypatch.setattr(fyers_data, "get_api_response", fake_get_api_response)

    results = fyers_data.BrokerData("auth-token").get_multiquotes(symbols)

    assert len(upstream_calls) == 1 + len(symbols)
    assert sum(endpoint.startswith("/data/quotes?") for endpoint in upstream_calls) == 1
    assert sum(endpoint.startswith("/data/depth?") for endpoint in upstream_calls) == len(symbols)
    assert len(results) == len(symbols)


def test_zebu_multiquote_makes_one_upstream_request_per_symbol(monkeypatch):
    symbols = [
        {"symbol": "SBIN", "exchange": "NSE"},
        {"symbol": "INFY", "exchange": "NSE"},
    ]
    upstream_payloads = []

    monkeypatch.setattr(zebu_data, "USE_ASYNC", False)
    monkeypatch.setattr(
        zebu_data,
        "get_br_symbol",
        lambda symbol, exchange: f"{exchange}:{symbol}",
    )
    monkeypatch.setattr(
        zebu_data,
        "get_token",
        lambda symbol, exchange: {"SBIN": "101", "INFY": "202"}[symbol],
    )
    monkeypatch.setenv("BROKER_API_KEY", "test-user:::test-client")

    class FakeResponse:
        def json(self):
            return {
                "stat": "Ok",
                "bp1": "99",
                "sp1": "101",
                "o": "100",
                "h": "102",
                "l": "98",
                "lp": "100",
                "c": "99",
                "v": "10",
                "oi": "5",
            }

    def fake_post(url, **kwargs):
        upstream_payloads.append(json.loads(kwargs["content"].removeprefix("jData=")))
        return FakeResponse()

    monkeypatch.setattr(zebu_data.httpx, "post", fake_post)

    results = zebu_data.BrokerData("auth-token").get_multiquotes(symbols)

    assert len(upstream_payloads) == len(symbols)
    assert {payload["token"] for payload in upstream_payloads} == {"101", "202"}
    assert len(results) == len(symbols)
