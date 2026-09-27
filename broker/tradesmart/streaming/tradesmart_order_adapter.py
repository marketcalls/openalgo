"""
TradeSmart order-update adapter — order updates on a second NorenWSAPI
connection.

Docs: broker-api-docs/tradesmart-api-docs.md ("WebSocket streaming" — connect,
task table, order-update notes, and the Reference section's enumerated order
statuses and product codes).
Endpoint: wss://v2api.tradesmartonline.in/NorenWSAPI/

Handshake (matches broker/tradesmart/streaming/tradesmart_websocket.py, and the
doc agrees with it):
    1. connect, send {"t":"a","uid":...,"actid":...,"source":"API","accesstoken":...}
    2. wait for {"t":"ak","s":"OK"} ack
    3. order updates start arriving as {"t":"om", ...} — see below
    4. send {"t":"h"} heartbeats (acked t="hk")

**TradeSmart does not use an order-update subscribe frame.** Its task table
lists order updates as `automatic` with no request `t`, unlike Shoonya /
Flattrade / Zebu / Definedge, which all require {"t":"o","actid":...} after the
connect ack. Nothing is sent here beyond the connect, per the doc. If a live
session turns out to deliver no om frames, sending the sibling brokers' t="o"
on ack is the first thing to try.

Two more TradeSmart-specific traps:
  - the stored auth token is a COMPOSITE "<uid>:::<bearer>"; the socket wants
    the bearer half only, so it goes through baseurl.parse_auth() rather than
    being passed through raw the way the other Noren adapters pass their token
  - besides om, this socket pushes other unsolicited feeds — am (alerts/GTT),
    rm (admin messages), ms (market status) — which are ignored here

Like the sibling Noren adapters, this opens its own connection rather than
multiplexing the market-data socket: BaseOrderUpdateAdapter owns its ws, and a
dedicated session keeps order updates independent of market-data
subscribe/reconnect churn.
"""

import json

from broker.tradesmart.api.baseurl import parse_auth, resolve_uid
from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

TRADESMART_WS_URL = "wss://v2api.tradesmartonline.in/NorenWSAPI/"
TRADESMART_HEARTBEAT_INTERVAL_SECONDS = 30

# TradeSmart's documented order statuses (Reference > Code reference):
# PENDING, CANCELED, OPEN, REJECTED, COMPLETE, TRIGGER_PENDING. The extra Noren
# in-flight states are kept as defensive entries — every one collapses to "open".
#
# NOTE the deliberate difference from broker/tradesmart/mapping/order_data.py::
# normalize_order_status, which folds TRIGGER_PENDING into "open". That is the
# REST orderbook path, where the React order book gates its Modify/Cancel
# buttons on order_status === 'open'. This is the push-event path, whose
# consumers (services/flow_order_update_monitor_service.py's watch filters, the
# WS clients) expect the distinct "trigger pending". Don't unify them.
_STATUS_MAP = {
    "complete": "complete",
    "executed": "complete",
    "open": "open",
    "new": "open",
    "replaced": "open",
    "pending": "open",
    "open pending": "open",
    "modify pending": "open",
    "cancel pending": "open",
    "after market order req received": "open",
    "trigger pending": "trigger pending",
    "rejected": "rejected",
    "reject": "rejected",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}

# Noren carries a terminal state in "reporttype" (doc: "Fill, Rejected,
# Canceled") when "status" is unmapped. "Fill" is deliberately absent — it rides
# along with partial fills too, so it cannot mean "complete".
_REPORTTYPE_FALLBACK = {
    "rejected": "rejected",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}

# Doc: "Price type | LMT, MKT, SL-LMT, SL-MKT"
_PRICETYPE_MAP = {"LMT": "LIMIT", "MKT": "MARKET", "SL-LMT": "SL", "SL-MKT": "SL-M"}

# Doc: "C = CNC, M = NRML, I = MIS, F = MTF, H = Cover Order, B = Bracket Order".
# OpenAlgo has only CNC/NRML/MIS, so F/H/B have no equivalent and fall through
# to the raw code rather than being silently mislabelled as one of the three.
_PRODUCT_MAP = {"C": "CNC", "M": "NRML", "I": "MIS"}

_ACTION_MAP = {"B": "BUY", "S": "SELL"}


def _noren_text(value) -> str:
    """Lowercase a Noren free-text field, folding "_" to " " so TRIGGER_PENDING
    (the documented spelling) and "TRIGGER PENDING" compare equal."""
    return str(value or "").strip().lower().replace("_", " ")


class TradeSmartOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for TradeSmart (Noren v2, dedicated connection)."""

    def __init__(self, user_id: str, tradesmart_uid: str, accesstoken: str):
        super().__init__(broker_name="tradesmart", user_id=user_id)
        self.tradesmart_uid = tradesmart_uid
        self.accesstoken = accesstoken

    def get_ws_url(self) -> str:
        return TRADESMART_WS_URL

    def get_headers(self):
        return None  # Noren auth happens via the t="a" connect message

    def on_open_extra(self, ws) -> None:
        connect_msg = {
            "t": "a",
            "uid": self.tradesmart_uid,
            "actid": self.tradesmart_uid,
            "source": "API",
            "accesstoken": self.accesstoken,
        }
        ws.send(json.dumps(connect_msg))
        self.logger.info(f"Sent TradeSmart Noren connect for uid {self.tradesmart_uid}")

    def heartbeat_interval(self):
        return TRADESMART_HEARTBEAT_INTERVAL_SECONDS

    def send_heartbeat(self, ws) -> None:
        ws.send(json.dumps({"t": "h"}))

    def _close_after_failed_ack(self) -> None:
        """Drop a socket the broker refused to authenticate, so the base class'
        reconnect loop takes over instead of the adapter idling forever."""
        ws = self._ws
        if ws is None:
            return
        try:
            ws.close()
        except Exception:
            self.logger.debug("Closing the un-acked TradeSmart socket failed", exc_info=True)

    def normalize(self, raw_message):
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        frame_type = data.get("t")

        # Connect ack. Unlike the sibling Noren adapters there is nothing to
        # subscribe to — TradeSmart pushes order updates automatically once the
        # session is authenticated.
        if frame_type == "ak":
            # tradesmart_websocket.py compares s == "OK"; accept any casing.
            if _noren_text(data.get("s") or data.get("stat")) != "ok":
                # A rejected Noren auth does not always drop the socket —
                # TradeSmart can hold it open, which would leave this adapter
                # reporting `connected` and silent forever (and here there is no
                # subscribe frame whose failure would hint at it). Close it so
                # run_forever returns and BaseOrderUpdateAdapter's backoff loop
                # retries with a fresh handshake (same reasoning as
                # kotak_order_adapter's connect-ack watchdog).
                self.logger.error(f"TradeSmart connect ack not OK: {data}")
                self._close_after_failed_ack()
            else:
                self.logger.info(
                    "TradeSmart connect acked; order updates stream automatically (no t=o)"
                )
            return None

        if frame_type != "om":
            # t="hk" heartbeat acks and the other unsolicited feeds the doc
            # lists: am (alerts/GTT), rm (admin messages), ms (market status),
            # plus tf/df/pm/lf market data if anything ever subscribes here.
            return None

        raw_status = _noren_text(data.get("status"))
        raw_report = _noren_text(data.get("reporttype"))
        order_status = _STATUS_MAP.get(raw_status)
        if order_status is None:
            order_status = _REPORTTYPE_FALLBACK.get(raw_report) or raw_status or "open"

        qty = int(float(data.get("qty") or 0))
        fillshares = int(float(data.get("fillshares") or 0))

        # Symbol -> OpenAlgo format (get_oa_symbol on Noren tsym, same as the
        # REST orderbook mapping), falling back to the broker symbol.
        exchange = data.get("exch", "")
        symbol = to_openalgo_symbol(data.get("tsym", ""), exchange)

        # Noren uses "prd"; some deployments in this family (Flattrade,
        # Firstock) send "pcode" on the order feed instead. Accept either.
        product_code = data.get("prd") or data.get("pcode") or ""

        return {
            "orderid": data.get("norenordno", ""),
            "symbol": symbol,
            "exchange": exchange,
            "action": _ACTION_MAP.get(data.get("trantype", ""), data.get("trantype", "")),
            "quantity": qty,
            "price": float(data.get("prc") or 0),
            "trigger_price": float(data.get("trgprc") or 0),
            "pricetype": _PRICETYPE_MAP.get(data.get("prctyp", ""), data.get("prctyp", "")),
            "product": _PRODUCT_MAP.get(product_code, product_code),
            "order_status": order_status,
            "filled_quantity": fillshares,
            "pending_quantity": max(qty - fillshares, 0),
            "average_price": float(data.get("avgprc") or 0),
            "rejection_reason": data.get("rejreason", "") if order_status == "rejected" else "",
        }


def create_tradesmart_order_adapter(user_id: str) -> "TradeSmartOrderUpdateAdapter | None":
    """Factory: build a TradeSmartOrderUpdateAdapter for user_id."""
    stored_token = get_auth_token(user_id, bypass_cache=True)
    if not stored_token:
        logger.warning(
            f"No TradeSmart auth token for user {user_id}; order-update adapter not started"
        )
        return None

    # The stored token is "<uid>:::<bearer>" — the socket needs the bearer half
    # and the uid doubles as actid. Same resolution as tradesmart_adapter.py.
    token_uid, accesstoken = parse_auth(stored_token)
    tradesmart_uid = token_uid or resolve_uid(stored_token) or user_id

    if not accesstoken:
        logger.warning(
            f"No TradeSmart accesstoken for user {user_id}; order-update adapter not started"
        )
        return None
    if not tradesmart_uid:
        logger.warning(
            f"No TradeSmart uid found for user {user_id}; order-update adapter not started"
        )
        return None

    return TradeSmartOrderUpdateAdapter(
        user_id=user_id, tradesmart_uid=tradesmart_uid, accesstoken=accesstoken
    )
