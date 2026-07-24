"""
IIFL Capital order/trade-update adapter — dedicated MQTT connection to the
Bridge Package's "Order and Trade Updates" stream.

Docs: broker-api-docs/iiflcapital-api-docs/06-order-and-trade-updates.md
(packet shapes, connect/subscribe flow), 03-user.md ("Profile", for the
client ID), 05-orders.md ("Order Book" / "Trade Book", for the OpenAlgo
exchange-code mapping used below).
Endpoint: bridge.iiflcapital.com:8883 (same MQTT bridge as market data),
auth is the userSession token — same token used for REST calls.

IMPORTANT ARCHITECTURAL NOTE — why this does NOT subclass BaseOrderUpdateAdapter:
websocket_proxy/order_adapter.py's BaseOrderUpdateAdapter hardcodes a
`websocket.WebSocketApp` (the websocket-client PyPI library, standard wss://
protocol) in `_connect_once()`. IIFL Capital's entire streaming transport —
market data AND order/trade updates alike — is raw MQTT v3.1.1 over a plain
TLS socket (see iiflcapital_mqtt.py's hand-rolled IiflMqttClient, built for
exactly this reason). BaseOrderUpdateAdapter's transport assumption does not
hold for this broker, so this module instead follows the same sanctioned
escape hatch order_adapter.py already documents for Groww's
PollingOrderUpdateAdapter: a standalone, duck-typed peer class implementing
just `connect()` / `disconnect()` / the `connected` property, which is all
services/order_update_service.py's `_build_adapter()` requires. Internally it
opens a SECOND, dedicated IiflMqttClient — separate from whatever connection
broker/iiflcapital/streaming/iiflcapital_adapter.py (market data) happens to
have open — because order/trade updates must stay live regardless of whether
any market-data symbols are subscribed (mirrors zerodha_order_adapter.py's
dedicated, no-instrument ticker connection).

============================================================================
TOPIC STRINGS — confirmed against the official bridgePy SDK source
============================================================================
IIFL's own docs only describe subscribing via the Bridge Package's SDK
method calls, never the raw MQTT topic:

    req = '{"subscriptionList": ["CLIENT101"]}'
    connection_object.subscribe_order_updates(req)
    connection_object.subscribe_trade_updates(req)

The first version of this adapter guessed the raw topic by analogy with the
three confirmed market-feed prefixes (prod/marketfeed/<mw|oi|index>/v1/),
landing on "prod/orderupdate/v1/" / "prod/tradeupdate/v1/". That guess was
WRONG — confirmed by a live MQTT probe against bridge.iiflcapital.com:8883,
where the broker's SUBACK returned 0x80 (rejected) for both.

The real prefixes were found in the official SDK source
(https://github.com/IIFLCapital/BridgePy/blob/main/bridgePy/connector.py):

    self.order_updates = "prod/updates/order/v1/"
    self.trade_updates = "prod/updates/trade/v1/"

and the full topic is built as `topic_prefix + subscriptionList_item`
(connector.py's `_build_subscription_topics`), where the item is validated
against `^[0-9a-z/]+$` (lowercase/digits/slash only) — the IIFL clientId
(numeric, e.g. "78816704") satisfies this. Re-running the same live probe
with these corrected prefixes returned granted QoS 0 (accepted) for both
topics, confirming TOPIC_ORDER_UPDATE / TOPIC_TRADE_UPDATE below are correct.
============================================================================

Order-update packet (JSON, confirmed field names):
    clientId, validity, orderComplexity, product, orderType, tradingSymbol,
    transactionType, instrumentId, price, slTriggerPrice, quantity,
    disclosedQuantity, cancelledQuantity, algoId, marketProtectionPercent,
    placedBy, averageTradedPrice, filledQuantity, pendingQuantity,
    brokerOrderId, exchangeOrderId, rejectionReason, orderStatus,
    exchangeTimestamp, exchangeUpdateTime, mainLegOrderId, validityDate,
    source, comments, brokerUpdateTime.
Notably absent: a plain `exchange` field (trade-update packets have one;
order-update packets do not) — see _resolve_order_exchange() below for how
this adapter compensates.

Trade-update packet (JSON, confirmed field names):
    tradedPrice, filledQuantity, exchangeTradeId, instrumentId, exchange,
    clientId, orderComplexity, product, tradingSymbol, fillDate, fillTime,
    brokerOrderId, exchangeOrderId, transactionType, orderType, placedBy,
    algoId.

`orderStatus` values per 05-orders.md: "Open, Complete, Rejected, Cancelled,
etc." — docs are inconsistent on case (the JSON sample shows lowercase
"rejected", the field table shows title-case), so _STATUS_MAP below is
matched case-insensitively (raw value lower()'d before lookup).
"""

