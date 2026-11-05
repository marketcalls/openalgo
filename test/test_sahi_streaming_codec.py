"""Sahi market-data stream: protobuf codec and tick normalization.

No network. Frames are built by hand (independently of the codec under test)
and, when the protobuf runtime is available, cross-checked against messages
built from a runtime descriptor of the published schema.
"""

import pytest

# The proxy package registers every adapter on import, so it is loaded first,
# as the app does; importing an adapter package first is a circular import.
import websocket_proxy  # noqa: F401
from broker.sahi.streaming import sahi_proto as pb
from broker.sahi.streaming.sahi_mapping import (
    SahiCapabilityRegistry,
    build_payloads,
)

# ---------------------------------------------------------------------------
# Tiny independent wire helpers for building test frames
# ---------------------------------------------------------------------------


def varint(n: int) -> bytes:
    if n < 0:
        n += 1 << 64
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def vfield(field: int, value: int) -> bytes:
    return varint(field << 3) + varint(value)


def lfield(field: int, payload: bytes) -> bytes:
    return varint((field << 3) | 2) + varint(len(payload)) + payload


def packed(field: int, values) -> bytes:
    return lfield(field, b"".join(varint(v) for v in values))


def server(field: int, body: bytes) -> bytes:
    return lfield(field, body)


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------


def test_encode_subscribe_bytes():
    # ClientMessage{subscribe{mode=QUOTE(2), ids=[1, 300]}}
    # Subscribe body: 08 02 | 12 03 01 ac 02  (300 = 0xac 0x02) -> 7 bytes
    expected = bytes([0x0A, 0x07, 0x08, 0x02, 0x12, 0x03, 0x01, 0xAC, 0x02])
    assert pb.encode_subscribe(pb.MODE_QUOTE, [1, 300]) == expected


def test_encode_unsubscribe_and_mode_change_bytes():
    assert pb.encode_unsubscribe([5]) == bytes([0x12, 0x03, 0x0A, 0x01, 0x05])
    assert pb.encode_mode_change(pb.MODE_DEPTH, [5]) == bytes(
        [0x1A, 0x05, 0x08, 0x03, 0x12, 0x01, 0x05]
    )


def test_encode_large_id():
    big = 2**40 + 7
    assert pb.encode_subscribe(pb.MODE_LTP, [big]) == server(1, vfield(1, 1) + packed(2, [big]))


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------


def test_decode_ack_packed_and_unpacked():
    body = vfield(1, pb.ACK_SUBSCRIBE) + packed(2, [11, 22]) + vfield(2, 33)
    kind, ack = pb.decode_server_message(server(1, body))
    assert kind == pb.KIND_ACK
    assert ack == {"action": pb.ACK_SUBSCRIBE, "instrument_ids": [11, 22, 33]}


def test_decode_ltp_index_without_last_trade_time():
    body = vfield(1, 26000) + vfield(2, pb.SEGMENT_NSE) + vfield(3, 1) + vfield(4, 2456735)
    kind, tick = pb.decode_server_message(server(2, body))
    assert kind == pb.KIND_LTP
    assert tick["instrument_id"] == 26000
    assert tick["exchange_segment"] == pb.SEGMENT_NSE
    assert tick["instrument_type"] == 1
    assert tick["last_trade_price"] == 2456735
    assert tick["last_trade_time"] is None


def test_decode_quote_stock_absent_oi():
    body = (
        vfield(1, 2885)
        + vfield(2, pb.SEGMENT_NSE)
        + vfield(3, 2)
        + vfield(4, 129050)
        + vfield(5, 1761700000123)
        + vfield(6, 987654)
        + vfield(7, 141950)
        + vfield(8, 116150)
    )
    kind, tick = pb.decode_server_message(server(3, body))
    assert kind == pb.KIND_QUOTE
    assert tick["last_trade_time"] == 1761700000123
    assert tick["volume_today"] == 987654
    assert (tick["dpr_upper"], tick["dpr_lower"]) == (141950, 116150)
    assert tick["open_interest"] is None
    assert tick["prev_open_interest"] is None


