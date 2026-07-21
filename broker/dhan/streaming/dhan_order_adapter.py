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
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

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

# (Exchange, Segment) from the order-update payload -> OpenAlgo exchange code.
# Segment codes: E = equity, D = derivatives, C = currency, M = commodity.
_EXCHANGE_SEGMENT_MAP = {
    ("NSE", "E"): "NSE",
    ("NSE", "D"): "NFO",
    ("NSE", "C"): "CDS",
    ("BSE", "E"): "BSE",
    ("BSE", "D"): "BFO",
    ("BSE", "C"): "BCD",
    ("MCX", "M"): "MCX",
}


def _field(data: dict, *keys, default=None):
    """Return the first present key from `keys`.

    Dhan's live order-update payload sends camelCase keys (orderNo, txnType,
    tradedQty, ...) even though docs/13-live-order-update.md documents PascalCase
    (OrderNo, TxnType, TradedQty, ...). Read camelCase first and fall back to the
    documented PascalCase so the adapter is correct against the real feed and
    stays correct if Dhan ever aligns the wire format with its docs.
    """
    for k in keys:
        if k in data:
            return data[k]
    return default


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

        # Dhan's live status values are Title-case ("Pending"/"Traded"); upper() to
        # match the _STATUS_MAP keys (which mirror the REST orderbook vocabulary).
        raw_status = str(_field(data, "status", "Status", default="")).upper()
        order_status = _STATUS_MAP.get(raw_status, raw_status.lower())

        quantity = int(_field(data, "quantity", "Quantity", default=0) or 0)
        traded_qty = int(_field(data, "tradedQty", "TradedQty", default=0) or 0)

        # OpenAlgo exchange from (exchange, segment); symbol via securityId —
        # the same get_symbol(token, exchange) lookup the REST orderbook
        # mapping uses — falling back to Dhan's symbol field.
        exch = _field(data, "exchange", "Exchange", default="")
        seg = _field(data, "segment", "Segment", default="")
        exchange = _EXCHANGE_SEGMENT_MAP.get((exch, seg), exch)
        symbol = to_openalgo_symbol(
            _field(data, "symbol", "Symbol", default=""),
            exchange,
            token=_field(data, "securityId", "SecurityId"),
        )

        txn_type = _field(data, "txnType", "TxnType", default="")
        order_type = _field(data, "orderType", "OrderType", default="")
        product_code = _field(data, "product", "Product", default="")

        return {
            "orderid": _field(data, "orderNo", "OrderNo", default=""),
            "symbol": symbol,
            "exchange": exchange,
            "action": _ACTION_MAP.get(txn_type, txn_type),
            "quantity": quantity,
            "price": float(_field(data, "price", "Price", default=0) or 0),
            "trigger_price": float(_field(data, "triggerPrice", "TriggerPrice", default=0) or 0),
            "pricetype": _PRICETYPE_MAP.get(order_type, order_type),
            "product": _PRODUCT_MAP.get(product_code, product_code),
            "order_status": order_status,
            "filled_quantity": traded_qty,
            "pending_quantity": max(quantity - traded_qty, 0),
            "average_price": float(_field(data, "avgTradedPrice", "AvgTradedPrice", default=0) or 0),
            "rejection_reason": (
                _field(data, "reasonDescription", "ReasonDescription", default="")
                if raw_status == "REJECTED"
                else ""
            ),
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
