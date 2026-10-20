"""Kotak SFeed binary wire protocol decoding.

SFeed is the feed Kotak actually routes accounts to; the legacy HSM feed that
HSWebSocketLib.py speaks is still served but no data centre selects it and
Kotak's SDK removed every path to it. These pin the replicated wire format,
because a struct layout that is wrong by one field decodes into plausible
numbers rather than an error - the failure mode is a wrong price, not a crash.

Packets here are built with the same struct layouts they are read back with,
so these do not prove the layout matches Kotak's server. What they prove is
the decoding logic around it: routing, scaling, depth-row slicing, sentinel
normalization and the drop rules. The layouts themselves are pinned by their
sizes, which the SFeed spec states independently (54-byte mini, 144-byte
market-picture fixed body, 16-byte depth row, 33-byte CAS, 16-byte status).
"""

import importlib.util
import struct
from pathlib import Path

import pytest

# Loaded by path for the same reason test_kotak_hsm_decoding.py does it: the
# streaming package's __init__ imports the adapter, which imports
# websocket_proxy, which imports the adapter back. The decoder has no such
# dependency and a protocol test should not drag the proxy in to reach it.
_spec = importlib.util.spec_from_file_location(
    "kotak_sfeed_protocol",
    Path(__file__).resolve().parents[1] / "broker" / "kotak" / "streaming" / "sfeed_protocol.py",
)
sf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sf)


NSE_CM = 1  # exchange_id


def header(message_length, message_code, exchange_id=NSE_CM, level=0, auction_flag=0):
    return sf._HEADER.pack(message_length, message_code, exchange_id, level, auction_flag, 0, 0)


def market_picture(
    level=sf.LEVEL_TOUCH_LINE,
    token=11536,
    ltp=213500,
    open_price=210000,
    high=215000,
    low=209000,
    close=211000,
    volume=1500000,
    last_update_time=1700000000,
    buy_rows=((100, 213400, 3),),
    sell_rows=((150, 213600, 4),),
    buy_count=None,
    sell_count=None,
    auction_flag=0,
    exchange_id=NSE_CM,
    drop_rows=0,
):
    """Build a market-picture packet: 9-byte header, 135-byte body, depth rows.

    drop_rows truncates the packet after the fixed body so the "packet carried
    fewer rows than its counts claimed" path can be exercised.
    """
    buy_count = len(buy_rows) if buy_count is None else buy_count
    sell_count = len(sell_rows) if sell_count is None else sell_count

    body = sf._MP_BODY.pack(
        token,
        900,  # total_buy_qty
        800,  # total_sell_qty
        volume,
        1700000001,  # last_trade_time
        last_update_time,
        open_price,
        close,
        high,
        low,
        ltp,
        50,  # last_trade_qty
        212000,  # avg_trade_price
        0,  # indicative_close
        buy_count,
        sell_count,
        0,  # trading_status
        150,  # net_chg_percent, two implied decimals -> 1.50
        4200,  # open_interest
        99999.0,  # total_traded_value (double)
        2500,  # net_chg
        230000,  # upper_circuit
        190000,  # lower_circuit
        240000,  # yearly_high
        180000,  # yearly_low
        1,  # market_lot
        2,  # precision
        1,  # multiplier
    )

    rows = b"".join(sf._DEPTH_ROW.pack(q, p, o) for q, p, o in (*buy_rows, *sell_rows))
    if drop_rows:
        rows = rows[: -drop_rows * sf._DEPTH_ROW_SIZE]

    length = sf.HEADER_SIZE + len(body) + len(rows)
    return header(length, sf.MSG_MARKET_PICTURE, exchange_id, level, auction_flag) + body + rows


# --- framing ------------------------------------------------------------------


def test_a_batched_frame_yields_every_packet():
    a = market_picture(token=1)
    b = market_picture(token=2)

    assert sf.split_batch(a + b) == [a, b]


def test_a_truncated_tail_does_not_cost_the_packets_before_it():
    """A short final packet must not discard the whole frame."""
    good = market_picture(token=1)

    packets = sf.split_batch(good + good[:20])

    assert packets == [good]


def test_a_garbage_length_stops_the_scan():
    assert sf.split_batch(struct.pack("<H", 0) + b"\x00" * 40) == []


