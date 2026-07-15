"""
Angel One order-update adapter — dedicated Websocket Order Status stream.

Docs: broker-api-docs/angelone-api-docs/11-websocket-order-status.md.
Endpoint: wss://tns.angelone.in/smart-order-update
Auth: "Authorization: Bearer <jwt auth token>" handshake header.
Liveness: Angel's docs require a ~10s ping/pong cadence (ws_ping_interval
override below); connection limit is 3 per client code.

Message shape: {"user-id", "status-code", "order-status": "AB01", ...,
"orderData": {...}} where order-status codes map to order lifecycle states
and orderData mirrors the REST/postback payload (ordertype, producttype,
tradingsymbol, filledshares, unfilledshares, ...). AB00 is the post-connect
acknowledgement frame (empty orderData) and is ignored.
"""

import json

from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

ANGEL_ORDER_UPDATE_WS_URL = "wss://tns.angelone.in/smart-order-update"

# "order-status" codes (11-websocket-order-status.md) -> OpenAlgo's lowercase
# order_status vocabulary. Modify/AMO/pending variants are all still-working
# orders -> "open".
_STATUS_CODE_MAP = {
    "AB01": "open",
    "AB02": "cancelled",
    "AB03": "rejected",
    "AB04": "open",  # modified
    "AB05": "complete",
    "AB06": "open",  # after-market order req received
    "AB07": "cancelled",  # cancelled after market order
    "AB08": "open",  # modify AMO req received
    "AB09": "open",  # open pending
    "AB10": "open",  # trigger pending
    "AB11": "open",  # modify pending
}

# Fallback when the code is missing: orderData.orderstatus free text.
_STATUS_TEXT_MAP = {
    "open": "open",
    "pending": "open",
    "open pending": "open",
    "trigger pending": "open",
    "modified": "open",
    "modify pending": "open",
    "executed": "complete",
    "complete": "complete",
    "rejected": "rejected",
    "cancelled": "cancelled",
}

# Mirrors broker/angel/mapping/order_data.py's REST transforms.
_PRODUCT_MAP = {"DELIVERY": "CNC", "INTRADAY": "MIS", "CARRYFORWARD": "NRML"}
_PRICETYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "STOPLOSS_LIMIT": "SL",
    "STOPLOSS_MARKET": "SL-M",
}


class AngelOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Dedicated order-update WebSocket adapter for Angel One (SmartAPI)."""

    def __init__(self, user_id: str, auth_token: str):
        super().__init__(broker_name="angel", user_id=user_id)
        self.auth_token = auth_token

    def get_ws_url(self) -> str:
        return ANGEL_ORDER_UPDATE_WS_URL

    def get_headers(self):
        return {"Authorization": f"Bearer {self.auth_token}"}

    def ws_ping_interval(self) -> int:
        return 9  # Angel's docs require a ~10s ping/pong liveness cadence

    def normalize(self, raw_message):
        try:
            message = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        status_code = str(message.get("order-status", "")).upper()
        data = message.get("orderData") or {}

        if status_code == "AB00" or not data.get("orderid"):
            return None  # connection ack / empty frame

        if status_code in _STATUS_CODE_MAP:
            order_status = _STATUS_CODE_MAP[status_code]
        else:
            raw_text = str(data.get("orderstatus") or data.get("status") or "").strip().lower()
            order_status = _STATUS_TEXT_MAP.get(raw_text, raw_text or "open")

        filled = int(float(data.get("filledshares") or 0))
        unfilled = int(float(data.get("unfilledshares") or 0))
        quantity = int(float(data.get("quantity") or 0)) or (filled + unfilled)

        # Symbol -> OpenAlgo format via the instrument token (same lookup the
        # REST orderbook mapping uses), falling back to the trading symbol.
        exchange = data.get("exchange", "")
        symbol = to_openalgo_symbol(
            data.get("tradingsymbol", ""), exchange, token=data.get("symboltoken")
        )

        return {
            "orderid": str(data.get("orderid", "")),
            "symbol": symbol,
            "exchange": exchange,
            "action": str(data.get("transactiontype", "")).upper(),
            "quantity": quantity,
            "price": float(data.get("price") or 0),
            "trigger_price": float(data.get("triggerprice") or 0),
            "pricetype": _PRICETYPE_MAP.get(data.get("ordertype", ""), data.get("ordertype", "")),
            "product": _PRODUCT_MAP.get(data.get("producttype", ""), data.get("producttype", "")),
            "order_status": order_status,
            "filled_quantity": filled,
            "pending_quantity": unfilled,
            "average_price": float(data.get("averageprice") or 0),
            "rejection_reason": data.get("text", "") if order_status == "rejected" else "",
        }


def create_angel_order_adapter(user_id: str) -> "AngelOrderUpdateAdapter | None":
    """Factory: build an AngelOrderUpdateAdapter for user_id."""
    auth_token = get_auth_token(user_id, bypass_cache=True)
    if not auth_token:
        logger.warning(f"No Angel auth token found for user {user_id}; order-update adapter not started")
        return None

    return AngelOrderUpdateAdapter(user_id=user_id, auth_token=auth_token)
