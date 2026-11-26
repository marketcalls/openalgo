"""Pocketful's market-data feed: packets, messages, the address, and the proxy adapter.

Every packet here is built field by field at the offsets of Pocketful's Python
SDK 0.1.2 (packetDecoder.py), carrying the values of the response samples in
the docs (detailed-marketdata.md, compact-marketdata.md, snapquote-data.md), so
a decoder that agrees with these tests agrees with both sources. No network.
"""

from __future__ import annotations

import json
import logging
import struct
import threading
import time

# websocket_proxy imports the adapter from its package initializer.
import websocket_proxy  # noqa: F401  isort:skip

import pytest

from broker.pocketful.api import packet_decoder as decoder
from broker.pocketful.streaming import pocketful_adapter as adapter_module
from broker.pocketful.streaming.pocketful_adapter import PocketfulWebSocketAdapter
from broker.pocketful.streaming.pocketful_mapping import PocketfulExchangeMapper

# ----------------------------------------------------------------- docs samples

DETAILED_SAMPLE = {
    "mode": 1,
    "exchange_code": 1,
    "instrument_token": 1333,
    "last_traded_price": 144895,
    "last_traded_time": 1710489044,
    "last_traded_quantity": 1,
    "trade_volume": 8014246,
    "best_bid_price": 144890,
    "best_bid_quantity": 25,
    "best_ask_price": 144895,
    "best_ask_quantity": 628,
    "total_buy_quantity": 624983,
    "total_sell_quantity": 899665,
    "average_trade_price": 145018,
    "exchange_timestamp": 1710489044,
    "open_price": 145000,
    "high_price": 145930,
    "low_price": 144415,
    "close_price": 145545,
    "yearly_high_price": 175750,
    "yearly_low_price": 136355,
    "lowDPR": 130990,
    "highDPR": 160095,
    "currentOpenInterest": 0,
    "initialOpenInterest": 0,
}

COMPACT_SAMPLE = {
    "mode": 2,
    "exchange_code": 1,
    "instrument_token": 1333,
    "last_traded_price": 145065,
    "change": 4294966816,
    "last_traded_time": 1710491906,
    "lowDPR": 130990,
    "highDPR": 160095,
    "currentOpenInterest": 0,
    "initialOpenInterest": 0,
    "bidPrice": 145060,
    "askPrice": 145070,
}

SNAPQUOTE_SAMPLE = {
    "mode": 4,
    "exchange_code": 1,
    "instrument_token": 1333,
    "buyers": [3, 3, 1, 2, 6],
    "bidPrices": [145100, 145095, 145090, 145085, 145080],
    "bidQtys": [121, 53, 64, 76, 130],
    "sellers": [1, 4, 1, 3, 4],
    "askPrices": [145110, 145135, 145140, 145145, 145150],
    "askQtys": [33, 441, 68, 113, 324],
    "averageTradePrice": 145026,
    "open": 145000,
    "high": 145930,
    "low": 144415,
    "close": 145545,
    "totalBuyQty": 653906,
    "totalSellQty": 870361,
    "volume": 9438681,
}

# --------------------------------------------- packets at the SDK's own offsets

