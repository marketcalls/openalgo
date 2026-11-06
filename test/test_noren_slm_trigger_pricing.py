"""Regression contracts for GitHub issue #2390.

Shoonya, Flattrade and Firstock send an SL-M order as SL-LMT. The limit price
was computed from the LTP, so a SELL stop with trigger 980 while the LTP was
1000 went out with a limit near 995, above its own trigger. The limit must be
priced off the trigger: SELL below it, BUY above it, at least one tick past it.
An SL-M without a trigger price is refused.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest

pytest.importorskip("sqlalchemy")

BROKERS = ["shoonya", "flattrade", "firstock"]


class _FakeBrokerData:
    def __init__(self, auth_token):
        pass

    def get_quotes(self, symbol, exchange):
        return {"ltp": 1000.0, "bid": 999.95, "ask": 1000.05, "tick_size": 0.05}


def _transform(monkeypatch, broker):
    module = importlib.import_module(f"broker.{broker}.mapping.transform_data")
    monkeypatch.setattr(module, "get_br_symbol", lambda symbol, exchange: f"{symbol}-EQ")
    monkeypatch.setattr(
        module, "get_symbol_info", lambda symbol, exchange: types.SimpleNamespace(tick_size=0.05)
    )
    if hasattr(module, "BrokerData"):
        monkeypatch.setattr(module, "BrokerData", _FakeBrokerData)
    data_module = types.ModuleType(f"broker.{broker}.api.data")
    data_module.BrokerData = _FakeBrokerData
    monkeypatch.setitem(sys.modules, f"broker.{broker}.api.data", data_module)
    return module.transform_data


def _order(action, trigger):
    return {
        "apikey": "USER1",
        "symbol": "INFY",
        "exchange": "NSE",
        "action": action,
        "quantity": "1",
        "pricetype": "SL-M",
        "product": "MIS",
        "price": "0",
        "trigger_price": trigger,
    }


def _limit_and_type(payload):
    if "prc" in payload:
        return float(payload["prc"]), payload["prctyp"]
    return float(payload["price"]), payload["priceType"]


@pytest.mark.parametrize("broker", BROKERS)
def test_sell_slm_limit_is_below_trigger(monkeypatch, broker):
    transform = _transform(monkeypatch, broker)
    limit, order_type = _limit_and_type(transform(_order("SELL", "980"), "1594", "token"))
    assert order_type == "SL-LMT"
    assert limit < 980
    assert limit == pytest.approx(975.1)  # 980 less 0.5%, floored to the 0.05 tick


@pytest.mark.parametrize("broker", BROKERS)
def test_buy_slm_limit_is_above_trigger(monkeypatch, broker):
    transform = _transform(monkeypatch, broker)
    limit, order_type = _limit_and_type(transform(_order("BUY", "1020"), "1594", "token"))
    assert order_type == "SL-LMT"
    assert limit > 1020
    assert limit == pytest.approx(1025.1)  # 1020 plus 0.5%, ceiled to the 0.05 tick


@pytest.mark.parametrize("broker", BROKERS)
def test_slm_without_trigger_is_refused(monkeypatch, broker):
    transform = _transform(monkeypatch, broker)
    with pytest.raises(ValueError):
        transform(_order("SELL", "0"), "1594", "token")


def test_slm_limit_is_at_least_one_tick_past_trigger():
    from utils.mpp_slab import calculate_slm_protected_price

    # 5% of a 0.20 option is 0.01, under one 0.05 tick, so the tick wins.
    assert calculate_slm_protected_price(0.20, "SELL", instrument_type="CE", tick_size=0.05) == 0.15
    assert calculate_slm_protected_price(0.20, "BUY", instrument_type="CE", tick_size=0.05) == 0.25
    with pytest.raises(ValueError):
        calculate_slm_protected_price(0.05, "SELL", instrument_type="CE", tick_size=0.05)
