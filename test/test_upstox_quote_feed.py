"""Upstox V3 feed: merged quote fields, previous close, ltt and per-key mode.

Ticks are in the MessageToDict shape the client hands the adapter (int64 as
strings, proto3 defaults omitted), following upstox-api-docs/21a. Publish and
the websocket client are mocked.
"""

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

# websocket_proxy first: it imports the adapters in an order that avoids the
# broker package's import cycle.
import websocket_proxy  # noqa: F401
from broker.upstox.streaming.upstox_adapter import UpstoxWebSocketAdapter

KEY = "NSE_FO|45450"


@pytest.fixture
def adapter():
    """Adapter without __init__: no broker session, no ZMQ socket, no websocket."""
    ad = UpstoxWebSocketAdapter.__new__(UpstoxWebSocketAdapter)
    ad.logger = logging.getLogger("test_upstox_quote_feed")
    ad.lock = threading.Lock()
    ad.subscriptions = {}
    ad.subscription_queue = []
    ad.batch_timer = None
    ad._batch_generation = 0
    ad._snapshots = {}
    ad.ws_client = MagicMock()
    ad.ws_client._connected = True
    ad.ws_client.subscribe.return_value = True
    ad.ws_client.unsubscribe.return_value = True
    ad.published = []
    ad.publish_market_data = lambda topic, data: ad.published.append((topic, data))
    return ad


def _add_sub(ad, mode, symbol="NIFTY28NOV2423000CE", exchange="NFO"):
    ad.subscriptions[f"{symbol}_{exchange}_{mode}"] = {
        "symbol": symbol,
        "exchange": exchange,
        "mode": mode,
        "depth_level": 5,
        "token": "45450",
        "instrument_key": KEY,
    }


FULL_TICK = {
    "fullFeed": {
        "marketFF": {
            "ltpc": {"ltp": 219.3, "ltt": "1740729552723", "ltq": "75", "cp": 494.05},
            "marketLevel": {
                "bidAskQuote": [
                    {"bidQ": "150", "bidP": 219.25, "askQ": "75", "askP": 219.4},
                    {"bidQ": "300", "bidP": 219.2, "askQ": "225", "askP": 219.45},
                ]
            },
            "marketOHLC": {
                "ohlc": [
                    {
                        "interval": "1d",
                        "open": 480.0,
                        "high": 495.0,
                        "low": 210.0,
                        "close": 219.3,
                        "vol": "1234500",
                        "ts": "1740681000000",
                    },
                    {
                        "interval": "I1",
                        "open": 219.0,
                        "high": 219.5,
                        "low": 218.9,
                        "close": 219.3,
                        "vol": "4500",
                        "ts": "1740729480000",
                    },
                ]
            },
            "atp": 301.5,
            "vtt": "1234575",
            "oi": 98765.0,
            "tbq": 50000.0,
            "tsq": 60000.0,
        }
    }
}


def _feed(ad, tick, ts="1740729566039"):
    ad._on_market_data({"type": "live_feed", "feeds": {KEY: tick}, "currentTs": ts})
    return ad.published[-1][1]


def test_quote_close_is_previous_close_and_ltt_from_ltpc(adapter):
    _add_sub(adapter, 2)
    data = _feed(adapter, FULL_TICK)

    assert data["close"] == 494.05  # ltpc.cp, not today's candle close (= ltp)
    assert data["open"] == 480.0
    assert data["high"] == 495.0
    assert data["low"] == 210.0
    assert data["volume"] == 1234575  # vtt, volume traded today
    assert data["ltt"] == 1740729552723
    assert data["last_trade_time"] == 1740729552723
    assert data["last_quantity"] == 75
    assert data["last_trade_quantity"] == 75


def test_intraday_candle_never_stands_in_for_the_day_candle(adapter):
    _add_sub(adapter, 2)
    tick = {
        "fullFeed": {
            "marketFF": {
                "ltpc": {"ltp": 219.3, "ltt": "1740729552723", "cp": 494.05},
                "marketOHLC": {
                    "ohlc": [
                        {
                            "interval": "I1",
                            "open": 219.0,
                            "high": 219.5,
                            "low": 218.9,
                            "close": 219.3,
                            "vol": "4500",
                            "ts": "1740729480000",
                        }
                    ]
                },
            }
        }
    }
    data = _feed(adapter, tick)
    for key in ("open", "high", "low", "volume"):
        assert key not in data


def test_incremental_tick_keeps_merged_quote_fields(adapter):
    _add_sub(adapter, 2)
    _feed(adapter, FULL_TICK)
    # Next packet carries only a new trade.
    data = _feed(
        adapter,
        {
            "fullFeed": {
                "marketFF": {
                    "ltpc": {"ltp": 219.5, "ltt": "1740729553000", "ltq": "25", "cp": 494.05}
                }
            }
        },
    )

    assert data["ltp"] == 219.5
    assert data["open"] == 480.0
    assert data["average_price"] == 301.5
    assert data["total_buy_quantity"] == 50000
    assert data["total_sell_quantity"] == 60000
    assert data["volume"] == 1234575
    assert data["ltt"] == 1740729553000


