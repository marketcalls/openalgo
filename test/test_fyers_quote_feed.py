"""Fyers streaming publishes complete quote fields on every topic.

An AmiBroker client on the WebSocket proxy saw blank or random values in its
quote window while LTP charts worked. The proxy forwards a DEPTH topic to the
QUOTE and LTP subscribers of the same symbol, assuming a depth message carries
every quote field, and three Fyers defects broke that:

1. A depth subscription only subscribed the HSM depth feed (dp), which carries
   the five book levels and nothing else: no LTP, OHLC, volume or traded
   quantities. Depth now also subscribes the scrip's symbol feed (sf) and
   merges its latest quote fields into every depth message.
2. LTP and Quote on one symbol shared one callback slot, so the later
   registration won and unsubscribing either silenced both.
3. The reference key names other brokers publish (average_price,
   percent_change, last_quantity, last_trade_time) were missing.

Also: a tick whose HSM topic is not mapped used to be routed by symbol-name
substrings or to "the only subscription"; it is now dropped.

Frames are built byte for byte the way HSM sends them; no network, no socket.
"""

import struct
import threading

import pytest

import broker.fyers.streaming.fyers_adapter as fa_mod
from broker.fyers.streaming.fyers_adapter import FyersAdapter
from broker.fyers.streaming.fyers_hsm_websocket import FyersHSMWebSocket
from broker.fyers.streaming.fyers_mapping import FyersDataMapper
from broker.fyers.streaming.fyers_websocket_adapter import FyersWebSocketAdapter
from utils.logging import get_logger

NULL = -2147483648
EXCH, SYM = "NSE", "SBIN"
FULL = f"{EXCH}:{SYM}"
BRSYM = "NSE:SBIN-EQ"
SF = "sf|nse_cm|3045"
DP = "dp|nse_cm|3045"
SF_ID, DP_ID = 11, 12

QUOTE_FIELDS = FyersHSMWebSocket.DATA_FIELDS
DEPTH_FIELDS = FyersHSMWebSocket.DEPTH_FIELDS

BASE = {
    "ltp": 80150,
    "vol_traded_today": 523000,
    "last_traded_time": 1793170000,
    "exch_feed_time": 1793170001,
    "bid_size": 10,
    "ask_size": 20,
    "bid_price": 80145,
    "ask_price": 80150,
    "last_traded_qty": 7,
    "tot_buy_qty": 91000,
    "tot_sell_qty": 88000,
    "avg_trade_price": 80010,
    "low_price": 79500,
    "high_price": 80500,
    "open_price": 79800,
    "prev_close_price": 79000,
}

BOOK = {
    "bid_price1": 80145,
    "ask_price1": 80150,
    "bid_size1": 10,
    "ask_size1": 20,
    "bid_order1": 2,
    "ask_order1": 3,
}


def _frame(*scrips):
    return bytearray(
        bytes([0, 0, 6, 0, 0, 0, 0]) + struct.pack("!H", len(scrips)) + b"".join(scrips)
    )


def _ints(fields, names):
    return b"".join(struct.pack(">i", fields.get(n, NULL)) for n in names)


def _snapshot(topic_id, topic, names, fields):
    body = bytes([83]) + struct.pack("H", topic_id) + bytes([len(topic)]) + topic.encode()
    body += bytes([len(names)]) + _ints(fields, names)
    body += b"\x00\x00" + struct.pack(">H", 1) + bytes([2])
    for s in ("NSE", "3045", "SBIN-EQ"):
        body += bytes([len(s)]) + s.encode()
    return body


def _update(topic_id, names, fields):
    return bytes([85]) + struct.pack("H", topic_id) + bytes([len(names)]) + _ints(fields, names)


class FakeTokenConverter:
    """Stands in for the Fyers symbol-token API: SBIN -> sf/dp topic."""

    def __init__(self):
        self.calls = []

    def convert_openalgo_symbols_to_hsm(self, symbols, data_type):
        self.calls.append(data_type)
        token = DP if data_type == "DepthUpdate" else SF
        return [token], {token: BRSYM}, []


class FakeHsmClient:
    """Records what goes on the wire and feeds the real parser's mappings."""

    def __init__(self, parser):
        self.parser = parser
        self.sent = []

    def subscribe_symbols(self, tokens, mappings):
        self.sent.extend(tokens)
        self.parser.symbol_mappings.update(mappings)

    def is_connected(self):
        return True

    def disconnect(self):
        pass


