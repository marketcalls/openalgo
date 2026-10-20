"""
Fyers order-update adapter — dedicated Order WebSocket.

Docs: broker-api-docs/fyers-api-docs/FYERS_API_v3.md, "Order Websocket Usage
Guide" (~line 6010) and "Response attributes - For order updates" (~line 5183).
Endpoint: wss://socket.fyers.in/trade/v3
Auth header format: "<appId>:<accessToken>" — same convention already used
for Fyers REST calls (see broker/fyers/api/order_api.py's
Authorization: f"{api_key}:{AUTH_TOKEN}" header).
Subscribe handshake (post-connect): {"T": "SUB_ORD", "SLIST": ["orders"], "SUB_T": 1}.
Note "SLIST" is the wire key — the docs' prose calls the value "action_data",
but that is only the variable name in their Python sample. Fyers acks *any*
payload with {"code":1605,"message":"Successfully subscribed"}, including one
with the wrong key, so the ack cannot be used to confirm the handshake.

Order updates arrive wrapped in the action key, not flat:
{"orders": {...}, "s": "ok"} — see "Response from socket on any action
triggered" (~line 6076). The wrapped record uses the *raw* field names
(org_ord_status, tran_side, ord_type, qty_filled, price_limit, ...), not the
camelCase names the official SDK exposes after applying its "order_mapper"
(~line 6108). We accept both, since only the SDK's parsed shape is documented
in the response-attribute tables.

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


# Envelope keys an order record may arrive under. "orders" is what Fyers
# actually sends; "d"/"data" are defensive against alternate framing.
_ENVELOPE_KEYS = ("orders", "d", "data")

# A record must carry an order id and a status under one of their names to be
# an order update rather than a subscribe ack or heartbeat.
_ID_KEYS = ("id",)
# "org_ord_status" carries the documented 1-7 codes and is what the SDK maps to
# "status". "ord_status" is a separate, differently-coded field present in the
# same raw frame (the docs' sample shows 20); it is accepted last so a frame
# that somehow lacks the others is still surfaced rather than silently dropped.
_STATUS_KEYS = ("org_ord_status", "status", "ord_status")


def _pick(data: dict, *names: str):
    """Return the first present, non-None value among ``names``.

    The raw socket payload and the official SDK's post-mapping payload use
    different names for the same field (``tran_side`` vs ``side``), and only
    the latter is described in the docs' response-attribute tables. Callers
    pass the raw name first, then the parsed one.
    """
    for name in names:
        value = data.get(name)
        if value is not None:
            return value
    return None


def _unwrap_order_record(message: dict) -> dict | None:
    """Extract the order record from a socket frame, or None if it isn't one.

    Fyers wraps updates in the action key — ``{"orders": {...}, "s": "ok"}`` —
    rather than sending them flat. Subscribe acks
    (``{"code": 1605, ...}``) and heartbeats carry no order record and are
    filtered out here.
    """
    if not isinstance(message, dict):
        return None

    candidates = [message.get(key) for key in _ENVELOPE_KEYS]
    candidates.append(message)  # flat framing, as a fallback
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        has_id = any(candidate.get(k) is not None for k in _ID_KEYS)
        has_status = any(candidate.get(k) is not None for k in _STATUS_KEYS)
        if has_id and has_status:
            return candidate
    return None


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
        sub_msg = {"T": "SUB_ORD", "SLIST": ["orders"], "SUB_T": 1}
        ws.send(json.dumps(sub_msg))
        self.logger.info(f"Sent Fyers order-update subscribe for {self.app_id}")

    def normalize(self, raw_message):
        try:
            message = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        data = _unwrap_order_record(message)
        if not data:
            return None  # not an order record (ack/heartbeat/other frame)

        raw_status = _pick(data, *_STATUS_KEYS)
        order_status = _STATUS_MAP.get(raw_status, str(raw_status))
        if raw_status not in _STATUS_MAP:
            # Passed through verbatim rather than dropped. Log the field names so
            # an unexpected wire shape is diagnosable from the logs alone.
            self.logger.warning(
                f"Fyers order update with unmapped status {raw_status!r}; "
                f"record keys: {sorted(data)}"
            )

        qty = int(_pick(data, "qty") or 0)
        filled_qty = int(_pick(data, "qty_filled", "filledQty") or 0)

        # OpenAlgo exchange from (exchange, segment) codes; symbol via
        # get_oa_symbol on Fyers' "NSE:SBIN-EQ"-style brsymbol — the same
        # lookup the REST orderbook mapping uses.
        exchange = _oa_exchange(data)
        symbol = to_openalgo_symbol(_pick(data, "symbol") or "", exchange)

        side = _pick(data, "tran_side", "side")
        pricetype = _pick(data, "ord_type", "type")

        return {
            "orderid": str(_pick(data, "id") or ""),
            "symbol": symbol,
            "exchange": exchange,
            "action": _ACTION_MAP.get(side, str(side or "")),
            "quantity": qty,
            "price": float(_pick(data, "price_limit", "limitPrice") or 0),
            "trigger_price": float(_pick(data, "price_stop", "stopPrice") or 0),
            "pricetype": _PRICETYPE_MAP.get(pricetype, str(pricetype or "")),
            "product": _pick(data, "product_type", "productType") or "",
            "order_status": order_status,
            "filled_quantity": filled_qty,
            "pending_quantity": max(qty - filled_qty, 0),
            "average_price": float(_pick(data, "price_traded", "tradedPrice") or 0),
            "rejection_reason": (
                _pick(data, "oms_msg", "message", "status_msg") or "" if raw_status == 5 else ""
            ),
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
