"""Regression contracts for GitHub issue #2390 (Shoonya, Flattrade, Firstock:
SL-M converted to SL-LMT is priced off the LTP, not the trigger).

These brokers refuse SL-MKT from API sessions, so an SL-M goes out as SL-LMT
with a protective limit. The limit was computed from the LTP whenever a quote
was available: a SELL stop with trigger 980 while the LTP was 1000 went out
with a limit of about 995, above its trigger, so once triggered it rested away
from the market instead of exiting. The limit must come from the trigger:
SELL below it, BUY above it, at least one tick past it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import broker.firstock.api.order_api as firstock_orders
import broker.firstock.mapping.transform_data as firstock_map
import broker.flattrade.api.order_api as flattrade_orders
import broker.flattrade.mapping.transform_data as flattrade_map
import broker.shoonya.api.order_api as shoonya_orders
import broker.shoonya.mapping.transform_data as shoonya_map

LTP = 1000.0
TICK = 0.05


class _Quotes:
    """BrokerData stand-in: quote at LTP 1000, with or without a tick size."""

    tick_size = TICK

    def __init__(self, auth_token):
        pass

    def get_quotes(self, symbol, exchange):
        quote = {"ltp": LTP, "bid": LTP - 0.05, "ask": LTP + 0.05}
        if self.tick_size:
            quote["tick_size"] = self.tick_size
        return quote


class _NoTickQuotes(_Quotes):
    tick_size = None


@pytest.fixture
def market(monkeypatch):
    """Quote and master contract for SBIN on all three brokers, tick 0.05."""
    state = {"master_tick": TICK}

    def symbol_info(symbol, exchange):
        return SimpleNamespace(tick_size=state["master_tick"])

    for mod in (shoonya_map, flattrade_map, firstock_map):
        monkeypatch.setattr(mod, "get_br_symbol", lambda s, e: f"{s}-EQ")
        monkeypatch.setattr(mod, "get_symbol_info", symbol_info)
    monkeypatch.setattr("broker.shoonya.api.data.BrokerData", _Quotes)
    monkeypatch.setattr(flattrade_map, "BrokerData", _Quotes)
    monkeypatch.setattr("broker.firstock.api.data.BrokerData", _Quotes)
    return state


def order(action, trigger, pricetype="SL-M", **extra):
    data = {
        "apikey": "AB1234",
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": action,
        "quantity": "1",
        "pricetype": pricetype,
        "product": "MIS",
        "price": "0",
        "trigger_price": trigger,
    }
    data.update(extra)
    return data


def _price_and_type(broker, payload):
    if broker == "firstock":
        return float(payload["price"]), payload["priceType"], float(payload["triggerPrice"])
    return float(payload["prc"]), payload["prctyp"], float(payload["trgprc"])


BROKERS = {
    "shoonya": shoonya_map,
    "flattrade": flattrade_map,
    "firstock": firstock_map,
}


@pytest.mark.parametrize("broker", BROKERS)
def test_sell_stop_limit_lands_below_the_trigger(broker, market):
    payload = BROKERS[broker].transform_data(order("SELL", "980"), "token", "auth")
    price, prctyp, trigger = _price_and_type(broker, payload)

    assert prctyp == "SL-LMT"
    assert trigger == 980.0
    assert price < 980.0  # was ~995 off the LTP, above the trigger
    assert price == 975.1  # 980 less the 0.5% slab, floored to the tick


@pytest.mark.parametrize("broker", BROKERS)
def test_buy_stop_limit_lands_above_the_trigger(broker, market):
    payload = BROKERS[broker].transform_data(order("BUY", "1020"), "token", "auth")
    price, prctyp, trigger = _price_and_type(broker, payload)

    assert prctyp == "SL-LMT"
    assert trigger == 1020.0
    assert price > 1020.0  # was ~1005 off the LTP, below the trigger
    assert price == 1025.1  # 1020 plus the 0.5% slab, ceiled to the tick


@pytest.mark.parametrize("broker", BROKERS)
@pytest.mark.parametrize("trigger", ["0", "", None, "abc"])
def test_sl_m_without_a_trigger_is_refused(broker, trigger, market):
    with pytest.raises(BROKERS[broker].SLMOrderRefused, match="needs a trigger price"):
        BROKERS[broker].transform_data(order("SELL", trigger), "token", "auth")


@pytest.mark.parametrize("broker", BROKERS)
def test_limit_is_at_least_one_tick_past_the_trigger(broker, market):
    # A cheap option: the 5% slab of a 0.50 trigger is 0.025, under one tick.
    data = order("SELL", "0.5", symbol="NIFTY28NOV2526000CE", exchange="NFO")
    payload = BROKERS[broker].transform_data(data, "token", "auth")
    price, _, _ = _price_and_type(broker, payload)
    assert price == 0.45

    data = order("BUY", "0.5", symbol="NIFTY28NOV2526000CE", exchange="NFO")
    payload = BROKERS[broker].transform_data(data, "token", "auth")
    price, _, _ = _price_and_type(broker, payload)
    assert price == 0.55


@pytest.mark.parametrize("broker", BROKERS)
def test_sell_trigger_one_tick_above_zero_keeps_the_trigger(broker, market):
    data = order("SELL", "0.05", symbol="NIFTY28NOV2526000CE", exchange="NFO")
    payload = BROKERS[broker].transform_data(data, "token", "auth")
    price, prctyp, _ = _price_and_type(broker, payload)
    assert prctyp == "SL-LMT"
    assert price == 0.05


@pytest.mark.parametrize("broker", BROKERS)
def test_no_tick_size_anywhere_uses_the_trigger(broker, market, monkeypatch):
    market["master_tick"] = None
    monkeypatch.setattr("broker.shoonya.api.data.BrokerData", _NoTickQuotes)
    monkeypatch.setattr(flattrade_map, "BrokerData", _NoTickQuotes)
    payload = BROKERS[broker].transform_data(order("SELL", "980"), "token", "auth")
    price, prctyp, _ = _price_and_type(broker, payload)
    assert prctyp == "SL-LMT"
    assert price == 980.0


@pytest.mark.parametrize("broker", ["shoonya", "flattrade"])
def test_no_auth_token_prices_off_the_trigger_with_the_master_tick(broker, market):
    payload = BROKERS[broker].transform_data(order("SELL", "980"), "token", None)
    price, prctyp, _ = _price_and_type(broker, payload)
    assert prctyp == "SL-LMT"
    assert price == 975.1


@pytest.mark.parametrize("broker", BROKERS)
def test_market_orders_still_price_off_the_ltp(broker, market):
    payload = BROKERS[broker].transform_data(order("BUY", "0", pricetype="MARKET"), "token", "auth")
    price, prctyp, _ = _price_and_type(broker, payload)
    assert prctyp == "LMT"
    assert price == 1005.0  # LTP 1000 plus the 0.5% slab


# --- refusal reaches the trader as a 400, and nothing reaches the broker ---


class _NoHttp:
    def __getattr__(self, name):
        raise AssertionError("the broker must not be called for a refused order")


ORDER_APIS = {
    "shoonya": shoonya_orders,
    "flattrade": flattrade_orders,
    "firstock": firstock_orders,
}


@pytest.mark.parametrize("broker", ORDER_APIS)
def test_place_order_api_refuses_sl_m_without_trigger(broker, market, monkeypatch):
    mod = ORDER_APIS[broker]
    monkeypatch.setenv("BROKER_API_KEY", "AB1234:::client_API")
    monkeypatch.setattr(mod, "get_token", lambda s, e: "3045")
    monkeypatch.setattr(mod, "get_httpx_client", lambda: _NoHttp())

    response, data, orderid = mod.place_order_api(order("SELL", "0"), "auth")

    assert response.status == 400
    assert data["status"] == "error"
    assert "needs a trigger price" in data["message"]
    assert orderid is None


def test_firstock_modify_prices_sl_m_off_the_trigger(market):
    data = order("SELL", "980", orderid="1")
    payload = firstock_map.transform_modify_order_data(data, "token", "auth")
    assert payload["priceType"] == "SL-LMT"
    assert float(payload["price"]) == 975.1


def test_firstock_modify_refuses_sl_m_without_trigger(market, monkeypatch):
    monkeypatch.setenv("BROKER_API_KEY", "AB1234_API")
    monkeypatch.setattr(firstock_orders, "get_token", lambda s, e: "3045")
    monkeypatch.setattr(firstock_orders, "get_httpx_client", lambda: _NoHttp())

    result, status = firstock_orders.modify_order(order("SELL", "0", orderid="1"), "auth")

    assert status == 400
    assert "needs a trigger price" in result["message"]
