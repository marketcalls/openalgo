"""
Flattrade order-update adapter — order-update subscription on a second
PiConnectWSAPI connection.

Docs: broker-api-docs/flattrade-api-docs/09-websocket.md ("Subscribe Order
Update" / "Unsubscribe Order Update", plus the shared Connect and Heartbeat
sections). Endpoint: wss://piconnect.flattrade.in/PiConnectWSAPI/

Handshake (Noren protocol, matches
broker/flattrade/streaming/flattrade_websocket.py::_send_authentication — for
Flattrade the doc and the live client agree, unlike Shoonya):
    1. connect, send {"t":"a","uid":...,"actid":...,"source":"API","accesstoken":...}
    2. wait for {"t":"ak","s":"OK"} ack
    3. send {"t":"o","actid":...} to subscribe order updates
    4. order feed arrives as {"t":"om", ...Noren order fields...}
    5. send {"t":"h"} heartbeats every 30s (acked as t="hk")

Two Flattrade-specific quirks the sibling Noren adapters do not have:
  - the order feed carries the product in "pcode", not "prd" (doc line 205),
    so both are read
  - there is NO subscription acknowledgement for the order-update subscribe
    (doc line 194) — the t="o" frame is fire-and-forget, so nothing waits on
    an ack, and unsubscribe is t="uo" (acked "uok"), not the depth "ud"

Like Definedge and Shoonya, this opens its own connection rather than
multiplexing the market-data socket: BaseOrderUpdateAdapter owns its ws, and a
dedicated session keeps order updates independent of market-data
subscribe/reconnect churn.

Credentials: accesstoken = get_auth_token(user_id) (Flattrade's jKey session
token); uid/actid = the trading user id from BROKER_API_KEY, which is always
"userid:::api_key" for Flattrade (broker/flattrade/api/auth_api.py takes the
[1] component unconditionally, so login cannot work without the ":::"). Same
resolution as broker/flattrade/streaming/flattrade_adapter.py.
"""

import json
import os

from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

FLATTRADE_WS_URL = "wss://piconnect.flattrade.in/PiConnectWSAPI/"
# Doc: "To keep the connection alive, send a heartbeat message every 30 seconds."
FLATTRADE_HEARTBEAT_INTERVAL_SECONDS = 30

# Noren order-status free text -> OpenAlgo's lowercase order_status vocabulary.
# Every in-flight OMS state collapses to "open"; see the Zerodha map in
# .claude/skills/broker-integration/references/order-updates.md.
#
# NOTE the deliberate difference from broker/flattrade/mapping/order_data.py::
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
# event that triggered this message (Fill, Rejected, Canceled)"). Consulted only
# when "status" is unmapped. "Fill" is deliberately absent — it rides along with
# partial fills too, so it cannot mean "complete".
_REPORTTYPE_FALLBACK = {
    "rejected": "rejected",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}

# Noren prctyp codes -> OpenAlgo pricetype constants. The doc lists only
# LMT/SL-LMT for the order feed, but Flattrade's REST orderbook returns all
# four, so all four are mapped.
_PRICETYPE_MAP = {"LMT": "LIMIT", "MKT": "MARKET", "SL-LMT": "SL", "SL-MKT": "SL-M"}

# Noren product codes -> OpenAlgo product constants
_PRODUCT_MAP = {"C": "CNC", "M": "NRML", "I": "MIS"}

_ACTION_MAP = {"B": "BUY", "S": "SELL"}


def _noren_text(value) -> str:
    """Lowercase a Noren free-text field, folding "_" to " " so TRIGGER_PENDING
    and "TRIGGER PENDING" (both appear across Noren deployments) compare equal."""
    return str(value or "").strip().lower().replace("_", " ")


class FlattradeOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for Flattrade (Noren protocol, dedicated connection)."""

    def __init__(self, user_id: str, flattrade_uid: str, accesstoken: str):
        super().__init__(broker_name="flattrade", user_id=user_id)
        self.flattrade_uid = flattrade_uid
        self.accesstoken = accesstoken

    def get_ws_url(self) -> str:
        return FLATTRADE_WS_URL

    def get_headers(self):
        return None  # Noren auth happens via the t="a" connect message

    def on_open_extra(self, ws) -> None:
        connect_msg = {
            "t": "a",
            "uid": self.flattrade_uid,
            "actid": self.flattrade_uid,
            "source": "API",
            "accesstoken": self.accesstoken,
        }
        ws.send(json.dumps(connect_msg))
        self.logger.info(f"Sent Flattrade Noren connect for uid {self.flattrade_uid}")

    def heartbeat_interval(self):
        return FLATTRADE_HEARTBEAT_INTERVAL_SECONDS

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
            self.logger.debug("Closing the un-acked Flattrade socket failed", exc_info=True)

    def normalize(self, raw_message):
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        frame_type = data.get("t")

        # Connect ack -> now subscribe to order updates on this session. There is
        # no ack for the subscribe itself, so this is the last handshake step.
        if frame_type == "ak":
            # flattrade_websocket.py compares s == "OK" while the doc writes
            # "Ok"; accept either rather than betting on the casing. Keep the
            # auth verdict and the socket check separate so the log says which
            # one failed.
            if _noren_text(data.get("s") or data.get("stat")) != "ok":
                # A rejected Noren auth does not always drop the socket —
                # Flattrade can hold it open, which would leave this adapter
                # reporting `connected` while subscribed to nothing and silent
                # forever. Close it so run_forever returns and
                # BaseOrderUpdateAdapter's backoff loop retries with a fresh
                # handshake (same reasoning as kotak_order_adapter's connect-ack
                # watchdog).
                self.logger.error(f"Flattrade connect ack not OK: {data}")
                self._close_after_failed_ack()
            elif self._ws is None:
                self.logger.warning(
                    "Flattrade connect acked but the socket is already gone; "
                    "order-update subscribe skipped (reconnect will retry)"
                )
            else:
                self._ws.send(json.dumps({"t": "o", "actid": self.flattrade_uid}))
                self.logger.info("Flattrade connect acked; sent order-update subscribe (t=o)")
            return None

        if frame_type != "om":
            return None  # t="hk" heartbeat acks, t="uok" unsubscribe acks, feeds, etc.

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

        # Flattrade's order feed names the product "pcode" (doc line 205) where
        # the rest of Noren uses "prd"; accept either.
        product_code = data.get("pcode") or data.get("prd") or ""

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


def create_flattrade_order_adapter(user_id: str) -> "FlattradeOrderUpdateAdapter | None":
    """Factory: build a FlattradeOrderUpdateAdapter for user_id."""
    accesstoken = get_auth_token(user_id, bypass_cache=True)
    if not accesstoken:
        logger.warning(
            f"No Flattrade accesstoken (auth token) for user {user_id}; order-update adapter not started"
        )
        return None

    # BROKER_API_KEY format: userid:::api_key — the trading user id is the first
    # component and doubles as actid, the same resolution flattrade_adapter.py
    # and broker/flattrade/api/order_api.py use.
    api_key = os.getenv("BROKER_API_KEY", "")
    flattrade_uid = api_key.split(":::")[0] if ":::" in api_key else user_id

    if not flattrade_uid:
        logger.warning(
            f"No Flattrade uid found for user {user_id}; order-update adapter not started"
        )
        return None

    return FlattradeOrderUpdateAdapter(
        user_id=user_id, flattrade_uid=flattrade_uid, accesstoken=accesstoken
    )