from __future__ import annotations

import base64
import json
import os
import threading
from datetime import datetime

from broker.iiflcapital.api.rate_limiter import apply_rate_limit
from broker.iiflcapital.baseurl import BASE_URL
from broker.iiflcapital.mapping.transform_data import (
    reverse_map_order_type,
    reverse_map_product_type,
)
from broker.iiflcapital.streaming.iiflcapital_mqtt import (
    CONNACK_ACCEPTED,
    IiflMqttClient,
)
from database.auth_db import get_auth_token
from database.token_db import get_symbol
from utils.event_bus import bus
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from websocket_proxy.order_adapter import to_openalgo_symbol

logger = get_logger(__name__)

IIFL_MQTT_HOST = "bridge.iiflcapital.com"
IIFL_MQTT_PORT = 8883

# ============================================================================
# CONFIRMED against the official bridgePy SDK source
# (https://github.com/IIFLCapital/BridgePy/blob/main/bridgePy/connector.py):
#   self.order_updates = "prod/updates/order/v1/"
#   self.trade_updates = "prod/updates/trade/v1/"
# and topic = topic_prefix + subscriptionList_item (see connector.py's
# _build_subscription_topics), where subscriptionList_item is the IIFL
# clientId, validated against ^[0-9a-z/]+$ (lowercase/digits/slash only --
# numeric client IDs like "78816704" satisfy this). The originally-guessed
# "prod/orderupdate/v1/" / "prod/tradeupdate/v1/" prefixes (inferred by
# analogy with the market-feed topics, before this SDK source was available)
# were confirmed WRONG via a live MQTT probe: the broker's SUBACK returned
# 0x80 (rejected) for those, and granted QoS 0 (accepted) for the prefixes
# below. Kept as isolated module-level constants (mirrors TOPIC_MARKET_FEED /
# TOPIC_INDEX_FEED / TOPIC_OPEN_INTEREST in iiflcapital_websocket.py).
# ============================================================================
TOPIC_ORDER_UPDATE = "prod/updates/order/v1/"
TOPIC_TRADE_UPDATE = "prod/updates/trade/v1/"

# orderStatus (order-update packets) -> OpenAlgo's lowercase order_status
# vocabulary. Matched case-insensitively (raw value lower()'d first). Mirrors
# broker/iiflcapital/mapping/order_data.py::_map_status for consistency
# between the REST order book and this streaming feed; kept as a local copy
# since that function is module-private.
_STATUS_MAP = {
    "complete": "complete",
    "completed": "complete",
    "filled": "complete",
    "success": "complete",
    "executed": "complete",
    "rejected": "rejected",
    "fail": "rejected",
    "failed": "rejected",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "trigger_pending": "trigger pending",
    "trigger pending": "trigger pending",
    "open": "open",
    "pending": "open",
    "partially_filled": "open",
    "new": "open",
    "put order req received": "open",
}

