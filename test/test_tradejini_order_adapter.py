"""Tradejini order-update adapter: binary frame decoding, event normalization
and factory guards.

Frames are built here with the layout of the official streaming SDK
(broker/tradejini/api/nxtradstream.py, binaryspec-doc.md): a 6-byte header
(length, version 1, compression flag) and packets of [2-byte length, 1-byte
type, key/value fields]. The event field names come from
broker-api-docs/tradejini-api-docs/12-websocket-sdks.md "Event Field Reference".
"""

import importlib
import json
import os
import struct
import sys
import zlib
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

importlib.import_module("websocket_proxy")
mod = importlib.import_module("broker.tradejini.streaming.tradejini_order_adapter")
sdk = importlib.import_module("broker.tradejini.api.nxtradstream")


def _event_packet(message: str) -> bytes:
    body = message.encode("utf-8")
    fields = bytes([56]) + struct.pack("<H", len(body)) + bytes([61]) + body
    return struct.pack("<h", 3 + len(fields)) + struct.pack("b", 15) + fields


def _auth_packet(status: int) -> bytes:
    fields = bytes([25, status])
    return struct.pack("<h", 3 + len(fields)) + struct.pack("b", 13) + fields


def _ping_packet() -> bytes:
    fields = bytes([62, 1])
    return struct.pack("<h", 3 + len(fields)) + struct.pack("b", 16) + fields


def _frame(*packets: bytes, compress: bool = True) -> bytes:
    payload = b"".join(packets)
    flag = 100 if compress else 0
    if compress:
        payload = zlib.compress(payload)
    return struct.pack("<i", len(payload)) + struct.pack("b", 1) + struct.pack("b", flag) + payload


ORDER_EVENT = {
    "evntType": "orders",
    "type": "limit",
    "trdSym": "RELIANCE-EQ",
    "exch": "NSE",
    "qty": 10,
    "product": "intraday",
    "price": 2450.5,
    "side": "buy",
    "status": "open",
    "orderId": "210115000000001",
    "orderTime": "09:15:00",
    "actStatus": "",
    "msg": "Order placed",
    "reason": "",
}


def _event(**overrides) -> str:
    event = dict(ORDER_EVENT)
    event.update(overrides)
    return json.dumps(event)


@pytest.fixture
def adapter():
    return mod.TradejiniOrderUpdateAdapter(user_id="trader", api_key="KEY", access_token="tok")


@pytest.fixture(autouse=True)
def symbol_lookup():
    def lookup(broker_symbol, exchange, token=None):
        return {"RELIANCE-EQ": "RELIANCE", "EQT_RELIANCE_EQ_NSE": "RELIANCE"}.get(
            broker_symbol, broker_symbol
        )

    with patch.object(mod, "to_openalgo_symbol", side_effect=lookup) as m:
        yield m


# -- frame decoding ------------------------------------------------------------


def test_decoder_matches_the_vendored_sdk():
    """Our decoder and the SDK must read the same event out of one frame."""
    frame = _frame(_ping_packet(), _event_packet(_event()))
    received = []
    stream = sdk.NxtradStream("example.invalid", stream_cb=lambda _s, d: received.append(d))
    stream._NxtradStream__on_message(None, frame)
    sdk_events = [d["message"] for d in received if d.get("msgType") == sdk.EVENTS]

    events, auth = mod.decode_stream_frame(frame)
    assert events == sdk_events == [_event()]
    assert auth == []


@pytest.mark.parametrize("compress", [True, False])
def test_decoder_reads_every_event_in_a_frame(compress):
    frame = _frame(
        _event_packet(_event(orderId="1")),
        _ping_packet(),
        _event_packet(_event(orderId="2")),
        compress=compress,
    )
    events, _ = mod.decode_stream_frame(frame)
    assert [json.loads(e)["orderId"] for e in events] == ["1", "2"]


def test_decoder_ignores_other_versions_and_short_frames():
    frame = bytearray(_frame(_event_packet(_event())))
    frame[4] = 2
    assert mod.decode_stream_frame(bytes(frame)) == ([], [])
    assert mod.decode_stream_frame(b"\x00\x01") == ([], [])


# -- normalization -------------------------------------------------------------


def test_order_event_maps_to_openalgo_vocabulary(adapter):
    fields = adapter.normalize(_frame(_event_packet(_event())))
    assert fields == {
        "orderid": "210115000000001",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "pricetype": "LIMIT",
        "product": "MIS",
        "order_status": "open",
        "quantity": 10,
        "price": 2450.5,
    }


def test_symid_is_preferred_when_the_broker_sends_it(adapter, symbol_lookup):
    fields = adapter.normalize_event(_event(symId="EQT_RELIANCE_EQ_NSE", trdSym="X"))
    assert fields["symbol"] == "RELIANCE"
    assert symbol_lookup.call_args_list[0].args == ("EQT_RELIANCE_EQ_NSE", "NSE")


def test_unmapped_symbol_passes_through(adapter):
    assert adapter.normalize_event(_event(trdSym="UNKNOWN-EQ"))["symbol"] == "UNKNOWN-EQ"


