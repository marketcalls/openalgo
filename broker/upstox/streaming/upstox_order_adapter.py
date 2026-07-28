"""
Upstox order-update adapter — dedicated Portfolio Stream Feed WebSocket.

Docs: broker-api-docs/upstox-api-docs/21c-websocket-portfolio-stream.md,
21d-websocket-portfolio-auth.md, 23-webhook.md ("Webhook payloads mirror
WebSocket update structures" — so the order-update message field names
follow the webhook payload documented in 23-webhook.md).

Auth flow (two steps, and the redirect code is single-use — must be
re-fetched on every (re)connect, not cached):
    1. GET the authorized redirect URI with Authorization: Bearer <token>.
    2. Connect directly to that returned wss:// URL (auth is baked into its
       query params; no separate header needed for step 2).
"""

import json

from database.auth_db import get_auth_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter

logger = get_logger(__name__)

UPSTOX_PORTFOLIO_AUTH_URL = "https://api.upstox.com/v2/feed/portfolio-stream-feed/authorize"
# Direct endpoint fallback: 21c-websocket-portfolio-stream.md documents wss
# connection with the Bearer header (HTTP 302 -> authorized endpoint, which
# websocket-client follows during the handshake).
UPSTOX_PORTFOLIO_DIRECT_WS_URL = (
    "wss://api.upstox.com/v2/feed/portfolio-stream-feed?update_types=order"
)

# Upstox order "status" free-text values -> OpenAlgo's lowercase order_status
# vocabulary. Upstox statuses are already close to lowercase; unrecognized
# values pass through verbatim rather than being forced into a bucket.
_STATUS_MAP = {
    "complete": "complete",
    "cancelled": "cancelled",
    "rejected": "rejected",
    "open": "open",
    "trigger pending": "trigger pending",
    "put order req received": "open",
    "modified": "open",
    "modify pending": "open",
    "cancel pending": "open",
}

# Upstox "product" codes -> OpenAlgo product constants
_PRODUCT_MAP = {"D": "CNC", "I": "MIS"}


class UpstoxOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Dedicated order-update WebSocket adapter for Upstox."""

    def __init__(self, user_id: str, access_token: str):
        super().__init__(broker_name="upstox", user_id=user_id)
        self.access_token = access_token

    def get_ws_url(self) -> str:
        """
        Fetch a fresh authorized redirect URI. Called on every (re)connect
        attempt by BaseOrderUpdateAdapter._connect_once — the "code" query
        param in the returned URL is single-use per Upstox's docs, so this
        must not be cached across reconnects. Falls back to the direct wss
        endpoint (Bearer-header auth, 302-redirect handshake) if the
        authorize endpoint is unavailable.
        """
        try:
            client = get_httpx_client()
            response = client.get(
                UPSTOX_PORTFOLIO_AUTH_URL,
                params={"update_types": "order"},
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            payload = response.json()
            url = payload.get("data", {}).get("authorized_redirect_uri")
            if url:
                return url
            self.logger.warning(
                "Upstox portfolio-stream authorize returned no redirect URI; "
                "falling back to direct endpoint"
            )
        except Exception as e:
            self.logger.warning(
                f"Upstox portfolio-stream authorize failed ({e}); "
                "falling back to direct endpoint"
            )
        return UPSTOX_PORTFOLIO_DIRECT_WS_URL

    def get_headers(self):
        # Required for the direct-endpoint fallback; harmless on the
        # pre-authorized redirect URI (auth is in its query params).
        return {"Authorization": f"Bearer {self.access_token}"}

    def normalize(self, raw_message):
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        if data.get("update_type") not in (None, "order"):
            return None  # gtt_order/position/holding updates — not in scope here

        raw_status = str(data.get("status", "")).lower()
        order_status = _STATUS_MAP.get(raw_status, raw_status or "open")

        quantity = int(data.get("quantity") or 0)
        filled_quantity = int(data.get("filled_quantity") or 0)

        exchange = data.get("exchange", "")
        symbol = data.get("trading_symbol", "") or data.get("tradingsymbol", "")
        # Map to OpenAlgo symbol format (NHPC-EQ -> NHPC) via the instrument
        # token, exactly like broker/upstox/mapping/order_data.py does for the
        # orderbook (Upstox's SymToken.token is the instrument key, e.g.
        # "NSE_EQ|INE848E01016"). Falls back to the broker trading symbol.
        instrument_token = data.get("instrument_token") or data.get("instrument_key")
        if instrument_token and exchange:
            try:
                from database.token_db import get_symbol

                symbol = get_symbol(instrument_token, exchange) or symbol
            except Exception:
                pass

        return {
            "orderid": data.get("order_id", ""),
            "symbol": symbol,
            "exchange": exchange,
            "action": data.get("transaction_type", ""),
            "quantity": quantity,
            "price": float(data.get("price") or 0),
            "trigger_price": float(data.get("trigger_price") or 0),
            "pricetype": data.get("order_type", ""),
            "product": _PRODUCT_MAP.get(data.get("product", ""), data.get("product", "")),
            "order_status": order_status,
            "filled_quantity": filled_quantity,
            "pending_quantity": int(data.get("pending_quantity") or max(quantity - filled_quantity, 0)),
            "average_price": float(data.get("average_price") or 0),
            "rejection_reason": (
                data.get("status_message") or data.get("status", "")
            )
            if order_status == "rejected"
            else "",
        }


def create_upstox_order_adapter(user_id: str) -> "UpstoxOrderUpdateAdapter | None":
    """Factory: build an UpstoxOrderUpdateAdapter for user_id."""
    access_token = get_auth_token(user_id, bypass_cache=True)
    if not access_token:
        logger.warning(f"No Upstox access token found for user {user_id}; order-update adapter not started")
        return None

    return UpstoxOrderUpdateAdapter(user_id=user_id, access_token=access_token)
