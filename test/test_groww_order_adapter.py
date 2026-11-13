"""Groww order-update adapter: NATS order subjects carrying protobuf payloads.

Wire format from the official SDK (growwapi 1.5.0: constants.py subjects,
proto/stock_orders_socket_response_pb2.py); payload fields from
https://groww.in/trade-api/docs/python-sdk/feed.
"""

import importlib
import json
from unittest.mock import MagicMock, patch

import pytest

importlib.import_module("websocket_proxy")
adapter_mod = importlib.import_module("broker.groww.streaming.groww_order_adapter")
groww_nkeys = importlib.import_module("broker.groww.streaming.groww_nkeys")


# -- a minimal protobuf encoder for the test payloads -------------------------


def _varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field(number: int, value) -> bytes:
    if isinstance(value, int):
        return _varint(number << 3) + _varint(value)
    data = value.encode() if isinstance(value, str) else value
    return _varint(number << 3 | 2) + _varint(len(data)) + data


def _order_payload(**fields) -> bytes:
    """OrderDetailsBroadCastDto with an OrderDetailUpdateDto built from fields."""
    numbers = {name: number for number, (name, _) in adapter_mod._ORDER_FIELDS.items()}
    inner = b""
    for name, value in fields.items():
        kind = adapter_mod._ORDER_FIELDS[numbers[name]][1]
        if isinstance(kind, list):
            value = kind.index(value)
            if value == 0:
                continue  # proto3 leaves zero values off the wire
        inner += _field(numbers[name], value)
    stage = _field(2, "ORDER_PLACED")
    return _field(1, stage) + _field(2, inner)


FNO_PUSH = {
    "qty": 75,
    "price": 130,
    "filledQty": 75,
    "remainingQty": 0,
    "avgFillPrice": 110,
    "growwOrderId": "GMKFO250214150557M2HR6EJF2HSE",
    "exchangeOrderId": "1400000179694433",
    "orderStatus": "EXECUTED",
    "exchange": "NSE",
    "segment": "FNO",
    "product": "NRML",
    "orderType": "LIMIT",
    "transactionType": "SELL",
    "contractId": "NIFTY2522025400CE",
}


@pytest.fixture
def adapter():
    with (
        patch.object(adapter_mod, "get_oa_symbol", side_effect=lambda s, e: f"OA:{s}"),
        patch.object(adapter_mod, "to_openalgo_symbol", side_effect=lambda s, e: f"OA:{s}"),
    ):
        yield adapter_mod.GrowwOrderUpdateAdapter(user_id="trader", auth_token="tok")


def test_decoder_reads_every_field_and_defaults_zero_enums():
    push = adapter_mod.decode_order_update(
        _order_payload(
            qty=3,
            filledQty=3,
            growwOrderId="GMK1",
            orderStatus="EXECUTED",
            exchange="BSE",
            segment="CASH",
            contractId="INE221H01019",
        )
    )
    assert push["qty"] == 3
    assert push["growwOrderId"] == "GMK1"
    assert push["orderStatus"] == "EXECUTED"
    # Zero enums are absent on the wire: BSE, CASH, CNC, MARKET, BUY.
    assert (push["exchange"], push["segment"], push["product"]) == ("BSE", "CASH", "CNC")
    assert (push["orderType"], push["transactionType"]) == ("MARKET", "BUY")
    assert push["contractId"] == "INE221H01019"


def test_order_detail_supplies_symbol_and_prices(adapter):
    detail = {
        "groww_order_id": "GMK250502123553ZXM5BKVXX9LM",
        "trading_symbol": "IDEA",
        "exchange": "NSE",
        "segment": "CASH",
        "transaction_type": "BUY",
        "order_type": "SL_M",
        "product": "CNC",
        "price": 0,
        "trigger_price": 14.5,
        "average_fill_price": 14.55,
    }
    payload = _order_payload(
        qty=3,
        filledQty=3,
        growwOrderId="GMK250502123553ZXM5BKVXX9LM",
        orderStatus="EXECUTED",
        exchange="NSE",
        contractId="INE669E01016",
    )
    with patch.object(adapter, "_order_detail", return_value=detail) as read:
        fields = adapter.normalize(payload)
    read.assert_called_once_with("GMK250502123553ZXM5BKVXX9LM", "CASH")
    assert fields == {
        "orderid": "GMK250502123553ZXM5BKVXX9LM",
        "order_status": "complete",
        "quantity": 3,
        "filled_quantity": 3,
        "pending_quantity": 0,
        "rejection_reason": "",
        "symbol": "OA:IDEA",
        "exchange": "NSE",
        "action": "BUY",
        "price": 0.0,
        "trigger_price": 14.5,
        "pricetype": "SL-M",
        "product": "CNC",
        "average_price": 14.55,
    }


