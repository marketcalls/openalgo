"""
Groww order-update adapter: the order-update subjects of Groww's NATS feed.

Docs: https://groww.in/trade-api/docs/python-sdk/feed ("Derivatives order
updates" / "Equity order updates": subscribe_fno_order_updates,
subscribe_equity_order_updates; payload fields qty, price, filledQty,
avgFillPrice, growwOrderId, exchangeOrderId, orderStatus, duration, exchange,
segment, product, contractId). The cURL reference has no feed page, so the
wire format follows the official SDK, growwapi 1.5.0 on PyPI:

- socket token: POST https://api.groww.in/v1/api/apex/v1/socket/token/create/
  with {"socketKey": <nkey public key>} -> {"token", "subscriptionId"}
  (client.py generate_socket_token)
- feed: NATS over wss://socket-api.groww.in, CONNECT with the token as jwt and
  the server nonce signed by the nkey (nats_client.py, as
  broker/groww/streaming/nats_websocket.py already does for market data)
- subjects (constants.py): "stocks/order/updates.apex.<subscriptionId>" (CASH)
  and "stocks_fo/order/updates.apex.<subscriptionId>" (FNO). The SDK has no
  commodity order-update subject.
- payload: protobuf OrderDetailsBroadCastDto, field 2 OrderDetailUpdateDto
  (proto/stock_orders_socket_response_pb2.py)

An equity update names the instrument by ISIN (contractId), which the master
contract does not hold, and the feed does not say what unit its integer
prices are in. So the order's symbol, prices and attributes are read from
GET /v1/order/detail/{groww_order_id} (04-orders.md "Get order details") and
mapped as the orderbook maps them (api/order_api.py direct_get_order_book,
mapping/order_data.py); the status and quantities come from the push. When
the detail read fails, the push's own fields are used.

The adapter opens its own NATS connection with its own socket token and
subscribes only to the two order subjects.
"""

import base64
import json
import uuid

from broker.groww.api.rate_limiter import groww_request
from broker.groww.mapping.order_data import GROWW_PRICETYPE_MAP, map_order_status
from broker.groww.mapping.transform_data import openalgo_exchange
from broker.groww.streaming import groww_nkeys
from broker.groww.streaming.groww_nats import NATSProtocol
from database.auth_db import get_auth_token
from database.token_db import get_oa_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

GROWW_FEED_URL = "wss://socket-api.groww.in"
GROWW_SOCKET_TOKEN_URL = "https://api.groww.in/v1/api/apex/v1/socket/token/create/"
GROWW_ORDER_DETAIL_URL = "https://api.groww.in/v1/order/detail/"
EQUITY_ORDER_SUBJECT = "stocks/order/updates.apex."
FNO_ORDER_SUBJECT = "stocks_fo/order/updates.apex."

# Enum names from StockOrdersSocketResponse.proto, indexed by wire value.
_ORDER_STATUS = [
    "NEW",
    "ACKED",
    "TRIGGER_PENDING",
    "APPROVED",
    "REJECTED",
    "FAILED",
    "EXECUTED",
    "DELIVERY_AWAITED",
    "CANCELLED",
    "CANCELLATION_REQUESTED",
    "MODIFICATION_REQUESTED",
    "COMPLETED",
]
_EXCHANGE = ["BSE", "NSE", "MCX", "MCXSX", "NCDEX", "US"]
_SEGMENT = ["CASH", "FNO", "CURRENCY", "COMMODITY"]
_PRODUCT = ["CNC", "MIS", "CO", "BO", "NRML", "ARB", "MTF"]
# The SDK renames MKT/L to MARKET/LIMIT (proto_parser.get_data_dict); SL and
# SL_M keep their names, as in the REST order_type.
_ORDER_TYPE = ["MARKET", "LIMIT", "SL", "SL_M"]
_BUY_SELL = ["BUY", "SELL"]

# OrderDetailUpdateDto field number -> (name, kind)
_ORDER_FIELDS = {
    1: ("qty", "int"),
    2: ("price", "int"),
    3: ("triggerPrice", "int"),
    4: ("filledQty", "int"),
    5: ("remainingQty", "int"),
    6: ("avgFillPrice", "int"),
    7: ("growwOrderId", "str"),
    8: ("exchangeOrderId", "str"),
    9: ("orderStatus", _ORDER_STATUS),
    10: ("duration", None),
    11: ("exchange", _EXCHANGE),
    12: ("segment", _SEGMENT),
    13: ("product", _PRODUCT),
    14: ("orderType", _ORDER_TYPE),
    15: ("transactionType", _BUY_SELL),
    16: ("remark", "str"),
    22: ("contractId", "str"),
}