def test_undocumented_fill_fields_are_not_invented(adapter):
    fields = adapter.normalize_event(_event(status="completed"))
    assert fields["order_status"] == "complete"
    for key in ("filled_quantity", "pending_quantity", "average_price", "trigger_price"):
        assert key not in fields


def test_order_book_field_names_are_read_when_present(adapter):
    fields = adapter.normalize_event(
        _event(status="completed", fillQty=10, pendingQty=0, avgPrice=2451.0, trigPrice=2440)
    )
    assert fields["filled_quantity"] == 10
    assert fields["pending_quantity"] == 0
    assert fields["average_price"] == 2451.0
    assert fields["trigger_price"] == 2440.0


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("open", "open"),
        ("pending", "open"),
        ("trigger pending", "trigger pending"),
        ("completed", "complete"),
        ("filled", "complete"),
        ("rejected", "rejected"),
        ("cancelled", "cancelled"),
        ("canceled", "cancelled"),
        ("Expired", "expired"),
    ],
)
def test_status_mapping(adapter, raw, expected):
    assert adapter.normalize_event(_event(status=raw))["order_status"] == expected


@pytest.mark.parametrize(
    "side, type_, product, action, pricetype, oa_product",
    [
        ("sell", "market", "delivery", "SELL", "MARKET", "CNC"),
        ("b", "stoplimit", "normal", "BUY", "SL", "NRML"),
        ("s", "stopmarket", "intraday", "SELL", "SL-M", "MIS"),
    ],
)
def test_side_type_product(adapter, side, type_, product, action, pricetype, oa_product):
    fields = adapter.normalize_event(_event(side=side, type=type_, product=product))
    assert (fields["action"], fields["pricetype"], fields["product"]) == (
        action,
        pricetype,
        oa_product,
    )


def test_rejection_reason_only_on_rejected(adapter):
    rejected = adapter.normalize_event(_event(status="rejected", reason="Insufficient funds"))
    assert rejected["rejection_reason"] == "Insufficient funds"
    assert "rejection_reason" not in adapter.normalize_event(_event(reason="x"))


@pytest.mark.parametrize("evnt_type", ["positions", "trades", ""])
def test_non_order_events_are_ignored(adapter, evnt_type):
    assert adapter.normalize_event(_event(evntType=evnt_type)) is None


def test_non_json_event_is_ignored(adapter):
    assert adapter.normalize(_frame(_event_packet("not json"))) is None


def test_every_event_in_a_frame_is_published(adapter):
    frame = _frame(_event_packet(_event(orderId="1")), _event_packet(_event(orderId="2")))
    with patch.object(adapter, "_publish_event_fields") as publish:
        adapter._handle_message(frame)
    assert [c.args[0]["orderid"] for c in publish.call_args_list] == ["1", "2"]


def test_auth_accepted_packet_is_quiet(adapter):
    assert adapter.normalize(_frame(_auth_packet(1))) is None
    assert adapter._auth_rejected is False


def test_auth_refused_packet_stands_the_adapter_down(adapter):
    ws = MagicMock()
    adapter._ws = ws
    assert adapter.normalize(_frame(_auth_packet(0), _event_packet(_event()))) is None
    assert adapter._auth_rejected is True
    ws.close.assert_called_once()


# -- wire ----------------------------------------------------------------------


def test_subscribe_frame_matches_the_sdk(adapter):
    ws = MagicMock()
    adapter.on_open_extra(ws)
    sent = ws.send.call_args.args[0]
    assert sent.endswith("\n")
    assert json.loads(sent) == {"type": "event", "action": "sub", "events": ["orders"]}


def test_ws_url_uses_fresh_token_joined_to_api_key(adapter):
    with patch.object(mod, "get_auth_token", return_value="fresh"):
        url = adapter.get_ws_url()
    assert url == "wss://api.tradejini.com/v2.1/stream?token=KEY:fresh&version=3.1"


def test_ws_url_keeps_a_token_that_already_has_the_key(adapter):
    with patch.object(mod, "get_auth_token", return_value="OTHER:tok"):
        assert "token=OTHER:tok&" in adapter.get_ws_url()


# -- factory -------------------------------------------------------------------


def test_factory_returns_none_without_session():
    with patch.object(mod, "get_auth_token", return_value=None):
        assert mod.create_tradejini_order_adapter("trader") is None


def test_factory_returns_none_without_api_key():
    with (
        patch.object(mod, "get_auth_token", return_value="tok"),
        patch("broker.tradejini.api.auth_api.get_api_key", return_value=""),
    ):
        assert mod.create_tradejini_order_adapter("trader") is None


def test_factory_builds_adapter():
    with (
        patch.object(mod, "get_auth_token", return_value="tok"),
        patch("broker.tradejini.api.auth_api.get_api_key", return_value="KEY"),
    ):
        adapter = mod.create_tradejini_order_adapter("trader")
    assert isinstance(adapter, mod.TradejiniOrderUpdateAdapter)
    assert adapter.broker_name == "tradejini"
