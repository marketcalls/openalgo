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
    spot_by_exchange = {"NSE": 3010.0, "BSE": 3040.0}
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
    monkeypatch.setattr(
        greeks_service,
        "get_underlying_exchange",
        lambda base_symbol, options_exchange: "NSE" if options_exchange == "NFO" else "BSE",
    )
    monkeypatch.setattr(greeks_service, "_resolve_forward_price", lambda *a, **k: None)
    monkeypatch.setattr(
        "services.quotes_service.get_quotes",
        lambda symbol, exchange, api_key=None: (
            True,
            {"status": "success", "data": {"ltp": spot_by_exchange[exchange]}},
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
                "spot_price": kwargs["spot_price"],
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
    assert by_exchange["NFO"]["spot_price"] == 3010.0
    assert by_exchange["BFO"]["spot_price"] == 3040.0
