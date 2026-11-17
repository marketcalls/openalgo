"""Tradejini streaming: Quote omits L5-only totals until a book exists, and
Depth keeps the L1 quote fields."""

import websocket_proxy  # noqa: F401  isort:skip

import pytest

from broker.tradejini.streaming.tradejini_adapter import TradejiniWebSocketAdapter


def _sub(mode):
    return {
        "symbol": "SBIN",
        "exchange": "NSE",
        "brexchange": "NSE",
        "token": "3045",
        "mode": mode,
    }


L1 = {
    "msgType": "L1",
    "symbol": "3045_NSE",
    "ltp": 810.5,
    "open": 800.0,
    "high": 815.0,
    "low": 798.0,
    "close": 805.0,
    "chng": 5.5,
    "chngPer": 0.68,
    "atp": 808.2,
    "ltq": 15,
    "vol": 123456,
    "OI": 0,
    "ltt": "05/11/2026 14:25:31",
}

L5 = {
    "msgType": "L5",
    "symbol": "3045_NSE",
    "totBuyQty": 5000,
    "totSellQty": 7000,
    "bid": [{"price": 810.4, "qty": 10, "no": 2}],
    "ask": [{"price": 810.6, "qty": 12, "no": 3}],
}


@pytest.fixture
def adapter():
    a = TradejiniWebSocketAdapter()
    a.published = []
    a.publish_market_data = lambda topic, data: a.published.append((topic, data))
    return a


def _last(adapter, suffix):
    return [data for topic, data in adapter.published if topic.endswith(suffix)][-1]


def test_quote_omits_totals_without_a_book(adapter):
    adapter.subscriptions = {"q": _sub(2)}
    adapter._on_data(None, dict(L1))

    quote = _last(adapter, "_QUOTE")
    assert "total_buy_quantity" not in quote
    assert "total_sell_quantity" not in quote
    assert quote["percent_change"] == 0.68
    assert quote["change_percent"] == 0.68
    assert quote["last_trade_time"] == "05/11/2026 14:25:31"


def test_quote_uses_book_totals_when_depth_subscribed(adapter):
    adapter.subscriptions = {"q": _sub(2), "d": _sub(3)}
    adapter._on_data(None, dict(L5))
    adapter._on_data(None, dict(L1))

    quote = _last(adapter, "_QUOTE")
    assert quote["total_buy_quantity"] == 5000
    assert quote["total_sell_quantity"] == 7000


def test_depth_keeps_l1_quote_fields(adapter):
    adapter.subscriptions = {"d": _sub(3)}
    adapter._on_data(None, dict(L1))
    adapter._on_data(None, dict(L5))

    depth = _last(adapter, "_DEPTH")
    assert depth["average_price"] == 808.2
    assert depth["last_quantity"] == 15
    assert depth["percent_change"] == 0.68
    assert depth["change_percent"] == 0.68
    assert depth["change"] == 5.5
    assert depth["last_trade_time"] == "05/11/2026 14:25:31"
    assert depth["total_buy_quantity"] == 5000
