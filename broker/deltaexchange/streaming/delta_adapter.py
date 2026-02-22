"""
delta_adapter.py
OpenAlgo WebSocket adapter for Delta Exchange.

Channels used:
  v2/ticker    — real-time OHLCV + mark_price + OI + best bid/ask
  l2_orderbook — 5-level order book (depth mode)

Authentication:
  HMAC-SHA256 auth message sent on every (re)connect.
  Signature = HMAC-SHA256(api_secret, "GET" + timestamp + "/live")
"""

import json
import logging
import threading
import time
from typing import Any

from broker.deltaexchange.streaming.delta_websocket import DeltaWebSocket
from broker.deltaexchange.streaming.delta_mapping import (
    DeltaCapabilityRegistry,
    DeltaExchangeMapper,
    DeltaModeMapper,
)
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper


class DeltaWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Delta Exchange–specific implementation of the BaseBrokerWebSocketAdapter."""

    def __init__(self):
        super().__init__()
        self.logger       = logging.getLogger("delta_websocket_adapter")
        self.ws_client    = None
        self.user_id      = None
        self.broker_name  = "deltaexchange"
        self.running      = False
        self._lock        = threading.Lock()
        self.last_values: dict[str, dict] = {}

    # ── BaseBrokerWebSocketAdapter interface ──────────────────────────────────

    def initialize(
        self,
        broker_name: str,
        user_id: str,
        auth_data: dict | None = None,
    ) -> None:
        """
        Fetch credentials and build the DeltaWebSocket client.

        auth_data may carry:
            api_key    / access_token — the Delta Exchange API key
            api_secret               — the Delta Exchange API secret
        """
        self.user_id     = user_id
        self.broker_name = broker_name

        if auth_data:
            api_key    = auth_data.get("api_key") or auth_data.get("access_token", "")
            api_secret = auth_data.get("api_secret", "")
        else:
            # OpenAlgo stores the api_key as the auth token
            api_key    = get_auth_token(user_id) or ""
            api_secret = ""   # Will be empty unless the DB is extended to store secret

        if not api_key:
            raise ValueError(f"No API key found for user {user_id}")

        self.ws_client = DeltaWebSocket(
            api_key    = api_key,
            api_secret = api_secret,
            on_open    = self._on_open,
            on_message = self._on_data,
            on_error   = self._on_error,
            on_close   = self._on_close,
            max_retry_attempt = 5,
            retry_delay       = 5,
            retry_multiplier  = 2,
        )

        self.running = True
        self.logger.info("DeltaWebSocketAdapter initialised for user %s", user_id)

    def connect(self) -> None:
        """Spin up the WebSocket connection in a daemon thread."""
        if not self.ws_client:
            self.logger.error("Call initialize() before connect()")
            return
        threading.Thread(target=self.ws_client.connect, daemon=True).start()

    def disconnect(self) -> None:
        """Close connection and clean up ZeroMQ resources."""
        self.running = False
        if self.ws_client:
            self.ws_client.close_connection()
        self.cleanup_zmq()

    def subscribe(
        self,
        symbol: str,
        exchange: str,
        mode: int = 2,
        depth_level: int = 1,
    ) -> dict[str, Any]:
        """
        Subscribe to market data for a single symbol.

        Modes:
          1 — LTP         → v2/ticker
          2 — Quote       → v2/ticker  (includes bid/ask/OI)
          3 — Depth       → l2_orderbook
        """
        if not DeltaCapabilityRegistry.supports_mode(mode):
            return self._create_error_response(
                "INVALID_MODE",
                f"Mode {mode} not supported by Delta Exchange. Supported: {DeltaCapabilityRegistry.subscription_modes}",
            )

        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"{symbol} not found for exchange {exchange}"
            )

        br_symbol = token_info.get("brexchange_symbol") or token_info.get("token") or symbol
        channel   = DeltaModeMapper.get_channel(mode)
        corr_id   = f"{symbol}_{exchange}_{mode}"

        with self._lock:
            self.subscriptions[corr_id] = {
                "symbol":    symbol,
                "exchange":  exchange,
                "br_symbol": br_symbol,
                "mode":      mode,
                "channel":   channel,
                "depth_level": depth_level,
            }

        if self.connected and self.ws_client:
            try:
                if channel == DeltaWebSocket.CHANNEL_TICKER:
                    self.ws_client.subscribe_ticker([br_symbol])
                else:
                    self.ws_client.subscribe_l2_orderbook([br_symbol])
                self.logger.info("Subscribed: %s.%s mode=%s channel=%s", symbol, exchange, mode, channel)
            except Exception as exc:
                self.logger.error("subscribe error %s.%s: %s", symbol, exchange, exc)
                return self._create_error_response("SUBSCRIPTION_ERROR", str(exc))
        else:
            self.logger.info("Buffered subscription for %s.%s (not yet connected)", symbol, exchange)

        return self._create_success_response(
            f"Subscription requested for {symbol}.{exchange}",
            symbol=symbol, exchange=exchange, mode=mode, channel=channel,
        )

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        """Unsubscribe from market data for a symbol."""
        channel = DeltaModeMapper.get_channel(mode)
        corr_id = f"{symbol}_{exchange}_{mode}"

        should_disconnect      = False
        should_upstream_unsub  = False
        with self._lock:
            # Read the stored br_symbol that was resolved at subscribe() time
            # before removing the entry.  This guarantees the upstream unsubscribe
            # uses exactly the same symbol string that was passed to the WebSocket
            # at subscription time (brexchange_symbol → token → symbol fallback
            # chain), avoiding a mismatch when brexchange_symbol is absent and
            # the token was used instead.
            stored = self.subscriptions.pop(corr_id, None)
            br_symbol = (stored or {}).get("br_symbol") or symbol

            remaining = list(self.subscriptions.values())

            # Only send the upstream unsubscribe when no remaining subscription
            # still needs this br_symbol + channel (e.g. mode 1 and mode 2 both
            # map to v2/ticker — removing one must not kill the shared stream).
            should_upstream_unsub = not any(
                s.get("br_symbol") == br_symbol and s.get("channel") == channel
                for s in remaining
            )

            # Only drop the LTP cache when no other mode for this symbol/exchange
            # remains (the cache is keyed on symbol_exchange, shared across modes).
            cache_key = f"{symbol}_{exchange}"
            if not any(
                s.get("symbol") == symbol and s.get("exchange") == exchange
                for s in remaining
            ):
                self.last_values.pop(cache_key, None)

            if not remaining:
                should_disconnect = True

        if self.connected and self.ws_client and should_upstream_unsub:
            try:
                if channel == DeltaWebSocket.CHANNEL_TICKER:
                    self.ws_client.unsubscribe_ticker([br_symbol])
                else:
                    self.ws_client.unsubscribe_l2_orderbook([br_symbol])
            except Exception as exc:
                self.logger.error("unsubscribe error %s.%s: %s", symbol, exchange, exc)
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(exc))

        if should_disconnect:
            self.logger.info("No subscriptions remaining — disconnecting.")
            self.disconnect()

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
        )

    # ── internal callbacks ────────────────────────────────────────────────────

    def _on_open(self, wsapp) -> None:
        """Called after (re)connection.

        Public channel replay is handled automatically by DeltaWebSocket._ws_on_open,
        which replays every entry in _active_sub_msgs before invoking this callback.
        Manually re-subscribing here would create duplicate subscribe messages and
        accumulate extra aggregated keys in _active_sub_msgs on each reconnect.

        Private feeds are bootstrapped here on first connect via _queue_or_send,
        which registers them in _active_sub_msgs so subsequent reconnects replay
        them automatically without needing another explicit call.
        """
        self.logger.info("DeltaWS connection opened")
        self.connected = True

        # Subscribe to authenticated private feeds on every (re)connect
        self._subscribe_private_feeds()

    def _on_error(self, wsapp, error) -> None:
        self.logger.error("DeltaWS error: %s", error)

    def _on_close(self, wsapp) -> None:
        self.logger.info("DeltaWS closed")
        self.connected = False
        # No manual reconnect here — DeltaWebSocket.connect() runs a blocking
        # retry loop that handles all reconnection with proper backoff and the
        # configured max_retry_attempt limit.  Spawning another connect() thread
        # from this callback (which is invoked mid-loop, before run_forever
        # returns) would create a second competing retry loop with a reset
        # counter, bypassing max_retry_attempt and risking duplicate connections.

    def _on_data(self, wsapp, msg: dict) -> None:
        """
        Route incoming messages to the appropriate normaliser.

        Delta ticker shape:
          { "type": "v2/ticker", "symbol": "BTCUSD",
            "mark_price": "67000", "open": 66000, "high": 68000,
            "low": 65000, "close": 66500, "volume": 1234,
            "oi": "5000", "quotes": { "best_bid": "66990", "best_ask": "67010" } }

        Delta l2_orderbook shape:
          { "type": "l2_orderbook", "symbol": "BTCUSD",
            "buy":  [{"price": "66990", "size": 1000, "depth": 1}, ...],
            "sell": [{"price": "67010", "size":  800, "depth": 1}, ...] }

        Private order event shape:
          { "type": "orders", "action": "fill",
            "id": 12345, "product_id": 27, "product_symbol": "BTCUSD",
            "size": 1, "side": "buy", "average_fill_price": "67000",
            "state": "filled", "client_order_id": "..." }

        Private position update shape:
          { "type": "positions", "product_id": 27, "product_symbol": "BTCUSD",
            "size": 2, "entry_price": "66800", "realized_pnl": "100",
            "unrealized_pnl": "400" }
        """
        try:
            msg_type  = msg.get("type", "")
            br_symbol = msg.get("symbol", "") or msg.get("product_symbol", "")

            # ── Private / account-level events (no symbol-level subscription needed) ─────
            if msg_type in ("orders", "positions", "margins"):
                self._handle_private_event(msg_type, msg)
                return

            if not br_symbol:
                return

            # Find ALL OpenAlgo subscriptions matching this broker symbol + channel.
            # Multiple modes (e.g. 1=LTP and 2=Quote) can share the same v2/ticker
            # channel, so we must fan out to every subscriber.
            subscriptions = self._find_subscriptions_by_br_symbol(br_symbol, msg_type)
            if not subscriptions:
                self.logger.debug("No subscription for br_symbol=%s type=%s", br_symbol, msg_type)
                return

            # Normalise once — all subscriptions share the same br_symbol/exchange
            cache_key = f"{subscriptions[0]['symbol']}_{subscriptions[0]['exchange']}"
            if msg_type == "v2/ticker":
                base_data = self._normalise_ticker(msg, cache_key)
            elif msg_type == "l2_orderbook":
                base_data = self._normalise_l2_orderbook(msg, cache_key)
            else:
                self.logger.debug("Unhandled message type: %s", msg_type)
                return

            ts = int(time.time() * 1000)
            for subscription in subscriptions:
                oa_symbol   = subscription["symbol"]
                oa_exchange = subscription["exchange"]
                oa_mode     = subscription["mode"]
                mode_str    = DeltaModeMapper.get_mode_str(oa_mode)
                topic       = f"{oa_exchange}_{oa_symbol}_{mode_str}"

                market_data = dict(base_data)  # shallow copy per subscriber
                market_data.update({
                    "symbol":    oa_symbol,
                    "exchange":  oa_exchange,
                    "mode":      oa_mode,
                    "timestamp": ts,
                })

                self.publish_market_data(topic, market_data)

        except Exception as exc:
            self.logger.error("_on_data error: %s", exc, exc_info=True)

    # ── private feed helpers ──────────────────────────────────────────────────

    def _subscribe_private_feeds(self) -> None:
        """Subscribe to authenticated order / position / margin channels.

        Called automatically after every WebSocket (re)connect.  These channels
        deliver fill confirmations, position changes, and wallet updates without
        the need to poll REST endpoints.  Requires that the WebSocket session
        has been authenticated (the auth frame is sent in DeltaWebSocket._ws_on_open).
        """
        if not self.ws_client:
            return
        try:
            self.ws_client.subscribe_orders_channel()
            self.ws_client.subscribe_positions_channel()
            self.ws_client.subscribe_margins_channel()
            self.logger.info("Subscribed to private feeds: orders, positions, margins")
        except Exception as exc:
            self.logger.error("Failed to subscribe to private feeds: %s", exc)

    def _handle_private_event(self, event_type: str, msg: dict) -> None:
        """Normalise and publish an account-level private event.

        Private events are published on a fixed per-type topic so that any
        OpenAlgo service can subscribe to them via ZeroMQ:

          Topic pattern: ``deltaexchange_{event_type}``
          Examples:      ``deltaexchange_orders``, ``deltaexchange_positions``,
                         ``deltaexchange_margins``

        The raw message dict is forwarded as-is; callers can inspect
        ``msg["action"]`` (e.g. "fill", "create", "cancel") for order events
        and ``msg["size"]`` / ``msg["entry_price"]`` for position events.
        """
        topic = f"deltaexchange_{event_type}"
        payload = dict(msg)
        payload["timestamp"] = int(time.time() * 1000)
        self.publish_market_data(topic, payload)
        self.logger.debug("Private event published: type=%s topic=%s", event_type, topic)

    # ── normalisation ─────────────────────────────────────────────────────────

    def _normalise_ticker(self, msg: dict, cache_key: str) -> dict:
        """
        Map v2/ticker fields to OpenAlgo market data format.

        Field mapping:
            ltp        ← mark_price  (string)
            open       ← open
            high       ← high
            low        ← low
            close      ← close       (previous session close)
            volume     ← volume
            oi         ← oi          (string)
            bid_price  ← quotes.best_bid
            ask_price  ← quotes.best_ask
        """
        def _f(v, d=0.0):
            try: return float(v) if v is not None else d
            except: return d

        def _i(v, d=0):
            try: return int(float(v)) if v is not None else d
            except: return d

        quotes = msg.get("quotes") or {}

        with self._lock:
            cached = self.last_values.get(cache_key, {}).copy()

        def _cv(key, raw_val, cast=_f, default=0):
            val = cast(raw_val)
            if val != 0:
                return val
            return cast(cached.get(key, default))

        result = {
            "ltp":           _cv("ltp",        msg.get("mark_price"),  _f),
            "open":          _cv("open",        msg.get("open"),        _f),
            "high":          _cv("high",        msg.get("high"),        _f),
            "low":           _cv("low",         msg.get("low"),         _f),
            "close":         _cv("close",       msg.get("close"),       _f),
            "volume":        _cv("volume",      msg.get("volume"),      _i),
            "oi":            _cv("oi",          msg.get("oi"),          _f),
            "bid_price":     _cv("bid_price",   quotes.get("best_bid"), _f),
            "ask_price":     _cv("ask_price",   quotes.get("best_ask"), _f),
            "bid_qty":       0,
            "ask_qty":       0,
            "average_price": 0,
            "oi_change":     0,
        }

        with self._lock:
            if cache_key not in self.last_values:
                self.last_values[cache_key] = {}
            for k, v in result.items():
                if v != 0:
                    self.last_values[cache_key][k] = v

        return result

    def _normalise_l2_orderbook(self, msg: dict, cache_key: str) -> dict:
        """
        Map l2_orderbook message to OpenAlgo depth format.

        buy/sell: [{"price": str, "size": int, "depth": int}, ...]
        """
        def _f(v, d=0.0):
            try: return float(v) if v is not None else d
            except: return d

        def _parse_levels(side_list, n=5):
            levels = []
            for lvl in (side_list or [])[:n]:
                levels.append({"price": _f(lvl.get("price")), "quantity": int(lvl.get("size", 0))})
            while len(levels) < n:
                levels.append({"price": 0.0, "quantity": 0})
            return levels

        bids = _parse_levels(msg.get("buy",  []))
        asks = _parse_levels(msg.get("sell", []))

        result = {
            "bids": bids,
            "asks": asks,
            "totalbuyqty":  sum(lvl["quantity"] for lvl in bids),
            "totalsellqty": sum(lvl["quantity"] for lvl in asks),
            "ltp": 0,
        }

        # Merge with cached ticker ltp if available
        with self._lock:
            cached = self.last_values.get(cache_key, {})
        result["ltp"] = _f(cached.get("ltp", 0))

        return result

    # ── helpers ───────────────────────────────────────────────────────────────

    def _find_subscriptions_by_br_symbol(self, br_symbol: str, msg_type: str) -> list[dict]:
        """Return ALL subscriptions whose br_symbol and channel match the incoming message.

        Multiple subscription modes (e.g. mode 1=LTP and mode 2=Quote) can map
        to the same underlying WebSocket channel (v2/ticker).  Returning every
        match ensures each subscriber receives its own publish call.
        """
        expected_channel = (
            DeltaWebSocket.CHANNEL_TICKER if msg_type == "v2/ticker"
            else DeltaWebSocket.CHANNEL_L2_BOOK
        )
        with self._lock:
            matched = [
                sub for sub in self.subscriptions.values()
                if sub.get("br_symbol") == br_symbol and sub.get("channel") == expected_channel
            ]
            if not matched:
                # Fallback: any sub with matching br_symbol regardless of channel
                matched = [
                    sub for sub in self.subscriptions.values()
                    if sub.get("br_symbol") == br_symbol
                ]
        return matched
