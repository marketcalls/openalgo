import threading
import json
import logging
import time
import zmq
from typing import Dict, Any, Optional, List

from database.auth_db import get_auth_token
from database.token_db import get_token

import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .groww_mapping import GrowwExchangeMapper, GrowwCapabilityRegistry
from .nats_websocket import GrowwNATSWebSocket

class GrowwWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Groww-specific implementation of the WebSocket adapter"""
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("groww_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "groww"
        self.running = False
        self.lock = threading.Lock()
        self.subscription_keys = {}  # Map correlation_id to subscription keys
    
    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Groww WebSocket API
        
        Args:
            broker_name: Name of the broker (always 'groww' in this case)
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
            # Use provided token
            auth_token = auth_data.get('auth_token')
            
            if not auth_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")
        
        # Create WebSocket client with callbacks
        self.ws_client = GrowwNATSWebSocket(
            auth_token=auth_token,
            on_data=self._on_data,
            on_error=self._on_error
        )
        
        self.running = True
        
    def connect(self) -> None:
        """Establish connection to Groww WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return
            
        try:
            self.logger.info("Connecting to Groww WebSocket")
            self.ws_client.connect()
            self.connected = True
            self.logger.info("Connected to Groww WebSocket successfully")
            
            # Resubscribe to existing subscriptions if any
            with self.lock:
                for correlation_id, sub_info in self.subscriptions.items():
                    self._resubscribe(correlation_id, sub_info)
                    
        except Exception as e:
            self.logger.error(f"Failed to connect to Groww WebSocket: {e}")
            self.connected = False
            raise
    
    def unsubscribe_all(self) -> Dict[str, Any]:
        """
        Unsubscribe from all active subscriptions with proper cleanup

        Returns:
            Dict: Response with status and details
        """
        try:
            if not self.subscriptions:
                return self._create_success_response("No active subscriptions to unsubscribe")

            unsubscribed_count = 0
            failed_count = 0
            unsubscribed_list = []
            failed_list = []

            self.logger.info(f"🧹 Unsubscribing from {len(self.subscriptions)} active subscriptions...")

            # Create a copy of subscriptions to iterate over
            subscriptions_copy = self.subscriptions.copy()

            for correlation_id, sub_info in subscriptions_copy.items():
                try:
                    symbol = sub_info['symbol']
                    exchange = sub_info['exchange']
                    mode = sub_info['mode']

                    # Unsubscribe from the symbol
                    response = self.unsubscribe(symbol, exchange, mode)

                    if response.get('status') == 'success':
                        unsubscribed_count += 1
                        unsubscribed_list.append({
                            'symbol': symbol,
                            'exchange': exchange,
                            'mode': mode
                        })
                        self.logger.debug(f"✅ Unsubscribed: {exchange}:{symbol} mode {mode}")
                    else:
                        failed_count += 1
                        failed_list.append({
                            'symbol': symbol,
                            'exchange': exchange,
                            'mode': mode,
                            'error': response.get('message', 'Unknown error')
                        })
                        self.logger.warning(f"❌ Failed to unsubscribe: {exchange}:{symbol} mode {mode}")

                except Exception as e:
                    failed_count += 1
                    failed_list.append({
                        'correlation_id': correlation_id,
                        'error': str(e)
                    })
                    self.logger.error(f"Error unsubscribing from {correlation_id}: {e}")

            # Force clear all remaining subscriptions and keys
            self.subscriptions.clear()
            self.subscription_keys.clear()

            # CRITICAL: Call the disconnect method to properly close everything
            self.logger.info("🔌 Calling disconnect() to terminate Groww connection completely...")
            try:
                self.disconnect()
                self.logger.info("✅ Successfully disconnected from Groww server")
            except Exception as e:
                self.logger.error(f"❌ Error during disconnect: {e}")
                # Force cleanup even if disconnect fails
                self.running = False
                self.connected = False
                if self.ws_client:
                    try:
                        self.ws_client.disconnect()
                    except:
                        pass
                    self.ws_client = None
                self.cleanup_zmq()

            # Reset message counter for next session
            if hasattr(self, '_message_count'):
                self._message_count = 0

            self.logger.info(f"📊 Unsubscribe all complete: {unsubscribed_count} success, {failed_count} failed")
            self.logger.info("✅ All subscriptions cleared and disconnected from Groww server")
            self.logger.info("✅ ZMQ resources cleaned up - no more data will be published")

            return self._create_success_response(
                f"Unsubscribed from {unsubscribed_count} subscriptions and disconnected from server",
                total_processed=len(subscriptions_copy),
                successful_count=unsubscribed_count,
                failed_count=failed_count,
                successful=unsubscribed_list,
                failed=failed_list if failed_list else None,
                backend_cleared=True,
                server_disconnected=True,
                zmq_cleaned=True
            )

        except Exception as e:
            self.logger.error(f"Error in unsubscribe_all: {e}")
            return self._create_error_response("UNSUBSCRIBE_ALL_ERROR", str(e))

    def disconnect(self) -> None:
        """Disconnect from Groww WebSocket with proper cleanup"""
        self.logger.info("🔌 Starting Groww adapter disconnect sequence...")
        self.running = False

        try:
            # Disconnect WebSocket client
            if self.ws_client:
                try:
                    self.ws_client.disconnect()
                    self.logger.info("🔗 WebSocket client disconnected")
                except Exception as e:
                    self.logger.error(f"Error disconnecting WebSocket client: {e}")

            # Clear all state for clean reconnection
            self.connected = False
            self.ws_client = None
            self.subscriptions.clear()
            self.subscription_keys.clear()

            # Clean up ZeroMQ resources
            self.cleanup_zmq()

            self.logger.info("✅ Groww adapter disconnected and state cleared")

        except Exception as e:
            self.logger.error(f"❌ Error during disconnect: {e}")
            # Force cleanup even if there were errors
            self.connected = False
            self.ws_client = None
            self.subscriptions.clear()
            self.subscription_keys.clear()
            self.cleanup_zmq()
    
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with Groww-specific implementation
        
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Depth
            depth_level: Market depth level (only 5 supported for Groww)
            
        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate the mode
        if mode not in [1, 2, 3]:
            return self._create_error_response("INVALID_MODE", 
                                              f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)")
                                              
        # Groww only supports depth level 5
        if mode == 3 and depth_level != 5:
            self.logger.info(f"Groww only supports depth level 5, using 5 instead of {depth_level}")
            depth_level = 5
        
        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND",
                                              f"Symbol {symbol} not found for exchange {exchange}")

        token = token_info['token']
        brexchange = token_info['brexchange']

        # Get instrument type from database
        instrumenttype = None
        try:
            from database.symbol import SymToken
            sym = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
            if sym:
                instrumenttype = sym.instrumenttype
                self.logger.info(f"Retrieved instrumenttype: {instrumenttype} for {symbol}.{exchange}")
        except Exception as e:
            self.logger.warning(f"Could not retrieve instrumenttype: {e}")

        # For indices, handle token mapping differently
        if 'INDEX' in exchange.upper():
            if exchange == 'NSE_INDEX':
                # NSE indices use symbol names as tokens (NIFTY, BANKNIFTY, etc.)
                self.logger.info(f"NSE Index subscription detected, using symbol {symbol} as token instead of {token}")
                token = symbol
            elif exchange == 'BSE_INDEX':
                # BSE indices use numeric tokens (e.g., "14" for SENSEX)
                # Keep the original token from database
                self.logger.info(f"BSE Index subscription detected, keeping numeric token {token} for {symbol}")

        # Get exchange and segment for Groww
        groww_exchange, segment = GrowwExchangeMapper.get_exchange_segment(exchange)

        # Log token details for debugging F&O
        if exchange in ['NFO', 'BFO']:
            self.logger.info(f"F&O Subscription Debug:")
            self.logger.info(f"  Symbol: {symbol}")
            self.logger.info(f"  Exchange: {exchange} -> Groww: {groww_exchange}")
            self.logger.info(f"  Segment: {segment}")
            self.logger.info(f"  Token from DB: {token}")
            self.logger.info(f"  Brexchange: {brexchange}")
        
        # Generate unique correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"
        
        # Store subscription for reconnection
        with self.lock:
            self.subscriptions[correlation_id] = {
                'symbol': symbol,
                'exchange': exchange,
                'groww_exchange': groww_exchange,
                'segment': segment,
                'brexchange': brexchange,
                'token': token,
                'mode': mode,
                'depth_level': depth_level
            }
        
        # Subscribe if connected
        if self.connected and self.ws_client:
            try:
                if mode in [1, 2]:  # LTP or Quote mode
                    if mode == 2:
                        self.logger.info(f"📈 QUOTE subscription for {symbol} - Note: Groww only provides LTP, OHLCV will be 0")
                    sub_key = self.ws_client.subscribe_ltp(groww_exchange, segment, token, symbol, instrumenttype)
                elif mode == 3:  # Depth mode
                    # Check if this is an index - indices don't have depth data
                    if instrumenttype == 'INDEX' or 'INDEX' in exchange:
                        self.logger.warning(f"⚠️ Indices don't have depth data. Converting to LTP subscription for {symbol}")
                        # Subscribe to LTP instead for indices
                        sub_key = self.ws_client.subscribe_ltp(groww_exchange, segment, token, symbol, instrumenttype)
                        # Update the mode in subscription info for proper matching
                        self.subscriptions[correlation_id]['mode'] = 1  # Change to LTP mode
                    else:
                        # Enhanced logging for BSE depth subscriptions
                        if 'BSE' in groww_exchange:
                            self.logger.info(f"🔴 Creating BSE DEPTH subscription:")
                            self.logger.info(f"   Exchange: {groww_exchange}")
                            self.logger.info(f"   Segment: {segment}")
                            self.logger.info(f"   Token: {token}")
                            self.logger.info(f"   Symbol: {symbol}")

                        # Subscribe to depth for non-index instruments
                        sub_key = self.ws_client.subscribe_depth(groww_exchange, segment, token, symbol, instrumenttype)

                        if 'BSE' in groww_exchange:
                            self.logger.info(f"🔴 BSE DEPTH subscription key: {sub_key}")

                # Store subscription key for unsubscribe
                self.subscription_keys[correlation_id] = sub_key

                mode_name = {1: 'LTP', 2: 'Quote', 3: 'Depth'}.get(mode, str(mode))
                self.logger.info(f"✅ Subscribed to {symbol}.{exchange} in {mode_name} mode (key: {sub_key})")

                # Special logging for LTP subscriptions to debug subscribe all issue
                if mode == 1:
                    self.logger.info(f"🔥 LTP SUBSCRIPTION CONFIRMED: {exchange}:{symbol} - data should start flowing")

                # Extra logging for F&O
                if exchange in ['NFO', 'BFO']:
                    self.logger.info(f"F&O subscription key created: {sub_key}")
                
            except Exception as e:
                self.logger.error(f"Error subscribing to {symbol}.{exchange}: {e}")
                return self._create_error_response("SUBSCRIPTION_ERROR", str(e))
        
        mode_name = {1: 'LTP', 2: 'Quote', 3: 'Depth'}.get(mode, str(mode))
        return self._create_success_response(
            f'Successfully subscribed to {symbol}.{exchange} in {mode_name} mode',
            symbol=symbol,
            exchange=exchange,
            mode=mode,
            depth_level=depth_level
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
        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"
        
        # Check if subscribed
        with self.lock:
            if correlation_id not in self.subscriptions:
                return self._create_error_response("NOT_SUBSCRIBED", 
                                                  f"Not subscribed to {symbol}.{exchange}")
            
            # Remove from subscriptions
            del self.subscriptions[correlation_id]
        
        # Unsubscribe if we have a subscription key
        if correlation_id in self.subscription_keys:
            sub_key = self.subscription_keys[correlation_id]
            
            if self.connected and self.ws_client:
                try:
                    self.ws_client.unsubscribe(sub_key)
                    self.logger.info(f"Unsubscribed from {symbol}.{exchange}")
                except Exception as e:
                    self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                    
            del self.subscription_keys[correlation_id]
        
        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode
        )
    
    def _resubscribe(self, correlation_id: str, sub_info: Dict):
        """Resubscribe to a symbol after reconnection"""
        try:
            groww_exchange = sub_info['groww_exchange']
            segment = sub_info['segment']
            token = sub_info['token']
            mode = sub_info['mode']
            
            if mode in [1, 2]:  # LTP or Quote mode
                sub_key = self.ws_client.subscribe_ltp(groww_exchange, segment, token, sub_info['symbol'])
            elif mode == 3:  # Depth mode
                sub_key = self.ws_client.subscribe_depth(groww_exchange, segment, token, sub_info['symbol'])
                
            self.subscription_keys[correlation_id] = sub_key
            self.logger.info(f"Resubscribed to {sub_info['symbol']}.{sub_info['exchange']}")
            
        except Exception as e:
            self.logger.error(f"Error resubscribing: {e}")
    
    def _on_data(self, data: Dict[str, Any]) -> None:
        """Callback for market data from WebSocket"""
        try:
            # Enhanced logging for BSE depth data
            is_bse_depth = False
            if 'depth_data' in data and 'exchange' in data and 'BSE' in data.get('exchange', ''):
                is_bse_depth = True
                self.logger.info(f"🔴 BSE DEPTH DATA RECEIVED!")
                self.logger.info(f"   Depth data: {data.get('depth_data', {})}")

            # Debug log the raw message data to see what we're actually receiving
            self.logger.debug(f"RAW GROWW DATA{' (BSE DEPTH)' if is_bse_depth else ''}: Type: {type(data)}, Data: {data}")

            # Add data validation to ensure we have the minimum required fields
            if not isinstance(data, dict):
                self.logger.error(f"Invalid data type received: {type(data)}")
                return

            # Ensure we have either market data or subscription info
            has_market_data = any(key in data for key in ['ltp_data', 'depth_data', 'index_data'])
            has_subscription_info = all(key in data for key in ['symbol', 'exchange'])

            if not (has_market_data or has_subscription_info):
                self.logger.warning(f"Received data without market data or subscription info: {data}")
                return
            
            # Find matching subscription based on the data
            subscription = None
            correlation_id = None

            # Data from NATS will have symbol, exchange, and mode fields
            if 'symbol' in data and 'exchange' in data:
                # This is from our NATS implementation
                symbol_from_data = data['symbol']  # This contains the actual symbol name now
                exchange = data['exchange']
                mode = data.get('mode', 'ltp')

                # Handle both numeric and string mode values
                if isinstance(mode, int):
                    # Convert numeric mode to string
                    mode = {1: 'ltp', 2: 'quote', 3: 'depth'}.get(mode, 'ltp')
                elif isinstance(mode, str) and mode.isdigit():
                    # Convert string numeric to string mode
                    mode = {1: 'ltp', 2: 'quote', 3: 'depth'}.get(int(mode), 'ltp')

                # Special logging for BSE depth
                if 'BSE' in exchange and mode == 'depth':
                    self.logger.info(f"🔴 BSE DEPTH: Looking for subscription")

                self.logger.info(f"Looking for subscription: symbol={symbol_from_data}, exchange={exchange}, mode={mode}")
                self.logger.info(f"Available subscriptions: {list(self.subscriptions.keys())}")
                
                # Find matching subscription based on symbol, exchange and mode
                with self.lock:
                    for cid, sub in self.subscriptions.items():
                        self.logger.debug(f"Checking {cid}: symbol={sub.get('symbol')}, exchange={sub.get('exchange')}, groww_exchange={sub.get('groww_exchange')}, mode={sub.get('mode')}")
                        
                        # For index subscriptions, the OpenAlgo exchange is NSE_INDEX/BSE_INDEX but Groww sends NSE/BSE
                        # Check if this is an index subscription
                        is_index_match = ((mode == 'index' or mode == 'index_depth') and
                                        ((sub['exchange'] == 'NSE_INDEX' and exchange == 'NSE') or
                                         (sub['exchange'] == 'BSE_INDEX' and exchange == 'BSE')) and
                                        sub['symbol'] == symbol_from_data)

                        # Regular match based on symbol, exchange and mode
                        # CRITICAL: Match with the original exchange, not groww_exchange
                        # Data from NATS has exchange='NSE' which should match sub['exchange']='NSE'
                        is_regular_match = (sub['symbol'] == symbol_from_data and
                                          sub['exchange'] == exchange and
                                          ((mode == 'ltp' and sub['mode'] in [1, 2]) or
                                           (mode == 'depth' and sub['mode'] == 3) or
                                           (mode == 'index' and sub['mode'] in [1, 2]) or
                                           (mode == 'index_depth' and sub['mode'] == 3)))
                        
                        if is_index_match or is_regular_match:
                            subscription = sub
                            correlation_id = cid
                            self.logger.info(f"Matched subscription: {cid}")
                            break
            
            # Try to match based on exchange token from protobuf data
            elif 'exchange_token' in data or 'token' in data:
                token = data.get('exchange_token') or data.get('token')
                segment = data.get('segment', 'CASH')
                exchange = data.get('exchange', 'NSE')
                
                self.logger.info(f"Processing message with token: {token}, segment: {segment}, exchange: {exchange}")
                
                # Find matching subscription
                with self.lock:
                    for cid, sub in self.subscriptions.items():
                        if str(sub['token']) == str(token) and sub['segment'] == segment and sub['groww_exchange'] == exchange:
                            subscription = sub
                            correlation_id = cid
                            break
            
            if not subscription:
                # Enhanced logging for BSE depth debugging
                if 'BSE' in str(data) and 'depth' in str(data).lower():
                    self.logger.error(f"🔴 BSE DEPTH DATA RECEIVED BUT NO SUBSCRIPTION FOUND!")
                    self.logger.error(f"   Data: {data}")
                    self.logger.error(f"   Active subscriptions: {self.subscriptions}")
                self.logger.warning(f"Received data for unsubscribed token/symbol: {data}")
                return
            
            # Extract symbol and exchange from subscription
            symbol = subscription['symbol']
            # Always use the subscription's exchange for correct labeling (NSE_INDEX, BSE_INDEX, etc.)
            exchange = subscription['exchange']
            subscription_mode = subscription['mode']

            # CRITICAL FIX: Like Angel, use the actual data mode from the message if available
            # This ensures proper mode handling for all data types
            actual_mode = data.get('mode', subscription_mode)

            # If we have ltp_data, it's always LTP mode (mode 1)
            if 'ltp_data' in data:
                actual_mode = 1
            elif 'depth_data' in data:
                actual_mode = 3
            elif subscription_mode == 2:  # Quote mode
                actual_mode = 2

            # Important: Create topic in the same format as Angel using ACTUAL mode
            # Format: EXCHANGE_SYMBOL_MODE (without broker name, like Angel does)
            mode_str = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}[actual_mode]
            topic = f"{exchange}_{symbol}_{mode_str}"

            # Normalize the data using actual mode
            market_data = self._normalize_market_data(data, actual_mode)

            # Add metadata - ensure all required fields for frontend
            market_data.update({
                'symbol': symbol,
                'exchange': exchange,
                'mode': actual_mode,  # Use actual mode, not subscription mode
                'timestamp': int(time.time() * 1000),
                'broker': 'groww',  # Add broker identifier
                'topic': topic,      # Add topic for debugging
                'subscription_mode': subscription_mode  # Keep original subscription mode for reference
            })

            # Add mode-specific enhancements for frontend compatibility
            if actual_mode == 1:  # LTP mode
                # Ensure we have a valid LTP value - CRITICAL for frontend display
                if 'ltp' not in market_data or market_data['ltp'] is None or market_data['ltp'] == 0:
                    # Try to get LTP from different possible fields
                    ltp_value = (
                        market_data.get('ltp') or
                        market_data.get('last_price') or
                        market_data.get('last_traded_price') or
                        data.get('ltp_data', {}).get('ltp') if 'ltp_data' in data else None or
                        data.get('ltp') or
                        0.0
                    )
                    market_data['ltp'] = float(ltp_value) if ltp_value else 0.0

                    if market_data['ltp'] == 0:
                        self.logger.warning(f"⚠️ NO VALID LTP DATA for {symbol}, check data source")
                    else:
                        self.logger.info(f"📈 LTP recovered for {symbol}: {market_data['ltp']}")

                # Ensure LTP timestamp
                if 'ltt' not in market_data:
                    market_data['ltt'] = int(time.time() * 1000)

                # Log LTP data for debugging subscribe all issue
                self.logger.info(f"🔍 LTP MODE: {exchange}:{symbol} = ₹{market_data['ltp']} at {market_data.get('ltt')}")

            elif actual_mode == 2:  # Quote mode
                # Ensure all quote fields are present for frontend
                quote_fields = ['open', 'high', 'low', 'close', 'volume', 'ltp']
                for field in quote_fields:
                    if field not in market_data:
                        market_data[field] = 0.0 if field != 'volume' else 0

                # Ensure LTP is also available in quote mode
                if 'ltp' not in market_data or market_data['ltp'] is None:
                    ltp_value = (
                        data.get('ltp_data', {}).get('ltp') if 'ltp_data' in data else None or
                        data.get('ltp') or
                        0.0
                    )
                    market_data['ltp'] = float(ltp_value) if ltp_value else 0.0

                # Log Quote data
                self.logger.info(f"🔍 QUOTE MODE: {exchange}:{symbol} = ₹{market_data['ltp']} (Vol: {market_data.get('volume', 0)})")

            elif actual_mode == 3:  # Depth mode
                # Ensure depth structure is complete
                if 'depth' not in market_data:
                    market_data['depth'] = {'buy': [], 'sell': []}
                    self.logger.warning(f"No depth data for {symbol}, creating empty structure")

                # Also ensure LTP is available in depth mode
                if 'ltp' not in market_data:
                    market_data['ltp'] = 0.0

                # Log Depth data
                buy_levels = len(market_data['depth'].get('buy', []))
                sell_levels = len(market_data['depth'].get('sell', []))
                self.logger.info(f"🔍 DEPTH MODE: {exchange}:{symbol} = {buy_levels}B/{sell_levels}S levels")

            # Enhanced logging for BSE depth
            if 'BSE' in exchange and mode == 3:
                self.logger.info(f"🔴 Publishing BSE DEPTH data for {symbol}")
                if 'depth' in market_data:
                    self.logger.info(f"   Buy levels: {len(market_data['depth'].get('buy', []))}")
                    self.logger.info(f"   Sell levels: {len(market_data['depth'].get('sell', []))}")

            # Periodic logging instead of every message (reduces noise) - but more frequent for debugging
            if not hasattr(self, '_message_count'):
                self._message_count = 0
            self._message_count += 1

            # More frequent logging for debugging LTP issue
            if self._message_count <= 20 or self._message_count % 25 == 0:
                mode_name = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}[actual_mode]
                ltp_info = f"LTP: ₹{market_data.get('ltp', 'N/A')}" if actual_mode in [1, 2] else f"Depth: {len(market_data.get('depth', {}).get('buy', []))}B/{len(market_data.get('depth', {}).get('sell', []))}S"
                self.logger.info(f"📈 Publishing #{self._message_count}: {topic} ({mode_name}) -> {ltp_info}")

            # CRITICAL: Always log LTP mode data to debug subscribe all issue
            if actual_mode == 1:
                self.logger.info(f"🚨 LTP PUBLISH: {topic} -> ₹{market_data.get('ltp')} (Message #{self._message_count})")

            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)

            # Log successful publication for debugging data flow issues
            self.logger.debug(f"✅ ZMQ Published: {topic} with {len(str(market_data))} bytes")

            # Verify publication by checking if we can access the data
            if actual_mode == 1 and market_data.get('ltp', 0) > 0:
                self.logger.info(f"✅ LTP DATA VERIFIED: {exchange}:{symbol} = ₹{market_data['ltp']} published successfully")
            
        except Exception as e:
            self.logger.error(f"Error processing market data: {e}", exc_info=True)
    
    def _on_error(self, error: str) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"Groww WebSocket error: {error}")
    
    def _normalize_market_data(self, message: Dict, mode: int) -> Dict[str, Any]:
        """
        Normalize Groww data format to a common format
        
        Args:
            message: The raw message from Groww
            mode: Subscription mode
            
        Returns:
            Dict: Normalized market data
        """
        # Handle data from our NATS/protobuf parser
        if 'ltp_data' in message:
            # This is parsed protobuf data from our NATS implementation
            ltp_data = message['ltp_data']
            
            if mode == 1:  # LTP mode
                return {
                    'ltp': ltp_data.get('ltp', 0),
                    'ltt': ltp_data.get('timestamp', int(time.time() * 1000))
                }
            elif mode == 2:  # Quote mode
                # Groww doesn't provide proper quote data, only LTP
                # Only include fields that have actual data
                quote_data = {
                    'ltp': ltp_data.get('ltp', 0),
                    'ltt': ltp_data.get('timestamp', int(time.time() * 1000))
                }

                # Only add OHLCV fields if they have non-zero values from Groww
                # (Groww sometimes sends these as 0, we don't include them)
                if ltp_data.get('open') and ltp_data.get('open') != 0:
                    quote_data['open'] = ltp_data.get('open')
                if ltp_data.get('high') and ltp_data.get('high') != 0:
                    quote_data['high'] = ltp_data.get('high')
                if ltp_data.get('low') and ltp_data.get('low') != 0:
                    quote_data['low'] = ltp_data.get('low')
                if ltp_data.get('close') and ltp_data.get('close') != 0:
                    quote_data['close'] = ltp_data.get('close')
                if ltp_data.get('volume') and ltp_data.get('volume') != 0:
                    quote_data['volume'] = ltp_data.get('volume')
                if ltp_data.get('value') and ltp_data.get('value') != 0:
                    quote_data['value'] = ltp_data.get('value')

                return quote_data
            else:
                # Fallback for other modes
                return {
                    'ltp': ltp_data.get('ltp', 0),
                    'ltt': ltp_data.get('timestamp', int(time.time() * 1000)),
                    'open': ltp_data.get('open', 0),
                    'high': ltp_data.get('high', 0),
                    'low': ltp_data.get('low', 0),
                    'close': ltp_data.get('close', 0),
                    'volume': ltp_data.get('volume', 0)
                }
        
        # Handle depth data from protobuf
        if 'depth_data' in message:
            depth_data = message['depth_data']
            result = {
                'ltp': 0,  # Will be filled from ltp_data if available
                'ltt': depth_data.get('timestamp', int(time.time() * 1000)),
                'volume': 0,
                'open': 0,
                'high': 0,
                'low': 0,
                'close': 0
            }
            
            # Add depth data in the same format as Angel
            result['depth'] = {
                'buy': [],
                'sell': []
            }
            
            # Extract buy levels
            buy_levels = depth_data.get('buy', [])
            for i in range(5):  # Groww supports 5 levels
                if i < len(buy_levels):
                    result['depth']['buy'].append(buy_levels[i])
                else:
                    result['depth']['buy'].append({
                        'price': 0.0,
                        'quantity': 0,
                        'orders': 0
                    })
            
            # Extract sell levels
            sell_levels = depth_data.get('sell', [])
            for i in range(5):  # Groww supports 5 levels
                if i < len(sell_levels):
                    result['depth']['sell'].append(sell_levels[i])
                else:
                    result['depth']['sell'].append({
                        'price': 0.0,
                        'quantity': 0,
                        'orders': 0
                    })
            
            return result
        
        # Handle index data from protobuf  
        if 'index_data' in message:
            index_data = message['index_data']
            return {
                'ltp': index_data.get('value', 0),
                'ltt': index_data.get('timestamp', int(time.time() * 1000))
            }
        
        # Handle legacy formats
        # Check if it's LTP data
        if 'ltp' in message:
            ltp_data = message.get('ltp', {})
            
            # Extract values from nested structure if present
            if isinstance(ltp_data, dict):
                # Format: {"NSE": {"CASH": {"token": {"tsInMillis": ..., "ltp": ...}}}}
                for exchange_data in ltp_data.values():
                    if isinstance(exchange_data, dict):
                        for segment_data in exchange_data.values():
                            if isinstance(segment_data, dict):
                                for token_data in segment_data.values():
                                    if isinstance(token_data, dict):
                                        return {
                                            'ltp': token_data.get('ltp', 0),
                                            'ltt': token_data.get('tsInMillis', int(time.time() * 1000))
                                        }
            else:
                # Direct format
                return {
                    'ltp': ltp_data,
                    'ltt': message.get('tsInMillis', int(time.time() * 1000))
                }
        
        # Check if it's depth/market depth data
        if 'buyBook' in message or 'sellBook' in message:
            result = {
                'ltp': message.get('ltp', 0),
                'ltt': message.get('tsInMillis', int(time.time() * 1000)),
                'depth': {
                    'buy': [],
                    'sell': []
                }
            }
            
            # Extract buy book
            buy_book = message.get('buyBook', {})
            for i in range(1, 6):  # Groww uses 1-5 indexing
                level = buy_book.get(str(i), {})
                result['depth']['buy'].append({
                    'price': level.get('price', 0),
                    'quantity': level.get('qty', 0),
                    'orders': level.get('orders', 0)
                })
            
            # Extract sell book
            sell_book = message.get('sellBook', {})
            for i in range(1, 6):  # Groww uses 1-5 indexing
                level = sell_book.get(str(i), {})
                result['depth']['sell'].append({
                    'price': level.get('price', 0),
                    'quantity': level.get('qty', 0),
                    'orders': level.get('orders', 0)
                })
            
            return result
        
        # Default format for quote/other data
        return {
            'ltp': message.get('ltp', message.get('last_price', 0)),
            'ltt': message.get('tsInMillis', message.get('timestamp', int(time.time() * 1000))),
            'volume': message.get('volume', 0),
            'open': message.get('open', 0),
            'high': message.get('high', 0),
            'low': message.get('low', 0),
            'close': message.get('close', 0)
        }