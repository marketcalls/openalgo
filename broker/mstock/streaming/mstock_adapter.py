import threading
import json
import logging
import time
import os
import asyncio
from typing import Dict, Any, Optional, List

from broker.mstock.api.data import BrokerData
from broker.mstock.api.mstockwebsocket import MstockWebSocket
from database.auth_db import get_auth_token
from database.token_db import get_token

import sys

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .mstock_mapping import MstockExchangeMapper, MstockCapabilityRegistry


class MstockWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """mstock-specific implementation of the WebSocket adapter"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("mstock_websocket")
        self.ws_client = None  # WebSocket client
        self.data_client = None  # REST API client
        self.user_id = None
        self.broker_name = "mstock"
        self.running = False
        self.lock = threading.Lock()
        self.stream_thread = None  # Thread for streaming connection
        self.auth_token = None
        self.event_loop = None  # Event loop for async operations

    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize mstock adapter with REST API client

        Args:
            broker_name: Name of the broker (always 'mstock' in this case)
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
            auth_token = get_auth_token(user_id)

            if not auth_token:
                self.logger.error(f"No authentication token found for user {user_id}")
                raise ValueError(f"No authentication token found for user {user_id}")
        else:
            # Use provided tokens
            auth_token = auth_data.get('auth_token')

            if not auth_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")

        self.auth_token = auth_token

        # Create BrokerData instance (REST API client)
        self.data_client = BrokerData(auth_token=auth_token)

        # Create MstockWebSocket instance (WebSocket client)
        self.ws_client = MstockWebSocket(auth_token=auth_token)

        self.running = True
        self.logger.info(f"mstock adapter initialized for user {user_id}")

    def connect(self) -> None:
        """
        Establish persistent connection to mstock WebSocket (like Angel)
        """
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        self.logger.info("Connecting to mstock WebSocket in streaming mode...")
        self.running = True

        # Start streaming connection in background thread
        self.stream_thread = threading.Thread(target=self._run_stream, daemon=True)
        self.stream_thread.start()

        # Wait for connection to establish and event loop to be ready
        timeout = 5
        for _ in range(timeout * 2):  # Check every 0.5s
            if self.event_loop:
                break
            time.sleep(0.5)

        if not self.event_loop:
            self.logger.error("Failed to establish event loop")
            return

        self.connected = True
        self.logger.info("mstock WebSocket adapter connected")

    def _run_stream(self) -> None:
        """Run the streaming WebSocket connection in background thread"""
        try:
            # Create new event loop for this thread
            self.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.event_loop)

            # Connect to WebSocket in streaming mode with callback
            self.event_loop.run_until_complete(
                self.ws_client.connect_stream_async(self._on_data)
            )
        except Exception as e:
            self.logger.error(f"Error in streaming mode: {str(e)}", exc_info=True)
        finally:
            if self.event_loop:
                self.event_loop.close()
            self.event_loop = None
            self.connected = False
            self.running = False

    def _on_data(self, quote_data: Dict) -> None:
        """
        Callback function called when data is received from WebSocket

        Args:
            quote_data: Parsed quote data from mstock WebSocket
        """
        try:
            # Extract token to find matching subscription
            token = quote_data.get('token')
            if not token:
                self.logger.warning("Received data without token")
                return

            # Log received token for debugging
            self.logger.debug(f"Received data for token: {token}")

            # Find the subscription that matches this token
            subscription = None
            with self.lock:
                # Log all subscribed tokens for debugging
                subscribed_tokens = {cid: sub['token'] for cid, sub in self.subscriptions.items()}
                self.logger.debug(f"Looking for token '{token}' in subscriptions: {subscribed_tokens}")

                for correlation_id, sub in self.subscriptions.items():
                    if sub['token'] == token:
                        subscription = sub
                        break

            if not subscription:
                self.logger.warning(f"Received data for unsubscribed token: '{token}' (subscriptions: {list(self.subscriptions.keys())})")
                return

            # Create topic for ZeroMQ
            symbol = subscription['symbol']
            exchange = subscription['exchange']
            mode = subscription['mode']
            mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}[mode]
            topic = f"{exchange}_{symbol}_{mode_str}"

            # Normalize the data
            market_data = self._normalize_market_data(quote_data, mode)

            # Add metadata
            market_data.update({
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'timestamp': int(time.time() * 1000)
            })

            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)
            self.logger.debug(f"Published data for {symbol} on {exchange} mode {mode}")

        except Exception as e:
            self.logger.error(f"Error processing data: {str(e)}", exc_info=True)

    def disconnect(self) -> None:
        """Disconnect from mstock WebSocket"""
        self.running = False

        if self.ws_client:
            self.ws_client.disconnect_stream()

        self.logger.info("mstock WebSocket adapter disconnected")

        # Clean up ZeroMQ resources
        self.cleanup_zmq()

    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with mstock-specific implementation

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Snap Quote (Depth)
            depth_level: Market depth level (only 5 supported by mstock)

        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate the mode
        if mode not in [1, 2, 3]:
            return self._create_error_response("INVALID_MODE",
                                              f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)")

        # If depth mode, check if supported depth level
        if mode == 3 and depth_level not in [5]:
            return self._create_error_response("INVALID_DEPTH",
                                              f"Invalid depth level {depth_level}. mstock only supports 5 levels")

        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND",
                                              f"Symbol {symbol} not found for exchange {exchange}")

        token = token_info['token']
        brexchange = token_info['brexchange']

        # Get exchange type for mstock
        exchange_type = MstockExchangeMapper.get_exchange_type(brexchange)

        # Generate unique correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"

        # Store subscription
        with self.lock:
            self.subscriptions[correlation_id] = {
                'symbol': symbol,
                'exchange': exchange,
                'brexchange': brexchange,
                'token': token,
                'mode': mode,
                'depth_level': depth_level,
                'exchange_type': exchange_type
            }

        # Subscribe on the persistent WebSocket connection
        if self.ws_client and self.running and self.event_loop:
            # Schedule coroutine in the background event loop thread
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.ws_client.subscribe_stream_async(correlation_id, token, exchange_type, mode),
                    self.event_loop
                )
                # Wait for result with timeout
                result = future.result(timeout=5.0)

                if result:
                    self.logger.info(f"Subscribed to {symbol} on {exchange} mode {mode}")
                else:
                    self.logger.warning(f"Failed to subscribe to {symbol} on {exchange}")

            except Exception as e:
                self.logger.error(f"Error subscribing: {str(e)}")

        return {
            'status': 'success',
            'message': f'Subscribed to {symbol} on {exchange} in mode {mode}',
            'correlation_id': correlation_id
        }


    def _normalize_market_data(self, quote_data: Dict, mode: int) -> Dict[str, Any]:
        """
        Normalize mstock data format to OpenAlgo common format

        Args:
            quote_data: Raw quote data from mstock binary packet
            mode: Subscription mode

        Returns:
            Dict: Normalized market data
        """
        try:
            # Base data structure - always include LTP
            normalized = {
                'ltp': float(quote_data.get('ltp', 0))
            }

            # Add mode-specific data
            if mode >= 2:  # Quote mode - add OHLC and volume
                normalized.update({
                    'open': float(quote_data.get('open', 0)),
                    'high': float(quote_data.get('high', 0)),
                    'low': float(quote_data.get('low', 0)),
                    'close': float(quote_data.get('close', 0)),
                    'prev_close': float(quote_data.get('close', 0)),
                    'volume': int(quote_data.get('volume', 0)),
                    'oi': int(quote_data.get('oi', 0)),
                    'last_traded_qty': int(quote_data.get('last_traded_qty', 0))
                })

            if mode == 3:  # Depth mode - add market depth
                # Format bids and asks
                bids = quote_data.get('bids', [])[:5]  # Top 5 bids
                asks = quote_data.get('asks', [])[:5]  # Top 5 asks

                normalized['depth'] = {
                    'buy': bids,
                    'sell': asks
                }

                normalized.update({
                    'total_buy_qty': int(quote_data.get('total_buy_qty', 0)),
                    'total_sell_qty': int(quote_data.get('total_sell_qty', 0)),
                    'upper_circuit': float(quote_data.get('upper_circuit', 0)),
                    'lower_circuit': float(quote_data.get('lower_circuit', 0))
                })

            return normalized

        except Exception as e:
            self.logger.error(f"Error normalizing market data: {str(e)}")
            return {'ltp': 0}  # Return minimal valid data

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
        correlation_id = f"{symbol}_{exchange}_{mode}"

        with self.lock:
            if correlation_id in self.subscriptions:
                # Unsubscribe from WebSocket
                if self.ws_client and self.running and self.event_loop:
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.ws_client.unsubscribe_stream_async(correlation_id),
                            self.event_loop
                        )
                        future.result(timeout=5.0)
                    except Exception as e:
                        self.logger.error(f"Error unsubscribing: {str(e)}")

                del self.subscriptions[correlation_id]
                self.logger.info(f"Unsubscribed from {symbol} on {exchange} mode {mode}")
                return {
                    'status': 'success',
                    'message': f'Unsubscribed from {symbol} on {exchange}'
                }
            else:
                return self._create_error_response("NOT_SUBSCRIBED",
                                                  f"{symbol} on {exchange} is not subscribed")

    def _create_error_response(self, error_code: str, message: str) -> Dict[str, Any]:
        """Create standardized error response"""
        return {
            'status': 'error',
            'error_code': error_code,
            'message': message
        }

    def get_subscriptions(self) -> List[Dict[str, Any]]:
        """
        Get list of active subscriptions

        Returns:
            List of subscription details
        """
        with self.lock:
            return [
                {
                    'symbol': sub['symbol'],
                    'exchange': sub['exchange'],
                    'mode': sub['mode'],
                    'depth_level': sub.get('depth_level', 5)
                }
                for sub in self.subscriptions.values()
            ]