# (field, offset, struct format) exactly as packetDecoder.py slices them.
DETAILED_OFFSETS = [
    ("mode", 0, ">b"),
    ("exchange_code", 1, ">b"),
    ("instrument_token", 2, ">I"),
    ("last_traded_price", 6, ">I"),
    ("last_traded_time", 10, ">I"),
    ("last_traded_quantity", 14, ">I"),
    ("trade_volume", 18, ">I"),
    ("best_bid_price", 22, ">I"),
    ("best_bid_quantity", 26, ">I"),
    ("best_ask_price", 30, ">I"),
    ("best_ask_quantity", 34, ">I"),
    ("total_buy_quantity", 38, ">Q"),
    ("total_sell_quantity", 46, ">Q"),
    ("average_trade_price", 54, ">I"),
    ("exchange_timestamp", 58, ">I"),
    ("open_price", 62, ">I"),
    ("high_price", 66, ">I"),
    ("low_price", 70, ">I"),
    ("close_price", 74, ">I"),
    ("yearly_high_price", 78, ">I"),
    ("yearly_low_price", 82, ">I"),
    ("lowDPR", 86, ">I"),
    ("highDPR", 90, ">I"),
    ("currentOpenInterest", 94, ">I"),
    ("initialOpenInterest", 98, ">I"),
]
COMPACT_OFFSETS = [
    ("mode", 0, ">b"),
    ("exchange_code", 1, ">b"),
    ("instrument_token", 2, ">I"),
    ("last_traded_price", 6, ">I"),
    ("change", 10, ">I"),
    ("last_traded_time", 14, ">I"),
    ("lowDPR", 18, ">I"),
    ("highDPR", 22, ">I"),
    ("currentOpenInterest", 26, ">I"),
    ("initialOpenInterest", 30, ">I"),
    ("bidPrice", 34, ">I"),
    ("askPrice", 38, ">I"),
]
SNAPQUOTE_SCALARS = [
    ("mode", 0, ">b"),
    ("exchange_code", 1, ">b"),
    ("instrument_token", 2, ">I"),
    ("averageTradePrice", 126, ">I"),
    ("open", 130, ">I"),
    ("high", 134, ">I"),
    ("low", 138, ">I"),
    ("close", 142, ">I"),
    ("totalBuyQty", 146, ">Q"),
    ("totalSellQty", 154, ">Q"),
    ("volume", 162, ">I"),
]
SNAPQUOTE_ARRAYS = [
    ("buyers", 6),
    ("bidPrices", 26),
    ("bidQtys", 46),
    ("sellers", 66),
    ("askPrices", 86),
    ("askQtys", 106),
]


def _pack(size, offsets, values):
    packet = bytearray(size)
    for field, offset, fmt in offsets:
        struct.pack_into(fmt, packet, offset, values[field])
    return packet


def detailed_packet(**overrides):
    return bytes(_pack(102, DETAILED_OFFSETS, {**DETAILED_SAMPLE, **overrides}))


def compact_packet(**overrides):
    return bytes(_pack(42, COMPACT_OFFSETS, {**COMPACT_SAMPLE, **overrides}))


def snapquote_packet(**overrides):
    values = {**SNAPQUOTE_SAMPLE, **overrides}
    packet = _pack(166, SNAPQUOTE_SCALARS, values)
    for field, start in SNAPQUOTE_ARRAYS:
        for i, value in enumerate(values[field]):
            struct.pack_into(">I", packet, start + 4 * i, value)
    return bytes(packet)


# ---------------------------------------------------------------------- decoder


def test_detailed_packet_decodes_to_the_docs_sample():
    assert decoder.decodeDetailedMarketData(detailed_packet()) == DETAILED_SAMPLE


def test_compact_packet_decodes_to_the_docs_sample():
    assert decoder.decodeCompactMarketData(compact_packet()) == COMPACT_SAMPLE


def test_snapquote_packet_decodes_to_the_docs_sample():
    assert decoder.decodeSnapquoteData(snapquote_packet()) == SNAPQUOTE_SAMPLE


def test_every_field_is_read_from_its_own_offset():
    """A distinct value per field: a swapped or shifted field cannot pass."""
    detailed = {field: 1000 + i for i, (field, _, _) in enumerate(DETAILED_OFFSETS)}
    detailed.update(mode=1, exchange_code=7)
    assert decoder.decodeDetailedMarketData(detailed_packet(**detailed)) == detailed

    compact = {field: 2000 + i for i, (field, _, _) in enumerate(COMPACT_OFFSETS)}
    compact.update(mode=2, exchange_code=2)
    assert decoder.decodeCompactMarketData(compact_packet(**compact)) == compact

    snap = {field: 3000 + i for i, (field, _, _) in enumerate(SNAPQUOTE_SCALARS)}
    snap.update(mode=4, exchange_code=4)
    for n, (field, _) in enumerate(SNAPQUOTE_ARRAYS):
        snap[field] = [4000 + 10 * n + level for level in range(5)]
    assert decoder.decodeSnapquoteData(snapquote_packet(**snap)) == snap


