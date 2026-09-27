"""
IndMoney (INDstocks) order-update adapter — dedicated order-update WebSocket.

Docs: broker-api-docs/indstocks-api-docs/08-websockets.md ("Order Updates").
Endpoint: wss://ws-order-updates.indstocks.com/api/v1/ws/trades
Auth: raw access token in the Authorization header (no "Bearer" prefix, per
the INDstocks docs). Subscribe handshake (post-connect):
{"action": "subscribe", "mode": "order_update"}.

The documented sample frame does NOT match what the server sends. Observed live
on 2026-08-06:

    {"mode": "order_update", "timestamp": 1786000826536,
     "data": {"order_id": "96057848", "entity_name": "Yes Bank Ltd",
              "order_type": "SELL", "order_status": "S", "lot": 1,
              "executed_price": 22.89, "elapsed_time": 23,
              "error_message": " ", "req_quantity": 1, "requested_lot": 1}}

Differences from the docs: the payload is nested under "data" (docs show it
flat), there is no "type" field, order_status is a single letter rather than the
REST vocabulary, "order_type" is the BUY/SELL side rather than the price type,
and there is no filled/pending split - only req_quantity.

Symbol and exchange are not included (entity_name is a company name, not a
tradable symbol), so those are left empty and consumers correlate by orderid.

NOTE: the order_id here is bare numeric ("96057848") while the REST order book
and the place-order response use a prefixed form ("EQ-96057848"/"DRV-…"). The
stream id is the numeric part of the canonical id, so _canonical_order_id()
resolves it against the order book before publishing - without that, clients
cannot match an update to the order they placed, and dedup by order id fails.
"""

import json
import threading
import time

from cachetools import TTLCache

from broker.indmoney.mapping.order_data import normalize_order_status
from database.auth_db import get_auth_token
from utils.logging import get_logger
from websocket_proxy.order_adapter import BaseOrderUpdateAdapter

logger = get_logger(__name__)

INDMONEY_ORDER_UPDATE_WS_URL = "wss://ws-order-updates.indstocks.com/api/v1/ws/trades"

# Maps (user_id, bare numeric order id) -> the canonical EQ-/DRV- id.
#
# The user id is part of the key because the order book it is built from is
# per-user: two accounts can hold the same numeric id, and a process-global
# mapping would publish one user's canonical id on another's stream.
#
# Bounded and TTL'd: an order id is only interesting for the trading day, and
# this runs in a worker that never restarts.
_ID_CACHE = TTLCache(maxsize=4096, ttl=86400)
_ID_CACHE_LOCK = threading.Lock()

# A burst of frames for the SAME unknown order must not trigger one order-book
# fetch each. Throttling is therefore per (user, order id), not global - a
# global clock would leave a genuinely new order publishing a bare id for the
# whole window, so the same order would appear under two different ids across
# its own lifecycle and break dedup.
_ID_REFRESH_MIN_INTERVAL = 5.0
_id_refresh_attempts = TTLCache(maxsize=4096, ttl=300)


def _canonical_order_id(raw_id, user_id):
    """
    Resolve the stream's bare numeric order id to the canonical EQ-/DRV- id.

    Returns `raw_id` unchanged if it is already prefixed, or if the order book
    cannot be reached - an unresolved id is still better than dropping the
    update.
    """
    order_id = str(raw_id or "").strip()
    if not order_id or "-" in order_id:
        return order_id  # already canonical

    key = (str(user_id), order_id)
    now = time.monotonic()

    with _ID_CACHE_LOCK:
        hit = _ID_CACHE.get(key)
        if hit:
            return hit
        last_try = _id_refresh_attempts.get(key, 0.0)
        due = (now - last_try) >= _ID_REFRESH_MIN_INTERVAL
        if due:
            _id_refresh_attempts[key] = now

    if not due:
        return order_id

    try:
        # Imported lazily: the streaming package and websocket_proxy import each
        # other, so a module-level import here risks the known cycle.
        from broker.indmoney.api.order_api import get_order_book
        from database.auth_db import get_auth_token

        auth = get_auth_token(user_id)
        if not auth:
            return order_id

        # Fetch OUTSIDE the lock. Holding a mutex across a network round trip
        # would stall normalization for every other order-update stream while
        # one user's order book is slow or being rate-limited.
        book = get_order_book(auth) or []

        resolved = None
        with _ID_CACHE_LOCK:
            for order in book:
                if not isinstance(order, dict):
                    continue
                canonical = str(order.get("id", ""))
                suffix = canonical.split("-", 1)[-1]
                if suffix and suffix != canonical:
                    _ID_CACHE[(str(user_id), suffix)] = canonical
                    if suffix == order_id:
                        resolved = canonical
        return resolved or order_id

    except Exception as e:
        logger.warning(f"Could not resolve IndMoney order id {order_id}: {e}")
        return order_id


