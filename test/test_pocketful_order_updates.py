"""Pocketful order-update adapter: connect, subscribe, decode, map, publish, stop.

Fixtures are the example payloads of Pocketful's "Order Updates" and "Trade
Updates" pages (offline copy of 2026-11-17). The order page's example ends
with a trailing comma after "validity", which is not valid JSON; that comma is
the only change. Frames are built the way the official SDKs read them: one
mode byte (50 order update, 51 trade update), four header bytes, then JSON.

No network: the socket is a fake WebSocketApp, the symbol lookup and the
stored token are patched, and events are caught at the bus.
"""

import json
import logging
import threading
import time
from types import SimpleNamespace

import pytest

# websocket_proxy must load before a broker streaming package (the two import
# each other; app.py loads websocket_proxy first).
import websocket_proxy  # noqa: F401
import websocket_proxy.order_adapter as order_adapter
from broker.pocketful.streaming import pocketful_order_adapter as mod

CLIENT_ID = "SB3179"
ACCESS_TOKEN = "Au-C4o8pSEKRETtoken_part.YoJRluHBJophmZuYTN"
STORED_TOKEN = f"{CLIENT_ID}:::{ACCESS_TOKEN}"

# order-updates.md "Order Updates Response", trailing comma removed.
ORDER_UPDATE_DOC = {
    "error": {"code": 0, "message": ""},
    "result": [
        {
            "average_price": 0,
            "average_trade_price": 0,
            "client_id": "SB3179",
            "deposit": 0,
            "device": "",
            "disclosed_quantity": 0,
            "exchange": "NSE",
            "exchange_order_id": "1200000008791186",
            "exchange_time": 1641191673,
            "execution_type": "REGULAR",
            "filled_quantity": 0,
            "instrument_token": 10666,
            "last_activity_reference": 1325678673994464800,
            "leg_order_indicator": "",
            "login_id": "SB3179",
            "lot_size": 0,
            "lotsize": 1,
            "market_protection_percentage": 0,
            "mode": "MODIFY",
            "nest_request_id": "",
            "nnfid": 111111111111100,
            "oms_order_id": "20220103-1157",
            "order_entry_time": 1641191331,
            "order_side": "BUY",
            "order_status": "MODCONFIRMED",
            "order_type": "LIMIT",
            "price": 36.95,
            "pro_cli": "CLIENT",
            "product": "MIS",
            "quantity": 1,
            "rejection_code": "NONE",
            "rejection_reason": "NONE",
            "remaining_quantity": 1,
            "series": "",
            "spread_token": "",
            "trade_price": 0,
            "trading_symbol": "PNB-EQ",
            "transaction_type": "LIMIT",
            "trigger_price": 0,
            "user_order_id": "10002",
            "validity": "DAY",
        }
    ],
}

# trade-updates.md "Trade Updates Response", verbatim.
TRADE_UPDATE_DOC = {
    "error": {"code": 0, "message": ""},
    "result": [
        {
            "client_id": "SB3179",
            "exchange": "NSE",
            "exchange_order_id": "1200000014631276",
            "exchange_time": 1641201487,
            "filled_quantity": 1,
            "instrument_token": 10666,
            "login_id": "SB3179",
            "oms_order_id": "20220103-1891",
            "order_side": "BUY",
            "pro_cli": "CLIENT",
            "product": "CNC",
            "trade_id": "53768151",
            "trade_price": 38,
            "trading_symbol": "PNB-EQ",
            "transaction_type": None,
            "user_order_id": "10002",
            "v_login_id": None,
        }
    ],
}

ASCII_HEADER = b"\x00\x00\x04\x4c"  # every byte below 0x80: the SDK's decode works
HIGH_HEADER = b"\x00\x00\x03\xe8"  # 0xE8 is not valid UTF-8 here: the SDK's decode fails


def frame(mode, payload, header=ASCII_HEADER):
    return bytes([mode]) + header + json.dumps(payload).encode("utf-8")


def order(**changes):
    record = dict(ORDER_UPDATE_DOC["result"][0])
    record.update(changes)
    return record


def order_frame(*records, header=ASCII_HEADER):
    return frame(
        mod.ORDER_UPDATE_MODE,
        {"error": {"code": 0, "message": ""}, "result": list(records)},
        header,
    )


class FakeBus:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


@pytest.fixture
def bus(monkeypatch):
    fake = FakeBus()
    # The base class publishes through the module-global bus of order_adapter.
    monkeypatch.setattr(order_adapter, "bus", fake)
    return fake


