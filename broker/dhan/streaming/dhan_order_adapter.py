"""
Dhan order-update adapter — dedicated Live Order Update WebSocket.

Docs: broker-api-docs/dhan-api-docs/13-live-order-update.md
Endpoint: wss://api-order-update.dhan.co
Auth: JSON LoginReq message sent after connect (not a header), per the
"For Individual" flow — {"LoginReq": {"MsgCode": 42, "ClientId": ..., "Token": ...}, "UserType": "SELF"}.
"""

import json

from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter

logger = get_logger(__name__)

DHAN_ORDER_UPDATE_WS_URL = "wss://api-order-update.dhan.co"

# Live Order Update "Status" values -> OpenAlgo's lowercase order_status
# vocabulary (open/complete/rejected/cancelled). TRANSIT/EXPIRED have no
# exact OpenAlgo equivalent; TRANSIT is treated as still-open (in flight to
# the exchange) and EXPIRED is passed through verbatim (lowercased) rather
# than forced into a misleading bucket.
_STATUS_MAP = {
    "TRANSIT": "open",
    "PENDING": "open",
    "REJECTED": "rejected",
    "CANCELLED": "cancelled",
    "TRADED": "complete",
    "EXPIRED": "expired",
}

# Live Order Update "Product" single-letter codes -> OpenAlgo product constants
_PRODUCT_MAP = {
    "C": "CNC",
    "I": "MIS",
    "M": "NRML",  # MARGIN — closest OpenAlgo equivalent
    "F": "NRML",  # MTF — closest OpenAlgo equivalent
}

# Live Order Update "OrderType" codes -> OpenAlgo pricetype constants
_PRICETYPE_MAP = {
    "LMT": "LIMIT",
    "MKT": "MARKET",
    "SL": "SL",
    "SLM": "SL-M",
}

# Live Order Update "TxnType" codes -> OpenAlgo action constants
_ACTION_MAP = {"B": "BUY", "S": "SELL"}


class DhanOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Dedicated order-update WebSocket adapter for Dhan (individual-user flow)."""

    def __init__(self, user_id: str, client_id: str, access_token: str):
        super().__init__(broker_name="dhan", user_id=user_id)
        self.client_id = client_id
        self.access_token = access_token

    def get_ws_url(self) -> str:
        return DHAN_ORDER_UPDATE_WS_URL

    def get_headers(self):
        return None  # auth is sent as a message, not a header

    def on_open_extra(self, ws) -> None:
        login_msg = {
            "LoginReq": {
                "MsgCode": 42,
                "ClientId": self.client_id,
                "Token": self.access_token,
            },
            "UserType": "SELF",
        }
        ws.send(json.dumps(login_msg))
        self.logger.info(f"Sent Dhan order-update LoginReq for client {self.client_id}")

    def normalize(self, raw_message):
        try:
            message = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        if message.get("Type") != "order_alert":
            return None  # ignore login-ack / other frame types

        data = message.get("Data") or {}
        raw_status = str(data.get("Status", "")).upper()
        order_status = _STATUS_MAP.get(raw_status, raw_status.lower())

        quantity = int(data.get("Quantity") or 0)
        traded_qty = int(data.get("TradedQty") or 0)

        return {
            "orderid": data.get("OrderNo", ""),
            "symbol": data.get("Symbol", ""),
            "exchange": data.get("Exchange", ""),
            "action": _ACTION_MAP.get(data.get("TxnType", ""), data.get("TxnType", "")),
            "quantity": quantity,
            "price": float(data.get("Price") or 0),
            "trigger_price": float(data.get("TriggerPrice") or 0),
            "pricetype": _PRICETYPE_MAP.get(data.get("OrderType", ""), data.get("OrderType", "")),
            "product": _PRODUCT_MAP.get(data.get("Product", ""), data.get("Product", "")),
            "order_status": order_status,
            "filled_quantity": traded_qty,
            "pending_quantity": max(quantity - traded_qty, 0),
            "average_price": float(data.get("AvgTradedPrice") or 0),
            "rejection_reason": data.get("ReasonDescription", "") if raw_status == "REJECTED" else "",
        }


def create_dhan_order_adapter(user_id: str) -> "DhanOrderUpdateAdapter | None":
    """
    Factory: build a DhanOrderUpdateAdapter for user_id using the same
    credential resolution as broker/dhan/streaming/dhan_adapter.py
    (BROKER_API_KEY client_id + DB access token). Returns None if
    credentials cannot be resolved.
    """
    import os

    from dotenv import load_dotenv

    load_dotenv()

    broker_api_key = os.getenv("BROKER_API_KEY")
    if broker_api_key and ":::" in broker_api_key:
        client_id = broker_api_key.split(":::")[0]
    else:
        client_id = broker_api_key or user_id

    access_token = get_auth_token(user_id, bypass_cache=True)
    if not access_token:
        logger.warning(f"No Dhan access token found for user {user_id}; order-update adapter not started")
        return None

    return DhanOrderUpdateAdapter(user_id=user_id, client_id=client_id, access_token=access_token)