# IIFL brexchange segment codes (as carried on trade-update packets'
# `exchange` field, e.g. "NSEEQ") -> OpenAlgo exchange codes. Mirrors
# broker/iiflcapital/mapping/order_data.py::_map_exchange and
# broker/iiflcapital/streaming/iiflcapital_mapping.py's module docstring
# table; kept as a local copy since _map_exchange is module-private.
_IIFL_EXCHANGE_MAP = {
    "NSEEQ": "NSE",
    "BSEEQ": "BSE",
    "NSEFO": "NFO",
    "BSEFO": "BFO",
    "NSECURR": "CDS",
    "BSECURR": "BCD",
    "MCXCOMM": "MCX",
    "NSECOMM": "MCX",
    "NCDEXCOMM": "MCX",
}

# Exchanges probed (in this order) to resolve an order-update packet's
# exchange, since -- unlike trade-update packets -- it carries no plain
# `exchange` field. instrumentId is exchange-scoped, so the first exchange
# whose SymToken table has a (token, exchange) match wins. Small, bounded
# (max 7 O(1) cache lookups); best-effort like to_openalgo_symbol() itself.
_CANDIDATE_EXCHANGES = ("NSE", "BSE", "NFO", "BFO", "MCX", "CDS", "BCD")


def _to_int(value) -> int:
    try:
        if value in (None, "", "-"):
            return 0
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value) -> float:
    try:
        if value in (None, "", "-"):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# transactionType -> OpenAlgo BUY/SELL. Order-update packets observed on a
# live account send the full word ("BUY"/"SELL"), but trade-update packets
# for the SAME fill were observed sending single-letter codes ("B"/"S")
# instead -- confirmed live: an order's order-update packet reported
# action="BUY" while its paired trade-update packet for the identical fill
# reported action="B". Neither IIFL doc page documents this distinction, so
# handle both conventions defensively rather than assume one endpoint's
# format holds for the other.
_ACTION_MAP = {"B": "BUY", "S": "SELL", "BUY": "BUY", "SELL": "SELL"}


def _normalize_action(value) -> str:
    text = str(value or "").strip().upper()
    return _ACTION_MAP.get(text, text)


def _resolve_order_exchange(token: str) -> str:
    """Best-effort resolve the OpenAlgo exchange for an order-update packet's
    instrumentId. Returns "" if the master contract for this instrument isn't
    loaded under any candidate exchange (e.g. contract not yet downloaded)."""
    if not token:
        return ""
    for exchange in _CANDIDATE_EXCHANGES:
        if get_symbol(token, exchange):
            return exchange
    return ""


def _decode_jwt_username(token: str) -> str:
    """Extract `preferred_username` from the userSession JWT.

    Duplicated from iiflcapital_websocket.py::_decode_jwt_username (kept
    local rather than imported, since that symbol is module-private) so this
    adapter can build the same "OPENID~~<token>~" bridgePy-format MQTT
    username/password pair the market-feed client uses for the same broker.
    Raises ValueError on a malformed/expired token.
    """
    try:
        payload_segment = token.split(".")[1]
        padding_needed = (4 - len(payload_segment) % 4) % 4
        padded = payload_segment + ("=" * padding_needed)
        decoded = base64.urlsafe_b64decode(padded)
        claims = json.loads(decoded)
    except Exception as exc:
        raise ValueError(f"Invalid IIFL user_session JWT: {type(exc).__name__}") from exc

    username = claims.get("preferred_username")
    if not username:
        raise ValueError("IIFL JWT missing 'preferred_username' claim")
    return str(username)


