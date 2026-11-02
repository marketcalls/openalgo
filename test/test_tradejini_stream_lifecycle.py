"""Tradejini streaming: socket lifecycle, bounded caches, and Depth price fields.

NxtradStream (broker/tradejini/api/nxtradstream.py) is shared by the streaming
adapter and the quote/depth request path in api/data.py, so the socket fixes
cover both.

- A connect racing disconnect() used to open a socket (plus its reader thread)
  that nobody owned, which kept streaming into the shared ZMQ bus. A
  disconnect mid-handshake left a socket only the garbage collector closed.
- NxtradStream.L1_dict kept the last quote of every token ever streamed until
  the whole L1 feed was cancelled.
- Depth updates showed LTP/OHLC/volume as 0: Tradejini's L5 packet carries only
  the book, so Depth now also rides L1 and the two are merged.
"""

import logging
import threading
import time

import pytest

import broker.tradejini.api.data as tjdata
import broker.tradejini.api.nxtradstream as nx
import broker.tradejini.streaming.tradejini_adapter as ta


class _FakeWebSocketApp:
    created = []

    def __init__(self, url, on_open=None, on_message=None, on_error=None, on_close=None):
        self.on_open = on_open
        self.closed = False
        self.sock = None  # as in websocket-client until run_forever() starts
        _FakeWebSocketApp.created.append(self)

    def run_forever(self):
        return None

    def close(self):
        self.closed = True


@pytest.fixture
def fake_ws(monkeypatch):
    _FakeWebSocketApp.created = []
    monkeypatch.setattr(nx.websocket, "WebSocketApp", _FakeWebSocketApp)
    return _FakeWebSocketApp


def _bare_adapter(client):
    """An adapter with its connection state, without a ZMQ socket."""
    a = ta.TradejiniWebSocketAdapter.__new__(ta.TradejiniWebSocketAdapter)
    a.logger = logging.getLogger("test_tradejini")
    a.lock = threading.Lock()
    a.running = True
    a.connected = False
    a.reconnect_attempts = 0
    a.reconnect_delay = 5
    a.max_reconnect_delay = 60
    a.max_reconnect_attempts = 10
    a._connect_thread = None
    a._retry_pending = False
    a._pending_delay = 0.0
    a._dirty_feeds = {}
    a._feed_dirty = threading.Event()
    a._flush_thread = None
    a._flush_stop = threading.Event()
    a.subscriptions = {}
    a._last_l1 = {}
    a._last_l5 = {}
    a.ws_client = client
    a.user_id = "user"
    a.ws_token = "key:token"
    a.cleanup_zmq = lambda: None
    return a


def test_disconnect_during_token_read_opens_no_socket(monkeypatch, fake_ws):
    token_read_started = threading.Event()

    def slow_token(*args, **kwargs):
        token_read_started.set()
        time.sleep(0.3)
        return "token"

    monkeypatch.setattr(ta, "get_auth_token", slow_token)
    monkeypatch.setattr(ta, "get_api_key", lambda: "key")

    stream = nx.NxtradStream("example.invalid")
    adapter = _bare_adapter(stream)

    adapter.connect()
    assert token_read_started.wait(2)
    adapter.disconnect()

    thread = adapter._connect_thread
    if thread is not None:
        thread.join(2)

    assert fake_ws.created == []


def test_stream_refuses_connect_after_disconnect(fake_ws):
    stream = nx.NxtradStream("example.invalid")
    stream.disconnect()
    stream.connect("key:token")

    assert fake_ws.created == []
    assert stream.ws is None


def test_disconnect_closes_the_socket_it_raced(fake_ws):
    stream = nx.NxtradStream("example.invalid")
    stream.connect("key:token")
    stream.disconnect()

    assert len(fake_ws.created) == 1
    assert fake_ws.created[0].closed


class _HandshakingSocket:
    connected = False

    def __init__(self):
        self.shut = False

    def shutdown(self):
        self.shut = True


def test_disconnect_mid_handshake_aborts_and_keeps_the_socket(fake_ws):
    """WebSocketApp.close() mid-handshake drops the socket without closing it.

    WebSocket.close() returns early when not connected, so the handshake would
    finish on an unreferenced socket that only the garbage collector closes.
    """
    stream = nx.NxtradStream("example.invalid")
    stream.connect("key:token")
    app = fake_ws.created[0]
    handshake = _HandshakingSocket()
    app.sock = handshake

    stream.disconnect()

    assert handshake.shut
    assert app.sock is handshake  # still reachable for __on_open's close
    assert not app.closed


def test_socket_opening_after_disconnect_is_closed(fake_ws):
    """A close() before run_forever() starts is lost; on_open must catch it."""
    events = []
    stream = nx.NxtradStream("example.invalid", connect_cb=lambda _s, m: events.append(m))
    stream.connect("key:token")
    ws = fake_ws.created[0]
    stream.disconnect()
    ws.closed = False  # websocket-client dropped the early close

    ws.on_open(ws)

    assert ws.closed
    assert stream.isConnected is False
    assert events == []