def test_push_fields_are_used_when_the_detail_read_fails(adapter):
    with patch.object(adapter, "_order_detail", return_value=None):
        fields = adapter.normalize(_order_payload(**FNO_PUSH))
    assert fields["exchange"] == "NFO"
    assert fields["symbol"] == "OA:NIFTY2522025400CE"
    assert fields["action"] == "SELL"
    assert fields["pricetype"] == "LIMIT"
    assert fields["product"] == "NRML"
    assert (fields["price"], fields["average_price"]) == (130.0, 110.0)
    assert fields["order_status"] == "complete"


def test_rejection_and_trigger_pending(adapter):
    with patch.object(adapter, "_order_detail", return_value=None):
        rejected = adapter.normalize(
            _order_payload(growwOrderId="G1", orderStatus="REJECTED", remark="Insufficient margin")
        )
        pending = adapter.normalize(
            _order_payload(growwOrderId="G2", orderStatus="TRIGGER_PENDING", remark="Order placed")
        )
    assert rejected["order_status"] == "rejected"
    assert rejected["rejection_reason"] == "Insufficient margin"
    assert pending["order_status"] == "trigger pending"
    assert pending["rejection_reason"] == ""


def test_handshake_answers_first_info_only_and_subscribes_both_subjects(adapter):
    key_pair = groww_nkeys.generate_keypair()
    adapter._nkey_seed = key_pair.seed
    adapter.socket_token = "jwt"
    adapter.subscription_id = "sub-1"
    ws = MagicMock()
    adapter._ws = ws

    info = b'INFO {"server_id":"x","nonce":"abc"}\r\n'
    assert adapter._split_frames(info) == []
    sent = ws.send.call_args[0][0]
    connect_line, sub_eq, sub_fo, ping = sent.split("\r\n")[:4]
    connect = json.loads(connect_line[len("CONNECT ") :])
    assert connect["jwt"] == "jwt"
    assert connect["nkey"] == key_pair.public_key.decode()
    assert connect["sig"]
    assert sub_eq == "SUB stocks/order/updates.apex.sub-1 1"
    assert sub_fo == "SUB stocks_fo/order/updates.apex.sub-1 2"
    assert ping == "PING"

    ws.send.reset_mock()
    adapter._split_frames(info)  # the INFO after CONNECT
    ws.send.assert_not_called()

    adapter._split_frames(b"PING\r\n")
    ws.send.assert_called_once_with("PONG\r\n")


def test_msg_split_across_frames_is_reassembled(adapter):
    adapter._ws = MagicMock()
    payload = _order_payload(**FNO_PUSH)
    frame = b"MSG stocks_fo/order/updates.apex.sub-1 2 %d\r\n" % len(payload) + payload + b"\r\n"
    assert adapter._split_frames(frame[:30]) == []
    assert adapter._split_frames(frame[30:] + b"PONG\r\n") == [payload]

    published = []
    adapter._publish_event_fields = published.append
    with patch.object(adapter, "_order_detail", return_value=None):
        adapter._handle_message(frame)
    assert [p["orderid"] for p in published] == [FNO_PUSH["growwOrderId"]]


def test_socket_token_refusal_stands_the_adapter_down(adapter):
    response = MagicMock(status_code=401)
    client = MagicMock()
    client.post.return_value = response
    with patch.object(adapter_mod, "get_httpx_client", return_value=client):
        with pytest.raises(adapter_mod.GrowwSocketTokenRefused) as exc:
            adapter.get_ws_url()
    assert exc.value.status_code == 401  # read by order_adapter._is_auth_rejection


def test_factory_without_session_returns_none():
    with patch.object(adapter_mod, "get_auth_token", return_value=None):
        assert adapter_mod.create_groww_order_adapter("trader") is None


def test_factory_with_session_builds_the_adapter():
    with patch.object(adapter_mod, "get_auth_token", return_value="tok"):
        a = adapter_mod.create_groww_order_adapter("trader")
    assert isinstance(a, adapter_mod.GrowwOrderUpdateAdapter)
    assert a.auth_token == "tok"
