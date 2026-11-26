"""
Flattrade order-update adapter: event driven, over the one PiConnect session.

PiConnect permits ONE WebSocket session per {uid, accesstoken}; a second
connection makes the broker close the older one with code 1000 (issue #1806,
broker-api-docs/flattrade-api-docs/09-websocket.md). Order updates (t="o" /
t="om") therefore cannot have a socket of their own while market data is
streaming. Until issue #2386 this adapter fell back to polling the order book
every ORDER_POLL_INTERVAL seconds, and that poller kept reading the book with
the expired token after the daily rollover.

How it works now (FlattradeEventOrderAdapter):

  relay mode    The market-data adapter in the websocket proxy process
                (flattrade_adapter.py) owns the session. It subscribes t="o"
                on its socket and forwards every t="om" frame over a
                Flattrade-only local ZMQ channel (flattrade_order_relay.py).
                This adapter normalizes each frame and publishes an
                OrderUpdateEvent on the Flask event bus.

  standalone    No market-data adapter is running (nobody has a chart or
                watchlist open). This adapter opens its own PiConnect socket
                (FlattradeOrderUpdateAdapter below) and subscribes t="o".

  handover      The market-data adapter sends "claim" before every connect.
                On a claim this adapter closes its socket at once, before the
                broker can evict anything, and does not reopen it while the
                market-data adapter keeps sending "alive". After "release", or
                OWNER_TIMEOUT_SECONDS of silence, it goes standalone again.

  rollover      Nothing connects unless a login happened in the current trading
                session (last_rollover_boundary(), default 03:00 IST). A socket
                still open when the session ends is closed. A refused connect
                ack stands the adapter down until the next broker login, which
                builds a fresh adapter (database.auth_db.upsert_auth).

  catch-up      Each time a new order stream starts (relay "ready", or the
                standalone connect ack) one order-book read is compared with
                the last known state, and changes missed in the gap are
                published. The first read only records the state.

Fallback: FLATTRADE_ORDER_POLLING=TRUE, or a relay port that cannot be bound,
returns the old PollingOrderUpdateAdapter.

Docs: broker-api-docs/flattrade-api-docs/09-websocket.md ("Subscribe Order
Update", plus the shared Connect and Heartbeat sections). Endpoint:
wss://piconnect.flattrade.in/PiConnectWSAPI/

Handshake (Noren protocol, matches flattrade_websocket.py::_send_authentication):
    1. connect, send {"t":"a","uid":...,"actid":...,"source":"API","accesstoken":...}
    2. wait for {"t":"ak","s":"OK"} ack
    3. send {"t":"o","actid":...} to subscribe order updates (no ack, doc line 194)
    4. order feed arrives as {"t":"om", ...Noren order fields...}
    5. send {"t":"h"} heartbeats every 30s (acked as t="hk")

The order feed carries the product in "pcode", not "prd" (doc line 205), so
both are read.

Credentials: accesstoken = get_auth_token(user_id); uid/actid = the trading
user id from BROKER_API_KEY, "userid:::api_key" for Flattrade.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime

from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import (
    BaseOrderUpdateAdapter,
    _is_auth_rejection,
    to_openalgo_symbol,
)

from . import flattrade_order_relay as relay_mod

logger = get_logger(__name__)

FLATTRADE_WS_URL = "wss://piconnect.flattrade.in/PiConnectWSAPI/"
# Doc: "To keep the connection alive, send a heartbeat message every 30 seconds."
FLATTRADE_HEARTBEAT_INTERVAL_SECONDS = 30

# The market-data adapter owns the session while its last claim/ready/alive
# is younger than this (it sends "alive" every ALIVE_INTERVAL_SECONDS).
OWNER_TIMEOUT_SECONDS = 3 * relay_mod.ALIVE_INTERVAL_SECONDS
# After connect(), wait this long for a running market-data adapter to be
# heard before opening a socket of our own.
STARTUP_GRACE_SECONDS = relay_mod.ALIVE_INTERVAL_SECONDS + 2
# Delays between standalone connect attempts that failed for a reason other
# than a refused token.
STANDALONE_BACKOFFS = [5, 10, 30, 60]
# A standalone session that lived this long clears the backoff.
STABLE_SESSION_SECONDS = 60
# How long a "login this session" answer is reused (it is a database read).
SESSION_CHECK_TTL_SECONDS = 30
_SUPERVISOR_TICK_SECONDS = 1.0

# Noren order-status free text -> OpenAlgo's lowercase order_status vocabulary.
# Every in-flight OMS state collapses to "open".
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


def normalize_order_frame(data: dict) -> dict:
    """Map one t="om" frame to OrderUpdateEvent kwargs (OpenAlgo vocabulary)."""
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


def _comparable_status(status) -> str:
    """Status as both feeds agree on it: the REST book folds trigger pending
    into "open", the push feed keeps it apart (see _STATUS_MAP)."""
    text = _noren_text(status)
    return "open" if text == "trigger pending" else text


def _login_this_trading_session(user_id: str) -> bool:
    """True if a login for user_id happened since the last session rollover.

    Same question as utils.session.has_login_this_trading_session, but measured
    from last_rollover_boundary(): between midnight and 03:00 IST the running
    session began at yesterday's boundary, so an evening login is still
    current. Reads only the database, so it is safe from a background thread.
    """
    from utils.session import is_session_expiry_disabled, last_rollover_boundary

    if is_session_expiry_disabled():
        return True
    try:
        import pytz

        from database.auth_db import get_active_sessions

        boundary = last_rollover_boundary()
        ist = pytz.timezone("Asia/Kolkata")
        for sess in get_active_sessions(user_id):
            raw = sess.get("login_time")
            if not raw:
                continue
            try:
                login_dt = raw if isinstance(raw, datetime) else datetime.fromisoformat(raw)
            except ValueError:
                continue
            # SQLite returns naive IST wall-clock values.
            if login_dt.tzinfo is None:
                login_dt = ist.localize(login_dt)
            if login_dt >= boundary:
                return True
    except Exception:
        logger.debug("Flattrade session check failed", exc_info=True)
    return False


def _flattrade_uid(user_id: str) -> str:
    """Trading user id from BROKER_API_KEY ("userid:::api_key"), read when called."""
    api_key = os.getenv("BROKER_API_KEY", "")
    return api_key.split(":::")[0] if ":::" in api_key else user_id


class FlattradeOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """One dedicated PiConnect socket subscribed to order updates.

    Used by FlattradeEventOrderAdapter only while no market-data adapter holds
    the session. It makes ONE connection attempt per connect(): retries are the
    supervisor's decision, because a retry must first check that the session
    is still free and still current.
    """

    def __init__(self, user_id: str, flattrade_uid: str, accesstoken: str):
        super().__init__(broker_name="flattrade", user_id=user_id)
        self.flattrade_uid = flattrade_uid
        self.accesstoken = accesstoken
        # Set by FlattradeEventOrderAdapter: on_order(fields) sees every
        # published update, on_subscribed() runs after the order subscribe.
        self.on_order = None
        self.on_subscribed = None

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

    def _run_forever(self, generation: int | None = None) -> None:
        """One attempt, then stop; FlattradeEventOrderAdapter decides on retries."""
        if generation is None:
            generation = self._generation
        try:
            if self._is_current(generation):
                self._connect_once(generation)
        except Exception as e:
            if _is_auth_rejection(e):
                self._auth_rejected = True
            else:
                self.logger.warning(f"Flattrade order socket error: {e}")
        finally:
            with self._lock:
                if self._generation == generation:
                    self._running = False

    def _close_socket(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            ws.close()
        except Exception:
            self.logger.debug("Closing the Flattrade order socket failed", exc_info=True)

    def _publish_event_fields(self, fields: dict) -> None:
        hook = self.on_order
        if hook is not None:
            try:
                hook(fields)
            except Exception:
                self.logger.debug("Flattrade order hook failed", exc_info=True)
        super()._publish_event_fields(fields)

    def normalize(self, raw_message):
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None

        frame_type = data.get("t")

        # Connect ack -> subscribe to order updates on this session. There is
        # no ack for the subscribe itself, so this is the last handshake step.
        if frame_type == "ak":
            # flattrade_websocket.py compares s == "OK" while the doc writes
            # "Ok"; accept either.
            if _noren_text(data.get("s") or data.get("stat")) != "ok":
                # A refused token does not heal by retrying; only a new login
                # issues one. Flattrade can also hold a refused socket open, so
                # close it ourselves.
                self.logger.info(
                    "Flattrade refused the stored session for order updates. "
                    "They resume after the next broker login."
                )
                self._auth_rejected = True
                self._close_socket()
            elif self._ws is None:
                self.logger.debug("Flattrade connect acked but the socket is already gone")
            else:
                self._ws.send(json.dumps({"t": "o", "actid": self.flattrade_uid}))
                self.logger.info("Flattrade connect acked; subscribed to order updates")
                hook = self.on_subscribed
                if hook is not None:
                    hook()
            return None

        if frame_type != "om":
            return None  # t="hk" heartbeat acks, t="uok" unsubscribe acks, etc.

        return normalize_order_frame(data)


class FlattradeEventOrderAdapter:
    """Event-driven Flattrade order updates; see the module docstring.

    Same connect()/disconnect()/connected surface as BaseOrderUpdateAdapter,
    which is all services/order_update_service.py uses.
    """

    def __init__(self, user_id: str, flattrade_uid: str, relay):
        self.broker_name = "flattrade"
        self.user_id = user_id
        self.flattrade_uid = flattrade_uid
        self.logger = get_logger("order_adapter_flattrade")
        self._relay = relay
        self._relay_handle = None

        self._lock = threading.Lock()
        self._running = False
        self._generation = 0
        self._started_at = 0.0

        # monotonic time the market-data adapter was last heard, None if it
        # released the session or was never heard.
        self._owner_seen_at: float | None = None
        self._relay_mode_logged = False

        self._socket: FlattradeOrderUpdateAdapter | None = None
        self._socket_started_at = 0.0
        self._standalone_failures = 0
        self._next_standalone_at = 0.0
        self._auth_rejected = False

        self._session_ok: bool | None = None
        self._session_checked_at = 0.0
        self._paused_logged = False

        # orderid -> (comparable status, filled quantity); None until the
        # first order-book read seeds it.
        self._known: dict[str, tuple] | None = None
        self._catch_up_pending = False

        # Publishes relayed frames with the same defaults as a socket would.
        self._publisher = FlattradeOrderUpdateAdapter(user_id, flattrade_uid, accesstoken="")

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> None:
        with self._lock:
            if self._running:
                return
            self._generation += 1
            generation = self._generation
            self._running = True
            self._started_at = time.monotonic()
            self._auth_rejected = False
        self._relay_handle = self._relay.add_handler(self._on_relay_message)
        threading.Thread(
            target=self._supervise,
            args=(generation,),
            daemon=True,
            name=f"order-adapter-flattrade-{self.user_id}",
        ).start()
        self.logger.info(f"Flattrade order updates started for {self.user_id} (event driven)")

    def disconnect(self) -> None:
        with self._lock:
            self._generation += 1
            self._running = False
            socket = self._socket
            self._socket = None
            handle = self._relay_handle
            self._relay_handle = None
        if handle is not None:
            self._relay.remove_handler(handle)
        if socket is not None:
            socket.disconnect()

    @property
    def connected(self) -> bool:
        return self._running

    def _is_current(self, generation: int) -> bool:
        return self._running and self._generation == generation

    # -- relay -------------------------------------------------------------

    def _on_relay_message(self, message: dict) -> None:
        if not self._running:
            return
        if message.get("user_id") != self.user_id and message.get("actid") != self.flattrade_uid:
            return
        kind = message.get("kind")
        now = time.monotonic()

        if kind == relay_mod.KIND_RELEASE:
            with self._lock:
                self._owner_seen_at = None
                self._relay_mode_logged = False
            self.logger.info(
                "Flattrade market-data connection closed; order updates switch to "
                "their own connection"
            )
            return

        if kind not in (
            relay_mod.KIND_CLAIM,
            relay_mod.KIND_READY,
            relay_mod.KIND_ALIVE,
            relay_mod.KIND_ORDER,
        ):
            return

        with self._lock:
            self._owner_seen_at = now
            socket = self._socket
            self._socket = None
            log_switch = not self._relay_mode_logged
            self._relay_mode_logged = True
            if kind == relay_mod.KIND_READY:
                self._catch_up_pending = True
        if socket is not None:
            # Step aside before the market-data socket authenticates.
            socket.disconnect()
        if log_switch:
            self.logger.info("Flattrade order updates now arrive on the market-data connection")

        if kind == relay_mod.KIND_ORDER:
            self._publish_frame(message.get("frame"))

    def _publish_frame(self, raw) -> None:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return
        if not isinstance(data, dict) or data.get("t") != "om":
            return
        try:
            fields = normalize_order_frame(data)
        except Exception:
            self.logger.debug("Could not read a Flattrade order update", exc_info=True)
            return
        self._remember(fields)
        self._publisher._publish_event_fields(fields)

    def _remember(self, fields: dict) -> None:
        orderid = str(fields.get("orderid") or "")
        if not orderid:
            return
        with self._lock:
            if self._known is not None:
                self._known[orderid] = (
                    _comparable_status(fields.get("order_status")),
                    int(fields.get("filled_quantity") or 0),
                )

    # -- supervisor --------------------------------------------------------

    def _supervise(self, generation: int) -> None:
        while self._is_current(generation):
            try:
                self._tick(generation)
            except Exception:
                self.logger.exception("Flattrade order-update supervisor error")
            time.sleep(_SUPERVISOR_TICK_SECONDS)
        self.logger.info(f"Flattrade order updates stopped for {self.user_id}")

    def _owner_active(self, now: float) -> bool:
        seen = self._owner_seen_at
        return seen is not None and now - seen < OWNER_TIMEOUT_SECONDS

    def _session_current(self, now: float) -> bool:
        if self._session_ok is None or now - self._session_checked_at >= SESSION_CHECK_TTL_SECONDS:
            self._session_ok = _login_this_trading_session(self.user_id)
            self._session_checked_at = now
        return self._session_ok

    def _tick(self, generation: int) -> None:
        now = time.monotonic()

        if not self._session_current(now):
            # The stored token belongs to an ended session: no socket, no read.
            self._stop_socket()
            if not self._paused_logged:
                self._paused_logged = True
                self.logger.info(
                    "Flattrade order updates paused: no broker login since today's "
                    "session start. They resume after the next login."
                )
            return
        self._paused_logged = False

        if self._catch_up_pending:
            self._catch_up()

        if self._owner_active(now) or self._auth_rejected:
            return
        if now - self._started_at < STARTUP_GRACE_SECONDS:
            return

        socket = self._socket
        if socket is not None:
            if socket._running:
                return
            # The single attempt has ended.
            self._socket = None
            if socket._auth_rejected:
                self._auth_rejected = True
                return
            lived = now - self._socket_started_at
            if lived >= STABLE_SESSION_SECONDS:
                self._standalone_failures = 0
            delay = STANDALONE_BACKOFFS[
                min(self._standalone_failures, len(STANDALONE_BACKOFFS) - 1)
            ]
            self._standalone_failures += 1
            self._next_standalone_at = now + delay
            return

        if now >= self._next_standalone_at:
            self._start_socket(generation, now)

    def _start_socket(self, generation: int, now: float) -> None:
        accesstoken = get_auth_token(self.user_id, bypass_cache=True)
        if not accesstoken:
            return
        socket = FlattradeOrderUpdateAdapter(self.user_id, self.flattrade_uid, accesstoken)
        socket.on_order = self._remember
        socket.on_subscribed = self._mark_catch_up
        with self._lock:
            # A claim may have landed during the token read.
            if not self._is_current(generation) or self._owner_active(time.monotonic()):
                return
            self._socket = socket
            self._socket_started_at = now
        self.logger.info(
            "No Flattrade market-data connection is open; order updates use their own connection"
        )
        socket.connect()

    def _stop_socket(self) -> None:
        with self._lock:
            socket = self._socket
            self._socket = None
        if socket is not None:
            socket.disconnect()

    def _mark_catch_up(self) -> None:
        self._catch_up_pending = True

    # -- catch-up ----------------------------------------------------------

    def _catch_up(self) -> None:
        """One order-book read after a new order stream starts; publish what
        changed since the last known state. The first read only records it."""
        self._catch_up_pending = False
        from services.orderbook_service import get_orderbook

        auth_token = get_auth_token(self.user_id)
        if not auth_token:
            return
        success, response, _ = get_orderbook(auth_token=auth_token, broker="flattrade")
        if not success:
            self.logger.debug(
                f"Flattrade catch-up read failed: {response.get('message', 'unknown error')}"
            )
            return
        orders = (response.get("data") or {}).get("orders") or []
        snapshot: dict[str, tuple] = {}
        by_id: dict[str, dict] = {}
        for order in orders:
            orderid = str(order.get("orderid") or "")
            if not orderid:
                continue
            snapshot[orderid] = (
                _comparable_status(order.get("order_status")),
                int(order.get("filled_quantity") or 0),
            )
            by_id[orderid] = order

        with self._lock:
            known = self._known
            if known is None:
                self._known = snapshot
                changed = []
            else:
                changed = [oid for oid, state in snapshot.items() if known.get(oid) != state]
                known.update(snapshot)
        for orderid in changed:
            self._publish_book_order(by_id[orderid])

    def _publish_book_order(self, order: dict) -> None:
        status = str(order.get("order_status", "")).strip().lower()
        self._publisher._publish_event_fields(
            {
                "orderid": str(order.get("orderid", "")),
                "symbol": order.get("symbol", ""),
                "exchange": order.get("exchange", ""),
                "action": str(order.get("action", "")).upper(),
                "quantity": int(order.get("quantity") or 0),
                "price": float(order.get("price") or 0),
                "trigger_price": float(order.get("trigger_price") or 0),
                "pricetype": order.get("pricetype", ""),
                "product": order.get("product", ""),
                "order_status": status,
                "filled_quantity": int(order.get("filled_quantity") or 0),
                "pending_quantity": int(order.get("pending_quantity") or 0),
                "average_price": float(order.get("average_price") or 0),
                "rejection_reason": order.get("rejection_reason", "")
                if status == "rejected"
                else "",
            }
        )


def _polling_requested() -> bool:
    return os.getenv("FLATTRADE_ORDER_POLLING", "FALSE").strip().upper() == "TRUE"


class FlattradeSessionPoller:
    """The REST-polling fallback, held back after the session rollover.

    Wraps the shared PollingOrderUpdateAdapter rather than changing it (that
    class serves every polling broker). A gate thread runs the poller only
    while a login of the current trading session exists, so the fallback can
    no longer read the order book all night with the previous day's token
    (issue #2386: the overnight log of 2026-11-18 caught exactly that, from a
    fallback started because another process held the relay port).
    """

    def __init__(self, user_id: str):
        from websocket_proxy.order_adapter import PollingOrderUpdateAdapter

        self.broker_name = "flattrade"
        self.user_id = user_id
        self._poller = PollingOrderUpdateAdapter(broker_name="flattrade", user_id=user_id)
        self._lock = threading.Lock()
        self._running = False
        self._generation = 0
        self._paused_logged = False

    def connect(self) -> None:
        with self._lock:
            if self._running:
                return
            self._generation += 1
            generation = self._generation
            self._running = True
        threading.Thread(
            target=self._gate,
            args=(generation,),
            daemon=True,
            name=f"order-poller-gate-flattrade-{self.user_id}",
        ).start()

    def disconnect(self) -> None:
        with self._lock:
            self._generation += 1
            self._running = False
        self._poller.disconnect()

    @property
    def connected(self) -> bool:
        return self._running

    def _gate(self, generation: int) -> None:
        while self._running and self._generation == generation:
            try:
                self._check()
            except Exception:
                logger.exception("Flattrade order poller gate error")
            slept = 0.0
            while (
                slept < SESSION_CHECK_TTL_SECONDS
                and self._running
                and self._generation == generation
            ):
                time.sleep(1)
                slept += 1

    def _check(self) -> None:
        if _login_this_trading_session(self.user_id):
            self._paused_logged = False
            self._poller.connect()  # idempotent
            return
        self._poller.disconnect()
        if not self._paused_logged:
            self._paused_logged = True
            logger.info(
                "Flattrade order updates paused: no broker login since today's "
                "session start. They resume after the next login."
            )


def create_flattrade_order_adapter(user_id: str):
    """Factory called by services/order_update_service.py.

    Returns the event-driven FlattradeEventOrderAdapter. Falls back to polling
    (FlattradeSessionPoller) when FLATTRADE_ORDER_POLLING=TRUE or when the
    relay port cannot be bound (a second socket without the relay could evict
    the market-data feed, issue #1806, so the relay is required). Returns None
    in the debug reloader's watcher process, which serves nothing.
    """
    if relay_mod.is_reloader_watcher():
        return None

    if _polling_requested():
        logger.info("FLATTRADE_ORDER_POLLING=TRUE: Flattrade order updates poll the order book")
        return FlattradeSessionPoller(user_id)

    relay = relay_mod.listener()
    if not relay.bound:
        return FlattradeSessionPoller(user_id)

    flattrade_uid = _flattrade_uid(user_id)
    if not flattrade_uid:
        logger.warning(f"No Flattrade user id for {user_id}; order updates not started")
        return None
    return FlattradeEventOrderAdapter(user_id=user_id, flattrade_uid=flattrade_uid, relay=relay)
