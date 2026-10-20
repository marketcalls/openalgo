"""A broker request refused as busy reaches the trader as HTTP 429 and a sentence.

Under the gthread worker a broker plugin's rate limiter refuses a request whose
turn would come later than a ceiling, instead of holding one of the fixed pool
of request threads for the whole wait. It raises
``utils.broker_backpressure.BrokerBusyError``, whose text says what happened
and what to do. The read-only data services used to catch every exception as a
500 carrying ``str(e)``, or as "internal error"; they now answer the refusal as
429 with that sentence. Everything else they return is unchanged.

Nothing raises BrokerBusyError under eventlet or the development server, so
there these paths are unreachable and those workers behave exactly as before;
the last test pins that a busy refusal cannot even be produced there.
"""

from __future__ import annotations

import types
from datetime import datetime

import pytest

import database.settings_db as settings_db
from services import (
    depth_service,
    funds_service,
    holdings_service,
    margin_service,
    option_chain_service,
    option_greeks_service,
    quotes_service,
    tradebook_service,
)
from services.broker_busy import BROKER_BUSY_STATUS, broker_busy_result, is_broker_busy
from utils import broker_backpressure, runtime
from utils.broker_backpressure import BROKER_BUSY_MESSAGE, BrokerBusyError

BUSY = (False, {"status": "error", "message": BROKER_BUSY_MESSAGE}, 429)


def _raise_busy(*args, **kwargs):
    raise BrokerBusyError()


def _raise_other(*args, **kwargs):
    raise RuntimeError("connection reset by broker")


def _data_module(**methods):
    """A broker ``api.data`` module whose BrokerData has the given methods."""

    class BrokerData:
        def __init__(self, auth_token, feed_token=None):
            pass

    for name, fn in methods.items():
        setattr(BrokerData, name, lambda self, *a, _fn=fn, **k: _fn(*a, **k))
    return types.SimpleNamespace(BrokerData=BrokerData)


@pytest.fixture(autouse=True)
def _live_mode(monkeypatch):
    monkeypatch.setattr(settings_db, "get_analyze_mode", lambda: False)
    yield


def test_the_helper_carries_the_exceptions_sentence():
    assert broker_busy_result(BrokerBusyError(), "x") == BUSY
    custom = BrokerBusyError("Your broker allows 10 orders a second.")
    assert broker_busy_result(custom, "x")[1]["message"] == "Your broker allows 10 orders a second."
    assert BROKER_BUSY_STATUS == 429 and is_broker_busy(429) and not is_broker_busy(500)


# --- quotes, multiquotes, depth ------------------------------------------------


def test_quotes(monkeypatch):
    monkeypatch.setattr(quotes_service, "validate_symbol_exchange", lambda s, e: (True, None))
    monkeypatch.setattr(
        quotes_service, "import_broker_module", lambda b: _data_module(get_quotes=_raise_busy)
    )
    assert quotes_service.get_quotes_with_auth("t", None, "zerodha", "SBIN", "NSE") == BUSY

    monkeypatch.setattr(
        quotes_service, "import_broker_module", lambda b: _data_module(get_quotes=_raise_other)
    )
    ok, body, status = quotes_service.get_quotes_with_auth("t", None, "zerodha", "SBIN", "NSE")
    assert (ok, status, body["message"]) == (False, 500, "connection reset by broker")


def test_multiquotes_native(monkeypatch):
    monkeypatch.setattr(quotes_service, "validate_symbol_exchange", lambda s, e: (True, None))
    monkeypatch.setattr(
        quotes_service, "import_broker_module", lambda b: _data_module(get_multiquotes=_raise_busy)
    )
    symbols = [{"symbol": "SBIN", "exchange": "NSE"}, {"symbol": "INFY", "exchange": "NSE"}]
    assert quotes_service.get_multiquotes_with_auth("t", None, "zerodha", symbols) == BUSY


def test_multiquotes_fallback_stops_at_the_first_busy_symbol(monkeypatch):
    calls = []

    def get_quotes(symbol, exchange):
        calls.append(symbol)
        if symbol == "INFY":
            raise BrokerBusyError()
        return {"ltp": 1.0}

    monkeypatch.setattr(quotes_service, "validate_symbol_exchange", lambda s, e: (True, None))
    monkeypatch.setattr(
        quotes_service, "import_broker_module", lambda b: _data_module(get_quotes=get_quotes)
    )
    symbols = [{"symbol": s, "exchange": "NSE"} for s in ("SBIN", "INFY", "TCS")]
    assert quotes_service.get_multiquotes_with_auth("t", None, "zerodha", symbols) == BUSY
    assert calls == ["SBIN", "INFY"]


def test_multiquotes_fallback_still_records_other_errors_per_symbol(monkeypatch):
    def get_quotes(symbol, exchange):
        if symbol == "INFY":
            raise RuntimeError("no such token")
        return {"ltp": 1.0}

    monkeypatch.setattr(quotes_service, "validate_symbol_exchange", lambda s, e: (True, None))
    monkeypatch.setattr(
        quotes_service, "import_broker_module", lambda b: _data_module(get_quotes=get_quotes)
    )
    symbols = [{"symbol": s, "exchange": "NSE"} for s in ("SBIN", "INFY")]
    ok, body, status = quotes_service.get_multiquotes_with_auth("t", None, "zerodha", symbols)
    assert (ok, status) == (True, 200)
    assert body["results"][1] == {"symbol": "INFY", "exchange": "NSE", "error": "no such token"}


