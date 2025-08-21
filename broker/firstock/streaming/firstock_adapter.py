import threading
import json
import logging
import time
from typing import Dict, Any, Optional, List
import os
from dotenv import load_dotenv

from database.auth_db import get_auth_token
from database.token_db import get_token

import sys

# Load environment variables
load_dotenv()

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .firstock_mapping import FirstockExchangeMapper
from .firstock_websocket import FirstockWebSocket

class FirstockWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Firstock-specific implementation of the WebSocket adapter"""
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("firstock_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "firstock"
        self.running = False
        self.lock = threading.Lock()
        # Snapshot management for value retention (similar to Shoonya implementation)
        self.market_snapshots = {}  # {token: snapshot_data} - retains previous values
    
    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Firstock WebSocket API
        
        Args:
            broker_name: Name of the broker (always 'firstock' in this case)
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
            # IMPORTANT: For Firstock, this must be the 'susertoken' from login API response
            auth_token = get_auth_token(user_id)
            
            # Auth token must come from database (after Firstock login)
            
            if not auth_token:
                self.logger.error(f"No authentication token found for user {user_id}")
                self.logger.error("For Firstock, the auth_token must be the 'susertoken' from the login API")
                raise ValueError(f"No authentication token found for user {user_id}. Please login through Firstock's login API first.")
                
            self.auth_token = auth_token
            
            # For Firstock, we need to get the broker-specific user ID from BROKER_API_KEY
            # The BROKER_API_KEY contains the Firstock user ID (e.g., RR0884_API)
            broker_api_key = os.getenv('BROKER_API_KEY', '')
            if broker_api_key:
                # Extract the user ID part (remove _API suffix if present)
                self.firstock_user_id = broker_api_key.replace('_API', '')
                self.logger.info(f"Using Firstock user ID '{self.firstock_user_id}' from BROKER_API_KEY")
            else:
                # Fallback to OpenAlgo user ID if BROKER_API_KEY not set
                self.firstock_user_id = user_id
                self.logger.warning(f"BROKER_API_KEY not found in environment. Using OpenAlgo user ID '{user_id}' which may fail authentication")
            
        else:
            # Use provided tokens
            # IMPORTANT: For Firstock, this must be the 'susertoken' from login API response
            auth_token = auth_data.get('auth_token')
            
            if not auth_token:
                self.logger.error("Missing required authentication data")
                self.logger.error("For Firstock, the auth_token must be the 'susertoken' from the login API")
                raise ValueError("Missing required authentication data")
                
            self.auth_token = auth_token
            
            # Check if broker-specific user ID is provided
            if 'broker_user_id' in auth_data:
                self.firstock_user_id = auth_data['broker_user_id']
                self.logger.info(f"Using Firstock user ID '{self.firstock_user_id}' from auth_data")
            else:
                # Get from BROKER_API_KEY environment variable
                broker_api_key = os.getenv('BROKER_API_KEY', '')
                if broker_api_key:
                    # Extract the user ID part (remove _API suffix if present)
                    self.firstock_user_id = broker_api_key.replace('_API', '')
                    self.logger.info(f"Using Firstock user ID '{self.firstock_user_id}' from BROKER_API_KEY")
                else:
                    # Fallback to OpenAlgo user ID if BROKER_API_KEY not set
                    self.firstock_user_id = user_id
                    self.logger.warning(f"BROKER_API_KEY not found in environment. Using OpenAlgo user ID '{user_id}' which may fail authentication")
        
        # Create FirstockWebSocket instance
        # Use Firstock-specific user ID if available
        self.ws_client = FirstockWebSocket(
            user_id=self.firstock_user_id,
            auth_token=self.auth_token,
            max_retry_attempt=5,
            retry_delay=5
        )
        
        # Set callbacks
        self.ws_client.on_open = self._on_open
        self.ws_client.on_data = self._on_data
        self.ws_client.on_error = self._on_error
        self.ws_client.on_close = self._on_close
        self.ws_client.on_message = self._on_message
        
        self.running = True
        
    def connect(self) -> None:
        """Establish connection to Firstock WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return
            
        try:
            self.ws_client.connect()
        except Exception as e:
            self.logger.error(f"Failed to connect to Firstock WebSocket: {e}")
            raise
    
    def disconnect(self) -> None:
        """Disconnect from Firstock WebSocket"""
        self.running = False
        
        if self.ws_client:
            self.ws_client.close_connection()
            
        # Clear snapshots
        self.market_snapshots.clear()
            
        # Clean up ZeroMQ resources
        self.cleanup_zmq()
    
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with Firstock-specific implementation
        
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Depth (Firstock always provides full data)
            depth_level: Market depth level (Firstock provides 5-level depth)
            
        Returns:
            Dict: Response with status and error message if applicable
        """
        # Firstock provides full market data including depth in a single feed
        # Mode parameter is maintained for API consistency but all data is provided
        
        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND", 
                                              f"Symbol {symbol} not found for exchange {exchange}")
            
        token = token_info['token']
        brexchange = token_info['brexchange']
        
        # Create subscription token in Firstock format (EXCHANGE:TOKEN)
        subscription_token = f"{brexchange}:{token}"
        
        # Generate unique correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"
        
        # Store subscription for reconnection
        with self.lock:
            self.subscriptions[correlation_id] = {
                'symbol': symbol,
                'exchange': exchange,
                'brexchange': brexchange,
                'token': token,
                'subscription_token': subscription_token,
                'mode': mode,
                'depth_level': depth_level
            }
        
        # Subscribe if connected
        if self.ws_client and self.ws_client.is_connected():
            try:
                # Create token list for Firstock WebSocket client
                token_list = [{
                    "exchangeType": brexchange,
                    "tokens": [token]
                }]
                
                self.ws_client.subscribe(correlation_id, mode, token_list)
                self.logger.info(f"Subscribed to {symbol}.{exchange} with token {subscription_token}")
            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))
        
        # Return success
        return self._create_success_response(
            'Subscription requested',
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            depth_level=5  # Firstock always provides 5-level depth
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
        
        # Create subscription token in Firstock format
        subscription_token = f"{brexchange}:{token}"
        
        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"
        
        # Remove from subscriptions
        with self.lock:
            if correlation_id in self.subscriptions:
                del self.subscriptions[correlation_id]
        
        # Unsubscribe if connected
        if self.ws_client and self.ws_client.is_connected():
            try:
                # Create token list for Firstock WebSocket client
                token_list = [{
                    "exchangeType": brexchange,
                    "tokens": [token]
                }]
                
                self.ws_client.unsubscribe(correlation_id, mode, token_list)
                self.logger.info(f"Unsubscribed from {symbol}.{exchange}")
            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))
        
        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode
        )
    
    def _on_open(self, ws) -> None:
        """Callback when connection is established"""
        self.logger.info("Connected to Firstock WebSocket")
        self.connected = True
        
        # Resubscribe to existing subscriptions if reconnecting
        with self.lock:
            for correlation_id, sub in self.subscriptions.items():
                try:
                    # Create token list for resubscription
                    token_list = [{
                        "exchangeType": sub['brexchange'],
                        "tokens": [sub['token']]
                    }]
                    
                    self.ws_client.subscribe(correlation_id, sub['mode'], token_list)
                    self.logger.info(f"Resubscribed to {sub['symbol']}.{sub['exchange']}")
                except Exception as e:
                    self.logger.error(f"Error resubscribing to {sub['symbol']}.{sub['exchange']}: {e}")
    
    def _on_error(self, ws, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"Firstock WebSocket error: {error}")
    
    def _on_close(self, ws) -> None:
        """Callback when connection is closed"""
        self.logger.info("Firstock WebSocket connection closed")
        self.connected = False
    
    def _on_message(self, ws, message) -> None:
        """Callback for text messages from the WebSocket"""
        self.logger.debug(f"Received text message: {message}")
    
    def _on_data(self, ws, data) -> None:
        """Callback for data messages from the WebSocket"""
        try:
            self.logger.info(f"Received data from Firstock WebSocket: {data}")
            
            # Handle market data
            if isinstance(data, dict) and 'c_symbol' in data:
                self._process_market_data(data)
            # Handle order updates
            elif isinstance(data, dict) and 'norenordno' in data:
                self._process_order_update(data)
            # Handle position updates
            elif isinstance(data, dict) and 'netqty' in data and 'pcode' in data:
                self._process_position_update(data)
            else:
                self.logger.debug(f"Received unknown data type: {data}")
                
        except Exception as e:
            self.logger.error(f"Error processing data: {e}", exc_info=True)
    
    def _update_market_snapshot(self, token: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update market snapshot for value retention.
        Only updates non-zero/non-invalid values to retain previous valid data.
        """
        # Get existing snapshot or create empty one
        snapshot = self.market_snapshots.get(token, {})
        
        # Fields to merge (only if not invalid/zero)
        merge_fields = [
            # Price fields
            'i_last_traded_price', 'i_open_price', 'i_high_price', 'i_low_price', 'i_closing_price',
            'i_average_trade_price', 'i_upper_circuit_limit', 'i_lower_circuit_limit',
            # Quantity/volume fields  
            'i_volume_traded_today', 'i_last_trade_quantity', 'i_total_buy_quantity', 'i_total_sell_quantity',
            'i_open_interest', 'i_total_open_interest',
            # Time fields
            'i_last_trade_time', 'i_feed_time', 'c_exch_feed_time'
        ]
        
        # Always update these fields (metadata)
        always_update = ['c_symbol', 'c_exch_seg', 'c_net_change_indicator', 'i_buy_depth_size', 'i_sell_depth_size']
        
        # Update snapshot with always-update fields
        for field in always_update:
            if field in data:
                snapshot[field] = data[field]
        
        # Merge non-invalid values from update
        updated_fields = []
        for field in merge_fields:
            if field in data:
                value = data[field]
                # Skip Firstock's invalid values (9223372036854775808 or 0 for prices)
                if (isinstance(value, (int, float)) and 
                    value != 9223372036854775808 and 
                    (field not in ['i_last_traded_price', 'i_open_price', 'i_high_price', 'i_low_price', 
                                   'i_closing_price', 'i_average_trade_price', 'i_upper_circuit_limit', 
                                   'i_lower_circuit_limit'] or value != 0)):
                    snapshot[field] = value
                    updated_fields.append(field)
                elif not isinstance(value, (int, float)):
                    # Non-numeric fields (like timestamps) - always update
                    snapshot[field] = value
                    updated_fields.append(field)
        
        # Handle depth data separately - only update if we have valid depth data
        if 'best_buy' in data and 'best_sell' in data:
            new_buy_depth = self._filter_depth_data(data.get('best_buy', []))
            new_sell_depth = self._filter_depth_data(data.get('best_sell', []))
            
            self.logger.debug(f"Token {token} depth analysis - buy entries: {len(new_buy_depth)}, sell entries: {len(new_sell_depth)}")
            
            # Only update depth if we have valid new data, otherwise retain previous snapshot
            if new_buy_depth:  # Has valid buy data
                snapshot['best_buy'] = new_buy_depth
                updated_fields.append('best_buy')
                self.logger.debug(f"Token {token} updated buy depth with {len(new_buy_depth)} valid entries")
            elif 'best_buy' not in snapshot:  # No previous data, initialize empty
                snapshot['best_buy'] = []
            else:
                self.logger.debug(f"Token {token} retaining previous buy depth ({len(snapshot.get('best_buy', []))} entries)")
                
            if new_sell_depth:  # Has valid sell data  
                snapshot['best_sell'] = new_sell_depth
                updated_fields.append('best_sell')
                self.logger.debug(f"Token {token} updated sell depth with {len(new_sell_depth)} valid entries")
            elif 'best_sell' not in snapshot:  # No previous data, initialize empty
                snapshot['best_sell'] = []
            else:
                self.logger.debug(f"Token {token} retaining previous sell depth ({len(snapshot.get('best_sell', []))} entries)")
        
        # Update stored snapshot
        self.market_snapshots[token] = snapshot
        
        if updated_fields:
            self.logger.debug(f"Updated snapshot fields for token {token}: {updated_fields}")
        
        return snapshot
    
    def _filter_depth_data(self, depth_list: List[Dict]) -> List[Dict]:
        """Filter out invalid depth entries and retain valid ones"""
        filtered_depth = []
        for level in depth_list:
            price = level.get('price', 0)
            quantity = level.get('quantity', 0)
            orders = level.get('orders', 0)
            
            # Keep entries that have valid data (not the invalid marker)
            if (price != 9223372036854775808 and quantity != 9223372036854775808 and 
                orders != 9223372036854775808 and (price > 0 or quantity > 0)):
                filtered_depth.append(level)
        
        return filtered_depth

    def _process_market_data(self, data: Dict[str, Any]) -> None:
        """Process market data from Firstock"""
        try:
            # Extract token from c_symbol field
            token = data.get('c_symbol', '')
            exchange_seg = data.get('c_exch_seg', '')
            
            self.logger.debug(f"Processing market data for token: {token}, exchange: {exchange_seg}")
            self.logger.debug(f"Raw data keys: {list(data.keys())}")
            
            # Find ALL subscriptions that match this token - we need to publish for each mode
            matching_subscriptions = []
            with self.lock:
                for sub in self.subscriptions.values():
                    if sub['token'] == token and sub['brexchange'] == exchange_seg:
                        matching_subscriptions.append(sub)
            
            if not matching_subscriptions:
                self.logger.warning(f"Received data for unsubscribed token: {token} on {exchange_seg}")
                self.logger.debug(f"Available subscriptions: {list(self.subscriptions.keys())}")
                return
            
            # Update snapshot with current data (retains previous values for invalid/zero fields)
            processed_data = self._update_market_snapshot(token, data)
            
            # Publish data for each subscribed mode
            for subscription in matching_subscriptions:
                symbol = subscription['symbol']
                exchange = subscription['exchange']
                mode = subscription['mode']
                
                # Firstock provides all data in one feed, so we publish based on requested mode
                mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}[mode]
                topic = f"{exchange}_{symbol}_{mode_str}"
                
                # Normalize the data based on the requested mode using processed snapshot
                market_data = self._normalize_market_data(processed_data, mode)
                
                # Add metadata
                market_data.update({
                    'symbol': symbol,
                    'exchange': exchange,
                    'mode': mode,
                    'timestamp': int(time.time() * 1000)  # Current timestamp in ms
                })
                
                self.logger.info(f"Publishing {mode_str} data for {symbol}.{exchange}: {market_data}")
                
                # Publish to ZeroMQ
                self.publish_market_data(topic, market_data)
            
        except Exception as e:
            self.logger.error(f"Error processing market data: {e}", exc_info=True)
    
    def _normalize_market_data(self, data: Dict[str, Any], mode: int) -> Dict[str, Any]:
        """
        Normalize Firstock data format to a common format
        
        Args:
            data: The raw message from Firstock
            mode: Subscription mode
            
        Returns:
            Dict: Normalized market data
        """
        # Firstock prices are in paise, convert to rupees by dividing by 100
        
        if mode == 1:  # LTP mode
            return {
                'ltp': float(data.get('i_last_traded_price', 0)) / 100.0,
                'ltt': data.get('i_last_trade_time', 0)
            }
        elif mode == 2:  # Quote mode
            return {
                'ltp': float(data.get('i_last_traded_price', 0)) / 100.0,
                'ltt': data.get('i_last_trade_time', 0),
                'volume': data.get('i_volume_traded_today', 0),
                'open': float(data.get('i_open_price', 0)) / 100.0,
                'high': float(data.get('i_high_price', 0)) / 100.0,
                'low': float(data.get('i_low_price', 0)) / 100.0,
                'close': float(data.get('i_closing_price', 0)) / 100.0,
                'last_quantity': data.get('i_last_trade_quantity', 0),
                'average_price': float(data.get('i_average_trade_price', 0)) / 100.0,
                'total_buy_quantity': data.get('i_total_buy_quantity', 0),
                'total_sell_quantity': data.get('i_total_sell_quantity', 0),
                'oi': data.get('i_open_interest', 0),
                'upper_circuit': float(data.get('i_upper_circuit_limit', 0)) / 100.0,
                'lower_circuit': float(data.get('i_lower_circuit_limit', 0)) / 100.0
            }
        elif mode == 3:  # Depth mode
            result = {
                'ltp': float(data.get('i_last_traded_price', 0)) / 100.0,
                'ltt': data.get('i_last_trade_time', 0),
                'volume': data.get('i_volume_traded_today', 0),
                'open': float(data.get('i_open_price', 0)) / 100.0,
                'high': float(data.get('i_high_price', 0)) / 100.0,
                'low': float(data.get('i_low_price', 0)) / 100.0,
                'close': float(data.get('i_closing_price', 0)) / 100.0,
                'oi': data.get('i_total_open_interest', 0),
                'upper_circuit': float(data.get('i_upper_circuit_limit', 0)) / 100.0,
                'lower_circuit': float(data.get('i_lower_circuit_limit', 0)) / 100.0
            }
            
            # Extract depth data
            result['depth'] = {
                'buy': self._extract_depth_data(data.get('best_buy', []), is_buy=True),
                'sell': self._extract_depth_data(data.get('best_sell', []), is_buy=False)
            }
            
            return result
        else:
            return {}
    
    def _extract_depth_data(self, depth_list: List[Dict], is_buy: bool) -> List[Dict[str, Any]]:
        """
        Extract depth data from Firstock's format (used by normalize method)
        This converts the retained snapshot depth data to the final output format
        
        Args:
            depth_list: List of depth levels from snapshot (already filtered)
            is_buy: Whether this is buy or sell side
            
        Returns:
            List: List of depth levels with price, quantity, and orders
        """
        depth = []
        
        for level in depth_list:
            # These should already be filtered, but double-check
            price = level.get('price', 0)
            quantity = level.get('quantity', 0)
            orders = level.get('orders', 0)
            
            # Convert invalid values to 0 for display
            if price == 9223372036854775808:
                price = 0
            if quantity == 9223372036854775808:
                quantity = 0
            if orders == 9223372036854775808:
                orders = 0
            
            depth.append({
                'price': float(price) / 100.0,  # Convert from paise to rupees
                'quantity': quantity,
                'orders': orders
            })
        
        # Ensure we have at least 5 levels
        while len(depth) < 5:
            depth.append({
                'price': 0.0,
                'quantity': 0,
                'orders': 0
            })
        
        return depth[:5]  # Return only first 5 levels
    
    def _process_order_update(self, data: Dict[str, Any]) -> None:
        """Process order update from Firstock"""
        # This can be implemented if order updates via WebSocket are needed
        self.logger.debug(f"Received order update: {data}")
    
    def _process_position_update(self, data: Dict[str, Any]) -> None:
        """Process position update from Firstock"""
        # This can be implemented if position updates via WebSocket are needed
        self.logger.debug(f"Received position update: {data}")