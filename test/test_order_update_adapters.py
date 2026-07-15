"""Unit tests for the real-time order-update adapters.

Covers the pure normalization layer of every broker order-update adapter —
sample payloads are taken from each broker's API documentation
(broker-api-docs/) — plus the Nubra protobuf wire decoder, the
to_openalgo_symbol helper, and the postback normalizers. No sockets are
opened: normalize() and the maps are exercised directly.
"""

import atexit
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Env must be set before importing database-backed modules (engine + PEPPER
# bind at import time). Mirrors test_auth_upsert_multisession.py.
TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_order_update_adapters.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("API_KEY_PEPPER", "a" * 64)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

# websocket_proxy must load before broker.*.streaming modules (the packages
# import each other; the cycle only resolves in this order — same as app.py).
import websocket_proxy  # noqa: E402, F401
from websocket_proxy.order_adapter import _RECONNECT_BACKOFFS, to_openalgo_symbol  # noqa: E402

# ---------------------------------------------------------------------------
# to_openalgo_symbol helper
# ---------------------------------------------------------------------------


def test_to_openalgo_symbol_falls_back_to_broker_symbol():
    # No master-contract row for this fake symbol -> raw value passes through.
    assert to_openalgo_symbol("FAKE-XYZ-EQ", "NSE") == "FAKE-XYZ-EQ"
    assert to_openalgo_symbol("", "") == ""


def test_to_openalgo_symbol_prefers_token_lookup(monkeypatch):
    import database.token_db as token_db

    monkeypatch.setattr(token_db, "get_symbol", lambda token, exchange: "NHPC")
    monkeypatch.setattr(token_db, "get_oa_symbol", lambda symbol, exchange: "WRONG")
    assert to_openalgo_symbol("NHPC-EQ", "NSE", token="NSE_EQ|INE848E01016") == "NHPC"


def test_to_openalgo_symbol_uses_brsymbol_lookup(monkeypatch):
    import database.token_db as token_db

    monkeypatch.setattr(token_db, "get_symbol", lambda token, exchange: None)
    monkeypatch.setattr(token_db, "get_oa_symbol", lambda symbol, exchange: "SBIN")
    assert to_openalgo_symbol("SBIN-EQ", "NSE") == "SBIN"


def test_reconnect_backoff_is_bounded():
    assert _RECONNECT_BACKOFFS[0] >= 1
    assert max(_RECONNECT_BACKOFFS) <= 60


# ---------------------------------------------------------------------------
# Zerodha — Kite ticker text frames (12-postbacks.md payload shape)
# ---------------------------------------------------------------------------


def _zerodha_adapter():
    from broker.zerodha.streaming.zerodha_order_adapter import ZerodhaOrderUpdateAdapter

    return ZerodhaOrderUpdateAdapter(user_id="u", api_key="k", access_token="t")


def test_zerodha_normalize_complete():
    fields = _zerodha_adapter().normalize(json.dumps({
        "type": "order",
        "data": {
            "order_id": "220303000308932", "status": "COMPLETE",
            "tradingsymbol": "SBIN", "exchange": "NSE",
            "transaction_type": "BUY", "order_type": "MARKET", "product": "CNC",
            "quantity": 1, "filled_quantity": 1, "pending_quantity": 0,
            "average_price": 470, "price": 0, "trigger_price": 0,
        },
    }))
    assert fields["order_status"] == "complete"
    assert fields["action"] == "BUY"
    assert fields["pricetype"] == "MARKET"
    assert fields["average_price"] == 470.0


def test_zerodha_ignores_binary_and_non_order_frames():
    adapter = _zerodha_adapter()
    assert adapter.normalize(b"\x00\x01\x02") is None  # binary tick/heartbeat
    assert adapter.normalize(json.dumps({"type": "message", "data": "hello"})) is None


def test_zerodha_rejected_carries_status_message():
    fields = _zerodha_adapter().normalize(json.dumps({
        "type": "order",
        "data": {"order_id": "1", "status": "REJECTED", "tradingsymbol": "SBIN",
                 "exchange": "NSE", "status_message": "RMS: margin shortfall"},
    }))
    assert fields["order_status"] == "rejected"
    assert fields["rejection_reason"] == "RMS: margin shortfall"


# ---------------------------------------------------------------------------
# Dhan — Live Order Update WS (13-live-order-update.md sample)
# ---------------------------------------------------------------------------


def _dhan_adapter():
    from broker.dhan.streaming.dhan_order_adapter import DhanOrderUpdateAdapter

    return DhanOrderUpdateAdapter(user_id="u", client_id="c", access_token="t")


def test_dhan_normalize_doc_sample():
    fields = _dhan_adapter().normalize(json.dumps({
        "Type": "order_alert",
        "Data": {
            "Exchange": "NSE", "Segment": "E", "OrderNo": "1124091136546",
            "Symbol": "IDEA", "TxnType": "B", "OrderType": "LMT", "Product": "C",
            "Status": "Cancelled", "Quantity": 1, "TradedQty": 0,
            "Price": 13, "TriggerPrice": 0, "AvgTradedPrice": 0,
        },
    }))
    assert fields["order_status"] == "cancelled"
    assert fields["pricetype"] == "LIMIT"
    assert fields["product"] == "CNC"
    assert fields["action"] == "BUY"
    assert fields["exchange"] == "NSE"


def test_dhan_derivative_segment_maps_to_nfo():
    fields = _dhan_adapter().normalize(json.dumps({
        "Type": "order_alert",
        "Data": {"Exchange": "NSE", "Segment": "D", "OrderNo": "1",
                 "Symbol": "NIFTY-Jul2026-FUT", "TxnType": "S", "OrderType": "MKT",
                 "Product": "M", "Status": "TRADED", "Quantity": 65, "TradedQty": 65},
    }))
    assert fields["exchange"] == "NFO"
    assert fields["order_status"] == "complete"
    assert fields["product"] == "NRML"


def test_dhan_ignores_non_order_frames():
    assert _dhan_adapter().normalize(json.dumps({"Type": "login_ack"})) is None


# ---------------------------------------------------------------------------
# Fyers — order WS / postback numeric codes (FYERS_API_v3.md)
# ---------------------------------------------------------------------------


def _fyers_adapter():
    from broker.fyers.streaming.fyers_order_adapter import FyersOrderUpdateAdapter

    return FyersOrderUpdateAdapter(user_id="u", app_id="a", access_token="t")


def test_fyers_normalize_filled_fno():
    fields = _fyers_adapter().normalize(json.dumps({
        "id": "23071800238607", "status": 2, "symbol": "NSE:ABCAPITAL23JUL190CE",
        "qty": 5400, "filledQty": 5400, "remainingQuantity": 0, "side": -1,
        "type": 2, "productType": "MARGIN", "tradedPrice": 2.15,
        "limitPrice": 2.15, "stopPrice": 0, "exchange": 10, "segment": 11,
        "message": "Completed",
    }))
    assert fields["order_status"] == "complete"
    assert fields["action"] == "SELL"
    assert fields["pricetype"] == "MARKET"
    assert fields["exchange"] == "NFO"  # NSE (10) + F&O segment (11)


def test_fyers_rejected_carries_message():
    fields = _fyers_adapter().normalize(json.dumps({
        "id": "1", "status": 5, "symbol": "NSE:SBIN-EQ", "qty": 1, "filledQty": 0,
        "side": 1, "type": 1, "exchange": 10, "segment": 10,
        "message": "insufficient funds",
    }))
    assert fields["order_status"] == "rejected"
    assert fields["rejection_reason"] == "insufficient funds"
    assert fields["exchange"] == "NSE"


# ---------------------------------------------------------------------------
# Upstox — portfolio stream (21c/23 payload shape; live-verified fields)
# ---------------------------------------------------------------------------


def _upstox_adapter():
    from broker.upstox.streaming.upstox_order_adapter import UpstoxOrderUpdateAdapter

    return UpstoxOrderUpdateAdapter(user_id="u", access_token="t")


def test_upstox_normalize_rejected_with_rms_reason():
    fields = _upstox_adapter().normalize(json.dumps({
        "update_type": "order", "order_id": "260715000344871",
        "trading_symbol": "NHPC-EQ", "exchange": "NSE", "transaction_type": "BUY",
        "quantity": 1, "price": 50, "trigger_price": 0, "order_type": "LIMIT",
        "product": "D", "status": "rejected",
        "status_message": "RMS:Rule: Check circuit limit ... Circuit breach",
        "filled_quantity": 0, "pending_quantity": 0, "average_price": 0,
    }))
    assert fields["order_status"] == "rejected"
    assert fields["rejection_reason"].startswith("RMS:Rule")
    assert fields["product"] == "CNC"  # D -> CNC


def test_upstox_ignores_position_updates():
    assert _upstox_adapter().normalize(json.dumps({"update_type": "position"})) is None


# ---------------------------------------------------------------------------
# AliceBlue / Definedge — Noren om frames (10-webhooks.md / 11-order-update.md)
# ---------------------------------------------------------------------------


def test_aliceblue_normalize_rejected():
    from broker.aliceblue.streaming.aliceblue_order_adapter import (
        AliceBlueOrderUpdateAdapter,
    )

    adapter = AliceBlueOrderUpdateAdapter(user_id="u", alice_ucc="1332014", auth_token="t")
    fields = adapter.normalize(json.dumps({
        "t": "om", "norenordno": "24070600000744", "tsym": "MRF-EQ", "exch": "NSE",
        "qty": "1", "prc": "0.00", "prctyp": "MKT", "trantype": "B", "pcode": "I",
        "status": "REJECTED", "reporttype": "Rejected",
        "rejreason": "RED:Margin Shortfall",
    }))
    assert fields["order_status"] == "rejected"
    assert fields["rejection_reason"] == "RED:Margin Shortfall"
    assert fields["action"] == "BUY"
    assert fields["pricetype"] == "MARKET"


def test_definedge_normalize_fill_and_ck_ack():
    from broker.definedge.streaming.definedge_order_adapter import (
        DefinedgeOrderUpdateAdapter,
    )

    adapter = DefinedgeOrderUpdateAdapter(user_id="u", definedge_uid="1272808", susertoken="s")
    # connect-ack frame with no live socket: handled, produces no event
    assert adapter.normalize(json.dumps({"t": "ck", "s": "Ok"})) is None

    fields = adapter.normalize(json.dumps({
        "t": "om", "norenordno": "1", "tsym": "INFY-EQ", "exch": "NSE",
        "qty": "10", "fillshares": "10", "avgprc": "1500.5", "prc": "0",
        "prctyp": "MKT", "trantype": "B", "prd": "M", "status": "COMPLETE",
    }))
    assert fields["order_status"] == "complete"
    assert fields["product"] == "NRML"
    assert fields["filled_quantity"] == 10
    assert fields["average_price"] == 1500.5


# ---------------------------------------------------------------------------
# Angel — smart-order-update frames (11-websocket-order-status.md)
# ---------------------------------------------------------------------------


def _angel_adapter():
    from broker.angel.streaming.angel_order_adapter import AngelOrderUpdateAdapter

    return AngelOrderUpdateAdapter(user_id="u", auth_token="t")


def test_angel_status_codes_and_maps():
    fields = _angel_adapter().normalize(json.dumps({
        "order-status": "AB05",
        "orderData": {
            "orderid": "1111111", "tradingsymbol": "SBIN-EQ", "exchange": "NSE",
            "transactiontype": "BUY", "quantity": "1", "filledshares": "1",
            "unfilledshares": "0", "ordertype": "STOPLOSS_LIMIT",
            "producttype": "DELIVERY", "price": 551, "triggerprice": 550,
            "averageprice": 551,
        },
    }))
    assert fields["order_status"] == "complete"  # AB05
    assert fields["pricetype"] == "SL"
    assert fields["product"] == "CNC"


def test_angel_connection_ack_ignored():
    assert _angel_adapter().normalize(json.dumps({
        "order-status": "AB00", "orderData": {"orderid": ""},
    })) is None


# ---------------------------------------------------------------------------
# IndMoney — thin order stream (08-websockets.md sample)
# ---------------------------------------------------------------------------


def test_indmoney_partially_executed_is_open():
    from broker.indmoney.streaming.indmoney_order_adapter import (
        IndmoneyOrderUpdateAdapter,
    )

    adapter = IndmoneyOrderUpdateAdapter(user_id="u", access_token="t")
    fields = adapter.normalize(json.dumps({
        "type": "order", "order_id": "INDM20250512ABC123",
        "order_status": "PARTIALLY_EXECUTED", "filled_quantity": 5,
        "remaining_quantity": 5, "average_price": 2500.40,
    }))
    assert fields["order_status"] == "open"
    assert fields["quantity"] == 10
    assert fields["filled_quantity"] == 5
    assert fields["pending_quantity"] == 5


# ---------------------------------------------------------------------------
# Arrow — order-updates stream (12-order-data.md sample; string numerics)
# ---------------------------------------------------------------------------


def test_arrow_doc_sample_pending():
    from broker.arrow.streaming.arrow_order_adapter import ArrowOrderUpdateAdapter

    adapter = ArrowOrderUpdateAdapter(user_id="u", app_id="a", access_token="t")
    assert adapter.normalize("PING") is None  # non-JSON heartbeat text

    fields = adapter.normalize(json.dumps({
        "updateType": "ORDER_UPDATE", "exchange": "NFO",
        "symbol": "NIFTY27JAN26C25300", "id": "26012301000023", "price": "0.05",
        "quantity": "65", "product": "M", "orderStatus": "PENDING",
        "transactionType": "B", "order": "LMT", "cumulativeFillQty": "0",
        "averagePrice": "0", "orderTriggerPrice": "0", "leavesQuantity": "65",
    }))
    assert fields["order_status"] == "open"
    assert fields["pricetype"] == "LIMIT"
    assert fields["product"] == "MIS"
    assert fields["quantity"] == 65
    assert fields["pending_quantity"] == 65


# ---------------------------------------------------------------------------
# Nubra — protobuf wire decoder (hand-encoded NubraToClientIntentUpdate)
# ---------------------------------------------------------------------------


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        bits = value & 0x7F
        value >>= 7
        if value:
            out.append(bits | 0x80)
        else:
            out.append(bits)
            return bytes(out)


def _field(field_no: int, wire_type: int, payload: bytes) -> bytes:
    return _varint((field_no << 3) | wire_type) + payload


def _varint_field(field_no: int, value: int) -> bytes:
    return _field(field_no, 0, _varint(value))


def _bytes_field(field_no: int, value: bytes) -> bytes:
    return _field(field_no, 2, _varint(len(value)) + value)


def test_nubra_wire_decoder_and_normalize():
    from google.protobuf.any_pb2 import Any as ProtoAny

    from broker.nubra.streaming.nubra_order_adapter import NubraOrderUpdateAdapter

    refdata = _bytes_field(5, b"RELIANCE") + _bytes_field(10, b"NSE")
    intent_response = (
        _varint_field(1, 987654321)      # intent_order_id
        + _varint_field(2, 2)            # order_status: EXECUTED
        + _varint_field(7, 2)            # delivery_type: IDAY -> MIS
        + _varint_field(8, 2)            # price_type: MARKET
        + _varint_field(13, 10)          # order_qty
        + _varint_field(14, 10)          # filled_qty
        + _varint_field(17, 142400)      # order_price (paise)
        + _varint_field(18, 142385)      # filled_price (paise)
        + _bytes_field(25, refdata)      # refdata
        + _varint_field(29, 1)           # order_side: BUY
    )
    update = _bytes_field(1, intent_response)

    inner = ProtoAny(type_url="type.googleapis.com/nubra.NubraToClientIntentUpdate",
                     value=update)
    outer = ProtoAny(type_url="type.googleapis.com/google.protobuf.Any",
                     value=inner.SerializeToString())

    adapter = NubraOrderUpdateAdapter(user_id="u", session_token="t")
    fields = adapter.normalize(outer.SerializeToString())

    assert fields["orderid"] == "987654321"
    assert fields["order_status"] == "complete"
    assert fields["action"] == "BUY"
    assert fields["pricetype"] == "MARKET"
    assert fields["product"] == "MIS"
    assert fields["quantity"] == 10
    assert fields["price"] == 1424.0          # paise -> rupees
    assert fields["average_price"] == 1423.85
    assert fields["symbol"] == "RELIANCE"
    assert fields["exchange"] == "NSE"


def test_nubra_ignores_text_and_foreign_frames():
    from broker.nubra.streaming.nubra_order_adapter import NubraOrderUpdateAdapter

    adapter = NubraOrderUpdateAdapter(user_id="u", session_token="t")
    assert adapter.normalize("Invalid Token") is None
    assert adapter.normalize(b"\x00garbage") is None


# ---------------------------------------------------------------------------
# Postback normalizers (blueprints/postback.py)
# ---------------------------------------------------------------------------


def test_postback_normalizers_map_to_common_format():
    import blueprints.postback as pb

    samples = {
        "zerodha": {"order_id": "1", "status": "COMPLETE", "tradingsymbol": "SBIN",
                    "exchange": "NSE", "transaction_type": "BUY", "quantity": 1,
                    "filled_quantity": 1, "average_price": 470},
        "dhan": {"orderId": "2", "orderStatus": "TRADED", "tradingSymbol": "SBIN",
                 "exchangeSegment": "NSE_EQ", "transactionType": "BUY", "quantity": 1,
                 "filled_qty": 1, "orderType": "MARKET", "productType": "CNC"},
        "fyers": {"id": "3", "status": 2, "symbol": "NSE:SBIN-EQ", "qty": 1,
                  "filledQty": 1, "side": 1, "type": 2, "productType": "CNC",
                  "exchange": 10, "segment": 10},
        "upstox": {"update_type": "order", "order_id": "4", "status": "complete",
                   "trading_symbol": "SBIN-EQ", "exchange": "NSE",
                   "transaction_type": "BUY", "quantity": 1, "filled_quantity": 1,
                   "order_type": "MARKET", "product": "D"},
        "angel": {"orderid": "5", "orderstatus": "complete",
                  "tradingsymbol": "SBIN-EQ", "exchange": "NSE",
                  "transactiontype": "BUY", "quantity": "1", "filledshares": "1",
                  "unfilledshares": "0", "ordertype": "MARKET",
                  "producttype": "DELIVERY"},
        "aliceblue": {"norenordno": "6", "status": "Complete", "tsym": "SBIN-EQ",
                      "exch": "NSE", "trantype": "B", "qty": 1, "fillshares": 1,
                      "prctyp": "MKT", "pcode": "CNC"},
    }
    for broker, payload in samples.items():
        fields = pb._NORMALIZERS[broker](payload)
        assert fields is not None, broker
        assert fields["order_status"] == "complete", broker
        assert fields["action"] == "BUY", broker
        assert fields["exchange"] == "NSE", (broker, fields["exchange"])


def test_dhan_postback_fno_exchange_mapping():
    import blueprints.postback as pb

    fields = pb._NORMALIZERS["dhan"]({
        "orderId": "9", "orderStatus": "PENDING", "tradingSymbol": "NIFTY-FUT",
        "exchangeSegment": "NSE_FNO", "transactionType": "SELL", "quantity": 65,
        "filled_qty": 0, "orderType": "STOP_LOSS", "productType": "MARGIN",
    })
    assert fields["exchange"] == "NFO"
    assert fields["pricetype"] == "SL"
    assert fields["product"] == "NRML"
    assert fields["order_status"] == "open"