@pytest.fixture
def symbols(monkeypatch):
    """Master contract with one row: token 10666 on NSE is PNB (brsymbol PNB-EQ)."""
    import database.token_db as token_db

    calls = []

    def get_symbol(token, exchange):
        calls.append((token, exchange))
        return "PNB" if (token, exchange) == ("10666", "NSE") else None

    monkeypatch.setattr(token_db, "get_symbol", get_symbol)
    monkeypatch.setattr(token_db, "get_oa_symbol", lambda brsymbol, exchange: None)
    return calls


def adapter():
    return mod.PocketfulOrderUpdateAdapter(
        user_id="admin", client_id=CLIENT_ID, access_token=ACCESS_TOKEN
    )


class RecordingSocket:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)


# --- connection, as the SDKs make it -----------------------------------------


def test_the_feed_url_is_the_sdk_path_with_both_parts_of_the_stored_token():
    a = adapter()

    assert a.get_ws_url() == (
        f"wss://algo.pocketful.in/ws/v1/feeds?login_id={CLIENT_ID}&access_token={ACCESS_TOKEN}"
    )
    assert a.get_headers() is None


def test_the_open_socket_subscribes_to_the_updates_channel_as_the_sdk_does():
    ws = RecordingSocket()

    adapter().on_open_extra(ws)

    # wsclient.send_message("OrderUpdateMessage", [client_id, "web"]),
    # serialised by json.dumps exactly as the SDK serialises it.
    assert ws.sent == ['{"a": "subscribe", "v": ["SB3179", "web"], "m": "updates"}']


def test_the_heartbeat_is_the_sdk_heartbeat_every_eight_seconds():
    a = adapter()
    ws = RecordingSocket()

    a.send_heartbeat(ws)

    assert a.heartbeat_interval() == 8
    assert ws.sent == ['{"a": "h", "v": [], "m": ""}']


# --- mapping -------------------------------------------------------------------


def test_the_documented_order_update_becomes_one_normalized_event(bus, symbols):
    adapter()._handle_message(frame(mod.ORDER_UPDATE_MODE, ORDER_UPDATE_DOC))

    assert len(bus.events) == 1
    event = bus.events[0]
    assert event.topic == "order.update"
    assert (event.mode, event.broker) == ("live", "pocketful")
    assert event.request_data == {"user_id": "admin"}
    assert {
        "orderid": event.orderid,
        "symbol": event.symbol,
        "exchange": event.exchange,
        "action": event.action,
        "quantity": event.quantity,
        "price": event.price,
        "trigger_price": event.trigger_price,
        "pricetype": event.pricetype,
        "product": event.product,
        "order_status": event.order_status,
        "filled_quantity": event.filled_quantity,
        "pending_quantity": event.pending_quantity,
        "average_price": event.average_price,
        "rejection_reason": event.rejection_reason,
    } == {
        "orderid": "20220103-1157",
        "symbol": "PNB",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "price": 36.95,
        "trigger_price": 0.0,
        "pricetype": "LIMIT",
        "product": "MIS",
        "order_status": "open",
        "filled_quantity": 0,
        "pending_quantity": 1,
        "average_price": 0.0,
        "rejection_reason": "",
    }
    # The token lookup keys on the master contract's text token, not the int.
    assert symbols[0] == ("10666", "NSE")


def test_every_order_in_the_result_list_is_published(bus, symbols):
    adapter()._handle_message(
        order_frame(
            order(
                oms_order_id="A-1", order_status="COMPLETE", filled_quantity=1, remaining_quantity=0
            ),
            order(oms_order_id="A-2", order_status="REJECTED", rejection_reason="RMS: margin"),
        )
    )

    assert [(e.orderid, e.order_status) for e in bus.events] == [
        ("A-1", "complete"),
        ("A-2", "rejected"),
    ]


def test_a_trade_update_publishes_nothing(bus, symbols):
    adapter()._handle_message(frame(mod.TRADE_UPDATE_MODE, TRADE_UPDATE_DOC))

    assert bus.events == []


@pytest.mark.parametrize(
    "raw",
    [
        bytes([1]) + b"\x00" * 101,  # detailed market data
        bytes([2]) + b"\x00" * 41,  # compact market data
        bytes([4]) + b"\x00" * 165,  # snapquote
        b"",
        '{"a": "h", "v": [], "m": ""}',
        frame(mod.ORDER_UPDATE_MODE, {"error": {"code": 0, "message": ""}, "result": []}),
    ],
)
def test_frames_that_carry_no_order_publish_nothing(bus, symbols, raw, caplog):
    """Market data on the same socket is ignored quietly, not logged as a failure."""
    caplog.set_level(logging.DEBUG)

    adapter()._handle_message(raw)

    assert bus.events == []
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_an_error_envelope_is_logged_and_its_orders_still_published(bus, symbols, caplog):
    caplog.set_level(logging.DEBUG)
    payload = {"error": {"code": 1, "message": "partial"}, "result": [order()]}

    adapter()._handle_message(frame(mod.ORDER_UPDATE_MODE, payload))

    assert [e.orderid for e in bus.events] == ["20220103-1157"]
    assert any(
        r.levelno == logging.WARNING and "reported error 1: partial" in r.getMessage()
        for r in caplog.records
    )


