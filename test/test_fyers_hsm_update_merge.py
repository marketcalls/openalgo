"""Fyers HSM feed publishes each update whole, and invents nothing (issue #2318).

An HSM update frame (data type 0x55) is one incremental change to a scrip. The
client used to send a message after every changed field, so the first message
carried the new LTP with the previous tick's volume, bid and ask, and the
adapter then dropped the complete messages that followed as duplicates of that
LTP. Subscribers saw every field except LTP one update behind, and an update
that moved only bid or ask never arrived. Live on MCX, 36 of 37 published
CRUDEOIL ticks carried stale fields.

The same issue showed three values that Fyers never sends: change and change %
were always 0 (the frame has no ch/chp, the SDK derives them from ltp and
prev_close_price), a depth message carried the bid/ask midpoint as its LTP
(9665.50 on a contract that ticks in whole rupees), and index depth was five
made-up levels around the index value.

The frames below are built byte for byte the way HSM sends them.
"""

import struct
import threading

import pytest

from broker.fyers.streaming.fyers_adapter import FyersAdapter
from broker.fyers.streaming.fyers_hsm_websocket import FyersHSMWebSocket
from broker.fyers.streaming.fyers_mapping import FyersDataMapper
from utils.logging import get_logger

NULL = -2147483648
FULL = "MCX:CRUDEOIL19NOV26FUT"
SF = "sf|mcx_fo|472789"
DP = "dp|mcx_fo|472789"
SF_ID, DP_ID = 7, 8


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
    for s in ("MCX", "472789", "CRUDEOIL26NOVFUT"):
        body += bytes([len(s)]) + s.encode()
    return body


def _update(topic_id, names, fields):
    return bytes([85]) + struct.pack("H", topic_id) + bytes([len(names)]) + _ints(fields, names)


QUOTE_FIELDS = FyersHSMWebSocket.DATA_FIELDS
DEPTH_FIELDS = FyersHSMWebSocket.DEPTH_FIELDS

BASE = {
    "ltp": 966500,
    "vol_traded_today": 18450,
    "last_traded_time": 1793170000,
    "exch_feed_time": 1793170000,
    "bid_size": 1,
    "ask_size": 8,
    "bid_price": 966500,
    "ask_price": 966600,
    "last_traded_qty": 1,
    "tot_buy_qty": 955,
    "tot_sell_qty": 872,
    "avg_trade_price": 966400,
    "low_price": 958400,
    "high_price": 973500,
    "open_price": 966100,
    "prev_close_price": 979800,
}

DEPTH = {
    "bid_price1": 966500,
    "ask_price1": 966600,
    "bid_size1": 1,
    "ask_size1": 8,
    "bid_order1": 1,
    "ask_order1": 2,
}


@pytest.fixture()
def feed():
    """Real HSM parser wired to the real adapter, with no socket."""
    ws = object.__new__(FyersHSMWebSocket)
    ws.logger = get_logger("test_hsm")
    ws.subscriptions, ws.scrips_data, ws.index_data, ws.depth_data = {}, {}, {}, {}
    ws.symbol_mappings = {SF: FULL, DP: FULL}
    ws.on_error_callback = None

    ad = object.__new__(FyersAdapter)
    ad.logger = ws.logger
    ad.data_mapper = FyersDataMapper()
    ad.lock = threading.Lock()
    ad.last_ltp = {}
    ad.active_subscriptions = {FULL: {"symbol": "CRUDEOIL19NOV26FUT", "exchange": "MCX"}}
    ad.hsm_to_symbol = {SF: FULL, DP: FULL}
    ad.symbol_to_hsm = {FULL: SF}

    raw, quotes, depths = [], [], []
    ad.subscription_callbacks = {}

    def on_raw(d):
        raw.append(d)
        ad._on_message(d)

    ws.on_message_callback = on_raw

    class Feed:
        pass

    f = Feed()
    f.ws, f.ad, f.raw, f.quotes, f.depths = ws, ad, raw, quotes, depths

    def send(*scrips):
        raw.clear()
        quotes.clear()
        depths.clear()
        ws._parse_binary_message(_frame(*scrips))

    def subscribe(quote=False, depth=False):
        if quote:
            ad.subscription_callbacks[f"SymbolUpdate_{FULL}"] = quotes.append
        if depth:
            ad.subscription_callbacks[f"DepthUpdate_{FULL}"] = depths.append

    f.send, f.subscribe = send, subscribe
    return f


TICK = {
    "ltp": 966600,
    "vol_traded_today": 18453,
    "last_traded_qty": 3,
    "bid_price": 966600,
    "ask_price": 966700,
    "last_traded_time": 1793170001,
}