class IndmoneyOrderUpdateAdapter(BaseOrderUpdateAdapter):
    """Dedicated order-update WebSocket adapter for IndMoney/INDstocks."""

    def __init__(self, user_id: str, access_token: str):
        super().__init__(broker_name="indmoney", user_id=user_id)
        self.access_token = access_token

    def get_ws_url(self) -> str:
        return INDMONEY_ORDER_UPDATE_WS_URL

    def get_headers(self):
        # Raw token, no "Bearer" prefix — per INDstocks WS docs.
        return {"Authorization": self.access_token}

    def _handle_message(self, raw_message):
        # Log every inbound frame before normalization. The base adapter drops a
        # frame silently when normalize() returns None, so without this an
        # unexpected payload shape is invisible - exactly the failure mode that
        # made this stream look connected-but-dead.
        self.logger.info(f">> RAW INDMONEY ORDER FRAME: {str(raw_message)[:500]}")
        return super()._handle_message(raw_message)

    def on_open_extra(self, ws) -> None:
        # Confirmed live: the server echoes "mode":"order_update" (singular) on
        # every frame, so that is the correct subscription mode. The server
        # sends no subscribe acknowledgement, so an unrecognised mode would fail
        # silently - the socket stays open and simply never delivers.
        ws.send(json.dumps({"action": "subscribe", "mode": "order_update"}))
        self.logger.info("Sent IndMoney order_update subscribe")

    # Candidate spellings per logical field. The documented sample does not
    # match what the server actually sends (see the class docstring), so read
    # tolerantly rather than binding to a single spelling.
    _ORDER_ID_KEYS = ("order_id", "orderId", "orderid", "id", "order_no", "orderNo")
    _STATUS_KEYS = ("order_status", "orderStatus", "status")
    _FILLED_KEYS = ("filled_quantity", "filledQuantity", "traded_qty", "tradedQty", "filled_qty")
    _REMAINING_KEYS = (
        "remaining_quantity",
        "remainingQuantity",
        "pending_qty",
        "pendingQty",
        "remaining_qty",
    )
    _AVG_PRICE_KEYS = (
        "executed_price",
        "average_price",
        "averagePrice",
        "avg_price",
        "avgPrice",
        "traded_price",
    )
    _QUANTITY_KEYS = ("req_quantity", "quantity", "qty", "requested_qty")

    # The live stream reports status as a single letter, not the REST
    # vocabulary. Confirmed against real order flow on 2026-08-06:
    #   R -> first frame emitted on place and on modify (received/requested)
    #   P -> pending at the exchange (carries elapsed_time)
    #   S -> executed (carries executed_price)
    # The remaining codes are inferred from the usual Indian-broker convention
    # and are logged when they fire so they can be confirmed against real
    # rejections/cancellations.
    _CONFIRMED_STATUS_CODES = {"R": "open", "P": "open", "S": "complete"}
    _INFERRED_STATUS_CODES = {
        "C": "cancelled",
        "X": "cancelled",
        "F": "rejected",
        "E": "rejected",
        "J": "rejected",
    }

    @staticmethod
    def _field(data, keys, default=None):
        """First present, non-empty value among `keys`."""
        for key in keys:
            if key in data and data[key] not in (None, ""):
                return data[key]
        return default

    @staticmethod
    def _as_int(value):
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            return 0

    def _map_status(self, raw_status):
        """Map the stream's status code to an OpenAlgo canonical status."""
        code = str(raw_status).strip().upper()

        if code in self._CONFIRMED_STATUS_CODES:
            return self._CONFIRMED_STATUS_CODES[code]

        if code in self._INFERRED_STATUS_CODES:
            mapped = self._INFERRED_STATUS_CODES[code]
            self.logger.warning(
                f"Order-update status code {code!r} mapped to {mapped!r} by inference. "
                "Confirm this against the broker before relying on it."
            )
            return mapped

        # Not a single-letter code - fall back to the REST vocabulary, which the
        # stream may also use (underscore variants like PARTIALLY_EXECUTED).
        mapped = normalize_order_status(code.replace("_", " "))
        if mapped == code.lower():
            self.logger.warning(f"Unrecognised order-update status {raw_status!r}; passing through")
        return mapped

    @staticmethod
    def _decode(raw_message):
        """
        Decode a frame to a dict, tolerating double-encoded JSON.

        INDstocks sends the payload as a JSON *string* containing JSON, i.e. the
        text frame is "{\\"mode\\":\\"order_update\\",...}" rather than
        {"mode":"order_update",...}. A single json.loads() therefore yields a
        str, not a dict. The market-data adapter already decodes twice; this
        stream needs the same treatment.
        """
        value = raw_message
        for _ in range(3):  # bounded: one real decode plus the extra wrapper
            if isinstance(value, dict):
                return value
            if isinstance(value, (bytes, bytearray)):
                value = value.decode("utf-8", errors="replace")
            if not isinstance(value, str):
                return None
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return None
        return value if isinstance(value, dict) else None

    def normalize(self, raw_message):
        frame = self._decode(raw_message)

        if frame is None:
            self.logger.warning(
                f"Could not decode an order-update frame: {str(raw_message)[:300]}"
            )
            return None

        # The real payload is nested under "data"; the documented sample shows
        # it flat. Accept either so neither shape is dropped.
        data = frame.get("data")
        if not isinstance(data, dict):
            data = frame

        orderid = self._field(data, self._ORDER_ID_KEYS)
        raw_status = self._field(data, self._STATUS_KEYS)

        # Treat any frame carrying an order id AND a status as an order update,
        # whatever it calls itself. The previous code required type == "order"
        # and returned None otherwise - and the base adapter drops a None
        # silently, with no log line, so a shape mismatch made every update
        # disappear without a trace.
        if orderid is None or raw_status is None:
            # Acks and heartbeats are legitimately uninteresting, but a frame we
            # cannot turn into an update must stay visible - a silent drop here
            # is exactly what hid this stream's failure before.
            self.logger.info(
                f"Order-update frame carried no order id/status, ignoring: {str(frame)[:300]}"
            )
            return None

        order_status = self._map_status(raw_status)

        # The stream reports the requested quantity only; it carries no
        # filled/pending split. Prefer explicit fields if they ever appear,
        # otherwise derive the split from the status.
        quantity = self._as_int(self._field(data, self._QUANTITY_KEYS, 0))
        filled = self._field(data, self._FILLED_KEYS)
        remaining = self._field(data, self._REMAINING_KEYS)

        if filled is None and remaining is None:
            if order_status == "complete":
                filled, remaining = quantity, 0
            else:
                filled, remaining = 0, quantity
        else:
            filled = self._as_int(filled)
            remaining = self._as_int(remaining)
            quantity = quantity or (filled + remaining)

        try:
            average_price = float(self._field(data, self._AVG_PRICE_KEYS, 0) or 0)
        except (TypeError, ValueError):
            average_price = 0.0

        # "order_type" on this stream is the transaction side (BUY/SELL), not
        # the price type.
        action = str(self._field(data, ("order_type", "txn_type", "transaction_type"), "")).upper()
        if action not in ("BUY", "SELL"):
            action = ""

        # error_message is " " (a single space) when there is nothing to report.
        rejection_reason = str(self._field(data, ("error_message", "reason"), "") or "").strip()

        # Publish the canonical EQ-/DRV- id so consumers can match the update to
        # the order they placed.
        canonical_id = _canonical_order_id(orderid, self.user_id)

        self.logger.info(
            f"Order update: {canonical_id} {action} status={order_status} "
            f"(raw {raw_status!r}) qty={quantity} filled={filled} avg={average_price}"
        )

        fields = {
            "orderid": str(canonical_id),
            "action": action,
            "order_status": order_status,
            "quantity": quantity,
            "filled_quantity": filled,
            "pending_quantity": remaining,
            "average_price": average_price,
        }
        if rejection_reason and order_status == "rejected":
            fields["rejection_reason"] = rejection_reason
        return fields


def create_indmoney_order_adapter(user_id: str) -> "IndmoneyOrderUpdateAdapter | None":
    """Factory: build an IndmoneyOrderUpdateAdapter for user_id."""
    access_token = get_auth_token(user_id, bypass_cache=True)
    if not access_token:
        logger.warning(
            f"No IndMoney access token found for user {user_id}; order-update adapter not started"
        )
        return None

    return IndmoneyOrderUpdateAdapter(user_id=user_id, access_token=access_token)
