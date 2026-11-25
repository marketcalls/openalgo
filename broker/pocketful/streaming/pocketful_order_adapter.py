"""
Pocketful order-update adapter: order updates on a dedicated feed socket.

Sources. Pocketful's API documentation (offline copy of 2026-11-17, pages
"Connecting Websockets", "Order Updates", "Trade Updates", "Annexure", plus the
order book pages for the status vocabulary) and the official SDKs: Python
``pocketful`` 0.1.2 (``pocketfulwebsocket.py``, ``wsclient.py``,
``packetDecoder.py``) and pocketful-tech/pocketfulapi-javascript
(``PocketfulAPI/wsclient.js``, ``pocketfulwebsocket.js``, ``packetDecoder.js``).

Endpoint. The "Connecting Websockets" page names ``wss://algo.pocketful.in/api/v1/ws``
and leaves the authentication open ("include your access token in the
connection handshake or subsequent authentication message"). Both SDKs connect
to ``wss://algo.pocketful.in/ws/v1/feeds?login_id=<client_id>&access_token=<token>``
(Python ``wsclient.socket_connect``, JS ``socketConnect``), with the host taken
from the REST base URL by swapping https for wss. The SDKs are followed: they
are the code Pocketful ships and the only source that says how the token is
presented, and OpenAlgo's existing Pocketful feed already used that path. The
host comes from ``broker.pocketful.api.baseurl.BASE_URL`` the same way.

Subscription. Once the socket is open, ``subscribe_order_update`` sends
``{"a": "subscribe", "v": [<client_id>, "web"], "m": "updates"}``. The SDKs'
``subscribe_trade_update`` sends a message type (``TradeUpdateMessage``) that
their ``send_message`` has no branch for, so it sends nothing; the ``updates``
subscription is the only one either SDK can actually send. Unsubscribing order
updates also sends nothing in either SDK, so stopping is closing the socket.

Heartbeat. Both SDKs send ``{"a": "h", "v": [], "m": ""}`` every 8 seconds.

Frames. Updates arrive as frames whose first byte is a mode (Python
``struct.unpack('>b', message[0:1])``, JS ``readInt8(0)``): 50 is an order
update, 51 a trade update, 1, 2 and 4 are market data. The update decoders
read JSON from offset 5 (``json.loads(packet.decode("utf-8")[5:])``). The four
bytes after the mode are not documented and are not interpreted here. The
JSON is the ``{"error": {...}, "result": [<order>, ...]}`` document the "Order
Updates" page shows as the result of ``read_order_update_data``.

Trade updates (mode 51) are not published. An order update carries the
order's cumulative ``filled_quantity``, ``average_price``, ``remaining_quantity``
and ``order_status``, which is the state OpenAlgo's event describes. A trade
update carries one fill with no order status and no order quantity, so an
event built from it would have to invent the status, and the strategy book
would book its quantity as if it were the order's running total.

Threads. Everything here runs on the base class's adapter and heartbeat
threads, which are plain ``threading.Thread`` objects: green under eventlet,
real under gthread and the dev server, like every other order adapter. No
callback crosses to another thread; events go out through the in-process bus.

Credentials. The stored OpenAlgo token is ``<client_id>:::<access_token>``
(``baseurl.pack_token``); both parts come from it. The access token rides in
the URL query, so the URL is never logged.
"""

import json
import struct
from urllib.parse import urlencode

from broker.pocketful.api.baseurl import BASE_URL
from broker.pocketful.api.baseurl import access_token as stored_access_token
from broker.pocketful.api.baseurl import client_id as stored_client_id
from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

# https://algo.pocketful.in -> wss://algo.pocketful.in, as the SDKs derive it.
FEED_WS_URL = BASE_URL.replace("https://", "wss://", 1).rstrip("/") + "/ws/v1/feeds"

# Frame modes (first byte), from the SDKs' on_message.
ORDER_UPDATE_MODE = 50
TRADE_UPDATE_MODE = 51
# The update decoders read the JSON from this offset.
UPDATE_JSON_OFFSET = 5

HEARTBEAT_INTERVAL_SECONDS = 8
HEARTBEAT_MESSAGE = {"a": "h", "v": [], "m": ""}

