"""Ibulls prices MARKET and SL-M orders with Market Price Protection (#2392).

Ibulls' RMS may refuse a native MARKET or SL-M order from an API session, so
OpenAlgo sends them already priced, from the shared slabs in utils/mpp_slab:

- MARKET -> LIMIT at the LTP moved by the slab, above it for a BUY and below
  it for a SELL, at least one tick past it, on a tick;
- SL-M -> STOPLIMIT whose limit is the trigger moved the same way.

The plugin used to look up the feed token of a hard-coded username for the
quote, priced a BUY off the bid and a SELL off the ask, and rounded to two
decimals. The LTP now comes from the feed token stored with the Ibulls
session, whoever places the order.
"""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from flask import Flask, session

import broker.ibulls.api.order_api as oa
import broker.ibulls.mapping.transform_data as td
import database.auth_db as auth_db
from broker.ibulls.api.data import BrokerData

OPTION = "NIFTY25NOV2524000CE"
TICKS = {("SBIN", "NSE"): 0.05, ("PENNY", "NSE"): 0.01, (OPTION, "NFO"): 0.05}


@pytest.fixture
def market(monkeypatch):
    """Master contract tick sizes, LTPs and the stored Ibulls session. Records
    every row lookup, feed token lookup and LTP request an order makes."""
    state = SimpleNamespace(ltp={}, rows=[], feed_names=[], ltp_calls=[], info_calls=[])

    def symbol_info(symbol, exchange):
        state.info_calls.append((symbol, exchange))
        tick = TICKS.get((symbol, exchange))
        return SimpleNamespace(tick_size=tick) if tick is not None else None

    class Query:
        def filter_by(self, **kwargs):
            state.rows.append(kwargs)
            return SimpleNamespace(first=lambda: SimpleNamespace(name="alice"))

    def feed_token(name):
        state.feed_names.append(name)
        return "stored-feed"

    def get_ltp(self, symbol, exchange):
        state.ltp_calls.append((self.auth_token, self.feed_token, symbol))
        return state.ltp.get(symbol, 0.0)

    monkeypatch.setattr(td, "get_symbol_info", symbol_info)
    monkeypatch.setattr(auth_db, "Auth", SimpleNamespace(query=Query()))
    monkeypatch.setattr(auth_db, "get_feed_token", feed_token)
    monkeypatch.setattr(BrokerData, "get_ltp", get_ltp)
    return state


def _order(symbol="SBIN", exchange="NSE", action="BUY", pricetype="MARKET", **extra):
    return {
        "symbol": symbol,
        "exchange": exchange,
        "action": action,
        "pricetype": pricetype,
        "product": "MIS",
        "quantity": "1",
        "price": "0",
        "trigger_price": "0",
        **extra,
    }


def _on_tick(price, tick):
    return Decimal(str(price)) % Decimal(str(tick)) == 0


def _d(value):
    return Decimal(str(value))


def _send(order, sess=None):
    """transform_data as a browser (sess dict), an API call ({}), or a strategy
    thread outside any request (None)."""
    if sess is None:
        return td.transform_data(order, "2885", "interactive-token")
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context("/"):
        session.update(sess)
        return td.transform_data(order, "2885", "interactive-token")


# --------------------------------------------------------------------------
# MARKET -> protected LIMIT off the LTP
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symbol", "exchange", "ltp", "action", "limit"),
    [
        # Equity above 500: 0.5%. 800.5 x 1.005 = 804.5025, up to 804.55.
        ("SBIN", "NSE", 800.5, "BUY", 804.55),
        # 800.5 x 0.995 = 796.4975, down to 796.45.
        ("SBIN", "NSE", 800.5, "SELL", 796.45),
        # Options below 10: 5%, wider than equity.
        (OPTION, "NFO", 5.0, "BUY", 5.25),
        (OPTION, "NFO", 5.0, "SELL", 4.75),
        # 5% of 0.05 is less than a tick: at least one tick past the LTP.
        (OPTION, "NFO", 0.05, "BUY", 0.1),
        # A SELL cannot go below the smallest price there is.
        (OPTION, "NFO", 0.05, "SELL", 0.05),
    ],
)
def test_a_market_order_goes_out_as_a_protected_limit(market, symbol, exchange, ltp, action, limit):
    market.ltp[symbol] = ltp

    sent = _send(_order(symbol, exchange, action))

    tick = TICKS[(symbol, exchange)]
    assert sent["orderType"] == "LIMIT"
    assert float(sent["limitPrice"]) == limit
    assert _on_tick(sent["limitPrice"], tick)
    if action == "BUY":
        assert _d(sent["limitPrice"]) >= _d(ltp) + _d(tick)
    elif ltp > tick:
        assert _d(sent["limitPrice"]) <= _d(ltp) - _d(tick)


