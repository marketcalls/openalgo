"""Definedge streaming: every subscribed mode receives each tick, built from
the merged per-scrip snapshot, with OpenAlgo's reference keys."""

import websocket_proxy  # noqa: F401  isort:skip

import pytest

from broker.definedge.streaming.definedge_adapter import DefinedgeWebSocketAdapter


def _sub(mode):
    return {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "brexchange": "NSE",
        "definedge_exchange": "NSE",
        "token": "2885",
        "scrip": "NSE|2885",
        "mode": mode,
        "depth_level": 5,
        "actual_depth": 5,
    }


@pytest.fixture
def adapter():
    a = DefinedgeWebSocketAdapter()
    a.published = []
    a.publish_market_data = lambda topic, data: a.published.append((topic, data))
    return a


def _topics(adapter, suffix):
    return [data for topic, data in adapter.published if topic.endswith(suffix)]


TOUCHLINE = {
    "t": "tf",
    "e": "NSE",
    "tk": "2885",
    "ft": "1730784000",
    "lp": "1395.40",
    "pc": "0.32",
    "v": "11238602",
    "o": "1382.60",
    "h": "1398.00",
    "l": "1378.50",
    "c": "1391.00",
    "ap": "1391.24",
}

DEPTH = {
    "t": "df",
    "e": "NSE",
    "tk": "2885",
    "lp": "1395.50",
    "ltt": "14:25:31",
    "ltq": "7",
    "tbq": "120952",
    "tsq": "131730",
    "bp1": "1395.40",
    "bq1": "10",
    "sp1": "1395.60",
    "sq1": "12",
    "bp2": "1395.35",
    "sp2": "1395.65",
}


def test_touchline_reaches_quote_even_when_depth_subscribed_first(adapter):
    adapter.subscriptions = {"d": _sub(3), "q": _sub(2)}

    adapter._on_data(None, dict(TOUCHLINE))

    quotes = _topics(adapter, "_QUOTE")
    assert len(quotes) == 1
    assert quotes[0]["ltp"] == 1395.40
    assert quotes[0]["percent_change"] == 0.32
    # No depth data cached yet: Depth gets nothing rather than an empty book
    assert _topics(adapter, "_DEPTH") == []
    assert all(data for _, data in adapter.published)


def test_depth_tick_publishes_full_quote_and_depth(adapter):
    adapter.subscriptions = {"l": _sub(1), "q": _sub(2), "d": _sub(3)}

    adapter._on_data(None, dict(TOUCHLINE))
    adapter.published.clear()
    adapter._on_depth_data(None, dict(DEPTH))

    quote = _topics(adapter, "_QUOTE")[-1]
    assert quote["ltp"] == 1395.50
    assert quote["open"] == 1382.60
    assert quote["average_price"] == 1391.24
    assert quote["percent_change"] == 0.32
    assert quote["last_quantity"] == 7
    assert quote["last_trade_time"] == "14:25:31"
    # ltt carries the broker's last trade time, not the feed time
    assert quote["ltt"] == "14:25:31"

    depth = _topics(adapter, "_DEPTH")[-1]
    assert depth["average_price"] == 1391.24
    assert depth["percent_change"] == 0.32
    assert depth["total_buy_quantity"] == 120952
    assert depth["total_sell_quantity"] == 131730
    assert depth["total_buy_qty"] == 120952
    assert depth["last_quantity"] == 7
    assert depth["ltt"] == "14:25:31"
    assert depth["depth"]["buy"][0]["price"] == 1395.40

    assert _topics(adapter, "_LTP")[-1]["ltp"] == 1395.50


def test_touchline_after_depth_refreshes_depth_with_quote_fields(adapter):
    adapter.subscriptions = {"d": _sub(3), "q": _sub(2)}
    adapter._on_depth_data(None, dict(DEPTH))
    adapter.published.clear()

    adapter._on_data(None, {"t": "tf", "e": "NSE", "tk": "2885", "lp": "1396.00"})

    depth = _topics(adapter, "_DEPTH")[-1]
    assert depth["ltp"] == 1396.00
    assert depth["total_buy_quantity"] == 120952
    assert _topics(adapter, "_QUOTE")[-1]["ltp"] == 1396.00


def test_reference_keys_absent_when_feed_did_not_send_them(adapter):
    adapter.subscriptions = {"q": _sub(2)}
    adapter._on_data(None, {"t": "tf", "e": "NSE", "tk": "2885", "lp": "10", "ft": "123"})

    quote = _topics(adapter, "_QUOTE")[-1]
    assert "last_quantity" not in quote
    assert "last_trade_time" not in quote
    assert "percent_change" not in quote
    assert quote["ltt"] == "123"


def test_other_exchange_token_is_not_published(adapter):
    adapter.subscriptions = {"q": _sub(2)}
    adapter._on_data(None, {"t": "tf", "e": "BSE", "tk": "2885", "lp": "10"})
    assert adapter.published == []
