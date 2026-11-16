"""Nuvama order-update adapter: the Orders Streamer on the API Connect socket.

Docs: broker-api-docs/nuvama-api-docs/25-orders-streamer.md, and the official
SDK's feed/orders_feed.py for the request. The docs show no update packet; the
field names below come from a live capture (November 2026) of a placed,
filled and cancelled YESBANK order.

Request (one JSON line, resent on every reconnect):

    {"request": {"streaming_type": "orderFiler",
                 "data": {"accType": "EQ", "userID": <acc>, "accID": <acc>,
                          "responseType": ["ORDER_UPDATE", "TRADE_UPDATE"]},
                 "formFactor": "P", "appID": <app id key>,
                 "response_format": "json", "request_type": "subscribe"},
     "echo": {}}

The login returns no user id separate from the account id, and the packets
Nuvama sent back carried that same value as their userID.

Each update arrives as {"response": {"streaming_type": "orderFiler", "data":
{...}}}. Order packets (pTyp ORDER_UPDATE) carry oID, sym (the master
contract token, 11915_NSE), tSym, exc, tTyp (BUY/SELL), oTyp, pCode, prc,
trgPrc, tQty (total), fQty (filled), rQty, avgPrc, sts and rRsn. Every step
is a packet of its own: "put order req received", "validation pending",
"open pending", "open", "complete", "cancel pending", "cancelled". Trade
packets (pTyp TRADE_UPDATE) repeat a fill the order packet already reports
as complete with its filled quantity, so they are skipped.

Why this does not subclass BaseOrderUpdateAdapter: the base class runs a
websocket-client WebSocketApp, and Nuvama streams over a plain TCP socket.
Like broker/iiflcapital/streaming/iiflcapital_order_adapter.py, this is a
peer class with connect(), disconnect() and connected, which is all
services/order_update_service.py calls. It opens its own socket, apart from
the market data adapter (which runs in the websocket proxy process), so
order updates flow whether or not any symbol is subscribed.
"""

import json

from broker.nuvama.api.baseurl import parse_token
from broker.nuvama.mapping.order_data import normalize_status
from broker.nuvama.mapping.transform_data import (
    reverse_map_order_type,
    reverse_map_product_type,
    reverse_map_side,
)
from broker.nuvama.streaming.nuvama_socket import NuvamaStreamClient
from database.auth_db import get_auth_token
from utils.event_bus import bus
from utils.logging import get_logger
from websocket_proxy.order_adapter import to_openalgo_symbol

logger = get_logger(__name__)

_FINAL_STATUSES = ("complete", "cancelled", "rejected")


def _f(value):
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _i(value):
    return int(_f(value))


def normalize_order_update(data):
    """One orderFiler packet's data -> the OrderUpdateEvent fields, or None."""
    if not isinstance(data, dict) or data.get("pTyp") != "ORDER_UPDATE":
        return None
    order_id = data.get("oID")
    if not order_id:
        return None

    exchange = (data.get("exc") or "").upper()
    status = normalize_status(data.get("sts"))
    total = _i(data.get("tQty"))
    filled = _i(data.get("fQty"))
    pending = 0 if status in _FINAL_STATUSES else max(total - filled, 0)

    return {
        "orderid": str(order_id),
        "symbol": to_openalgo_symbol(data.get("tSym", ""), exchange, token=data.get("sym")),
        "exchange": exchange,
        "action": reverse_map_side(data.get("tTyp")),
        "quantity": total,
        "price": _f(data.get("prc")),
        "trigger_price": _f(data.get("trgPrc")),
        "pricetype": reverse_map_order_type(data.get("oTyp")),
        "product": reverse_map_product_type(data.get("pCode")),
        "order_status": status or "open",
        "filled_quantity": filled,
        "pending_quantity": pending,
        "average_price": _f(data.get("avgPrc")),
        "rejection_reason": (data.get("rRsn") or "").strip() if status == "rejected" else "",
    }


class NuvamaOrderUpdateAdapter:
    """Order updates from Nuvama's Orders Streamer, published as OrderUpdateEvent."""

    broker_name = "nuvama"

    def __init__(self, user_id, session):
        self.user_id = user_id
        request = {
            "request": {
                "streaming_type": "orderFiler",
                "data": {
                    "accType": session.account_type or "EQ",
                    "userID": session.account_id,
                    "accID": session.account_id,
                    "responseType": ["ORDER_UPDATE", "TRADE_UPDATE"],
                },
                "formFactor": "P",
                "appID": session.app_id_key,
                "response_format": "json",
                "request_type": "subscribe",
            },
            "echo": {},
        }
        self._client = NuvamaStreamClient(
            app_id=session.app_id_key,
            account_type=session.account_type or "EQ",
            on_packet=self._on_packet,
            standing_requests=[json.dumps(request) + "\n"],
            name="nuvama-orders",
        )

    def connect(self):
        self._client.start()

    def disconnect(self):
        self._client.stop()

    @property
    def connected(self):
        return self._client.is_connected()

    def _on_packet(self, streaming_type, data):
        if streaming_type != "orderFiler":
            return
        fields = normalize_order_update(data)
        if not fields:
            return
        fields.setdefault("mode", "live")
        fields.setdefault("broker", self.broker_name)
        fields.setdefault("request_data", {"user_id": self.user_id})
        fields.setdefault("api_type", f"{self.broker_name}.order_update")
        try:
            from events import OrderUpdateEvent

            bus.publish(OrderUpdateEvent(**fields))
        except Exception:
            logger.exception("Failed to publish a Nuvama order update")


def create_nuvama_order_adapter(user_id):
    """Factory for services/order_update_service.py; None without a usable session."""
    token = get_auth_token(user_id, bypass_cache=True)
    if not token:
        logger.warning(f"No Nuvama session for {user_id}; order updates not started")
        return None
    try:
        session = parse_token(token)
    except ValueError:
        logger.warning(f"Incomplete Nuvama session for {user_id}; order updates not started")
        return None
    return NuvamaOrderUpdateAdapter(user_id, session)