def test_decode_quote_derivative_oi_zero_present():
    body = vfield(1, 50001) + vfield(2, pb.SEGMENT_NFO) + vfield(3, 4) + vfield(4, 2470000)
    body += vfield(9, 0) + vfield(10, 0)
    _, tick = pb.decode_server_message(server(3, body))
    assert tick["open_interest"] == 0
    assert tick["prev_open_interest"] == 0


def test_decode_depth_two_buys_no_sells():
    lvl1 = vfield(1, 129000) + vfield(2, 50) + vfield(3, 3)
    lvl2 = vfield(1, 128995) + vfield(2, 10) + vfield(3, 1)
    body = vfield(1, 2885) + vfield(4, 129050) + lfield(11, lvl1) + lfield(11, lvl2)
    kind, tick = pb.decode_server_message(server(4, body))
    assert kind == pb.KIND_DEPTH
    assert tick["best_buys"] == [(129000, 50, 3), (128995, 10, 1)]
    assert tick["best_sells"] == []


def test_decode_error():
    body = lfield(1, b"UNKNOWN_INSTRUMENT") + lfield(2, b"id 9 not found")
    kind, err = pb.decode_server_message(server(5, body))
    assert kind == pb.KIND_ERROR
    assert err == {"code": "UNKNOWN_INSTRUMENT", "message": "id 9 not found"}


def test_unknown_fields_are_skipped():
    # Unknown fields of every wire type, inside the tick and at the top level.
    unknown = (
        vfield(99, 12345)  # varint
        + varint((98 << 3) | 1)
        + b"\x01" * 8  # fixed64
        + lfield(97, b"\xff\xfe junk")  # length-delimited
        + varint((96 << 3) | 5)
        + b"\x02" * 4  # fixed32
    )
    body = vfield(1, 7) + unknown + vfield(4, 100)
    frame = unknown + server(2, body) + vfield(50, 1)
    kind, tick = pb.decode_server_message(frame)
    assert kind == pb.KIND_LTP
    assert tick["instrument_id"] == 7
    assert tick["last_trade_price"] == 100


def test_unknown_oneof_and_empty_frame():
    assert pb.decode_server_message(server(9, b"\x08\x01")) == (None, None)
    assert pb.decode_server_message(b"") == (None, None)


def test_negative_int64():
    _, tick = pb.decode_server_message(server(2, vfield(1, 1) + vfield(4, -5)))
    assert tick["last_trade_price"] == -5


@pytest.mark.parametrize(
    "frame",
    [
        b"\x12",  # key with no length
        b"\x12\x05\x08",  # length beyond end
        b"\x12\x02\x08\xff",  # truncated varint inside
        b"\x0b",  # group wire type
    ],
)
def test_malformed_frames_raise(frame):
    with pytest.raises(pb.ProtoDecodeError):
        pb.decode_server_message(frame)


# ---------------------------------------------------------------------------
# Optional cross-check against the protobuf runtime
# ---------------------------------------------------------------------------


