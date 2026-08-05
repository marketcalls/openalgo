"""
Nubra order-update adapter — realtime order/trade events over the
notifications WebSocket stream.

Docs: broker-api-docs/nubra-api-rest-api-v3-llm-builder.md, "Realtime Order
Updates" section.
Endpoint: discovered per-session from GET /userinfo -> env_info.user_ws_url
(the URL is environment specific, so it must not be hardcoded). Falls back to
NUBRA_ORDER_WS_URL, then to the UAT endpoint.
Auth: Bearer session token + x-device-id headers (same convention as
broker/nubra/api/nubrawebsocket.py), then a post-open text handshake:
    subscribe <session_token> notifications notification

Payloads are binary protobuf: an outer google.protobuf.Any whose value is an
inner Any whose type_url ends with "NubraToClientIntentUpdate". That message
is NOT part of the in-tree broker/nubra/protos (only REST's
NubraOrderRequest/Response are), so this adapter decodes the wire format
directly with a minimal varint/length-delimited walker — extracting only the
fields OpenAlgo needs. Prices arrive in paise (÷100, matching
nubrawebsocket.py's convention).
"""

import os

from google.protobuf.any_pb2 import Any as ProtoAny

from broker.nubra.api.auth_api import get_ws_urls
from broker.nubra.mapping.order_data import resolve_instrument
from broker.nubra.mapping.transform_data import map_exchange
from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter

logger = get_logger(__name__)

NUBRA_ORDER_WS_URL_DEFAULT = "wss://uatapi.nubra.io/ws"

# NubraIntentOrderStatus enum -> OpenAlgo's lowercase order_status vocabulary.
# GTE (good-till-triggered) is a still-armed working order -> "open".
_STATUS_MAP = {1: "open", 2: "complete", 3: "rejected", 4: "trigger pending", 5: "cancelled", 6: "expired"}

# OrderSide enum -> OpenAlgo action constants
_ACTION_MAP = {1: "BUY", 2: "SELL"}

# PriceType enum -> OpenAlgo pricetype constants
_PRICETYPE_MAP = {1: "LIMIT", 2: "MARKET"}

# OrderDeliveryType enum -> OpenAlgo product constants (IDAY = intraday)
_PRODUCT_MAP = {1: "CNC", 2: "MIS"}


def _decode_fields(buf: bytes) -> dict[int, list]:
    """Minimal protobuf wire-format walker.

    Returns {field_number: [raw values]} where varint fields decode to int,
    length-delimited fields stay bytes (caller decides nested-message vs
    string), and fixed32/fixed64 decode to int. Unknown/undecodable input
    raises ValueError so callers can skip the frame.
    """
    fields: dict[int, list] = {}
    i, n = 0, len(buf)

    def read_varint(pos: int) -> tuple[int, int]:
        result, shift = 0, 0
        while True:
            if pos >= n:
                raise ValueError("truncated varint")
            b = buf[pos]
            result |= (b & 0x7F) << shift
            pos += 1
            if not (b & 0x80):
                return result, pos
            shift += 7
            if shift > 70:
                raise ValueError("varint too long")

    while i < n:
        tag, i = read_varint(i)
        field_no, wire_type = tag >> 3, tag & 0x07
        if wire_type == 0:  # varint
            value, i = read_varint(i)
        elif wire_type == 1:  # fixed64
            if i + 8 > n:
                raise ValueError("truncated fixed64")
            value = int.from_bytes(buf[i : i + 8], "little")
            i += 8
        elif wire_type == 2:  # length-delimited
            length, i = read_varint(i)
            if i + length > n:
                raise ValueError("truncated length-delimited field")
            value = buf[i : i + length]
            i += length
        elif wire_type == 5:  # fixed32
            if i + 4 > n:
                raise ValueError("truncated fixed32")
            value = int.from_bytes(buf[i : i + 4], "little")
            i += 4
        else:
            raise ValueError(f"unsupported wire type {wire_type}")
        fields.setdefault(field_no, []).append(value)
    return fields


def _first(fields: dict[int, list], field_no: int, default=0):
    values = fields.get(field_no)
    return values[0] if values else default


def _first_str(fields: dict[int, list], field_no: int) -> str:
    value = _first(fields, field_no, b"")
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return ""
    return str(value)


class NubraOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for Nubra (protobuf notifications stream)."""

    def __init__(self, user_id: str, session_token: str, device_id: str = "OPENALGO"):
        super().__init__(broker_name="nubra", user_id=user_id)
        self.session_token = session_token
        self.device_id = device_id
        self._ws_url = None

    def get_ws_url(self) -> str:
        """
        Resolve the order-update stream URL for this session.

        Nubra publishes it per environment via GET /userinfo, so ask the API
        first and only fall back to a configured/default endpoint if that call
        fails. Resolved once per adapter, then reused across reconnects.
        """
        if self._ws_url is None:
            user_ws_url, _market_ws_url = get_ws_urls(self.session_token, self.device_id)
            if user_ws_url:
                self.logger.info(f"Nubra order WS URL from /userinfo: {user_ws_url}")
            self._ws_url = user_ws_url or os.getenv(
                "NUBRA_ORDER_WS_URL", NUBRA_ORDER_WS_URL_DEFAULT
            )
        return self._ws_url

    def get_headers(self):
        return {
            "Authorization": f"Bearer {self.session_token}",
            "x-device-id": self.device_id,
        }

    def on_open_extra(self, ws) -> None:
        ws.send(f"subscribe {self.session_token} notifications notification")
        self.logger.info("Sent Nubra notifications subscribe")

    def normalize(self, raw_message):
        # Text frames are handshake acks / errors ("Invalid Token" -> the
        # reconnect loop re-fetches credentials via the factory on restart).
        if isinstance(raw_message, str):
            text = raw_message.strip()
            if text and text != "OK":
                self.logger.info(f"Nubra notifications text frame: {text}")
            return None
        if not isinstance(raw_message, (bytes, bytearray)):
            return None

        try:
            outer = ProtoAny()
            outer.ParseFromString(bytes(raw_message))
            inner = ProtoAny()
            inner.ParseFromString(outer.value)
        except Exception:
            return None

        if not inner.type_url.endswith("NubraToClientIntentUpdate"):
            return None

        try:
            update = _decode_fields(inner.value)
            response_bytes = _first(update, 1, b"")
            if not isinstance(response_bytes, bytes) or not response_bytes:
                return None
            resp = _decode_fields(response_bytes)
        except ValueError as e:
            self.logger.debug(f"Nubra intent-update decode failed: {e}")
            return None

        raw_status = int(_first(resp, 2, 0))
        order_status = _STATUS_MAP.get(raw_status, "open")

        symbol, exchange = "", ""
        refdata_bytes = _first(resp, 25, b"")
        if isinstance(refdata_bytes, bytes) and refdata_bytes:
            try:
                refdata = _decode_fields(refdata_bytes)
                broker_symbol = _first_str(refdata, 5)   # stock_name
                nubra_exchange = _first_str(refdata, 10)
                derivative_type = _first_str(refdata, 11)
                # RefData field 1 is ref_id, which is what Nubra stores in
                # symtoken.token. Field 4 is the exchange token and never
                # matches. resolve_instrument() also folds Nubra's "NSE" to NFO
                # for derivatives and confirms both against the master contract.
                symbol, exchange = resolve_instrument(
                    nubra_exchange,
                    derivative_type,
                    ref_id=_first(refdata, 1, None),
                    broker_symbol=broker_symbol,
                )
                if not symbol:
                    self.logger.warning(
                        f"Nubra order update not in the master contract: "
                        f"stockName={broker_symbol!r} exchange={nubra_exchange!r} "
                        f"derivativeType={derivative_type!r}"
                    )
                    symbol = broker_symbol
                    exchange = map_exchange(nubra_exchange, derivative_type)
            except ValueError:
                pass

        order_qty = int(_first(resp, 13, 0))
        filled_qty = int(_first(resp, 14, 0))

        # Prefer the trade-fill price for average when a fill event is present.
        average_paise = int(_first(resp, 18, 0))
        trade_fill_bytes = _first(resp, 19, b"")
        if isinstance(trade_fill_bytes, bytes) and trade_fill_bytes:
            try:
                trade_fill = _decode_fields(trade_fill_bytes)
                fill_price = int(_first(trade_fill, 2, 0))
                if fill_price:
                    average_paise = fill_price
            except ValueError:
                pass

        return {
            "orderid": str(int(_first(resp, 1, 0)) or ""),
            "symbol": symbol,
            "exchange": exchange,
            "action": _ACTION_MAP.get(int(_first(resp, 29, 0)), ""),
            "quantity": order_qty,
            "price": int(_first(resp, 17, 0)) / 100.0,
            "pricetype": _PRICETYPE_MAP.get(int(_first(resp, 8, 0)), ""),
            "product": _PRODUCT_MAP.get(int(_first(resp, 7, 0)), ""),
            "order_status": order_status,
            "filled_quantity": filled_qty,
            "pending_quantity": max(order_qty - filled_qty, 0),
            "average_price": average_paise / 100.0,
            "rejection_reason": _first_str(resp, 31) if order_status == "rejected" else "",
        }


def create_nubra_order_adapter(user_id: str) -> "NubraOrderUpdateAdapter | None":
    """Factory: build a NubraOrderUpdateAdapter for user_id (session token from DB)."""
    session_token = get_auth_token(user_id, bypass_cache=True)
    if not session_token:
        logger.warning(f"No Nubra session token found for user {user_id}; order-update adapter not started")
        return None

    return NubraOrderUpdateAdapter(user_id=user_id, session_token=session_token)