# --- scaling ------------------------------------------------------------------


def test_prices_are_scaled_by_the_exchange_divider():
    packet = market_picture(ltp=213500)

    decoded = sf.decode_packet(packet, {NSE_CM: 100})

    assert decoded["last_traded_price"] == 2135.00


def test_an_exchange_missing_from_the_auth_response_falls_back_to_100():
    """Kotak's own client defaults the same way rather than dropping the tick."""
    packet = market_picture(ltp=213500)

    decoded = sf.decode_packet(packet, {})

    assert decoded["last_traded_price"] == 2135.00


def test_a_currency_divider_keeps_four_decimals():
    """CDS quotes to 4dp: USDINR ticks at 0.0025, so a 100 divider loses real
    price. This is the SFeed-side equivalent of the precision bug fixed in
    HSWebSocketLib.setLongValues."""
    packet = market_picture(ltp=872350, exchange_id=3)  # cde_fo

    decoded = sf.decode_packet(packet, {3: 10000})

    assert decoded["last_traded_price"] == 87.2350


def test_percent_fields_are_not_scaled_by_the_exchange_divider():
    """net_chg_percent carries its own two implied decimals."""
    packet = market_picture()

    decoded = sf.decode_packet(packet, {NSE_CM: 10000})

    assert decoded["net_change_percent"] == 1.5


def test_a_quantity_is_never_divided():
    packet = market_picture(volume=1500000)

    decoded = sf.decode_packet(packet, {NSE_CM: 100})

    assert decoded["volume_traded_today"] == 1500000


# --- market picture -----------------------------------------------------------


def test_touch_line_reads_exactly_one_bid_and_one_ask():
    """Level 4 always carries 1+1, whatever the depth counts in the body say."""
    packet = market_picture(
        level=sf.LEVEL_TOUCH_LINE,
        buy_rows=((100, 213400, 3),),
        sell_rows=((150, 213600, 4),),
        buy_count=5,  # body lies; level wins
        sell_count=5,
    )

    decoded = sf.decode_packet(packet, {NSE_CM: 100})

    assert len(decoded["buy"]) == 1
    assert len(decoded["sell"]) == 1
    assert decoded["buy"][0] == {"quantity": 100, "price": 2134.00, "orders": 3}
    assert decoded["sell"][0] == {"quantity": 150, "price": 2136.00, "orders": 4}


def test_depth_reads_the_row_counts_from_the_body():
    buys = tuple((10 * i, 213400 - i, i) for i in range(1, 6))
    sells = tuple((20 * i, 213600 + i, i) for i in range(1, 6))
    packet = market_picture(level=sf.LEVEL_DEPTH, buy_rows=buys, sell_rows=sells)

    decoded = sf.decode_packet(packet, {NSE_CM: 100})

    assert len(decoded["buy"]) == 5
    assert len(decoded["sell"]) == 5
    assert decoded["buy"][0]["price"] == 2133.99


def test_fewer_rows_than_the_counts_claim_is_survived():
    """A short packet must yield the rows it has, not raise or invent any."""
    buys = tuple((10 * i, 213400 - i, i) for i in range(1, 6))
    sells = tuple((20 * i, 213600 + i, i) for i in range(1, 6))
    packet = market_picture(level=sf.LEVEL_DEPTH, buy_rows=buys, sell_rows=sells, drop_rows=3)

    decoded = sf.decode_packet(packet, {NSE_CM: 100})

    assert len(decoded["buy"]) == 5
    assert len(decoded["sell"]) == 2


def test_a_never_traded_instrument_reports_no_update_time_as_zero():
    """The exchange sends a negative 1900-01-01 placeholder here but a plain 0
    in last_trade_time for the same "nothing yet" case. One convention out."""
    packet = market_picture(last_update_time=-2208988800)

    decoded = sf.decode_packet(packet, {NSE_CM: 100})

    assert decoded["last_update_time"] == 0


def test_the_auction_flag_is_surfaced():
    packet = market_picture(auction_flag=1)

    assert sf.decode_packet(packet, {NSE_CM: 100})["auction"] is True


