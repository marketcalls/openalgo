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
                self.logger.info(f"Connecting to DefinEdge WebSocket (attempt {self.reconnect_attempts + 1})")
                if self.ws_client.connect():
                    self.reconnect_attempts = 0  # Reset attempts on successful connection
                    break
                else:
                    raise Exception("Connection failed")
                    
            except Exception as e:
                self.reconnect_attempts += 1
                delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), self.max_reconnect_delay)
                self.logger.error(f"Connection failed: {e}. Retrying in {delay} seconds...")
                time.sleep(delay)
        
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            self.logger.error("Max reconnection attempts reached. Giving up.")
    
    def disconnect(self) -> None:
        """Disconnect from DefinEdge WebSocket"""
        self.running = False
        if hasattr(self, 'ws_client') and self.ws_client:
            self.ws_client.disconnect()
            
        # Clean up ZeroMQ resources
        self.cleanup_zmq()
    
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
        
        # Generate unique correlation ID that includes mode to prevent overwriting
        correlation_id = f"{symbol}_{exchange}_{mode}"
        if mode == 3:
            correlation_id = f"{correlation_id}_{depth_level}"
        
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
        
        # Subscribe if connected
        if self.connected and self.ws_client:
            try:
                # Map mode to DefinEdge subscription type
                if mode in [1, 2]:  # LTP or Quote - use touchline
                    subscription_type = 'tick'
                else:  # mode == 3, Depth
                    subscription_type = 'depth'
                
                success = self.ws_client.subscribe(subscription_type, tokens)
                if not success:
                    return self._create_error_response("SUBSCRIPTION_ERROR", "Failed to subscribe")
                    
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
        
        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"
        
        # Remove from subscriptions
        with self.lock:
            if correlation_id in self.subscriptions:
                del self.subscriptions[correlation_id]
        
        # Unsubscribe if connected
        if self.connected and self.ws_client:
            try:
                # Map mode to DefinEdge subscription type
                if mode in [1, 2]:  # LTP or Quote
                    subscription_type = 'tick'
                else:  # mode == 3, Depth
                    subscription_type = 'depth'
                
                success = self.ws_client.unsubscribe(subscription_type, tokens)
                if not success:
                    return self._create_error_response("UNSUBSCRIPTION_ERROR", "Failed to unsubscribe")
                    
            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))
        
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
            for correlation_id, sub in self.subscriptions.items():
                try:
                    # Check if authenticated
                    if self.ws_client.is_connected():
                        # Map mode to DefinEdge subscription type
                        if sub["mode"] in [1, 2]:
                            subscription_type = 'tick'
                        else:
                            subscription_type = 'depth'
                        
                        self.ws_client.subscribe(subscription_type, sub["tokens"])
                        self.logger.info(f"Resubscribed to {sub['symbol']}.{sub['exchange']}")
                    else:
                        self.logger.warning(f"Cannot resubscribe to {sub['symbol']}.{sub['exchange']} - not authenticated")
                except Exception as e:
                    self.logger.error(f"Error resubscribing to {sub['symbol']}.{sub['exchange']}: {e}")
    
    def _on_error(self, wsapp, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"DefinEdge WebSocket error: {error}")
    
    def _on_close(self, wsapp, code, reason) -> None:
        """Callback when connection is closed"""
        self.logger.info(f"DefinEdge WebSocket connection closed: {code} - {reason}")
        self.connected = False
        
        # Attempt to reconnect if we're still running
        if self.running:
            threading.Thread(target=self._connect_with_retry, daemon=True).start()
    
    def _on_data(self, wsapp, message) -> None:
        """Callback for touchline/tick data from the WebSocket"""
        try:
            # DefinEdge sends data with 't' field indicating message type
            # 'tf' for touchline feed, 'tk' for touchline acknowledgement
            
            if message.get('t') == 'tk':
                # This is subscription acknowledgement, not data
                self.logger.info(f"Subscription acknowledged for {message.get('e')}|{message.get('tk')}")
                return
            
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
            
            # Normalize the data
            market_data = self._normalize_market_data(message, mode)
            
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
    
    def _on_depth_data(self, wsapp, message) -> None:
        """Callback for depth data from the WebSocket"""
        try:
            # DefinEdge sends depth data with 't' field = 'df' for depth feed
            # or 'dk' for depth acknowledgement
            
            if message.get('t') == 'dk':
                # This is subscription acknowledgement, not data
                self.logger.info(f"Depth subscription acknowledged for {message.get('e')}|{message.get('tk')}")
                return
            
            # Process depth data similar to touchline but with depth fields
            token = message.get('tk')
            exchange = message.get('e')
            
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
            
            # Normalize the depth data
            market_data = self._normalize_depth_data(message)
            
            # Add metadata
            market_data.update({
                'symbol': symbol,
                'exchange': orig_exchange,
                'mode': 3,  # Depth mode
                'timestamp': int(time.time() * 1000)
            })
            
            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)
            
        except Exception as e:
            self.logger.error(f"Error processing depth data: {e}", exc_info=True)
    
    def _normalize_market_data(self, message, mode) -> Dict[str, Any]:
        """
        Normalize broker-specific data format to a common format
        
        Args:
            message: The raw message from the broker
            mode: Subscription mode
            
        Returns:
            Dict: Normalized market data
        """
        # DefinEdge touchline feed format (from API docs)
        # All prices should be converted from string to float
        
        if mode == 1:  # LTP mode
            return {
                'ltp': float(message.get('lp', 0)),
                'ltt': message.get('ft', 0)  # Feed time
            }
        elif mode == 2:  # Quote mode
            return {
                'ltp': float(message.get('lp', 0)),
                'ltt': message.get('ft', 0),
                'volume': int(message.get('v', 0)),
                'open': float(message.get('o', 0)),
                'high': float(message.get('h', 0)),
                'low': float(message.get('l', 0)),
                'close': float(message.get('c', 0)),
                'change_percent': float(message.get('pc', 0)),
                'average_price': float(message.get('ap', 0)),
                'oi': int(message.get('oi', 0)) if message.get('oi') else 0,
                'prev_oi': int(message.get('poi', 0)) if message.get('poi') else 0,
                'total_oi': int(message.get('toi', 0)) if message.get('toi') else 0,
                'bid': float(message.get('bp1', 0)),
                'bid_qty': int(message.get('bq1', 0)),
                'ask': float(message.get('sp1', 0)),
                'ask_qty': int(message.get('sq1', 0))
            }
        else:
            return {}
    
    def _normalize_depth_data(self, message) -> Dict[str, Any]:
        """
        Normalize depth data to common format
        
        Args:
            message: Raw depth message from broker
            
        Returns:
            Dict: Normalized depth data
        """
        result = {
            'ltp': float(message.get('lp', 0)),
            'ltt': message.get('ft', 0),
            'volume': int(message.get('v', 0)),
            'open': float(message.get('o', 0)),
            'high': float(message.get('h', 0)),
            'low': float(message.get('l', 0)),
            'close': float(message.get('c', 0)),
            'change_percent': float(message.get('pc', 0)),
            'average_price': float(message.get('ap', 0)),
            'ltq': int(message.get('ltq', 0)) if message.get('ltq') else 0,
            'ltt_time': message.get('ltt', 0),
            'total_buy_qty': int(message.get('tbq', 0)) if message.get('tbq') else 0,
            'total_sell_qty': int(message.get('tsq', 0)) if message.get('tsq') else 0,
            'lower_circuit': float(message.get('lc', 0)) if message.get('lc') else 0,
            'upper_circuit': float(message.get('uc', 0)) if message.get('uc') else 0,
            '52w_high': float(message.get('52h', 0)) if message.get('52h') else 0,
            '52w_low': float(message.get('52l', 0)) if message.get('52l') else 0,
            'oi': int(message.get('oi', 0)) if message.get('oi') else 0,
            'prev_oi': int(message.get('poi', 0)) if message.get('poi') else 0,
            'total_oi': int(message.get('toi', 0)) if message.get('toi') else 0
        }
        
        # Add depth data
        result['depth'] = {
            'buy': [],
            'sell': []
        }
        
        # Extract 5 levels of depth
        for i in range(1, 6):
            # Buy side
            bp = message.get(f'bp{i}')
            bq = message.get(f'bq{i}')
            bo = message.get(f'bo{i}')
            
            if bp is not None:
                result['depth']['buy'].append({
                    'price': float(bp),
                    'quantity': int(bq) if bq else 0,
                    'orders': int(bo) if bo else 0
                })
            
            # Sell side
            sp = message.get(f'sp{i}')
            sq = message.get(f'sq{i}')
            so = message.get(f'so{i}')
            
            if sp is not None:
                result['depth']['sell'].append({
                    'price': float(sp),
                    'quantity': int(sq) if sq else 0,
                    'orders': int(so) if so else 0
                })
        
        return result