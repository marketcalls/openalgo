"""Groww QUOTE subscribers see merged values, never 0 placeholders.

Ticks are in the shape GrowwNATSWebSocket hands the adapter after protobuf
parsing: a protobuf field equal to its default is not on the wire, so a tick
omits OHLC/volume that did not change, and an index tick carries only a value.
"""

import logging
import threading

import pytest

# websocket_proxy first: it imports the adapters in an order that avoids the
# broker package's import cycle.
import websocket_proxy  # noqa: F401
from broker.groww.streaming.groww_adapter import GrowwWebSocketAdapter, _GrowwMarketCache


@pytest.fixture
def adapter():
    """Adapter without __init__: no broker session, no ZMQ socket, no websocket."""
    ad = GrowwWebSocketAdapter.__new__(GrowwWebSocketAdapter)
    ad.logger = logging.getLogger("test_groww_quote_feed")
    ad.lock = threading.Lock()
    ad.subscriptions = {}
    ad.market_cache = _GrowwMarketCache()
    ad.published = []
    ad.publish_market_data = lambda topic, data: ad.published.append((topic, data))
    return ad


def _add_sub(ad, symbol, exchange, mode, token, segment="CASH", groww_exchange=None):
    ad.subscriptions[f"{symbol}_{exchange}_{mode}"] = {
        "symbol": symbol,
        "exchange": exchange,
        "mode": mode,
        "token": token,
        "segment": segment,
        "groww_exchange": groww_exchange or exchange.replace("_INDEX", ""),
    }


def test_quote_keeps_ohlc_volume_from_earlier_tick(adapter):
    _add_sub(adapter, "SBIN", "NSE", 2, "3045")
    adapter._on_data(
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "mode": "ltp",
            "ltp_data": {
                "ltp": 812.5,
                "open": 805.0,
                "high": 815.0,
                "low": 801.0,
                "close": 803.2,
                "volume": 1200000,
                "timestamp": 1730790000000,
            },
        }
    )
    # Next tick: only ltp, volume and time changed.
    adapter._on_data(
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "mode": "ltp",
            "ltp_data": {"ltp": 812.9, "volume": 1200500, "timestamp": 1730790001000},
        }
    )

    topic, data = adapter.published[-1]
    assert topic == "NSE_SBIN_QUOTE"
    assert data["ltp"] == 812.9
    assert data["volume"] == 1200500
    assert data["open"] == 805.0
    assert data["high"] == 815.0
    assert data["low"] == 801.0
    assert data["close"] == 803.2


def test_index_quote_omits_fields_the_tick_does_not_carry(adapter):
    _add_sub(adapter, "NIFTY", "NSE_INDEX", 2, "NIFTY")
    adapter._on_data(
        {
            "symbol": "NIFTY",
            "exchange": "NSE",
            "mode": "index",
            "index_data": {"value": 24350.75, "timestamp": 1730790000000},
        }
    )

    topic, data = adapter.published[-1]
    assert topic == "NSE_INDEX_NIFTY_QUOTE"
    assert data["ltp"] == 24350.75
    for key in ("open", "high", "low", "close", "volume"):
        assert key not in data


def test_disconnect_clears_the_merged_cache(adapter):
    _add_sub(adapter, "SBIN", "NSE", 2, "3045")
    adapter._on_data(
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "mode": "ltp",
            "ltp_data": {"ltp": 812.5, "open": 805.0, "high": 815.0, "timestamp": 1730790000000},
        }
    )
    assert adapter.market_cache.snapshot("NSE", "CASH", "3045")

    adapter.running = True
    adapter.batch_timer = None
    adapter.batch_lock = threading.Lock()
    adapter.subscription_queue = []
    adapter.subscription_keys = {}
    adapter.ws_client = None
    adapter.cleanup_zmq = lambda: None
    adapter.disconnect()

    # After a reconnect, a sparse first tick shows only what it carries.
    _add_sub(adapter, "SBIN", "NSE", 2, "3045")
    adapter.published.clear()
    adapter._on_data(
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "mode": "ltp",
            "ltp_data": {"ltp": 813.0, "timestamp": 1730800000000},
        }
    )
    data = adapter.published[-1][1]
    assert data["ltp"] == 813.0
    assert "open" not in data and "high" not in data
