"""
High-level, AliceBlue-style adapter for Kotak broker WebSocket streaming.
Each instance is fully isolated and safe for multi-client use.
"""
import threading
import time
import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from .kotak_websocket import KotakWebSocket
from database.auth_db import get_auth_token
from utils.logging import get_logger

logger = get_logger(__name__)

class KotakWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    Adapter for Kotak WebSocket streaming, suitable for OpenAlgo or similar frameworks.
    Each instance is isolated and manages its own KotakWebSocket client.
    """
    def __init__(self):
        super().__init__()  # ← Initialize base adapter (sets up ZMQ)
        self._ws_client = None
        self._user_id = None
        self._broker_name = "kotak"
        self._auth_config = None
        self._connected = False
        self._lock = threading.RLock()
        
        # Cache structures - following AliceBlue pattern exactly
        self._ltp_cache = {}  # {(exchange, symbol): ltp_value}
        self._quote_cache = {}  # {(exchange, symbol): full_quote_dict}
        self._depth_cache = {}  # {(exchange, symbol): depth_dict}
        self._symbol_state = {}  # Store last known state for each symbol
        
        # Mapping from Kotak format to OpenAlgo format - critical for data flow
        self._kotak_to_openalgo = {}  # {(kotak_exchange, token): (exchange, symbol)}
        
        # Track active subscription modes per symbol - CRITICAL FOR MULTI-CLIENT SUPPORT
        self._symbol_modes = {}  # {(kotak_exchange, token): set of active modes}

    def initialize(self, broker_name: str, user_id: str, auth_data=None):
        """Initialize adapter for a specific user/session - following AliceBlue pattern."""
        self._broker_name = broker_name.lower()
        self._user_id = user_id
        
        # Load authentication from DB
        auth_string = get_auth_token(user_id)
        if not auth_string:
            logger.error(f"No authentication token found for user {user_id}")
            raise ValueError(f"No authentication token found for user {user_id}")
        
        auth_parts = auth_string.split(":::")
        if len(auth_parts) != 4:
            logger.error("Invalid authentication token format")
            raise ValueError("Invalid authentication token format")
        
        self._auth_config = dict(zip(['auth_token', 'sid', 'hs_server_id', 'access_token'], auth_parts))
        
        # Create websocket client
        self._ws_client = KotakWebSocket(self._auth_config)
        
        # Set up internal callbacks - this MUST happen during initialization like AliceBlue
        self._setup_internal_callbacks()
        
        logger.debug(f"Initialized KotakWebSocketAdapter for user {user_id}")

    def _setup_internal_callbacks(self):
        """Setup internal callbacks - following AliceBlue's _on_data_received pattern."""
        def on_quote_internal(quote):
            """Internal callback - mirrors AliceBlue's _on_data_received method."""
            try:
                logger.debug(f"Internal quote callback received: {quote}")
                # Use the same pattern as AliceBlue's _on_data_received
                self._on_data_received(quote)
            except Exception as e:
                logger.error(f"Error in internal quote handler: {e}")

        def on_depth_internal(depth):
            """Internal callback for depth data."""
            try:
                logger.debug(f"Internal depth callback received: {depth}")
                self._on_data_received(depth)
            except Exception as e:
                logger.error(f"Error in internal depth handler: {e}")

        # Set callbacks on the websocket client - this is crucial
        if self._ws_client:
            logger.debug("Setting up internal callbacks on KotakWebSocket client")
            self._ws_client.set_callbacks(
                on_quote=on_quote_internal,
                on_depth=on_depth_internal
            )

    def _on_data_received(self, parsed_data):
        """Handle received and parsed market data - FIXED for partial updates like AliceBlue."""
        try:
            logger.debug(f"Data received: {parsed_data}")

            # --- FIX: Handle list of dicts (multi-script update) ---
            if isinstance(parsed_data, list):
                for item in parsed_data:
                    self._on_data_received(item)
                return
            
            # Extract key identifiers - following AliceBlue pattern
            token = str(parsed_data.get('tk', ''))
            broker_exchange = parsed_data.get('e', 'UNKNOWN')
            ltp = parsed_data.get('ltp')
            
            # **CRITICAL FIX**: Check if this is depth data (has bids/asks) or LTP data
            has_depth_data = 'bids' in parsed_data and 'asks' in parsed_data
            has_ltp_data = ltp and float(ltp) > 0
            
            # Create symbol key - following AliceBlue pattern
            symbol_key = f"{broker_exchange}|{token}"
            
            with self._lock:
                # Check if this is a partial update by detecting missing expected fields
                is_partial_update = self._is_partial_update(parsed_data)

                # --- CRITICAL: If partial update and no previous state, initialize state ---
                if is_partial_update and symbol_key not in self._symbol_state:
                    logger.debug(f"Initializing state for partial update: {symbol_key}")
                    # Create initial state with proper default values
                    initial_state = {
                        'tk': parsed_data.get('tk', ''),
                        'e': parsed_data.get('e', ''),
                        'ts': parsed_data.get('ts', ''),
                        'ltp': 0.0,
                        'open': 0.0,
                        'high': 0.0,
                        'low': 0.0,
                        'prev_close': 0.0,
                        'volume': 0.0,
                        'bid': 0.0,
                        'ask': 0.0,
                        'bids': [],
                        'asks': []
                    }
                    
                    # **CRITICAL**: Copy any non-zero/non-empty values from the partial update
                    for key, value in parsed_data.items():
                        if key in initial_state:
                            # Don't overwrite with zero values for price fields
                            if key in ['open', 'high', 'low', 'prev_close', 'bid', 'ask']:
                                if value != 0.0 and value != 21474836.48:  # Kotak's invalid value
                                    initial_state[key] = value
                            elif key in ['ltp']:
                                # **CRITICAL FIX**: Only update LTP if it's a valid positive value
                                if value and float(value) > 0:
                                    initial_state[key] = value
                            elif key in ['volume']:
                                if value != 0.0 and value != 2147483648:  # Kotak's invalid volume
                                    initial_state[key] = value
                            elif key in ['ts']:
                                if value:  # Non-empty symbol name
                                    initial_state[key] = value
                            else:
                                initial_state[key] = value
                    
                    self._symbol_state[symbol_key] = initial_state

                # --- CRITICAL: Merge depth levels per level, not just per side ---
                if has_depth_data:
                    prev_state = self._symbol_state.get(symbol_key, {})
                    prev_bids = prev_state.get('bids', []) if prev_state else []
                    prev_asks = prev_state.get('asks', []) if prev_state else []
                    new_bids = parsed_data.get('bids', [])
                    new_asks = parsed_data.get('asks', [])
                    merged_bids = []
                    merged_asks = []
                    for i in range(5):
                        # --- BUY SIDE ---
                        if i < len(new_bids):
                            b = new_bids[i]
                            prev_b = prev_bids[i] if i < len(prev_bids) else {'price': 0, 'quantity': 0, 'orders': 0}
                            merged_bids.append({
                                'price': b.get('price', 0) if b.get('price', 0) != 0 else prev_b.get('price', 0),
                                'quantity': b.get('quantity', 0) if b.get('quantity', 0) != 0 else prev_b.get('quantity', 0),
                                'orders': b.get('orders', 0) if b.get('orders', 0) != 0 else prev_b.get('orders', 0),
                            })
                        elif i < len(prev_bids):
                            merged_bids.append(prev_bids[i])
                        else:
                            merged_bids.append({'price': 0, 'quantity': 0, 'orders': 0})

                        # --- SELL SIDE ---
                        if i < len(new_asks):
                            a = new_asks[i]
                            prev_a = prev_asks[i] if i < len(prev_asks) else {'price': 0, 'quantity': 0, 'orders': 0}
                            merged_asks.append({
                                'price': a.get('price', 0) if a.get('price', 0) != 0 else prev_a.get('price', 0),
                                'quantity': a.get('quantity', 0) if a.get('quantity', 0) != 0 else prev_a.get('quantity', 0),
                                'orders': a.get('orders', 0) if a.get('orders', 0) != 0 else prev_a.get('orders', 0),
                            })
                        elif i < len(prev_asks):
                            merged_asks.append(prev_asks[i])
                        else:
                            merged_asks.append({'price': 0, 'quantity': 0, 'orders': 0})
                    # Update parsed_data with merged depth
                    parsed_data['bids'] = merged_bids
                    parsed_data['asks'] = merged_asks

                # **CRITICAL FIX FOR PARTIAL UPDATES**: Implement AliceBlue-style state merging
                if is_partial_update and symbol_key in self._symbol_state:
                    logger.debug(f"Partial update detected for {symbol_key}")
                    merged_data = self._symbol_state[symbol_key].copy()
                    for key, value in parsed_data.items():
                        if key not in ['tk', 'e']:
                            # **CRITICAL FIX**: Add 'ltp' to protected price fields
                            if key in ['open', 'high', 'low', 'prev_close', 'bid', 'ask', 'ltp'] and value == 0.0:
                                continue  # Skip zero values for all price fields including LTP
                            elif key == 'ltp':
                                # **ENHANCED FIX**: Additional LTP validation
                                if value and float(value) > 0:
                                    merged_data[key] = value
                                # If LTP is 0 or invalid, skip updating (preserve previous value)
                                continue
                            elif key == 'volume' and value == 0.0:
                                continue
                            elif key == 'ts' and not value:
                                continue
                            else:
                                merged_data[key] = value
                        else:
                            merged_data[key] = value
                    parsed_data = merged_data
                    logger.debug(f"Merged data: {dict((k, v) for k, v in parsed_data.items() if k not in ['tk'])}")
                    ltp = parsed_data.get('ltp')
                    has_depth_data = 'bids' in parsed_data and 'asks' in parsed_data
                    has_ltp_data = ltp and float(ltp) > 0

                # Store the complete data (either original complete data or merged data)
                # --- CRITICAL: Store per-symbol state, including merged bids/asks for this symbol only ---
                self._symbol_state[symbol_key] = {
                    **parsed_data,
                    'bids': parsed_data.get('bids', []),
                    'asks': parsed_data.get('asks', [])
                }
                
                # Skip if neither LTP nor depth data is present (after merging)
                if not has_ltp_data and not has_depth_data:
                    logger.debug("No LTP or depth data after merging")
                    return
                
                # Find the original subscription mapping - critical step
                mapping_key = (broker_exchange, token)
                if mapping_key in self._kotak_to_openalgo:
                    exchange, symbol = self._kotak_to_openalgo[mapping_key]
                    cache_key = (exchange, symbol)
                    
                    # For LTP data, update LTP cache
                    if has_ltp_data:
                        self._ltp_cache[cache_key] = float(ltp)
                    
                    # For depth data, update depth cache
                    if has_depth_data:
                        depth_data = {
                            'buy': parsed_data.get('bids', []),
                            'sell': parsed_data.get('asks', []),
                            'totalbuyqty': parsed_data.get('totalbuyqty', 0),
                            'totalsellqty': parsed_data.get('totalsellqty', 0),
                            'ltp': float(ltp) if has_ltp_data else 0.0
                        }
                        self._depth_cache[cache_key] = depth_data
                    
                    # Always update quote cache with complete merged data
                    self._quote_cache[cache_key] = parsed_data.copy()
                    
                    # **CRITICAL FIX**: Publish data for ALL active modes for this symbol
                    active_modes = self._symbol_modes.get(mapping_key, set())
                    
                    for mode in active_modes:
                        mode_map = {1: 'LTP', 2: 'QUOTE', 3: 'DEPTH'}
                        mode_str = mode_map.get(mode, 'LTP')
                        topic = f"{exchange}_{symbol}_{mode_str}"
                        if mode == 1 and has_ltp_data:
                            publish_data = {
                                'ltp': float(ltp),
                                'ltt': parsed_data.get('timestamp', int(time.time() * 1000))
                            }
                        elif mode == 2:
                            publish_data = {
                                'ltp': float(ltp) if has_ltp_data else 0.0,
                                'ltt': parsed_data.get('timestamp', int(time.time() * 1000)),
                                'volume': parsed_data.get('volume', 0),
                                'open': parsed_data.get('open', 0.0),
                                'high': parsed_data.get('high', 0.0),
                                'low': parsed_data.get('low', 0.0),
                                'close': parsed_data.get('prev_close', 0.0)
                            }
                        elif mode == 3 and has_depth_data:
                            publish_data = {
                                'ltp': float(ltp) if has_ltp_data else 0.0,
                                'timestamp': int(time.time() * 1000),
                                'depth': {
                                    'buy': parsed_data.get('bids', []),
                                    'sell': parsed_data.get('asks', [])
                                },
                                'totalbuyqty': parsed_data.get('totalbuyqty', 0),
                                'totalsellqty': parsed_data.get('totalsellqty', 0)
                            }
                        else:
                            continue
                        publish_data.update({
                            'symbol': symbol,
                            'exchange': exchange,
                            'timestamp': int(time.time() * 1000)
                        })
                        logger.debug(f"Publishing to ZMQ topic: {topic}")
                        self.publish_market_data(topic, publish_data)
                    
                    if has_ltp_data:
                        logger.debug(f"Updated LTP cache: {exchange}:{symbol} = {ltp}")
                    if has_depth_data:
                        logger.debug(f"Updated depth cache: {exchange}:{symbol}")
                else:
                    logger.debug(f"No mapping found for {mapping_key}")
        except Exception as e:
            logger.error(f"Error processing received data: {e}")

            
    def _is_partial_update(self, parsed_data):
        """
        Determine if this is a partial update based on missing expected fields.
        Less aggressive detection to avoid skipping valid updates.
        """
        # If we have LTP and symbol name, treat as valid update
        ltp = parsed_data.get('ltp', 0.0)
        symbol_name = parsed_data.get('ts', '')
        
        if ltp and float(ltp) > 0 and symbol_name:
            return False  # Complete enough to process
        
        # Check for quote mode partial updates
        quote_fields = ['open', 'high', 'low', 'prev_close']
        has_quote_fields = any(field in parsed_data and parsed_data[field] != 0.0 
                            for field in quote_fields)
        
        if not has_quote_fields and not symbol_name:
            return True  # Definitely partial
        
        return False  # Default to processing the update


    def connect(self):
        """Connect to WebSocket - following AliceBlue pattern."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized. Call initialize() first.")
            return
        
        try:
            self._ws_client.connect()
            self._connected = True
            logger.debug("Kotak WebSocket connected successfully")
        except Exception as e:
            logger.error(f"Error connecting to Kotak WebSocket: {e}")
            self._connected = False

    def disconnect(self):
        """Disconnect from WebSocket."""
        try:
            if self._ws_client:
                self._ws_client.close()
            self._connected = False
            
            # Clean up ZeroMQ resources - CRITICAL for multi-instance support
            self.cleanup_zmq()
            
            logger.debug("Kotak WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error disconnecting from Kotak WebSocket: {e}")

    def subscribe(self, symbol, exchange, mode, depth_level=0):
        """Subscribe to a symbol - FIXED for multi-client support."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized.")
            return self._create_error_response("NOT_INITIALIZED", "WebSocket client not initialized.")
        
        try:
            logger.debug(f"Subscribing to {exchange}:{symbol} with mode {mode}")
            
            if mode in (1, 2):
                # Quote/LTP subscription
                success = self.subscribe_quote(exchange, symbol, mode)
            elif mode == 3:
                # Depth subscription
                success = self.subscribe_depth(exchange, symbol, mode)
            else:
                logger.error(f"Unknown subscribe mode: {mode}")
                return self._create_error_response("INVALID_MODE", f"Unknown subscribe mode: {mode}")
            
            if success:
                # Track subscription - following AliceBlue pattern with detailed tracking
                sub_key = f"{exchange}|{symbol}|{mode}"
                with self._lock:
                    self.subscriptions[sub_key] = {
                        'symbol': symbol,
                        'exchange': exchange,
                        'mode': mode,
                        'depth_level': depth_level
                    }
                return self._create_success_response(f"Subscribed to {exchange}:{symbol} mode {mode}")
            else:
                return self._create_error_response("SUBSCRIPTION_FAILED", f"Failed to subscribe to {exchange}:{symbol}")
                
        except Exception as e:
            logger.error(f"Error in subscribe: {e}")
            return self._create_error_response("SUBSCRIPTION_ERROR", f"Error subscribing: {str(e)}")

    def unsubscribe(self, symbol, exchange, mode):
        """Unsubscribe from a symbol - FIXED for multi-client support."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized.")
            return self._create_error_response("NOT_INITIALIZED", "WebSocket client not initialized.")
        
        try:
            logger.debug(f"Unsubscribing from {exchange}:{symbol} with mode {mode}")
            
            if mode in (1, 2):
                self.unsubscribe_quote(exchange, symbol, mode)
            elif mode == 3:
                self.unsubscribe_depth(exchange, symbol, mode)
            
            # Clean up tracking and cache - following AliceBlue pattern
            sub_key = f"{exchange}|{symbol}|{mode}"
            with self._lock:
                self.subscriptions.pop(sub_key, None)
                
                # Only clean up caches if NO modes are active for this symbol
                from broker.kotak.streaming.kotak_mapping import get_kotak_exchange
                from database.token_db import get_token
                
                kotak_exchange = get_kotak_exchange(exchange)
                token = get_token(symbol, exchange)
                mapping_key = (kotak_exchange, str(token))
                
                if mapping_key in self._symbol_modes:
                    active_modes = self._symbol_modes[mapping_key]
                    if not active_modes:  # No active modes left
                        cache_key = (exchange, symbol)
                        self._ltp_cache.pop(cache_key, None)
                        self._quote_cache.pop(cache_key, None)
                        self._depth_cache.pop(cache_key, None)
                
            return self._create_success_response(f"Unsubscribed from {exchange}:{symbol}")
            
        except Exception as e:
            logger.error(f"Error in unsubscribe: {e}")
            return self._create_error_response("UNSUBSCRIPTION_ERROR", f"Error unsubscribing: {str(e)}")

    def subscribe_quote(self, exchange, symbol, mode):
        """Subscribe to quote (LTP) - FIXED for multi-client support."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized.")
            return False
        
        try:
            from broker.kotak.streaming.kotak_mapping import get_kotak_exchange
            from database.token_db import get_token
            
            kotak_exchange = get_kotak_exchange(exchange)
            token = get_token(symbol, exchange)
            
            if not token:
                logger.error(f"No token found for {symbol} on {exchange}")
                return False
            
            logger.debug(f"Mapping: {exchange}:{symbol} -> {kotak_exchange}:{token}")
            
            # Store mapping and track mode - CRITICAL FOR MULTI-CLIENT SUPPORT
            with self._lock:
                mapping_key = (kotak_exchange, str(token))
                self._kotak_to_openalgo[mapping_key] = (exchange, symbol)
                
                # Track active modes for this symbol
                if mapping_key not in self._symbol_modes:
                    self._symbol_modes[mapping_key] = set()
                self._symbol_modes[mapping_key].add(mode)
                
                logger.debug(f"Stored mapping: {mapping_key} -> ({exchange}, {symbol})")
                logger.debug(f"Active modes for {mapping_key}: {self._symbol_modes[mapping_key]}")
            
            # Subscribe using Kotak's market watch streaming
            self._ws_client.subscribe(kotak_exchange, token, sub_type="mws")
            logger.debug(f"Subscribed to quote: {exchange}:{symbol} (kotak: {kotak_exchange}|{token})")
            return True
            
        except Exception as e:
            logger.error(f"Error subscribing to quote for {exchange}:{symbol}: {e}")
            return False

    def unsubscribe_quote(self, exchange, symbol, mode):
        """Unsubscribe from quote - FIXED for multi-client support."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized.")
            return
        
        try:
            from broker.kotak.streaming.kotak_mapping import get_kotak_exchange
            from database.token_db import get_token
            
            kotak_exchange = get_kotak_exchange(exchange)
            token = get_token(symbol, exchange)
            
            if not token:
                logger.error(f"No token found for {symbol} on {exchange}")
                return
            
            # **CRITICAL FIX**: Only unsubscribe from broker if no other modes are active
            with self._lock:
                mapping_key = (kotak_exchange, str(token))
                
                # Remove this mode from active modes
                if mapping_key in self._symbol_modes:
                    self._symbol_modes[mapping_key].discard(mode)
                    
                    # Only unsubscribe from broker if no LTP/QUOTE modes are active
                    ltp_quote_modes = {1, 2}
                    active_ltp_quote_modes = self._symbol_modes[mapping_key] & ltp_quote_modes
                    
                    if not active_ltp_quote_modes:
                        # No more LTP/QUOTE modes active, unsubscribe from broker
                        self._ws_client.unsubscribe(kotak_exchange, token, sub_type="mwu")
                        logger.debug(f"Unsubscribed from broker: {exchange}:{symbol}")
                    
                    # Clean up mapping only if NO modes are active
                    if not self._symbol_modes[mapping_key]:
                        self._kotak_to_openalgo.pop(mapping_key, None)
                        self._symbol_modes.pop(mapping_key, None)
                        logger.debug(f"Cleaned up mapping for: {exchange}:{symbol}")
            
        except Exception as e:
            logger.error(f"Error unsubscribing from quote for {exchange}:{symbol}: {e}")

    def subscribe_depth(self, exchange, symbol, mode):
        """Subscribe to market depth - FIXED for multi-client support."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized.")
            return False
        
        try:
            from broker.kotak.streaming.kotak_mapping import get_kotak_exchange
            from database.token_db import get_token
            
            kotak_exchange = get_kotak_exchange(exchange)
            token = get_token(symbol, exchange)
            
            if not token:
                logger.error(f"No token found for {symbol} on {exchange}")
                return False
            
            # Store mapping and track mode
            with self._lock:
                mapping_key = (kotak_exchange, str(token))
                self._kotak_to_openalgo[mapping_key] = (exchange, symbol)
                
                # Track active modes for this symbol
                if mapping_key not in self._symbol_modes:
                    self._symbol_modes[mapping_key] = set()
                self._symbol_modes[mapping_key].add(mode)
            
            self._ws_client.subscribe(kotak_exchange, token, sub_type="dps")
            logger.debug(f"Subscribed to depth: {exchange}:{symbol} (kotak: {kotak_exchange}|{token})")
            return True
            
        except Exception as e:
            logger.error(f"Error subscribing to depth for {exchange}:{symbol}: {e}")
            return False

    def unsubscribe_depth(self, exchange, symbol, mode):
        """Unsubscribe from market depth - FIXED for multi-client support."""
        if not self._ws_client:
            logger.error("WebSocket client not initialized.")
            return
        
        try:
            from broker.kotak.streaming.kotak_mapping import get_kotak_exchange
            from database.token_db import get_token
            
            kotak_exchange = get_kotak_exchange(exchange)
            token = get_token(symbol, exchange)
            
            if not token:
                logger.error(f"No token found for {symbol} on {exchange}")
                return
            
            # **CRITICAL FIX**: Only unsubscribe from broker if no other modes are active
            with self._lock:
                mapping_key = (kotak_exchange, str(token))
                
                # Remove this mode from active modes
                if mapping_key in self._symbol_modes:
                    self._symbol_modes[mapping_key].discard(mode)
                    
                    # Only unsubscribe from broker if no DEPTH modes are active
                    if 3 not in self._symbol_modes[mapping_key]:
                        # No more DEPTH modes active, unsubscribe from broker
                        self._ws_client.unsubscribe(kotak_exchange, token, sub_type="dpu")
                        logger.debug(f"Unsubscribed from broker depth: {exchange}:{symbol}")
                    
                    # Clean up mapping only if NO modes are active
                    if not self._symbol_modes[mapping_key]:
                        self._kotak_to_openalgo.pop(mapping_key, None)
                        self._symbol_modes.pop(mapping_key, None)
                        logger.debug(f"Cleaned up mapping for: {exchange}:{symbol}")
            
        except Exception as e:
            logger.error(f"Error unsubscribing from depth for {exchange}:{symbol}: {e}")

    def get_ltp(self):
        """Return LTP data in the format expected by the WebSocket server."""
        with self._lock:
            # Create the expected nested format that matches AliceBlue/Angel response
            ltp_dict = {}
            
            # Convert cache format to client-expected nested format
            for (exchange, symbol), ltp_value in self._ltp_cache.items():
                if exchange not in ltp_dict:
                    ltp_dict[exchange] = {}
                
                ltp_dict[exchange][symbol] = {
                    'ltp': ltp_value,
                    'timestamp': int(time.time() * 1000)
                }
            
            logger.debug(f"get_ltp returning: {ltp_dict}")
            return ltp_dict  # Return nested dict format

    def get_quote(self):
        """Return quote data in the format expected by the WebSocket server."""
        with self._lock:
            quote_dict = {}
            
            # Convert quote cache to client-expected nested format
            for (exchange, symbol), quote_data in self._quote_cache.items():
                if exchange not in quote_dict:
                    quote_dict[exchange] = {}
                
                # Build complete quote data from cached state
                quote_dict[exchange][symbol] = {
                    'timestamp': int(time.time() * 1000),
                    'ltp': quote_data.get('ltp', 0.0),
                    'open': quote_data.get('open', 0.0),
                    'high': quote_data.get('high', 0.0),
                    'low': quote_data.get('low', 0.0),
                    'close': quote_data.get('prev_close', 0.0),
                    'volume': quote_data.get('volume', 0)
                }
            
            logger.debug(f"get_quote returning: {quote_dict}")
            return quote_dict

    def get_depth(self):
        """Return depth data in the format expected by the WebSocket server."""
        with self._lock:
            depth_dict = {}

            for (exchange, symbol), depth_data in self._depth_cache.items():
                if exchange not in depth_dict:
                    depth_dict[exchange] = {}

                prev_depth = self._symbol_state.get(f"{exchange}|{symbol}", {})
                prev_buy = prev_depth.get('buyBook', {}) if prev_depth else {}
                prev_sell = prev_depth.get('sellBook', {}) if prev_depth else {}

                buy_book = {}
                for i, level in enumerate(depth_data.get('buy', [])[:5], 1):
                    # If this level is all zero, use previous value if available
                    if (level.get('price', 0) == 0 and level.get('quantity', 0) == 0 and level.get('orders', 0) == 0):
                        prev = prev_buy.get(str(i), {'price': '0', 'qty': '0', 'orders': '0'})
                        buy_book[str(i)] = prev
                    else:
                        buy_book[str(i)] = {
                            'price': str(level.get('price', 0)),
                            'qty': str(level.get('quantity', 0)),
                            'orders': str(level.get('orders', 0))
                        }

                sell_book = {}
                for i, level in enumerate(depth_data.get('sell', [])[:5], 1):
                    if (level.get('price', 0) == 0 and level.get('quantity', 0) == 0 and level.get('orders', 0) == 0):
                        prev = prev_sell.get(str(i), {'price': '0', 'qty': '0', 'orders': '0'})
                        sell_book[str(i)] = prev
                    else:
                        sell_book[str(i)] = {
                            'price': str(level.get('price', 0)),
                            'qty': str(level.get('quantity', 0)),
                            'orders': str(level.get('orders', 0))
                        }

                # Save merged state for next poll
                self._symbol_state[f"{exchange}|{symbol}"] = {
                    'buyBook': buy_book,
                    'sellBook': sell_book
                }

                depth_dict[exchange][symbol] = {
                    'timestamp': int(time.time() * 1000),
                    'ltp': depth_data.get('ltp', 0.0),
                    'buyBook': buy_book,
                    'sellBook': sell_book
                }

            logger.debug(f"get_depth returning: {depth_dict}")
            return depth_dict

    def get_last_quote(self):
        """Return the last quote data."""
        with self._lock:
            return dict(self._quote_cache)

    def get_last_depth(self):
        """Return last depth data."""
        if self._ws_client:
            return self._ws_client.get_last_depth()
        return {}

    def is_connected(self):
        """Check if WebSocket is connected."""
        return self._ws_client.is_connected() if self._ws_client else False

    def set_callbacks(self, on_quote=None, on_depth=None, on_index=None, on_error=None, on_open=None, on_close=None):  
        """Set additional user callbacks - following AliceBlue pattern."""
        # Internal callbacks are already set up during initialization
        # This method is for additional user callbacks if needed
        logger.debug("set_callbacks called - internal callbacks remain active")
        # Don't override internal callbacks - they handle the cache updates
        pass