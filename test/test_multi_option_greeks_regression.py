import os
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("API_KEY_PEPPER", "test-pepper-value-at-least-32-chars")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import services.option_greeks_service as greeks_service  # noqa: E402


def test_greeks_expiry_check_treats_naive_expiry_as_ist(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return datetime(2026, 6, 2, 15, 45, tzinfo=tz)
            return datetime(2026, 6, 2, 10, 15)

    monkeypatch.setattr(greeks_service, "datetime", FixedDateTime)

    years_to_expiry, days_to_expiry = greeks_service.calculate_time_to_expiry(
        datetime(2026, 6, 2, 15, 30)
    )

    assert years_to_expiry == 0.0
    assert days_to_expiry == 0.0


def test_multi_option_greeks_converts_expired_legs_to_zero_greeks(monkeypatch):
    symbols = [
        {"symbol": "NIFTY02JUN2623500PE", "exchange": "NFO"},
        {"symbol": "NIFTY02JUN2623400PE", "exchange": "NFO"},
    ]

    monkeypatch.setattr(
        greeks_service,
        "parse_option_symbol",
        lambda symbol, exchange, expiry_time=None: (
            "NIFTY",
            datetime(2026, 6, 2, 15, 30),
            23500.0 if "23500" in symbol else 23400.0,
            "PE",
        ),
    )
    monkeypatch.setattr(
        "services.quotes_service.get_quotes",
        lambda symbol, exchange, api_key=None: (
            True,
            {"status": "success", "data": {"ltp": 23483.55}},
            200,
        ),
    )
    monkeypatch.setattr(
        "services.quotes_service.get_multiquotes",
        lambda symbols, api_key=None: (
            True,
            {
                "status": "success",
                "results": [
                    {"symbol": item["symbol"], "exchange": item["exchange"], "data": {"ltp": 16.4}}
                    for item in symbols
                ],
            },
            200,
        ),
    )
    monkeypatch.setattr(
        greeks_service,
        "calculate_greeks",
        lambda **kwargs: (
            False,
            {"status": "error", "message": "Option has expired on 02-Jun-2026"},
            400,
        ),
    )

    success, response, status_code = greeks_service.get_multi_option_greeks(symbols)

    assert success is True
    assert status_code == 200
    assert response["status"] == "success"
    assert response["summary"] == {"total": 2, "success": 2, "failed": 0}
    assert all(item["status"] == "success" for item in response["data"])
    assert all(item["implied_volatility"] == 0 for item in response["data"])
    assert all(item["greeks"] == {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "rho": 0} for item in response["data"])
    assert all("expired" in item["note"] for item in response["data"])


def test_multi_option_greeks_keeps_per_exchange_state_for_duplicate_symbols(monkeypatch):
    symbols = [
        {"symbol": "RELIANCE28MAR243000CE", "exchange": "NFO"},
        {"symbol": "RELIANCE28MAR243000CE", "exchange": "BFO"},
    ]
    ltp_by_exchange = {"NFO": 41.5, "BFO": 63.25}

    monkeypatch.setattr(
        greeks_service,
        "parse_option_symbol",
        lambda symbol, exchange, expiry_time=None: (
            "RELIANCE",
            datetime(2026, 3, 28, 15, 30),
            3000.0,
            "CE",
        ),
    )
    monkeypatch.setattr(greeks_service, "_resolve_forward_price", lambda *a, **k: None)
    monkeypatch.setattr(
        "services.quotes_service.get_quotes",
        lambda symbol, exchange, api_key=None: (
            True,
            {"status": "success", "data": {"ltp": 3010.0}},
            200,
        ),
    )
    monkeypatch.setattr(
        "services.quotes_service.get_multiquotes",
        lambda symbols, api_key=None: (
            True,
            {
                "status": "success",
                "results": [
                    {
                        "symbol": item["symbol"],
                        "exchange": item["exchange"],
                        "data": {"ltp": ltp_by_exchange[item["exchange"]]},
                    }
                    for item in symbols
                ],
            },
            200,
        ),
    )
    monkeypatch.setattr(
        greeks_service,
        "calculate_greeks",
        lambda **kwargs: (
            True,
            {
                "status": "success",
                "symbol": kwargs["option_symbol"],
                "exchange": kwargs["exchange"],
                "option_price": kwargs["option_price"],
            },
            200,
        ),
    )

    success, response, status_code = greeks_service.get_multi_option_greeks(symbols)

    assert success is True
    assert set(response) == {"status", "data", "summary"}
    assert response["summary"] == {"total": 2, "success": 2, "failed": 0}

    by_exchange = {item["exchange"]: item for item in response["data"]}
    assert set(by_exchange) == {"NFO", "BFO"}
    assert by_exchange["NFO"]["option_price"] == 41.5
    assert by_exchange["BFO"]["option_price"] == 63.25


def test_multi_option_greeks_falls_back_to_requested_exchange(monkeypatch):
    symbols = [
        {"symbol": "NIFTY28MAR2420800CE", "exchange": "NFO"},
        {"symbol": "NIFTY28MAR2420900CE", "exchange": "NFO"},
    ]

    monkeypatch.setattr(
        greeks_service,
        "parse_option_symbol",
        lambda symbol, exchange, expiry_time=None: (
            "NIFTY",
            datetime(2026, 3, 28, 15, 30),
            20800.0 if "20800" in symbol else 20900.0,
            "CE",
        ),
    )
    monkeypatch.setattr(greeks_service, "_resolve_forward_price", lambda *a, **k: None)
    monkeypatch.setattr(
        "services.quotes_service.get_quotes",
        lambda symbol, exchange, api_key=None: (
            True,
            {"status": "success", "data": {"ltp": 20750.0}},
            200,
        ),
    )
    monkeypatch.setattr(
        "services.quotes_service.get_multiquotes",
        lambda symbols, api_key=None: (
            True,
            {
                "status": "success",
                "results": [
                    {"symbol": item["symbol"], "data": {"ltp": 145.3}} for item in symbols
                ],
            },
            200,
        ),
    )
    monkeypatch.setattr(
        greeks_service,
        "calculate_greeks",
        lambda **kwargs: (
            True,
            {
                "status": "success",
                "symbol": kwargs["option_symbol"],
                "exchange": kwargs["exchange"],
                "option_price": kwargs["option_price"],
            },
            200,
        ),
    )

    success, response, status_code = greeks_service.get_multi_option_greeks(symbols)

    assert success is True
    assert response["summary"] == {"total": 2, "success": 2, "failed": 0}
    assert all(item["option_price"] == 145.3 for item in response["data"])


def test_multi_option_greeks_does_not_guess_ambiguous_exchange(monkeypatch):
    symbols = [
        {"symbol": "RELIANCE28MAR243000CE", "exchange": "NFO"},
        {"symbol": "RELIANCE28MAR243000CE", "exchange": "BFO"},
        {"symbol": "RELIANCE28MAR243100CE", "exchange": "NFO"},
    ]

    monkeypatch.setattr(
        greeks_service,
        "parse_option_symbol",
        lambda symbol, exchange, expiry_time=None: (
            "RELIANCE",
            datetime(2026, 3, 28, 15, 30),
            3000.0 if "3000" in symbol else 3100.0,
            "CE",
        ),
    )
    monkeypatch.setattr(greeks_service, "_resolve_forward_price", lambda *a, **k: None)
    monkeypatch.setattr(
        "services.quotes_service.get_quotes",
        lambda symbol, exchange, api_key=None: (
            True,
            {"status": "success", "data": {"ltp": 3010.0}},
            200,
        ),
    )
    monkeypatch.setattr(
        "services.quotes_service.get_multiquotes",
        lambda symbols, api_key=None: (
            True,
            {
                "status": "success",
                "results": [
                    {"symbol": item["symbol"], "data": {"ltp": 41.5}} for item in symbols
                ],
            },
            200,
        ),
    )
    monkeypatch.setattr(
        greeks_service,
        "calculate_greeks",
        lambda **kwargs: (
            True,
            {
                "status": "success",
                "symbol": kwargs["option_symbol"],
                "exchange": kwargs["exchange"],
                "option_price": kwargs["option_price"],
            },
            200,
        ),
    )

    success, response, status_code = greeks_service.get_multi_option_greeks(symbols)

    assert response["summary"] == {"total": 3, "success": 1, "failed": 2}
    priced = [item for item in response["data"] if item["status"] == "success"]
    assert len(priced) == 1
    assert priced[0]["symbol"] == "RELIANCE28MAR243100CE"


def test_multi_option_greeks_keeps_per_leg_underlying_for_identical_symbols(monkeypatch):
    symbols = [
        {"symbol": "NIFTY30DEC2524000CE", "exchange": "NFO"},
        {
            "symbol": "NIFTY30DEC2524000CE",
            "exchange": "NFO",
            "underlying_symbol": "NIFTY30DEC25FUT",
            "underlying_exchange": "NFO",
        },
    ]
    spot_by_symbol = {"NIFTY": 24000.0, "NIFTY30DEC25FUT": 24500.0}

    monkeypatch.setattr(
        greeks_service,
        "parse_option_symbol",
        lambda symbol, exchange, expiry_time=None: (
            "NIFTY",
            datetime(2025, 12, 30, 15, 30),
            24000.0,
            "CE",
        ),
    )
    monkeypatch.setattr(greeks_service, "_resolve_forward_price", lambda *a, **k: None)
    monkeypatch.setattr(
        "services.quotes_service.get_quotes",
        lambda symbol, exchange, api_key=None: (
            True,
            {"status": "success", "data": {"ltp": spot_by_symbol[symbol]}},
            200,
        ),
    )
    monkeypatch.setattr(
        "services.quotes_service.get_multiquotes",
        lambda symbols, api_key=None: (
            True,
            {
                "status": "success",
                "results": [
                    {"symbol": item["symbol"], "exchange": item["exchange"], "data": {"ltp": 100.0}}
                    for item in symbols
                ],
            },
            200,
        ),
    )
    monkeypatch.setattr(
        greeks_service,
        "calculate_greeks",
        lambda **kwargs: (
            True,
            {
                "status": "success",
                "symbol": kwargs["option_symbol"],
                "exchange": kwargs["exchange"],
                "spot_price": kwargs["spot_price"],
            },
            200,
        ),
    )

    success, response, status_code = greeks_service.get_multi_option_greeks(symbols)

    assert success is True
    assert response["summary"] == {"total": 2, "success": 2, "failed": 0}
    assert [item["spot_price"] for item in response["data"]] == [24000.0, 24500.0]
