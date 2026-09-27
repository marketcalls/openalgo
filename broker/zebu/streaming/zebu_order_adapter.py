"""
Zebu order-update adapter — order-update subscription on a second NorenWSAPI
connection.

Endpoint: wss://go.mynt.in/NorenWSAPI/

There is no Zebu WebSocket doc in broker-api-docs/, so unlike the Shoonya and
Flattrade adapters this one is not written against a published order-update
spec. Two things stand in for it:
  - the handshake is taken verbatim from the live market-data client,
    broker/zebu/streaming/zebu_websocket.py::_send_authentication, which is in
    production
  - the order-update frames are the Noren standard shared by every other
    Noren broker in this repo (Shoonya, Flattrade, Definedge): subscribe with
    t="o", feed arrives as t="om", unsubscribe with t="uo"/t="ud"
Zebu's endpoint carries the same "NorenWSAPI" path suffix as Shoonya's, so the
same protocol revision is the reasonable expectation — but the om field names
below are inference, not documentation, and want checking against a live
session. The parsing is deliberately tolerant where the Noren family is known
to disagree (see the pcode/prd and norenordno notes inline).

Handshake:
    1. connect, send {"t":"a","uid":...,"actid":...,"source":"API","accesstoken":...}
    2. wait for {"t":"ak","s":"OK"} ack
    3. send {"t":"o","actid":...} to subscribe order updates
    4. order feed arrives as {"t":"om", ...Noren order fields...}
    5. send {"t":"h"} heartbeats to keep the session alive

Like the sibling Noren adapters, this opens its own connection rather than
multiplexing the market-data socket: BaseOrderUpdateAdapter owns its ws, and a
dedicated session keeps order updates independent of market-data
subscribe/reconnect churn.

Credentials: accesstoken = get_auth_token(user_id) (Zebu stores the Noren
susertoken as the auth token); uid/actid = the trading user id from the ":::"
BROKER_API_KEY ("userid:::client_id", e.g. Z56004:::Z56004_U), the same
resolution as broker/zebu/streaming/zebu_adapter.py.
"""

import json
import os

from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter, to_openalgo_symbol

logger = get_logger(__name__)

ZEBU_WS_URL = "wss://go.mynt.in/NorenWSAPI/"
ZEBU_HEARTBEAT_INTERVAL_SECONDS = 30

# Noren order-status free text -> OpenAlgo's lowercase order_status vocabulary.
# Every in-flight OMS state collapses to "open"; see the Zerodha map in
# .claude/skills/broker-integration/references/order-updates.md.
#
# NOTE the deliberate difference from broker/zebu/mapping/order_data.py::
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

# Noren sometimes carries a terminal state only in "reporttype" (Fill, Rejected,
# Canceled). Consulted only when "status" is unmapped. "Fill" is deliberately
# absent — it rides along with partial fills too, so it cannot mean "complete".
_REPORTTYPE_FALLBACK = {
    "rejected": "rejected",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}

# Noren prctyp codes -> OpenAlgo pricetype constants
_PRICETYPE_MAP = {"LMT": "LIMIT", "MKT": "MARKET", "SL-LMT": "SL", "SL-MKT": "SL-M"}

# Noren product codes -> OpenAlgo product constants
_PRODUCT_MAP = {"C": "CNC", "M": "NRML", "I": "MIS"}

_ACTION_MAP = {"B": "BUY", "S": "SELL"}


def _noren_text(value) -> str:
    """Lowercase a Noren free-text field, folding "_" to " " so TRIGGER_PENDING
    and "TRIGGER PENDING" (both appear across Noren deployments) compare equal."""
    return str(value or "").strip().lower().replace("_", " ")


class ZebuOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Order-update adapter for Zebu (Noren protocol, dedicated connection)."""

    def __init__(self, user_id: str, zebu_uid: str, susertoken: str):
        super().__init__(broker_name="zebu", user_id=user_id)
        self.zebu_uid = zebu_uid
        self.susertoken = susertoken

    def get_ws_url(self) -> str:
        return ZEBU_WS_URL

    def get_headers(self):
        return None  # Noren auth happens via the t="a" connect message

    def on_open_extra(self, ws) -> None:
        connect_msg = {
            "t": "a",
            "uid": self.zebu_uid,
            "actid": self.zebu_uid,
            "source": "API",
            "accesstoken": self.susertoken,
        }
        ws.send(json.dumps(connect_msg))
        self.logger.info(f"Sent Zebu Noren connect for uid {self.zebu_uid}")

    def heartbeat_interval(self):
        return ZEBU_HEARTBEAT_INTERVAL_SECONDS

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
            self.logger.debug("Closing the un-acked Zebu socket failed", exc_info=True)

    def normalize(self, raw_message):
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None

        frame_type = data.get("t")

        # Connect ack -> now subscribe to order updates on this session.
        if frame_type == "ak":
            # zebu_websocket.py compares s.lower() == "ok"; do the same rather
            # than betting on the casing. Keep the auth verdict and the socket
            # check separate so the log says which one failed.
            if _noren_text(data.get("s") or data.get("stat")) != "ok":
                # A rejected Noren auth does not always drop the socket — Zebu
                # can hold it open, which would leave this adapter reporting
                # `connected` while subscribed to nothing and silent forever.
                # Close it so run_forever returns and BaseOrderUpdateAdapter's
                # backoff loop retries with a fresh handshake (same reasoning as
                # kotak_order_adapter's connect-ack watchdog). That retry also
                # matters more here than elsewhere: the connect variant is
                # unverified (see the module docstring), so a wrong guess must
                # surface as a retry loop, not as silence.
                self.logger.error(f"Zebu connect ack not OK: {data}")
                self._close_after_failed_ack()
            elif self._ws is None:
                self.logger.warning(
                    "Zebu connect acked but the socket is already gone; "
                    "order-update subscribe skipped (reconnect will retry)"
                )
            else:
                self._ws.send(json.dumps({"t": "o", "actid": self.zebu_uid}))
                self.logger.info("Zebu connect acked; sent order-update subscribe (t=o)")
            return None

        if frame_type != "om":
            return None  # t="ok"/"uok"/"hk" acks, market-data feeds, etc.

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

        # The Noren family disagrees on the product key: Zebu's REST orderbook
        # uses "prd", but Flattrade's and Firstock's order feeds use "pcode".
        # With no Zebu WS doc to settle it, accept either.
        product_code = data.get("prd") or data.get("pcode") or ""

        # Likewise the order number: "norenordno" everywhere except Shoonya's
        # order-feed table, which spells it "norenoordno".
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
            "product": _PRODUCT_MAP.get(product_code, product_code),
            "order_status": order_status,
            "filled_quantity": fillshares,
            "pending_quantity": max(qty - fillshares, 0),
            "average_price": float(data.get("avgprc") or 0),
            "rejection_reason": data.get("rejreason", "") if order_status == "rejected" else "",
        }


def create_zebu_order_adapter(user_id: str) -> "ZebuOrderUpdateAdapter | None":
    """Factory: build a ZebuOrderUpdateAdapter for user_id."""
    susertoken = get_auth_token(user_id, bypass_cache=True)
    if not susertoken:
        logger.warning(
            f"No Zebu susertoken (auth token) for user {user_id}; order-update adapter not started"
        )
        return None

    # BROKER_API_KEY format: userid:::client_id (e.g. Z56004:::Z56004_U) — the
    # trading user id is the first component and doubles as actid, the same
    # resolution zebu_adapter.py uses.
    full_api_key = os.getenv("BROKER_API_KEY", "")
    if full_api_key and ":::" in full_api_key:
        zebu_uid = full_api_key.split(":::")[0]
    elif full_api_key:
        logger.warning("Zebu BROKER_API_KEY missing ':::' separator; using it as-is for uid")
        zebu_uid = full_api_key
    else:
        logger.warning(f"No Zebu BROKER_API_KEY found; using user_id '{user_id}' as uid")
        zebu_uid = user_id

    if not zebu_uid:
        logger.warning(f"No Zebu uid found for user {user_id}; order-update adapter not started")
        return None

    return ZebuOrderUpdateAdapter(user_id=user_id, zebu_uid=zebu_uid, susertoken=susertoken)
