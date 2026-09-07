"""Kotak SFeed binary wire protocol (``native_batch``).

A from-scratch reimplementation of the wire format Kotak's own SDK speaks in
``neo_api_client/websocket/feed/protocol.py``. We do not import their package:
OpenAlgo talks to brokers directly, their client is async-only, and vendoring a
dependency for one broker would drag asyncio into a threaded adapter. What is
replicated here is the *format* - struct layouts, message codes, field order -
not their code structure.

This is a different protocol from the legacy HSM feed in HSWebSocketLib.py, not
a newer version of it. The differences that matter when reading this file:

    | | HSM (HSWebSocketLib.py) | SFeed (here) |
    |---|---|---|
    | Byte order  | big-endian          | little-endian, packed |
    | Framing     | one packet per frame | batched, uint16 length prefix each |
    | Header      | 1-byte message type  | 9 bytes, uint16 code at offset 2 |
    | Codes       | 1 to 10              | 104, 105, 1109, 1117/1119, 6511, ... |
    | Scaling     | per-scrip prec/mul in the tick | per-exchange divider from auth |

That last row is the one that bites. HSM carries the precision and multiplier
for an instrument inside its own tick, so a decoder can scale a packet using
only the packet. SFeed does not: prices are plain integers and the divider
arrives once, in the authentication response, keyed by exchange id. Decoding
therefore needs the dividers map threaded in from the client, and a packet that
arrives before authentication completes cannot be scaled at all.

No sentinel handling here either - SFeed has no equivalent of HSM's 0x80000000
"field not available" marker. An absent value is simply zero.
"""

import struct

# Every price field is an integer that must be divided by the exchange's
# divider. 100 is the value Kotak falls back to for an exchange the auth
# response did not mention.
HEADER_SIZE = 9
DEFAULT_DIVIDER = 100

# Message codes: uint16 little-endian at header offset 2.
# 1117 is the documented auth response; 1119 is what SFeed production actually
# sends. Both are accepted - treating only the documented one as valid means a
# client that authenticates successfully and then times out waiting for an ack
# that already arrived.
MSG_AUTH_RESPONSE_CODES = (1117, 1119)
# Subscribe acknowledgement, carrying the token -> trading symbol map. Only
# sent when the subscribe frame asked for it with "ack_symbol": true.
MSG_SUBSCRIBE_ACK = 1109
MSG_MARKET_OPEN = 6511
MSG_MARKET_CLOSE = 6521
MSG_INDEX = 7207
MSG_MARKET_PICTURE = 7208
# Market status with a real body, from the dedicated exchange subscription.
# 6511/6521 above carry the same meaning but arrive header-only.
MSG_MARKET_STATUS = 105
# Closing auction session reference price and order imbalance. Arrives on an
# existing scrip or depth subscription, not a separate one.
MSG_CAS_CHANGE = 104

# Depth level, transmitted as a u8 in the header. Market-data packets are
# routed by this, not by message_code.
LEVEL_MINI_TOUCH_LINE = 1
LEVEL_TOUCH_LINE = 4
LEVEL_DEPTH = 8
LEVEL_FULL_DEPTH = 16

# Exchange id is a signed byte in the binary header; the control plane uses the
# name. Same segment vocabulary OpenAlgo already uses for Kotak elsewhere.
EXCHANGE_NAME_TO_ID = {
    "none": 0,
    "nse_cm": 1,
    "nse_fo": 2,
    "cde_fo": 3,
    "nse_com": 4,
    "bse_cm": 5,
    "bse_fo": 6,
    "bse_cd": 7,
    "bse_co": 8,
    "mcx_fo": 9,
    "ncd_co": 10,
}
EXCHANGE_ID_TO_NAME = {v: k for k, v in EXCHANGE_NAME_TO_ID.items()}

MARKET_STATUS_TEXT = {
    1: "Market open",
    2: "Market closed",
    3: "Pre-open session ending",
    4: "Pre-open ended, normal market open",
    5: "Auction status changed",
    6: "Closing session started",
    7: "Closing session ended",
    8: "Continuous trading closed, closing auction starting soon",
    9: "Closing auction price band set",
    10: "Closing auction (CAS) started",
    11: "Market orders restricted",
    12: "Closing auction (CAS) ended",
}

# Struct layouts. All little-endian, and "<" also means unaligned, which is
# what gives us the C "#pragma pack(1)" the feed is written with - do not
# switch these to "=" or native order, the padding would silently shift every
# field after the first odd-sized one.
#
# Header: message_length u16, message_code u16, exchange_id i8, level u8,
#         auction_flag u8, seq_no u8, bitmask_length u8
_HEADER = struct.Struct("<HHbBBBB")
_U16 = struct.Struct("<H")

# Index body, 78 bytes at offset 9.
_INDEX_BODY = struct.Struct("<IiiiiiQiiidBi21s")

# Mini touch line body, 45 bytes at offset 9 (54 total).
_MINI_BODY = struct.Struct("<IqIqIiiIBI")