@pytest.mark.parametrize(
    "sess",
    [{"user": "bob"}, {}, None],
    ids=["signed-in browser", "API order without a cookie", "outside a request"],
)
def test_the_ltp_comes_from_the_stored_ibulls_session(market, sess):
    market.ltp["SBIN"] = 800.5

    _send(_order(), sess)

    assert market.rows == [{"broker": "ibulls", "is_revoked": False}]
    assert market.feed_names == ["alice"]
    assert market.ltp_calls == [("interactive-token", "stored-feed", "SBIN")]


def test_a_market_order_without_an_ltp_goes_out_as_market(market):
    sent = _send(_order())

    assert (sent["orderType"], sent["limitPrice"]) == ("MARKET", "0")


def test_a_market_order_without_a_tick_size_goes_out_as_market_without_a_quote(market):
    market.ltp["UNLISTED"] = 100.0

    sent = _send(_order("UNLISTED"))

    assert (sent["orderType"], sent["limitPrice"]) == ("MARKET", "0")
    assert market.ltp_calls == []


# --------------------------------------------------------------------------
# SL-M -> STOPLIMIT beyond its own trigger
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("symbol", "exchange", "trigger", "action", "limit"),
    [
        ("SBIN", "NSE", 800.0, "BUY", 804.0),
        ("SBIN", "NSE", 800.0, "SELL", 796.0),
        # Equity below 100: 2%.
        ("PENNY", "NSE", 50.0, "BUY", 51.0),
        ("PENNY", "NSE", 50.0, "SELL", 49.0),
        (OPTION, "NFO", 5.0, "SELL", 4.75),
        # 5% of 0.10 is less than a tick: one tick past the trigger.
        (OPTION, "NFO", 0.10, "BUY", 0.15),
        (OPTION, "NFO", 0.10, "SELL", 0.05),
        # A trigger off the tick grid still gets a full tick of room: snapping
        # alone would leave 0.10 (0.04 above 0.06) and 0.10 (0.04 below 0.14).
        (OPTION, "NFO", 0.06, "BUY", 0.15),
        (OPTION, "NFO", 0.14, "SELL", 0.05),
    ],
)
def test_an_sl_m_order_goes_out_as_a_stop_limit_beyond_its_trigger(
    market, symbol, exchange, trigger, action, limit
):
    market.ltp[symbol] = 1.0  # far from the trigger: must not be used

    sent = _send(_order(symbol, exchange, action, "SL-M", trigger_price=str(trigger)))

    tick = TICKS[(symbol, exchange)]
    assert sent["orderType"] == "STOPLIMIT"
    assert float(sent["limitPrice"]) == limit
    assert sent["stopPrice"] == str(trigger)
    assert _on_tick(sent["limitPrice"], tick)
    if action == "BUY":
        assert _d(sent["limitPrice"]) >= _d(trigger) + _d(tick)
    else:
        assert _d(sent["limitPrice"]) <= _d(trigger) - _d(tick)
    assert market.ltp_calls == []


def test_an_sl_m_sell_too_low_to_protect_is_refused(market):
    with pytest.raises(td.OrderFieldError, match="too low"):
        _send(_order(OPTION, "NFO", "SELL", "SL-M", trigger_price="0.05"))


def test_an_sl_m_without_a_tick_size_is_refused(market):
    with pytest.raises(td.OrderFieldError, match="tick size"):
        _send(_order("UNLISTED", "NSE", "BUY", "SL-M", trigger_price="100"))


def test_a_tick_size_that_cannot_be_read_is_treated_as_missing(market, monkeypatch):
    def unreadable(symbol, exchange):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(td, "get_symbol_info", unreadable)
    market.ltp["SBIN"] = 800.5

    sent = _send(_order())

    assert (sent["orderType"], sent["limitPrice"]) == ("MARKET", "0")
    with pytest.raises(td.OrderFieldError, match="tick size"):
        _send(_order(pricetype="SL-M", trigger_price="800"))


@pytest.mark.parametrize(
    ("pricetype", "price", "trigger", "order_type"),
    [("LIMIT", "801.5", "0", "LIMIT"), ("SL", "801.5", "800", "STOPLIMIT")],
)
def test_limit_and_sl_orders_keep_their_own_prices(market, pricetype, price, trigger, order_type):
    sent = _send(_order(pricetype=pricetype, price=price, trigger_price=trigger))

    assert (sent["orderType"], sent["limitPrice"], sent["stopPrice"]) == (
        order_type,
        price,
        trigger,
    )
    assert market.ltp_calls == [] and market.rows == []


# --------------------------------------------------------------------------
# The order paths: place, modify, close-all
# --------------------------------------------------------------------------


class _Client:
    def __init__(self):
        self.sent = []

    def _answer(self, body):
        return SimpleNamespace(
            status_code=200,
            json=lambda: body,
            text=json.dumps(body),
        )

    def post(self, url, headers=None, json=None):
        self.sent.append(("POST", json))
        return self._answer({"type": "success", "result": {"AppOrderID": 101}})

    def put(self, url, headers=None, content=None):
        self.sent.append(("PUT", json.loads(content)))
        return self._answer({"type": "success", "result": {"AppOrderID": 101}})