def test_short_packets_decode_to_nothing_and_extra_bytes_are_ignored():
    assert decoder.decodeDetailedMarketData(detailed_packet()[:101]) == {}
    assert decoder.decodeCompactMarketData(compact_packet()[:41]) == {}
    assert decoder.decodeSnapquoteData(snapquote_packet()[:165]) == {}
    assert decoder.decodeCompactMarketData(compact_packet() + b"\x00\x01") == COMPACT_SAMPLE
    assert decoder.packet_mode(b"") is None
    assert decoder.packet_mode('{"mode": 2}') is None, "a text frame has no mode byte"


def test_the_feed_address_and_messages_are_the_sdks():
    assert decoder.feed_url("CSG981", "tok.en-1") == (
        "wss://algo.pocketful.in/ws/v1/feeds?login_id=CSG981&access_token=tok.en-1"
    )
    assert json.loads(decoder.HEARTBEAT_MESSAGE) == {"a": "h", "v": [], "m": ""}
    assert decoder.HEARTBEAT_SECONDS == 8
    assert json.loads(decoder.feed_message("subscribe", [[1, 1333]], decoder.SNAPQUOTE_MODE)) == {
        "a": "subscribe",
        "v": [[1, 1333]],
        "m": "full_snapquote",
    }
    assert decoder.CHANNEL_NAMES == {1: "marketdata", 2: "compact_marketdata", 4: "full_snapquote"}


def test_exchange_codes_are_the_docs_and_an_unknown_exchange_is_refused():
    docs = {"NSE": 1, "NFO": 2, "CDS": 3, "MCX": 4, "BSE": 6, "BFO": 7}
    for exchange, code in docs.items():
        assert PocketfulExchangeMapper.get_exchange_code(exchange) == code
    assert PocketfulExchangeMapper.get_exchange_code("NCDEX") is None
    assert PocketfulExchangeMapper.get_exchange_code(None) is None


# ---------------------------------------------------------------------- adapter


class FakeSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False
        self.on_send = None

    def send(self, payload):
        if self.on_send is not None:
            hook, self.on_send = self.on_send, None
            hook()
        self.sent.append(json.loads(payload))

    def close(self):
        self.closed = True


TOKENS = {("HDFCBANK", "NSE"): "1333", ("NIFTY", "NSE_INDEX"): "26000"}


@pytest.fixture
def adapter(monkeypatch):
    def lookup(symbol, exchange):
        token = TOKENS.get((symbol, exchange))
        return {"token": token, "brexchange": exchange} if token else None

    monkeypatch.setattr(adapter_module.SymbolMapper, "get_token_from_symbol", lookup)
    instance = PocketfulWebSocketAdapter()
    published: list[tuple[str, dict]] = []
    instance.publish_market_data = lambda topic, data: published.append((topic, data))
    instance.published = published
    yield instance
    instance.running = False
    instance.cleanup_zmq()


def _connect(adapter):
    ws = FakeSocket()
    adapter.connected = True
    adapter.ws_client = ws
    return ws


def _subscribe_now(adapter, symbol, exchange, mode):
    """Subscribe on a connected adapter and send the batch at once."""
    response = adapter.subscribe(symbol, exchange, mode)
    assert response["status"] == "success", response
    if adapter.batch_timer is not None:
        adapter.batch_timer.cancel()
    adapter._process_batch_subscriptions()


def _messages(ws, action):
    return [(m["m"], m["v"]) for m in ws.sent if m["a"] == action]