# Market picture fixed body, 135 bytes spanning offsets 9 to 144, followed by
# a variable number of 16-byte depth rows.
_MP_BODY = struct.Struct("<IqqqqqIIIIIqIIIIhiIdiIIIIIBI")
_MP_FIXED_END = 144

_DEPTH_ROW = struct.Struct("<qii")
_DEPTH_ROW_SIZE = 16

_MARKET_STATUS_BODY = struct.Struct("<H5s")
_CAS_CHANGE_BODY = struct.Struct("<IIqq")


def split_batch(frame):
    """Split one binary WebSocket frame into its individual packets.

    A single frame may carry several packets laid end to end, each introduced
    by its own uint16 length prefix. A truncated or garbage tail ends the scan
    rather than raising - a malformed final packet must not cost us the valid
    packets that preceded it in the same frame.
    """
    packets = []
    offset = 0
    total = len(frame)
    while offset + 2 <= total:
        size = _U16.unpack_from(frame, offset)[0]
        if size < HEADER_SIZE or offset + size > total:
            break
        packets.append(frame[offset : offset + size])
        offset += size
    return packets


def _decode_string(raw):
    """Decode a fixed-width, NUL-padded UTF-8 field."""
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()


def decode_packet(packet, dividers):
    """Decode one packet into a dict, or None if it carries nothing usable.

    Args:
        packet: a single packet already sliced out of a batch by split_batch.
        dividers: exchange_id -> price divider, from the auth response. An
            exchange missing from the map falls back to DEFAULT_DIVIDER.

    Returns:
        A dict with a "type" key naming the shape ("scrip", "scrip_lite",
        "index", "market_status", "cas"), using SFeed's own field names.
        Translation to OpenAlgo's quote/depth shape happens in the client, so
        this stays a straight reading of the wire and can be tested as one.
    """
    if len(packet) < HEADER_SIZE:
        return None

    (
        message_length,
        message_code,
        exchange_id,
        level,
        auction_flag,
        _seq_no,
        _bitmask_length,
    ) = _HEADER.unpack_from(packet, 0)

    exchange = EXCHANGE_ID_TO_NAME.get(exchange_id, str(exchange_id))
    divider = dividers.get(exchange_id) or DEFAULT_DIVIDER

    # Route on message_code first, then fall back to the level byte. Market
    # data packets do not have a distinguishing code - they are told apart by
    # level, which is why the order here matters.
    if message_code in (MSG_MARKET_OPEN, MSG_MARKET_CLOSE):
        # Header-only. Synthesize the status code the body would have carried.
        status_code = 1 if message_code == MSG_MARKET_OPEN else 2
        return {
            "type": "market_status",
            "exchange_segment": exchange,
            "status_code": status_code,
            "status": MARKET_STATUS_TEXT[status_code],
        }

    if message_code == MSG_INDEX:
        return _decode_index(packet, exchange, divider)

    if message_code == MSG_MARKET_STATUS:
        return _decode_market_status(packet, exchange)

    if message_code == MSG_CAS_CHANGE:
        return _decode_cas_change(packet, exchange, divider)

    if level == LEVEL_MINI_TOUCH_LINE:
        return _decode_mini(packet, exchange, divider)
    if level in (2, LEVEL_TOUCH_LINE, LEVEL_DEPTH, LEVEL_FULL_DEPTH):
        return _decode_market_picture(
            packet, exchange, divider, int(level), auction_flag, message_length
        )

    return None


def _decode_index(packet, exchange, divider):
    (
        token,
        open_price,
        close_price,
        high_price,
        low_price,
        index_value,
        last_trade_time,
        yearly_high,
        yearly_low,
        net_chg_percent,
        _market_cap,
        precision,
        multiplier,
        name,
    ) = _INDEX_BODY.unpack_from(packet, HEADER_SIZE)

    return {
        "type": "index",
        "exchange_segment": exchange,
        "instrument_token": str(token),
        "name": _decode_string(name),
        "last_traded_price": index_value / divider,
        "open_price": open_price / divider,
        "high_price": high_price / divider,
        "low_price": low_price / divider,
        "close_price": close_price / divider,
        "change": (index_value - close_price) / divider,
        # Percent fields carry two implied decimals of their own and are not
        # scaled by the exchange divider.
        "net_change_percent": net_chg_percent / 100,
        "yearly_high": yearly_high / divider,
        "yearly_low": yearly_low / divider,
        "last_trade_time": last_trade_time,
        "precision": precision,
        "multiplier": multiplier / divider,
    }


def _decode_market_status(packet, exchange):
    """Message code 105, the only market-status packet with a body.

    The status string on the wire is unreliable - the live feed sends an empty
    string for most codes other than 1 - so the text comes from the static
    table and the wire string is used only for a code the table has never
    seen.
    """
    status_code, status_bytes = _MARKET_STATUS_BODY.unpack_from(packet, HEADER_SIZE)

    status_text = MARKET_STATUS_TEXT.get(status_code)
    if status_text is None:
        status_text = _decode_string(status_bytes) or f"Unknown status_code {status_code}"

    return {
        "type": "market_status",
        "exchange_segment": exchange,
        "status_code": status_code,
        "status": status_text,
    }