def _runtime_classes():
    descriptor_pb2 = pytest.importorskip("google.protobuf.descriptor_pb2")
    from google.protobuf import descriptor_pool, message_factory

    F = descriptor_pb2.FieldDescriptorProto
    fdp = descriptor_pb2.FileDescriptorProto(
        name="sahi_md_test.proto", package="sahitest", syntax="proto3"
    )

    def msg(name, fields, oneof=None):
        m = fdp.message_type.add(name=name)
        if oneof:
            m.oneof_decl.add(name=oneof)
        for num, fname, ftype, label, type_name, extra in fields:
            f = m.field.add(name=fname, number=num, type=ftype, label=label)
            if type_name:
                f.type_name = f".sahitest.{type_name}"
            if extra == "oneof":
                f.oneof_index = 0
            elif extra == "optional":
                f.proto3_optional = True
                f.oneof_index = len(m.oneof_decl)
                m.oneof_decl.add(name=f"_{fname}")
        return m

    OPT, REP = F.LABEL_OPTIONAL, F.LABEL_REPEATED
    I64, MSG = F.TYPE_INT64, F.TYPE_MESSAGE
    E = F.TYPE_INT32  # enums are varints on the wire; int32 is equivalent here
    msg("Subscribe", [(1, "mode", E, OPT, None, None), (2, "ids", I64, REP, None, None)])
    msg("Unsubscribe", [(1, "ids", I64, REP, None, None)])
    msg("ModeChange", [(1, "mode", E, OPT, None, None), (2, "ids", I64, REP, None, None)])
    msg(
        "ClientMessage",
        [
            (1, "subscribe", MSG, OPT, "Subscribe", "oneof"),
            (2, "unsubscribe", MSG, OPT, "Unsubscribe", "oneof"),
            (3, "mode_change", MSG, OPT, "ModeChange", "oneof"),
        ],
        oneof="payload",
    )
    msg(
        "DepthLevel",
        [
            (1, "price", I64, OPT, None, None),
            (2, "qty", I64, OPT, None, None),
            (3, "num_orders", I64, OPT, None, None),
        ],
    )
    msg(
        "DepthTick",
        [
            (1, "instrument_id", I64, OPT, None, None),
            (2, "exchange_segment", E, OPT, None, None),
            (3, "instrument_type", E, OPT, None, None),
            (4, "last_trade_price", I64, OPT, None, None),
            (5, "last_trade_time", I64, OPT, None, "optional"),
            (6, "volume_today", I64, OPT, None, None),
            (7, "dpr_upper", I64, OPT, None, None),
            (8, "dpr_lower", I64, OPT, None, None),
            (9, "prev_open_interest", I64, OPT, None, "optional"),
            (10, "open_interest", I64, OPT, None, "optional"),
            (11, "best_buys", MSG, REP, "DepthLevel", None),
            (12, "best_sells", MSG, REP, "DepthLevel", None),
        ],
    )
    msg("ServerMessage", [(4, "depth_tick", MSG, OPT, "DepthTick", "oneof")], oneof="payload")

    pool = descriptor_pool.DescriptorPool()
    pool.Add(fdp)
    get = message_factory.GetMessageClass
    return {
        n: get(pool.FindMessageTypeByName(f"sahitest.{n}"))
        for n in ("ClientMessage", "ServerMessage")
    }


def test_cross_check_with_protobuf_runtime():
    classes = _runtime_classes()
    cm = classes["ClientMessage"]()
    cm.ParseFromString(pb.encode_subscribe(pb.MODE_DEPTH, [1, 2**35, 999]))
    assert cm.WhichOneof("payload") == "subscribe"
    assert cm.subscribe.mode == 3
    assert list(cm.subscribe.ids) == [1, 2**35, 999]

    cm = classes["ClientMessage"]()
    cm.ParseFromString(pb.encode_mode_change(pb.MODE_LTP, [42]))
    assert cm.WhichOneof("payload") == "mode_change"
    assert (cm.mode_change.mode, list(cm.mode_change.ids)) == (1, [42])

    sm = classes["ServerMessage"]()
    t = sm.depth_tick
    t.instrument_id = 123456
    t.exchange_segment = 3
    t.instrument_type = 5
    t.last_trade_price = 1525
    t.open_interest = 0
    t.volume_today = 10**12
    for p, q, o in [(1520, 75, 2), (1515, 150, 4), (1510, 1, 1)]:
        lv = t.best_buys.add()
        lv.price, lv.qty, lv.num_orders = p, q, o
    kind, tick = pb.decode_server_message(sm.SerializeToString())
    assert kind == pb.KIND_DEPTH
    assert tick["instrument_id"] == 123456
    assert tick["exchange_segment"] == 3
    assert tick["last_trade_price"] == 1525
    assert tick["last_trade_time"] is None
    assert tick["open_interest"] == 0
    assert tick["prev_open_interest"] is None
    assert tick["volume_today"] == 10**12
    assert tick["best_buys"] == [(1520, 75, 2), (1515, 150, 4), (1510, 1, 1)]
    assert tick["best_sells"] == []


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _depth_tick():
    _, tick = pb.decode_server_message(
        server(
            4,
            vfield(1, 2885)
            + vfield(4, 129050)
            + vfield(5, 1761700000123)
            + vfield(6, 4000)
            + vfield(7, 141950)
            + vfield(8, 116150)
            + lfield(11, vfield(1, 129000) + vfield(2, 50) + vfield(3, 3))
            + lfield(11, vfield(1, 128995) + vfield(2, 10) + vfield(3, 1)),
        )
    )
    return tick


