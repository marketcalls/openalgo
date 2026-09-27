"""
5Paisa order-update adapter — OrderTradeConfirmations on a dedicated feed
connection.

    !!  NOT REGISTERED. Do not add this to _BROKER_FACTORIES.  !!

5Paisa allows only ONE feed connection per {access_token, client_code}, and a
new connection silently evicts the existing one with a normal close (opcode 8,
code 1000). Registering this adapter puts it in a permanent eviction war with
the market-data adapter, which connects to the same host with the same token:

    market-data socket killed          14:41:20,715
    order-update socket connects       14:41:20,824   (~100ms later)
    market-data reconnects (attempt 2) 14:41:30,806
    order-update socket killed         14:41:30,947   (~140ms later)

Both feeds then flap forever and order updates never reach /websocket/order.
Verified live on 2026-08-07; 5Paisa documents no connection limit, so the only
evidence is the log above.

Multiplexing onto the market-data socket instead does not work either: that
adapter runs inside the websocket_proxy *subprocess* under gunicorn+eventlet and
Docker (see app.py's start_websocket_proxy call site), so an OrderUpdateEvent
published there lands on the wrong process's event bus and never reaches
subscribers/wsproxy_subscriber.py.

5Paisa therefore uses the REST-polling fallback — it is listed in
services/order_update_service.py::_POLLING_BROKERS.

This module is kept, unwired, because the normalization below is the only
written-down record of the OrderTradeConfirmations payload shapes (its tests in
test/test_order_update_adapters.py keep it honest). If 5Paisa ever raises the
connection limit, or order updates are moved onto their own login/token, this is
ready to register.

Docs: broker-api-docs/fivepaisa-api-docs/08-order-tracking.md
      ("Web Socket Trade Confirmation")
Endpoint: wss://{a|b|}openfeed.5paisa.com/feeds/api/chat?Value1={token}|{clientcode}

Two things about this feed that are easy to get wrong:

1. **The host is sharded by the token.** Decode the access-token JWT and read
   its `RedirectServer` claim: "C" -> openfeed, "A" -> aopenfeed, "B" ->
   bopenfeed. Connecting to the wrong host silently pushes no order updates at
   all (market data still works on any host), so there is no error to notice —
   only silence. `fivepaisa_websocket.decode_redirect_server` / `get_feed_url`
   own that resolution and are shared with the market-data client.

2. **`ReqType` decides which fields exist.** The docs' "Response body" table
   lists only a common subset; the real frames (see the five samples in the
   docs) differ per request type:

   | ReqType | Meaning      | BrokerOrderID | qty fields                       |
   |---------|--------------|---------------|----------------------------------|
   | P       | Place        | yes           | Qty / TradedQty / PendingQty     |
   | M       | Modify       | yes           | Qty / TradedQty / PendingQty     |
   | C       | Cancel       | yes           | Qty / TradedQty / PendingQty     |
   | T       | Trade (fill) | **no**        | OrderQty / TotalTradedQty / PendingQty |
   | S       | SL triggered | **no**        | Qty only                         |

   Fills and stop-loss triggers — the two updates that matter most — carry only
   `ExchOrderID`. OpenAlgo's 5Paisa orderbook keys on `BrokerOrderId`
   (mapping/order_data.py), and that is the id `place_order` hands back, so
   emitting an ExchOrderID here would produce order updates the caller cannot
   match to its own order. This adapter therefore remembers the
   ExchOrderID -> BrokerOrderID pairing from the P/M/C frames (which carry both)
   and resolves T/S frames through it, falling back to the ExchOrderID when the
   place frame was missed (e.g. the order predates this connection).

Field names drift between the docs table and the wire, exactly like Dhan's
order feed: the table says `ExchangeOrderID` while every sample sends
`ExchOrderID`, and the REST orderbook spells the broker id `BrokerOrderId` while
the feed sends `BrokerOrderID`. `_field()` reads every observed spelling.

Like Shoonya and Definedge, this opens its own connection rather than
multiplexing the market-data socket, so order updates stay independent of
market-data subscribe/reconnect churn.

Credentials: access_token = get_auth_token(user_id); client_code = the third
":::" component of BROKER_API_KEY, the same resolution as
broker/fivepaisa/streaming/fivepaisa_adapter.py::_resolve_client_code.
"""

import json
import os
from collections import OrderedDict

from broker.fivepaisa.mapping.transform_data import (
    reverse_map_exchange,
    reverse_map_product_type,
)
from broker.fivepaisa.streaming.fivepaisa_websocket import (
    decode_redirect_server,
    get_feed_url,
)
from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

ORDER_UPDATE_METHOD = "OrderTradeConfirmations"

# 5Paisa's market-data client uses a 10s ping with a 5s pong deadline; keep the
# same cadence here so a half-open socket is detected just as quickly.
PING_INTERVAL_SECONDS = 10