class GrowwSocketTokenRefused(Exception):
    """Groww refused the socket-token request (the login token is dead)."""

    def __init__(self, status_code):
        super().__init__(f"Groww refused the socket token request ({status_code})")
        self.status_code = status_code


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _fields(data: bytes):
    """Yield (field_number, wire_type, value) for one protobuf message."""
    pos = 0
    while pos < len(data):
        key, pos = _read_varint(data, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _read_varint(data, pos)
        elif wire == 2:
            length, pos = _read_varint(data, pos)
            value, pos = data[pos : pos + length], pos + length
        elif wire == 1:
            value, pos = data[pos : pos + 8], pos + 8
        elif wire == 5:
            value, pos = data[pos : pos + 4], pos + 4
        else:
            raise ValueError(f"unsupported wire type {wire}")
        yield number, wire, value


def decode_order_update(payload: bytes) -> dict | None:
    """OrderDetailsBroadCastDto bytes -> the OrderDetailUpdateDto fields.

    Proto3 leaves zero values off the wire, so an absent enum is its first
    name (exchange BSE, segment CASH, status NEW, ...) and an absent number 0.
    """
    inner = None
    for number, wire, value in _fields(payload):
        if number == 2 and wire == 2:
            inner = value
    if inner is None:
        return None

    order: dict = {}
    for name, kind in _ORDER_FIELDS.values():
        if isinstance(kind, list):
            order[name] = kind[0]
        elif kind == "int":
            order[name] = 0
        elif kind == "str":
            order[name] = ""
    for number, wire, value in _fields(inner):
        spec = _ORDER_FIELDS.get(number)
        if spec is None or spec[1] is None:
            continue
        name, kind = spec
        if kind == "str" and wire == 2:
            order[name] = value.decode("utf-8", errors="replace")
        elif kind == "int" and wire == 0:
            order[name] = value - (1 << 64) if value >= 1 << 63 else value
        elif isinstance(kind, list) and wire == 0:
            order[name] = kind[value] if value < len(kind) else str(value)
    return order


class GrowwOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for Groww (NATS order subjects)."""

    def __init__(self, user_id: str, auth_token: str):
        super().__init__(broker_name="groww", user_id=user_id)
        self.auth_token = auth_token
        self._reset_connection_state()

    def _reset_connection_state(self) -> None:
        self.socket_token = None
        self.subscription_id = None
        self._nkey_seed = None
        self._buffer = b""
        self._connect_sent = False

    # -- connection ---------------------------------------------------------

    def _generate_socket_token(self) -> None:
        key_pair = groww_nkeys.generate_keypair()
        response = get_httpx_client().post(
            GROWW_SOCKET_TOKEN_URL,
            json={"socketKey": key_pair.public_key.decode("utf-8")},
            headers={
                "x-request-id": str(uuid.uuid4()),
                "Authorization": f"Bearer {self.auth_token}",
                "Content-Type": "application/json",
                "x-api-version": "1.0",
            },
            timeout=15,
        )
        if response.status_code in (401, 403):
            raise GrowwSocketTokenRefused(response.status_code)
        response.raise_for_status()
        body = response.json()
        if not body.get("token") or not body.get("subscriptionId"):
            raise ValueError("Groww socket token response has no token or subscriptionId")
        self.socket_token = body["token"]
        self.subscription_id = body["subscriptionId"]
        self._nkey_seed = key_pair.seed

    def get_ws_url(self) -> str:
        # A fresh socket token and parser state for every (re)connect.
        self._reset_connection_state()
        self._generate_socket_token()
        return GROWW_FEED_URL

    def get_headers(self):
        return {
            "Authorization": f"Bearer {self.socket_token}",
            "X-Subscription-Id": self.subscription_id,
            "Sec-WebSocket-Protocol": "nats",
        }

    def _send_handshake(self, ws, nonce: str | None) -> None:
        nkey = sig = None
        if nonce:
            key_pair = groww_nkeys.from_seed(self._nkey_seed)
            nkey = key_pair.public_key.decode("utf-8")
            sig = base64.b64encode(key_pair.sign(nonce.encode())).decode("utf-8")
        # The same CONNECT the market-data feed sends (identifies as nats.py,
        # as the official SDK does).
        commands = [NATSProtocol().create_connect(jwt=self.socket_token, nkey=nkey, sig=sig)]
        for sid, prefix in enumerate((EQUITY_ORDER_SUBJECT, FNO_ORDER_SUBJECT), start=1):
            commands.append(f"SUB {prefix}{self.subscription_id} {sid}\r\n")
        commands.append("PING\r\n")
        ws.send("".join(commands))

    def _split_frames(self, data: bytes) -> list[bytes]:
        """Consume NATS protocol lines; answer INFO and PING; return MSG payloads."""
        self._buffer += data
        payloads = []
        while True:
            line_end = self._buffer.find(b"\r\n")
            if line_end == -1:
                return payloads
            line = self._buffer[:line_end]
            op = line.split(b" ", 1)[0].upper()
            if op in (b"MSG", b"HMSG"):
                # MSG <subject> <sid> [reply-to] <#bytes>
                # HMSG <subject> <sid> [reply-to] <#header bytes> <#total bytes>
                parts = line.split()
                size = int(parts[-1])
                headers = int(parts[-2]) if op == b"HMSG" else 0
                end = line_end + 2 + size
                if len(self._buffer) < end + 2:
                    return payloads  # payload still arriving
                payloads.append(self._buffer[line_end + 2 + headers : end])
                self._buffer = self._buffer[end + 2 :]
                continue
            self._buffer = self._buffer[line_end + 2 :]
            ws = self._ws
            if op == b"INFO":
                # Only the first INFO is the handshake; answering the one the
                # server sends after CONNECT gets the connection refused.
                if not self._connect_sent and ws is not None:
                    self._connect_sent = True
                    try:
                        info = json.loads(line[4:].strip() or b"{}")
                    except json.JSONDecodeError:
                        info = {}
                    self._send_handshake(ws, info.get("nonce"))
            elif op == b"PING" and ws is not None:
                ws.send("PONG\r\n")
            elif op == b"-ERR":
                self.logger.warning(
                    f"Groww order feed error ({self.user_id}): {line[4:].decode(errors='replace').strip()}"
                )

    # -- messages -----------------------------------------------------------

    def _order_detail(self, groww_order_id: str, segment: str) -> dict | None:
        """The order as GET /v1/order/detail returns it, or None."""
        try:
            response = groww_request(
                get_httpx_client(),
                "GET",
                f"{GROWW_ORDER_DETAIL_URL}{groww_order_id}",
                "non_trading",
                params={"segment": segment},
                headers={
                    "Authorization": f"Bearer {self.auth_token}",
                    "Accept": "application/json",
                    "X-API-VERSION": "1.0",
                },
                timeout=10,
            )
            body = response.json()
        except Exception as e:
            self.logger.debug(f"Groww order detail read failed for {groww_order_id}: {e}")
            return None
        if (
            response.status_code != 200
            or not isinstance(body, dict)
            or body.get("status") != "SUCCESS"
        ):
            return None
        payload = body.get("payload")
        return payload if isinstance(payload, dict) else None

    def _fields_from(self, push: dict, detail: dict | None) -> dict:
        order_status = map_order_status(push.get("orderStatus"))
        common = {
            "orderid": push["growwOrderId"],
            "order_status": order_status,
            "quantity": int(push.get("qty") or 0),
            "filled_quantity": int(push.get("filledQty") or 0),
            "pending_quantity": int(push.get("remainingQty") or 0),
            "rejection_reason": (push.get("remark") or "") if order_status == "rejected" else "",
        }
        if detail:
            # As direct_get_order_book and map_order_data map an orderbook row.
            exchange = openalgo_exchange(detail.get("exchange", ""), detail.get("segment", ""))
            trading_symbol = detail.get("trading_symbol", "")
            order_type = detail.get("order_type", "")
            return {
                **common,
                "symbol": get_oa_symbol(trading_symbol, exchange) or trading_symbol,
                "exchange": exchange,
                "action": detail.get("transaction_type", ""),
                "price": float(detail.get("price") or 0),
                "trigger_price": float(detail.get("trigger_price") or 0),
                "pricetype": GROWW_PRICETYPE_MAP.get(order_type, order_type),
                "product": detail.get("product", ""),
                "average_price": float(detail.get("average_fill_price") or 0),
            }
        exchange = openalgo_exchange(push.get("exchange", ""), push.get("segment", ""))
        order_type = push.get("orderType", "")
        return {
            **common,
            "symbol": to_openalgo_symbol(push.get("contractId", ""), exchange),
            "exchange": exchange,
            "action": push.get("transactionType", ""),
            "price": float(push.get("price") or 0),
            "trigger_price": float(push.get("triggerPrice") or 0),
            "pricetype": GROWW_PRICETYPE_MAP.get(order_type, order_type),
            "product": push.get("product", ""),
            "average_price": float(push.get("avgFillPrice") or 0),
        }

    def normalize(self, raw_message):
        """One decoded order-update payload (MSG body) -> OrderUpdateEvent kwargs."""
        if not isinstance(raw_message, (bytes, bytearray)):
            return None
        push = decode_order_update(bytes(raw_message))
        if not push or not push.get("growwOrderId"):
            return None
        detail = self._order_detail(push["growwOrderId"], push.get("segment", ""))
        return self._fields_from(push, detail)

    def _handle_message(self, raw_message) -> None:
        # Frames carry NATS protocol text; only MSG bodies are order updates.
        if isinstance(raw_message, str):
            raw_message = raw_message.encode("utf-8")
        try:
            payloads = self._split_frames(bytes(raw_message))
        except Exception as e:
            self._buffer = b""
            self.logger.debug(f"Unreadable Groww order feed frame: {e}")
            return
        for payload in payloads:
            super()._handle_message(payload)


def create_groww_order_adapter(user_id: str) -> "GrowwOrderUpdateAdapter | None":
    """Build a GrowwOrderUpdateAdapter for user_id, or None without a session.

    The stored auth token is Groww's access token, sent as a Bearer token on
    the socket-token and order-detail requests (as api/order_api.py does).
    """
    auth_token = get_auth_token(user_id, bypass_cache=True)
    if not auth_token:
        logger.warning(
            f"No Groww auth token found for user {user_id}; order-update adapter not started"
        )
        return None
    return GrowwOrderUpdateAdapter(user_id=user_id, auth_token=auth_token)
