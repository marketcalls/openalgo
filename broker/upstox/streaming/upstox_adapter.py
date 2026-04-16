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

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("upstox_websocket")
        self.ws_client: UpstoxWebSocketClient | None = None
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.market_status: dict[str, Any] = {}
        self.connected = False
        self.running = False
        self.lock = threading.Lock()

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
            self.logger.debug(f"Stored subscription: {correlation_id} -> {subscription_info}")

        if self.connected and self.ws_client:
            try:
                success = self.ws_client.subscribe(
                    [instrument_key], self._get_upstox_mode(mode, depth_level)
                )

                if success:
                    self.logger.info(f"Subscribed to {symbol} on {exchange} (key={instrument_key})")
                    return self._create_success_response(f"Subscribed to {symbol} on {exchange}")
                else:
                    with self.lock:
                        self.subscriptions.pop(correlation_id, None)
                    return self._create_error_response(
                        "SUBSCRIBE_FAILED", f"Failed to subscribe to {symbol} on {exchange}"
                    )

            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                with self.lock:
                    self.subscriptions.pop(correlation_id, None)
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

        return self._create_success_response(
            f"Subscription requested for {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
        )

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

            if self.ws_client:
                try:
                    self.ws_client.disconnect()
                except Exception as e:
                    self.logger.warning(f"Error disconnecting WebSocket client: {e}")

            with self.lock:
                self.subscriptions.clear()

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
        """Callback when WebSocket connection is opened"""
        self.logger.info("Upstox WebSocket connection opened")
        self.connected = True

        # Resubscribe to existing subscriptions on reconnection
        with self.lock:
            for correlation_id, sub in self.subscriptions.items():
                try:
                    instrument_key = sub["instrument_key"]
                    mode = sub["mode"]
                    depth_level = sub["depth_level"]

                    if self.ws_client.subscribe(
                        [instrument_key], self._get_upstox_mode(mode, depth_level)
                    ):
                        self.logger.info(f"Resubscribed to {sub['symbol']}.{sub['exchange']}")
                    else:
                        self.logger.warning(
                            f"Failed to resubscribe to {sub['symbol']}.{sub['exchange']}"
                        )
                except Exception as e:
                    self.logger.error(
                        f"Error resubscribing to {sub['symbol']}.{sub['exchange']}: {e}"
                    )

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
        """Extract market data based on subscription mode"""
        mode = sub_info["mode"]
        symbol = sub_info["symbol"]
        exchange = sub_info["exchange"]
        token = sub_info["token"]

        base_data = {"symbol": symbol, "exchange": exchange, "token": token}

        if mode == 1:
            return self._extract_ltp_data(feed_data, base_data)
        elif mode == 2:
            return self._extract_quote_data(feed_data, base_data, current_ts)
        elif mode == 3:
            depth_data = self._extract_depth_data(feed_data, current_ts)
            depth_data.update(base_data)
            return depth_data

        return {}

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
        """Extract QUOTE data from feed"""
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
        """Extract depth data from feed"""
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
