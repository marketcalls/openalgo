"""
Hand-rolled protobuf codec for the Sahi market-data stream.

Schema: package sahi.direct.marketdata.v1 (ClientMessage / ServerMessage).
One message per binary WebSocket frame, no length prefix.

Only the wire format is implemented here (varint and length-delimited), which
keeps the adapter free of generated ``_pb2`` code and its protobuf runtime
version coupling. Unknown fields are skipped per wire type, repeated int64
fields are accepted packed and unpacked, and proto3 ``optional`` fields decode
to ``None`` when absent.

Decoded server messages are returned as ``(kind, payload)`` where ``kind`` is
one of ``KIND_ACK``, ``KIND_LTP``, ``KIND_QUOTE``, ``KIND_DEPTH``, ``KIND_ERROR``
or ``None`` (empty / unknown payload) and ``payload`` is a plain dict.
"""

# Enum values (sahi.direct.marketdata.v1)
MODE_INVALID = 0
MODE_LTP = 1
MODE_QUOTE = 2
MODE_DEPTH = 3

SEGMENT_NSE = 1
SEGMENT_BSE = 2
SEGMENT_NFO = 3
SEGMENT_BFO = 4

ACK_SUBSCRIBE = 1
ACK_UNSUBSCRIBE = 2
ACK_MODE_CHANGE = 3

KIND_ACK = "ack"
KIND_LTP = "ltp"
KIND_QUOTE = "quote"
KIND_DEPTH = "depth"
KIND_ERROR = "error"

# Wire types
_WT_VARINT = 0
_WT_I64 = 1
_WT_LEN = 2
_WT_I32 = 5

_U64 = 1 << 64
_I64_SIGN = 1 << 63


class ProtoDecodeError(ValueError):
    """Raised when a frame is not a well-formed protobuf message."""


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def _encode_varint(value: int, out: bytearray) -> None:
    # int64 negatives are encoded as their 64-bit two's complement (10 bytes).
    if value < 0:
        value += _U64
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)


def _encode_key(field: int, wire_type: int, out: bytearray) -> None:
    _encode_varint((field << 3) | wire_type, out)


def _encode_len_field(field: int, payload: bytes | bytearray, out: bytearray) -> None:
    _encode_key(field, _WT_LEN, out)
    _encode_varint(len(payload), out)
    out += payload


def _encode_packed_int64(field: int, values, out: bytearray) -> None:
    if not values:
        return  # proto3: an empty repeated field is omitted
    packed = bytearray()
    for v in values:
        _encode_varint(int(v), packed)
    _encode_len_field(field, packed, out)


def _encode_mode_and_ids(mode: int, instrument_ids) -> bytearray:
    body = bytearray()
    if mode:  # proto3 scalar default (0) is omitted
        _encode_key(1, _WT_VARINT, body)
        _encode_varint(int(mode), body)
    _encode_packed_int64(2, instrument_ids, body)
    return body


def encode_subscribe(mode: int, instrument_ids) -> bytes:
    """ClientMessage{subscribe = Subscribe{mode, instrument_ids}}"""
    out = bytearray()
    _encode_len_field(1, _encode_mode_and_ids(mode, instrument_ids), out)
    return bytes(out)


def encode_unsubscribe(instrument_ids) -> bytes:
    """ClientMessage{unsubscribe = Unsubscribe{instrument_ids}}"""
    body = bytearray()
    _encode_packed_int64(1, instrument_ids, body)
    out = bytearray()
    _encode_len_field(2, body, out)
    return bytes(out)