def test_an_unknown_level_is_ignored_rather_than_guessed():
    packet = market_picture(level=99)

    assert sf.decode_packet(packet, {NSE_CM: 100}) is None


# --- mini touch line ----------------------------------------------------------


def test_mini_touch_line_decodes():
    body = sf._MINI_BODY.pack(11536, 1700000000, 213500, 50, 211000, 150, 2500, 1, 2, 1)
    packet = header(sf.HEADER_SIZE + len(body), 0, level=sf.LEVEL_MINI_TOUCH_LINE) + body

    decoded = sf.decode_packet(packet, {NSE_CM: 100})

    assert decoded["type"] == "scrip_lite"
    assert decoded["last_traded_price"] == 2135.00
    assert decoded["close_price"] == 2110.00
    assert decoded["net_change_percent"] == 1.5


# --- index --------------------------------------------------------------------


def test_index_decodes_and_derives_change_from_close():
    body = sf._INDEX_BODY.pack(
        26000,
        2100000,
        2110000,
        2150000,
        2090000,
        2135000,
        1700000000,
        2400000,
        1800000,
        150,
        0.0,
        2,
        100,
        b"Nifty 50",
    )
    packet = header(sf.HEADER_SIZE + len(body), sf.MSG_INDEX) + body

    decoded = sf.decode_packet(packet, {NSE_CM: 100})

    assert decoded["type"] == "index"
    assert decoded["name"] == "Nifty 50"
    assert decoded["last_traded_price"] == 21350.00
    assert decoded["change"] == pytest.approx(250.00)


# --- market status ------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected_status_code", "expected_text"),
    [
        (sf.MSG_MARKET_OPEN, 1, "Market open"),
        (sf.MSG_MARKET_CLOSE, 2, "Market closed"),
    ],
)
def test_header_only_status_packets_synthesize_their_status_code(
    code, expected_status_code, expected_text
):
    """6511/6521 carry no body, so the code has to come from the message code."""
    decoded = sf.decode_packet(header(sf.HEADER_SIZE, code), {})

    assert decoded["status_code"] == expected_status_code
    assert decoded["status"] == expected_text


def test_market_status_prefers_the_static_table_over_the_wire_string():
    """The live feed sends an empty string for most codes; trusting it would
    publish a blank status for a closed market."""
    body = sf._MARKET_STATUS_BODY.pack(2, b"")
    packet = header(sf.HEADER_SIZE + len(body), sf.MSG_MARKET_STATUS) + body

    decoded = sf.decode_packet(packet, {})

    assert decoded["status_code"] == 2
    assert decoded["status"] == "Market closed"


def test_an_unmapped_status_code_falls_back_to_the_wire_string():
    body = sf._MARKET_STATUS_BODY.pack(99, b"WEIRD")
    packet = header(sf.HEADER_SIZE + len(body), sf.MSG_MARKET_STATUS) + body

    assert sf.decode_packet(packet, {})["status"] == "WEIRD"


# --- closing auction session --------------------------------------------------


def test_a_cas_packet_outside_the_auction_window_is_dropped():
    """The exchange broadcasts all-zero CAS packets all day. Delivering them
    would publish a 0.00 reference price over a real one."""
    body = sf._CAS_CHANGE_BODY.pack(11536, 0, 0, 0)
    packet = header(sf.HEADER_SIZE + len(body), sf.MSG_CAS_CHANGE) + body

    assert sf.decode_packet(packet, {NSE_CM: 100}) is None


def test_a_partially_zero_cas_packet_is_still_real():
    body = sf._CAS_CHANGE_BODY.pack(11536, 213500, 0, 0)
    packet = header(sf.HEADER_SIZE + len(body), sf.MSG_CAS_CHANGE) + body

    decoded = sf.decode_packet(packet, {NSE_CM: 100})

    assert decoded["ref_price"] == 2135.00
    assert decoded["imbalance_qty"] == 0


# --- header routing -----------------------------------------------------------


def test_a_runt_packet_is_ignored():
    assert sf.decode_packet(b"\x00\x00", {}) is None


def test_exchange_id_maps_to_the_segment_name_openalgo_already_uses():
    packet = market_picture(exchange_id=9)  # mcx_fo

    assert sf.decode_packet(packet, {})["exchange_segment"] == "mcx_fo"