def test_ltp_mode_publishes_only_the_documented_ltp_frame(adapter):
    adapter.subscribe("HDFCBANK", "NSE", 1)
    adapter._on_message(None, compact_packet())

    assert len(adapter.published) == 1
    topic, data = adapter.published[0]
    assert topic == "NSE_HDFCBANK_LTP"
    assert set(data) == {"ltp", "timestamp"}
    assert data["ltp"] == 1450.65
    assert abs(data["timestamp"] - time.time() * 1000) < 5000


def test_quote_mode_publishes_the_documented_quote_frame(adapter):
    adapter.subscribe("HDFCBANK", "NSE", 2)
    adapter._on_message(None, detailed_packet())

    topic, data = adapter.published[-1]
    assert topic == "NSE_HDFCBANK_QUOTE"
    assert data["ltp"] == 1448.95
    assert data["change"] == -6.5  # 1448.95 - 1455.45
    assert data["change_percent"] == -0.45
    assert data["volume"] == 8014246
    assert (data["open"], data["high"], data["low"], data["close"]) == (
        1450.0,
        1459.3,
        1444.15,
        1455.45,
    )
    assert data["last_trade_quantity"] == 1
    assert data["avg_trade_price"] == 1450.18
    assert (data["bid_price"], data["bid_size"]) == (1448.9, 25)
    assert (data["ask_price"], data["ask_size"]) == (1448.95, 628)


def test_a_price_the_feed_does_not_have_is_left_out_not_sent_as_zero(adapter):
    adapter.subscribe("HDFCBANK", "NSE", 2)
    adapter._on_message(None, detailed_packet(last_traded_price=0, open_price=0, close_price=0))

    _, data = adapter.published[-1]
    assert "ltp" not in data and "open" not in data and "close" not in data
    assert "change" not in data and "change_percent" not in data
    assert data["high"] == 1459.3


def test_each_packet_reaches_only_the_mode_it_serves(adapter):
    """A compact packet used to be published under whichever subscription of
    the instrument came first, so a Quote subscriber got an LTP-only frame."""
    adapter.subscribe("HDFCBANK", "NSE", 2)
    adapter.subscribe("HDFCBANK", "NSE", 1)

    adapter._on_message(None, compact_packet())
    assert [topic for topic, _ in adapter.published] == ["NSE_HDFCBANK_LTP"]

    adapter._on_message(None, detailed_packet())
    assert [topic for topic, _ in adapter.published] == ["NSE_HDFCBANK_LTP", "NSE_HDFCBANK_QUOTE"]


def test_another_exchanges_packet_with_the_same_token_is_not_published(adapter):
    adapter.subscribe("HDFCBANK", "NSE", 1)
    adapter._on_message(None, compact_packet(exchange_code=2))
    assert adapter.published == []


def test_depth_never_publishes_the_average_price_as_the_last_traded_price(adapter):
    """The snapquote packet has no LTP. Its average price was published as one,
    and the depth stream mirrors ltp into the cache the sandbox fills from."""
    adapter.subscribe("HDFCBANK", "NSE", 3)

    adapter._on_message(None, snapquote_packet())
    topic, data = adapter.published[-1]
    assert topic == "NSE_HDFCBANK_DEPTH"
    assert "ltp" not in data, "no last traded price has arrived yet"
    assert data["avg_trade_price"] == 1450.26
    assert data["depth"]["buy"][0] == {"price": 1451.0, "quantity": 121, "orders": 3}
    assert data["depth"]["buy"][4] == {"price": 1450.8, "quantity": 130, "orders": 6}
    assert data["depth"]["sell"][0] == {"price": 1451.1, "quantity": 33, "orders": 1}
    assert data["depth"]["sell"][4] == {"price": 1451.5, "quantity": 324, "orders": 4}
    assert len(data["depth"]["buy"]) == len(data["depth"]["sell"]) == 5
    assert (data["totalbuyqty"], data["totalsellqty"], data["volume"]) == (
        653906,
        870361,
        9438681,
    )

    adapter._on_message(None, compact_packet())  # LTP 1450.65 arrives
    adapter._on_message(None, snapquote_packet())
    assert adapter.published[-1][1]["ltp"] == 1450.65


