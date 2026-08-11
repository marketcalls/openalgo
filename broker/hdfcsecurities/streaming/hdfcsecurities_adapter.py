"""HDFC Securities InvestRight WebSocket adapter -> OpenAlgo unified streaming.

Subclasses BaseBrokerWebSocketAdapter. Resolves OpenAlgo (symbol, exchange) to
InvestRight scripIds, drives the HDFCSecuritiesWebSocket client, normalizes
protobuf ticks and publishes them to the ZeroMQ bus via the inherited
publish_market_data().

NSE_INDEX / BSE_INDEX are first-class: the feed has dedicated NSE_INDEX_ /
BSE_INDEX_ scripId prefixes, and the publish topic keeps the OpenAlgo exchange
(the proxy already recognizes both as two-segment prefixes when splitting
topics).

Two properties of the feed shape the state kept here:

  - `instrumentId` is unique only WITHIN an exchange. 840 tokens in the live
    security master appear on more than one OpenAlgo exchange, so subscription
    state is keyed (exchange, token) and the exchange is taken from the tick's
    packet type, never guessed from the token alone.
  - The *_CIRC and *_OI packets are partial refreshes carrying no price. They
    are merged into the last full snapshot for that instrument rather than
    published as a quote of their own, which would blank the live price.
"""

import sys
import threading

from broker.hdfcsecurities.mapping.transform_data import ws_scrip_id
from broker.hdfcsecurities.streaming.hdfcsecurities_mapping import (
    HDFCSecuritiesCapabilityRegistry,
)
from broker.hdfcsecurities.streaming.hdfcsecurities_websocket import HDFCSecuritiesWebSocket
from database.auth_db import get_auth_token
from database.token_db import get_token
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

# OpenAlgo numeric mode -> topic suffix. The proxy fans a published mode DOWN to
# lower-mode subscribers (server.py: `for m in range(1, mode + 1)`) and never
# up, so an instrument must always be published at the HIGHEST mode any client
# subscribed it at. Publishing at a lower mode starves the higher-mode clients
# completely.
_MODE_TO_TOPIC = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}

# The feed runs on a real OS thread (see hdfcsecurities_websocket), so the
# subscription-state lock must be a real lock too -- an eventlet-patched one
# taken from a foreign thread does not block correctly.
if "eventlet" in sys.modules:
    import eventlet

    _real_threading = eventlet.patcher.original("threading")
else:
    _real_threading = threading

# Partial-refresh packet kinds and the fields each one is allowed to carry over
# into the merged snapshot.
_PARTIAL_TICK_FIELDS = {
    "circuit": ("lower_limit", "upper_limit"),
    "oi": ("oi",),
}