# The objects below are built without __init__; their destructors would try to
# tear down sockets that were never opened.
class _Parser(FyersHSMWebSocket):
    def __del__(self):
        pass


class _Adapter(FyersAdapter):
    def __del__(self):
        pass


class _Outer(FyersWebSocketAdapter):
    def __del__(self):
        pass


@pytest.fixture()
def stack(monkeypatch):
    """Real HSM parser -> real FyersAdapter -> real proxy adapter, no sockets."""
    monkeypatch.setattr(fa_mod, "get_br_symbol", lambda s, e: BRSYM)

    ws = object.__new__(_Parser)
    ws.logger = get_logger("test_fyers_quote_feed")
    ws.subscriptions, ws.scrips_data, ws.index_data, ws.depth_data = {}, {}, {}, {}
    ws.symbol_mappings = {}
    ws.on_error_callback = None

    ad = object.__new__(_Adapter)
    ad.access_token, ad.userid = "token", "user"
    ad.logger = ws.logger
    ad.token_converter = FakeTokenConverter()
    ad.data_mapper = FyersDataMapper()
    ad.ws_client = FakeHsmClient(ws)
    ad.active_subscriptions, ad.subscription_callbacks = {}, {}
    ad.symbol_to_hsm, ad.hsm_to_symbol = {}, {}
    ad.connected, ad.connecting, ad.last_error = True, False, None
    ad.lock = threading.Lock()
    ad.last_ltp, ad.latest_quote, ad.depth_awaiting_quote = {}, {}, {}
    ws.on_message_callback = ad._on_message

    outer = object.__new__(_Outer)
    outer.logger = ws.logger
    outer.lock = threading.Lock()
    outer.subscriptions = {}
    outer.active_callbacks = {}
    outer.connected = True
    outer.fyers_adapter = ad
    outer.socket = object()
    outer.tbt_subscriptions, outer.tbt_symbol_to_ticker, outer.tbt_ticker_to_symbol = {}, {}, {}
    outer.tbt_client = None
    outer._hsm_batch_queue, outer._hsm_batch_timer = [], None
    outer._hsm_batch_lock = threading.Lock()
    outer._hsm_callback_registry = {}
    outer.HSM_BATCH_DELAY_SEC = 3600

    published = []
    outer.publish_market_data = lambda topic, data: published.append((topic, dict(data)))

    class Stack:
        pass

    s = Stack()
    s.ws, s.ad, s.outer, s.published = ws, ad, outer, published

    def subscribe(*modes):
        for mode in modes:
            assert outer.subscribe(SYM, EXCH, mode)["status"] == "success"
        outer._hsm_batch_timer.cancel()
        outer._flush_hsm_batch()

    def send(*scrips):
        published.clear()
        ws._parse_binary_message(_frame(*scrips))

    def topics():
        return [t for t, _ in published]

    def payload(topic):
        return [d for t, d in published if t == topic][-1]

    s.subscribe, s.send, s.topics, s.payload = subscribe, send, topics, payload
    yield s
    with outer._hsm_batch_lock:
        if outer._hsm_batch_timer is not None:
            outer._hsm_batch_timer.cancel()


QUOTE_KEYS = {
    "ltp": 801.5,
    "open": 798.0,
    "high": 805.0,
    "low": 795.0,
    "close": 790.0,
    "volume": 523000,
    "average_price": 800.1,
    "avg_trade_price": 800.1,
    "last_quantity": 7,
    "last_trade_quantity": 7,
    "last_trade_time": 1793170000,
    "last_traded_time": 1793170000,
    "percent_change": 1.46,
    "change_percent": 1.46,
    "total_buy_quantity": 91000,
    "total_sell_quantity": 88000,
}


# --- defect 1: depth subscribes the symbol feed and carries the quote --------


def test_depth_subscription_also_subscribes_the_symbol_feed(stack):
    stack.subscribe(3)
    assert DP in stack.ad.ws_client.sent
    assert SF in stack.ad.ws_client.sent
    assert stack.ad.hsm_to_symbol[SF] == FULL
    # One symbol-token lookup, not two
    assert stack.ad.token_converter.calls == ["DepthUpdate"]