QUOTE_KEYS = {
    "symbol",
    "exchange",
    "mode",
    "ltp",
    "ltt",
    "timestamp",
    "volume",
    "last_quantity",
    "average_price",
    "total_buy_quantity",
    "total_sell_quantity",
    "open",
    "high",
    "low",
    "close",
    "oi",
    "open_interest",
    "upper_circuit",
    "lower_circuit",
}


def test_depth_tick_fans_out_to_every_mode():
    out = dict(build_payloads(pb.KIND_DEPTH, _depth_tick(), "RELIANCE", "NSE", {1, 2, 3}, 1))
    assert set(out) == {"NSE_RELIANCE_LTP", "NSE_RELIANCE_QUOTE", "NSE_RELIANCE_DEPTH"}

    ltp = out["NSE_RELIANCE_LTP"]
    assert ltp == {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "mode": "ltp",
        "ltp": 1290.5,
        "ltt": 1761700000123,
        "timestamp": 1,
    }

    quote = out["NSE_RELIANCE_QUOTE"]
    assert set(quote) == QUOTE_KEYS
    assert quote["mode"] == "quote"
    assert quote["ltp"] == 1290.5
    assert quote["volume"] == 4000
    assert quote["upper_circuit"] == 1419.5
    assert quote["lower_circuit"] == 1161.5
    for k in ("open", "high", "low", "close", "last_quantity", "average_price", "oi"):
        assert quote[k] == 0

    depth = out["NSE_RELIANCE_DEPTH"]
    assert set(depth) == QUOTE_KEYS | {"depth"}
    assert depth["mode"] == "full"
    buy, sell = depth["depth"]["buy"], depth["depth"]["sell"]
    assert len(buy) == 5 and len(sell) == 5
    assert buy[0] == {"price": 1290.0, "quantity": 50, "orders": 3}
    assert buy[1] == {"price": 1289.95, "quantity": 10, "orders": 1}
    assert buy[2:] == [{"price": 0.0, "quantity": 0, "orders": 0}] * 3
    assert sell == [{"price": 0.0, "quantity": 0, "orders": 0}] * 5


def test_depth_truncated_to_five_levels():
    tick = _depth_tick()
    tick["best_sells"] = [(100 + i, i, 1) for i in range(20)]
    ((_, depth),) = build_payloads(pb.KIND_DEPTH, tick, "X", "NSE", {3}, 0)
    assert [lvl["price"] for lvl in depth["depth"]["sell"]] == [1.0, 1.01, 1.02, 1.03, 1.04]


def test_lower_tick_does_not_serve_higher_modes():
    _, tick = pb.decode_server_message(server(3, vfield(1, 1) + vfield(4, 500)))
    out = build_payloads(pb.KIND_QUOTE, tick, "SBIN", "NSE", {1, 2, 3}, 0)
    assert [t for t, _ in out] == ["NSE_SBIN_LTP", "NSE_SBIN_QUOTE"]


def test_index_ltp_without_time_and_derivative_oi():
    _, tick = pb.decode_server_message(server(2, vfield(1, 26000) + vfield(4, 2456735)))
    ((topic, ltp),) = build_payloads(pb.KIND_LTP, tick, "NIFTY", "NSE_INDEX", {1}, 7)
    assert topic == "NSE_INDEX_NIFTY_LTP"
    assert ltp["ltp"] == 24567.35 and ltp["ltt"] == 0 and ltp["exchange"] == "NSE_INDEX"

    _, tick = pb.decode_server_message(server(3, vfield(1, 5) + vfield(4, 1) + vfield(10, 1500)))
    ((_, quote),) = build_payloads(pb.KIND_QUOTE, tick, "NIFTYFUT", "NFO", {2}, 0)
    assert quote["oi"] == 1500 and quote["open_interest"] == 1500


def test_capabilities_depth_five_only():
    assert SahiCapabilityRegistry.get_supported_depth_levels() == [5]
    assert SahiCapabilityRegistry.get_supported_depth_levels("NFO") == [5]
    assert SahiCapabilityRegistry.get_fallback_depth_level("NSE", 20) == 5


# ---------------------------------------------------------------------------
# Adapter multi-mode bookkeeping with fake socket and fake publisher
# ---------------------------------------------------------------------------


