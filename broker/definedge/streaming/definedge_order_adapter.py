"""
Definedge order-update adapter — order-update subscription on a second
NorenWSTRTP connection.

Docs: broker-api-docs/definedge-api-docs/11-order-update-websocket.md (order
subscribe/feed) + 10-websocket.md (connect/heartbeat, shared with market data).
Endpoint: wss://trade.definedgesecurities.com/NorenWSTRTP/

Handshake (Noren protocol, mirrors
broker/definedge/streaming/definedge_websocket.py::_authenticate):
    1. connect, send {"t":"c","uid":...,"actid":...,"source":"TRTP","susertoken":...}
    2. wait for {"t":"ck","s":"Ok"} ack
    3. send {"t":"o","actid":...} to subscribe order updates (ack t="ok")
    4. order feed arrives as {"t":"om", ...Noren order fields...}
    5. send {"t":"h"} heartbeats to keep the session alive

Credentials: susertoken = get_feed_token(user_id) (Definedge stores the Noren
session token as the feed token); uid/actid = get_user_id(user_id) — same
resolution as broker/definedge/streaming/definedge_adapter.py.
"""

import json

from database.auth_db import get_feed_token, get_user_id
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

DEFINEDGE_WS_URL = "wss://trade.definedgesecurities.com/NorenWSTRTP/"
DEFINEDGE_HEARTBEAT_INTERVAL_SECONDS = 30

# Noren order-status free text -> OpenAlgo's lowercase order_status
# vocabulary. Mirrors broker/definedge/mapping/order_data.py, which treats
# COMPLETE/EXECUTED as complete, OPEN/NEW/REPLACED/PENDING as open,
# REJECTED as rejected, CANCELED/CANCELLED as cancelled.
_STATUS_MAP = {
    "complete": "complete",
    "executed": "complete",
    "open": "open",
    "new": "open",
    "replaced": "open",
    "pending": "open",
    "trigger_pending": "trigger pending",
    "trigger pending": "trigger pending",
    "rejected": "rejected",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}

# Noren prctyp codes -> OpenAlgo pricetype constants
_PRICETYPE_MAP = {"LMT": "LIMIT", "MKT": "MARKET", "SL-LMT": "SL", "SL-MKT": "SL-M"}

# Noren prd codes -> OpenAlgo product constants
_PRODUCT_MAP = {"C": "CNC", "M": "NRML", "I": "MIS"}

_ACTION_MAP = {"B": "BUY", "S": "SELL"}


class DefinedgeOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for Definedge (Noren protocol, dedicated connection)."""

    def __init__(self, user_id: str, definedge_uid: str, susertoken: str):
        super().__init__(broker_name="definedge", user_id=user_id)
        self.definedge_uid = definedge_uid
        self.susertoken = susertoken

    def get_ws_url(self) -> str:
        return DEFINEDGE_WS_URL

    def get_headers(self):
        return None  # Noren auth happens via the t="c" connect message

    def on_open_extra(self, ws) -> None:
        connect_msg = {
            "t": "c",
            "uid": self.definedge_uid,
            "actid": self.definedge_uid,
            "source": "TRTP",
            "susertoken": self.susertoken,
        }
        ws.send(json.dumps(connect_msg))
        self.logger.info(f"Sent Definedge Noren connect for uid {self.definedge_uid}")

    def heartbeat_interval(self):
        return DEFINEDGE_HEARTBEAT_INTERVAL_SECONDS

    def send_heartbeat(self, ws) -> None:
        ws.send(json.dumps({"t": "h"}))

    def normalize(self, raw_message):
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        frame_type = data.get("t")

        # Connect ack -> now subscribe to order updates on this session.
        if frame_type == "ck":
            if str(data.get("s", "")).lower() == "ok" and self._ws is not None:
                self._ws.send(json.dumps({"t": "o", "actid": self.definedge_uid}))
                self.logger.info("Definedge connect acked; sent order-update subscribe (t=o)")
            else:
                self.logger.warning(f"Definedge connect ack not OK: {data}")
            return None

        if frame_type != "om":
            return None  # t="ok"/"uok" subscription acks, heartbeats, etc.

        raw_status = str(data.get("status", "")).strip().lower()
        order_status = _STATUS_MAP.get(raw_status, raw_status or "open")

        qty = int(data.get("qty") or 0)
        fillshares = int(data.get("fillshares") or 0)

        # Symbol -> OpenAlgo format (get_oa_symbol on Noren tsym, same as the
        # REST orderbook mapping), falling back to the broker symbol.
        exchange = data.get("exch", "")
        symbol = to_openalgo_symbol(data.get("tsym", ""), exchange)

        return {
            "orderid": data.get("norenordno", ""),
            "symbol": symbol,
            "exchange": exchange,
            "action": _ACTION_MAP.get(data.get("trantype", ""), data.get("trantype", "")),
            "quantity": qty,
            "price": float(data.get("prc") or 0),
            "trigger_price": float(data.get("trgprc") or 0),
            "pricetype": _PRICETYPE_MAP.get(data.get("prctyp", ""), data.get("prctyp", "")),
            "product": _PRODUCT_MAP.get(data.get("prd", ""), data.get("prd", "")),
            "order_status": order_status,
            "filled_quantity": fillshares,
            "pending_quantity": max(qty - fillshares, 0),
            "average_price": float(data.get("avgprc") or 0),
            "rejection_reason": data.get("rejreason", "") if order_status == "rejected" else "",
        }


def create_definedge_order_adapter(user_id: str) -> "DefinedgeOrderUpdateAdapter | None":
    """Factory: build a DefinedgeOrderUpdateAdapter for user_id."""
    susertoken = get_feed_token(user_id)
    if not susertoken:
        logger.warning(
            f"No Definedge susertoken (feed token) for user {user_id}; order-update adapter not started"
        )
        return None

    definedge_uid = get_user_id(user_id)
    if not definedge_uid:
        logger.warning(f"No Definedge uid found for user {user_id}; order-update adapter not started")
        return None

    return DefinedgeOrderUpdateAdapter(
        user_id=user_id, definedge_uid=definedge_uid, susertoken=susertoken
    )