def encode_mode_change(mode: int, instrument_ids) -> bytes:
    """ClientMessage{mode_change = ModeChange{mode, instrument_ids}}"""
    out = bytearray()
    _encode_len_field(3, _encode_mode_and_ids(mode, instrument_ids), out)
    return bytes(out)


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def _read_varint(buf, pos: int, end: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= end:
            raise ProtoDecodeError("truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if b < 0x80:
            return result, pos
        shift += 7
        if shift >= 70:
            raise ProtoDecodeError("varint too long")


def _to_int64(value: int) -> int:
    value &= _U64 - 1
    return value - _U64 if value >= _I64_SIGN else value


def _skip(buf, pos: int, end: int, wire_type: int) -> int:
    if wire_type == _WT_VARINT:
        _, pos = _read_varint(buf, pos, end)
    elif wire_type == _WT_I64:
        pos += 8
    elif wire_type == _WT_LEN:
        length, pos = _read_varint(buf, pos, end)
        pos += length
    elif wire_type == _WT_I32:
        pos += 4
    else:
        # Groups (3/4) are not used by proto3; anything else is corrupt.
        raise ProtoDecodeError(f"unsupported wire type {wire_type}")
    if pos > end:
        raise ProtoDecodeError("truncated field")
    return pos


def _read_len(buf, pos: int, end: int) -> tuple[int, int]:
    """Return (start, stop) of a length-delimited payload; pos is after the key."""
    length, pos = _read_varint(buf, pos, end)
    stop = pos + length
    if stop > end:
        raise ProtoDecodeError("truncated length-delimited field")
    return pos, stop


def _read_repeated_int64(buf, pos: int, end: int, wire_type: int, out: list) -> int:
    if wire_type == _WT_LEN:  # packed
        start, stop = _read_len(buf, pos, end)
        while start < stop:
            v, start = _read_varint(buf, start, stop)
            out.append(_to_int64(v))
        return stop
    if wire_type == _WT_VARINT:  # unpacked
        v, pos = _read_varint(buf, pos, end)
        out.append(_to_int64(v))
        return pos
    return _skip(buf, pos, end, wire_type)


def _decode_depth_level(buf, pos: int, end: int) -> tuple[int, int, int]:
    price = qty = orders = 0
    while pos < end:
        key, pos = _read_varint(buf, pos, end)
        field, wt = key >> 3, key & 7
        if wt == _WT_VARINT and field in (1, 2, 3):
            v, pos = _read_varint(buf, pos, end)
            v = _to_int64(v)
            if field == 1:
                price = v
            elif field == 2:
                qty = v
            else:
                orders = v
        else:
            pos = _skip(buf, pos, end, wt)
    return price, qty, orders


def _decode_tick(buf, pos: int, end: int) -> dict:
    """Decode LtpTick / QuoteTick / DepthTick (they share field numbers 1-10)."""
    tick = {
        "instrument_id": 0,
        "exchange_segment": 0,
        "instrument_type": 0,
        "last_trade_price": 0,
        "last_trade_time": None,
        "volume_today": 0,
        "dpr_upper": 0,
        "dpr_lower": 0,
        "prev_open_interest": None,
        "open_interest": None,
        "best_buys": [],
        "best_sells": [],
    }
    while pos < end:
        key, pos = _read_varint(buf, pos, end)
        field, wt = key >> 3, key & 7
        if wt == _WT_VARINT and 1 <= field <= 10:
            v, pos = _read_varint(buf, pos, end)
            name = _TICK_FIELDS[field]
            tick[name] = v if field in (2, 3) else _to_int64(v)
        elif wt == _WT_LEN and field in (11, 12):
            start, pos = _read_len(buf, pos, end)
            level = _decode_depth_level(buf, start, pos)
            (tick["best_buys"] if field == 11 else tick["best_sells"]).append(level)
        else:
            pos = _skip(buf, pos, end, wt)
    return tick


_TICK_FIELDS = {
    1: "instrument_id",
    2: "exchange_segment",
    3: "instrument_type",
    4: "last_trade_price",
    5: "last_trade_time",
    6: "volume_today",
    7: "dpr_upper",
    8: "dpr_lower",
    9: "prev_open_interest",
    10: "open_interest",
}


def _decode_ack(buf, pos: int, end: int) -> dict:
    ack = {"action": 0, "instrument_ids": []}
    while pos < end:
        key, pos = _read_varint(buf, pos, end)
        field, wt = key >> 3, key & 7
        if field == 1 and wt == _WT_VARINT:
            ack["action"], pos = _read_varint(buf, pos, end)
        elif field == 2:
            pos = _read_repeated_int64(buf, pos, end, wt, ack["instrument_ids"])
        else:
            pos = _skip(buf, pos, end, wt)
    return ack


def _decode_error(buf, pos: int, end: int) -> dict:
    err = {"code": "", "message": ""}
    while pos < end:
        key, pos = _read_varint(buf, pos, end)
        field, wt = key >> 3, key & 7
        if field in (1, 2) and wt == _WT_LEN:
            start, pos = _read_len(buf, pos, end)
            text = bytes(buf[start:pos]).decode("utf-8", errors="replace")
            err["code" if field == 1 else "message"] = text
        else:
            pos = _skip(buf, pos, end, wt)
    return err


_PAYLOAD_DECODERS = {
    1: (KIND_ACK, _decode_ack),
    2: (KIND_LTP, _decode_tick),
    3: (KIND_QUOTE, _decode_tick),
    4: (KIND_DEPTH, _decode_tick),
    5: (KIND_ERROR, _decode_error),
}


def decode_server_message(data: bytes) -> tuple[str | None, dict | None]:
    """Decode one ServerMessage frame into (kind, payload).

    Returns (None, None) for a message whose oneof is unset or unknown.
    Raises ProtoDecodeError on a malformed frame.
    """
    buf = memoryview(data)
    end = len(buf)
    pos = 0
    kind = None
    payload = None
    try:
        while pos < end:
            key, pos = _read_varint(buf, pos, end)
            field, wt = key >> 3, key & 7
            entry = _PAYLOAD_DECODERS.get(field)
            if entry is not None and wt == _WT_LEN:
                start, pos = _read_len(buf, pos, end)
                # oneof: the last payload field on the wire wins
                kind, decoder = entry
                payload = decoder(buf, start, pos)
            else:
                pos = _skip(buf, pos, end, wt)
    except IndexError as e:  # defensive; bounds are checked above
        raise ProtoDecodeError("truncated frame") from e
    return kind, payload
