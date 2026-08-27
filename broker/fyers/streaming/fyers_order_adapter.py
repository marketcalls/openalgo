"""
Fyers order-update adapter — dedicated Order WebSocket.

Docs: broker-api-docs/fyers-api-docs/FYERS_API_v3.md, "Order Websocket Usage
Guide" (~line 6010) and "Response attributes - For order updates" (~line 5183).
Endpoint: wss://socket.fyers.in/trade/v3
Auth header format: "<appId>:<accessToken>" — same convention already used
for Fyers REST calls (see broker/fyers/api/order_api.py's
Authorization: f"{api_key}:{AUTH_TOKEN}" header).
Subscribe handshake (post-connect): {"T": "SUB_ORD", "SUB_T": 1, "action_data": ["orders"]}.

The order-update payload shares its flat field shape with Fyers' Postback
payload (numeric status/type/side/segment/exchange codes) — see
broker-api-docs/fyers-api-docs/FYERS_API_v3.md ~line 4167.
"""

import json

from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

FYERS_ORDER_UPDATE_WS_URL = "wss://socket.fyers.in/trade/v3"

# "status" numeric codes -> OpenAlgo's lowercase order_status vocabulary.
# 3 is documented as "(Not used currently)".
_STATUS_MAP = {
    1: "cancelled",
    2: "complete",
    4: "open",  # Transit — in flight to the exchange
    5: "rejected",
    6: "open",  # Pending
    7: "expired",  # no exact OpenAlgo equivalent; passed through verbatim
}

# "type" numeric codes -> OpenAlgo pricetype constants
_PRICETYPE_MAP = {1: "LIMIT", 2: "MARKET", 3: "SL-M", 4: "SL"}

# "side" numeric codes -> OpenAlgo action constants
_ACTION_MAP = {1: "BUY", -1: "SELL"}

# (exchange, segment) numeric codes -> OpenAlgo exchange constants.
# Fyers exchange codes: 10 = NSE, 11 = MCX, 12 = BSE.
# Fyers segment codes: 10 = capital/equity, 11 = F&O, 12 = currency,
# 20 = commodity. Unknown combinations fall back to the exchange prefix of
# the Fyers symbol string ("NSE:SBIN-EQ" -> "NSE").
_EXCHANGE_SEGMENT_MAP = {
    (10, 10): "NSE",
    (10, 11): "NFO",
    (10, 12): "CDS",
    (12, 10): "BSE",
    (12, 11): "BFO",
    (12, 12): "BCD",
    (11, 20): "MCX",
    (11, 11): "MCX",
}


def _oa_exchange(data: dict) -> str:
    mapped = _EXCHANGE_SEGMENT_MAP.get((data.get("exchange"), data.get("segment")))
    if mapped:
        return mapped
    symbol = str(data.get("symbol", ""))
    return symbol.split(":", 1)[0] if ":" in symbol else str(data.get("exchange", ""))


class FyersOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Dedicated order-update WebSocket adapter for Fyers."""

    def __init__(self, user_id: str, app_id: str, access_token: str):
        super().__init__(broker_name="fyers", user_id=user_id)
        self.app_id = app_id
        self.access_token = access_token

    def get_ws_url(self) -> str:
        return FYERS_ORDER_UPDATE_WS_URL

    def get_headers(self):
        return {"Authorization": f"{self.app_id}:{self.access_token}"}

    def on_open_extra(self, ws) -> None:
        sub_msg = {"T": "SUB_ORD", "SUB_T": 1, "action_data": ["orders"]}
        ws.send(json.dumps(sub_msg))
        self.logger.info(f"Sent Fyers order-update subscribe for {self.app_id}")

    def normalize(self, raw_message):
        try:
            message = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        # The order record may arrive flat at the top level or nested under
        # a "d"/"data" envelope key, depending on socket framing — accept both.
        data = message
        if "id" not in data or "status" not in data:
            data = message.get("d") or message.get("data") or {}
        if "id" not in data or "status" not in data:
            return None  # not an order record (ack/heartbeat/other frame)

        raw_status = data.get("status")
        order_status = _STATUS_MAP.get(raw_status, str(raw_status))

        qty = int(data.get("qty") or 0)
        filled_qty = int(data.get("filledQty") or 0)

        # OpenAlgo exchange from (exchange, segment) codes; symbol via
        # get_oa_symbol on Fyers' "NSE:SBIN-EQ"-style brsymbol — the same
        # lookup the REST orderbook mapping uses.
        exchange = _oa_exchange(data)
        symbol = to_openalgo_symbol(data.get("symbol", ""), exchange)

        return {
            "orderid": str(data.get("id", "")),
            "symbol": symbol,
            "exchange": exchange,
            "action": _ACTION_MAP.get(data.get("side"), str(data.get("side", ""))),
            "quantity": qty,
            "price": float(data.get("limitPrice") or 0),
            "trigger_price": float(data.get("stopPrice") or 0),
            "pricetype": _PRICETYPE_MAP.get(data.get("type"), str(data.get("type", ""))),
            "product": data.get("productType", ""),
            "order_status": order_status,
            "filled_quantity": filled_qty,
            "pending_quantity": max(qty - filled_qty, 0),
            "average_price": float(data.get("tradedPrice") or 0),
            "rejection_reason": data.get("message", "") if raw_status == 5 else "",
        }


def create_fyers_order_adapter(user_id: str) -> "FyersOrderUpdateAdapter | None":
    """
    Factory: build a FyersOrderUpdateAdapter for user_id. app_id comes from
    BROKER_API_KEY (same env var Fyers REST calls use for the Authorization
    header); access_token comes from the DB.
    """
    import os

    from dotenv import load_dotenv

    load_dotenv()

    app_id = os.getenv("BROKER_API_KEY")
    if not app_id:
        logger.warning("BROKER_API_KEY not set; Fyers order-update adapter not started")
        return None

    access_token = get_auth_token(user_id, bypass_cache=True)
    if not access_token:
        logger.warning(f"No Fyers access token found for user {user_id}; order-update adapter not started")
        return None

    return FyersOrderUpdateAdapter(user_id=user_id, app_id=app_id, access_token=access_token)
