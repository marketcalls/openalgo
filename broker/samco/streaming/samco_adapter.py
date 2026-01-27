import json
import logging
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional

from broker.samco.api.data import BrokerData
from broker.samco.streaming.samcoWebSocket import SamcoWebSocket
from database.auth_db import get_auth_token

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .samco_mapping import SamcoCapabilityRegistry, SamcoExchangeMapper


class SamcoWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Samco-specific implementation of the WebSocket adapter"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("samco_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "samco"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None
    ) -> None:
        """
        Initialize connection with Samco WebSocket API

        Args:
            broker_name: Name of the broker (always 'samco' in this case)
            user_id: Client ID/user ID
            auth_data: If provided, use these credentials instead of fetching from DB

        Raises:
            ValueError: If required authentication tokens are not found
        """
        self.user_id = user_id
        self.broker_name = broker_name

        # Get tokens from database if not provided
        if not auth_data:
            # Fetch authentication token from database
            session_token = get_auth_token(user_id)

            if not session_token:
                self.logger.error(f"No authentication token found for user {user_id}")
                raise ValueError(f"No authentication token found for user {user_id}")
        else:
            # Use provided tokens
            session_token = auth_data.get("session_token") or auth_data.get("auth_token")

            if not session_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data (session_token)")

        # Create SamcoWebSocket instance
        self.ws_client = SamcoWebSocket(session_token=session_token, user_id=user_id)

        # Set callbacks
        self.ws_client.on_open = self._on_open
        self.ws_client.on_data = self._on_data
        self.ws_client.on_error = self._on_error
        self.ws_client.on_close = self._on_close
        self.ws_client.on_message = self._on_message

        self.running = True

    def connect(self) -> None:
        """Establish connection to Samco WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _connect_with_retry(self) -> None:
        """Connect to Samco WebSocket with retry logic"""
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.logger.info(
                    f"Connecting to Samco WebSocket (attempt {self.reconnect_attempts + 1})"
                )
                self.ws_client.connect()
                self.reconnect_attempts = 0  # Reset attempts on successful connection
                break

            except Exception as e:
                self.reconnect_attempts += 1
                delay = min(
                    self.reconnect_delay * (2**self.reconnect_attempts), self.max_reconnect_delay
                )
                self.logger.error(f"Connection failed: {e}. Retrying in {delay} seconds...")
                time.sleep(delay)

        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Max reconnection attempts reached. Giving up.")

    def disconnect(self) -> None:
        """Disconnect from Samco WebSocket"""
        self.running = False
        if hasattr(self, "ws_client") and self.ws_client:
            self.ws_client.close_connection()

        # Clean up ZeroMQ resources
        self.cleanup_zmq()

    def subscribe(
        self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5
    ) -> dict[str, Any]:
        """
        Subscribe to market data with Samco-specific implementation

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Snap Quote (Depth)
            depth_level: Market depth level (5)

        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate the mode
        if mode not in [1, 2, 3]:
            return self._create_error_response(
                "INVALID_MODE", f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)"
            )

        # If depth mode, check if supported depth level
        if mode == 3 and depth_level not in [5]:
            return self._create_error_response(
                "INVALID_DEPTH", f"Invalid depth level {depth_level}. Must be 5"
            )

        # Handle index symbols - fetch listingId from API
        if exchange in ["NSE_INDEX", "BSE_INDEX"]:
            try:
                # Get auth token for API call
                auth_token = get_auth_token(self.user_id)
                if not auth_token:
                    return self._create_error_response(
                        "AUTH_ERROR", f"No auth token found for user {self.user_id}"
                    )

                # Create BrokerData instance and fetch listingId
                broker_data = BrokerData(auth_token)
                listing_id = broker_data.get_index_listing_id(symbol, exchange)

                # For index, use listingId as token (e.g., '-23' for NIFTY)
                token = listing_id
                brexchange = "NSE" if exchange == "NSE_INDEX" else "BSE"

                self.logger.info(
                    f"Samco index subscribe: symbol={symbol}, exchange={exchange}, listingId={listing_id}"
                )

            except Exception as e:
                self.logger.error(f"Error getting index listingId for {symbol}: {e}")
                return self._create_error_response(
                    "INDEX_ERROR", f"Error getting index listingId: {str(e)}"
                )
        else:
            # Map symbol to token using symbol mapper for non-index symbols
            token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
            if not token_info:
                return self._create_error_response(
                    "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
                )

            token = token_info["token"]
            brexchange = token_info["brexchange"]

            # Debug log the token format
            self.logger.info(
                f"Samco subscribe: symbol={symbol}, exchange={exchange}, token={token}, brexchange={brexchange}"
            )

        # Check if the requested depth level is supported for this exchange
        is_fallback = False
        actual_depth = depth_level

        if mode == 3:  # Snap Quote mode (includes depth data)
            if not SamcoCapabilityRegistry.is_depth_level_supported(exchange, depth_level):
                # If requested depth is not supported, use the highest available
                actual_depth = SamcoCapabilityRegistry.get_fallback_depth_level(
                    exchange, depth_level
                )
                is_fallback = True

                self.logger.info(
                    f"Depth level {depth_level} not supported for {exchange}, "
                    f"using {actual_depth} instead"
                )

        # Create token list for Samco API
        # Samco uses symbol names with exchange
        token_list = [
            {"exchangeType": SamcoExchangeMapper.get_exchange_type(brexchange), "tokens": [token]}
        ]

        # Generate unique correlation ID that includes mode to prevent overwriting
        correlation_id = f"{symbol}_{exchange}_{mode}"
        if mode == 3:
            correlation_id = f"{correlation_id}_{depth_level}"

        # Store subscription for reconnection
        with self.lock:
            self.subscriptions[correlation_id] = {
                "symbol": symbol,
                "exchange": exchange,
                "brexchange": brexchange,
                "token": token,
                "mode": mode,
                "depth_level": depth_level,
                "actual_depth": actual_depth,
                "token_list": token_list,
                "is_fallback": is_fallback,
            }

        # Subscribe if connected
        if self.connected and self.ws_client:
            try:
                self.ws_client.subscribe(correlation_id, mode, token_list)
            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

        # Return success with capability info
        return self._create_success_response(
            "Subscription requested"
            if not is_fallback
            else f"Using depth level {actual_depth} instead of requested {depth_level}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            requested_depth=depth_level,
            actual_depth=actual_depth,
            is_fallback=is_fallback,
        )

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> dict[str, Any]:
        """
        Unsubscribe from market data

        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode

        Returns:
            Dict: Response with status
        """
        # Handle index symbols - need to use listingId for streaming
        if exchange in ["NSE_INDEX", "BSE_INDEX"]:
            try:
                auth_token = get_auth_token(self.user_id)
                if not auth_token:
                    return self._create_error_response(
                        "AUTH_ERROR", "Authentication token not found"
                    )
                broker_data = BrokerData(auth_token)
                listing_id = broker_data.get_index_listing_id(symbol, exchange)
                token = listing_id  # e.g., '-21' for NIFTY
                brexchange = "NSE" if exchange == "NSE_INDEX" else "BSE"
                self.logger.info(
                    f"Samco index unsubscribe: symbol={symbol}, exchange={exchange}, listingId={listing_id}"
                )
            except Exception as e:
                self.logger.error(f"Error getting index listingId for unsubscribe: {e}")
                return self._create_error_response(
                    "INDEX_ERROR", f"Failed to get index listingId: {str(e)}"
                )
        else:
            # Map symbol to token for non-index symbols
            token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
            if not token_info:
                return self._create_error_response(
                    "SYMBOL_NOT_FOUND", f"Symbol {symbol} not found for exchange {exchange}"
                )

            token = token_info["token"]
            brexchange = token_info["brexchange"]

        # Create token list for Samco API
        token_list = [
            {"exchangeType": SamcoExchangeMapper.get_exchange_type(brexchange), "tokens": [token]}
        ]

        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Remove from subscriptions
        with self.lock:
            if correlation_id in self.subscriptions:
                del self.subscriptions[correlation_id]

        # Unsubscribe if connected
        if self.connected and self.ws_client:
            try:
                self.ws_client.unsubscribe(correlation_id, mode, token_list)
            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
        )

    def _on_open(self, wsapp) -> None:
        """Callback when connection is established"""
        self.logger.info("Connected to Samco WebSocket")
        self.connected = True

        # Resubscribe to existing subscriptions if reconnecting
        # Group subscriptions by mode and batch them into single requests
        with self.lock:
            subscriptions_by_mode = {}
            for correlation_id, sub in self.subscriptions.items():
                mode = sub["mode"]
                if mode not in subscriptions_by_mode:
                    subscriptions_by_mode[mode] = []
                # Collect all token_lists for this mode
                subscriptions_by_mode[mode].extend(sub["token_list"])

            # Send batched subscriptions for each mode
            for mode, token_list in subscriptions_by_mode.items():
                try:
                    # Merge all tokens by exchange
                    merged_tokens = {}
                    for token_group in token_list:
                        exchange = token_group.get("exchangeType", "NSE")
                        tokens = token_group.get("tokens", [])
                        if exchange not in merged_tokens:
                            merged_tokens[exchange] = []
                        merged_tokens[exchange].extend(tokens)

                    # Build merged token_list
                    merged_token_list = [
                        {"exchangeType": ex, "tokens": list(set(toks))}  # Remove duplicates
                        for ex, toks in merged_tokens.items()
                    ]

                    self.ws_client.subscribe(f"batch_mode_{mode}", mode, merged_token_list)
                    self.logger.info(
                        f"Batch resubscribed mode {mode} with {len(merged_token_list)} exchange groups"
                    )
                except Exception as e:
                    self.logger.error(f"Error batch resubscribing mode {mode}: {e}")

    def _on_error(self, wsapp, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"Samco WebSocket error: {error}")

    def _on_close(self, wsapp) -> None:
        """Callback when connection is closed"""
        self.logger.info("Samco WebSocket connection closed")
        self.connected = False

        # Attempt to reconnect if we're still running
        if self.running:
            threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _on_message(self, wsapp, message) -> None:
        """Callback for text messages from the WebSocket"""
        self.logger.debug(f"Received message: {message}")

    def _on_data(self, wsapp, message) -> None:
        """Callback for market data from the WebSocket"""
        try:
            # Log the raw message data (DEBUG level to avoid flooding logs)
            self.logger.debug(f"SAMCO ADAPTER received data: {message}")

            if not isinstance(message, dict):
                self.logger.warning(f"Received message is not a dictionary: {type(message)}")
                return

            # Extract symbol from the message
            symbol_key = message.get("symbol", "") or message.get("token", "")

            # Skip if no symbol (non-data message)
            if not symbol_key:
                self.logger.debug("Received message without symbol, skipping")
                return

            # Get the message's subscription mode (from streaming_type)
            # Mode 2 = "quote" (LTP/Quote data), Mode 3 = "quote2" (Depth data)
            msg_mode = message.get("subscription_mode", 2)

            # Determine which subscription modes this message should go to
            # "quote" messages (mode 2) should go to LTP (1) and Quote (2) subscribers
            # "quote2" messages (mode 3) should go to Depth (3) subscribers
            if msg_mode == 3:
                target_modes = [3]  # Depth data only goes to depth subscribers
            else:
                target_modes = [1, 2]  # Quote data goes to LTP and Quote subscribers

            # Find ALL subscriptions that match this symbol and have compatible modes
            matching_subscriptions = []
            with self.lock:
                for sub in self.subscriptions.values():
                    # Check if mode is compatible
                    if sub["mode"] not in target_modes:
                        continue

                    # Match by token (may be "11536_NSE" or "11536")
                    if sub["token"] == symbol_key or sub["symbol"] == symbol_key:
                        matching_subscriptions.append(sub)
                        continue

                    # Try matching with exchange suffix (if token doesn't have it)
                    token_with_exchange = f"{sub['token']}_{sub['brexchange']}"
                    if symbol_key == token_with_exchange:
                        matching_subscriptions.append(sub)
                        continue

                    # Try matching by extracting scripCode from symbol_key (handle "11536_NSE" -> "11536")
                    if "_" in symbol_key:
                        scripcode = symbol_key.split("_")[0]
                        if sub["token"] == scripcode:
                            matching_subscriptions.append(sub)
                            continue

            if not matching_subscriptions:
                self.logger.debug(
                    f"No matching subscription for symbol: {symbol_key}, msg_mode: {msg_mode}"
                )
                return

            # Publish to all matching subscriptions
            for subscription in matching_subscriptions:
                symbol = subscription["symbol"]
                exchange = subscription["exchange"]
                mode = subscription["mode"]

                # Use subscription mode for topic
                mode_str = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}.get(mode, "QUOTE")
                topic = f"{exchange}_{symbol}_{mode_str}"

                # Normalize the data based on subscription mode
                market_data = self._normalize_market_data(message, mode)

                # Add metadata
                market_data.update(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "mode": mode,
                        "timestamp": int(time.time() * 1000),  # Current timestamp in ms
                    }
                )

                # Log the market data we're sending (DEBUG level to avoid flooding logs)
                self.logger.debug(
                    f"Publishing to topic {topic}: ltp={market_data.get('ltp')}, depth={bool(market_data.get('depth'))}"
                )

                # Publish to ZeroMQ
                self.publish_market_data(topic, market_data)

        except Exception as e:
            self.logger.error(f"Error processing market data: {e}", exc_info=True)

    def _normalize_market_data(self, message, mode) -> dict[str, Any]:
        """
        Normalize broker-specific data format to a common format.

        Note: The data is already normalized by samcoWebSocket, so we just
        pass through the relevant fields based on mode.

        Args:
            message: The normalized message from samcoWebSocket
            mode: Subscription mode

        Returns:
            Dict: Market data for publishing
        """
        if mode == 1:  # LTP mode
            return {
                "ltp": message.get("last_traded_price", 0),
                "ltt": message.get("exchange_timestamp", 0),
            }
        elif mode == 2:  # Quote mode
            return {
                "ltp": message.get("last_traded_price", 0),
                "ltt": message.get("exchange_timestamp", 0),
                "volume": message.get("volume_trade_for_the_day", 0),
                "open": message.get("open_price_of_the_day", 0),
                "high": message.get("high_price_of_the_day", 0),
                "low": message.get("low_price_of_the_day", 0),
                "close": message.get("closed_price", 0),
                "last_trade_quantity": message.get("last_traded_quantity", 0),
                "change": message.get("change", 0),
                "change_percentage": message.get("change_percentage", 0),
                "best_bid_price": message.get("best_bid_price", 0),
                "best_bid_quantity": message.get("best_bid_quantity", 0),
                "best_ask_price": message.get("best_ask_price", 0),
                "best_ask_quantity": message.get("best_ask_quantity", 0),
            }
        elif mode == 3:  # Snap Quote mode (includes depth data)
            result = {
                "ltp": message.get("last_traded_price", 0),
                "ltt": message.get("exchange_timestamp", 0),
                "volume": message.get("volume_trade_for_the_day", 0),
                "open": message.get("open_price_of_the_day", 0),
                "high": message.get("high_price_of_the_day", 0),
                "low": message.get("low_price_of_the_day", 0),
                "close": message.get("closed_price", 0),
                "last_quantity": message.get("last_traded_quantity", 0),
                "change": message.get("change", 0),
                "change_percentage": message.get("change_percentage", 0),
            }

            # Pass through depth data from samcoWebSocket normalization
            if "depth" in message:
                result["depth"] = message["depth"]

            return result
        else:
            return {}

    def _extract_depth_data(self, message, is_buy: bool) -> list[dict[str, Any]]:
        """
        Extract depth data from Samco's message format

        Args:
            message: The raw message containing depth data
            is_buy: Whether to extract buy or sell side

        Returns:
            List: List of depth levels with price, quantity, and orders
        """
        depth = []
        side_label = "Buy" if is_buy else "Sell"

        # Get the appropriate depth data key
        depth_key = "best_5_buy_data" if is_buy else "best_5_sell_data"
        depth_data = message.get(depth_key, [])

        self.logger.debug(f"Extracting {side_label} depth data: {len(depth_data)} levels")

        for level in depth_data:
            if isinstance(level, dict):
                depth.append(
                    {
                        "price": level.get("price", 0),
                        "quantity": level.get("quantity", 0),
                        "orders": level.get("no of orders", 0),
                    }
                )

        # Pad to 5 levels if needed
        while len(depth) < 5:
            depth.append({"price": 0.0, "quantity": 0, "orders": 0})

        return depth