class IiflCapitalOrderUpdateAdapter:
    """
    Dedicated order/trade-update MQTT adapter for IIFL Capital.

    Does NOT inherit BaseOrderUpdateAdapter (see module docstring for why —
    IIFL's transport is MQTT, not a plain WebSocket). Implements the same
    connect() / disconnect() / connected surface PollingOrderUpdateAdapter
    uses, which is all services/order_update_service.py's _build_adapter()
    requires to manage either kind of adapter uniformly.

    One dedicated IiflMqttClient per instance, opened fresh on every
    (re)connect (clean_session=True — subscriptions never survive a
    reconnect, so on_connect always re-subscribes both topics).
    """

    # Mirrors iiflcapital_websocket.py's IiflcapitalWebSocket reconnect
    # settings for parity across the two IIFL streaming adapters.
    RECONNECT_MAX_DELAY = 60
    RECONNECT_MAX_TRIES = 50

    def __init__(self, user_id: str, auth_token: str):
        self.broker_name = "iiflcapital"
        self.user_id = user_id
        self.auth_token = auth_token
        self.logger = get_logger("order_adapter_iiflcapital")

        self._client_id: str | None = None
        self._mqtt: IiflMqttClient | None = None
        self._lock = threading.Lock()
        self._running = False
        self._shutting_down = False
        self._connected = False
        self._fatal_error = False
        self._thread: threading.Thread | None = None
        # Woken by disconnect() to cut short a pending reconnect backoff.
        self._reconnect_event = threading.Event()

    # -- lifecycle -----------------------------------------------------------

    def connect(self) -> None:
        """Start the background connection thread. Idempotent."""
        with self._lock:
            if self._running:
                return
            self._shutting_down = False
            self._running = True
            self._thread = threading.Thread(
                target=self._run_forever,
                daemon=True,
                name=f"order-adapter-iiflcapital-{self.user_id}",
            )
            self._thread.start()

    def disconnect(self) -> None:
        """Stop the adapter and close the MQTT socket. FD-safe (close-before-
        reconnect), idempotent."""
        with self._lock:
            self._shutting_down = True
            self._running = False
            self._connected = False
            mqtt_client = self._mqtt
            self._mqtt = None
        self._reconnect_event.set()
        if mqtt_client is not None:
            try:
                mqtt_client.disconnect()
            except Exception:
                self.logger.debug(
                    "Error disconnecting IIFL order-update MQTT client", exc_info=True
                )

    @property
    def connected(self) -> bool:
        return self._connected

    # -- internals: connection supervisor ------------------------------------

    def _run_forever(self) -> None:
        """IiflMqttClient has no built-in reconnect loop (unlike
        IiflcapitalWebSocket, which wraps one around it for market data) --
        this is the minimal supervisor loop that plays that role here,
        mirroring IiflcapitalWebSocket._reconnect_loop's backoff formula."""
        attempt = 0
        while not self._shutting_down:
            self._fetch_client_id_if_needed()

            connected_this_attempt = False
            try:
                connected_this_attempt = self._connect_once()
            except Exception as e:
                self.logger.warning(
                    f"IIFL order-update connection error for user {self.user_id}: {e}"
                )

            if connected_this_attempt:
                # A real connection was established (even if it later
                # dropped) -- reset backoff so a long-stable session
                # followed by a single blip doesn't inherit a huge delay.
                attempt = 0

            if self._shutting_down or self._fatal_error:
                break

            delay = min(2 * (1.5**attempt), self.RECONNECT_MAX_DELAY)
            attempt += 1
            if attempt > self.RECONNECT_MAX_TRIES:
                self.logger.error(
                    f"IIFL order-update reconnect attempts exhausted for user {self.user_id}"
                )
                break

            self.logger.info(
                f"IIFL order-update reconnect attempt {attempt} in {delay:.0f}s "
                f"(user {self.user_id})"
            )
            self._reconnect_event.clear()
            self._reconnect_event.wait(timeout=delay)
            if self._shutting_down:
                break

            # Sessions roll ~3 AM IST; re-read before reconnecting so a
            # stale construction-time token isn't reused indefinitely
            # (mirrors iiflcapital_websocket.py's _refresh_user_session).
            fresh_token = get_auth_token(self.user_id, bypass_cache=True)
            if fresh_token:
                self.auth_token = fresh_token
            else:
                self.logger.warning(
                    f"IIFL order-update: no auth token found for user {self.user_id} "
                    "on reconnect; retrying with the last known token"
                )

        self._running = False
        self.logger.info(f"IIFL order-update adapter stopped for user {self.user_id}")

    def _connect_once(self) -> bool:
        """Open one dedicated MQTT connection and block until it disconnects.

        Returns True if the broker accepted the connection at any point
        during this attempt (used by _run_forever to reset backoff), False
        if the handshake itself failed or was refused.
        """
        disconnected_event = threading.Event()

        def on_connect(rc, reason):
            if rc != CONNACK_ACCEPTED:
                self.logger.error(
                    f"IIFL order-update CONNACK refused for user {self.user_id}: {reason}"
                )
                if rc in (4, 5):  # bad credentials / not authorized -- token is dead
                    self._fatal_error = True
                disconnected_event.set()
                return
            with self._lock:
                self._connected = True
            self.logger.info(f"IIFL order-update MQTT connected for user {self.user_id}")
            self._subscribe_topics()

        def on_disconnect(_exc):
            with self._lock:
                self._connected = False
            disconnected_event.set()

        def on_message(topic, payload):
            self._handle_message(topic, payload)

        def on_error(exc):
            self.logger.warning(f"IIFL order-update MQTT error for user {self.user_id}: {exc}")

        try:
            username = _decode_jwt_username(self.auth_token)
        except ValueError as e:
            self.logger.error(
                f"IIFL order-update: cannot build MQTT credentials for user {self.user_id}: {e}"
            )
            self._fatal_error = True
            return False

        mqtt_client = IiflMqttClient(
            host=IIFL_MQTT_HOST,
            port=IIFL_MQTT_PORT,
            client_id=self._make_client_id(),
            username=username,
            password=f"OPENID~~{self.auth_token}~",  # bridgePy format
            keepalive=20,
        )
        mqtt_client.on_connect = on_connect
        mqtt_client.on_disconnect = on_disconnect
        mqtt_client.on_message = on_message
        mqtt_client.on_error = on_error

        with self._lock:
            self._mqtt = mqtt_client

        try:
            rc = mqtt_client.connect(timeout=15.0)
        except Exception:
            with self._lock:
                if self._mqtt is mqtt_client:
                    self._mqtt = None
            raise

        if rc != CONNACK_ACCEPTED:
            with self._lock:
                if self._mqtt is mqtt_client:
                    self._mqtt = None
            return False

        # Blocks until the reader thread observes a disconnect (broker drop,
        # our own disconnect() calling mqtt_client.disconnect(), or any
        # socket error) -- mirrors BaseOrderUpdateAdapter._connect_once()'s
        # run_forever() blocking call for a plain WebSocket.
        disconnected_event.wait()

        with self._lock:
            if self._mqtt is mqtt_client:
                self._mqtt = None
            self._connected = False
        return True

    def _make_client_id(self) -> str:
        # Distinct prefix from the market-feed adapter's "openalgo" + suffix
        # scheme (iiflcapital_websocket.py) so the two dedicated MQTT
        # sessions (market-data, order-update) never collide on client_id --
        # IIFL drops the OLDER session on a collision (CONNACK rc=2).
        return (
            "openalgo-orderupdate" + datetime.now().strftime("%d%m%y%H%M%S%f") + os.urandom(4).hex()
        )

    # -- internals: client ID resolution --------------------------------------

    def _fetch_client_id_if_needed(self) -> None:
        with self._lock:
            have_it = bool(self._client_id)
        if not have_it:
            self._fetch_client_id()

    def _fetch_client_id(self) -> None:
        """Resolve the IIFL client ID via GET /profile (authenticate_broker()
        receives a client_id at OAuth login time but never persists it — see
        broker/iiflcapital/api/auth_api.py — so this adapter fetches its own
        copy). Best-effort: any failure is logged and swallowed so the caller
        can still bring the MQTT link up and retry client-ID resolution on
        the next reconnect, rather than crashing the adapter outright.
        """
        try:
            client = get_httpx_client()
            headers = {
                "Authorization": f"Bearer {self.auth_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            apply_rate_limit()
            response = client.get(f"{BASE_URL}/profile", headers=headers)
            data = response.json()
        except Exception as e:
            self.logger.warning(
                f"IIFL order-update: profile fetch failed for user {self.user_id} "
                f"(client ID unresolved -- order/trade updates may not work "
                f"until this succeeds): {e}"
            )
            return

        if response.status_code != 200:
            self.logger.warning(
                f"IIFL order-update: profile fetch returned HTTP {response.status_code} "
                f"for user {self.user_id} (client ID unresolved)"
            )
            return

        result = data.get("result") if isinstance(data, dict) else None
        client_id = result.get("clientId") if isinstance(result, dict) else None
        if not client_id:
            self.logger.warning(
                f"IIFL order-update: profile response missing clientId for user "
                f"{self.user_id} (order/trade updates may not work without it)"
            )
            return

        with self._lock:
            self._client_id = str(client_id)
        self.logger.info(f"IIFL order-update: resolved client ID for user {self.user_id}")

    def _subscribe_topics(self) -> None:
        if not self._client_id:
            self._fetch_client_id()
        if not self._client_id:
            self.logger.warning(
                f"IIFL order-update: no client ID available for user {self.user_id}; "
                "skipping subscribe -- order/trade updates will not be received "
                "until a client ID can be resolved on a future reconnect"
            )
            return

        topics = [TOPIC_ORDER_UPDATE + self._client_id, TOPIC_TRADE_UPDATE + self._client_id]
        mqtt_client = self._mqtt
        if mqtt_client is None:
            return
        try:
            mqtt_client.subscribe(topics, qos=0)
            self.logger.info(
                f"IIFL order-update: subscribed order/trade update topics for user {self.user_id}"
            )
        except Exception as e:
            self.logger.exception(
                f"IIFL order-update subscribe failed for user {self.user_id}: {e}"
            )

    # -- internals: message handling / normalization --------------------------

    def _handle_message(self, topic: str, payload: bytes) -> None:
        try:
            data = json.loads(payload.decode("utf-8"))
        except Exception as e:
            self.logger.debug(f"IIFL order-update: could not decode message on {topic}: {e}")
            return
        if not isinstance(data, dict):
            return

        if topic.startswith(TOPIC_ORDER_UPDATE):
            fields = self.normalize("order", data)
        elif topic.startswith(TOPIC_TRADE_UPDATE):
            fields = self.normalize("trade", data)
        else:
            self.logger.debug(f"IIFL order-update: message on unrecognized topic {topic}")
            return

        if not fields:
            return
        self._publish_event_fields(fields)

    def normalize(self, message_kind: str, data: dict) -> dict | None:
        """
        Parse one decoded order-update or trade-update JSON packet into
        kwargs for events.OrderUpdateEvent. `message_kind` is "order" or
        "trade" depending on which topic the packet arrived on (see
        _handle_message). Uses OpenAlgo's common field-name vocabulary (see
        websocket_proxy/order_adapter.py's BaseOrderUpdateAdapter.normalize()
        docstring): orderid, symbol, exchange, action, quantity, price,
        trigger_price, pricetype, product, order_status, filled_quantity,
        pending_quantity, average_price, rejection_reason.
        """
        if message_kind == "order":
            return self._normalize_order(data)
        if message_kind == "trade":
            return self._normalize_trade(data)
        return None

    def _normalize_order(self, data: dict) -> dict:
        raw_status = str(data.get("orderStatus", "")).strip().lower()
        order_status = _STATUS_MAP.get(raw_status, "open")

        token = str(data.get("instrumentId") or "")
        trading_symbol = str(data.get("tradingSymbol") or "")
        # Order-update packets carry no `exchange` field (unlike trade-update
        # packets) -- resolve it via the instrumentId probe above.
        exchange = _resolve_order_exchange(token)
        symbol = (
            to_openalgo_symbol(trading_symbol, exchange, token=token)
            if exchange
            else trading_symbol
        )

        return {
            "orderid": str(data.get("brokerOrderId") or data.get("exchangeOrderId") or ""),
            "symbol": symbol,
            "exchange": exchange,
            "action": _normalize_action(data.get("transactionType")),
            "quantity": _to_int(data.get("quantity")),
            "price": _to_float(data.get("price")),
            "trigger_price": _to_float(data.get("slTriggerPrice")),
            "pricetype": reverse_map_order_type(str(data.get("orderType") or "")),
            "product": reverse_map_product_type(str(data.get("product") or "")),
            "order_status": order_status,
            "filled_quantity": _to_int(data.get("filledQuantity")),
            "pending_quantity": _to_int(data.get("pendingQuantity")),
            "average_price": _to_float(data.get("averageTradedPrice")),
            "rejection_reason": (
                str(data.get("rejectionReason") or "") if order_status == "rejected" else ""
            ),
        }

    def _normalize_trade(self, data: dict) -> dict:
        token = str(data.get("instrumentId") or "")
        trading_symbol = str(data.get("tradingSymbol") or "")
        broker_exchange = str(data.get("exchange") or "").upper()
        exchange = _IIFL_EXCHANGE_MAP.get(broker_exchange, broker_exchange)
        symbol = (
            to_openalgo_symbol(trading_symbol, exchange, token=token)
            if exchange
            else trading_symbol
        )

        filled_qty = _to_int(data.get("filledQuantity"))
        traded_price = _to_float(data.get("tradedPrice"))

        return {
            "orderid": str(data.get("brokerOrderId") or data.get("exchangeOrderId") or ""),
            "symbol": symbol,
            "exchange": exchange,
            "action": _normalize_action(data.get("transactionType")),
            # Trade-update packets carry only this fill's own quantity, not
            # the parent order's total (no `quantity`/`pendingQuantity`
            # field) -- best-effort proxy using the fill quantity.
            "quantity": filled_qty,
            "price": traded_price,
            "trigger_price": 0.0,
            "pricetype": reverse_map_order_type(str(data.get("orderType") or "")),
            "product": reverse_map_product_type(str(data.get("product") or "")),
            # A trade-update packet only ever fires for an actual execution,
            # so "complete" describes THIS fill -- it does not assert the
            # whole parent order is done if it was filled across multiple
            # trade packets. The paired order-update packet's orderStatus /
            # pendingQuantity remains authoritative for the order's overall
            # state; this event is supplementary per-fill detail (exact
            # execution price/time/exchangeTradeId) the order-update stream
            # doesn't carry.
            "order_status": "complete",
            "filled_quantity": filled_qty,
            "pending_quantity": 0,
            "average_price": traded_price,
            "rejection_reason": "",
        }

    def _publish_event_fields(self, fields: dict) -> None:
        fields.setdefault("mode", "live")
        fields.setdefault("broker", self.broker_name)
        fields.setdefault("request_data", {"user_id": self.user_id})
        fields.setdefault("api_type", f"{self.broker_name}.order_update")

        try:
            from events import OrderUpdateEvent

            bus.publish(OrderUpdateEvent(**fields))
        except Exception:
            self.logger.exception("Failed to publish IIFL Capital OrderUpdateEvent")


def create_iiflcapital_order_adapter(user_id: str) -> IiflCapitalOrderUpdateAdapter | None:
    """
    Factory: build an IiflCapitalOrderUpdateAdapter for user_id.

    The stored DB auth token IS the userSession -- the same token used for
    every REST call (see broker/iiflcapital/api/auth_api.py::authenticate_broker
    and iiflcapital_adapter.py's initialize(), which sources the market-data
    connection's token the same way).
    """
    auth_token = get_auth_token(user_id, bypass_cache=True)
    if not auth_token:
        logger.warning(
            f"No IIFL Capital auth token found for user {user_id}; order-update adapter not started"
        )
        return None

    return IiflCapitalOrderUpdateAdapter(user_id=user_id, auth_token=auth_token)
