"""
Zerodha order-update adapter — order postbacks on a Kite ticker connection.

Docs: broker-api-docs/zerodha-api-docs/10-websocket.md ("Text Messages") and
12-postbacks.md (payload shape — the ticker's {"type":"order"} text frames
carry the same fields as the HTTPS postback).
Endpoint: wss://ws.kite.trade?api_key=<api_key>&access_token=<access_token>

Kite allows up to 3 concurrent ticker connections per API key; this adapter
opens a dedicated one and never subscribes to any instrument, so every
incoming *binary* frame (market data / 1-byte heartbeats) is ignored — only
JSON *text* frames are decoded. Order postbacks arrive on the ticker without
any explicit subscription.

Credentials: OpenAlgo stores Zerodha's DB auth token as the composite
"api_key:access_token" string (see broker/zerodha/streaming/
zerodha_websocket.py::_refresh_access_token, which splits on ":").
"""

import json

from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

# Kite order "status" values -> OpenAlgo's lowercase order_status vocabulary.
# The in-flight OMS states (PUT ORDER REQ RECEIVED, VALIDATION PENDING,
# OPEN PENDING, MODIFY..., TRIGGER PENDING) are all still-working -> "open".
_STATUS_MAP = {
    "COMPLETE": "complete",
    "REJECTED": "rejected",
    "CANCELLED": "cancelled",
    "OPEN": "open",
    "UPDATE": "open",
    "TRIGGER PENDING": "trigger pending",
    "VALIDATION PENDING": "open",
    "PUT ORDER REQ RECEIVED": "open",
    "OPEN PENDING": "open",
    "MODIFY VALIDATION PENDING": "open",
    "MODIFY PENDING": "open",
    "CANCEL PENDING": "open",
    "AMO REQ RECEIVED": "open",
}


class ZerodhaOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for Zerodha (Kite ticker text frames)."""

    def __init__(self, user_id: str, api_key: str, access_token: str):
        super().__init__(broker_name="zerodha", user_id=user_id)
        self.api_key = api_key
        self.access_token = access_token

    def get_ws_url(self) -> str:
        return (
            f"wss://ws.kite.trade?api_key={self.api_key}"
            f"&access_token={self.access_token}"
        )

    def get_headers(self):
        return None  # auth is in the URL query params

    def normalize(self, raw_message):
        if isinstance(raw_message, (bytes, bytearray)):
            return None  # binary market-data / heartbeat frames

        try:
            message = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        if message.get("type") != "order":
            return None  # "message"/"error" broker notices — not order events

        data = message.get("data") or {}
        raw_status = str(data.get("status", "")).upper()
        order_status = _STATUS_MAP.get(raw_status, raw_status.lower() or "open")

        # Kite's order_type (MARKET/LIMIT/SL/SL-M) and product (CNC/NRML/MIS)
        # already match OpenAlgo's constants — no mapping tables needed.
        # Symbol is mapped to OpenAlgo format the same way the REST orderbook
        # mapping does (get_oa_symbol on Kite's tradingsymbol).
        exchange = data.get("exchange", "")
        symbol = to_openalgo_symbol(data.get("tradingsymbol", ""), exchange)

        return {
            "orderid": str(data.get("order_id", "")),
            "symbol": symbol,
            "exchange": exchange,
            "action": str(data.get("transaction_type", "")).upper(),
            "quantity": int(data.get("quantity") or 0),
            "price": float(data.get("price") or 0),
            "trigger_price": float(data.get("trigger_price") or 0),
            "pricetype": data.get("order_type", ""),
            "product": data.get("product", ""),
            "order_status": order_status,
            "filled_quantity": int(data.get("filled_quantity") or 0),
            "pending_quantity": int(
                data.get("pending_quantity") or data.get("unfilled_quantity") or 0
            ),
            "average_price": float(data.get("average_price") or 0),
            "rejection_reason": data.get("status_message") or "" if order_status == "rejected" else "",
        }


def create_zerodha_order_adapter(user_id: str) -> "ZerodhaOrderUpdateAdapter | None":
    """
    Factory: build a ZerodhaOrderUpdateAdapter for user_id. The stored DB
    token is the composite "api_key:access_token"; both halves are needed for
    the ticker URL.
    """
    auth_token = get_auth_token(user_id, bypass_cache=True)
    if not auth_token:
        logger.warning(f"No Zerodha auth token found for user {user_id}; order-update adapter not started")
        return None

    if ":" in auth_token:
        api_key, access_token = auth_token.split(":", 1)
    else:
        import os

        api_key = os.getenv("BROKER_API_KEY", "")
        access_token = auth_token

    if not api_key or not access_token:
        logger.warning(f"Incomplete Zerodha credentials for user {user_id}; order-update adapter not started")
        return None

    return ZerodhaOrderUpdateAdapter(user_id=user_id, api_key=api_key, access_token=access_token)