# --- the reported bug: one update, one complete message ----------------------


def test_update_frame_is_sent_once_with_every_field(feed):
    feed.subscribe(quote=True)
    feed.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    feed.send(_update(SF_ID, QUOTE_FIELDS, TICK))

    assert len(feed.raw) == 1, "one message per scrip per update frame"
    assert len(feed.quotes) == 1
    q = feed.quotes[0]
    assert q["ltp"] == 9666.0
    # Every one of these was the previous tick's value before the fix
    assert q["volume"] == 18453
    assert q["last_trade_quantity"] == 3
    assert q["bid_price"] == 9666.0
    assert q["ask_price"] == 9667.0
    assert q["last_traded_time"] == 1793170001


def test_update_that_moves_only_bid_and_ask_is_published(feed):
    feed.subscribe(quote=True)
    feed.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    feed.send(_update(SF_ID, QUOTE_FIELDS, TICK))
    # Same second, same LTP: the old LTP de-duplication dropped this one
    feed.send(_update(SF_ID, QUOTE_FIELDS, {"bid_price": 966650, "ask_price": 966750}))

    assert len(feed.quotes) == 1
    assert feed.quotes[0]["ltp"] == 9666.0
    assert feed.quotes[0]["bid_price"] == 9666.5
    assert feed.quotes[0]["ask_price"] == 9667.5


def test_update_with_no_change_sends_nothing(feed):
    feed.subscribe(quote=True)
    feed.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    feed.send(_update(SF_ID, QUOTE_FIELDS, {"ltp": BASE["ltp"]}))
    assert feed.raw == []


def test_update_for_unknown_topic_does_not_break_the_next_scrip(feed):
    feed.subscribe(quote=True)
    feed.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    feed.send(_update(99, QUOTE_FIELDS, TICK), _update(SF_ID, QUOTE_FIELDS, TICK))
    assert len(feed.quotes) == 1
    assert feed.quotes[0]["volume"] == 18453


# --- change and change % ------------------------------------------------------


def test_change_is_derived_from_ltp_and_previous_close():
    quote = FyersDataMapper().map_to_openalgo_quote(
        {"type": "sf", "symbol": FULL, "ltp": 966500, "prev_close_price": 979800, "precision": 2}
    )
    # 9665 - 9798, as the Fyers app shows: -133 (-1.36%)
    assert quote["change"] == -133.0
    assert quote["change_percent"] == -1.36


def test_change_stays_zero_without_previous_close():
    quote = FyersDataMapper().map_to_openalgo_quote({"type": "sf", "symbol": FULL, "ltp": 966500})
    assert quote["change"] == 0.0
    assert quote["change_percent"] == 0.0


# --- depth carries a real LTP or none ----------------------------------------


def test_depth_has_no_midpoint_ltp():
    depth = FyersDataMapper().map_to_openalgo_depth({"type": "dp", "symbol": FULL, **DEPTH})
    assert "ltp" not in depth
    assert depth["depth"]["buy"][0]["price"] == 9665.0


def test_depth_alone_publishes_without_ltp(feed):
    feed.subscribe(depth=True)
    feed.send(_snapshot(DP_ID, DP, DEPTH_FIELDS, DEPTH))
    assert len(feed.depths) == 1
    assert "ltp" not in feed.depths[0]


def test_depth_borrows_the_real_ltp_from_the_quote_feed(feed):
    feed.subscribe(quote=True, depth=True)
    feed.send(_snapshot(SF_ID, SF, QUOTE_FIELDS, BASE))
    feed.send(_snapshot(DP_ID, DP, DEPTH_FIELDS, DEPTH))
    # 9665.0 traded; the old midpoint of 9665 / 9666 was 9665.5
    assert feed.depths[0]["ltp"] == 9665.0
    assert feed.ad.get_last_ltp("MCX", "CRUDEOIL19NOV26FUT") == 9665.0


def test_tbt_depth_has_no_midpoint_ltp():
    depth = FyersDataMapper().map_tbt_depth_to_openalgo(
        "MCX:CRUDEOIL26NOVFUT",
        {
            "buy": [{"price": 9665.0, "quantity": 1, "orders": 1}],
            "sell": [{"price": 9666.0, "quantity": 8, "orders": 2}],
        },
        "CRUDEOIL19NOV26FUT:50",
        "MCX",
    )
    assert "ltp" not in depth


def test_index_depth_is_empty_not_invented():
    depth = FyersDataMapper().map_index_to_depth(
        {"type": "if", "symbol": "NSE:NIFTY50-INDEX", "ltp": 2293675}
    )
    assert depth["ltp"] == 22936.75
    assert depth["depth"] == {"buy": [], "sell": []}
