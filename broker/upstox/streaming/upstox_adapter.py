# broker/upstox/streaming/upstox_adapter.py
"""
Upstox V3 WebSocket adapter implementation (synchronous).

Uses sync websocket-client (same as Angel/Dhan) to avoid asyncio event loop
conflicts with eventlet in gunicorn+eventlet deployments.
"""
import json
import logging
import threading
from typing import Any

from database.auth_db import get_auth_token
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .upstox_client import UpstoxWebSocketClient


class UpstoxWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    Upstox V3 WebSocket adapter implementation.

    Features:
    - Uses synchronous websocket-client (no asyncio event loop needed)
    - Processes protobuf messages decoded to dict format
    - Manages subscriptions and market data publishing
    - Compatible with eventlet/gunicorn deployments
    """

    # Thread cleanup timeout
    THREAD_JOIN_TIMEOUT = 5

    # NOTE on Upstox V3 connection limits:
    #   Standard tier: 2 connections per user
    #   Plus tier:     5 connections per user
    # The pool size is driven by the MAX_WEBSOCKET_CONNECTIONS environment
    # variable in .env (default 3) — set it to 2 if you are on Standard,
    # or up to 5 on Plus. See upstox-api-docs/21a-websocket-market-data-v3.md.

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("upstox_websocket")
        self.ws_client: UpstoxWebSocketClient | None = None
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.market_status: dict[str, Any] = {}
        self.connected = False
        self.running = False
        self.lock = threading.Lock()

        # Batch subscription queue (mirrors Zerodha pattern).
        # Coalesces multiple subscribe() calls into one or two WS messages
        # (one per Upstox mode: ltpc / full) and naturally bridges the cold-
        # start race between connect() returning and _on_connect firing.
        self.subscription_queue: list[dict[str, Any]] = []
        self.batch_timer: threading.Timer | None = None
        self.batch_delay = 0.5  # seconds — long enough to absorb the WS handshake

        # Per-instrument LTPC cache. Upstox V3 sends incremental ticks where
        # `fullFeed.marketFF.ltpc` may be absent on packets that only update
        # `marketLevel`. We cache the last LTPC so quote/depth packets can
        # carry forward a non-zero LTP into validation downstream.
        self._last_ltpc: dict[str, dict[str, Any]] = {}

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Initialize the adapter with authentication data"""
        try:
            auth_token = self._get_auth_token(auth_data, user_id)
            if not auth_token:
                return self._create_error_response("AUTH_ERROR", "No authentication token found")

            self.ws_client = UpstoxWebSocketClient(auth_token)
            self.ws_client.callbacks = {
                "on_connect": self._on_connect,
                "on_message": self._on_market_data,
                "on_error": self._on_error,
                "on_close": self._on_close,
            }

            self.logger.debug("UpstoxWebSocketClient initialized successfully")
            return self._create_success_response("Initialized Upstox WebSocket adapter")

        except Exception as e:
            self.logger.error(f"Initialization error: {e}")
            return self._create_error_response("INIT_ERROR", str(e))

    def connect(self) -> dict[str, Any]:
        """Establish WebSocket connection"""
        try:
            if self.connected:
                return self._create_success_response("Already connected")

            if not self.ws_client:
                return self._create_error_response(
                    "NOT_INITIALIZED", "WebSocket client not initialized"
                )

            success = self.ws_client.connect()

            if success:
                self.connected = True
                self.running = True
                self.logger.info("Connected to Upstox WebSocket")
                return self._create_success_response("Connected to Upstox WebSocket")
            else:
                return self._create_error_response(
                    "CONNECTION_FAILED", "Failed to connect to Upstox WebSocket"
                )

        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            return self._create_error_response("CONNECTION_ERROR", str(e))

    def subscribe(
        self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 0
    ) -> dict[str, Any]:
        """Subscribe to market data"""
        if mode not in [1, 2, 3]:
            return self._create_error_response(
                "INVALID_MODE", f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)"
            )

        if not self.connected:
            return self._create_error_response("NOT_CONNECTED", "WebSocket is not connected")

        if not self.ws_client:
            return self._create_error_response(
                "NOT_INITIALIZED", "WebSocket client not initialized"
            )

        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
            )

        instrument_key = self._create_instrument_key(token_info)
        correlation_id = f"{symbol}_{exchange}_{mode}"

        with self.lock:
            if correlation_id in self.subscriptions:
                self.logger.debug(f"Already subscribed to {symbol} on {exchange} with mode {mode}")
                return self._create_success_response(
                    f"Already subscribed to {symbol} on {exchange}"
                )

        subscription_info = {
            "symbol": symbol,
            "exchange": exchange,
            "mode": mode,
            "depth_level": depth_level,
            "token": token_info["token"],
            "instrument_key": instrument_key,
        }

        with self.lock:
            self.subscriptions[correlation_id] = subscription_info
            self.subscription_queue.append(subscription_info)
            self.logger.debug(f"Queued subscription: {correlation_id} -> {subscription_info}")

        # Defer the actual WS send by `batch_delay` seconds so multiple
        # subscribes coalesce into a single grouped-by-mode message. The
        # delay also bridges the cold-start race between connect() returning
        # and _on_connect firing — by the time the timer expires, the
        # handshake has typically completed. If it hasn't, _process_batch_
        # subscriptions defers; _on_connect will replay from self.subscriptions.
        self._start_batch_timer()

        return self._create_success_response(
            f"Subscription queued for {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
        )

    def _start_batch_timer(self) -> None:
        """Arm (or rearm) the batched-subscribe timer."""
        with self.lock:
            if self.batch_timer is not None:
                self.batch_timer.cancel()
            self.batch_timer = threading.Timer(
                self.batch_delay, self._process_batch_subscriptions
            )
            self.batch_timer.daemon = True
            self.batch_timer.start()

    def _process_batch_subscriptions(self) -> None:
        """Drain the subscription queue and send one bulk-subscribe per mode.

        Upstox V3's `instrumentKeys` field accepts an array, so N symbols of
        the same mode collapse to a single message. Modes 2 and 3 both map
        to Upstox's `full` feed, so they coalesce into the same message.
        """
        # Snapshot under lock — release before the WS send to avoid blocking
        # subsequent subscribe() calls during network I/O.
        with self.lock:
            self.batch_timer = None
            queue = self.subscription_queue[:]
            self.subscription_queue.clear()

        if not queue:
            return

        # If the WS handshake hasn't completed, do nothing — _on_connect will
        # replay every recorded subscription from self.subscriptions (which
        # already includes everything we just dequeued).
        if not (self.ws_client and getattr(self.ws_client, "_connected", False)):
            self.logger.debug(
                f"Batch deferred: WS not connected yet. {len(queue)} subscription(s) "
                f"will be sent from _on_connect."
            )
            return

        # Group instrument keys by Upstox mode string ("ltpc" or "full").
        keys_by_mode: dict[str, list[str]] = {}
        for sub in queue:
            mode_str = self._get_upstox_mode(sub["mode"], sub.get("depth_level", 0))
            keys_by_mode.setdefault(mode_str, []).append(sub["instrument_key"])

        for mode_str, instrument_keys in keys_by_mode.items():
            try:
                self.logger.info(
                    f"📦 Batch subscribing {len(instrument_keys)} instrument(s) in {mode_str} mode"
                )
                self.ws_client.subscribe(instrument_keys, mode_str)
            except Exception as e:
                self.logger.error(f"Batch subscribe failed for mode {mode_str}: {e}")

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        """Unsubscribe from market data"""
        try:
            if not self.ws_client:
                return self._create_error_response(
                    "NOT_INITIALIZED", "WebSocket client not initialized"
                )

            token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
            if not token_info:
                return self._create_error_response(
                    "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
                )

            instrument_key = self._create_instrument_key(token_info)
            correlation_id = f"{symbol}_{exchange}_{mode}"

            with self.lock:
                if correlation_id not in self.subscriptions:
                    self.logger.debug(f"Not subscribed to {symbol} on {exchange} with mode {mode}")
                    return self._create_success_response(
                        f"Not subscribed to {symbol} on {exchange}"
                    )

            success = self.ws_client.unsubscribe([instrument_key])

            if success:
                with self.lock:
                    self.subscriptions.pop(correlation_id, None)
                self.logger.info(f"Unsubscribed from {symbol} on {exchange}")
                return self._create_success_response(f"Unsubscribed from {symbol} on {exchange}")
            else:
                return self._create_error_response(
                    "UNSUBSCRIBE_FAILED", f"Failed to unsubscribe from {symbol} on {exchange}"
                )

        except Exception as e:
            self.logger.error(f"Unsubscribe error: {e}")
            return self._create_error_response("UNSUBSCRIBE_ERROR", str(e))

    def disconnect(self) -> None:
        """Disconnect from WebSocket and cleanup resources"""
        try:
            self.running = False
            self.connected = False

            # Cancel any pending batch-subscribe timer so it doesn't fire
            # against a half-torn-down adapter.
            with self.lock:
                if self.batch_timer is not None:
                    self.batch_timer.cancel()
                    self.batch_timer = None

            if self.ws_client:
                try:
                    self.ws_client.disconnect()
                except Exception as e:
                    self.logger.warning(f"Error disconnecting WebSocket client: {e}")

            with self.lock:
                self.subscriptions.clear()
                self.subscription_queue.clear()
                self._last_ltpc.clear()

            self.cleanup_zmq()
            self.logger.info("Disconnected from Upstox WebSocket")

        except Exception as e:
            self.logger.error(f"Disconnect error: {e}")
        finally:
            self.running = False
            self.connected = False

    def cleanup(self) -> None:
        """Clean up all resources"""
        try:
            if self.ws_client:
                try:
                    self.ws_client.disconnect()
                except Exception as ws_err:
                    self.logger.error(f"Error stopping WebSocket client during cleanup: {ws_err}")
                finally:
                    self.ws_client = None

            with self.lock:
                self.running = False
                self.connected = False
                self.subscriptions.clear()
                self.subscription_queue.clear()
                self._last_ltpc.clear()
                if self.batch_timer is not None:
                    self.batch_timer.cancel()
                    self.batch_timer = None

            self.cleanup_zmq()
            self.logger.info("Upstox adapter cleaned up completely")

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            try:
                self.cleanup_zmq()
            except Exception as zmq_err:
                self.logger.error(f"Error cleaning up ZMQ during final cleanup attempt: {zmq_err}")

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass

    # Private helper methods
    def _get_auth_token(self, auth_data: dict[str, Any] | None, user_id: str) -> str | None:
        """Get authentication token from auth_data or database"""
        if auth_data and "auth_token" in auth_data:
            return auth_data["auth_token"]
        return get_auth_token(user_id)

    def _create_instrument_key(self, token_info: dict[str, Any]) -> str:
        """Create instrument key from token info"""
        token = token_info["token"]
        brexchange = token_info["brexchange"]
        if "|" in token:
            token = token.split("|")[-1]
        return f"{brexchange}|{token}"

    def _get_upstox_mode(self, mode: int, depth_level: int) -> str:
        """Convert internal mode to Upstox mode string"""
        mode_map = {1: "ltpc", 2: "full", 3: "full"}
        return mode_map.get(mode, "ltpc")

    def _create_topic(self, exchange: str, symbol: str, mode: int) -> str:
        """Create ZMQ topic for publishing"""
        mode_map = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}
        mode_str = mode_map.get(mode, "QUOTE")
        return f"{exchange}_{symbol}_{mode_str}"

    # WebSocket event handlers (called synchronously by upstox_client)
    def _on_connect(self):
        """Callback when WebSocket connection is opened.

        Handles both the initial cold start (subscriptions queued before the
        handshake completed) and reconnects (subscriptions need re-issuing).
        Sends one bulk message per Upstox mode regardless of how many
        symbols are involved.
        """
        self.logger.info("Upstox WebSocket connection opened")
        self.connected = True

        # Drain the pending queue (subscribes that arrived before handshake)
        # and merge with the persistent record; on reconnect, queue is empty
        # but self.subscriptions still has every active subscription.
        with self.lock:
            if self.batch_timer is not None:
                self.batch_timer.cancel()
                self.batch_timer = None
            self.subscription_queue.clear()
            all_subs = list(self.subscriptions.values())

        if not all_subs:
            return

        keys_by_mode: dict[str, list[str]] = {}
        for sub in all_subs:
            mode_str = self._get_upstox_mode(sub["mode"], sub.get("depth_level", 0))
            keys_by_mode.setdefault(mode_str, []).append(sub["instrument_key"])

        for mode_str, instrument_keys in keys_by_mode.items():
            try:
                self.logger.info(
                    f"🔌 Replaying {len(instrument_keys)} subscription(s) in {mode_str} mode "
                    f"after WS handshake"
                )
                self.ws_client.subscribe(instrument_keys, mode_str)
            except Exception as e:
                self.logger.error(f"Replay subscribe failed for mode {mode_str}: {e}")

    def _on_error(self, error: str):
        """Handle WebSocket errors"""
        self.logger.error(f"WebSocket error: {error}")
        self.connected = False

    def _on_close(self):
        """Handle WebSocket closure"""
        self.logger.info("WebSocket connection closed")
        self.connected = False

    def _on_market_data(self, data: dict[str, Any]):
        """Handle market data messages"""
        try:
            if data.get("type") == "market_info":
                self._handle_market_info(data)
                return

            feeds = data.get("feeds", {})
            if not feeds:
                self.logger.debug(f"No feeds in market data: {list(data.keys())}")
                return

            self.logger.debug(f"Processing {len(feeds)} feed(s): {list(feeds.keys())}")

            current_ts = data.get("currentTs", 0)

            for feed_key, feed_data in feeds.items():
                self._process_feed(feed_key, feed_data, current_ts)

        except Exception as e:
            self.logger.error(f"Market data handler error: {e}")

    def _handle_market_info(self, data: dict[str, Any]):
        """Handle market info messages"""
        if "marketInfo" in data:
            self.market_status = data["marketInfo"]
            if "segmentStatus" in self.market_status:
                self.logger.debug(f"Market status update: {self.market_status['segmentStatus']}")

    def _process_feed(self, feed_key: str, feed_data: dict[str, Any], current_ts: int):
        """Process individual feed data"""
        try:
            matching_subscriptions = []
            with self.lock:
                for correlation_id, sub_info in self.subscriptions.items():
                    if sub_info.get("instrument_key") == feed_key:
                        matching_subscriptions.append((correlation_id, sub_info))
                    elif "|" in feed_key:
                        token = feed_key.split("|")[-1]
                        if sub_info.get("token") == token or sub_info.get("token") == feed_key:
                            matching_subscriptions.append((correlation_id, sub_info))

            if not matching_subscriptions:
                self.logger.warning(f"No subscription found for feed key: {feed_key}")
                return

            for correlation_id, sub_info in matching_subscriptions:
                symbol = sub_info["symbol"]
                exchange = sub_info["exchange"]
                mode = sub_info["mode"]

                topic = self._create_topic(exchange, symbol, mode)
                market_data = self._extract_market_data(feed_data, sub_info, current_ts)

                if market_data:
                    self.logger.debug(f"Publishing {symbol}.{exchange} mode={mode} topic={topic} ltp={market_data.get('ltp', 'N/A')}")
                    if mode == 3:  # Depth mode
                        depth_data = market_data.copy()
                        depth_levels = {
                            "buy": depth_data.pop("buy", []),
                            "sell": depth_data.pop("sell", []),
                            "timestamp": depth_data.get("timestamp", current_ts),
                        }
                        depth_data["depth"] = depth_levels
                        self.publish_market_data(topic, depth_data)
                    else:
                        self.publish_market_data(topic, market_data)

        except Exception as e:
            self.logger.error(f"Error processing feed for {feed_key}: {e}")

    def _extract_market_data(
        self, feed_data: dict[str, Any], sub_info: dict[str, Any], current_ts: int
    ) -> dict[str, Any]:
        """Extract market data based on subscription mode.

        Wraps the per-mode extractors with a per-instrument LTPC cache: if
        the current tick is incremental and didn't include `ltpc`, we
        backfill from the last-seen value so `ltp` is always present
        downstream. Bug observed in production: mode-3 (depth) packets that
        only update `marketLevel` were producing `Missing LTP value`
        validation failures because ltpc.get("ltp", 0) was emitting 0
        (and in some paths returning an empty dict that dropped the key
        entirely).
        """
        mode = sub_info["mode"]
        symbol = sub_info["symbol"]
        exchange = sub_info["exchange"]
        token = sub_info["token"]
        instrument_key = sub_info.get("instrument_key", token)

        base_data = {"symbol": symbol, "exchange": exchange, "token": token}

        # Cache any LTPC that arrived on this tick, regardless of mode.
        ltpc_in_tick = self._extract_tick_ltpc(feed_data)
        if ltpc_in_tick:
            with self.lock:
                self._last_ltpc[instrument_key] = ltpc_in_tick

        # Per-mode extraction.
        if mode == 1:
            result = self._extract_ltp_data(feed_data, base_data)
        elif mode == 2:
            result = self._extract_quote_data(feed_data, base_data, current_ts)
        elif mode == 3:
            depth_data = self._extract_depth_data(feed_data, current_ts)
            depth_data.update(base_data)
            result = depth_data
        else:
            return {}

        # Carry-forward: if the extractor produced an empty dict (no fullFeed
        # wrapper) or its `ltp` is 0/missing, splice in the cached LTPC.
        if not result:
            cached = self._last_ltpc.get(instrument_key)
            if cached:
                result = base_data.copy()
                result.update(
                    {
                        "ltp": float(cached.get("ltp", 0) or 0),
                        "ltq": int(cached.get("ltq", 0) or 0),
                        "ltt": int(cached.get("ltt", 0) or 0),
                        "cp": float(cached.get("cp", 0) or 0),
                        "timestamp": current_ts,
                    }
                )
        elif not result.get("ltp"):
            cached = self._last_ltpc.get(instrument_key)
            if cached and cached.get("ltp"):
                result["ltp"] = float(cached["ltp"])

        return result

    def _extract_tick_ltpc(self, feed_data: dict[str, Any]) -> dict[str, Any]:
        """Pull LTPC from a Feed protobuf-as-dict regardless of which oneof
        branch it was sent under (`Feed.ltpc` for mode=ltpc, or
        `Feed.fullFeed.{marketFF|indexFF}.ltpc` for mode=full).
        """
        if "ltpc" in feed_data and isinstance(feed_data["ltpc"], dict):
            return feed_data["ltpc"]
        full_feed = feed_data.get("fullFeed") or {}
        ff = full_feed.get("marketFF") or full_feed.get("indexFF") or {}
        ltpc = ff.get("ltpc") or {}
        return ltpc if isinstance(ltpc, dict) else {}

    def _extract_ltp_data(
        self, feed_data: dict[str, Any], base_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract LTP data from feed"""
        market_data = base_data.copy()

        if "ltpc" in feed_data:
            ltpc = feed_data["ltpc"]
            market_data.update(
                {
                    "ltp": float(ltpc.get("ltp", 0)),
                    "ltq": int(ltpc.get("ltq", 0)),
                    "ltt": int(ltpc.get("ltt", 0)),
                    "cp": float(ltpc.get("cp", 0)),
                }
            )

        return market_data

    def _extract_quote_data(
        self, feed_data: dict[str, Any], base_data: dict[str, Any], current_ts: int
    ) -> dict[str, Any]:
        """Extract QUOTE data from feed."""
        if "fullFeed" not in feed_data:
            return {}

        full_feed = feed_data["fullFeed"]
        ff = full_feed.get("marketFF") or full_feed.get("indexFF", {})

        ltpc = ff.get("ltpc", {})
        ltp = ltpc.get("ltp", 0)
        ltq = ltpc.get("ltq", 0)

        ohlc_list = ff.get("marketOHLC", {}).get("ohlc", [])
        ohlc = next(
            (o for o in ohlc_list if o.get("interval") == "1d"), ohlc_list[0] if ohlc_list else {}
        )

        volume = ohlc.get("vol", 0) if ohlc else 0
        avg_price = float(ff.get("atp", 0))
        total_buy_qty = int(ff.get("tbq", 0))
        total_sell_qty = int(ff.get("tsq", 0))

        market_data = base_data.copy()
        market_data.update(
            {
                "open": float(ohlc.get("open", 0)),
                "high": float(ohlc.get("high", 0)),
                "low": float(ohlc.get("low", 0)),
                "close": float(ohlc.get("close", 0)),
                "ltp": float(ltp),
                "last_trade_quantity": int(ltq),
                "volume": int(volume),
                "average_price": float(avg_price),
                "total_buy_quantity": int(total_buy_qty),
                "total_sell_quantity": int(total_sell_qty),
                "timestamp": int(ohlc.get("ts", current_ts)),
            }
        )

        return market_data

    def _extract_depth_data(self, feed_data: dict[str, Any], current_ts: int) -> dict[str, Any]:
        """Extract depth data from feed."""
        if "fullFeed" not in feed_data:
            return {"buy": [], "sell": [], "timestamp": current_ts, "ltp": 0}

        full_feed = feed_data["fullFeed"]
        market_ff = full_feed.get("marketFF") or full_feed.get("indexFF", {})
        market_level = market_ff.get("marketLevel", {})
        bid_ask = market_level.get("bidAskQuote", [])

        ltpc = market_ff.get("ltpc", {})
        ltp = float(ltpc.get("ltp", 0))

        buy_levels = []
        sell_levels = []

        for level in bid_ask:
            bid_price = float(level.get("bidP", 0))
            bid_qty = int(float(level.get("bidQ", 0)))
            if bid_price > 0:
                buy_levels.append({"price": bid_price, "quantity": bid_qty, "orders": 0})

            ask_price = float(level.get("askP", 0))
            ask_qty = int(float(level.get("askQ", 0)))
            if ask_price > 0:
                sell_levels.append({"price": ask_price, "quantity": ask_qty, "orders": 0})

        buy_levels = sorted(buy_levels, key=lambda x: x["price"], reverse=True)
        sell_levels = sorted(sell_levels, key=lambda x: x["price"])

        buy_levels.extend([{"price": 0.0, "quantity": 0, "orders": 0}] * (5 - len(buy_levels)))
        sell_levels.extend([{"price": 0.0, "quantity": 0, "orders": 0}] * (5 - len(sell_levels)))

        return {
            "buy": buy_levels[:5],
            "sell": sell_levels[:5],
            "timestamp": current_ts,
            "ltp": ltp,
        }