class _FakeClient:
    def __init__(self):
        self.sent = []

    def send(self, frame):
        self.sent.append(frame)
        return True

    def is_connected(self):
        return True

    def stop(self):
        pass


@pytest.fixture
def adapter(monkeypatch):
    from broker.sahi.streaming import sahi_adapter as mod

    a = mod.SahiWebSocketAdapter.__new__(mod.SahiWebSocketAdapter)
    import threading

    a.logger = mod.get_logger("sahi_test")
    a.broker_name = "sahi"
    a.ws_client = _FakeClient()
    a.running = True
    a.connected = True
    a.lock = threading.Lock()
    a._subs = {}
    a._keys = {}
    a._server = {}
    a._dirty = set()
    a._batch_timer = None
    a.published = []
    a.publish_market_data = lambda topic, data: a.published.append((topic, data))
    tokens = {("RELIANCE", "NSE"): "2885", ("NIFTY", "NSE_INDEX"): "26000"}
    tokens.update({(f"S{i}", "NSE"): str(100000 + i) for i in range(1200)})
    monkeypatch.setattr(mod, "get_token", lambda s, e: tokens.get((s, e)))
    # Tests flush by hand; the timer must not fire in the middle of one.
    monkeypatch.setattr(mod, "BATCH_DELAY", 3600)
    yield a
    with a.lock:
        a._cancel_batch_timer()
    a._zmq_cleaned_up = True  # nothing to clean: __init__ was bypassed


def flushed(a):
    """Run the batch flush the timer would, and return the frames it sent."""
    before = len(a.ws_client.sent)
    a._flush_pending()
    return a.ws_client.sent[before:]


def test_adapter_multi_mode_upgrade_and_downgrade(adapter):
    sent = adapter.ws_client.sent
    assert adapter.subscribe("RELIANCE", "NSE", 1)["status"] == "success"
    assert sent == []  # nothing goes out before the batch flush
    assert flushed(adapter) == [pb.encode_subscribe(pb.MODE_LTP, [2885])]
    r = adapter.subscribe("RELIANCE", "NSE", 3, depth_level=20)
    assert r["actual_depth"] == 5 and r["is_fallback"] is True
    assert flushed(adapter) == [pb.encode_mode_change(pb.MODE_DEPTH, [2885])]
    n = len(sent)
    adapter.subscribe("RELIANCE", "NSE", 2)  # lower than current: no frame
    assert flushed(adapter) == []
    assert len(sent) == n

    adapter._on_message(
        server(4, vfield(1, 2885) + vfield(4, 129050) + lfield(11, vfield(1, 129000)))
    )
    assert sorted(t for t, _ in adapter.published) == [
        "NSE_RELIANCE_DEPTH",
        "NSE_RELIANCE_LTP",
        "NSE_RELIANCE_QUOTE",
    ]

    adapter.unsubscribe("RELIANCE", "NSE", 3)
    assert flushed(adapter) == [pb.encode_mode_change(pb.MODE_QUOTE, [2885])]
    adapter.unsubscribe("RELIANCE", "NSE", 1)
    assert flushed(adapter) == []  # quote still highest: no frame
    adapter.unsubscribe("RELIANCE", "NSE", 2)
    assert flushed(adapter) == [pb.encode_unsubscribe([2885])]
    assert adapter._subs == {} and adapter._server == {}
    assert adapter.unsubscribe("RELIANCE", "NSE", 2)["status"] == "error"


def test_adapter_batches_a_burst_into_grouped_frames(adapter):
    for i in range(3):
        adapter.subscribe(f"S{i}", "NSE", 1)
    adapter.subscribe("RELIANCE", "NSE", 3)
    adapter.subscribe("NIFTY", "NSE_INDEX", 2)
    assert adapter.ws_client.sent == []
    assert flushed(adapter) == [
        pb.encode_subscribe(pb.MODE_LTP, [100000, 100001, 100002]),
        pb.encode_subscribe(pb.MODE_QUOTE, [26000]),
        pb.encode_subscribe(pb.MODE_DEPTH, [2885]),
    ]
    # One window mixing a removal, an upgrade and a new id: unsubscribe first.
    adapter.unsubscribe("S0", "NSE", 1)
    adapter.subscribe("S1", "NSE", 3)
    adapter.subscribe("S2", "NSE", 3)
    adapter.subscribe("S3", "NSE", 1)
    assert flushed(adapter) == [
        pb.encode_unsubscribe([100000]),
        pb.encode_mode_change(pb.MODE_DEPTH, [100001, 100002]),
        pb.encode_subscribe(pb.MODE_LTP, [100003]),
    ]


