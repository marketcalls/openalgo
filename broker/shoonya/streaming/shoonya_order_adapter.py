"""
Shoonya order-update adapter — order-update subscription on a second
NorenWSAPI connection.

Docs: broker-api-docs/shoonya-api-docs/09-websocket-api.md ("Subscribe Order
Update" / "Unsubscribe Order Update", plus the shared Connect handshake).
Endpoint: wss://api.shoonya.com/NorenWSAPI/

Handshake (Noren protocol, mirrors
broker/shoonya/streaming/shoonya_websocket.py::_send_authentication):
    1. connect, send {"t":"a","uid":...,"actid":...,"source":"API","accesstoken":...}
    2. wait for {"t":"ak","s":"OK"} ack
    3. send {"t":"o","actid":...} to subscribe order updates (ack t="ok")
    4. order feed arrives as {"t":"om", ...Noren order fields...}
    5. send {"t":"h"} heartbeats to keep the session alive

Three places where the doc is wrong and the live market-data client
(shoonya_websocket.py) is authoritative, since that code is in production:
  - the connect frame's token field is "accesstoken", not the doc's "usertoken"
  - "source" is "API", not the doc's WEB/MOB
  - the order-feed section heads t="om" as "touchline feed" (a copy-paste from
    the touchline table); "om" is the order feed
The doc also lists the order-update section under "/NorenWSTP" while its own
Connect section gives wss://api.shoonya.com/NorenWSAPI/ — the market-data
client uses NorenWSAPI, so this uses NorenWSAPI too.

Like Definedge (the other Noren broker here), this opens its own connection
rather than multiplexing the market-data socket: BaseOrderUpdateAdapter owns
its ws, and a dedicated session keeps order updates independent of
market-data subscribe/reconnect churn.

Credentials: accesstoken = get_auth_token(user_id) (Shoonya stores the Noren
susertoken as the auth token — note this differs from Definedge, which keeps
it as the *feed* token); uid/actid = the trading user id from the ":::"
BROKER_API_KEY, the same resolution as
broker/shoonya/streaming/shoonya_adapter.py::initialize.
"""

import json
import os

from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

SHOONYA_WS_URL = "wss://api.shoonya.com/NorenWSAPI/"
SHOONYA_HEARTBEAT_INTERVAL_SECONDS = 30

# Noren order-status free text -> OpenAlgo's lowercase order_status vocabulary.
# Every in-flight OMS state collapses to "open"; see the Zerodha map in
# .claude/skills/broker-integration/references/order-updates.md.
#
# NOTE the deliberate difference from broker/shoonya/mapping/order_data.py::
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

# Noren sometimes carries a terminal state only in "reporttype" (doc: "Order
# event for which this message is sent out. (Fill, Rejected, Canceled)").
# Consulted only when "status" is unmapped. "Fill" is deliberately absent — it
# rides along with partial fills too, so it cannot mean "complete".
_REPORTTYPE_FALLBACK = {
    "rejected": "rejected",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}

# Noren prctyp codes -> OpenAlgo pricetype constants
_PRICETYPE_MAP = {"LMT": "LIMIT", "MKT": "MARKET", "SL-LMT": "SL", "SL-MKT": "SL-M"}

# Noren prd codes -> OpenAlgo product constants
_PRODUCT_MAP = {"C": "CNC", "M": "NRML", "I": "MIS"}

_ACTION_MAP = {"B": "BUY", "S": "SELL"}


def _noren_text(value) -> str:
    """Lowercase a Noren free-text field, folding "_" to " " so TRIGGER_PENDING
    and "TRIGGER PENDING" (both appear across Noren deployments) compare equal."""
    return str(value or "").strip().lower().replace("_", " ")


class ShoonyaOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for Shoonya (Noren protocol, dedicated connection)."""

    def __init__(self, user_id: str, shoonya_uid: str, susertoken: str):
        super().__init__(broker_name="shoonya", user_id=user_id)
        self.shoonya_uid = shoonya_uid
        self.susertoken = susertoken

    def get_ws_url(self) -> str:
        return SHOONYA_WS_URL

    def get_headers(self):
        return None  # Noren auth happens via the t="a" connect message

    def on_open_extra(self, ws) -> None:
        connect_msg = {
            "t": "a",
            "uid": self.shoonya_uid,
            "actid": self.shoonya_uid,
            "source": "API",
            "accesstoken": self.susertoken,
        }
        ws.send(json.dumps(connect_msg))
        self.logger.info(f"Sent Shoonya Noren connect for uid {self.shoonya_uid}")

    def heartbeat_interval(self):
        return SHOONYA_HEARTBEAT_INTERVAL_SECONDS

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
            self.logger.debug("Closing the un-acked Shoonya socket failed", exc_info=True)

    def normalize(self, raw_message):
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        frame_type = data.get("t")

        # Connect ack -> now subscribe to order updates on this session.
        if frame_type == "ak":
            # shoonya_websocket.py compares s == "OK" while the doc writes "Ok";
            # accept either rather than betting on the casing. Keep the auth
            # verdict and the socket check separate so the log says which failed.
            if _noren_text(data.get("s") or data.get("stat")) != "ok":
                # A rejected Noren auth does not always drop the socket —
                # Shoonya can hold it open, which would leave this adapter
                # reporting `connected` while subscribed to nothing and silent
                # forever. Close it so run_forever returns and
                # BaseOrderUpdateAdapter's backoff loop retries with a fresh
                # handshake (same reasoning as kotak_order_adapter's connect-ack
                # watchdog).
                self.logger.error(f"Shoonya connect ack not OK: {data}")
                self._close_after_failed_ack()
            elif self._ws is None:
                self.logger.warning(
                    "Shoonya connect acked but the socket is already gone; "
                    "order-update subscribe skipped (reconnect will retry)"
                )
            else:
                self._ws.send(json.dumps({"t": "o", "actid": self.shoonya_uid}))
                self.logger.info("Shoonya connect acked; sent order-update subscribe (t=o)")
            return None

        if frame_type != "om":
            return None  # t="ok"/"uok" subscription acks, heartbeats, feeds, etc.

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

        # The order-feed table spells the order number "norenoordno" (double o)
        # while every other Noren payload uses "norenordno"; read both.
        orderid = data.get("norenordno") or data.get("norenoordno") or ""

        return {
            "orderid": orderid,
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


def create_shoonya_order_adapter(user_id: str) -> "ShoonyaOrderUpdateAdapter | None":
    """Factory: build a ShoonyaOrderUpdateAdapter for user_id."""
    susertoken = get_auth_token(user_id, bypass_cache=True)
    if not susertoken:
        logger.warning(
            f"No Shoonya susertoken (auth token) for user {user_id}; order-update adapter not started"
        )
        return None

    # BROKER_API_KEY format: userid:::client_id — the trading user id is the
    # first component and doubles as actid (broker/shoonya/api/order_api.py and
    # shoonya_adapter.py resolve it the same way).
    full_api_key = os.getenv("BROKER_API_KEY", "")
    if full_api_key and ":::" in full_api_key:
        shoonya_uid = full_api_key.split(":::")[0]
    elif full_api_key:
        shoonya_uid = full_api_key
    else:
        shoonya_uid = user_id

    if not shoonya_uid:
        logger.warning(f"No Shoonya uid found for user {user_id}; order-update adapter not started")
        return None

    return ShoonyaOrderUpdateAdapter(
        user_id=user_id, shoonya_uid=shoonya_uid, susertoken=susertoken
    )