def test_depth_message_carries_every_quote_field(stack):
    stack.subscribe(3)
    stack.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    stack.send(_snapshot(DP_ID, DP, DEPTH_FIELDS, BOOK))

    assert stack.topics() == ["NSE_SBIN_DEPTH"]
    depth = stack.payload("NSE_SBIN_DEPTH")
    for key, value in QUOTE_KEYS.items():
        assert depth[key] == value, key
    assert depth["depth"]["buy"][0] == {"price": 801.45, "quantity": 10, "orders": 2}
    assert depth["subscription_mode"] == 3


def test_depth_follows_the_latest_quote_update(stack):
    stack.subscribe(3)
    stack.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE), _snapshot(DP_ID, DP, DEPTH_FIELDS, BOOK))
    stack.send(
        _update(
            SF_ID, QUOTE_FIELDS, {"ltp": 80200, "vol_traded_today": 523500, "high_price": 80600}
        )
    )
    stack.send(_update(DP_ID, DEPTH_FIELDS, {"bid_size1": 15}))

    depth = stack.payload("NSE_SBIN_DEPTH")
    assert depth["ltp"] == 802.0
    assert depth["volume"] == 523500
    assert depth["high"] == 806.0


def test_depth_before_the_first_quote_is_sent_again_complete(stack):
    stack.subscribe(3)
    stack.send(_snapshot(DP_ID, DP, DEPTH_FIELDS, BOOK))
    early = stack.payload("NSE_SBIN_DEPTH")
    assert "ltp" not in early and "open" not in early  # nothing invented

    stack.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    assert stack.topics() == ["NSE_SBIN_DEPTH"]
    depth = stack.payload("NSE_SBIN_DEPTH")
    assert depth["ltp"] == 801.5 and depth["open"] == 798.0
    assert depth["depth"]["buy"][0]["price"] == 801.45

    # Only once: the next quote tick does not resend the book
    stack.send(_update(SF_ID, QUOTE_FIELDS, {"ltp": 80200}))
    assert stack.topics() == []


def test_unsent_quote_field_is_left_out_of_depth(stack):
    stack.subscribe(3)
    partial = {k: v for k, v in BASE.items() if k != "avg_trade_price"}
    stack.send(
        _snapshot(SF_ID, SF, QUOTE_FIELDS, partial), _snapshot(DP_ID, DP, DEPTH_FIELDS, BOOK)
    )
    depth = stack.payload("NSE_SBIN_DEPTH")
    assert "average_price" not in depth and "avg_trade_price" not in depth
    assert depth["ltp"] == 801.5


# --- reference counting across LTP, Quote and Depth ---------------------------


def test_unsubscribing_quote_keeps_depth_complete(stack):
    stack.subscribe(2, 3)
    stack.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE), _snapshot(DP_ID, DP, DEPTH_FIELDS, BOOK))
    assert set(stack.topics()) == {"NSE_SBIN_QUOTE", "NSE_SBIN_DEPTH"}

    stack.outer.unsubscribe(SYM, EXCH, 2)
    stack.send(_update(SF_ID, QUOTE_FIELDS, {"ltp": 80200}))
    assert stack.topics() == []  # no QUOTE subscriber left
    stack.send(_update(DP_ID, DEPTH_FIELDS, {"bid_size1": 15}))
    assert stack.topics() == ["NSE_SBIN_DEPTH"]
    assert stack.payload("NSE_SBIN_DEPTH")["ltp"] == 802.0


def test_unsubscribing_depth_keeps_quote(stack):
    stack.subscribe(2, 3)
    stack.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE), _snapshot(DP_ID, DP, DEPTH_FIELDS, BOOK))

    stack.outer.unsubscribe(SYM, EXCH, 3)
    stack.send(_update(SF_ID, QUOTE_FIELDS, {"ltp": 80200}))
    assert stack.topics() == ["NSE_SBIN_QUOTE"]
    assert stack.payload("NSE_SBIN_QUOTE")["ltp"] == 802.0
    stack.send(_update(DP_ID, DEPTH_FIELDS, {"bid_size1": 15}))
    assert stack.topics() == []


# --- defect 2: LTP and Quote are tracked apart --------------------------------


