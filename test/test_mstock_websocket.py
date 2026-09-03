"""mStock WebSocket wire protocol: batching, frame parsing, socket hygiene.

Three defect classes are pinned here, each of which shipped and each of which
is invisible to a reading of the source:

Subscribes were sent one frame per symbol. mStock's `tokenList` accepts many
tokens per `exchangeType` and several exchange groups per message -- the
subscribe example in the Market Data WebSocket docs batches two tokens -- so a
100-symbol watchlist cost 100 broker frames plus a 200ms settle pause per mode
upgrade. Coalescing coexists with per-token bookkeeping: the frame is batched,
the `correlation_id` records are not, or unsubscribe and reconnect break.

Header-prefixed LTP and Quote frames were discarded. The parser treated
"shorter than 383 bytes" as "a bare packet", but a header-prefixed LTP frame is
4 + 51 = 55 bytes and a Quote frame 4 + 123 = 127, both under that threshold.
Two call sites gated on the same size set, so they rejected such frames before
the parser ever saw them -- a fix confined to the parser would not have worked.

`fetch_quote` leaked its socket. It closed only after the success and no-quote
returns, so a send failing mid-call (connection reset, broken pipe, timeout)
jumped to the exception handler with the descriptor still open. Measured at 100
calls: 100 sockets held, growing 1:1. It backs the depth API and production is
a single Gunicorn worker that never restarts, so a broker-side disconnect
leaked one descriptor per request until "too many open files" took down every
socket in the worker.

The first test in each group asserts the defect itself -- a leak count, a
dropped frame, a frame count -- so this file cannot pass vacuously if the fix
is refactored away.
"""

import json
import struct

import pytest
import websocket as ws_module

from broker.mstock.api.mstockwebsocket import MstockWebSocket


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def ltp_packet(token="22", ltp_paise=12345):
    """A bare 51-byte LTP packet (mode 1)."""
    p = bytearray(51)
    p[0] = 1
    p[1] = 1
    p[2 : 2 + len(token)] = token.encode()
    p[43:51] = struct.pack("<Q", ltp_paise)
    return bytes(p)


def snap_packet(token="22", ltp_paise=12345):
    """A bare 379-byte snap-quote packet (mode 3)."""
    p = bytearray(379)
    p[0] = 3
    p[1] = 1
    p[2 : 2 + len(token)] = token.encode()
    p[43:51] = struct.pack("<Q", ltp_paise)
    return bytes(p)


def framed(packets, packet_size):
    """Prefix packets with the documented 2-byte count + 2-byte size header."""
    return struct.pack("<H", len(packets)) + struct.pack("<H", packet_size) + b"".join(packets)


class FakeWs:
    """Captures frames instead of sending them."""

    def __init__(self):
        self.sent = []
        self.closed = False

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def close(self):
        self.closed = True


@pytest.fixture
def client():
    ws_client = MstockWebSocket(auth_token="test-token")
    ws_client.ws = FakeWs()
    ws_client._connected = True
    return ws_client


def subs(*specs):
    """Build subscribe_batch entries from (token, exchange_type) pairs."""
    return [
        {"correlation_id": f"mstock_{token}_3", "token": token, "exchange_type": exchange_type}
        for token, exchange_type in specs
    ]


# --------------------------------------------------------------------------
# subscribe coalescing
# --------------------------------------------------------------------------
def test_many_tokens_collapse_into_one_frame(client):
    """THE DEFECT: this was one frame per symbol."""
    assert client.subscribe_batch(subs(("22", 1), ("1333", 1), ("3045", 1)), mode=3) is True

    assert len(client.ws.sent) == 1, "three subscribes must cost one broker frame"
    frame = client.ws.sent[0]
    assert frame["action"] == 1
    assert frame["params"]["mode"] == 3
    assert frame["params"]["tokenList"] == [{"exchangeType": 1, "tokens": ["22", "1333", "3045"]}]


def test_multiple_exchange_types_group_in_one_frame(client):
    client.subscribe_batch(subs(("22", 1), ("1333", 2), ("500410", 3), ("99", 1)), mode=2)

    assert len(client.ws.sent) == 1
    by_type = {g["exchangeType"]: g["tokens"] for g in client.ws.sent[0]["params"]["tokenList"]}
    assert by_type == {1: ["22", "99"], 2: ["1333"], 3: ["500410"]}


