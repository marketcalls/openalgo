"""Dhan streaming quote fields: previous close, full-mode quote fields, ltt.

Synthetic binary frames go through the real DhanWebSocket parser into the
adapter's 5-depth handler; publishing is captured instead of sent on ZeroMQ.
"""

import struct
import threading
from unittest.mock import MagicMock

import pytest

# The proxy package registers every adapter on import, so it is loaded first,
# as the app does; importing an adapter package first is a circular import.
import websocket_proxy  # noqa: F401
from broker.dhan.streaming import dhan_adapter as mod
from broker.dhan.streaming.dhan_websocket import DhanWebSocket

SEG_NSE = 1
SEC_ID = 2885
LTT = 1761700000


def _header(code: int, payload_len: int, segment: int = SEG_NSE, sec: int = SEC_ID) -> bytes:
    return struct.pack("<BHBI", code, 8 + payload_len, segment, sec)


def prev_close_frame(prev_close: float, prev_oi: int) -> bytes:
    payload = struct.pack("<fI", prev_close, prev_oi)
    return _header(6, len(payload)) + payload


def quote_frame(day_close: float = 0.0) -> bytes:
    payload = struct.pack(
        "<fHIfIIIffff",
        1300.5,  # ltp
        25,  # ltq
        LTT,  # ltt
        1298.25,  # atp
        40000,  # volume
        7000,  # total sell qty
        9000,  # total buy qty
        1290.0,  # open
        day_close,  # day close (post market only)
        1310.0,  # high
        1285.0,  # low
    )
    return _header(4, len(payload)) + payload


def full_frame(day_close: float = 0.0) -> bytes:
    head = struct.pack(
        "<fHIfIIIIIIffff",
        1300.5,
        25,
        LTT,
        1298.25,
        40000,
        7000,  # total sell qty
        9000,  # total buy qty
        150,  # oi
        160,  # oi high
        140,  # oi low
        1290.0,
        day_close,
        1310.0,
        1285.0,
    )
    depth = b"".join(
        struct.pack("<IIHHff", 10 + i, 20 + i, 1, 2, 1300.0 - i, 1301.0 + i) for i in range(5)
    )
    payload = head + depth
    assert len(payload) == 154
    return _header(8, len(payload)) + payload


@pytest.fixture
def adapter(monkeypatch):
    a = mod.DhanWebSocketAdapter.__new__(mod.DhanWebSocketAdapter)
    a.logger = MagicMock()
    a.lock = threading.Lock()
    a.subscriptions = {}
    a.subscriptions_5depth = {}
    a.subscriptions_20depth = {}
    a.subscription_queue = []
    a.depth_20_accumulator = {}
    a.depth_20_timeouts = {}
    a.depth_20_data_received = {}
    a.depth_20_fallbacks = {}
    a.prev_close_data = {}
    a.ws_client_5depth = MagicMock()
    a.ws_client_20depth = None
    a.published = []
    a.publish_market_data = lambda topic, data: a.published.append((topic, data))
    monkeypatch.setattr(
        mod.SymbolMapper, "get_token_from_symbol", lambda s, e: {"token": str(SEC_ID)}
    )
    return a


def subscribe(a, mode: int) -> None:
    a.subscriptions_5depth[f"RELIANCE_NSE_{mode}_5"] = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "token": str(SEC_ID),
        "mode": mode,
        "instrument": {"ExchangeSegment": "NSE_EQ", "SecurityId": str(SEC_ID)},
    }


def feed(a, frame: bytes) -> None:
    ws = DhanWebSocket.__new__(DhanWebSocket)
    ws.is_20_depth = False
    ws.logger = MagicMock()
    ws.on_data = a._on_data_5depth
    ws._parse_regular_message(frame)


def test_quote_close_is_previous_close_not_day_close(adapter):
    subscribe(adapter, 2)
    feed(adapter, prev_close_frame(1280.5, 120))
    assert adapter.published == []  # prev close is stored, not published alone

    feed(adapter, quote_frame(day_close=0.0))
    ((topic, quote),) = adapter.published
    assert topic == "NSE_RELIANCE_QUOTE"
    assert quote["close"] == 1280.5
    assert "day_close" not in quote  # Dhan sends 0 before market close
    assert quote["ltt"] == LTT and quote["last_trade_time"] == LTT


def test_day_close_kept_separately_after_market(adapter):
    subscribe(adapter, 2)
    feed(adapter, prev_close_frame(1280.5, 120))
    feed(adapter, quote_frame(day_close=1301.0))
    ((_, quote),) = adapter.published
    assert quote["close"] == 1280.5
    assert quote["day_close"] == 1301.0


def test_close_omitted_until_prev_close_arrives(adapter):
    subscribe(adapter, 2)
    feed(adapter, quote_frame(day_close=1301.0))
    ((_, quote),) = adapter.published
    assert "close" not in quote
    assert quote["day_close"] == 1301.0


def test_full_payload_carries_quote_fields_and_prev_close(adapter):
    subscribe(adapter, 3)
    feed(adapter, prev_close_frame(1280.5, 120))
    feed(adapter, full_frame())
    ((topic, full),) = adapter.published
    assert topic == "NSE_RELIANCE_DEPTH"
    assert full["close"] == 1280.5
    assert full["prev_oi"] == 120
    assert full["last_quantity"] == 25
    assert full["average_price"] == 1298.25
    assert full["total_buy_quantity"] == 9000
    assert full["total_sell_quantity"] == 7000
    assert full["ltt"] == LTT and full["last_trade_time"] == LTT
    assert full["oi"] == 150 and full["volume"] == 40000
    assert full["depth"]["buy"][0] == {"price": 1300.0, "quantity": 10, "orders": 1}
    assert full["depth"]["sell"][0] == {"price": 1301.0, "quantity": 20, "orders": 2}


def test_unsubscribe_clears_stored_prev_close(adapter):
    subscribe(adapter, 2)
    feed(adapter, prev_close_frame(1280.5, 120))
    assert adapter.prev_close_data

    adapter.unsubscribe("RELIANCE", "NSE", 2)
    assert adapter.prev_close_data == {}

    # Resubscribed: no close until Dhan sends a fresh Prev Close packet.
    subscribe(adapter, 2)
    feed(adapter, quote_frame())
    ((_, quote),) = adapter.published
    assert "close" not in quote


def test_unsubscribe_keeps_prev_close_while_another_mode_remains(adapter):
    subscribe(adapter, 2)
    subscribe(adapter, 3)
    feed(adapter, prev_close_frame(1280.5, 120))
    adapter.unsubscribe("RELIANCE", "NSE", 3)
    assert adapter.prev_close_data


def test_unsubscribe_all_clears_prev_close(adapter):
    subscribe(adapter, 2)
    feed(adapter, prev_close_frame(1280.5, 120))
    adapter.unsubscribe_all()
    assert adapter.prev_close_data == {}


def test_disconnect_clears_prev_close(adapter):
    subscribe(adapter, 2)
    feed(adapter, prev_close_frame(1280.5, 120))
    assert adapter.prev_close_data

    adapter.running = True
    adapter.connected = True
    adapter.batch_timer = None
    adapter._stop_fallback_monitor_internal = lambda: None
    adapter.cleanup_zmq = lambda: None
    adapter.disconnect()
    assert adapter.prev_close_data == {}