# Pocketful order_status -> OpenAlgo's lowercase vocabulary. Every key but the
# last four is a value Pocketful's pages show:
#   COMPLETE, REJECTED, CANCELLED, PENDING  order-book.md "Understanding Order
#                                           Statuses" (PENDING: "still open")
#   CONFIRMED                               trade-book.md
#   MODCONFIRMED                            order-updates.md
#   MODIFY_CONFIRMED                        cancel-bracket-order.md
#   AMO_REQ_RECEIVED, AMO_MODIFY_CONFIRMED  fetch-pending-orders.md
#   AMO_CANCEL_CONFIRMED                    fetch-completed-orders.md
# The last four are spellings OpenAlgo's Pocketful order book mapping already
# recognised (broker/pocketful/mapping/order_data.py before this rewrite).
# Anything else passes through lowercased, never forced into a bucket: a
# "PARTIALLY_FILLED" still reaches the strategy book as a partial fill, and an
# unknown terminal-sounding state is never reported as a fill or a cancel.
_STATUS_MAP = {
    "COMPLETE": "complete",
    "REJECTED": "rejected",
    "CANCELLED": "cancelled",
    "PENDING": "open",
    "CONFIRMED": "open",
    "MODCONFIRMED": "open",
    "MODIFY_CONFIRMED": "open",
    "AMO_REQ_RECEIVED": "open",
    "AMO_MODIFY_CONFIRMED": "open",
    "AMO_CANCEL_CONFIRMED": "cancelled",
    "OPEN": "open",
    "TRIGGER PENDING": "trigger pending",
    "TRIGGER_PENDING": "trigger pending",
    "CANCEL_CONFIRMED": "cancelled",
}

# order_type -> OpenAlgo pricetype. LIMIT and SL are the API's order types
# (place-regular-order.md); SLM is how Pocketful spells stop loss market
# (place-regular-order.md "trigger_price", fetch-completed-orders.md
# "order_type"); MARKET and SL-M are the annexure's names for the two types
# an order placed outside the API can still carry.
_PRICETYPE_MAP = {
    "LIMIT": "LIMIT",
    "MARKET": "MARKET",
    "SL": "SL",
    "SLM": "SL-M",
    "SL-M": "SL-M",
}

# product -> OpenAlgo product. CNC, MIS and NRML are the documented order
# values (place-regular-order.md); INTRADAY and MARGIN are the annexure's
# product names ("Intraday for Equity, Futures & Options", "Carry Forward in
# Futures & Options"). CO and BO pass through: OpenAlgo has no product for them.
_PRODUCT_MAP = {
    "CNC": "CNC",
    "MIS": "MIS",
    "NRML": "NRML",
    "INTRADAY": "MIS",
    "MARGIN": "NRML",
}


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _int(value) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def map_order_status(raw_status) -> str:
    """A Pocketful order_status in OpenAlgo's lowercase vocabulary."""
    key = _text(raw_status).upper()
    return _STATUS_MAP.get(key) or key.lower() or "open"


def decode_frame(raw_message):
    """(mode, decoded JSON) for an update frame, or (mode, None) for any other frame.

    Returns (None, None) for an empty frame. Text frames are read as their
    UTF-8 bytes, as the JavaScript SDK reads every frame (``Buffer.from``).
    The JSON is cut from the bytes, not from the decoded text as the SDKs do:
    the two agree whenever the four header bytes are ASCII, and slicing bytes
    still works if they are not, where decoding the whole frame would fail.
    """
    if isinstance(raw_message, str):
        raw_message = raw_message.encode("utf-8")
    if not isinstance(raw_message, (bytes, bytearray)) or not raw_message:
        return None, None
    mode = struct.unpack(">b", bytes(raw_message[0:1]))[0]
    if mode not in (ORDER_UPDATE_MODE, TRADE_UPDATE_MODE):
        return mode, None
    body = bytes(raw_message[UPDATE_JSON_OFFSET:])
    return mode, json.loads(body.decode("utf-8"))


def order_records(payload) -> list[dict]:
    """The order dicts inside a decoded order-update document.

    The documented shape is ``{"error": {...}, "result": [<order>, ...]}``. A
    bare order object (one carrying ``oms_order_id``) or a list of them is
    accepted too, so a server that drops the envelope still gets through.
    """
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    if "result" in payload:
        result = payload.get("result")
        if isinstance(result, dict):
            return [result]
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        return []
    if "oms_order_id" in payload:
        return [payload]
    return []


class PocketfulOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for Pocketful (the SDKs' feed socket, ``updates`` channel)."""

    def __init__(self, user_id: str, client_id: str, access_token: str):
        super().__init__(broker_name="pocketful", user_id=user_id)
        self.client_id = client_id
        self.access_token = access_token

    # -- connection ------------------------------------------------------

    def get_ws_url(self) -> str:
        query = urlencode({"login_id": self.client_id, "access_token": self.access_token})
        return f"{FEED_WS_URL}?{query}"

    def get_headers(self):
        return None  # the SDKs authenticate in the URL query only

    def on_open_extra(self, ws) -> None:
        ws.send(json.dumps({"a": "subscribe", "v": [self.client_id, "web"], "m": "updates"}))
        self.logger.info(f"Subscribed to Pocketful order updates for client {self.client_id}")

    def heartbeat_interval(self):
        return HEARTBEAT_INTERVAL_SECONDS

    def send_heartbeat(self, ws) -> None:
        ws.send(json.dumps(HEARTBEAT_MESSAGE))

    # -- message handling ------------------------------------------------

    def _handle_message(self, raw_message) -> None:
        """Publish one event per order in an order-update frame.

        The base class publishes one event per frame, and Pocketful's frame
        carries a ``result`` list, so every order after the first would be
        dropped without this.
        """
        try:
            mode, payload = decode_frame(raw_message)
        except Exception:
            self.logger.exception(
                f"Could not read a Pocketful order update frame ({len(raw_message)} bytes)"
            )
            return
        if mode == TRADE_UPDATE_MODE:
            self.logger.debug("Pocketful trade update skipped; its order update carries the fill")
            return
        if mode != ORDER_UPDATE_MODE:
            return  # market data, or a frame this adapter does not use

        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and _int(error.get("code")):
            self.logger.warning(
                f"Pocketful order update reported error {error.get('code')}: "
                f"{_text(error.get('message'))}"
            )

        for record in order_records(payload):
            try:
                fields = self.normalize(record)
            except Exception:
                self.logger.exception(
                    f"Could not map Pocketful order update for order {record.get('oms_order_id')}"
                )
                continue
            if fields:
                self._publish_event_fields(fields)

    def normalize(self, raw_message):
        """One order dict from an order-update ``result`` list -> OrderUpdateEvent kwargs.

        ``_handle_message`` decodes the frame and splits the list; anything
        that is not one order dict with an ``oms_order_id`` returns None.
        """
        record = raw_message
        if not isinstance(record, dict):
            return None

        # oms_order_id is the id place order returns (place-regular-order.md)
        # and the one cancel, modify and order history take.
        orderid = _text(record.get("oms_order_id"))
        if not orderid:
            return None

        exchange = _text(record.get("exchange")).upper()
        token = _text(record.get("instrument_token"))
        symbol = to_openalgo_symbol(
            _text(record.get("trading_symbol")), exchange, token=token or None
        )

        order_status = map_order_status(record.get("order_status"))
        quantity = _int(record.get("quantity"))
        filled_quantity = _int(record.get("filled_quantity"))
        remaining = record.get("remaining_quantity")
        if remaining is None or _text(remaining) == "":
            pending_quantity = max(quantity - filled_quantity, 0)
        else:
            pending_quantity = _int(remaining)

        order_type = _text(record.get("order_type")).upper()
        product = _text(record.get("product")).upper()

        # The page's example shows "NONE" in rejection_reason on a live order.
        reason = _text(record.get("rejection_reason"))
        if order_status != "rejected" or reason.upper() == "NONE":
            reason = ""

        return {
            "orderid": orderid,
            "symbol": symbol,
            "exchange": exchange,
            "action": _text(record.get("order_side")).upper(),
            "quantity": quantity,
            "price": _float(record.get("price")),
            "trigger_price": _float(record.get("trigger_price")),
            "pricetype": _PRICETYPE_MAP.get(order_type, order_type),
            "product": _PRODUCT_MAP.get(product, product),
            "order_status": order_status,
            "filled_quantity": filled_quantity,
            "pending_quantity": pending_quantity,
            "average_price": _float(record.get("average_price"))
            or _float(record.get("average_trade_price")),
            "rejection_reason": reason,
        }


def create_pocketful_order_adapter(user_id: str) -> "PocketfulOrderUpdateAdapter | None":
    """Build the adapter from the stored ``<client_id>:::<access_token>`` token."""
    auth_token = get_auth_token(user_id, bypass_cache=True)
    if not auth_token:
        logger.warning(f"No Pocketful session found for user {user_id}; order updates not started")
        return None

    bare_token = stored_access_token(auth_token)
    login_id = stored_client_id(auth_token)
    if not bare_token or not login_id:
        logger.warning(
            f"The Pocketful session for user {user_id} has no client id; order updates not started"
        )
        return None

    return PocketfulOrderUpdateAdapter(user_id=user_id, client_id=login_id, access_token=bare_token)
