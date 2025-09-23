"""
Dhan WebSocket Adapter for OpenAlgo
Manages both 5-level and 20-level depth connections
"""
import threading
import json
import logging
import time
import asyncio
import platform
from typing import Dict, Any, Optional, List
from collections import defaultdict
from datetime import datetime, time as dt_time

from database.auth_db import get_auth_token
from database.token_db import get_token

import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .dhan_mapping import DhanExchangeMapper, DhanCapabilityRegistry
from .dhan_websocket import DhanWebSocket


class DhanWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Dhan-specific implementation of the WebSocket adapter"""
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("dhan_websocket")
        self.user_id = None
        self.broker_name = "dhan"
        
        # Separate WebSocket clients for different depth levels
        self.ws_client_5depth = None
        self.ws_client_20depth = None
        
        # Track subscriptions by depth level
        self.subscriptions_5depth = {}
        self.subscriptions_20depth = {}
        
        # Track 20-depth data accumulation
        self.depth_20_accumulator = {}
        
        # Fallback tracking for 20-depth subscriptions
        self.depth_20_fallbacks = {}  # Track which subscriptions have fallen back to 5-depth
        self.depth_20_timeouts = {}   # Track timeout for 20-depth subscriptions
        self.depth_20_data_received = {}  # Track when 20-depth data was last received
        
        # Fallback monitoring thread (will be started in initialize)
        self.fallback_monitor_thread = None
        
        # Connection management
        self.running = False
        self.lock = threading.Lock()
        self.reconnect_delay = 5
        self.max_reconnect_delay = 60
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
    
    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Dhan WebSocket API
        
        Args:
            broker_name: Name of the broker (always 'dhan' in this case)
            user_id: Client ID/user ID
            auth_data: If provided, use these credentials instead of fetching from DB
        """
        self.user_id = user_id
        self.broker_name = broker_name
        
        # For Dhan, use credentials from .env file
        import os
        from dotenv import load_dotenv
        load_dotenv()
        
        # Get Dhan credentials from environment
        client_id = os.getenv('BROKER_API_KEY')  # This is the Dhan client ID
        auth_token = os.getenv('BROKER_API_SECRET')  # This is the Dhan access token
        
        if not client_id or not auth_token:
            # Fall back to database if env vars not set
            if not auth_data:
                auth_token = get_auth_token(user_id)
                client_id = user_id
                if not auth_token:
                    self.logger.error(f"No authentication token found for user {user_id}")
                    raise ValueError(f"No authentication token found for user {user_id}")
            else:
                auth_token = auth_data.get('auth_token')
                client_id = auth_data.get('client_id', user_id)
                if not auth_token:
                    self.logger.error("Missing required authentication data")
                    raise ValueError("Missing required authentication data")
        
        self.logger.debug(f"Using Dhan credentials - Client ID: {client_id}")
        
        # Store the client_id for later use
        self.client_id = client_id
        
        # Initialize 5-depth WebSocket client
        self.ws_client_5depth = DhanWebSocket(
            client_id=client_id,  # Use the actual Dhan client ID
            access_token=auth_token,
            is_20_depth=False
        )
        
        # Initialize 20-depth WebSocket client
        self.ws_client_20depth = DhanWebSocket(
            client_id=client_id,  # Use the actual Dhan client ID
            access_token=auth_token,
            is_20_depth=True
        )
        
        # Set callbacks for 5-depth client
        self.ws_client_5depth.on_open = self._on_open_5depth
        self.ws_client_5depth.on_data = self._on_data_5depth
        self.ws_client_5depth.on_error = self._on_error_5depth
        self.ws_client_5depth.on_close = self._on_close_5depth
        
        # Set callbacks for 20-depth client
        self.ws_client_20depth.on_open = self._on_open_20depth
        self.ws_client_20depth.on_data = self._on_data_20depth
        self.ws_client_20depth.on_error = self._on_error_20depth
        self.ws_client_20depth.on_close = self._on_close_20depth
        
        self.running = True
        
        # Start fallback monitoring thread - temporarily disabled for debugging
        # self.start_fallback_monitor()
    
    def connect(self) -> None:
        """Establish connections to Dhan WebSocket endpoints"""
        if not self.ws_client_5depth or not self.ws_client_20depth:
            self.logger.error("WebSocket clients not initialized. Call initialize() first.")
            return
        
        # Connect to 5-depth endpoint
        self.logger.debug("Connecting to Dhan 5-depth WebSocket...")
        self.ws_client_5depth.connect()
        
        # Connect to 20-depth endpoint
        self.logger.debug("Connecting to Dhan 20-depth WebSocket...")
        self.ws_client_20depth.connect()
    
    def disconnect(self) -> None:
        """Disconnect from Dhan WebSocket endpoints"""
        self.running = False
        
        if self.ws_client_5depth:
            self.ws_client_5depth.disconnect()
        
        if self.ws_client_20depth:
            self.ws_client_20depth.disconnect()
        
        # Clean up ZeroMQ resources
        self.cleanup_zmq()
        
        # Stop fallback monitor
        self.stop_fallback_monitor()
    
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with Dhan-specific implementation
        
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Depth
            depth_level: Market depth level (5 or 20)
            
        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate mode
        if mode not in [1, 2, 3]:
            return self._create_error_response("INVALID_MODE", 
                                              f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)")
        
        # Map symbol to token
        self.logger.debug(f"Looking up token for {symbol}.{exchange}")
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            self.logger.error(f"Token lookup failed for {symbol}.{exchange}")
            return self._create_error_response("SYMBOL_NOT_FOUND", 
                                              f"Symbol {symbol} not found for exchange {exchange}")
        
        token = token_info['token']
        brexchange = token_info['brexchange']
        self.logger.debug(f"Token found: {token}, brexchange: {brexchange}")
        
        # Get Dhan exchange code
        dhan_exchange = DhanExchangeMapper.get_dhan_exchange(exchange)
        self.logger.debug(f"Dhan exchange mapping: {exchange} -> {dhan_exchange}")
        if not dhan_exchange:
            return self._create_error_response("EXCHANGE_NOT_SUPPORTED", 
                                              f"Exchange {exchange} not supported")
        
        # Check depth level support - use 5-level for all segments
        is_fallback = False
        actual_depth = depth_level
        
        if mode == 3:  # Depth mode
            # Force 5-level depth for all exchanges (keeping 20-level code intact but not using it)
            if depth_level == 20:
                actual_depth = 5
                is_fallback = True
                self.logger.debug(f"Using 5-level depth for {exchange} instead of requested 20-level depth")
            elif not DhanCapabilityRegistry.is_depth_level_supported(exchange, depth_level):
                actual_depth = DhanCapabilityRegistry.get_fallback_depth_level(exchange, depth_level)
                is_fallback = True
                self.logger.debug(
                    f"Depth level {depth_level} not supported for {exchange}, "
                    f"using {actual_depth} instead"
                )
        
        # Prepare instrument info
        instrument = {
            'ExchangeSegment': dhan_exchange,
            'SecurityId': token
        }
        
        # Map mode to Dhan subscription type
        dhan_mode_map = {
            1: 'TICKER',  # LTP
            2: 'QUOTE',   # Quote
            3: 'FULL' if actual_depth == 5 else '20_DEPTH'  # Depth
        }
        dhan_mode = dhan_mode_map.get(mode)
        
        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}_{actual_depth}"
        
        self.logger.info(f"Subscribing to {symbol}.{exchange} in mode {mode} (requested depth {depth_level} -> actual depth {actual_depth}), token: {token}, dhan_exchange: {dhan_exchange}")
        #self.logger.info(f"Will use {'20-depth' if actual_depth == 20 and mode == 3 else '5-depth'} connection")
        
        # Subscribe based on depth level
        if actual_depth == 20 and mode == 3:
            # Use 20-depth connection
            with self.lock:
                # Check subscription limit
                if len(self.subscriptions_20depth) >= DhanCapabilityRegistry.MAX_SUBSCRIPTIONS_20_DEPTH:
                    return self._create_error_response("SUBSCRIPTION_LIMIT", 
                                                      f"Maximum {DhanCapabilityRegistry.MAX_SUBSCRIPTIONS_20_DEPTH} subscriptions allowed for 20-depth")
                
                self.subscriptions_20depth[correlation_id] = {
                    'symbol': symbol,
                    'exchange': exchange,
                    'dhan_exchange': dhan_exchange,
                    'token': token,
                    'mode': mode,
                    'depth_level': actual_depth,
                    'instrument': instrument
                }
                
                # Set timeout for 20-depth fallback (30 seconds)
                self.depth_20_timeouts[correlation_id] = time.time() + 30
                # Reset data received timestamp
                self.depth_20_data_received[correlation_id] = time.time()
            
            # Subscribe if connected
            if self.ws_client_20depth and self.ws_client_20depth.connected:
                try:
                    self.ws_client_20depth.subscribe([instrument], '20_DEPTH')
                except Exception as e:
                    self.logger.error(f"Error subscribing to 20-depth for {symbol}.{exchange}: {e}")
                    return self._create_error_response("SUBSCRIPTION_ERROR", str(e))
        else:
            # Use 5-depth connection
            with self.lock:
                # Check subscription limit
                if len(self.subscriptions_5depth) >= DhanCapabilityRegistry.MAX_SUBSCRIPTIONS_5_DEPTH:
                    return self._create_error_response("SUBSCRIPTION_LIMIT", 
                                                      f"Maximum {DhanCapabilityRegistry.MAX_SUBSCRIPTIONS_5_DEPTH} subscriptions allowed")
                
                self.subscriptions_5depth[correlation_id] = {
                    'symbol': symbol,
                    'exchange': exchange,
                    'dhan_exchange': dhan_exchange,
                    'token': token,
                    'mode': mode,
                    'depth_level': actual_depth,
                    'instrument': instrument
                }
            
            # Subscribe if connected
            if self.ws_client_5depth and self.ws_client_5depth.connected:
                try:
                    self.ws_client_5depth.subscribe([instrument], dhan_mode)
                except Exception as e:
                    self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                    return self._create_error_response("SUBSCRIPTION_ERROR", str(e))
        
        # Store in base class subscriptions for reconnection
        with self.lock:
            self.subscriptions[correlation_id] = {
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'depth_level': actual_depth,
                'is_20_depth': (actual_depth == 20 and mode == 3)
            }
        
        return self._create_success_response(
            'Subscription requested' if not is_fallback else f"Using depth level {actual_depth} instead of requested {depth_level}",
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            requested_depth=depth_level,
            actual_depth=actual_depth,
            is_fallback=is_fallback
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
            return self._create_error_response("SYMBOL_NOT_FOUND", 
                                              f"Symbol {symbol} not found for exchange {exchange}")
        
        token = token_info['token']
        
        # Get Dhan exchange code
        dhan_exchange = DhanExchangeMapper.get_dhan_exchange(exchange)
        if not dhan_exchange:
            return self._create_error_response("EXCHANGE_NOT_SUPPORTED", 
                                              f"Exchange {exchange} not supported")
        
        # Prepare instrument info
        instrument = {
            'ExchangeSegment': dhan_exchange,
            'SecurityId': token
        }
        
        # Remove from all possible subscriptions
        removed = False
        with self.lock:
            # Check 5-depth subscriptions
            for depth in [5, 20]:
                correlation_id = f"{symbol}_{exchange}_{mode}_{depth}"
                
                if correlation_id in self.subscriptions_5depth:
                    del self.subscriptions_5depth[correlation_id]
                    if self.ws_client_5depth:
                        self.ws_client_5depth.unsubscribe([instrument])
                    removed = True
                
                if correlation_id in self.subscriptions_20depth:
                    del self.subscriptions_20depth[correlation_id]
                    # Clean up fallback tracking
                    if correlation_id in self.depth_20_timeouts:
                        del self.depth_20_timeouts[correlation_id]
                    if correlation_id in self.depth_20_data_received:
                        del self.depth_20_data_received[correlation_id]
                    if correlation_id in self.depth_20_fallbacks:
                        del self.depth_20_fallbacks[correlation_id]
                    if self.ws_client_20depth:
                        self.ws_client_20depth.unsubscribe([instrument])
                    removed = True
                
                if correlation_id in self.subscriptions:
                    del self.subscriptions[correlation_id]
        
        if removed:
            self.logger.info(f"Unubscribing to {symbol}.{exchange} in mode {mode}")
            return self._create_success_response(
                f"Unsubscribed from {symbol}.{exchange}",
                symbol=symbol,
                exchange=exchange,
                mode=mode
            )
        else:
            return self._create_error_response("NOT_SUBSCRIBED",
                                              f"Not subscribed to {symbol}.{exchange}")

    def unsubscribe_all(self) -> Dict[str, Any]:
        """
        Unsubscribe from all subscriptions and disconnect from WebSocket

        Returns:
            Dict: Response with status
        """
        unsubscribed_count = 0

        with self.lock:
            # Count total subscriptions before clearing
            unsubscribed_count = len(self.subscriptions_5depth) + len(self.subscriptions_20depth)

            # Clear all subscriptions
            self.subscriptions_5depth.clear()
            self.subscriptions_20depth.clear()
            self.subscriptions.clear()

            # Clear fallback tracking
            self.depth_20_timeouts.clear()
            self.depth_20_data_received.clear()
            self.depth_20_fallbacks.clear()
            self.depth_20_accumulator.clear()

        # Disconnect from WebSocket servers
        if self.ws_client_5depth:
            try:
                self.ws_client_5depth.disconnect()
                self.logger.debug("Disconnected from Dhan 5-depth WebSocket")
            except Exception as e:
                self.logger.error(f"Error disconnecting 5-depth WebSocket: {e}")

        if self.ws_client_20depth:
            try:
                self.ws_client_20depth.disconnect()
                self.logger.debug("Disconnected from Dhan 20-depth WebSocket")
            except Exception as e:
                self.logger.error(f"Error disconnecting 20-depth WebSocket: {e}")

        # Clean up ZeroMQ resources
        self.cleanup_zmq()
        self.logger.info(f"Dhan adapter disconnected and cleaned up after unsubscribing {unsubscribed_count} instruments")

        return self._create_success_response(
            f"Unsubscribed from {unsubscribed_count} instruments and disconnected",
            unsubscribed_count=unsubscribed_count
        )

    # Callbacks for 5-depth connection
    def _on_open_5depth(self, ws):
        """Handle 5-depth connection open"""
        self.logger.debug("Connected to Dhan 5-depth WebSocket")
        self.connected = True
        
        # Resubscribe to existing subscriptions
        with self.lock:
            instruments_by_mode = defaultdict(list)
            
            for sub in self.subscriptions_5depth.values():
                mode = sub['mode']
                dhan_mode = {1: 'TICKER', 2: 'QUOTE', 3: 'FULL'}[mode]
                instruments_by_mode[dhan_mode].append(sub['instrument'])
            
            # Subscribe in batches by mode
            for dhan_mode, instruments in instruments_by_mode.items():
                try:
                    self.ws_client_5depth.subscribe(instruments, dhan_mode)
                    self.logger.debug(f"Resubscribed to {len(instruments)} instruments in {dhan_mode} mode")
                except Exception as e:
                    self.logger.error(f"Error resubscribing: {e}")
    
    def _on_error_5depth(self, ws, error):
        """Handle 5-depth connection error"""
        self.logger.error(f"Dhan 5-depth WebSocket error: {error}")
    
    def _on_close_5depth(self, ws):
        """Handle 5-depth connection close"""
        self.logger.debug("Dhan 5-depth WebSocket connection closed")
        self.connected = False
    
    def _on_data_5depth(self, ws, data):
        """Handle data from 5-depth connection"""
        try:
            # Find matching subscription by token and exchange segment
            security_id = data.get('security_id')
            exchange_segment = data.get('exchange_segment')
            data_type = data.get('type')
            
            # Find the subscription that matches this token
            # First try exact match (token + exchange segment)
            subscription = None
            with self.lock:
                for sub in self.subscriptions_5depth.values():
                    expected_segment = DhanExchangeMapper.get_segment_from_exchange(sub['exchange'])
                    
                    if (sub['token'] == security_id and expected_segment == exchange_segment):
                        subscription = sub
                        self.logger.debug(f"Exact match found: {sub['symbol']}.{sub['exchange']}")
                        break
                
                # If no exact match, try token-only match (for flexibility)
                if not subscription:
                    for sub in self.subscriptions_5depth.values():
                        if sub['token'] == security_id:
                            subscription = sub
                            expected_segment = DhanExchangeMapper.get_segment_from_exchange(sub['exchange'])
                            self.logger.debug(f"Token-only match found: {sub['symbol']}.{sub['exchange']} (expected segment {expected_segment}, got {exchange_segment})")
                            break
            
            if not subscription:
                #self.logger.warning(f"Received data for unsubscribed token: {security_id}, segment: {exchange_segment}")
                return
            
            # Get symbol and exchange from subscription
            symbol = subscription['symbol']
            exchange = subscription['exchange']
            
            # Normalize and publish data
            market_data = self._normalize_5depth_data(data, symbol, exchange)
            if market_data:
                # Determine topic based on data type
                mode_map = {
                    'ticker': 'LTP',
                    'quote': 'QUOTE',
                    'full': 'DEPTH',
                    'oi': 'OI',
                    'prev_close': 'PREV_CLOSE'
                }
                
                mode_str = mode_map.get(data_type, 'UNKNOWN')
                topic = f"{exchange}_{symbol}_{mode_str}"
                
                self.publish_market_data(topic, market_data)
                
        except Exception as e:
            self.logger.error(f"Error processing 5-depth data: {e}", exc_info=True)
    
    # Callbacks for 20-depth connection
    def _on_open_20depth(self, ws):
        """Handle 20-depth connection open"""
        self.logger.debug("Connected to Dhan 20-depth WebSocket")
        
        # Resubscribe to existing subscriptions
        with self.lock:
            instruments = [sub['instrument'] for sub in self.subscriptions_20depth.values()]
            
            if instruments:
                try:
                    self.ws_client_20depth.subscribe(instruments, '20_DEPTH')
                    self.logger.debug(f"Resubscribed to {len(instruments)} instruments for 20-depth")
                except Exception as e:
                    self.logger.error(f"Error resubscribing to 20-depth: {e}")
    
    def _on_error_20depth(self, ws, error):
        """Handle 20-depth connection error"""
        self.logger.error(f"Dhan 20-depth WebSocket error: {error}")
    
    def _on_close_20depth(self, ws):
        """Handle 20-depth connection close"""
        self.logger.debug("Dhan 20-depth WebSocket connection closed")
    
    def _on_data_20depth(self, ws, data):
        """Handle data from 20-depth connection"""
        try:
            # 20-depth data comes in two parts: bid and ask
            # We need to accumulate both before publishing
            security_id = data.get('security_id')
            side = data.get('side')
            
            if data.get('type') != 'depth_20':
                return
            
            # Store in accumulator
            if security_id not in self.depth_20_accumulator:
                self.depth_20_accumulator[security_id] = {}
            
            self.depth_20_accumulator[security_id][side] = data.get('levels', [])
            
            # Check if we have both sides
            if 'buy' in self.depth_20_accumulator[security_id] and 'sell' in self.depth_20_accumulator[security_id]:
                # Find matching subscription by token and exchange segment
                exchange_segment = data.get('exchange_segment')
                
                # Find the subscription that matches this token and exchange segment
                subscription = None
                with self.lock:
                    for sub in self.subscriptions_20depth.values():
                        if (sub['token'] == security_id and 
                            DhanExchangeMapper.get_segment_from_exchange(sub['exchange']) == exchange_segment):
                            subscription = sub
                            break
                
                if not subscription:
                    self.logger.warning(f"Received 20-depth data for unsubscribed token: {security_id}, segment: {exchange_segment}")
                    # Clear accumulator
                    del self.depth_20_accumulator[security_id]
                    return
                
                # Get symbol and exchange from subscription
                symbol = subscription['symbol']
                exchange = subscription['exchange']
                
                # Create combined depth data
                market_data = {
                    'symbol': symbol,
                    'exchange': exchange,
                    'mode': 3,  # Depth mode
                    'timestamp': int(time.time() * 1000),
                    'depth': {
                        'buy': self.depth_20_accumulator[security_id]['buy'],
                        'sell': self.depth_20_accumulator[security_id]['sell']
                    },
                    'depth_level': 20
                }
                
                # Publish with standard DEPTH topic (mode 3)
                topic = f"{exchange}_{symbol}_DEPTH"
                self.publish_market_data(topic, market_data)
                
                # Clear accumulator
                del self.depth_20_accumulator[security_id]
                
                # Update data received timestamp for fallback monitoring
                correlation_id = f"{symbol}_{exchange}_3_20"
                if correlation_id in self.depth_20_timeouts:
                    self.depth_20_data_received[correlation_id] = time.time()
                
        except Exception as e:
            self.logger.error(f"Error processing 20-depth data: {e}", exc_info=True)
    
    def _normalize_5depth_data(self, data: Dict[str, Any], symbol: str, exchange: str) -> Dict[str, Any]:
        """Normalize 5-depth data to common format"""
        data_type = data.get('type')
        
        base_data = {
            'symbol': symbol,
            'exchange': exchange,
            'timestamp': int(time.time() * 1000)
        }
        
        if data_type == 'ticker':
            base_data.update({
                'mode': 1,
                'ltp': data.get('ltp', 0),
                'ltt': data.get('ltt', 0)
            })
        
        elif data_type == 'quote':
            base_data.update({
                'mode': 2,
                'ltp': data.get('ltp', 0),
                'ltt': data.get('ltt', 0),
                'volume': data.get('volume', 0),
                'open': data.get('open', 0),
                'high': data.get('high', 0),
                'low': data.get('low', 0),
                'close': data.get('close', 0),
                'last_quantity': data.get('ltq', 0),
                'average_price': data.get('atp', 0),
                'total_buy_quantity': data.get('total_buy_quantity', 0),
                'total_sell_quantity': data.get('total_sell_quantity', 0)
            })
        
        elif data_type == 'full':
            base_data.update({
                'mode': 3,
                'ltp': data.get('ltp', 0),
                'ltt': data.get('ltt', 0),
                'volume': data.get('volume', 0),
                'open': data.get('open', 0),
                'high': data.get('high', 0),
                'low': data.get('low', 0),
                'close': data.get('close', 0),
                'oi': data.get('oi', 0),
                'oi_high': data.get('oi_high', 0),
                'oi_low': data.get('oi_low', 0),
                'depth': data.get('depth', {'buy': [], 'sell': []}),
                'depth_level': 5
            })
        
        elif data_type == 'oi':
            base_data.update({
                'oi': data.get('oi', 0)
            })
        
        elif data_type == 'prev_close':
            base_data.update({
                'prev_close': data.get('prev_close', 0),
                'prev_oi': data.get('prev_oi', 0)
            })
        
        return base_data
    
    def start_fallback_monitor(self):
        """Start the fallback monitoring thread"""
        # Only start if running is True and thread is not already active
        if getattr(self, 'running', False) and (self.fallback_monitor_thread is None or not self.fallback_monitor_thread.is_alive()):
            self.fallback_monitor_thread = threading.Thread(target=self._fallback_monitor_loop, daemon=True)
            self.fallback_monitor_thread.start()
            self.logger.debug("Started fallback monitor thread")
    
    def stop_fallback_monitor(self):
        """Stop the fallback monitoring thread"""
        self.running = False
        if self.fallback_monitor_thread and self.fallback_monitor_thread.is_alive():
            self.fallback_monitor_thread.join(timeout=2)
            self.logger.debug("Stopped fallback monitor thread")
    
    def _fallback_monitor_loop(self):
        """Monitor 20-depth subscriptions and fallback to 5-depth if no data received"""
        while getattr(self, 'running', False):
            try:
                current_time = time.time()
                fallback_candidates = []
                
                with self.lock:
                    # Check for timed-out 20-depth subscriptions
                    for correlation_id, timeout_time in list(self.depth_20_timeouts.items()):
                        if current_time > timeout_time and correlation_id not in self.depth_20_fallbacks:
                            # Check if we've received any data since the subscription
                            last_data_time = self.depth_20_data_received.get(correlation_id, 0)
                            time_since_data = current_time - last_data_time
                            
                            if time_since_data > 30:  # 30 seconds without data
                                fallback_candidates.append(correlation_id)
                
                # Process fallbacks outside the lock to avoid deadlocks
                for correlation_id in fallback_candidates:
                    self._perform_fallback_to_5depth(correlation_id)
                
                # Sleep for 5 seconds before next check
                time.sleep(5)
                
            except Exception as e:
                self.logger.error(f"Error in fallback monitor loop: {e}", exc_info=True)
                time.sleep(5)
    
    def _perform_fallback_to_5depth(self, correlation_id):
        """Perform automatic fallback from 20-depth to 5-depth"""
        try:
            with self.lock:
                # Check if this subscription still exists and hasn't already fallen back
                if correlation_id not in self.subscriptions_20depth or correlation_id in self.depth_20_fallbacks:
                    return
                
                subscription = self.subscriptions_20depth[correlation_id]
                symbol = subscription['symbol']
                exchange = subscription['exchange']
                
                self.logger.warning(f"20-depth timeout for {symbol}.{exchange}, falling back to 5-depth")
                
                # Mark as fallen back
                self.depth_20_fallbacks[correlation_id] = time.time()
                
                # Remove from 20-depth subscriptions and timeouts
                del self.subscriptions_20depth[correlation_id]
                if correlation_id in self.depth_20_timeouts:
                    del self.depth_20_timeouts[correlation_id]
                if correlation_id in self.depth_20_data_received:
                    del self.depth_20_data_received[correlation_id]
                
                # Create new 5-depth subscription
                correlation_id_5depth = f"{symbol}_{exchange}_3_5"
                
                self.subscriptions_5depth[correlation_id_5depth] = {
                    'symbol': symbol,
                    'exchange': exchange,
                    'dhan_exchange': subscription['dhan_exchange'],
                    'token': subscription['token'],
                    'mode': subscription['mode'],
                    'depth_level': 5,  # Fallback to 5-depth
                    'instrument': subscription['instrument']
                }
                
                # Update base subscriptions
                if correlation_id in self.subscriptions:
                    self.subscriptions[correlation_id_5depth] = self.subscriptions[correlation_id].copy()
                    self.subscriptions[correlation_id_5depth]['depth_level'] = 5
                    self.subscriptions[correlation_id_5depth]['is_20_depth'] = False
                    del self.subscriptions[correlation_id]
            
            # Subscribe to 5-depth if connected
            if self.ws_client_5depth and self.ws_client_5depth.connected:
                try:
                    self.ws_client_5depth.subscribe([subscription['instrument']], 'FULL')
                    self.logger.debug(f"Successfully subscribed to 5-depth for {symbol}.{exchange}")
                except Exception as e:
                    self.logger.error(f"Error subscribing to 5-depth for fallback {symbol}.{exchange}: {e}")
            
        except Exception as e:
            self.logger.error(f"Error performing fallback for {correlation_id}: {e}", exc_info=True)