def test_a_depth_subscription_takes_the_book_and_the_last_traded_price(adapter):
    ws = _connect(adapter)
    _subscribe_now(adapter, "HDFCBANK", "NSE", 3)

    assert sorted(_messages(ws, "subscribe")) == [
        ("compact_marketdata", [[1, 1333]]),
        ("full_snapquote", [[1, 1333]]),
    ]


def test_unsubscribing_depth_keeps_the_channel_an_ltp_subscription_needs(adapter):
    ws = _connect(adapter)
    _subscribe_now(adapter, "HDFCBANK", "NSE", 1)
    _subscribe_now(adapter, "HDFCBANK", "NSE", 3)
    assert _messages(ws, "subscribe") == [
        ("compact_marketdata", [[1, 1333]]),
        ("full_snapquote", [[1, 1333]]),
    ], "the compact channel the LTP subscription holds is not subscribed twice"

    adapter.unsubscribe("HDFCBANK", "NSE", 3)
    assert _messages(ws, "unsubscribe") == [("full_snapquote", [[1, 1333]])]

    adapter.unsubscribe("HDFCBANK", "NSE", 1)
    assert _messages(ws, "unsubscribe")[-1] == ("compact_marketdata", [[1, 1333]])
    assert adapter._broker_channels == set()


def test_releasing_the_last_depth_subscription_drops_its_cached_price(adapter):
    adapter.subscribe("HDFCBANK", "NSE", 3)
    adapter._on_message(None, compact_packet())
    assert adapter._last_ltp == {(1, 1333): 145065}

    adapter.unsubscribe("HDFCBANK", "NSE", 3)
    assert adapter._last_ltp == {}
    adapter._on_message(None, compact_packet())  # a packet still in flight
    assert adapter._last_ltp == {}, "a released instrument's price came back"


def test_an_unsubscribe_landing_during_the_subscribe_send_is_not_lost(adapter):
    """The unsubscribe runs inside the subscribe's send. The broker had not
    confirmed the channel, so there was nothing to unsubscribe yet; it must be
    dropped when the subscribe returns, or it streams with nobody listening."""
    ws = _connect(adapter)
    adapter.subscribe("HDFCBANK", "NSE", 1)
    adapter.batch_timer.cancel()
    ws.on_send = lambda: adapter.unsubscribe("HDFCBANK", "NSE", 1)

    adapter._process_batch_subscriptions()

    assert _messages(ws, "subscribe") == [("compact_marketdata", [[1, 1333]])]
    assert _messages(ws, "unsubscribe") == [("compact_marketdata", [[1, 1333]])]
    assert adapter._broker_channels == set() and adapter._inflight == {}


def test_a_resubscribe_during_the_send_keeps_the_channel(adapter):
    ws = _connect(adapter)
    adapter.subscribe("HDFCBANK", "NSE", 1)
    adapter.batch_timer.cancel()

    def churn():
        adapter.unsubscribe("HDFCBANK", "NSE", 1)
        adapter.subscribe("HDFCBANK", "NSE", 1)
        adapter.batch_timer.cancel()

    ws.on_send = churn
    adapter._process_batch_subscriptions()

    assert _messages(ws, "unsubscribe") == []
    assert adapter._broker_channels == {(decoder.COMPACT_MODE, 1, 1333)}


