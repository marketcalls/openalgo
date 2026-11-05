"""mstock streaming: ticks route on exchange type and token, and carry the
trade time and last_quantity the packet holds."""

import websocket_proxy  # noqa: F401  isort:skip

import pytest

from broker.mstock.streaming.mstock_adapter import MstockWebSocketAdapter


@pytest.fixture
def adapter():
    a = MstockWebSocketAdapter()
    a.published = []
    a.publish_market_data = lambda topic, data: a.published.append((topic, data))
    a.subscriptions = {
        "nse": {
            "symbol": "INFY",
            "exchange": "NSE",
            "brexchange": "NSE",
            "token": "1594",
            "mode": 2,
            "depth_level": 5,
            "exchange_type": 1,
        },
        "bse": {
            "symbol": "OTHER",
            "exchange": "BSE",
            "brexchange": "BSE",
            "token": "1594",
            "mode": 2,
            "depth_level": 5,
            "exchange_type": 3,
        },
    }
    return a


def _quote_packet(**overrides):
    packet = {
        "subscription_mode": 2,
        "exchange_type": 1,
        "token": "1594",
        "exchange_timestamp": 1730784000000,
        "ltp": 1500.5,
        "last_traded_qty": 25,
        "avg_price": 1498.0,
        "volume": 1000,
        "total_buy_qty": 10.0,
        "total_sell_qty": 20.0,
        "open": 1490.0,
        "high": 1505.0,
        "low": 1485.0,
        "close": 1495.0,
        "last_traded_timestamp": 0,
    }
    packet.update(overrides)
    return packet


def test_tick_routes_on_exchange_type_and_token(adapter):
    adapter._on_data(_quote_packet())

    assert [topic for topic, _ in adapter.published] == ["NSE_INFY_QUOTE"]


def test_quote_carries_exchange_time_and_last_quantity(adapter):
    adapter._on_data(_quote_packet())

    data = adapter.published[0][1]
    assert data["last_quantity"] == 25
    assert data["last_trade_quantity"] == 25
    assert data["last_trade_time"] == 1730784000000
    assert data["ltt"] == 1730784000000


def test_full_packet_prefers_last_traded_timestamp(adapter):
    adapter._on_data(
        _quote_packet(subscription_mode=3, last_traded_timestamp=1730783990, bids=[], asks=[])
    )

    data = adapter.published[0][1]
    assert data["last_trade_time"] == 1730783990
    assert data["exchange_timestamp"] == 1730784000000


def test_no_time_published_when_feed_sends_none(adapter):
    adapter._on_data(_quote_packet(exchange_timestamp=0))
    assert "last_trade_time" not in adapter.published[0][1]
