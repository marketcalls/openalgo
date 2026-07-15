"""
Arrow order-update adapter — dedicated WebSocket Order Updates stream.

Docs: broker-api-docs/arrow-api-docs/12-order-data.md (+ SDK notes in
23-python-sdk-websocket-streaming.md).
Endpoint: wss://order-updates.arrow.trade?appID=<appID>&token=<token>
Auth: query params — appID is the application id (BROKER_API_KEY env, same
convention as broker/arrow/api/baseurl.py) and token is the user JWT access
token from the DB.
Liveness: Arrow's protocol expects the CLIENT to send a text "PONG" every
~3 seconds; ~5s of read silence means a stale connection (their SDK
defaults). Handled via the heartbeat hooks below.

Messages are JSON text; order events carry updateType "ORDER_UPDATE" and an
"id" field. All numeric fields arrive as strings.
"""

import json
import os

from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

ARROW_ORDER_UPDATE_WS_URL = "wss://order-updates.arrow.trade"
ARROW_HEARTBEAT_INTERVAL_SECONDS = 3

# Arrow orderStatus values -> OpenAlgo's lowercase order_status vocabulary.
_STATUS_MAP = {
    "PENDING": "open",
    "OPEN": "open",
    "COMPLETE": "complete",
    "CANCELLED": "cancelled",
    "REJECTED": "rejected",
    "TRIGGER_PENDING": "open",
    "AFTER_MARKET_ORDER_REQ_RECEIVED": "open",
}

# Arrow "order" (order type) codes -> OpenAlgo pricetype constants
_PRICETYPE_MAP = {"LMT": "LIMIT", "MKT": "MARKET", "SL": "SL", "SL-M": "SL-M"}

# Arrow product codes -> OpenAlgo product constants
# (per 12-order-data.md: M = Margin/intraday, C = Cash/delivery, I = Intraday)
_PRODUCT_MAP = {"M": "MIS", "C": "CNC", "I": "MIS"}

_ACTION_MAP = {"B": "BUY", "S": "SELL"}


def _num(value, cast=float, default=0):
    """Parse Arrow's string-typed numeric fields safely."""
    try:
        return cast(float(value))
    except (TypeError, ValueError):
        return default


class ArrowOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Dedicated order-update WebSocket adapter for Arrow."""

    def __init__(self, user_id: str, app_id: str, access_token: str):
        super().__init__(broker_name="arrow", user_id=user_id)
        self.app_id = app_id
        self.access_token = access_token

    def get_ws_url(self) -> str:
        return f"{ARROW_ORDER_UPDATE_WS_URL}?appID={self.app_id}&token={self.access_token}"

    def get_headers(self):
        return None  # auth is in the URL query params

    def heartbeat_interval(self):
        return ARROW_HEARTBEAT_INTERVAL_SECONDS

    def send_heartbeat(self, ws) -> None:
        ws.send("PONG")  # Arrow expects a client-side text PONG cadence

    def normalize(self, raw_message):
        if isinstance(raw_message, (bytes, bytearray)):
            return None

        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None  # PING/acks or other non-JSON text frames

        if not isinstance(data, dict) or not data.get("id"):
            return None
        if data.get("updateType") not in (None, "ORDER_UPDATE"):
            return None

        raw_status = str(data.get("orderStatus", "")).upper()
        order_status = _STATUS_MAP.get(raw_status, raw_status.lower() or "open")

        quantity = _num(data.get("quantity"), int)
        filled = _num(data.get("cumulativeFillQty"), int)
        leaves = _num(data.get("leavesQuantity"), int, default=max(quantity - filled, 0))

        # Symbol -> OpenAlgo format (get_oa_symbol on Arrow's brsymbol, with
        # the instrument token as an extra key), same as the REST mapping.
        exchange = data.get("exchange", "")
        symbol = to_openalgo_symbol(
            data.get("symbol", ""), exchange, token=data.get("token")
        )

        return {
            "orderid": str(data.get("id", "")),
            "symbol": symbol,
            "exchange": exchange,
            "action": _ACTION_MAP.get(data.get("transactionType", ""), data.get("transactionType", "")),
            "quantity": quantity,
            "price": _num(data.get("price")),
            "trigger_price": _num(data.get("orderTriggerPrice")),
            "pricetype": _PRICETYPE_MAP.get(data.get("order", ""), data.get("order", "")),
            "product": _PRODUCT_MAP.get(data.get("product", ""), data.get("product", "")),
            "order_status": order_status,
            "filled_quantity": filled,
            "pending_quantity": leaves,
            "average_price": _num(data.get("averagePrice")),
            "rejection_reason": data.get("rejectionReason", "") if order_status == "rejected" else "",
        }


def create_arrow_order_adapter(user_id: str) -> "ArrowOrderUpdateAdapter | None":
    """Factory: build an ArrowOrderUpdateAdapter for user_id."""
    app_id = os.getenv("BROKER_API_KEY")
    if not app_id:
        logger.warning("BROKER_API_KEY (Arrow appID) not set; order-update adapter not started")
        return None

    access_token = get_auth_token(user_id, bypass_cache=True)
    if not access_token:
        logger.warning(f"No Arrow access token found for user {user_id}; order-update adapter not started")
        return None

    return ArrowOrderUpdateAdapter(user_id=user_id, app_id=app_id, access_token=access_token)