def test_depth(monkeypatch):
    monkeypatch.setattr(depth_service, "validate_symbol_exchange", lambda s, e: (True, None))
    monkeypatch.setattr(
        depth_service, "import_broker_module", lambda b: _data_module(get_depth=_raise_busy)
    )
    assert depth_service.get_depth_with_auth("t", None, "zerodha", "SBIN", "NSE") == BUSY


# --- account reads ------------------------------------------------------------


def test_funds(monkeypatch):
    module = types.SimpleNamespace(get_margin_data=_raise_busy)
    monkeypatch.setattr(funds_service, "import_broker_module", lambda b: module)
    assert funds_service.get_funds_with_auth("t", "zerodha") == BUSY


def test_holdings(monkeypatch):
    funcs = {
        "get_holdings": _raise_busy,
        "map_portfolio_data": lambda d: d,
        "calculate_portfolio_statistics": lambda d: {},
        "transform_holdings_data": lambda d: d,
    }
    monkeypatch.setattr(holdings_service, "import_broker_module", lambda b: funcs)
    assert holdings_service.get_holdings_with_auth("t", "zerodha") == BUSY


def test_tradebook(monkeypatch):
    funcs = {
        "get_trade_book": _raise_busy,
        "map_trade_data": lambda trade_data: trade_data,
        "transform_tradebook_data": lambda d: d,
    }
    monkeypatch.setattr(tradebook_service, "import_broker_module", lambda b: funcs)
    assert tradebook_service.get_tradebook_with_auth("t", "zerodha") == BUSY


def test_margin_logs_and_answers_429(monkeypatch):
    logged = []
    monkeypatch.setattr(
        margin_service,
        "executor",
        types.SimpleNamespace(submit=lambda fn, *args: logged.append(args)),
    )
    module = types.SimpleNamespace(calculate_margin_api=_raise_busy)
    monkeypatch.setattr(margin_service, "import_broker_module", lambda b: module)

    result = margin_service.calculate_margin_with_auth([], "t", "zerodha", {"apikey": "k"})
    assert result == BUSY
    assert logged == [("margin", {"apikey": "k"}, BUSY[1])]


def test_margin_passes_a_busy_response_status_through(monkeypatch):
    """A plugin may refuse with busy_response() instead of raising."""
    monkeypatch.setattr(margin_service, "executor", types.SimpleNamespace(submit=lambda *a: None))
    module = types.SimpleNamespace(
        calculate_margin_api=lambda positions, auth: broker_backpressure.busy_response()[:2]
    )
    monkeypatch.setattr(margin_service, "import_broker_module", lambda b: module)
    assert margin_service.calculate_margin_with_auth([], "t", "zerodha", {}) == BUSY


# --- option chain -------------------------------------------------------------


def _chain_symbols(base, expiry, strikes_with_labels, exchange):
    rows = []
    for item in strikes_with_labels:
        strike = item["strike"]
        leg = {"exists": True, "label": "ATM", "lotsize": 75, "tick_size": 0.05}
        rows.append(
            {
                "strike": strike,
                "ce": {**leg, "symbol": f"{base}{expiry}{int(strike)}CE"},
                "pe": {**leg, "symbol": f"{base}{expiry}{int(strike)}PE"},
            }
        )
    return rows


@pytest.fixture
def chain_stubs(monkeypatch):
    oc = option_chain_service
    monkeypatch.setattr(
        oc, "get_quotes", lambda **k: (True, {"data": {"ltp": 24010.0, "prev_close": 0}}, 200)
    )
    monkeypatch.setattr(
        oc, "get_available_strikes", lambda *a: [23900.0, 23950.0, 24000.0, 24050.0, 24100.0]
    )
    monkeypatch.setattr(oc, "get_option_symbols_for_chain", _chain_symbols)
    monkeypatch.setattr(oc, "get_auth_token_broker", lambda *a, **k: (None, None, None))
    return oc


def _chain():
    return option_chain_service.get_option_chain("NIFTY", "NSE_INDEX", "28OCT25", 1, "key")


def test_option_chain_refused_quotes_are_a_429_not_a_chain_of_zeros(chain_stubs, monkeypatch):
    monkeypatch.setattr(chain_stubs, "get_multiquotes", lambda **k: BUSY)
    assert _chain() == BUSY


def test_option_chain_other_quote_failures_are_unchanged(chain_stubs, monkeypatch):
    """Before and after: a failed multiquote still returns the chain, unpriced."""
    failure = (False, {"status": "error", "message": "Failed to fetch multiquotes"}, 500)
    monkeypatch.setattr(chain_stubs, "get_multiquotes", lambda **k: failure)
    ok, body, status = _chain()
    assert (ok, status) == (True, 200)
    assert all(row["ce"]["ltp"] == 0 for row in body["chain"])


