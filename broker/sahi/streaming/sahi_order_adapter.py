"""
Sahi order-update adapter -- WSS /v1/stream/orders.

Docs: broker-api-docs/sahi-api-docs/02-api-reference.md, "WSS /v1/stream/orders
-- Order updates" and "WebSocket connections":

  - wss://direct.sahi.com/v1/stream/orders, authenticated by the same Bearer
    JWT as REST in the upgrade request's Authorization header. No login or
    subscribe frame: the server pushes as soon as the socket is open, scoped
    to the token's account.
  - Each frame is JSON text, one order object shaped exactly like an element
    of GET /v1/orders, so it goes through the order book's own mapping
    (broker/sahi/mapping/order_data.map_order_data): paise to rupees, Sahi
    codes to OpenAlgo ones, the same status map. The stream therefore always
    agrees with the order book.
  - The server pings every 30s and wants a pong within 15s; websocket-client
    answers pings itself.
  - 5 concurrent order-stream connections per account, counted separately
    from the tick stream, so this socket does not displace market data.
  - Close 4401 means the token expired. The reconnect then fails the upgrade
    with 401, and the base class stands the adapter down until the next
    broker login, which is the only way Sahi issues a new token.

Delivery may repeat an update after a restart on Sahi's side; the docs leave
deduplication to the consumer, as OpenAlgo's order-update docs do (orderid +
order_status + filled_quantity).

The CloudFront in front of Sahi refuses an upgrade without a User-Agent, so
the handshake names itself, as the tick stream does.
"""

import json

from broker.sahi.api.baseurl import USER_AGENT, WS_BASE_URL
from broker.sahi.mapping.order_data import map_order_data
from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter

logger = get_logger(__name__)

ORDER_STREAM_PATH = "/v1/stream/orders"


def normalize_order(row: dict) -> dict | None:
    """One GET /v1/orders-shaped object -> OrderUpdateEvent kwargs."""
    if not isinstance(row, dict) or not row.get("order_id"):
        return None
    mapped = map_order_data({"orders": [row]})
    if not mapped:
        return None
    order = mapped[0]
    quantity = order["quantity"]
    filled = order["filled_quantity"]
    status = order["order_status"]
    return {
        "orderid": order["orderid"],
        "symbol": order["symbol"],
        "exchange": order["exchange"],
        "action": order["action"],
        "quantity": quantity,
        "price": order["price"],
        "trigger_price": order["trigger_price"],
        "pricetype": order["pricetype"],
        "product": order["product"],
        "order_status": status,
        "filled_quantity": filled,
        # Only a working order has quantity left at the exchange; a cancelled,
        # rejected or completed one has none, whatever was unfilled.
        "pending_quantity": max(quantity - filled, 0)
        if status in ("open", "trigger pending")
        else 0,
        "average_price": order["average_price"],
        "rejection_reason": order.get("rejection_reason") or "",
    }


class SahiOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for Sahi (JSON order frames, no subscribe)."""

    def __init__(self, user_id: str, access_token: str):
        super().__init__(broker_name="sahi", user_id=user_id)
        self.access_token = access_token

    def get_ws_url(self) -> str:
        return f"{WS_BASE_URL}{ORDER_STREAM_PATH}"

    def get_headers(self):
        return {"Authorization": f"Bearer {self.access_token}", "User-Agent": USER_AGENT}

    def normalize(self, raw_message):
        if isinstance(raw_message, (bytes, bytearray)):
            raw_message = bytes(raw_message).decode("utf-8", errors="replace")
        try:
            data = json.loads(raw_message)
        except (TypeError, ValueError):
            return None
        return normalize_order(data)


def create_sahi_order_adapter(user_id: str) -> "SahiOrderUpdateAdapter | None":
    """Factory: build the adapter from the stored access token, or None when
    the user has no Sahi session (order_api.py sends the same token)."""
    access_token = get_auth_token(user_id, bypass_cache=True)
    if not access_token:
        logger.warning(
            f"No Sahi auth token found for user {user_id}; order-update adapter not started"
        )
        return None
    return SahiOrderUpdateAdapter(user_id=user_id, access_token=access_token)
