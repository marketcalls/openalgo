"""
AliceBlue order-update adapter — dedicated Order Status Feed WebSocket.

Docs: broker-api-docs/aliceblue-api-docs/10-webhooks.md, "Order Status Feed
WebSocket API" section.
Auth flow:
    1. GET open-api/order-notify/ws/createWsToken with Authorization: Bearer
       <token> -> {"result": [{"orderToken": "..."}]}.
    2. Connect to wss://a3.aliceblueonline.com/open-api/order-notify/websocket
       and send {"orderToken": ..., "userId": ...} to subscribe.
    3. Send {"heartbeat": "h", "userId": ...} every 60s or the connection is
       dropped by AliceBlue.

userId here is the numeric UCC (client_id) — same resolution as
broker/aliceblue/streaming/aliceblue_adapter.py (get_user_id, falling back to
decoding the "ucc" claim from the JWT auth token).
"""

import base64
import json

from database.auth_db import get_auth_token, get_user_id
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter

logger = get_logger(__name__)

ALICEBLUE_CREATE_WS_TOKEN_URL = "https://ant.aliceblueonline.com/open-api/order-notify/ws/createWsToken"
ALICEBLUE_ORDER_UPDATE_WS_URL = "wss://a3.aliceblueonline.com/open-api/order-notify/websocket"
ALICEBLUE_HEARTBEAT_INTERVAL_SECONDS = 55  # under the 60s server timeout

# AliceBlue is Noren-lineage — "status"/"reporttype" free text (Noren
# convention: New/Replaced/Complete/Rejected/Cancelled/...) -> OpenAlgo's
# lowercase order_status vocabulary. Case-insensitive match.
_STATUS_MAP = {
    "open": "open",
    "new": "open",
    "trigger_pending": "open",
    "trigger pending": "open",
    "replaced": "open",
    "complete": "complete",
    "rejected": "rejected",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}

# Matches broker/aliceblue/mapping/order_data.py's REST Prctype mapping (the
# verified source of truth for this broker's price-type codes).
_PRICETYPE_MAP = {"MKT": "MARKET", "L": "LIMIT", "SL": "SL", "SL-M": "SL-M"}

_ACTION_MAP = {"B": "BUY", "S": "SELL"}


class AliceBlueOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Dedicated order-update WebSocket adapter for AliceBlue."""

    def __init__(self, user_id: str, alice_ucc: str, auth_token: str):
        super().__init__(broker_name="aliceblue", user_id=user_id)
        self.alice_ucc = alice_ucc
        self.auth_token = auth_token
        self._order_token: str | None = None

    def get_ws_url(self) -> str:
        self._order_token = self._fetch_order_token()
        return ALICEBLUE_ORDER_UPDATE_WS_URL

    def get_headers(self):
        return None  # auth handshake happens via a post-connect message

    def _fetch_order_token(self) -> str:
        client = get_httpx_client()
        response = client.get(
            ALICEBLUE_CREATE_WS_TOKEN_URL,
            headers={"Authorization": f"Bearer {self.auth_token}"},
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("result") or []
        if not results or not results[0].get("orderToken"):
            raise RuntimeError("AliceBlue createWsToken did not return an orderToken")
        return results[0]["orderToken"]

    def on_open_extra(self, ws) -> None:
        sub_msg = {"orderToken": self._order_token, "userId": self.alice_ucc}
        ws.send(json.dumps(sub_msg))
        self.logger.info(f"Sent AliceBlue order-notify subscribe for UCC {self.alice_ucc}")

    def heartbeat_interval(self):
        return ALICEBLUE_HEARTBEAT_INTERVAL_SECONDS

    def send_heartbeat(self, ws) -> None:
        ws.send(json.dumps({"heartbeat": "h", "userId": self.alice_ucc}))

    def normalize(self, raw_message):
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        if data.get("t") != "om":
            return None  # subscribe ack / other frame types

        raw_status = str(data.get("status", "")).strip().lower()
        order_status = _STATUS_MAP.get(raw_status, raw_status or "open")

        qty = int(data.get("qty") or 0)
        fillshares = int(data.get("fillshares") or 0)

        return {
            "orderid": data.get("norenordno", ""),
            "symbol": data.get("tsym", ""),
            "exchange": data.get("exch", ""),
            "action": _ACTION_MAP.get(data.get("trantype", ""), data.get("trantype", "")),
            "quantity": qty,
            "price": float(data.get("prc") or 0),
            "trigger_price": float(data.get("trgprc") or 0),
            "pricetype": _PRICETYPE_MAP.get(data.get("prctyp", ""), data.get("prctyp", "")),
            "product": data.get("pcode", ""),
            "order_status": order_status,
            "filled_quantity": fillshares,
            "pending_quantity": max(qty - fillshares, 0),
            "average_price": float(data.get("avgprc") or 0),
            "rejection_reason": data.get("rejreason", "") if raw_status == "rejected" else "",
        }


def create_aliceblue_order_adapter(user_id: str) -> "AliceBlueOrderUpdateAdapter | None":
    """
    Factory: build an AliceBlueOrderUpdateAdapter for user_id. Resolves the
    numeric UCC the same way broker/aliceblue/streaming/aliceblue_adapter.py
    does: get_user_id(), falling back to decoding the "ucc" claim from the
    JWT auth token.
    """
    auth_token = get_auth_token(user_id, bypass_cache=True)
    if not auth_token:
        logger.warning(f"No AliceBlue auth token found for user {user_id}; order-update adapter not started")
        return None

    alice_ucc = get_user_id(user_id)
    if not alice_ucc:
        try:
            payload_b64 = auth_token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            alice_ucc = payload.get("ucc")
        except Exception as e:
            logger.warning(f"Failed to extract UCC from AliceBlue JWT for user {user_id}: {e}")

    if not alice_ucc:
        logger.warning(f"No AliceBlue UCC found for user {user_id}; order-update adapter not started")
        return None

    return AliceBlueOrderUpdateAdapter(user_id=user_id, alice_ucc=alice_ucc, auth_token=auth_token)