def test_depth_payload_carries_quote_fields(adapter):
    _add_sub(adapter, 3)
    _feed(adapter, FULL_TICK)
    # A packet that only updates the book.
    data = _feed(
        adapter,
        {
            "fullFeed": {
                "marketFF": {
                    "marketLevel": {
                        "bidAskQuote": [{"bidQ": "10", "bidP": 219.3, "askQ": "20", "askP": 219.5}]
                    }
                }
            }
        },
    )

    assert data["ltp"] == 219.3
    assert data["close"] == 494.05
    assert data["open"] == 480.0
    assert data["volume"] == 1234575
    assert data["average_price"] == 301.5
    assert data["total_buy_quantity"] == 50000
    assert data["depth"]["buy"][0] == {"price": 219.3, "quantity": 10}
    assert data["depth"]["sell"][0] == {"price": 219.5, "quantity": 20}


def test_ltpc_subscribe_does_not_downgrade_a_full_key(adapter):
    _add_sub(adapter, 2)
    _add_sub(adapter, 1)
    adapter.subscription_queue = list(adapter.subscriptions.values())
    adapter._process_batch_subscriptions()

    sent = [call.args for call in adapter.ws_client.subscribe.call_args_list]
    assert sent == [([KEY], "full")]


def test_unsubscribing_one_mode_keeps_the_key_for_the_other(adapter):
    _add_sub(adapter, 2)
    _add_sub(adapter, 1)
    token_info = {"token": "45450", "brexchange": "NSE_FO"}
    with patch(
        "broker.upstox.streaming.upstox_adapter.SymbolMapper.get_token_from_symbol",
        return_value=token_info,
    ):
        adapter.unsubscribe("NIFTY28NOV2423000CE", "NFO", 2)
        adapter.ws_client.unsubscribe.assert_not_called()
        adapter.ws_client.subscribe.assert_called_once_with([KEY], "ltpc")

        adapter.unsubscribe("NIFTY28NOV2423000CE", "NFO", 1)
        adapter.ws_client.unsubscribe.assert_called_once_with([KEY])
    assert adapter.subscriptions == {}


def test_client_moves_a_key_between_modes():
    from broker.upstox.streaming.upstox_client import UpstoxWebSocketClient

    client = UpstoxWebSocketClient.__new__(UpstoxWebSocketClient)
    client.logger = logging.getLogger("test_upstox_quote_feed")
    client._connected = True
    client.ws = MagicMock()
    client._subscriptions = set()
    client._keys_by_mode = {}

    assert client.subscribe([KEY], "ltpc")
    assert client.subscribe([KEY], "full")
    assert client._keys_by_mode == {"full": {KEY}}
    # Back down to ltpc once the full subscriber leaves: must be sent, not deduplicated.
    assert client.subscribe([KEY], "ltpc")
    assert client.ws.send.call_count == 3
    assert client._keys_by_mode == {"ltpc": {KEY}}


# --- review follow-ups ---------------------------------------------------------


def _client():
    from broker.upstox.streaming.upstox_client import UpstoxWebSocketClient

    client = UpstoxWebSocketClient.__new__(UpstoxWebSocketClient)
    client.logger = logging.getLogger("test_upstox_quote_feed")
    client._connected = True
    client.ws = MagicMock()
    client._subscriptions = set()
    client._keys_by_mode = {}
    return client


def test_an_emptied_mode_does_not_trigger_the_combined_cap():
    """Moving every key out of a mode must not leave the connection counted
    as multi-mode, which would cap later subscribes at the combined limit."""
    client = _client()
    assert client.subscribe([KEY], "ltpc")
    assert client.subscribe([KEY], "full")  # the only ltpc key moves to full
    assert client.subscribe([KEY], "ltpc")  # and back: full is now empty

    many = [f"NSE_EQ|K{i}" for i in range(client.DEFAULT_MODE_COMBINED_LIMIT + 10)]
    keys, dropped = client._enforce_key_limits(many, "ltpc")
    limit = client.MODE_KEY_LIMITS.get("ltpc", client.DEFAULT_MODE_KEY_LIMIT)
    assert len(keys) == min(len(many), limit - 1)
    assert dropped == len(many) - len(keys)


def test_a_failed_mode_change_on_unsubscribe_is_reported(adapter):
    _add_sub(adapter, 2)
    _add_sub(adapter, 1)
    adapter.ws_client.subscribe.return_value = False
    token_info = {"token": "45450", "brexchange": "NSE_FO"}
    with patch(
        "broker.upstox.streaming.upstox_adapter.SymbolMapper.get_token_from_symbol",
        return_value=token_info,
    ):
        result = adapter.unsubscribe("NIFTY28NOV2423000CE", "NFO", 2)

    assert result["status"] == "error"
    assert "NIFTY28NOV2423000CE_NFO_2" in adapter.subscriptions, "kept for a retry"