def test_an_unreadable_order_frame_is_logged_and_dropped(bus, symbols, caplog):
    caplog.set_level(logging.DEBUG)

    adapter()._handle_message(bytes([mod.ORDER_UPDATE_MODE]) + ASCII_HEADER + b"{not json")

    assert bus.events == []
    assert any(
        r.levelno == logging.ERROR and "Could not read a Pocketful order update" in r.getMessage()
        for r in caplog.records
    )


def test_the_header_bytes_are_skipped_without_being_decoded(bus, symbols):
    """The SDK decodes the whole frame as UTF-8 and then drops five characters.

    With a header byte of 0x80 or more that decode raises; slicing the bytes
    first reads the JSON either way, and is identical for an ASCII header.
    """
    raw = order_frame(order(), header=HIGH_HEADER)
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")

    adapter()._handle_message(raw)

    assert [e.orderid for e in bus.events] == ["20220103-1157"]

    ascii_raw = order_frame(order())
    assert mod.decode_frame(ascii_raw)[1] == json.loads(ascii_raw.decode("utf-8")[5:])


def test_a_text_frame_is_read_as_its_bytes_like_the_javascript_sdk(bus, symbols):
    text = order_frame(order()).decode("utf-8")

    adapter()._handle_message(text)

    assert [e.orderid for e in bus.events] == ["20220103-1157"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("COMPLETE", "complete"),
        ("REJECTED", "rejected"),
        ("CANCELLED", "cancelled"),
        ("PENDING", "open"),
        ("CONFIRMED", "open"),
        ("MODCONFIRMED", "open"),
        ("MODIFY_CONFIRMED", "open"),
        ("AMO_REQ_RECEIVED", "open"),
        ("AMO_MODIFY_CONFIRMED", "open"),
        ("AMO_CANCEL_CONFIRMED", "cancelled"),
        ("CANCEL_CONFIRMED", "cancelled"),
        ("TRIGGER_PENDING", "trigger pending"),
        ("TRIGGER PENDING", "trigger pending"),
        ("OPEN", "open"),
        ("complete", "complete"),
        # Unknown states pass through lowercased rather than into a bucket.
        ("PARTIALLY_FILLED", "partially_filled"),
        ("", "open"),
        (None, "open"),
    ],
)
def test_order_status_vocabulary(raw, expected):
    assert mod.map_order_status(raw) == expected


def test_a_rejection_reason_is_reported_only_for_a_rejected_order(symbols):
    a = adapter()

    rejected = a.normalize(order(order_status="REJECTED", rejection_reason="RMS: margin shortfall"))
    live = a.normalize(order(order_status="CONFIRMED", rejection_reason="RMS: stale text"))
    rejected_without_text = a.normalize(order(order_status="REJECTED", rejection_reason="NONE"))

    assert rejected["rejection_reason"] == "RMS: margin shortfall"
    assert live["rejection_reason"] == ""
    assert rejected_without_text["rejection_reason"] == ""


@pytest.mark.parametrize(
    ("order_type", "pricetype"),
    [("LIMIT", "LIMIT"), ("SL", "SL"), ("SLM", "SL-M"), ("MARKET", "MARKET"), ("SL-M", "SL-M")],
)
def test_order_types_map_to_openalgo_price_types(symbols, order_type, pricetype):
    assert adapter().normalize(order(order_type=order_type))["pricetype"] == pricetype


@pytest.mark.parametrize(
    ("product", "expected"),
    [
        ("CNC", "CNC"),
        ("MIS", "MIS"),
        ("NRML", "NRML"),
        ("INTRADAY", "MIS"),
        ("MARGIN", "NRML"),
        ("CO", "CO"),
    ],
)
def test_products_map_to_openalgo_products(symbols, product, expected):
    assert adapter().normalize(order(product=product))["product"] == expected


def test_quantities_and_average_price_fall_back_when_a_field_is_missing(symbols):
    record = order(quantity=10, filled_quantity=4, average_price=0, average_trade_price=37.5)
    del record["remaining_quantity"]

    fields = adapter().normalize(record)

    assert fields["pending_quantity"] == 6
    assert fields["average_price"] == 37.5


def test_a_record_without_an_order_id_is_not_an_order(symbols):
    assert adapter().normalize(order(oms_order_id="")) is None
    assert adapter().normalize("not a record") is None


