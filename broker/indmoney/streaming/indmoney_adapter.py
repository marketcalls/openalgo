import threading
import json
import logging
import time
from typing import Dict, Any, Optional, List

from broker.indmoney.streaming.indWebSocket import IndWebSocket
from database.auth_db import get_auth_token

import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .indmoney_mapping import (
    IndmoneyExchangeMapper,
    IndmoneyModeMapper,
    IndmoneyCapabilityRegistry
)


class IndmoneyWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """INDmoney-specific implementation of the WebSocket adapter"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("indmoney_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "indmoney"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
        self.last_values = {}  # Cache for retaining last known values

    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with INDmoney WebSocket API

        Args:
            broker_name: Name of the broker (always 'indmoney' in this case)
            user_id: Client ID/user ID
            auth_data: If provided, use these credentials instead of fetching from DB

        Raises:
            ValueError: If required authentication tokens are not found
        """
        self.user_id = user_id
        self.broker_name = broker_name

        # Get access token from database if not provided
        if not auth_data:
            # Fetch authentication token from database
            access_token = get_auth_token(user_id)

            if not access_token:
                self.logger.error(f"No access token found for user {user_id}")
                raise ValueError(f"No access token found for user {user_id}")
        else:
            # Use provided token
            access_token = auth_data.get('access_token') or auth_data.get('auth_token')

            if not access_token:
                self.logger.error("Missing required access token")
                raise ValueError("Missing required access token")

        # Create IndWebSocket instance
        self.ws_client = IndWebSocket(
            access_token=access_token,
            max_retry_attempt=5,
            retry_strategy=1,  # Exponential backoff
            retry_delay=5,
            retry_multiplier=2
        )

        # Set callbacks
        self.ws_client.on_open = self._on_open
        self.ws_client.on_data = self._on_data
        self.ws_client.on_error = self._on_error
        self.ws_client.on_close = self._on_close
        self.ws_client.on_message = self._on_message

        self.running = True
        self.logger.info(f"INDmoney WebSocket adapter initialized for user {user_id}")

    def connect(self) -> None:
        """Establish connection to INDmoney WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        threading.Thread(target=self._connect_with_retry, daemon=True).start()

    def _connect_with_retry(self) -> None:
        """Connect to INDmoney WebSocket with retry logic"""
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.logger.info(f"Connecting to INDmoney WebSocket (attempt {self.reconnect_attempts + 1})")
                self.ws_client.connect()
                self.reconnect_attempts = 0  # Reset attempts on successful connection
                break

            except Exception as e:
                self.reconnect_attempts += 1
                delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), self.max_reconnect_delay)
                self.logger.error(f"Connection failed: {e}. Retrying in {delay} seconds...")
                time.sleep(delay)

        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Max reconnection attempts reached. Giving up.")

    def disconnect(self) -> None:
        """Disconnect from INDmoney WebSocket"""
        self.running = False
        if hasattr(self, 'ws_client') and self.ws_client:
            self.ws_client.close_connection()

        # Clean up ZeroMQ resources
        self.cleanup_zmq()

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 1) -> Dict[str, Any]:
        """
        Subscribe to market data with INDmoney-specific implementation

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote
            depth_level: Market depth level (INDmoney only supports 1)

        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate the mode
        if mode not in [1, 2]:
            return self._create_error_response(
                "INVALID_MODE",
                f"Invalid mode {mode}. INDmoney supports only 1 (LTP) or 2 (Quote)"
            )

        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND",
                f"Symbol {symbol} not found for exchange {exchange}"
            )

        token = token_info['token']
        brexchange = token_info['brexchange']

        # Create INDmoney instrument token (SEGMENT:TOKEN format)
        instrument_token = IndmoneyExchangeMapper.create_instrument_token(brexchange, token)

        # Convert mode to INDmoney format
        indmoney_mode = IndmoneyModeMapper.get_indmoney_mode(mode)

        # Generate unique correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Store subscription for reconnection
        with self.lock:
            self.subscriptions[correlation_id] = {
                'symbol': symbol,
                'exchange': exchange,
                'brexchange': brexchange,
                'token': token,
                'instrument_token': instrument_token,
                'mode': mode,
                'indmoney_mode': indmoney_mode,
                'depth_level': depth_level
            }

        # Subscribe if connected
        self.logger.info(f"Checking connection status: connected={self.connected}, ws_client={self.ws_client is not None}")
        if self.connected and self.ws_client:
            try:
                self.logger.info(f"ATTEMPTING SUBSCRIPTION: {symbol}.{exchange}, instrument_token={instrument_token}, mode={indmoney_mode}")
                self.ws_client.subscribe(
                    instruments=[instrument_token],
                    mode=indmoney_mode
                )
                self.logger.info(f"SUBSCRIPTION SENT: {symbol}.{exchange} in {indmoney_mode} mode")
            except Exception as e:
                self.logger.error(f"SUBSCRIPTION ERROR for {symbol}.{exchange}: {e}", exc_info=True)
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))
        else:
            self.logger.warning(f"NOT CONNECTED YET - subscription will be sent when connection opens")

        # Return success
        return self._create_success_response(
            f"Subscription requested for {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            instrument_token=instrument_token
        )

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> Dict[str, Any]:
        """
        Unsubscribe from market data

        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode

        Returns:
            Dict: Response with status
        """
        # Map symbol to token
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response(
                "SYMBOL_NOT_FOUND",
                f"Symbol {symbol} not found for exchange {exchange}"
            )

        token = token_info['token']
        brexchange = token_info['brexchange']

        # Create INDmoney instrument token
        instrument_token = IndmoneyExchangeMapper.create_instrument_token(brexchange, token)

        # Convert mode to INDmoney format
        indmoney_mode = IndmoneyModeMapper.get_indmoney_mode(mode)

        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Remove from subscriptions
        should_disconnect = False
        with self.lock:
            if correlation_id in self.subscriptions:
                del self.subscriptions[correlation_id]
            # Check if all subscriptions are removed
            if len(self.subscriptions) == 0:
                should_disconnect = True
            # Clear cached values for this symbol
            cache_key = f"{symbol}_{exchange}"
            if cache_key in self.last_values:
                del self.last_values[cache_key]

        # Unsubscribe if connected
        if self.connected and self.ws_client:
            try:
                self.ws_client.unsubscribe(
                    instruments=[instrument_token],
                    mode=indmoney_mode
                )
                self.logger.info(f"Unsubscribed from {symbol}.{exchange}")
            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))

        # Disconnect from broker if no subscriptions remain
        if should_disconnect:
            self.logger.info("No subscriptions remaining, disconnecting from broker")
            self.disconnect()

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode
        )

    def _on_open(self, wsapp) -> None:
        """Callback when connection is established"""
        self.logger.info("==================== WEBSOCKET OPENED ====================")
        self.logger.info(f"Connection established to INDmoney WebSocket")
        self.connected = True

        # Resubscribe to existing subscriptions if reconnecting
        with self.lock:
            self.logger.info(f"Number of stored subscriptions: {len(self.subscriptions)}")

            # Group subscriptions by mode for efficient resubscription
            ltp_instruments = []
            quote_instruments = []

            for correlation_id, sub in self.subscriptions.items():
                instrument_token = sub['instrument_token']
                mode = sub['indmoney_mode']
                self.logger.info(f"  - {correlation_id}: instrument={instrument_token}, mode={mode}")

                if mode == 'ltp':
                    ltp_instruments.append(instrument_token)
                elif mode == 'quote':
                    quote_instruments.append(instrument_token)

            # Resubscribe in batches
            try:
                if ltp_instruments:
                    self.logger.info(f"RESUBSCRIBING to {len(ltp_instruments)} LTP instruments: {ltp_instruments}")
                    self.ws_client.subscribe(instruments=ltp_instruments, mode='ltp')
                    self.logger.info(f"✓ Resubscribed to {len(ltp_instruments)} instruments in LTP mode")

                if quote_instruments:
                    self.logger.info(f"RESUBSCRIBING to {len(quote_instruments)} QUOTE instruments: {quote_instruments}")
                    self.ws_client.subscribe(instruments=quote_instruments, mode='quote')
                    self.logger.info(f"✓ Resubscribed to {len(quote_instruments)} instruments in QUOTE mode")

                if not ltp_instruments and not quote_instruments:
                    self.logger.warning("No subscriptions to resubscribe (subscriptions list is empty)")

            except Exception as e:
                self.logger.error(f"Error resubscribing: {e}", exc_info=True)

        self.logger.info("==================== READY FOR DATA ====================")

    def _on_error(self, wsapp, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"INDmoney WebSocket error: {error}")

    def _on_close(self, wsapp) -> None:
        """Callback when connection is closed"""
        self.logger.info("INDmoney WebSocket connection closed")
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
            # Parse JSON if message comes as string
            if isinstance(message, str):
                self.logger.debug(f"Parsing JSON string: {message[:100]}...")
                message = json.loads(message)

            # Log all incoming messages for debugging
            self.logger.info(f">> RAW INDMONEY DATA: {message}")

            # INDmoney sends data in JSON format
            # Expected format from API doc:
            # {
            #   "mode": "ltp",
            #   "instrument": "2885",
            #   "timestamp": 1750138351089,
            #   "data": {"ltp": 1426}
            # }

            if not isinstance(message, dict):
                self.logger.warning(f"[WARN] Message is not a dictionary after parsing: {type(message)}")
                return

            # Extract instrument token and mode
            instrument = message.get('instrument')
            mode = message.get('mode')
            data = message.get('data', {})

            self.logger.info(f"[DATA] Instrument={instrument}, Mode={mode}, Data={data}")

            if not instrument or not mode:
                self.logger.warning(f"[WARN] Message missing instrument or mode: {message}")
                return

            # Find the subscription that matches this instrument
            subscription = None
            with self.lock:
                for sub in self.subscriptions.values():
                    # INDmoney returns only the token part, not the full SEGMENT:TOKEN
                    if sub['token'] == instrument:
                        subscription = sub
                        break

            if not subscription:
                self.logger.debug(f"Received data for unsubscribed instrument: {instrument}")
                return

            # Create topic for ZeroMQ
            symbol = subscription['symbol']
            exchange = subscription['exchange']

            # Map INDmoney mode to OpenAlgo mode string
            mode_str = 'LTP' if mode == 'ltp' else 'QUOTE'
            topic = f"{exchange}_{symbol}_{mode_str}"

            # Normalize the data with caching for value retention
            cache_key = f"{symbol}_{exchange}"
            market_data = self._normalize_market_data(message, mode, cache_key)

            # Add metadata
            market_data.update({
                'symbol': symbol,
                'exchange': exchange,
                'mode': subscription['mode'],
                'timestamp': message.get('timestamp', int(time.time() * 1000))
            })

            # Log and publish
            self.logger.debug(f"Publishing market data: topic={topic}, data={market_data}")
            self.publish_market_data(topic, market_data)

        except Exception as e:
            self.logger.error(f"Error processing market data: {e}", exc_info=True)

    def _normalize_market_data(self, message: Dict[str, Any], mode: str, cache_key: str) -> Dict[str, Any]:
        """
        Normalize broker-specific data format to a common format.
        Retains previous values if new value is 0 or missing.

        Args:
            message: The raw message from the broker
            mode: Subscription mode ('ltp' or 'quote')
            cache_key: Key for caching values (symbol_exchange)

        Returns:
            Dict: Normalized market data
        """
        data = message.get('data', {})
        timestamp = message.get('timestamp', int(time.time() * 1000))

        # Get cached values for this symbol - thread-safe copy
        with self.lock:
            cached = self.last_values.get(cache_key, {}).copy()

        def get_value(key: str, default=0):
            """Get new value if non-zero, otherwise return cached value"""
            new_val = data.get(key, 0)
            if new_val != 0:
                return new_val
            return cached.get(key, default)

        if mode == 'ltp':
            result = {
                'ltp': get_value('ltp'),
                'ltt': timestamp
            }
        elif mode == 'quote':
            result = {
                'ltp': get_value('ltp'),
                'ltt': timestamp,
                'open': get_value('open'),
                'high': get_value('high'),
                'low': get_value('low'),
                'close': get_value('close'),
                'volume': get_value('volume'),
                'bid_price': get_value('bid_price'),
                'bid_qty': get_value('bid_qty'),
                'ask_price': get_value('ask_price'),
                'ask_qty': get_value('ask_qty'),
                'average_price': get_value('average_price'),
                'oi': get_value('oi'),
                'oi_change': get_value('oi_change')
            }
        else:
            result = {}

        # Update cache with current values (only non-zero values) - thread-safe
        if result:
            with self.lock:
                if cache_key not in self.last_values:
                    self.last_values[cache_key] = {}
                for key, val in result.items():
                    if val != 0 and key != 'ltt':
                        self.last_values[cache_key][key] = val

        return result