def _decode_cas_change(packet, exchange, divider):
    """Message code 104, closing auction reference price and imbalance.

    Outside the closing auction window the exchange still broadcasts this
    packet with all three values zero. That carries no information, so it is
    dropped rather than delivered as an empty update. A packet where only some
    of the three are zero is real and is kept.
    """
    stk_exch_token, ref_price, imbalance_qty, imbalance_qty_at_market = (
        _CAS_CHANGE_BODY.unpack_from(packet, HEADER_SIZE)
    )

    if ref_price == 0 and imbalance_qty == 0 and imbalance_qty_at_market == 0:
        return None

    return {
        "type": "cas",
        "exchange_segment": exchange,
        "instrument_token": str(stk_exch_token),
        "ref_price": ref_price / divider,
        "imbalance_qty": imbalance_qty,
        "imbalance_qty_at_market": imbalance_qty_at_market,
    }


def _decode_mini(packet, exchange, divider):
    (
        token,
        last_trade_time,
        last_traded_price,
        last_trade_qty,
        close_price,
        net_chg_percent,
        net_chg,
        market_lot,
        precision,
        multiplier,
    ) = _MINI_BODY.unpack_from(packet, HEADER_SIZE)

    return {
        "type": "scrip_lite",
        "exchange_segment": exchange,
        "instrument_token": str(token),
        "last_traded_price": last_traded_price / divider,
        "last_trade_time": last_trade_time,
        "last_trade_qty": last_trade_qty,
        "close_price": close_price / divider,
        "net_change": net_chg / divider,
        "net_change_percent": net_chg_percent / 100,
        "market_lot": market_lot,
        "precision": precision,
        "multiplier": multiplier,
    }


def _decode_market_picture(packet, exchange, divider, level, auction_flag, message_length):
    (
        token,
        total_buy_qty,
        total_sell_qty,
        volume_traded_today,
        last_trade_time,
        last_update_time,
        open_price,
        close_price,
        high_price,
        low_price,
        last_traded_price,
        last_trade_qty,
        avg_trade_price,
        _indicative_close,
        buy_depth_count,
        sell_depth_count,
        _trading_status,
        net_chg_percent,
        open_interest,
        total_traded_value,
        net_chg,
        upper_circuit,
        lower_circuit,
        yearly_high,
        yearly_low,
        market_lot,
        precision,
        multiplier,
    ) = _MP_BODY.unpack_from(packet, HEADER_SIZE)

    # An instrument that has never updated sends a negative sentinel here -
    # the exchange's blank placeholder, 1900-01-01 IST as a signed Unix time -
    # where last_trade_time uses plain 0 for the same "nothing yet" case.
    # Normalize the two onto one convention so a consumer needs one check.
    if last_update_time < 0:
        last_update_time = 0

    # Touch line always carries exactly one bid and one ask, whatever the
    # depth counts in the body say.
    if level == LEVEL_TOUCH_LINE:
        buy_n, sell_n = 1, 1
    else:
        buy_n, sell_n = buy_depth_count, sell_depth_count

    buy = []
    sell = []
    offset = _MP_FIXED_END
    limit = min(message_length, len(packet))
    for i in range(buy_n + sell_n):
        if offset + _DEPTH_ROW_SIZE > limit:
            break  # packet carried fewer rows than its counts claimed
        qty, price, orders = _DEPTH_ROW.unpack_from(packet, offset)
        row = {"quantity": qty, "price": price / divider, "orders": orders}
        (buy if i < buy_n else sell).append(row)
        offset += _DEPTH_ROW_SIZE

    return {
        "type": "scrip",
        "exchange_segment": exchange,
        "instrument_token": str(token),
        "level": level,
        "last_traded_price": last_traded_price / divider,
        "open_price": open_price / divider,
        "high_price": high_price / divider,
        "low_price": low_price / divider,
        "close_price": close_price / divider,
        "average_trade_price": avg_trade_price / divider,
        "last_trade_time": last_trade_time,
        "last_update_time": last_update_time,
        "last_trade_qty": last_trade_qty,
        "total_buy_quantity": total_buy_qty,
        "total_sell_quantity": total_sell_qty,
        "volume_traded_today": volume_traded_today,
        "open_interest": open_interest,
        "net_change": net_chg / divider,
        "net_change_percent": net_chg_percent / 100,
        "upper_circuit_limit": upper_circuit / divider,
        "lower_circuit_limit": lower_circuit / divider,
        "yearly_high": yearly_high / divider,
        "yearly_low": yearly_low / divider,
        "total_traded_value": total_traded_value / divider,
        "market_lot": market_lot,
        "precision": precision,
        "multiplier": multiplier,
        "auction": auction_flag > 0,
        "buy": buy,
        "sell": sell,
    }