def test_per_token_bookkeeping_survives_batching(client):
    """One frame, but still one tracked subscription per token."""
    client.subscribe_batch(subs(("22", 1), ("1333", 1)), mode=3)

    assert len(client.ws.sent) == 1
    assert set(client.subscriptions) == {"mstock_22_3", "mstock_1333_3"}
    assert client.subscriptions["mstock_22_3"] == {
        "token": "22",
        "exchange_type": 1,
        "mode": 3,
    }


def test_single_subscribe_still_works(client):
    assert client.subscribe_stream("cid_1", "22", 1, 2) is True

    assert client.ws.sent[0]["params"]["tokenList"] == [{"exchangeType": 1, "tokens": ["22"]}]
    assert client.subscriptions["cid_1"]["token"] == "22"


def test_unsubscribe_batches_one_frame_per_mode(client):
    client.subscribe_batch(subs(("22", 1), ("1333", 1)), mode=3)
    client.subscribe_stream("cid_ltp", "3045", 1, 1)
    client.ws.sent.clear()

    assert client.unsubscribe_batch(["mstock_22_3", "mstock_1333_3", "cid_ltp"]) is True

    assert len(client.ws.sent) == 2
    assert all(f["action"] == 0 for f in client.ws.sent)
    by_mode = {f["params"]["mode"]: f["params"]["tokenList"] for f in client.ws.sent}
    assert by_mode[3] == [{"exchangeType": 1, "tokens": ["22", "1333"]}]
    assert by_mode[1] == [{"exchangeType": 1, "tokens": ["3045"]}]
    assert client.subscriptions == {}


def test_unsubscribe_single_leaves_others_subscribed(client):
    client.subscribe_batch(subs(("22", 1), ("1333", 1)), mode=3)
    client.ws.sent.clear()

    assert client.unsubscribe_stream("mstock_22_3") is True
    assert client.ws.sent[0]["params"]["tokenList"] == [{"exchangeType": 1, "tokens": ["22"]}]
    assert set(client.subscriptions) == {"mstock_1333_3"}
    assert client.unsubscribe_stream("never_subscribed") is False


def test_reconnect_resubscribe_groups_by_mode(client):
    client.subscribe_batch(subs(("22", 1), ("1333", 1)), mode=3)
    client.subscribe_batch(subs(("3045", 1), ("500410", 3)), mode=1)
    client.ws.sent.clear()

    client._resubscribe_all()

    assert len(client.ws.sent) == 2, "four tokens must cost two frames, not four"
    by_mode = {f["params"]["mode"]: f["params"]["tokenList"] for f in client.ws.sent}
    assert by_mode[3] == [{"exchangeType": 1, "tokens": ["22", "1333"]}]
    assert {g["exchangeType"] for g in by_mode[1]} == {1, 3}


def test_empty_batch_sends_nothing(client):
    assert client.subscribe_batch([], mode=3) is True
    assert client.unsubscribe_batch([]) is True
    assert client.ws.sent == []


def test_not_connected_sends_nothing_and_records_nothing(client):
    client._connected = False

    assert client.subscribe_batch(subs(("22", 1)), mode=3) is False
    assert client.ws.sent == []
    assert client.subscriptions == {}


# --------------------------------------------------------------------------
# binary frame parsing
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "label,data,expected",
    [
        # THE DEFECT: these two were dropped for being under 383 bytes.
        ("header + 1 LTP (55B)", framed([ltp_packet()], 51), 1),
        ("header + 2 LTP (106B)", framed([ltp_packet("22"), ltp_packet("33")], 51), 2),
        ("bare LTP (51B)", ltp_packet(), 1),
        ("bare snap (379B)", snap_packet(), 1),
        ("header + 1 snap (383B)", framed([snap_packet()], 379), 1),
        ("header + 2 snap (762B)", framed([snap_packet("11"), snap_packet("22")], 379), 2),
        ("garbage (7B)", b"\x00" * 7, 0),
        ("empty", b"", 0),
    ],
)
def test_every_documented_frame_shape_parses(label, data, expected):
    assert len(MstockWebSocket.parse_binary_message(data)) == expected, label