def test_churning_many_instruments_leaves_no_state_behind(adapter, monkeypatch):
    """Every per-instrument container empties once its subscriptions are gone."""
    monkeypatch.setattr(
        adapter_module.SymbolMapper,
        "get_token_from_symbol",
        lambda symbol, exchange: {"token": symbol[1:], "brexchange": exchange},
    )
    ws = _connect(adapter)
    for n in range(300):
        symbol = f"S{10000 + n}"
        for mode in (1, 2, 3):
            assert adapter.subscribe(symbol, "NSE", mode)["status"] == "success"
        if n % 3 == 0:  # some unsubscribe while the subscribe is on its way
            ws.on_send = lambda s=symbol: adapter.unsubscribe(s, "NSE", 3)
        adapter.batch_timer.cancel()
        adapter._process_batch_subscriptions()
        adapter._on_message(None, compact_packet(instrument_token=10000 + n))
        adapter._on_message(None, snapquote_packet(instrument_token=10000 + n))
        for mode in (1, 2, 3):
            adapter.unsubscribe(symbol, "NSE", mode)

    assert adapter.subscriptions == {} and adapter.subscription_queue == {}
    assert adapter._broker_channels == set() and adapter._inflight == {}
    assert adapter._last_ltp == {} and dict(adapter._routes) == {}
    assert adapter._depth_instruments == frozenset()
    subscribed = {(m, tuple(i)) for m, v in _messages(ws, "subscribe") for i in v}
    unsubscribed = {(m, tuple(i)) for m, v in _messages(ws, "unsubscribe") for i in v}
    assert subscribed == unsubscribed, "a channel was left streaming at the broker"


def test_an_exchange_the_feed_does_not_have_is_refused_not_sent_as_nse(adapter, monkeypatch):
    monkeypatch.setitem(TOKENS, ("SOYBEAN", "NCDEX"), "555")
    response = adapter.subscribe("SOYBEAN", "NCDEX", 1)
    assert response["status"] == "error"
    assert adapter.subscriptions == {}


def test_depth_other_than_five_levels_is_refused(adapter):
    response = adapter.subscribe("HDFCBANK", "NSE", 3, depth_level=20)
    assert response["status"] == "error"
    assert response["message"].endswith(".")
    assert adapter.subscriptions == {}
    assert adapter.subscribe("HDFCBANK", "NSE", 3, depth_level=5)["actual_depth"] == 5


def test_an_index_streams_on_its_cash_segment(adapter):
    ws = _connect(adapter)
    _subscribe_now(adapter, "NIFTY", "NSE_INDEX", 1)
    assert _messages(ws, "subscribe") == [("compact_marketdata", [[1, 26000]])]
    adapter._on_message(None, compact_packet(instrument_token=26000, last_traded_price=2400050))
    assert adapter.published[-1] == (
        "NSE_INDEX_NIFTY_LTP",
        {"ltp": 24000.5, "timestamp": adapter.published[-1][1]["timestamp"]},
    )


def test_a_new_socket_gets_the_sdk_heartbeat_and_every_subscription_again(adapter, monkeypatch):
    monkeypatch.setattr(adapter_module, "HEARTBEAT_SECONDS", 60)
    first = _connect(adapter)
    _subscribe_now(adapter, "HDFCBANK", "NSE", 2)
    assert _messages(first, "subscribe") == [("marketdata", [[1, 1333]])]

    second = FakeSocket()
    adapter.running = True
    adapter.connected = False
    adapter.ws_client = second
    try:
        adapter._on_open(second)
        deadline = time.monotonic() + 2
        while not second.sent and time.monotonic() < deadline:
            time.sleep(0.01)
        assert second.sent[0] == {"a": "h", "v": [], "m": ""}

        adapter.batch_timer.cancel()
        adapter._process_batch_subscriptions()
        assert _messages(second, "subscribe") == [("marketdata", [[1, 1333]])]
    finally:
        adapter._on_close(second)


# ------------------------------------------------------------- the connection


class FakeApp:
    """websocket.WebSocketApp stand-in: records the URL, stops the loop on run."""

    made: list[FakeApp] = []
    adapter = None

    def __init__(self, url, **_callbacks):
        self.url = url
        FakeApp.made.append(self)

    def run_forever(self):
        FakeApp.adapter._reconnect_stop.set()

    def close(self):
        pass