# How many ExchOrderID -> BrokerOrderID pairs to retain. One trading day of
# orders on a single account fits comfortably; the cap only exists so a
# long-lived process cannot grow this map without bound.
_ORDER_ID_CACHE_SIZE = 5000

# 5Paisa order statuses -> OpenAlgo's lowercase order_status vocabulary.
# Keys are lowercased before lookup. Sources: the "Order Status" table in
# docs 08-order-tracking.md (order book) plus the Status values in the
# OrderTradeConfirmations samples ("Placed", "Modified", "Cancelled",
# "Fully Executed", "SL Triggered").
#
# Every in-flight OMS state collapses to "open", per the house rule. That
# includes "SL Triggered": once the trigger fires the order is live at the
# exchange, so it is open, not pending. 5Paisa has no distinct trigger-pending
# state — a resting SL order simply reports "Placed"/"Pending" — so this
# adapter does not synthesise one, matching mapping/order_data.py.
_STATUS_MAP = {
    "placed": "open",
    "pending": "open",
    "modified": "open",
    "xmitted": "open",
    "ah placed": "open",
    "ah modified": "open",
    "sl triggered": "open",
    "fully executed": "complete",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "ah cancelled": "cancelled",
    "rejected by 5p": "rejected",
    "rejected by exch": "rejected",
}

_ACTION_MAP = {"B": "BUY", "S": "SELL"}


def _field(data: dict, *keys, default=None):
    """Return the first present key from `keys`.

    The feed and the REST orderbook disagree on capitalisation for several
    fields, and the docs' response table disagrees with its own samples. Read
    every spelling that has been observed rather than betting on one.
    """
    for k in keys:
        if k in data and data[k] is not None:
            return data[k]
    return default


def _num(value, cast, default=0):
    """Coerce a broker numeric that may arrive as None, "" or a string."""
    try:
        return cast(value)
    except (TypeError, ValueError):
        return default


def _pricetype(at_market, trigger_price: float) -> str:
    """Derive the OpenAlgo pricetype the same way the REST orderbook does
    (mapping/order_data.py::transform_order_data): 5Paisa has no order-type
    field, only the AtMarket flag and the presence of a stop-loss trigger."""
    at_market = str(at_market or "").upper()
    if trigger_price > 0:
        return "SL-M" if at_market == "Y" else "SL"
    return "MARKET" if at_market == "Y" else "LIMIT"


class FivepaisaOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for 5Paisa (OrderTradeConfirmations feed)."""

    def __init__(self, user_id: str, client_code: str, access_token: str):
        super().__init__(broker_name="fivepaisa", user_id=user_id)
        self.client_code = client_code
        self.access_token = access_token
        # ExchOrderID -> BrokerOrderID, learned from P/M/C frames so the T/S
        # frames (which omit BrokerOrderID) can report the id callers hold.
        self._broker_order_ids: OrderedDict[str, str] = OrderedDict()

    # -- connection ------------------------------------------------------

    def get_ws_url(self) -> str:
        base = get_feed_url(decode_redirect_server(self.access_token))
        return f"{base}?Value1={self.access_token}|{self.client_code}"

    def get_headers(self):
        return None  # credentials ride in the Value1 query parameter

    def ws_ping_interval(self) -> int:
        return PING_INTERVAL_SECONDS

    def on_open_extra(self, ws) -> None:
        # The docs say order updates are pushed without subscribing, but the
        # feed's own Method section documents this Subscribe frame. Sending it
        # is harmless if updates already flow and necessary if they don't.
        ws.send(
            json.dumps(
                {
                    "Method": ORDER_UPDATE_METHOD,
                    "Operation": "Subscribe",
                    "ClientCode": self.client_code,
                }
            )
        )
        self.logger.info(
            f"Sent 5Paisa {ORDER_UPDATE_METHOD} subscribe for client {self.client_code}"
        )

    # -- message handling ------------------------------------------------

    def _handle_message(self, raw_message) -> None:
        """Split array frames before normalising.

        5Paisa's feed wraps some pushes in a JSON array (the market-data client
        does the same unwrapping). The base class publishes one event per
        message, so an array has to be fanned out here or every confirmation
        but one is dropped.
        """
        if isinstance(raw_message, (bytes, bytearray)):
            return  # no binary frames on this subscription, but never parse one

        try:
            payload = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return

        frames = payload if isinstance(payload, list) else [payload]
        for frame in frames:
            if not isinstance(frame, dict):
                continue
            try:
                fields = self.normalize(frame)
            except Exception as e:
                self.logger.debug(f"Failed to normalize 5Paisa order update: {e}")
                continue
            if fields:
                self._publish_event_fields(fields)

    def _remember_order_id(self, exch_order_id: str, broker_order_id: str) -> None:
        if not exch_order_id or not broker_order_id:
            return
        self._broker_order_ids[exch_order_id] = broker_order_id
        self._broker_order_ids.move_to_end(exch_order_id)
        while len(self._broker_order_ids) > _ORDER_ID_CACHE_SIZE:
            self._broker_order_ids.popitem(last=False)

    def normalize(self, raw_message):
        """Normalize one OrderTradeConfirmations frame (already a dict here —
        `_handle_message` does the JSON/array unwrapping)."""
        data = raw_message
        if not isinstance(data, dict):
            try:
                data = json.loads(raw_message)
            except (json.JSONDecodeError, TypeError):
                return None
            if not isinstance(data, dict):
                return None

        req_type = str(_field(data, "ReqType", "reqType", default="")).upper()
        if not req_type:
            return None  # subscription acks and anything that is not an order event

        exch_order_id = str(
            _field(data, "ExchOrderID", "ExchangeOrderID", "ExchOrderId", default="") or ""
        )
        broker_order_id = _field(data, "BrokerOrderID", "BrokerOrderId")

        if broker_order_id:
            # Place/Modify/Cancel carry both ids — record the pairing so the
            # Trade and SL-trigger frames that follow can be attributed.
            self._remember_order_id(exch_order_id, str(broker_order_id))
            orderid = str(broker_order_id)
        else:
            orderid = self._broker_order_ids.get(exch_order_id, exch_order_id)

        exchange = (
            reverse_map_exchange(data.get("Exch"), data.get("ExchType"))
            or data.get("Exch")
            or ""
        )
        symbol = to_openalgo_symbol(
            str(_field(data, "Symbol", "ScripName", default="") or ""),
            exchange,
            token=_field(data, "ScripCode"),
        )

        raw_status = str(_field(data, "Status", default="")).strip()
        order_status = _STATUS_MAP.get(raw_status.lower(), raw_status.lower() or "open")

        # Trade frames describe the fill, not the order: Qty/Price are this
        # trade's, while OrderQty/OrderPrice/TotalTradedQty describe the parent
        # order. Prefer the order-level fields so consumers see order state.
        quantity = _num(_field(data, "OrderQty", "Qty", default=0), int)
        filled_quantity = _num(_field(data, "TotalTradedQty", "TradedQty", default=0), int)
        pending_quantity = _num(
            _field(data, "PendingQty", default=max(quantity - filled_quantity, 0)), int
        )
        price = _num(_field(data, "OrderPrice", "Price", default=0), float, 0.0)
        trigger_price = _num(_field(data, "SLTriggerRate", default=0), float, 0.0)

        # 5Paisa never sends a running average. On a Trade frame `Price` is the
        # executed price of that fill, which is the closest thing available;
        # every other frame type leaves it at 0 rather than inventing a value.
        average_price = _num(data.get("Price"), float, 0.0) if req_type == "T" else 0.0

        product_code = str(_field(data, "Product", "DelvIntra", default="") or "")
        product = reverse_map_product_type(product_code, exchange) or product_code

        action_code = str(_field(data, "BuySell", default="") or "")

        return {
            "orderid": orderid,
            "symbol": symbol,
            "exchange": exchange,
            "action": _ACTION_MAP.get(action_code, action_code),
            "quantity": quantity,
            "price": price,
            "trigger_price": trigger_price,
            "pricetype": _pricetype(data.get("AtMarket"), trigger_price),
            "product": product,
            "order_status": order_status,
            "filled_quantity": filled_quantity,
            "pending_quantity": max(pending_quantity, 0),
            "average_price": average_price,
            "rejection_reason": (
                str(_field(data, "Remark", "Reason", default="") or "")
                if order_status == "rejected"
                else ""
            ),
        }


def create_fivepaisa_order_adapter(user_id: str) -> "FivepaisaOrderUpdateAdapter | None":
    """Factory: build a FivepaisaOrderUpdateAdapter for user_id."""
    access_token = get_auth_token(user_id, bypass_cache=True)
    if not access_token:
        logger.warning(
            f"No 5Paisa access token found for user {user_id}; order-update adapter not started"
        )
        return None

    # BROKER_API_KEY format: api_key:::user_id:::client_id — the same parse as
    # fivepaisa_adapter.py::_resolve_client_code and api/order_api.py.
    broker_api_key = os.getenv("BROKER_API_KEY", "")
    parts = broker_api_key.split(":::") if broker_api_key else []
    client_code = parts[2].strip() if len(parts) >= 3 and parts[2].strip() else user_id

    if not client_code:
        logger.warning(
            f"No 5Paisa client code for user {user_id}; order-update adapter not started"
        )
        return None

    return FivepaisaOrderUpdateAdapter(
        user_id=user_id, client_code=client_code, access_token=access_token
    )