def test_multi_packet_frame_keeps_every_token():
    """A batched frame must not lose everything after the first packet."""
    frame = framed([snap_packet("111", 12345), snap_packet("222", 67890)], 379)

    quotes = MstockWebSocket.parse_binary_message(frame)

    assert [q["token"] for q in quotes] == ["111", "222"]
    assert [q["ltp"] for q in quotes] == [123.45, 678.90]


def test_header_claiming_more_packets_than_fit_is_clamped():
    frame = struct.pack("<H", 99) + struct.pack("<H", 379) + snap_packet()

    assert len(MstockWebSocket.parse_binary_message(frame)) == 1


def test_oi_is_not_scaled_but_prices_are():
    """OI is a contract count; only prices carry the paise divisor."""
    p = bytearray(snap_packet("22", 12345))
    p[131:139] = struct.pack("<Q", 4200)  # open interest
    quote = MstockWebSocket.parse_binary_message(bytes(p))[0]

    assert quote["ltp"] == 123.45
    assert quote["oi"] == 4200


# --------------------------------------------------------------------------
# fetch_quote socket hygiene
# --------------------------------------------------------------------------
class FakeConn:
    """Records whether it was closed; can fail on send or on close."""

    created = []

    def __init__(self, behaviour="good"):
        self.behaviour = behaviour
        self.closed = False
        self.sends = 0
        FakeConn.created.append(self)

    def send(self, payload):
        self.sends += 1
        # The 2nd send is the subscribe, after LOGIN already succeeded.
        if self.behaviour == "send_fails" and self.sends == 2:
            raise ConnectionResetError("connection reset by peer")

    def recv(self):
        # "close_raises" is a *successful* read whose close() then fails: the
        # point of that case is that the raising close() must not replace the
        # quote the caller is about to get, which an empty read could not show.
        return snap_packet() if self.behaviour in ("good", "close_raises") else b""

    def close(self):
        self.closed = True
        if self.behaviour == "close_raises":
            raise OSError("socket already dead")


@pytest.fixture
def quote_client(monkeypatch):
    FakeConn.created = []

    def install(behaviour):
        monkeypatch.setattr(ws_module, "create_connection", lambda *a, **k: FakeConn(behaviour))

    ws_client = MstockWebSocket(auth_token="test-token")
    ws_client.install = install
    return ws_client


@pytest.mark.parametrize("calls", [10, 50])
def test_send_failure_does_not_leak_sockets(quote_client, calls):
    """THE DEFECT: every failed call held its descriptor, growing 1:1."""
    quote_client.install("send_fails")

    for _ in range(calls):
        assert quote_client.fetch_quote("22", 1, mode=3) is None

    assert len(FakeConn.created) == calls
    leaked = [c for c in FakeConn.created if not c.closed]
    assert leaked == [], f"{len(leaked)} of {calls} sockets left open"


def test_success_path_closes_and_returns_quote(quote_client):
    quote_client.install("good")

    quote = quote_client.fetch_quote("22", 1, mode=3)

    assert quote is not None and quote["token"] == "22"
    assert FakeConn.created[0].closed is True


def test_no_quote_path_closes(quote_client):
    quote_client.install("empty")

    assert quote_client.fetch_quote("22", 1, mode=3) is None
    assert FakeConn.created[0].closed is True


def test_close_failure_does_not_mask_the_result(quote_client):
    """A raising close() must not replace what the caller gets.

    The read succeeds and the quote is already the return value when close()
    raises in the finally. Asserting the quote, not None, is what pins this:
    letting that exception escape would turn a good fetch into None (or worse,
    a raise) at the call site.
    """
    quote_client.install("close_raises")

    quote = quote_client.fetch_quote("22", 1, mode=3)

    assert quote is not None, "a failing close() must not swallow the quote"
    assert quote["token"] == "22"
    assert FakeConn.created[0].closed is True


def test_connect_failure_is_handled(quote_client, monkeypatch):
    def boom(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(ws_module, "create_connection", boom)

    assert quote_client.fetch_quote("22", 1, mode=3) is None