# --- the factory and the registry ----------------------------------------------


def test_the_factory_takes_both_parts_from_the_stored_token(monkeypatch):
    reads = []

    def get_auth_token(name, bypass_cache=False):
        reads.append((name, bypass_cache))
        return STORED_TOKEN

    monkeypatch.setattr(mod, "get_auth_token", get_auth_token)

    a = mod.create_pocketful_order_adapter("admin")

    assert reads == [("admin", True)]
    assert (a.user_id, a.client_id, a.access_token) == ("admin", CLIENT_ID, ACCESS_TOKEN)


def test_the_factory_starts_nothing_without_a_session_or_a_client_id(monkeypatch):
    import database.auth_db as auth_db

    monkeypatch.setattr(mod, "get_auth_token", lambda name, bypass_cache=False: None)
    assert mod.create_pocketful_order_adapter("admin") is None

    # A bare access token, and no Pocketful row to take the client id from.
    class Query:
        def filter_by(self, **_kwargs):
            return SimpleNamespace(first=lambda: None)

    monkeypatch.setattr(auth_db, "Auth", SimpleNamespace(query=Query()))
    monkeypatch.setattr(mod, "get_auth_token", lambda name, bypass_cache=False: ACCESS_TOKEN)
    assert mod.create_pocketful_order_adapter("admin") is None


def test_the_order_update_service_builds_the_pocketful_adapter(monkeypatch):
    import services.order_update_service as service

    monkeypatch.setattr(mod, "get_auth_token", lambda name, bypass_cache=False: STORED_TOKEN)

    assert service._BROKER_FACTORIES["pocketful"] == (
        "broker.pocketful.streaming.pocketful_order_adapter",
        "create_pocketful_order_adapter",
    )
    built = service._build_adapter("admin", "Pocketful")
    assert isinstance(built, mod.PocketfulOrderUpdateAdapter)
    assert built.client_id == CLIENT_ID


# --- the whole loop, on a fake socket --------------------------------------------


class FakeWebSocketApp:
    instances = []
    frames = []

    def __init__(self, url, **kwargs):
        self.url = url
        self.kwargs = kwargs
        self.sent = []
        self.closed = threading.Event()
        self.delivered = threading.Event()
        FakeWebSocketApp.instances.append(self)

    def run_forever(self, **_kwargs):
        self.kwargs["on_open"](self)
        for raw in FakeWebSocketApp.frames:
            self.kwargs["on_message"](self, raw)
        self.delivered.set()
        self.closed.wait(10)
        self.kwargs["on_close"](self, 1000, "closed")

    def send(self, payload):
        self.sent.append(payload)

    def close(self):
        self.closed.set()


def test_connect_subscribes_publishes_and_disconnect_stops_without_logging_the_token(
    monkeypatch, bus, symbols, caplog
):
    caplog.set_level(logging.DEBUG)
    FakeWebSocketApp.instances = []
    FakeWebSocketApp.frames = [
        frame(1, {}) + b"\x00" * 90,  # market data on the same socket
        frame(mod.TRADE_UPDATE_MODE, TRADE_UPDATE_DOC),
        frame(mod.ORDER_UPDATE_MODE, ORDER_UPDATE_DOC),
    ]
    monkeypatch.setattr(order_adapter.websocket, "WebSocketApp", FakeWebSocketApp)
    a = adapter()

    a.connect()
    deadline = time.monotonic() + 10
    while not FakeWebSocketApp.instances and time.monotonic() < deadline:
        time.sleep(0.01)
    ws = FakeWebSocketApp.instances[0]
    assert ws.delivered.wait(10)

    assert ws.url == a.get_ws_url()
    assert ws.sent[0] == '{"a": "subscribe", "v": ["SB3179", "web"], "m": "updates"}'
    assert [(e.orderid, e.symbol, e.order_status) for e in bus.events] == [
        ("20220103-1157", "PNB", "open")
    ]
    assert a.connected is True

    a.disconnect()
    a._thread.join(5)
    assert not a._thread.is_alive()
    assert ws.closed.is_set()
    assert a.connected is False
    if a._heartbeat_thread is not None:
        a._heartbeat_thread.join(5)
        assert not a._heartbeat_thread.is_alive()

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "Subscribed to Pocketful order updates" in logged
    assert ACCESS_TOKEN not in logged
    assert "SEKRET" not in logged
    # The handlers' SensitiveDataFilter rewrites a record in place, so a logged
    # URL reaches this list as "access_token=[REDACTED]". The adapter must not
    # log the URL at all, redacted or not.
    assert "access_token" not in logged
    assert "ws/v1/feeds" not in logged
