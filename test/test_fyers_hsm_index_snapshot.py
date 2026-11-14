"""An index snapshot leaves the rest of its HSM frame readable.

HSM sends an index snapshot (topic ``if|``) with the same tail as a scrip
snapshot: two skipped bytes, the multiplier, the precision, and three
length-prefixed strings (exchange, exchange token, symbol). The parser read the
index fields and stopped there, so the next scrip in the frame was read from
inside that tail. Its data type came out as 0, the frame loop gave up, and every
snapshot after the index was lost. Those symbols never got a first snapshot, so
their updates were skipped too and they never ticked.

Seen live on 3 November 2026: a frame of 24 snapshots with India VIX fourth, and
the 20 after it never ticked. The frames below are built byte for byte the way
HSM sends them.
"""

import struct

import pytest

from broker.fyers.streaming.fyers_hsm_websocket import FyersHSMWebSocket
from utils.logging import get_logger

NULL = -2147483648
IF = "if|nse_cm|India VIX"
SF = "sf|nse_fo|35003"


def _frame(*scrips):
    return bytearray(
        bytes([0, 0, 6, 0, 0, 0, 0]) + struct.pack("!H", len(scrips)) + b"".join(scrips)
    )


def _snapshot(topic_id, topic, names, fields, strings):
    body = bytes([83]) + struct.pack("H", topic_id) + bytes([len(topic)]) + topic.encode()
    body += bytes([len(names)])
    body += b"".join(struct.pack(">i", fields.get(n, NULL)) for n in names)
    body += b"\x00\x1e" + struct.pack(">H", 1) + bytes([2])
    for s in strings:
        body += bytes([len(s)]) + s.encode()
    return body


@pytest.fixture()
def ws():
    ws = object.__new__(FyersHSMWebSocket)
    ws.logger = get_logger("test_hsm_index")
    ws.subscriptions, ws.scrips_data, ws.index_data, ws.depth_data = {}, {}, {}, {}
    ws.symbol_mappings = {IF: "NSE:INDIAVIX-INDEX", SF: "NSE:NIFTY26NOVFUT"}
    ws.on_error_callback = None
    ws.received = []
    ws.on_message_callback = ws.received.append
    return ws


def _index():
    return _snapshot(
        1,
        IF,
        FyersHSMWebSocket.INDEX_FIELDS[:6],
        {"ltp": 1342, "prev_close_price": 1310},
        ("nse_cm", "India VIX", "India VIX"),
    )


def _scrip():
    return _snapshot(
        2,
        SF,
        FyersHSMWebSocket.DATA_FIELDS,
        {"ltp": 2410050},
        ("nse_fo", "35003", "NIFTY26NOVFUT"),
    )


def test_a_scrip_after_an_index_in_the_same_frame_is_read(ws):
    ws._parse_binary_message(_frame(_index(), _scrip()))

    assert [m["hsm_token"] for m in ws.received] == [IF, SF]
    assert ws.scrips_data[2]["ltp"] == 2410050
    assert ws.scrips_data[2]["symbol"] == "NIFTY26NOVFUT"


def test_the_index_snapshot_keeps_its_fields_and_precision(ws):
    ws._parse_binary_message(_frame(_index()))

    index = ws.index_data[1]
    assert index["ltp"] == 1342
    assert index["prev_close_price"] == 1310
    assert index["multiplier"] == 1
    assert index["precision"] == 2
    assert index["original_symbol"] == "NSE:INDIAVIX-INDEX"


def test_two_indices_in_a_row_both_arrive(ws):
    second = _snapshot(
        3,
        "if|nse_cm|Nifty 50",
        FyersHSMWebSocket.INDEX_FIELDS[:6],
        {"ltp": 2400000},
        ("nse_cm", "Nifty 50", "Nifty 50"),
    )
    ws._parse_binary_message(_frame(_index(), second, _scrip()))

    assert [m["hsm_token"] for m in ws.received] == [IF, "if|nse_cm|Nifty 50", SF]


def test_an_index_whose_frame_ends_before_the_tail_still_arrives(ws):
    cut = _index()
    cut = cut[: cut.index(b"\x00\x1e") + 2]
    ws._parse_binary_message(_frame(cut))

    assert [m["hsm_token"] for m in ws.received] == [IF]
    assert ws.index_data[1]["ltp"] == 1342
    assert "multiplier" not in ws.index_data[1]