def test_subscribe_l1_drops_quotes_for_tokens_no_longer_listed():
    stream = nx.NxtradStream("example.invalid")
    stream.L1_dict = {
        "2885_NSE": {"ltp": 1},
        "11536_NSE": {"ltp": 2},
        "500325_BSE": {"ltp": 3},
    }

    stream.subscribeL1(["2885_NSE", "500325_BSE"])

    assert set(stream.L1_dict) == {"2885_NSE", "500325_BSE"}


L1_TICK = {
    "msgType": "L1",
    "symbol": "1594_NSE",
    "ltp": 1155.0,
    "open": 1191.9,
    "high": 1194.5,
    "low": 1151.0,
    "close": 1185.0,
    "vol": 1100000,
}
L5_TICK = {
    "msgType": "L5",
    "symbol": "1594_NSE",
    "totBuyQty": 543853,
    "totSellQty": 600000,
    "bid": [{"price": 1154.8, "qty": 123, "no": 3}],
    "ask": [{"price": 1155.0, "qty": 50, "no": 1}],
}


def _depth_adapter():
    adapter = _bare_adapter(client=None)
    adapter.subscriptions["INFY_NSE_3_5"] = {
        "symbol": "INFY",
        "exchange": "NSE",
        "brexchange": "NSE",
        "token": "1594",
        "mode": 3,
        "depth_level": 5,
    }
    published = []
    adapter.publish_market_data = lambda topic, data: published.append((topic, data))
    adapter.zmq_port = 0
    return adapter, published


def test_depth_rides_the_l1_feed_too():
    adapter, _ = _depth_adapter()
    assert adapter._feed_tokens("L1") == ["1594_NSE"]
    assert adapter._feed_tokens("L5") == ["1594_NSE"]


def test_depth_update_carries_l1_price_fields():
    """Tradejini's L5 packet has no LTP or OHLC; they must come from L1."""
    adapter, published = _depth_adapter()

    adapter._on_data(None, dict(L1_TICK))
    assert published == []  # no book yet, nothing to show

    adapter._on_data(None, dict(L5_TICK))
    topic, data = published[-1]
    assert topic == "NSE_INFY_DEPTH"
    assert data["ltp"] == 1155.0
    assert data["open"] == 1191.9
    assert data["volume"] == 1100000
    assert data["total_buy_quantity"] == 543853
    assert data["depth"]["buy"][0] == {"price": 1154.8, "quantity": 123, "orders": 3}

    # A later price tick refreshes the Depth view with the cached book
    adapter._on_data(None, dict(L1_TICK, ltp=1156.0))
    _, data = published[-1]
    assert data["ltp"] == 1156.0
    assert data["depth"]["buy"][0]["price"] == 1154.8


def test_unsubscribe_drops_cached_ticks(monkeypatch):
    adapter, _ = _depth_adapter()
    adapter._on_data(None, dict(L1_TICK))
    adapter._on_data(None, dict(L5_TICK))
    monkeypatch.setattr(
        ta.SymbolMapper,
        "get_token_from_symbol",
        staticmethod(lambda s, e: {"token": "1594", "brexchange": "NSE"}),
    )

    adapter.unsubscribe("INFY", "NSE", mode=3)

    assert adapter._last_l1 == {}
    assert adapter._last_l5 == {}


# --- Quote/depth request path (api/data.py) ---------------------------------


def test_request_path_close_after_connect_timeout_aborts_the_handshake(monkeypatch, fake_ws):
    """A request gives up after 15s and closes while the handshake may still run."""
    monkeypatch.setattr(tjdata, "get_api_key", lambda: "key")
    monkeypatch.setattr(tjdata.time, "sleep", lambda _s: None)  # skip the 15s wait

    ws = tjdata.TradejiniWebSocket()
    assert ws.connect("token") is False  # never reached "connected"

    app = fake_ws.created[0]
    handshake = _HandshakingSocket()
    app.sock = handshake
    ws.close()  # the request's finally block

    assert handshake.shut
    assert app.sock is handshake


def test_request_path_reconnect_after_close_opens_no_socket(monkeypatch, fake_ws):
    """A drop's reconnect that loses the race with close() must not connect."""
    monkeypatch.setattr(tjdata, "get_api_key", lambda: "key")
    monkeypatch.setattr(tjdata.time, "sleep", lambda _s: None)

    ws = tjdata.TradejiniWebSocket()
    ws.connect("token")
    stream = ws.nx_stream
    ws.close()

    # The reader thread checked _closing before close() set it, then reconnects
    stream.reconnect()

    assert len(fake_ws.created) == 1