class HDFCSecuritiesWebSocketAdapter(BaseBrokerWebSocketAdapter):
    def __init__(self):
        super().__init__()
        self.broker_name = "hdfcsecurities"
        self.user_id = None
        self.ws_client: HDFCSecuritiesWebSocket | None = None
        self.running = False
        # (exchange, token) -> {"symbol", "exchange", "modes", "scrip_id"}
        self.token_info: dict[tuple[str, int], dict] = {}
        # (exchange, token) -> last full snapshot, so a partial circuit/OI
        # packet can be merged instead of replacing the quote.
        self.last_snapshot: dict[tuple[str, int], dict] = {}
        # Serializes subscribe/unsubscribe against each other. The tick thread
        # never takes it: it only reads immutable entries.
        self._state_lock = _real_threading.Lock()

    # --- lifecycle ------------------------------------------------------

    def initialize(self, broker_name, user_id, auth_data=None):
        try:
            self.broker_name = broker_name
            self.user_id = user_id

            if auth_data and auth_data.get("token"):
                access_token = auth_data["token"]
            else:
                access_token = get_auth_token(user_id, bypass_cache=True)

            if not access_token:
                return self._create_error_response(
                    "NO_AUTH_TOKEN",
                    f"No HDFC Securities auth token found for user {user_id}",
                )

            self.ws_client = HDFCSecuritiesWebSocket(
                access_token=access_token,
                on_ticks=self._on_ticks,
                user_id=user_id,
            )
            # Keep self.connected truthful: the proxy gates adapter reuse on it
            # (server.py getattr(adapter, "connected", ...)); without these
            # hooks healthy adapters read as dead and get evicted/rebuilt.
            self.ws_client.on_connect = self._on_ws_connect
            self.ws_client.on_disconnect = self._on_ws_disconnect
            self.logger.info(f"HDFC Securities adapter initialized for user {user_id}")
            return self._create_success_response("HDFC Securities adapter initialized")
        except Exception as e:
            self.logger.exception(f"Error initializing HDFC Securities adapter: {e}")
            return self._create_error_response("INIT_ERROR", str(e))

    def _on_ws_connect(self):
        self.connected = True

    def _on_ws_disconnect(self):
        self.connected = False

    def connect(self):
        try:
            if not self.ws_client:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")
            self.ws_client.start()
            self.running = True
            # Best-effort wait; subscriptions queue until connected regardless.
            self.ws_client.wait_for_connection(timeout=15.0)
            self.connected = self.ws_client.is_connected()
            return self._create_success_response("HDFC Securities WebSocket connecting")
        except Exception as e:
            self.logger.exception(f"Error connecting HDFC Securities WebSocket: {e}")
            return self._create_error_response("CONNECT_ERROR", str(e))

    def disconnect(self):
        try:
            self.running = False
            self.connected = False
            if self.ws_client:
                self.ws_client.stop()
        except Exception as e:
            self.logger.exception(f"Error disconnecting HDFC Securities WebSocket: {e}")
        finally:
            # Drop the merge baselines: they rebuild from the first full tick
            # after a reconnect, and a pre-disconnect price must never be
            # republished as current. token_info deliberately survives -- the
            # client resubscribes its scrips and the ticks still need mapping.
            self.last_snapshot.clear()
            # Always release ZMQ resources (FD hygiene).
            self.cleanup_zmq()

    # --- subscription ---------------------------------------------------

    def _store_info(self, key, symbol, exchange, scrip_id, modes):
        """Publish a NEW immutable state entry for an instrument.

        The tick thread reads this map without locking, so an entry is never
        edited in place: `modes` is a frozenset and the whole dict is replaced,
        which under the GIL means a reader sees either the old entry or the new
        one but never a half-updated one. `topic_mode` is precomputed here so
        the tick path does no iteration at all -- calling max() over a set that
        subscribe/unsubscribe was mutating is what dropped ticks.
        """
        self.token_info[key] = {
            "symbol": symbol,
            "exchange": exchange,
            "scrip_id": scrip_id,
            "modes": modes,
            "topic_mode": _MODE_TO_TOPIC.get(max(modes), "QUOTE"),
        }

    def _resolve_token(self, symbol, exchange):
        token = get_token(symbol, exchange)
        if token is None:
            return None
        try:
            return int(token)
        except (ValueError, TypeError):
            self.logger.error(
                f"Non-integer HDFC Securities token for {exchange}:{symbol}: {token!r}"
            )
            return None

    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        try:
            if not self.ws_client:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")

            token = self._resolve_token(symbol, exchange)
            if token is None:
                return self._create_error_response(
                    "TOKEN_NOT_FOUND", f"No token for {exchange}:{symbol}"
                )

            key = (exchange, token)
            scrip_id = ws_scrip_id(exchange, token)

            # Several clients can hold the same instrument at different modes.
            # Keep every subscribed mode so publishing (and the broker-side
            # subscription tier) always follows the highest one.
            with self._state_lock:
                existing = self.token_info.get(key)
                modes = (existing["modes"] if existing else frozenset()) | {mode}
                self._store_info(key, symbol, exchange, scrip_id, modes)

            subscription_type = HDFCSecuritiesCapabilityRegistry.get_subscription_type_for_numeric(
                max(modes)
            )
            self.ws_client.subscribe_scrips([scrip_id], subscription_type)

            # InvestRight publishes 5-level depth only; advertise the actual
            # depth so the proxy reports it back to the client.
            actual_depth = HDFCSecuritiesCapabilityRegistry.get_fallback_depth_level(
                depth_level, exchange
            )
            return self._create_success_response(
                f"Subscribed {exchange}:{symbol}",
                symbol=symbol,
                exchange=exchange,
                mode=mode,
                actual_depth=actual_depth if mode == 3 else None,
            )
        except Exception as e:
            self.logger.exception(f"Error subscribing {exchange}:{symbol}: {e}")
            return self._create_error_response("SUBSCRIBE_ERROR", str(e))

    def unsubscribe(self, symbol, exchange, mode=2):
        try:
            if not self.ws_client:
                return self._create_error_response("NOT_INITIALIZED", "Call initialize() first")
            token = self._resolve_token(symbol, exchange)
            if token is None:
                return self._create_error_response(
                    "TOKEN_NOT_FOUND", f"No token for {exchange}:{symbol}"
                )

            key = (exchange, token)
            scrip_id = ws_scrip_id(exchange, token)

            with self._state_lock:
                info = self.token_info.get(key)
                # The proxy only calls this once the last client at THIS mode
                # has gone; other modes may still have clients, so drop the
                # broker subscription only when no mode is left.
                modes = (info["modes"] - {mode}) if info else frozenset()
                if modes:
                    self._store_info(key, symbol, exchange, scrip_id, modes)
                else:
                    self.token_info.pop(key, None)
                    self.last_snapshot.pop(key, None)

            if modes:
                self.ws_client.subscribe_scrips(
                    [scrip_id],
                    HDFCSecuritiesCapabilityRegistry.get_subscription_type_for_numeric(max(modes)),
                )
            else:
                self.ws_client.unsubscribe([scrip_id])
            return self._create_success_response(f"Unsubscribed {exchange}:{symbol}")
        except Exception as e:
            self.logger.exception(f"Error unsubscribing {exchange}:{symbol}: {e}")
            return self._create_error_response("UNSUBSCRIBE_ERROR", str(e))

    # --- tick handling --------------------------------------------------

    def _subscription_key(self, tick):
        """(exchange, token) for a tick, or None when it is not ours.

        The exchange comes from the packet type. It is absent only for packet
        types outside the documented enum, and those fall back to a token
        lookup that is used only when it is unambiguous -- guessing would
        publish one instrument's ticks under another's symbol.
        """
        token = tick.get("token")
        if token is None:
            return None
        exchange = tick.get("exchange")
        if exchange:
            key = (exchange, token)
            return key if key in self.token_info else None

        # list() snapshots the keys in one C-level step, so a concurrent
        # subscribe cannot break this scan.
        matches = [key for key in list(self.token_info) if key[1] == token]
        if len(matches) == 1:
            return matches[0]
        if matches:
            self.logger.debug(
                f"Dropping HDFC Securities tick for token {token}: no exchange on packet type "
                f"{tick.get('packet_type')} and {len(matches)} subscribed instruments share it"
            )
        return None

    def _on_ticks(self, ticks):
        for tick in ticks:
            try:
                key = self._subscription_key(tick)
                if key is None:
                    continue
                info = self.token_info[key]
                # Greek packets have no price fields; they arrive alongside the
                # MBP stream for options and are not part of the OpenAlgo tick
                # contract, so they are dropped here.
                if tick.get("kind") == "greek":
                    continue

                symbol = info["symbol"]
                exchange = info["exchange"]
                # Precomputed at subscribe time and always the highest
                # subscribed mode (the proxy fans down only). Reading it costs
                # one dict lookup, so a concurrent subscribe/unsubscribe cannot
                # make the tick path fail mid-iteration.
                topic_mode = info["topic_mode"]

                tick = self._merge_partial(key, tick)
                if tick is None:
                    continue

                data = self._normalize(tick, symbol, exchange, topic_mode)
                self.publish_market_data(f"{exchange}_{symbol}_{topic_mode}", data)
            except Exception as e:
                self.logger.error(f"Error handling HDFC Securities tick: {e}")

    def _merge_partial(self, key, tick):
        """Resolve a partial circuit/OI packet against the last full snapshot.

        Circuit and OI packets share MBPData with the full quote but populate
        only their own fields, so every price on them reads as the proto3
        default of 0. Publishing one as-is would replace a live quote with
        zeros. Returns the tick to publish, or None when there is no snapshot
        to merge into yet.
        """
        kind = tick.get("kind")
        fields = _PARTIAL_TICK_FIELDS.get(kind)
        if fields is None:
            # A full quote or index packet: this is the new baseline.
            self.last_snapshot[key] = tick
            return tick

        snapshot = self.last_snapshot.get(key)
        if snapshot is None:
            # Nothing to attach the update to; a standalone band or OI value is
            # not a publishable tick.
            return None

        merged = dict(snapshot)
        for field in fields:
            if field in tick:
                merged[field] = tick[field]
        merged["timestamp"] = tick.get("timestamp", merged.get("timestamp"))
        self.last_snapshot[key] = merged
        return merged

    def _normalize(self, tick, symbol, exchange, topic_mode):
        """Build the OpenAlgo normalized tick (same key set as the Zerodha
        adapter so the proxy/UI see one shape across brokers)."""
        ltp = tick.get("ltp", 0)
        data = {
            "symbol": symbol,
            "exchange": exchange,
            "token": str(tick.get("token", "")),
            "ltp": ltp,
            "last_price": ltp,
            "ltt": tick.get("ltt", tick.get("timestamp")),
            "timestamp": tick.get("timestamp"),
        }

        close = tick.get("close")
        if close is not None:
            data["close"] = close
            data["prev_close"] = close
            if close:
                change = ltp - close
                data["change"] = round(change, 2)
                data["change_percent"] = round(change / close * 100, 2)

        if topic_mode in ("QUOTE", "DEPTH"):
            data["volume"] = tick.get("volume", 0)
            data["last_quantity"] = tick.get("ltq", 0)
            data["average_price"] = tick.get("average_price", 0)
            data["total_buy_quantity"] = tick.get("total_buy_quantity", 0)
            data["total_sell_quantity"] = tick.get("total_sell_quantity", 0)
            for key in ("open", "high", "low"):
                if key in tick:
                    data[key] = tick[key]
            if "oi" in tick:
                data["oi"] = tick["oi"]
                data["open_interest"] = tick["oi"]

        if topic_mode == "DEPTH":
            if "depth" in tick:
                data["depth"] = tick["depth"]
            if "upper_limit" in tick:
                data["upper_circuit"] = tick["upper_limit"]
                data["lower_circuit"] = tick["lower_limit"]

        return data