def test_option_chain_busy_on_the_fyers_fast_path_is_a_429(chain_stubs, monkeypatch):
    module = _data_module(get_option_chain=_raise_busy)
    monkeypatch.setattr(chain_stubs, "get_auth_token_broker", lambda *a, **k: ("t", None, "fyers"))
    monkeypatch.setattr(chain_stubs, "import_broker_module", lambda b: module)
    monkeypatch.setattr(chain_stubs, "get_br_symbol", lambda s, e: "NSE:NIFTY50-INDEX")
    multiquotes = []
    monkeypatch.setattr(chain_stubs, "get_multiquotes", lambda **k: multiquotes.append(k))

    assert _chain() == BUSY
    assert multiquotes == []


def test_option_chain_underlying_ltp_refusal_keeps_its_429(chain_stubs, monkeypatch):
    monkeypatch.setattr(chain_stubs, "get_quotes", lambda **k: BUSY)
    ok, body, status = _chain()
    assert (ok, status) == (False, 429)
    assert BROKER_BUSY_MESSAGE in body["message"]


# --- multi-leg Greeks -----------------------------------------------------------


@pytest.fixture
def greeks_stubs(monkeypatch):
    gs = option_greeks_service
    monkeypatch.setattr(
        gs,
        "parse_option_symbol",
        lambda symbol, exchange, expiry_time=None: ("NIFTY", datetime(2099, 1, 1), 24000.0, "CE"),
    )
    monkeypatch.setattr(gs, "_resolve_forward_price", lambda *a, **k: None)
    monkeypatch.setattr(
        "services.quotes_service.get_quotes",
        lambda symbol, exchange, api_key=None: (True, {"data": {"ltp": 24010.0}}, 200),
    )
    return gs


LEGS = [{"symbol": "NIFTY01JAN9924000CE", "exchange": "NFO"}]


def test_multi_greeks_refused_prices_are_a_429(greeks_stubs, monkeypatch):
    monkeypatch.setattr(
        "services.quotes_service.get_multiquotes", lambda symbols, api_key=None: BUSY
    )
    assert greeks_stubs.get_multi_option_greeks(LEGS, api_key="k") == BUSY


def test_multi_greeks_refused_spot_is_a_429(greeks_stubs, monkeypatch):
    monkeypatch.setattr(
        "services.quotes_service.get_quotes", lambda symbol, exchange, api_key=None: BUSY
    )
    called = []
    monkeypatch.setattr(
        "services.quotes_service.get_multiquotes",
        lambda symbols, api_key=None: called.append(symbols),
    )
    assert greeks_stubs.get_multi_option_greeks(LEGS, api_key="k") == BUSY
    assert called == []


def test_multi_greeks_other_price_failures_are_unchanged(greeks_stubs, monkeypatch):
    failure = (False, {"status": "error", "message": "Failed to fetch multiquotes"}, 500)
    monkeypatch.setattr(
        "services.quotes_service.get_multiquotes", lambda symbols, api_key=None: failure
    )
    ok, body, status = greeks_stubs.get_multi_option_greeks(LEGS, api_key="k")
    assert (ok, status) == (False, 200)
    assert body["data"][0]["message"] == "Option LTP not available"


# --- the ticker endpoint calls the broker's history directly ---------------------


@pytest.mark.parametrize("fmt", ["json", "txt"])
def test_ticker_history_refused_as_busy_is_a_429(monkeypatch, fmt):
    import inspect

    from flask import Flask

    from restx_api import ticker

    monkeypatch.setattr(ticker, "get_auth_token_broker", lambda key: ("tok", "zerodha"))
    monkeypatch.setattr(
        ticker, "import_broker_module", lambda b: _data_module(get_history=_raise_busy)
    )
    get = inspect.unwrap(ticker.Ticker.get)  # below the rate-limit decorator
    url = f"/api/v1/ticker/NSE:SBIN?apikey=k&interval=D&from=2026-09-01&to=2026-09-20&format={fmt}"
    with Flask(__name__).test_request_context(url):
        result = get(ticker.Ticker(), "NSE:SBIN")

    if fmt == "json":
        assert result.status_code == 429
        assert result.get_json() == {"status": "error", "message": BROKER_BUSY_MESSAGE}
    else:
        response, status = result
        assert status == 429
        assert response.get_data(as_text=True).strip() == BROKER_BUSY_MESSAGE


# --- nothing is refused outside gthread ----------------------------------------


def test_without_gthread_no_queue_wait_is_refused(monkeypatch):
    """The only way BrokerBusyError is produced is gated on the gthread worker."""
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    assert broker_backpressure.max_queue_wait("data") is None
    assert broker_backpressure.max_queue_wait("order") is None
    broker_backpressure.check_queue_wait(3600.0, kind="data")
    broker_backpressure.check_queue_wait(3600.0, kind="order")

    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    with pytest.raises(BrokerBusyError):
        broker_backpressure.check_queue_wait(3600.0, kind="data")
