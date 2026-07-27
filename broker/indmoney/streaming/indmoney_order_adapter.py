"""
IndMoney (INDstocks) order-update adapter — dedicated order-update WebSocket.

Docs: broker-api-docs/indstocks-api-docs/08-websockets.md ("Order Updates").
Endpoint: wss://ws-order-updates.indstocks.com/api/v1/ws/trades
Auth: raw access token in the Authorization header (no "Bearer" prefix, per
the INDstocks docs). Subscribe handshake (post-connect):
{"action": "subscribe", "mode": "order_updates"}.

The streamed payload is thin — order_id, order_status, filled_quantity,
remaining_quantity, average_price, timestamp. Symbol/exchange/action are not
included; those fields are left empty and consumers correlate by orderid.
Status normalization reuses broker/indmoney/mapping/order_data.py::
normalize_order_status (the repo's single source of truth for this broker,
incl. PARTIALLY FILLED variants).
"""

import json

from broker.indmoney.mapping.order_data import normalize_order_status
from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter

logger = get_logger(__name__)

INDMONEY_ORDER_UPDATE_WS_URL = "wss://ws-order-updates.indstocks.com/api/v1/ws/trades"


class IndmoneyOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Dedicated order-update WebSocket adapter for IndMoney/INDstocks."""

    def __init__(self, user_id: str, access_token: str):
        super().__init__(broker_name="indmoney", user_id=user_id)
        self.access_token = access_token

    def get_ws_url(self) -> str:
        return INDMONEY_ORDER_UPDATE_WS_URL

    def get_headers(self):
        # Raw token, no "Bearer" prefix — per INDstocks WS docs.
        return {"Authorization": self.access_token}

    def on_open_extra(self, ws) -> None:
        ws.send(json.dumps({"action": "subscribe", "mode": "order_updates"}))
        self.logger.info("Sent IndMoney order_updates subscribe")

    def normalize(self, raw_message):
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        if data.get("type") != "order":
            return None  # subscription acks / other frame types

        # The stream uses underscore variants (e.g. PARTIALLY_EXECUTED) of the
        # REST status vocabulary (PARTIALLY FILLED ...) — normalize separators
        # before the shared status mapper.
        raw_status = str(data.get("order_status", "")).replace("_", " ")
        order_status = normalize_order_status(raw_status)

        filled = int(data.get("filled_quantity") or 0)
        remaining = int(data.get("remaining_quantity") or 0)

        return {
            "orderid": str(data.get("order_id", "")),
            "order_status": order_status,
            "quantity": filled + remaining,
            "filled_quantity": filled,
            "pending_quantity": remaining,
            "average_price": float(data.get("average_price") or 0),
        }


def create_indmoney_order_adapter(user_id: str) -> "IndmoneyOrderUpdateAdapter | None":
    """Factory: build an IndmoneyOrderUpdateAdapter for user_id."""
    access_token = get_auth_token(user_id, bypass_cache=True)
    if not access_token:
        logger.warning(
            f"No IndMoney access token found for user {user_id}; order-update adapter not started"
        )
        return None

    return IndmoneyOrderUpdateAdapter(user_id=user_id, access_token=access_token)
