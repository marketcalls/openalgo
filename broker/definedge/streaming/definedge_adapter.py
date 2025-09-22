import threading
import json
import logging
import time
from typing import Dict, Any, Optional, List

from broker.definedge.streaming.definedge_websocket import DefinedGeWebSocket
from database.auth_db import get_auth_token, get_feed_token
from database.token_db import get_token

import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .definedge_mapping import DefinedgeExchangeMapper, DefinedgeCapabilityRegistry


class MarketDataCache:
    """Manages market data caching with thread safety for DefinEdge"""
    
    def __init__(self):
        self._cache = {}
        self._initialized_tokens = set()
        self._lock = threading.Lock()
        self.logger = logging.getLogger("market_cache")
    
    def get(self, token: str) -> Dict[str, Any]:
        """Get cached data for a token"""
        with self._lock:
            return self._cache.get(token, {}).copy()
    
    def update(self, token: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update cache with new data and return merged result"""
        with self._lock:
            cached_data = self._cache.get(token, {})
            merged_data = self._merge_data(cached_data, data, token)
            self._cache[token] = merged_data
            
            if token not in self._initialized_tokens:
                self._initialized_tokens.add(token)
                self._log_cache_initialization(token, data)
            
            return merged_data.copy()
    
    def clear(self, token: str = None) -> None:
        """Clear cache for specific token or all tokens"""
        with self._lock:
            if token:
                self._cache.pop(token, None)
                self._initialized_tokens.discard(token)
                self.logger.info(f"Cleared cache for token {token}")
            else:
                cache_size = len(self._cache)
                self._cache.clear()
                self._initialized_tokens.clear()
                self.logger.info(f"Cleared all cached market data ({cache_size} tokens)")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            return {
                'total_tokens': len(self._cache),
                'initialized_tokens': len(self._initialized_tokens),
                'tokens': list(self._cache.keys())
            }
    
    def _merge_data(self, cached: Dict, new: Dict, token: str) -> Dict:
        """Smart merge logic for market data - similar to Shoonya"""
        merged = cached.copy()
        
        # Update with new values
        for key, value in new.items():
            if self._should_preserve_cached_value(key, value, cached):
                continue
            merged[key] = value
        
        # Preserve cached values for missing fields (like Shoonya does)
        for key, value in cached.items():
            if key not in new:
                merged[key] = value
        
        return merged
    
    def _should_preserve_cached_value(self, key: str, new_value: Any, cached: Dict) -> bool:
        """Determine if cached value should be preserved - same logic as Shoonya"""
        # Preserve non-zero OHLC values when new value is zero (same as Shoonya line 119-121)
        # Using raw field names as they come from broker
        if key in ['o', 'h', 'l', 'c', 'ap'] and self._is_zero_value(new_value):
            cached_value = cached.get(key)
            return cached_value is not None and not self._is_zero_value(cached_value)
        return False
    
    def _is_zero_value(self, value: Any) -> bool:
        """Check if value represents zero - same as Shoonya line 130-132"""
        return value in [None, '', '0', 0, '0.0', 0.0]
    
    def _log_cache_initialization(self, token: str, data: Dict) -> None:
        """Log cache initialization details - same as Shoonya"""
        # Use raw field names like Shoonya
        basic_fields = ['lp', 'o', 'h', 'l', 'c', 'v', 'ap', 'pc', 'ltq', 'ltt', 'tbq', 'tsq']
        present_fields = sum(1 for field in basic_fields if field in data)
        completeness = present_fields / len(basic_fields)
        
        # Check specifically for OHLC snapshot
        has_ohlc = any(data.get(f) and not self._is_zero_value(data.get(f)) for f in ['o', 'h', 'l', 'c'])
        if has_ohlc:
            self.logger.info(f"📸 OHLC snapshot cached for {token}: o={data.get('o')}, h={data.get('h')}, l={data.get('l')}, c={data.get('c')}")
        
        self.logger.info(f"Initializing cache for token {token} - "
                        f"{present_fields}/{len(basic_fields)} fields present ({completeness:.1%})")


class DefinedgeWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """DefinEdge-specific implementation of the WebSocket adapter"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("definedge_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "definedge"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
        self.market_cache = MarketDataCache()  # Initialize market data cache
        self.token_to_symbol = {}  # Map tokens to symbols for cache management
        self.ws_subscription_refs = {}  # Reference counting for WebSocket subscriptions
    
    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with DefinEdge WebSocket API
        
        Args:
            broker_name: Name of the broker (always 'definedge' in this case)
            user_id: Client ID/user ID
            auth_data: If provided, use these credentials instead of fetching from DB
        
        Raises:
            ValueError: If required authentication tokens are not found
        """
        self.user_id = user_id
        self.broker_name = broker_name
        
        # Get tokens from database if not provided (following Angel pattern)
        if not auth_data:
            # Fetch authentication tokens from database
            auth_token = get_auth_token(user_id)
            feed_token = get_feed_token(user_id)  # This contains susertoken for DefinEdge
            
            if not auth_token:
                self.logger.error(f"No authentication tokens found for user {user_id}")
                raise ValueError(f"No authentication tokens found for user {user_id}")
                
            # Get the actual DefinEdge user_id from database
            from database.auth_db import get_user_id
            definedge_uid = get_user_id(user_id)  # This should return "1272808"
            
            self.logger.info(f"Tokens retrieved from DB for user {user_id}, DefinEdge uid: {definedge_uid}")
            
            # For DefinEdge, uid and actid are typically the same value
            # If uid is not found, use a default or raise error
            if not definedge_uid:
                self.logger.error(f"No DefinEdge user ID found in database for {user_id}")
                raise ValueError(f"No DefinEdge user ID found for {user_id}")
            
            # Create auth_data dict for WebSocket
            auth_data = {
                'auth_token': auth_token,
                'feed_token': feed_token,  # susertoken
                'uid': definedge_uid,      # "1272808"
                'actid': definedge_uid     # Same as uid for DefinEdge
            }
        
        # Create DefinedGeWebSocket instance with auth data
        self.ws_client = DefinedGeWebSocket(auth_data)
        
        # Set callbacks
        self.ws_client.on_connect = self._on_open
        self.ws_client.on_tick = self._on_data
        self.ws_client.on_depth = self._on_depth_data
        self.ws_client.on_error = self._on_error
        self.ws_client.on_disconnect = self._on_close
        
        self.running = True
        
    def connect(self) -> None:
        """Establish connection to DefinEdge WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return
            
        threading.Thread(target=self._connect_with_retry, daemon=True).start()
    
    def _connect_with_retry(self) -> None:
        """Connect to DefinEdge WebSocket with retry logic"""
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                # Check if we should still be running
                if not self.running:
                    self.logger.info("Adapter stopped - aborting connection attempt")
                    return
                    
                self.logger.info(f"Connecting to DefinEdge WebSocket (attempt {self.reconnect_attempts + 1})")
                if self.ws_client and self.ws_client.connect():
                    self.reconnect_attempts = 0  # Reset attempts on successful connection
                    self.connected = True
                    break
                else:
                    raise Exception("Connection failed")
                    
            except Exception as e:
                self.reconnect_attempts += 1
                
                # Check again if we should still be running before sleeping
                if not self.running:
                    self.logger.info("Adapter stopped during retry - aborting")
                    return
                    
                delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), self.max_reconnect_delay)
                self.logger.error(f"Connection failed: {e}. Retrying in {delay} seconds...")
                time.sleep(delay)
        
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Max reconnection attempts reached. Giving up.")
            self.running = False  # Stop the adapter
    
    def disconnect(self) -> None:
        """Disconnect from DefinEdge WebSocket with proper cleanup"""
        self.logger.info("Starting DefinEdge adapter disconnection...")
        
        # First set running flag to False to prevent any reconnection attempts
        self.running = False
        
        # Clear all subscriptions before disconnecting
        with self.lock:
            subscription_count = len(self.subscriptions)
            self.subscriptions.clear()
            self.logger.info(f"Cleared {subscription_count} active subscriptions")
        
        # Disconnect WebSocket client
        if hasattr(self, 'ws_client') and self.ws_client:
            self.logger.info("Disconnecting WebSocket client...")
            self.ws_client.disconnect()
            self.ws_client = None  # Clear reference
        
        # Clean up market data cache
        if hasattr(self, 'market_cache'):
            self.market_cache.clear()
            self.logger.info("Cleared market data cache")
        
        # Clean up token mappings
        if hasattr(self, 'token_to_symbol'):
            self.token_to_symbol.clear()
            self.logger.info("Cleared token mappings")
        
        # Reset connection state
        self.connected = False
        self.reconnect_attempts = 0
            
        # Clean up ZeroMQ resources - IMPORTANT for port release
        try:
            self.cleanup_zmq()
            self.logger.info("ZeroMQ resources cleaned up successfully")
        except Exception as e:
            self.logger.error(f"Error cleaning up ZeroMQ: {e}")
        
        self.logger.info("DefinEdge adapter disconnection completed")
    
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with DefinEdge-specific implementation

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Depth
            depth_level: Market depth level (5 for DefinEdge)

        Returns:
            Dict: Response with status and error message if applicable
        """
        self.logger.info(f"[SUBSCRIBE] Request for {symbol}.{exchange} mode={mode}")

        # Validate the mode
        if mode not in [1, 2, 3]:
            return self._create_error_response("INVALID_MODE",
                                              f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)")

        # If depth mode, check if supported depth level
        if mode == 3 and depth_level not in [5]:
            return self._create_error_response("INVALID_DEPTH",
                                              f"Invalid depth level {depth_level}. Must be 5")

        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND",
                                              f"Symbol {symbol} not found for exchange {exchange}")

        token = token_info['token']
        brexchange = token_info['brexchange']

        # Map exchange to DefinEdge format
        definedge_exchange = DefinedgeExchangeMapper.get_exchange_code(brexchange)

        # Check if the requested depth level is supported for this exchange
        is_fallback = False
        actual_depth = depth_level

        if mode == 3:  # Depth mode
            if not DefinedgeCapabilityRegistry.is_depth_level_supported(exchange, depth_level):
                # If requested depth is not supported, use the highest available
                actual_depth = DefinedgeCapabilityRegistry.get_fallback_depth_level(
                    exchange, depth_level
                )
                is_fallback = True

                self.logger.info(
                    f"Depth level {depth_level} not supported for {exchange}, "
                    f"using {actual_depth} instead"
                )

        # Create token list for DefinEdge API
        tokens = [(definedge_exchange, token)]

        # Generate a unique correlation_id for each subscription
        # This allows multiple clients to subscribe to the same symbol
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        correlation_id = f"{symbol}_{exchange}_{mode}_{unique_id}"
        if mode == 3:
            correlation_id = f"{symbol}_{exchange}_{mode}_{depth_level}_{unique_id}"

        # Check if we need to subscribe to WebSocket
        base_correlation_id = f"{symbol}_{exchange}_{mode}"
        if mode == 3:
            base_correlation_id = f"{symbol}_{exchange}_{mode}_{depth_level}"

        already_ws_subscribed = any(
            cid.startswith(base_correlation_id)
            for cid in self.subscriptions.keys()
        )

        if already_ws_subscribed:
            self.logger.info(f"[SUBSCRIBE] WebSocket already subscribed for {base_correlation_id}, adding client subscription {correlation_id}")
        else:
            self.logger.info(f"[SUBSCRIBE] New WebSocket subscription needed for {correlation_id}")

        # Store subscription for reconnection
        with self.lock:
            self.subscriptions[correlation_id] = {
                'symbol': symbol,
                'exchange': exchange,
                'brexchange': brexchange,
                'definedge_exchange': definedge_exchange,
                'token': token,
                'mode': mode,
                'depth_level': depth_level,
                'actual_depth': actual_depth,
                'tokens': tokens,
                'is_fallback': is_fallback
            }
            # Track token to symbol mapping for cache management
            self.token_to_symbol[token] = (symbol, exchange)

        # Subscribe via WebSocket (reference counting will handle duplicates)
        if self.connected and self.ws_client:
            try:
                # Map mode to DefinEdge subscription type
                if mode == 1:  # LTP only - use touchline
                    subscription_type = 'tick'
                elif mode == 2:  # Quote - use touchline for OHLC
                    subscription_type = 'tick'
                    self.logger.info(f"Using touchline subscription for {symbol} Quote mode to get OHLC data")
                else:  # mode == 3, Depth
                    subscription_type = 'depth'

                # Use reference counting to avoid duplicate WebSocket subscriptions
                scrip = f"{definedge_exchange}|{token}"
                if self._should_ws_subscribe(scrip, subscription_type):
                    success = self.ws_client.subscribe(subscription_type, tokens)
                    if not success:
                        return self._create_error_response("SUBSCRIPTION_ERROR", "Failed to subscribe")
                    self.logger.info(f"[SUBSCRIBE] WebSocket subscription sent for {scrip}")
                else:
                    self.logger.info(f"[SUBSCRIBE] WebSocket already has active subscription for {scrip}")

            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))
        else:
            self.logger.warning(f"[SUBSCRIBE] Not connected, cannot subscribe to {symbol}.{exchange}")

        # Log current subscription state
        self.logger.info(f"[SUBSCRIBE] Total active subscriptions: {len(self.subscriptions)}")

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
        brexchange = token_info['brexchange']

        # Map exchange to DefinEdge format
        definedge_exchange = DefinedgeExchangeMapper.get_exchange_code(brexchange)

        # Create token list for DefinEdge API
        tokens = [(definedge_exchange, token)]

        # Find base correlation ID pattern
        base_correlation_id = f"{symbol}_{exchange}_{mode}"

        with self.lock:
            # Find the first matching subscription for this client
            matching_subscriptions = [
                (cid, sub) for cid, sub in self.subscriptions.items()
                if cid.startswith(base_correlation_id)
            ]

            if not matching_subscriptions:
                return self._create_error_response("NOT_SUBSCRIBED",
                                                  f"Not subscribed to {symbol}.{exchange}")

            # Remove the first matching subscription
            correlation_id, subscription = matching_subscriptions[0]

            # Check if this is the last subscription for this symbol/exchange/mode
            is_last = len(matching_subscriptions) == 1

            # Remove the subscription
            del self.subscriptions[correlation_id]

            # Clean up token mapping and cache if no other subscriptions use this token
            if not any(sub['token'] == token for sub in self.subscriptions.values()):
                self.token_to_symbol.pop(token, None)
                self.market_cache.clear(token)

            # Only unsubscribe from WebSocket if this was the last subscription
            if is_last:
                scrip = f"{definedge_exchange}|{token}"
                if self._should_ws_unsubscribe(scrip, subscription['mode']):
                    # Unsubscribe if connected
                    if self.connected and self.ws_client:
                        try:
                            # Map mode to DefinEdge subscription type
                            if subscription['mode'] == 1:  # LTP only - use touchline
                                subscription_type = 'tick'
                            elif subscription['mode'] == 2:  # Quote - we subscribed to touchline for OHLC
                                subscription_type = 'tick'
                            else:  # mode == 3, Depth
                                subscription_type = 'depth'

                            success = self.ws_client.unsubscribe(subscription_type, tokens)
                            if not success:
                                self.logger.warning(f"Failed to unsubscribe WebSocket for {symbol}.{exchange}")

                        except Exception as e:
                            self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode
        )
    
    def _on_open(self, wsapp) -> None:
        """Callback when connection is established"""
        self.logger.info("Connected to DefinEdge WebSocket")
        self.connected = True
        
        # Schedule resubscription after a short delay to allow authentication
        if self.subscriptions:
            import threading
            threading.Timer(1.0, self._resubscribe_all).start()
    
    def _resubscribe_all(self) -> None:
        """Resubscribe to all existing subscriptions after reconnection"""
        with self.lock:
            # Reset reference counts
            self.ws_subscription_refs = {}

            # Collect unique scrips for each subscription type
            tick_scrips = set()
            depth_scrips = set()

            for correlation_id, sub in self.subscriptions.items():
                definedge_exchange = sub['definedge_exchange']
                token = sub['token']
                scrip = f"{definedge_exchange}|{token}"
                mode = sub['mode']

                # Initialize reference count
                if scrip not in self.ws_subscription_refs:
                    self.ws_subscription_refs[scrip] = {'tick_count': 0, 'depth_count': 0}

                if mode in [1, 2]:  # LTP or Quote
                    if scrip not in tick_scrips:
                        tick_scrips.add((definedge_exchange, token))
                    self.ws_subscription_refs[scrip]['tick_count'] += 1
                elif mode == 3:  # Depth
                    if scrip not in depth_scrips:
                        depth_scrips.add((definedge_exchange, token))
                    self.ws_subscription_refs[scrip]['depth_count'] += 1

            # Resubscribe in batches
            try:
                if self.ws_client.is_connected():
                    if tick_scrips:
                        self.ws_client.subscribe('tick', list(tick_scrips))
                        self.logger.info(f"Resubscribed to {len(tick_scrips)} tick scrips with total {sum(self.ws_subscription_refs[f'{e}|{t}']['tick_count'] for e, t in tick_scrips)} subscriptions")

                    if depth_scrips:
                        self.ws_client.subscribe('depth', list(depth_scrips))
                        self.logger.info(f"Resubscribed to {len(depth_scrips)} depth scrips with total {sum(self.ws_subscription_refs[f'{e}|{t}']['depth_count'] for e, t in depth_scrips)} subscriptions")
                else:
                    self.logger.warning("Cannot resubscribe - not authenticated")
            except Exception as e:
                self.logger.error(f"Error during resubscription: {e}")
    
    def _on_error(self, wsapp, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"DefinEdge WebSocket error: {error}")
    
    def _on_close(self, wsapp, code, reason) -> None:
        """Callback when connection is closed"""
        self.logger.info(f"DefinEdge WebSocket connection closed: {code} - {reason}")
        self.connected = False
        
        # Only attempt to reconnect if adapter is still running (not manually disconnected)
        if self.running:
            self.logger.info("Connection lost - will attempt to reconnect")
            threading.Thread(target=self._connect_with_retry, daemon=True).start()
        else:
            self.logger.info("Adapter stopped - not attempting reconnection")
    
    def _on_data(self, wsapp, message) -> None:
        """Callback for touchline/tick data from the WebSocket"""
        try:
            # DefinEdge sends data with 't' field indicating message type
            # 'tf' for touchline feed, 'tk' for touchline acknowledgement
            
            if message.get('t') == 'tk':
                # This is subscription acknowledgement with initial OHLC snapshot
                token = message.get('tk')
                exchange = message.get('e')
                self.logger.info(f"📸 Touchline ACK for {exchange}|{token} - Initial snapshot")
                
                # Check and log OHLC values in acknowledgment
                ohlc_values = {
                    'open': message.get('o'),
                    'high': message.get('h'), 
                    'low': message.get('l'),
                    'close': message.get('c')
                }
                
                # Check if we have non-zero OHLC
                has_nonzero_ohlc = any(
                    v not in [None, '', '0', 0] 
                    for v in ohlc_values.values()
                )
                
                if has_nonzero_ohlc:
                    self.logger.info(f"✅ OHLC snapshot received: Open={ohlc_values['open']}, High={ohlc_values['high']}, Low={ohlc_values['low']}, Close={ohlc_values['close']}")
                    # Mark this as initial snapshot for cache
                    message['_is_snapshot'] = True
                else:
                    self.logger.warning(f"⚠️ No OHLC in touchline ACK (market may be closed)")
                
                # Always process acknowledgment as it contains initial snapshot
                # Continue processing - don't return
            
            # Extract symbol and exchange from our subscriptions using token
            token = message.get('tk')
            exchange = message.get('e')
            
            # Find the subscription that matches this token
            subscription = None
            with self.lock:
                for sub in self.subscriptions.values():
                    if sub['token'] == token and sub['definedge_exchange'] == exchange:
                        subscription = sub
                        break
            
            if not subscription:
                self.logger.warning(f"Received data for unsubscribed token: {exchange}|{token}")
                return
            
            # Create topic for ZeroMQ
            symbol = subscription['symbol']
            orig_exchange = subscription['exchange']
            mode = subscription['mode']
            
            mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}[mode]
            topic = f"{orig_exchange}_{symbol}_{mode_str}"
            
            # Use cache BEFORE normalization (like Shoonya does)
            # This preserves raw field names for cache logic
            cached_data = self.market_cache.update(token, message)
            
            # Now normalize the cached data for output
            market_data = self._normalize_raw_data(cached_data, mode)
            
            # Add metadata
            market_data.update({
                'symbol': symbol,
                'exchange': orig_exchange,
                'mode': mode,
                'timestamp': int(time.time() * 1000)  # Current timestamp in ms
            })
            
            # Log the market data we're sending
            self.logger.debug(f"Publishing market data on topic {topic}: {market_data}")
            
            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)
            
        except Exception as e:
            self.logger.error(f"Error processing market data: {e}", exc_info=True)
    
    def _publish_for_other_modes(self, token: str, symbol: str, exchange: str, market_data: Dict) -> None:
        """
        Publish market data for other subscription modes (Quote/LTP) when depth data is available.
        This allows Quote mode to get OHLC values from Depth subscriptions.
        """
        try:
            # Check if there are Quote or LTP subscriptions for this token
            with self.lock:
                for correlation_id, sub in self.subscriptions.items():
                    if sub['token'] == token and sub['mode'] in [1, 2]:  # LTP or Quote mode
                        mode = sub['mode']
                        mode_str = {1: 'LTP', 2: 'QUOTE'}[mode]
                        topic = f"{exchange}_{symbol}_{mode_str}"
                        
                        # Create mode-specific data
                        if mode == 1:  # LTP mode - only send LTP
                            ltp_data = {
                                'symbol': symbol,
                                'exchange': exchange,
                                'mode': 1,
                                'ltp': market_data.get('ltp', 0),
                                'timestamp': int(time.time() * 1000)
                            }
                            self.publish_market_data(topic, ltp_data)
                            self.logger.debug(f"Published LTP data from depth for {symbol}")
                            
                        elif mode == 2:  # Quote mode - send OHLC + quote data
                            quote_data = {
                                'symbol': symbol,
                                'exchange': exchange,
                                'mode': 2,
                                'ltp': market_data.get('ltp', 0),
                                'open': market_data.get('open', 0),
                                'high': market_data.get('high', 0),
                                'low': market_data.get('low', 0),
                                'close': market_data.get('close', 0),
                                'volume': market_data.get('volume', 0),
                                'timestamp': int(time.time() * 1000)
                            }
                            
                            # Log if we're providing OHLC from depth
                            if any(market_data.get(f) for f in ['open', 'high', 'low', 'close']):
                                self.logger.info(f"✓ Providing OHLC to Quote mode from Depth data for {symbol}")
                            
                            self.publish_market_data(topic, quote_data)
                            
        except Exception as e:
            self.logger.error(f"Error publishing for other modes: {e}")
    
    def _on_depth_data(self, wsapp, message) -> None:
        """Callback for depth data from the WebSocket"""
        try:
            # DefinEdge sends depth data with 't' field = 'df' for depth feed
            # or 'dk' for depth acknowledgement
            
            if message.get('t') == 'dk':
                # This is subscription acknowledgement with initial data
                self.logger.info(f"Depth subscription acknowledged: {message.get('e')}|{message.get('tk')}")
                # Check if acknowledgment contains initial OHLC data
                if any(message.get(f) for f in ['o', 'h', 'l', 'c']):
                    self.logger.info(f"✓ Depth ACK has OHLC: o={message.get('o')}, h={message.get('h')}, l={message.get('l')}, c={message.get('c')}")
                    # Process the acknowledgment as initial data
                else:
                    return
            
            # Process depth data similar to touchline but with depth fields
            token = message.get('tk')
            exchange = message.get('e')
            
            # Debug: Log what OHLC fields are in depth feed
            if message.get('t') == 'df':
                ohlc_check = {
                    'o': message.get('o'),
                    'h': message.get('h'),
                    'l': message.get('l'),
                    'c': message.get('c')
                }
                has_ohlc = any(v not in [None, '', '0', 0] for v in ohlc_check.values())
                if not hasattr(self, '_depth_ohlc_logged') or not self._depth_ohlc_logged.get(f"{exchange}|{token}"):
                    if not hasattr(self, '_depth_ohlc_logged'):
                        self._depth_ohlc_logged = {}
                    self._depth_ohlc_logged[f"{exchange}|{token}"] = True
                    if has_ohlc:
                        self.logger.info(f"✓ Depth feed has OHLC for {exchange}|{token}: {ohlc_check}")
                    else:
                        self.logger.warning(f"✗ Depth feed has NO OHLC for {exchange}|{token}")
            
            # Find the subscription
            subscription = None
            with self.lock:
                for sub in self.subscriptions.values():
                    if sub['token'] == token and sub['definedge_exchange'] == exchange:
                        subscription = sub
                        break
            
            if not subscription:
                self.logger.warning(f"Received depth data for unsubscribed token: {exchange}|{token}")
                return
            
            # Create topic for ZeroMQ
            symbol = subscription['symbol']
            orig_exchange = subscription['exchange']
            
            topic = f"{orig_exchange}_{symbol}_DEPTH"
            
            # Use cache BEFORE normalization (like Shoonya)
            cached_data = self.market_cache.update(token, message)
            
            # Now normalize the cached data for output
            market_data = self._normalize_raw_depth_data(cached_data)
            
            # Add metadata for depth subscription
            depth_data = market_data.copy()
            depth_data.update({
                'symbol': symbol,
                'exchange': orig_exchange,
                'mode': 3,  # Depth mode
                'timestamp': int(time.time() * 1000)
            })
            
            # Publish to ZeroMQ for depth subscribers
            self.publish_market_data(topic, depth_data)
            
            # IMPORTANT: Also publish OHLC data for any Quote mode subscriptions
            # This allows Quote mode to get OHLC from Depth data
            self._publish_for_other_modes(token, symbol, orig_exchange, market_data)
            
        except Exception as e:
            self.logger.error(f"Error processing depth data: {e}", exc_info=True)
    
    def _normalize_raw_data(self, message, mode) -> Dict[str, Any]:
        """
        Normalize broker-specific data format without converting missing values to 0
        
        Args:
            message: The raw message from the broker
            mode: Subscription mode
            
        Returns:
            Dict: Normalized market data (only includes fields that are present)
        """
        result = {}
        
        if mode == 1:  # LTP mode
            # Only include fields that are actually present in the message
            if 'lp' in message:
                result['ltp'] = float(message['lp'])
            if 'ft' in message:
                result['ltt'] = message['ft']
                
        elif mode == 2:  # Quote mode
            # Similar to Shoonya, include all fields with safe conversion
            result['ltp'] = self._safe_float(message.get('lp'))
            result['ltt'] = message.get('ft')
            result['volume'] = self._safe_int(message.get('v'))
            result['open'] = self._safe_float(message.get('o'))
            result['high'] = self._safe_float(message.get('h'))
            result['low'] = self._safe_float(message.get('l'))
            result['close'] = self._safe_float(message.get('c'))
            result['change_percent'] = self._safe_float(message.get('pc'))
            result['average_price'] = self._safe_float(message.get('ap'))
            result['oi'] = self._safe_int(message.get('oi'))
            result['prev_oi'] = self._safe_int(message.get('poi'))
            result['total_oi'] = self._safe_int(message.get('toi'))
            result['bid'] = self._safe_float(message.get('bp1'))
            result['bid_qty'] = self._safe_int(message.get('bq1'))
            result['ask'] = self._safe_float(message.get('sp1'))
            result['ask_qty'] = self._safe_int(message.get('sq1'))
            
            # Debug logging for OHLC
            if any(message.get(f) for f in ['o', 'h', 'l', 'c']):
                self.logger.debug(f"OHLC in message: o={message.get('o')}, h={message.get('h')}, l={message.get('l')}, c={message.get('c')}")
                        
        return result
    
    def _safe_float(self, value, default=0.0):
        """Safely convert value to float (similar to Shoonya)"""
        if value is None or value == '' or value == '-':
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default
    
    def _safe_int(self, value, default=0):
        """Safely convert value to int (similar to Shoonya)"""
        if value is None or value == '' or value == '-':
            return default
        try:
            return int(float(value))
        except (ValueError, TypeError):
            return default
    
    def _should_ws_subscribe(self, scrip: str, subscription_type: str) -> bool:
        """
        Check if we should send WebSocket subscription using reference counting

        Args:
            scrip: Exchange|Token identifier
            subscription_type: 'tick' or 'depth'

        Returns:
            bool: True if we need to subscribe, False if already subscribed
        """
        if scrip not in self.ws_subscription_refs:
            self.ws_subscription_refs[scrip] = {'tick_count': 0, 'depth_count': 0}

        if subscription_type == 'tick':
            if self.ws_subscription_refs[scrip]['tick_count'] == 0:
                self.ws_subscription_refs[scrip]['tick_count'] = 1
                return True
            else:
                self.ws_subscription_refs[scrip]['tick_count'] += 1
                self.logger.info(f"Additional tick subscription for {scrip}, count: {self.ws_subscription_refs[scrip]['tick_count']}")
                return False
        elif subscription_type == 'depth':
            if self.ws_subscription_refs[scrip]['depth_count'] == 0:
                self.ws_subscription_refs[scrip]['depth_count'] = 1
                return True
            else:
                self.ws_subscription_refs[scrip]['depth_count'] += 1
                self.logger.info(f"Additional depth subscription for {scrip}, count: {self.ws_subscription_refs[scrip]['depth_count']}")
                return False

        return True

    def _should_ws_unsubscribe(self, scrip: str, mode: int) -> bool:
        """
        Check if we should send WebSocket unsubscription using reference counting

        Args:
            scrip: Exchange|Token identifier
            mode: Subscription mode (1=LTP, 2=Quote, 3=Depth)

        Returns:
            bool: True if we should unsubscribe, False if other clients still subscribed
        """
        if scrip not in self.ws_subscription_refs:
            return True

        if mode in [1, 2]:  # tick subscription
            self.ws_subscription_refs[scrip]['tick_count'] -= 1
            if self.ws_subscription_refs[scrip]['tick_count'] <= 0:
                self.ws_subscription_refs[scrip]['tick_count'] = 0
                # Clean up if both counts are 0
                if self.ws_subscription_refs[scrip]['depth_count'] == 0:
                    del self.ws_subscription_refs[scrip]
                return True
            return False
        elif mode == 3:  # depth subscription
            self.ws_subscription_refs[scrip]['depth_count'] -= 1
            if self.ws_subscription_refs[scrip]['depth_count'] <= 0:
                self.ws_subscription_refs[scrip]['depth_count'] = 0
                # Clean up if both counts are 0
                if self.ws_subscription_refs[scrip]['tick_count'] == 0:
                    del self.ws_subscription_refs[scrip]
                return True
            return False

        return True

    def _normalize_raw_depth_data(self, message) -> Dict[str, Any]:
        """
        Normalize depth data using safe conversion (similar to Shoonya)
        
        Args:
            message: Raw depth message from broker
            
        Returns:
            Dict: Normalized depth data with safe defaults
        """
        # Use safe conversion for all fields like Shoonya does
        result = {
            'ltp': self._safe_float(message.get('lp')),
            'ltt': message.get('ft'),
            'volume': self._safe_int(message.get('v')),
            'open': self._safe_float(message.get('o')),
            'high': self._safe_float(message.get('h')),
            'low': self._safe_float(message.get('l')),
            'close': self._safe_float(message.get('c')),
            'change_percent': self._safe_float(message.get('pc')),
            'average_price': self._safe_float(message.get('ap')),
            'ltq': self._safe_int(message.get('ltq')),
            'ltt_time': message.get('ltt'),
            'total_buy_qty': self._safe_int(message.get('tbq')),
            'total_sell_qty': self._safe_int(message.get('tsq')),
            'lower_circuit': self._safe_float(message.get('lc')),
            'upper_circuit': self._safe_float(message.get('uc')),
            '52w_high': self._safe_float(message.get('52h')),
            '52w_low': self._safe_float(message.get('52l')),
            'oi': self._safe_int(message.get('oi')),
            'prev_oi': self._safe_int(message.get('poi')),
            'total_oi': self._safe_int(message.get('toi'))
        }
        
        # Handle depth data separately (similar to Shoonya)
        depth_buy = []
        depth_sell = []
        
        # Extract 5 levels of depth
        for i in range(1, 6):
            # Buy side - always include even if 0
            buy_level = {
                'price': self._safe_float(message.get(f'bp{i}')),
                'quantity': self._safe_int(message.get(f'bq{i}')),
                'orders': self._safe_int(message.get(f'bo{i}'))
            }
            depth_buy.append(buy_level)
            
            # Sell side - always include even if 0  
            sell_level = {
                'price': self._safe_float(message.get(f'sp{i}')),
                'quantity': self._safe_int(message.get(f'sq{i}')),
                'orders': self._safe_int(message.get(f'so{i}'))
            }
            depth_sell.append(sell_level)
        
        # Always include depth structure
        result['depth'] = {
            'buy': depth_buy,
            'sell': depth_sell
        }
        
        return result