@pytest.fixture
def client(monkeypatch):
    c = _Client()
    monkeypatch.setattr(oa, "get_httpx_client", lambda: c)
    monkeypatch.setattr(oa, "get_token", lambda symbol, exchange: "2885")
    monkeypatch.setattr(oa, "get_br_symbol", lambda symbol, exchange: f"{symbol}-EQ")
    return c


def test_place_order_refuses_an_sl_m_it_cannot_price_before_sending(market, client):
    res, body, orderid = oa.place_order_api(
        _order("UNLISTED", "NSE", "SELL", "SL-M", trigger_price="100"), "interactive-token"
    )

    assert res.status == 400
    assert body["status"] == "error" and "tick size" in body["message"]
    assert orderid is None
    assert client.sent == []


def test_place_order_sends_a_market_order_as_a_protected_limit(market, client):
    market.ltp["SBIN"] = 800.5

    res, _, orderid = oa.place_order_api(_order(), "interactive-token")

    assert (res.status, orderid) == (200, 101)
    _, sent = client.sent[0]
    assert (sent["orderType"], sent["limitPrice"]) == ("LIMIT", "804.55")


def test_a_modify_to_market_is_priced_by_the_openalgo_symbol(market, client):
    market.ltp["SBIN"] = 800.5

    oa.modify_order({**_order(), "orderid": "101"}, "interactive-token")

    _, sent = client.sent[0]
    assert (sent["modifiedOrderType"], sent["modifiedLimitPrice"]) == ("LIMIT", "804.55")
    assert ("SBIN", "NSE") in market.info_calls
    assert ("SBIN-EQ", "NSE") not in market.info_calls


def test_a_modify_to_an_sl_m_it_cannot_price_is_refused(market, client):
    answer, status = oa.modify_order(
        {**_order("UNLISTED", "NSE", "BUY", "SL-M", trigger_price="100"), "orderid": "101"},
        "interactive-token",
    )

    assert status == 400 and "tick size" in answer["message"]
    assert client.sent == []


def test_close_all_squares_off_with_protected_limits(market, monkeypatch):
    market.ltp["SBIN"] = 800.5
    positions = [
        {
            "Quantity": "10",
            "ExchangeSegment": "NSECM",
            "ExchangeInstrumentId": 3045,
            "ProductType": "MIS",
        },
        {
            "Quantity": "-5",
            "ExchangeSegment": "NSECM",
            "ExchangeInstrumentId": 9999,
            "ProductType": "MIS",
        },
        {
            "Quantity": "0",
            "ExchangeSegment": "NSECM",
            "ExchangeInstrumentId": 3045,
            "ProductType": "MIS",
        },
    ]
    placed = []
    monkeypatch.setattr(oa, "get_positions", lambda auth: {"result": {"positionList": positions}})
    monkeypatch.setattr(
        oa, "get_symbol", lambda token, exchange: "SBIN" if token == "3045" else None
    )
    monkeypatch.setattr(
        oa, "place_order_api", lambda payload, auth: placed.append(payload) or (None, {}, None)
    )

    oa.close_all_positions("apikey", "interactive-token")

    first, second = placed
    assert (first["orderSide"], first["orderType"], first["limitPrice"]) == (
        "SELL",
        "LIMIT",
        "796.45",
    )
    # A position whose symbol cannot be resolved still goes out, as MARKET.
    assert (second["orderSide"], second["orderType"], second["limitPrice"]) == (
        "BUY",
        "MARKET",
        "0",
    )


def test_a_square_off_that_cannot_be_priced_still_goes_out_and_the_rest_follow(market, monkeypatch):
    market.ltp["SBIN"] = 800.5
    positions = [
        {
            "Quantity": "10",
            "ExchangeSegment": "NSECM",
            "ExchangeInstrumentId": 1,
            "ProductType": "MIS",
        },
        {
            "Quantity": "10",
            "ExchangeSegment": "NSECM",
            "ExchangeInstrumentId": 2,
            "ProductType": "MIS",
        },
    ]
    placed = []

    def symbol_of(token, exchange):
        if token == "1":
            raise RuntimeError("database is locked")
        return "SBIN"

    monkeypatch.setattr(oa, "get_positions", lambda auth: {"result": {"positionList": positions}})
    monkeypatch.setattr(oa, "get_symbol", symbol_of)
    monkeypatch.setattr(
        oa, "place_order_api", lambda payload, auth: placed.append(payload) or (None, {}, None)
    )

    oa.close_all_positions("apikey", "interactive-token")

    assert [(p["orderType"], p["limitPrice"]) for p in placed] == [
        ("MARKET", "0"),
        ("LIMIT", "796.45"),
    ]
