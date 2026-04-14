"""
Fyers TBT (Tick-by-Tick) WebSocket Client for 50-Level Market Depth
Uses the official Fyers TBT WebSocket API with protobuf responses
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Dict, List, Optional, Set

import requests
import websocket

# Import protobuf message definitions (local copy)
try:
    from . import msg_pb2 as protomsg
except ImportError:
    protomsg = None
    logging.warning("Could not import Fyers protobuf definitions")


class FyersTbtWebSocket:
    """
    Fyers TBT WebSocket client for 50-level market depth
    """

    # Default TBT WebSocket URL
    DEFAULT_TBT_URL = "wss://rtsocket-api.fyers.in/versova"

    def __init__(self, access_token: str, log_path: str = ""):
        """
        Initialize TBT WebSocket client

        Args:
            access_token: Fyers access token (format: APPID:SECRET)
            log_path: Path for log files
        """
        self.access_token = access_token
        self.log_path = log_path
        self.logger = logging.getLogger("fyers_tbt_websocket")

        # WebSocket state
        self.ws = None
        self.ws_thread = None
        self.ping_thread = None
        self.running = False
        self.connected = False

        # Subscription tracking
        self.subscriptions: dict[str, set[str]] = {}  # channel -> symbols
        self.active_channels: set[str] = set()

        # Depth data storage (50 levels) - maintains cumulative state
        self.depth_data: dict[str, dict] = {}  # ticker -> cumulative depth data

        # Callbacks
        self.on_depth_update: Callable | None = None
        self.on_error: Callable | None = None
        self.on_open: Callable | None = None
        self.on_close: Callable | None = None

        # Reconnection settings
        self.reconnect_enabled = True
        self.max_reconnect_attempts = 10
        self.reconnect_attempts = 0
        self.reconnect_delay = 0

        # Get WebSocket URL
        self.ws_url = self._get_tbt_url()

    def _get_tbt_url(self) -> str:
        """Get TBT WebSocket URL from Fyers API"""
        try:
            response = requests.get(
                "https://api-t1.fyers.in/indus/home/tbtws",
                headers={"Authorization": self.access_token},
                timeout=10,
            )
            if response.status_code == 200:
                url = response.json().get("data", {}).get("socket_url", self.DEFAULT_TBT_URL)
                self.logger.debug(f"Got TBT WebSocket URL: {url}")
                return url
        except Exception as e:
            self.logger.warning(f"Failed to get TBT URL from API: {e}")

        return self.DEFAULT_TBT_URL

    def set_callbacks(
        self,
        on_depth_update: Callable | None = None,
        on_error: Callable | None = None,
        on_open: Callable | None = None,
        on_close: Callable | None = None,
    ):
        """Set callback functions"""
        self.on_depth_update = on_depth_update
        self.on_error = on_error
        self.on_open = on_open
        self.on_close = on_close

    def connect(self) -> bool:
        """
        Connect to TBT WebSocket

        Returns:
            True if connection initiated successfully
        """
        if self.running:
            self.logger.warning("Already connected or connecting")
            return False

        try:
            self.running = True
            self.ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
            self.ws_thread.start()

            # Wait for connection
            timeout = 15
            start_time = time.time()
            while not self.connected and time.time() - start_time < timeout:
                time.sleep(0.1)

            return self.connected

        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            self.running = False
            return False

    def disconnect(self):
        """Disconnect from TBT WebSocket"""
        was_connected = self.connected

        self.running = False
        self.connected = False
        self.reconnect_enabled = False

        # Close WebSocket
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                self.logger.debug(f"Error closing WebSocket: {e}")

        # Wait for threads to finish with longer timeout for Docker/Linux environments
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=5)
            if self.ws_thread.is_alive():
                self.logger.warning("WebSocket thread did not terminate within 5 seconds")

        if self.ping_thread and self.ping_thread.is_alive():
            self.ping_thread.join(timeout=3)
            if self.ping_thread.is_alive():
                self.logger.warning("Ping thread did not terminate within 3 seconds")

        # Clear subscriptions
        self.subscriptions.clear()
        self.active_channels.clear()
        self.depth_data.clear()

        if was_connected:
            self.logger.debug("TBT WebSocket disconnected")

    def _run_websocket(self):
        """Run WebSocket connection with reconnection logic"""
        while self.running:
            try:
                header = {"authorization": self.access_token}

                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    header=header,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=self._on_open,
                )

                self.ws.run_forever(ping_interval=0)  # We handle ping manually

            except Exception as e:
                self.logger.error(f"WebSocket error: {e}")
                self.connected = False

                if self.running and self.reconnect_enabled:
                    self._handle_reconnect()
                else:
                    break

    def _handle_reconnect(self):
        """Handle reconnection with exponential backoff"""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error(f"Max reconnect attempts ({self.max_reconnect_attempts}) reached")
            self.running = False
            return

        self.reconnect_attempts += 1
        if self.reconnect_attempts % 5 == 0:
            self.reconnect_delay = min(self.reconnect_delay + 5, 30)

        self.logger.info(
            f"Reconnecting in {self.reconnect_delay}s (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})"
        )
        time.sleep(self.reconnect_delay)

    def _on_open(self, ws):
        """Handle WebSocket connection open"""
        self.ws = ws
        self.reconnect_attempts = 0
        self.reconnect_delay = 0

        # Stop existing ping thread before creating new one (prevents thread accumulation)
        # Keep connected=False until the old thread has exited to prevent it from continuing
        # This is critical to prevent FD leaks from accumulated threads
        self.connected = False  # Ensure old ping thread exits its loop
        if self.ping_thread and self.ping_thread.is_alive():
            try:
                # Wait long enough for the 10s sleep in _ping_loop to finish
                self.ping_thread.join(timeout=11.0)
                if self.ping_thread.is_alive():
                    self.logger.warning("Old ping thread still alive during reconnect")
            except Exception as e:
                self.logger.debug(f"Error joining old ping thread: {e}")

        # Now safe to set connected=True and start new ping thread
        self.connected = True

        # Start new ping thread
        self.ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self.ping_thread.start()

        self.logger.info("TBT WebSocket connected")

        # Resubscribe to existing subscriptions
        self._resubscribe_all()

        if self.on_open:
            try:
                self.on_open()
            except Exception as e:
                self.logger.error(f"Error in on_open callback: {e}")

    def _on_close(self, ws, close_status_code=None, close_msg=None):
        """Handle WebSocket connection close"""
        self.connected = False

        if self.running:
            self.logger.warning(f"TBT WebSocket closed: {close_status_code} - {close_msg}")
        else:
            self.logger.debug("TBT WebSocket closed during shutdown")

        if self.on_close and not self.running:
            try:
                self.on_close({"code": close_status_code, "message": close_msg})
            except Exception as e:
                self.logger.error(f"Error in on_close callback: {e}")

    def _on_error(self, ws, error):
        """Handle WebSocket error"""
        if self.running:
            self.logger.error(f"TBT WebSocket error: {error}")

        if self.on_error:
            try:
                self.on_error(error)
            except Exception as e:
                self.logger.error(f"Error in on_error callback: {e}")

    def _on_message(self, ws, message):
        """Handle incoming WebSocket message"""
        try:
            # Check message type
            if isinstance(message, str):
                # Text message - could be pong or JSON response
                if message == "pong":
                    return

                # Try to parse as JSON (subscription response)
                try:
                    json_msg = json.loads(message)
                    self.logger.info(f"TBT JSON response: {json_msg}")

                    # Check for errors in JSON response
                    if json_msg.get("error"):
                        error_msg = json_msg.get("msg", "Unknown error")
                        self.logger.error(f"TBT subscription error: {error_msg}")
                        if self.on_error:
                            self.on_error(error_msg)
                    return
                except json.JSONDecodeError:
                    self.logger.debug(f"TBT text message (not JSON): {message[:100]}")
                    return

            # Binary message - parse as protobuf
            if not protomsg:
                self.logger.error("Protobuf module not available")
                return

            # Log raw message for debugging
            self.logger.debug(f"TBT received binary message: {len(message)} bytes")

            socket_msg = protomsg.SocketMessage()
            socket_msg.ParseFromString(message)

            # Check for errors
            if socket_msg.error:
                self.logger.error(f"TBT error message: {socket_msg.msg}")
                if self.on_error:
                    self.on_error(socket_msg.msg)
                return

            # Log parsed message info
            if socket_msg.feeds:
                feed_keys = list(socket_msg.feeds.keys())
                self.logger.debug(f"TBT feeds received: {feed_keys}")

                # Log first feed details for debugging
                if feed_keys:
                    first_key = feed_keys[0]
                    market_feed = socket_msg.feeds[first_key]
                    has_depth = (
                        market_feed.HasField("depth") if hasattr(market_feed, "HasField") else False
                    )
                    self.logger.debug(
                        f"TBT first feed '{first_key}': has_depth={has_depth}, snapshot={socket_msg.snapshot}"
                    )
            else:
                self.logger.debug(f"TBT message received but no feeds (msg_type={socket_msg.type})")

            # Process depth data
            self._process_depth_message(socket_msg)

        except Exception as e:
            self.logger.error(f"Error processing message: {e}", exc_info=True)

    def _process_depth_message(self, socket_msg):
        """Process depth data from protobuf message"""
        try:
            if not socket_msg.feeds:
                self.logger.debug("No feeds in socket message")
                return

            for token, market_feed in socket_msg.feeds.items():
                # Get the actual ticker symbol from the MarketFeed message
                # The dictionary key is the numeric token, but ticker field has the symbol
                ticker = market_feed.ticker if market_feed.ticker else token

                # Check if this feed has depth data
                has_depth = (
                    market_feed.HasField("depth") if hasattr(market_feed, "HasField") else False
                )

                if not has_depth:
                    self.logger.debug(f"No depth data for ticker: {ticker} (token: {token})")
                    continue

                # Extract depth data (stateful - accumulates updates)
                depth_data = self._extract_depth(ticker, market_feed, socket_msg.snapshot)

                # Log extraction results
                buy_count = len(depth_data.get("buy", []))
                sell_count = len(depth_data.get("sell", []))
                self.logger.debug(
                    f"TBT depth for {ticker}: {buy_count} buy, {sell_count} sell levels (snapshot={socket_msg.snapshot})"
                )

                # Invoke callback with the ticker symbol
                if self.on_depth_update:
                    try:
                        self.logger.debug(f"Invoking depth callback for {ticker}")
                        self.on_depth_update(ticker, depth_data)
                    except Exception as e:
                        self.logger.error(
                            f"Error in depth callback for {ticker}: {e}", exc_info=True
                        )
                else:
                    self.logger.warning(f"No on_depth_update callback set for {ticker}")

        except Exception as e:
            self.logger.error(f"Error processing depth message: {e}", exc_info=True)

    def _extract_depth(self, ticker: str, market_feed, is_snapshot: bool) -> dict[str, Any]:
        """
        Extract 50-level depth data from market feed with stateful updates

        Args:
            ticker: Symbol ticker for state tracking
            market_feed: Protobuf MarketFeed message
            is_snapshot: Whether this is a snapshot or diff

        Returns:
            Depth data dictionary with cumulative state
        """
        depth = market_feed.depth

        # Initialize state for this ticker if not exists
        if ticker not in self.depth_data:
            self.depth_data[ticker] = {
                "buy": [{"price": 0, "quantity": 0, "orders": 0} for _ in range(50)],
                "sell": [{"price": 0, "quantity": 0, "orders": 0} for _ in range(50)],
                "total_buy_qty": 0,
                "total_sell_qty": 0,
            }

        state = self.depth_data[ticker]

        # Process bids - update state at specific indices
        # Only update if the value is non-zero (0 means "no change" or "empty")
        if depth.bids:
            for i, bid in enumerate(depth.bids):
                if i >= 50:
                    break
                # Update price only if present and non-zero
                if bid.HasField("price") and bid.price.value > 0:
                    state["buy"][i]["price"] = bid.price.value / 100
                if bid.HasField("qty") and bid.qty.value > 0:
                    state["buy"][i]["quantity"] = bid.qty.value
                if bid.HasField("nord") and bid.nord.value > 0:
                    state["buy"][i]["orders"] = bid.nord.value

        # Process asks - update state at specific indices
        if depth.asks:
            for i, ask in enumerate(depth.asks):
                if i >= 50:
                    break
                # Update price only if present and non-zero
                if ask.HasField("price") and ask.price.value > 0:
                    state["sell"][i]["price"] = ask.price.value / 100
                if ask.HasField("qty") and ask.qty.value > 0:
                    state["sell"][i]["quantity"] = ask.qty.value
                if ask.HasField("nord") and ask.nord.value > 0:
                    state["sell"][i]["orders"] = ask.nord.value

        # Update total quantities if present
        if depth.HasField("tbq"):
            state["total_buy_qty"] = depth.tbq.value
        if depth.HasField("tsq"):
            state["total_sell_qty"] = depth.tsq.value

        # Get timestamps
        feed_time = market_feed.feed_time.value if market_feed.HasField("feed_time") else 0
        send_time = market_feed.send_time.value if market_feed.HasField("send_time") else 0

        # Return copy of current state - include all levels with non-zero price
        # (matching official SDK behavior which maintains all 50 levels)
        buy_levels = [level.copy() for level in state["buy"] if level["price"] > 0]
        sell_levels = [level.copy() for level in state["sell"] if level["price"] > 0]

        # Count actual filled levels for logging
        actual_levels = max(len(buy_levels), len(sell_levels))

        return {
            "buy": buy_levels,
            "sell": sell_levels,
            "total_buy_qty": state["total_buy_qty"],
            "total_sell_qty": state["total_sell_qty"],
            "snapshot": is_snapshot,
            "feed_time": feed_time,
            "send_time": send_time,
            "levels": actual_levels,
        }

    def _ping_loop(self):
        """Send periodic ping messages to keep connection alive"""
        while self.connected and self.running:
            try:
                if self.ws and self.ws.sock and self.ws.sock.connected:
                    self.ws.send("ping")
            except Exception as e:
                self.logger.debug(f"Ping error: {e}")

            time.sleep(10)

    def subscribe(self, symbols: list[str], channel: str = "1"):
        """
        Subscribe to 50-level depth for symbols

        Args:
            symbols: List of symbol tickers (e.g., ['NSE:RELIANCE-EQ', 'NSE:TCS-EQ'])
            channel: Channel number (1-50)
        """
        if not self.connected:
            self.logger.error("Not connected to TBT WebSocket")
            return False

        try:
            # Store subscription
            if channel not in self.subscriptions:
                self.subscriptions[channel] = set()
            self.subscriptions[channel].update(symbols)

            # Send subscribe message
            subscribe_msg = {
                "type": 1,
                "data": {"subs": 1, "symbols": list(symbols), "mode": "depth", "channel": channel},
            }

            self.ws.send(json.dumps(subscribe_msg))
            self.logger.debug(f"Subscribed to {len(symbols)} symbols on channel {channel}")

            # Resume channel if not active
            if channel not in self.active_channels:
                self.switch_channel(resume_channels=[channel], pause_channels=[])

            return True

        except Exception as e:
            self.logger.error(f"Subscribe error: {e}")
            return False

    def unsubscribe(self, symbols: list[str], channel: str = "1"):
        """
        Unsubscribe from symbols

        Args:
            symbols: List of symbol tickers
            channel: Channel number
        """
        if not self.connected:
            return False

        try:
            # Update subscription tracking
            if channel in self.subscriptions:
                self.subscriptions[channel].difference_update(symbols)
                if not self.subscriptions[channel]:
                    del self.subscriptions[channel]

            # Send unsubscribe message
            unsubscribe_msg = {
                "type": 1,
                "data": {"subs": -1, "symbols": list(symbols), "mode": "depth", "channel": channel},
            }

            self.ws.send(json.dumps(unsubscribe_msg))
            self.logger.debug(f"Unsubscribed from {len(symbols)} symbols on channel {channel}")

            return True

        except Exception as e:
            self.logger.error(f"Unsubscribe error: {e}")
            return False

    def switch_channel(self, resume_channels: list[str], pause_channels: list[str]):
        """
        Switch channel states (resume/pause)

        Args:
            resume_channels: Channels to resume receiving data
            pause_channels: Channels to pause
        """
        if not self.connected:
            return False

        try:
            # Update active channels
            self.active_channels.update(resume_channels)
            self.active_channels.difference_update(pause_channels)

            # Send switch message
            switch_msg = {
                "type": 2,
                "data": {
                    "resumeChannels": list(resume_channels),
                    "pauseChannels": list(pause_channels),
                },
            }

            self.ws.send(json.dumps(switch_msg))
            self.logger.debug(f"Channel switch: resume={resume_channels}, pause={pause_channels}")

            return True

        except Exception as e:
            self.logger.error(f"Channel switch error: {e}")
            return False

    def _resubscribe_all(self):
        """Resubscribe to all symbols after reconnection"""
        try:
            # Resume all active channels
            if self.active_channels:
                self.switch_channel(list(self.active_channels), [])

            # Resubscribe to all symbols
            for channel, symbols in self.subscriptions.items():
                if symbols:
                    subscribe_msg = {
                        "type": 1,
                        "data": {
                            "subs": 1,
                            "symbols": list(symbols),
                            "mode": "depth",
                            "channel": channel,
                        },
                    }
                    self.ws.send(json.dumps(subscribe_msg))
                    self.logger.debug(
                        f"Resubscribed to {len(symbols)} symbols on channel {channel}"
                    )

        except Exception as e:
            self.logger.error(f"Resubscribe error: {e}")

    def is_connected(self) -> bool:
        """Check if connected to TBT WebSocket"""
        return self.connected and self.running

    def get_depth(self, symbol: str) -> dict[str, Any] | None:
        """
        Get cached depth data for a symbol

        Args:
            symbol: Symbol ticker

        Returns:
            Depth data or None
        """
        return self.depth_data.get(symbol)

    def get_subscription_count(self) -> int:
        """Get total number of subscribed symbols"""
        return sum(len(symbols) for symbols in self.subscriptions.values())

    def __del__(self):
        """
        Destructor to ensure proper cleanup when TBT WebSocket is destroyed.
        This is critical for preventing FD leaks when objects are garbage collected.
        """
        try:
            if hasattr(self, "logger"):
                self.logger.debug("FyersTbtWebSocket destructor called")
            self.disconnect()
        except Exception as e:
            # Fallback logging if self.logger is not available
            import logging

            logger = logging.getLogger("fyers_tbt_websocket")
            logger.error(f"Error in TBT WebSocket destructor: {e}")

    def force_cleanup(self):
        """
        Force cleanup all resources (for emergency cleanup)
        """
        try:
            # Force stop all operations
            self.running = False
            self.connected = False
            self.reconnect_enabled = False

            # Force clear data structures
            if hasattr(self, "subscriptions"):
                self.subscriptions.clear()
            if hasattr(self, "active_channels"):
                self.active_channels.clear()
            if hasattr(self, "depth_data"):
                self.depth_data.clear()

            # Force close WebSocket
            if hasattr(self, "ws") and self.ws:
                try:
                    self.ws.close()
                except Exception:
                    pass
                self.ws = None

            # Reset thread references
            if hasattr(self, "ws_thread"):
                self.ws_thread = None
            if hasattr(self, "ping_thread"):
                self.ping_thread = None

        except Exception:
            pass  # Suppress all errors in force cleanup