def test_ltp_and_quote_both_publish(stack):
    stack.subscribe(1, 2)
    stack.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    assert sorted(stack.topics()) == ["NSE_SBIN_LTP", "NSE_SBIN_QUOTE"]
    assert stack.payload("NSE_SBIN_LTP")["subscription_mode"] == 1
    assert stack.payload("NSE_SBIN_QUOTE")["subscription_mode"] == 2


def test_quote_then_ltp_registration_keeps_quote(stack):
    # Separate flushes, quote first: the later LTP registration used to
    # replace the quote callback
    stack.subscribe(2)
    stack.subscribe(1)
    stack.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    assert sorted(stack.topics()) == ["NSE_SBIN_LTP", "NSE_SBIN_QUOTE"]


@pytest.mark.parametrize("gone, kept", [(1, "NSE_SBIN_QUOTE"), (2, "NSE_SBIN_LTP")])
def test_unsubscribing_one_of_ltp_and_quote_keeps_the_other(stack, gone, kept):
    stack.subscribe(1, 2)
    stack.outer.unsubscribe(SYM, EXCH, gone)
    stack.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    assert stack.topics() == [kept]
    assert f"SymbolUpdate_{FULL}" in stack.ad.subscription_callbacks


def test_unsubscribing_both_releases_the_symbol_slot(stack):
    stack.subscribe(1, 2, 3)
    stack.outer.unsubscribe(SYM, EXCH, 1)
    stack.outer.unsubscribe(SYM, EXCH, 2)
    assert f"SymbolUpdate_{FULL}" not in stack.ad.subscription_callbacks
    assert f"DepthUpdate_{FULL}" in stack.ad.subscription_callbacks


# --- defect 3: reference key names --------------------------------------------


def test_quote_carries_reference_and_existing_key_names(stack):
    stack.subscribe(2)
    stack.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    quote = stack.payload("NSE_SBIN_QUOTE")
    for key, value in QUOTE_KEYS.items():
        assert quote[key] == value, key


# --- routing: an unmapped tick is dropped, not guessed -------------------------


def test_unmapped_topic_is_not_routed_to_the_only_subscription(stack):
    stack.subscribe(2)
    other = "sf|nse_cm|99999"
    stack.ws.symbol_mappings[other] = "NSE:SBINX-EQ"
    stack.send(_snapshot(21, other, QUOTE_FIELDS, {**BASE, "ltp": 12345}))
    assert stack.topics() == []


# --- 50-level (TBT) depth: carries the quote from the symbol feed ------------

import broker.fyers.streaming.fyers_websocket_adapter as fwa_mod  # noqa: E402

TBT_SYM = f"{SYM}:50"
TBT_BOOK = {
    "buy": [{"price": 801.45, "quantity": 10, "orders": 2}],
    "sell": [{"price": 801.5, "quantity": 20, "orders": 3}],
    "total_buy_qty": 91000,
    "total_sell_qty": 88000,
}


class FakeTbtClient:
    def __init__(self):
        self.subscribed, self.unsubscribed = [], []

    def subscribe(self, tickers, channel="1"):
        self.subscribed.extend(tickers)
        return True

    def unsubscribe(self, tickers):
        self.unsubscribed.extend(tickers)

    def disconnect(self):
        pass


@pytest.fixture()
def tbt(stack, monkeypatch):
    monkeypatch.setattr(fwa_mod, "get_br_symbol", lambda s, e: BRSYM)
    stack.outer.tbt_client = FakeTbtClient()
    stack.outer.data_mapper = FyersDataMapper()
    stack.outer._disconnect_tbt = lambda: None
    return stack


def _subscribe_tbt(s, *extra_modes):
    assert s.outer.subscribe(TBT_SYM, EXCH, 3)["status"] == "success"
    for mode in extra_modes:
        assert s.outer.subscribe(SYM, EXCH, mode)["status"] == "success"
    s.outer._hsm_batch_timer.cancel()
    s.outer._flush_hsm_batch()


def _tbt_depth(s):
    s.published.clear()
    s.outer._on_tbt_depth_update(BRSYM, dict(TBT_BOOK))
    return [d for t, d in s.published if t.endswith("_DEPTH")][-1]


def test_tbt_depth_also_subscribes_the_symbol_feed(tbt):
    _subscribe_tbt(tbt)
    assert BRSYM in tbt.outer.tbt_client.subscribed
    assert SF in tbt.ad.ws_client.sent