def test_adapter_change_undone_inside_the_window_sends_nothing(adapter):
    adapter.subscribe("RELIANCE", "NSE", 1)
    adapter.unsubscribe("RELIANCE", "NSE", 1)
    assert flushed(adapter) == []
    assert adapter._server == {}


def test_adapter_splits_large_batches_at_500_ids(adapter):
    for i in range(1000):
        adapter.subscribe(f"S{i}", "NSE", 1)
    frames = flushed(adapter)
    assert frames == [
        pb.encode_subscribe(pb.MODE_LTP, [100000 + i for i in range(500)]),
        pb.encode_subscribe(pb.MODE_LTP, [100000 + i for i in range(500, 1000)]),
    ]
    assert adapter.subscribe("S1000", "NSE", 1)["code"] == "MAX_SYMBOLS_REACHED"
    # unsubscribe_all sends at once, without waiting for the window.
    assert adapter.unsubscribe_all()["status"] == "success"
    assert adapter.ws_client.sent[-2:] == [
        pb.encode_unsubscribe([100000 + i for i in range(500)]),
        pb.encode_unsubscribe([100000 + i for i in range(500, 1000)]),
    ]
    assert adapter._server == {} and adapter._dirty == set()


def test_adapter_timer_flushes_once_per_window(adapter, monkeypatch):
    from broker.sahi.streaming import sahi_adapter as mod

    monkeypatch.setattr(mod, "BATCH_DELAY", 0.05)
    adapter.subscribe("RELIANCE", "NSE", 1)
    timer = adapter._batch_timer
    adapter.subscribe("NIFTY", "NSE_INDEX", 1)
    assert adapter._batch_timer is timer  # a later change joins the window
    timer.join(2)
    assert adapter.ws_client.sent == [pb.encode_subscribe(pb.MODE_LTP, [2885, 26000])]
    assert adapter._batch_timer is None


def test_adapter_resubscribe_on_open_groups_by_mode(adapter):
    adapter.subscribe("RELIANCE", "NSE", 3)
    adapter.subscribe("NIFTY", "NSE_INDEX", 1)
    client = _FakeClient()
    adapter._on_open(client)
    assert client.sent == [
        pb.encode_subscribe(pb.MODE_LTP, [26000]),
        pb.encode_subscribe(pb.MODE_DEPTH, [2885]),
    ]
    # The reconnect settled the queued changes: the timer has nothing left.
    assert flushed(adapter) == []
    adapter._on_close(4408, "ping timeout")
    assert adapter._server == {}


def test_adapter_rejects_unknown_symbol_and_exchange(adapter):
    assert adapter.subscribe("NOPE", "NSE", 1)["status"] == "error"
    assert adapter.subscribe("GOLD", "MCX", 1)["code"] == "UNSUPPORTED_EXCHANGE"


def test_adapter_ignores_malformed_and_error_frames(adapter):
    adapter._on_message(b"\x12\x05\x08")
    adapter._on_message(server(5, lfield(1, b"E") + lfield(2, b"m")))
    assert adapter.published == []


def test_stop_right_after_connect_closes_the_socket(monkeypatch):
    """A stop landing between the handshake and the read loop closes the
    socket itself instead of leaving it to the garbage collector."""
    from broker.sahi.streaming import sahi_websocket as wsmod

    class _Sock:
        connected = True
        closed = False

        def abort(self):
            pass

        def shutdown(self):
            self.closed = True

    sock = _Sock()
    monkeypatch.setattr(wsmod.websocket, "create_connection", lambda *a, **k: sock)
    client = wsmod.SahiWebSocket("tok", None, on_message=lambda b: None)
    client._stop_event.set()
    assert client._connect_once() == (wsmod.CLOSE_NORMAL, "stopped")
    assert sock.closed
    assert client._ws is None