@pytest.fixture
def fake_app(monkeypatch, adapter):
    FakeApp.made = []
    FakeApp.adapter = adapter
    monkeypatch.setattr(adapter_module.websocket, "WebSocketApp", FakeApp)
    adapter.user_id = "openalgo-admin"
    adapter.running = True
    adapter._reconnect_stop = threading.Event()
    return FakeApp


class Captured(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


@pytest.fixture
def captured_logs():
    handler = Captured()
    names = ("pocketful_websocket", "broker.pocketful.streaming.pocketful_adapter")
    loggers = [logging.getLogger(name) for name in names]
    levels = [lg.level for lg in loggers]
    for lg in loggers:
        lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)
    yield handler
    for lg, level in zip(loggers, levels, strict=True):
        lg.removeHandler(handler)
        lg.setLevel(level)


def test_the_socket_signs_in_with_the_sessions_client_id_not_the_openalgo_user(
    adapter, fake_app, monkeypatch, captured_logs
):
    """login_id was OpenAlgo's own user name; the feed needs the Pocketful client."""
    monkeypatch.setattr(
        adapter_module, "get_auth_token", lambda *a, **k: "CSG981:::SEKRET-access.token"
    )

    adapter._connect_with_retry(adapter._reconnect_stop)

    assert [app.url for app in fake_app.made] == [
        "wss://algo.pocketful.in/ws/v1/feeds?login_id=CSG981&access_token=SEKRET-access.token"
    ]
    assert captured_logs.lines, "the connection logged nothing at all"
    assert not [line for line in captured_logs.lines if "SEKRET" in line]


def test_a_session_without_a_client_id_never_opens_a_socket(adapter, fake_app, monkeypatch):
    monkeypatch.setattr(adapter_module, "get_auth_token", lambda *a, **k: "bare-token")
    monkeypatch.setattr(adapter_module, "stored_client_id", lambda token: None)
    waits = []

    class Stop:
        def is_set(self):
            return bool(waits)

        def wait(self, seconds):
            waits.append(seconds)
            return True

    adapter._connect_with_retry(Stop())

    assert fake_app.made == []
    assert adapter.reconnect_attempts == 1 and waits, "it backs off instead of spinning"


def test_initialize_refuses_a_session_without_a_client_id(adapter, monkeypatch):
    # Only a packed token names its client; nothing stored backs up a bare one.
    monkeypatch.setattr(
        adapter_module, "stored_client_id", lambda token: adapter_module.split_token(token)[0]
    )
    with pytest.raises(ValueError, match="Log in to Pocketful again"):
        adapter.initialize("pocketful", "openalgo-admin", {"auth_token": "bare-token"})
    adapter.initialize("pocketful", "openalgo-admin", {"auth_token": "CSG981:::tok"})
    assert adapter.running is True


def test_repeated_connects_during_backoff_keep_one_retry_thread(adapter, monkeypatch):
    """test_gthread_memory_streaming pins this with a bare token; the same
    behaviour holds with a session token in the stored layout."""
    entered = threading.Event()

    class App:
        def __init__(self, *_args, **_kwargs):
            pass

        def run_forever(self):
            entered.set()

        def close(self):
            pass

    monkeypatch.setattr(adapter_module.websocket, "WebSocketApp", App)
    monkeypatch.setattr(adapter_module, "get_auth_token", lambda *a, **k: "C1:::token")
    adapter.user_id = "openalgo-admin"
    adapter.access_token = "C1:::token"
    adapter.running = True
    adapter.reconnect_delay = adapter.max_reconnect_delay = 60
    adapter.max_reconnect_attempts = 1000

    def retry_threads():
        return [
            t
            for t in threading.enumerate()
            if t.name == "pocketful-market-reconnect" and t.is_alive()
        ]

    adapter.connect()
    try:
        assert entered.wait(2), "the retry thread never reached the socket"
        for _ in range(50):
            adapter.connect()
        assert len(retry_threads()) == 1
    finally:
        adapter.disconnect()
    deadline = time.monotonic() + 2
    while retry_threads() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert retry_threads() == [], "disconnect left the retry thread in its backoff"