def test_tbt_quote_feed_publishes_nothing_on_its_own(tbt):
    _subscribe_tbt(tbt)
    tbt.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    assert tbt.topics() == []


def test_tbt_depth_carries_every_quote_field(tbt):
    _subscribe_tbt(tbt)
    tbt.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    depth = _tbt_depth(tbt)
    for key, value in QUOTE_KEYS.items():
        assert depth[key] == value, key
    assert depth["depth"]["buy"][0]["price"] == 801.45


def test_tbt_depth_before_any_quote_has_no_invented_fields(tbt):
    _subscribe_tbt(tbt)
    depth = _tbt_depth(tbt)
    for key in ("ltp", "open", "close", "volume"):
        assert key not in depth, key


def test_unsubscribing_tbt_releases_the_quote_feed(tbt):
    _subscribe_tbt(tbt)
    tbt.outer.unsubscribe(TBT_SYM, EXCH, 3)
    assert (tbt.outer._QUOTE_FEED_FOR_TBT, FULL) not in tbt.outer._hsm_callback_registry
    assert f"SymbolUpdate_{FULL}" not in tbt.ad.subscription_callbacks


def test_unsubscribing_tbt_keeps_a_live_quote_subscription(tbt):
    _subscribe_tbt(tbt, 2)
    tbt.outer.unsubscribe(TBT_SYM, EXCH, 3)
    assert f"SymbolUpdate_{FULL}" in tbt.ad.subscription_callbacks
    tbt.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    assert tbt.topics() == ["NSE_SBIN_QUOTE"]


# --- review follow-ups ---------------------------------------------------------


def test_index_quote_leaves_out_reference_fields_it_has_no_source_for():
    """An index (if) frame has no trade time, average price or traded
    quantity; their reference names are left out rather than sent as 0."""
    mapper = FyersDataMapper()
    index_frame = {
        "symbol": "NSE:NIFTY50-INDEX",
        "type": "if",
        "ltp": 2400000,
        "prev_close_price": 2390000,
        "high_price": 2410000,
        "low_price": 2380000,
        "open_price": 2395000,
        "exch_feed_time": 1793170001,
    }
    quote = mapper.map_fyers_data(index_frame, "Quote")
    for key in ("last_trade_time", "average_price", "last_quantity"):
        assert key not in quote, key

    stock_frame = dict(BASE, symbol=BRSYM, type="sf")
    quote = mapper.map_fyers_data(stock_frame, "Quote")
    assert quote["last_trade_time"] == 1793170000
    assert quote["average_price"] == 800.1
    assert quote["last_quantity"] == 7


def _keep_connection_open(s):
    """Another symbol stays subscribed, so unsubscribing ours does not close
    the Fyers connection (the case where an orphaned feed would linger)."""
    s.outer.subscriptions["NSE:INFY:2"] = {"symbol": "INFY", "exchange": "NSE", "mode": 2}


def test_tbt_unsubscribed_before_the_flush_subscribes_no_quote_feed(tbt):
    _keep_connection_open(tbt)
    assert tbt.outer.subscribe(TBT_SYM, EXCH, 3)["status"] == "success"
    tbt.outer.unsubscribe(TBT_SYM, EXCH, 3)
    if tbt.outer._hsm_batch_timer is not None:
        tbt.outer._hsm_batch_timer.cancel()
    tbt.outer._flush_hsm_batch()

    assert SF not in tbt.ad.ws_client.sent
    assert (tbt.outer._QUOTE_FEED_FOR_TBT, FULL) not in tbt.outer._hsm_callback_registry


def test_tbt_resubscription_does_not_merge_the_old_quote(tbt):
    _keep_connection_open(tbt)
    _subscribe_tbt(tbt)
    tbt.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    tbt.outer.unsubscribe(TBT_SYM, EXCH, 3)
    assert tbt.ad.get_latest_quote(EXCH, SYM) is None

    _subscribe_tbt(tbt)
    depth = _tbt_depth(tbt)
    for key in ("ltp", "open", "close", "volume"):
        assert key not in depth, key


def test_tbt_release_keeps_the_quote_a_5_level_depth_still_reads(tbt):
    _subscribe_tbt(tbt, 3)
    tbt.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    tbt.outer.unsubscribe(TBT_SYM, EXCH, 3)
    assert tbt.ad.get_latest_quote(EXCH, SYM) is not None
