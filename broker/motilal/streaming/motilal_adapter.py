"""
Motilal Oswal WebSocket adapter for OpenAlgo streaming proxy.

This adapter integrates Motilal Oswal's WebSocket client with OpenAlgo's
WebSocket proxy infrastructure to provide standardized market data streaming.
"""

import threading
import json
import logging
import time
from typing import Dict, Any, Optional, List
import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from broker.motilal.api.motilal_websocket import MotilalWebSocket
from database.auth_db import get_auth_token
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .motilal_mapping import MotilalExchangeMapper, MotilalCapabilityRegistry


class MotilalWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Motilal Oswal-specific implementation of the WebSocket adapter"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("motilal_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "motilal"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
        self._data_poll_thread = None
        self._stop_poll = threading.Event()

    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Motilal Oswal WebSocket API

        Args:
            broker_name: Name of the broker (always 'motilal' in this case)
            user_id: Client ID/user ID
            auth_data: If provided, use these credentials instead of fetching from DB

        Raises:
            ValueError: If required authentication tokens are not found
        """
        self.user_id = user_id
        self.broker_name = broker_name

        # Get tokens from database if not provided
        if not auth_data:
            # Fetch authentication tokens from database
            auth_token = get_auth_token(user_id)
            # Get API key from environment variable (BROKER_API_SECRET)
            api_key = os.getenv('BROKER_API_SECRET')

            if not auth_token:
                self.logger.error(f"No authentication token found for user {user_id}")
                raise ValueError(f"No authentication token found for user {user_id}")

            if not api_key:
                self.logger.error("BROKER_API_SECRET environment variable not set")
                raise ValueError("BROKER_API_SECRET environment variable not set")
        else:
            # Use provided tokens
            auth_token = auth_data.get('auth_token')
            api_key = auth_data.get('api_key')

            if not auth_token or not api_key:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")

        # Create MotilalWebSocket instance
        self.ws_client = MotilalWebSocket(
            client_id=user_id,
            auth_token=auth_token,
            api_key=api_key,
            use_uat=False  # Use production environment
        )

        self.running = True
        self.logger.debug(f"Motilal WebSocket adapter initialized for user {user_id}")

    def connect(self) -> None:
        """Establish connection to Motilal WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _connect_with_retry(self) -> None:
        """Connect to Motilal WebSocket with retry logic"""
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.logger.debug(f"Connecting to Motilal WebSocket (attempt {self.reconnect_attempts + 1})")
                self.ws_client.connect()

                # Wait a bit for connection to establish
                time.sleep(2)

                if self.ws_client.is_websocket_connected():
                    self.connected = True
                    self.reconnect_attempts = 0  # Reset attempts on successful connection
                    self.logger.info("Successfully connected to Motilal WebSocket")

                    # Start data polling thread
                    self._start_data_polling()

                    # Resubscribe to existing subscriptions
                    self._resubscribe_all()
                    break
                else:
                    raise Exception("Connection established but not receiving data")

            except Exception as e:
                self.reconnect_attempts += 1
                delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), self.max_reconnect_delay)
                self.logger.error(f"Connection failed: {e}. Retrying in {delay} seconds...")
                time.sleep(delay)

        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Max reconnection attempts reached. Giving up.")

    def disconnect(self) -> None:
        """Disconnect from Motilal WebSocket"""
        self.running = False
        self._stop_poll.set()

        # Stop data polling thread
        if self._data_poll_thread and self._data_poll_thread.is_alive():
            self._data_poll_thread.join(timeout=2)

        if hasattr(self, 'ws_client') and self.ws_client:
            self.ws_client.disconnect()

        # Clean up ZeroMQ resources
        self.cleanup_zmq()
        self.logger.info("Motilal WebSocket disconnected")

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with Motilal-specific implementation

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Depth
            depth_level: Market depth level (only 5 supported)

        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate mode
        if mode not in [1, 2, 3]:
            return self._create_error_response("INVALID_MODE",
                                              f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)")

        # If depth mode, check if supported depth level
        if mode == 3 and depth_level not in [5]:
            return self._create_error_response("INVALID_DEPTH",
                                              f"Invalid depth level {depth_level}. Motilal only supports 5-level depth")

        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND",
                                              f"Symbol {symbol} not found for exchange {exchange}")

        token = token_info['token']
        brexchange = token_info['brexchange']

        # Get Motilal-specific exchange type
        motilal_exchange = MotilalExchangeMapper.get_exchange_type(brexchange)
        exchange_segment = MotilalCapabilityRegistry.get_exchange_segment(exchange)

        # Check if the requested depth level is supported for this exchange
        is_fallback = False
        actual_depth = depth_level

        if mode == 3:  # Depth mode
            if not MotilalCapabilityRegistry.is_depth_level_supported(exchange, depth_level):
                # If requested depth is not supported, use the highest available
                actual_depth = MotilalCapabilityRegistry.get_fallback_depth_level(
                    exchange, depth_level
                )
                is_fallback = True

                self.logger.debug(
                    f"Depth level {depth_level} not supported for {exchange}, "
                    f"using {actual_depth} instead"
                )

        # Generate unique correlation ID that includes mode
        correlation_id = f"{symbol}_{exchange}_{mode}"
        if mode == 3:
            correlation_id = f"{correlation_id}_{depth_level}"

        # Store subscription for reconnection
        with self.lock:
            self.subscriptions[correlation_id] = {
                'symbol': symbol,
                'exchange': exchange,
                'brexchange': brexchange,
                'token': token,
                'mode': mode,
                'depth_level': depth_level,
                'actual_depth': actual_depth,
                'motilal_exchange': motilal_exchange,
                'exchange_segment': exchange_segment,
                'is_fallback': is_fallback
            }

        # Subscribe if connected
        if self.connected and self.ws_client:
            try:
                # Register scrip with Motilal WebSocket
                success = self.ws_client.register_scrip(
                    exchange=motilal_exchange,
                    exchange_type=exchange_segment,
                    scrip_code=int(token),
                    symbol=symbol
                )

                if not success:
                    return self._create_error_response("SUBSCRIPTION_ERROR",
                                                      f"Failed to register scrip {symbol}")

                self.logger.debug(f"Subscribed to {symbol}.{exchange} (token: {token}, mode: {mode})")

            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

        # Return success with capability info
        return self._create_success_response(
            'Subscription requested' if not is_fallback else f"Using depth level {actual_depth} instead of requested {depth_level}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            requested_depth=depth_level,
            actual_depth=actual_depth,
            is_fallback=is_fallback
        )

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Unsubscribe from market data

        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode
            depth_level: Market depth level (used to match correlation ID for depth subscriptions)

        Returns:
            Dict: Response with status
        """
        # Map symbol to token
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND",
                                              f"Symbol {symbol} not found for exchange {exchange}")

        token = token_info['token']
        brexchange = token_info['brexchange']

        # Get Motilal-specific exchange type
        motilal_exchange = MotilalExchangeMapper.get_exchange_type(brexchange)
        exchange_segment = MotilalCapabilityRegistry.get_exchange_segment(exchange)

        # Generate correlation ID (must match the one used in subscribe)
        correlation_id = f"{symbol}_{exchange}_{mode}"
        if mode == 3:
            correlation_id = f"{correlation_id}_{depth_level}"

        # Remove from subscriptions
        with self.lock:
            if correlation_id in self.subscriptions:
                del self.subscriptions[correlation_id]

        # Unsubscribe if connected
        if self.connected and self.ws_client:
            try:
                # Unregister scrip with Motilal WebSocket
                success = self.ws_client.unregister_scrip(
                    exchange=motilal_exchange,
                    exchange_type=exchange_segment,
                    scrip_code=int(token)
                )

                if not success:
                    return self._create_error_response("UNSUBSCRIPTION_ERROR",
                                                      f"Failed to unregister scrip {symbol}")

            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode
        )

    def _resubscribe_all(self) -> None:
        """Resubscribe to all existing subscriptions after reconnection"""
        with self.lock:
            subscriptions_copy = dict(self.subscriptions)

        for correlation_id, sub in subscriptions_copy.items():
            try:
                success = self.ws_client.register_scrip(
                    exchange=sub['motilal_exchange'],
                    exchange_type=sub['exchange_segment'],
                    scrip_code=int(sub['token']),
                    symbol=sub['symbol']
                )

                if success:
                    self.logger.debug(f"Resubscribed to {sub['symbol']}.{sub['exchange']}")
                else:
                    self.logger.warning(f"Failed to resubscribe to {sub['symbol']}.{sub['exchange']}")

            except Exception as e:
                self.logger.error(f"Error resubscribing to {sub['symbol']}.{sub['exchange']}: {e}")

    def _start_data_polling(self) -> None:
        """Start thread to poll market data from Motilal WebSocket client"""
        self._stop_poll.clear()
        self._data_poll_thread = threading.Thread(target=self._poll_market_data, daemon=True)
        self._data_poll_thread.start()
        self.logger.debug("Started market data polling thread")

    def _poll_market_data(self) -> None:
        """
        Poll market data from Motilal WebSocket client and publish to ZeroMQ.

        Since Motilal stores data in internal dictionaries (last_quotes, last_depth, last_oi),
        we need to periodically poll and publish this data.
        """
        self.logger.debug("Market data polling started")

        while not self._stop_poll.is_set() and self.running:
            try:
                with self.lock:
                    subscriptions_copy = dict(self.subscriptions)

                # Poll data for each subscription
                for correlation_id, sub in subscriptions_copy.items():
                    try:
                        symbol = sub['symbol']
                        exchange = sub['exchange']
                        mode = sub['mode']
                        token = sub['token']
                        motilal_exchange = sub['motilal_exchange']

                        # Get market data based on mode
                        market_data = None

                        if mode == 1:  # LTP only
                            quote = self.ws_client.get_quote(motilal_exchange, token)
                            if quote:
                                market_data = self._normalize_ltp_data(quote)

                        elif mode == 2:  # Quote (LTP + OHLC + Volume)
                            quote = self.ws_client.get_quote(motilal_exchange, token)
                            if quote:
                                market_data = self._normalize_quote_data(quote)

                        elif mode == 3:  # Depth (Full data including market depth)
                            quote = self.ws_client.get_quote(motilal_exchange, token)
                            depth = self.ws_client.get_market_depth(motilal_exchange, token)
                            oi = self.ws_client.get_open_interest(motilal_exchange, token)

                            if quote:
                                market_data = self._normalize_depth_data(quote, depth, oi)

                        # Publish data if available
                        if market_data:
                            # Add metadata
                            market_data.update({
                                'symbol': symbol,
                                'exchange': exchange,
                                'mode': mode,
                                'timestamp': int(time.time() * 1000)
                            })

                            # Create topic for ZeroMQ
                            mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}[mode]
                            topic = f"{exchange}_{symbol}_{mode_str}"

                            # Publish to ZeroMQ
                            self.publish_market_data(topic, market_data)

                            self.logger.debug(f"Published {mode_str} data for {symbol}.{exchange}")

                    except Exception as e:
                        self.logger.error(f"Error polling data for {correlation_id}: {e}")

                # Sleep between polls (adjust based on performance needs)
                time.sleep(0.5)  # Poll every 500ms

            except Exception as e:
                self.logger.error(f"Error in polling loop: {e}", exc_info=True)
                time.sleep(1)

        self.logger.debug("Market data polling stopped")

    def _normalize_ltp_data(self, quote: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize LTP data from Motilal format to common format

        Args:
            quote: Quote data from Motilal WebSocket

        Returns:
            Dict: Normalized LTP data
        """
        return {
            'ltp': quote.get('ltp', 0),
            'volume': quote.get('volume', 0)
        }

    def _normalize_quote_data(self, quote: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Quote data from Motilal format to common format

        Args:
            quote: Quote data from Motilal WebSocket

        Returns:
            Dict: Normalized Quote data
        """
        return {
            'ltp': quote.get('ltp', 0),
            'volume': quote.get('volume', 0),
            'open': quote.get('open', 0),
            'high': quote.get('high', 0),
            'low': quote.get('low', 0),
            'close': quote.get('prev_close', 0),
            'avg_price': quote.get('avg_trade_price', 0),
        }

    def _normalize_depth_data(self, quote: Dict[str, Any], depth: Optional[Dict[str, Any]],
                              oi: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Normalize Depth data from Motilal format to common format

        Note: Motilal only provides depth level 1 (best bid/ask).
        Levels 2-5 are padded with zeros to maintain standard 5-level depth format.

        Args:
            quote: Quote data from Motilal WebSocket
            depth: Market depth data (can be None)
            oi: Open interest data (can be None)

        Returns:
            Dict: Normalized Depth data with 5 levels
        """
        result = {
            'ltp': quote.get('ltp', 0),
            'volume': quote.get('volume', 0),
            'open': quote.get('open', 0),
            'high': quote.get('high', 0),
            'low': quote.get('low', 0),
            'close': quote.get('prev_close', 0),
            'upper_circuit': quote.get('upper_circuit', 0),
            'lower_circuit': quote.get('lower_circuit', 0)
        }

        # Add OI if available
        if oi:
            result['oi'] = oi.get('oi', 0)
        else:
            result['oi'] = 0

        # Add depth data - always ensure 5 levels
        buy_depth = []
        sell_depth = []

        if depth:
            # Get existing bids and asks (Motilal typically provides only level 1)
            bids = depth.get('bids', [])
            asks = depth.get('asks', [])

            # Ensure exactly 5 levels for buy depth
            for i in range(5):
                if i < len(bids) and bids[i] is not None:
                    buy_depth.append({
                        'price': bids[i].get('price', 0),
                        'quantity': bids[i].get('quantity', 0),
                        'orders': bids[i].get('orders', 0)
                    })
                else:
                    # Pad with zeros for levels 2-5
                    buy_depth.append({
                        'price': 0,
                        'quantity': 0,
                        'orders': 0
                    })

            # Ensure exactly 5 levels for sell depth
            for i in range(5):
                if i < len(asks) and asks[i] is not None:
                    sell_depth.append({
                        'price': asks[i].get('price', 0),
                        'quantity': asks[i].get('quantity', 0),
                        'orders': asks[i].get('orders', 0)
                    })
                else:
                    # Pad with zeros for levels 2-5
                    sell_depth.append({
                        'price': 0,
                        'quantity': 0,
                        'orders': 0
                    })
        else:
            # No depth data available - return 5 levels of zeros
            for i in range(5):
                buy_depth.append({'price': 0, 'quantity': 0, 'orders': 0})
                sell_depth.append({'price': 0, 'quantity': 0, 'orders': 0})

        result['depth'] = {
            'buy': buy_depth,
            'sell': sell_depth
        }

        return result
