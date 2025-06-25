"""
Fixed Dhan WebSocket adapter for OpenAlgo.
Implements the broker-specific WebSocket adapter for Dhan with proper mode mapping.
"""
import logging
import os
import threading
import time
from typing import Dict, List, Optional, Any, Set

# Add the project root to Python path if not already there
import sys
import os
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Now import using relative paths from the project root
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from database.token_db import get_token
from database.auth_db import get_auth_token

# Import the WebSocket client
from .dhan_websocket import DhanWebSocket
from .dhan_mapping import get_dhan_exchange, get_openalgo_exchange

class DhanWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """
    Dhan-specific implementation of the WebSocket adapter.
    Implements OpenAlgo WebSocket proxy interface with proper mode mapping.
    """
    
    # No fallback token mappings - using database lookups only
    
    def __init__(self):
        """Initialize the WebSocket adapter"""
        super().__init__()
        # Set a default logger name, will be updated in initialize()
        self.logger = logging.getLogger("websocket_adapter")
        self.ws_client = None
        self.user_id = None
        # broker_name will be set in initialize()
        self.running = False
        self.connected = False
        self.lock = threading.RLock()  # Changed to RLock for reentrant locking
        self.subscribed_symbols = {}  # {symbol: {exchange, token, mode}}
        self.token_to_symbol = {}  # {token: (symbol, exchange)}
        
        # Authentication
        self.client_id = None
        self.access_token = None
        
        # Connection management
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10  # Increased max attempts
        self.reconnect_delay = 5  # Start with 5s delay
        self.max_reconnect_delay = 300  # Max 5 minutes between attempts
        self.reconnecting = False  # Flag to prevent multiple concurrent reconnections
        
        # Extended mode mapping to handle all possible OpenAlgo modes
        self.mode_map = {
            # Standard OpenAlgo modes
            1: DhanWebSocket.MODE_LTP,    # LTP -> "ltp"
            2: DhanWebSocket.MODE_QUOTE,  # Quote -> "marketdata"  
            3: DhanWebSocket.MODE_FULL # Map mode 8 to FULL
        }
        
    def initialize(self, broker_name: str, user_id: str, **kwargs):
        """
        Initialize the adapter with user credentials and settings.
        
        Args:
            broker_name (str): Broker identifier (e.g., 'dhan')
            user_id (str): User identifier
            **kwargs: Additional arguments (optional)
        """
        self.broker_name = broker_name.lower()  # Store broker name for later use
        # Update logger name based on broker name
        self.logger = logging.getLogger(f"{self.broker_name}_websocket_adapter")
        self.logger.info(f"Initializing {self.broker_name} WebSocket adapter")
        self.user_id = user_id
        
        # Load authentication tokens
        try:
            # Use BROKER_API_KEY as client_id
            self.client_id = os.getenv("BROKER_API_KEY")
            self.logger.info(f"Retrieved API KEY: {self.client_id[:5]}... (length: {len(self.client_id) if self.client_id else 0})")
            if not self.client_id:
                error_msg = f"No BROKER_API_KEY available for {self.broker_name} authentication"
                self.logger.error(error_msg)
                return {"status": "error", "message": error_msg}
                
            # Use BROKER_API_SECRET as access_token
            self.access_token = os.getenv("BROKER_API_SECRET")
            self.logger.info(f"Retrieved API SECRET: {self.access_token[:5]}... (length: {len(self.access_token) if self.access_token else 0})")
            if not self.access_token:
                error_msg = f"No BROKER_API_SECRET available for {self.broker_name} authentication"
                self.logger.error(error_msg)
                return {"status": "error", "message": error_msg}
                
            self.logger.info(f"{self.broker_name} WebSocket adapter initialized")
            return {"status": "success", "message": f"{self.broker_name} WebSocket adapter initialized"}
            
        except Exception as e:
            self.logger.error(f"Error initializing {self.broker_name} adapter: {e}")
            return {"status": "error", "message": f"Error initializing {self.broker_name} adapter: {e}"}
    
    def connect(self):
        """
        Connect to the Dhan WebSocket server.
        
        Returns:
            dict: Connection status
        """
        self.logger.info(f"Connecting to {self.broker_name} WebSocket server")
        
        try:
            # Initialize WebSocket client if not already done
            if not self.ws_client:
                self.ws_client = DhanWebSocket(
                    client_id=self.client_id,
                    access_token=self.access_token,
                    version='v2',  # Use v2 by default
                    on_connect=self._on_connect,
                    on_disconnect=self._on_disconnect,
                    on_error=self._on_error,
                    on_ticks=self._on_ticks
                )
            
            # Start WebSocket connection
            self.ws_client.start()
            
            # Wait for connection
            connected = self.ws_client.wait_for_connection(timeout=10.0)
            if not connected:
                self.logger.error(f"Failed to connect to {self.broker_name} WebSocket server")
                return {"status": "error", "message": f"Failed to connect to {self.broker_name} WebSocket server"}
                
            self.connected = True
            self.running = True
            self.logger.info(f"Connected to {self.broker_name} WebSocket server")
            
            # Resubscribe to symbols if reconnection
            self._resubscribe()
            
            return {"status": "success", "message": f"Connected to {self.broker_name} WebSocket server"}
            
        except Exception as e:
            self.logger.error(f"Error connecting to {self.broker_name} WebSocket: {e}")
            return {"status": "error", "message": f"Error connecting to {self.broker_name} WebSocket: {e}"}
    
    def disconnect(self):
        """
        Disconnect from the Dhan WebSocket server.
        
        Returns:
            dict: Disconnection status
        """
        self.logger.info(f"Disconnecting from {self.broker_name} WebSocket server")
        
        try:
            if self.ws_client:
                self.ws_client.stop()
                self.ws_client = None
                
            self.connected = False
            self.running = False
            
            # Clean up ZeroMQ resources
            self.cleanup_zmq()
            
            self.logger.info(f"Disconnected from {self.broker_name} WebSocket server")
            return {"status": "success", "message": f"Disconnected from {self.broker_name} WebSocket server"}
            
        except Exception as e:
            self.logger.error(f"Error disconnecting from {self.broker_name} WebSocket: {e}")
            return {"status": "error", "message": f"Error disconnecting from {self.broker_name} WebSocket: {e}"}
    
    def resolve_token(self, symbol: str, exchange: str, token: int = None):
        """
        Resolve the correct token for a symbol using database lookup:
        1. Use the provided token if valid (not None and not 1)
        2. Look up in the database
        3. Use placeholder token as a last resort
        
        Args:
            symbol (str): Symbol name
            exchange (str): Exchange name
            token (int, optional): Token provided by caller
            
        Returns:
            int: Resolved token or placeholder (1) if not found
        """
        # Use the provided token if valid
        if token is not None and token != 1:
            try:
                # Convert token to int if it's a string
                resolved_token = int(str(token))
                if resolved_token != 1:
                    self.logger.info(f"Using provided token {resolved_token} for {exchange}:{symbol}")
                    return resolved_token
            except (ValueError, TypeError):
                self.logger.warning(f"Invalid token format provided for {exchange}:{symbol}: {token}")
            
        # Try to look up in database
        try:
            db_token = get_token(symbol, exchange)
            if db_token is not None:
                try:
                    # Convert database token to int if it's a string
                    resolved_token = int(str(db_token))
                    if resolved_token != 1:
                        self.logger.info(f"Using database token {resolved_token} for {exchange}:{symbol}")
                        return resolved_token
                except (ValueError, TypeError):
                    self.logger.warning(f"Invalid token format from database for {exchange}:{symbol}: {db_token}")
        except Exception as e:
            self.logger.warning(f"Database lookup failed for {exchange}:{symbol}: {e}")
        
        # Use placeholder token (1) as last resort
        self.logger.warning(f"No valid token found for {exchange}:{symbol}, using placeholder 1")
        return 1
                
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data for a symbol.
        
        Args:
            symbol (str): Symbol identifier (e.g., 'RELIANCE')
            exchange (str): Exchange (e.g., 'NSE', 'BSE', 'NFO')
            mode (int): Mode - 1:LTP, 2:QUOTE, 3:DEPTH, 4-8:DEPTH
            depth_level (int): Depth levels for market depth data
            
        Returns:
            dict: Subscription status
            
        Note:
            This method signature was standardized to match Angel/Zerodha adapters.
            The previous signature was: 
                subscribe(symbol, exchange, token=None, mode=1)
            which caused parameter mismatch when called from the WebSocket proxy.
            The proxy was passing mode=3 as token and depth_level=5 as mode,
            resulting in mode=5 being received for DEPTH subscriptions.
        """
        # Convert exchange code to Dhan format
        dhan_exchange = get_dhan_exchange(exchange)
        self.logger.info(f"Processing subscription for {exchange}:{symbol} with mode={mode}, depth_level={depth_level}")
        
        try:
            # IMPORTANT: Token was previously a parameter, now handled internally
            token = None  # Will be resolved using the resolve_token method
            
            # Resolve the token using our multi-step resolution method
            actual_token = self.resolve_token(symbol, exchange, token)
                
            if not self.connected or not self.ws_client:
                self.logger.warning(f"Cannot subscribe - not connected to {self.broker_name} WebSocket")
                return {"status": "error", "message": f"Not connected to {self.broker_name} WebSocket"}
                
            # Debug info - print mode type and value
            self.logger.info(f"DEBUG: Mode value received: {mode}, Type: {type(mode)}")
            
            # CRITICAL: Force convert mode to integer for comparison
            try:
                mode = int(mode)
                self.logger.info(f"DEBUG: Mode converted to int: {mode}")
            except (ValueError, TypeError):
                self.logger.warning(f"DEBUG: Could not convert mode {mode} to int, using as is")
            
            # Map OpenAlgo mode to Dhan mode with explicit handling of all possible modes
            if mode == 1:
                # Standard LTP mode
                dhan_mode = DhanWebSocket.MODE_LTP
                self.logger.info(f"Mapped OpenAlgo mode {mode} (LTP) to Dhan mode '{dhan_mode}'")
            elif mode == 2:
                # Standard QUOTE mode
                dhan_mode = DhanWebSocket.MODE_QUOTE
                self.logger.info(f"Mapped OpenAlgo mode {mode} (QUOTE) to Dhan mode '{dhan_mode}'")
            elif mode == 3:
                # Standard DEPTH mode
                dhan_mode = DhanWebSocket.MODE_FULL
                self.logger.info(f"Mapped OpenAlgo mode {mode} (DEPTH) to Dhan mode '{dhan_mode}'")
            else:
                # All other modes (4-8) map to FULL/DEPTH
                dhan_mode = DhanWebSocket.MODE_FULL
                self.logger.info(f"Mapped OpenAlgo mode {mode} (DEPTH/FULL) to Dhan mode '{dhan_mode}'")
            
            # Add symbol to subscription tracking
            with self.lock:
                self.subscribed_symbols[symbol] = {
                    "exchange": exchange,  # Store original OpenAlgo exchange
                    "dhan_exchange": dhan_exchange,  # Store Dhan exchange
                    "token": actual_token,
                    "mode": mode,
                    "depth_level": depth_level  # Store depth_level for future reference
                }
                # Store token mapping with both string and int keys for robustness
                self.token_to_symbol[str(actual_token)] = (symbol, exchange)
                self.token_to_symbol[int(actual_token)] = (symbol, exchange)
                
                self.logger.info(f"📝 Stored token mapping: {actual_token} -> ({symbol}, {exchange})")
                self.logger.info(f"📝 Current token_to_symbol: {self.token_to_symbol}")
            
            # Map OpenAlgo exchange to Dhan exchange code
            exchange_code = 1  # Default to NSE_EQ
            if exchange == "NSE":
                exchange_code = 1  # NSE_EQ
            elif exchange == "BSE":
                exchange_code = 4  # BSE_EQ
            elif exchange == "NFO":
                exchange_code = 2  # NSE_FNO
            elif exchange == "BFO":
                exchange_code = 8  # BSE_FNO  
            elif exchange == "MCX":
                exchange_code = 5  # MCX_COMM
            elif exchange == "CDS" or exchange == "NSE_CDS":
                exchange_code = 3  # NSE_CURRENCY
            elif exchange == "BSE_CDS":
                exchange_code = 7  # BSE_CURRENCY
            # Special handling for index instruments
            elif exchange == "INDICES" or exchange == "NSE_INDICES" or exchange == "NSE_INDEX":
                exchange_code = 0  # IDX_I
            elif exchange == "BSE_INDICES" or exchange == "BSE_INDEX":
                exchange_code = 0  # IDX_I (Dhan treats all indices as IDX_I)
                
            self.logger.info(f"Exchange {exchange} mapped to Dhan exchange code {exchange_code}")
                
            # Subscribe to token with Dhan WebSocket, passing exchange code
            self.logger.info(f"🚀 Subscribing to {dhan_exchange}:{symbol} with token {actual_token} in mode '{dhan_mode}' using exchange code {exchange_code}")
            
            # Check if WebSocket client is properly initialized and connected
            if not self.ws_client:
                self.logger.error("❌ WebSocket client is None!")
                return {"status": "error", "message": "WebSocket client not initialized"}
                
            # Check connection status
            is_connected = self.ws_client.is_connected()
            self.logger.info(f"WebSocket connection status: {is_connected}")
            
            if not is_connected:
                self.logger.warning("⚠️ WebSocket client may not be connected, but attempting subscription anyway")
                # Don't fail here - let the subscription attempt proceed
            
            # Perform subscription
            success = self.ws_client.subscribe_tokens([actual_token], dhan_mode, exchange_codes={actual_token: exchange_code})
            
            if success:
                self.logger.info(f"✅ Successfully subscribed to {exchange}:{symbol}")
            else:
                self.logger.error(f"❌ Failed to subscribe to {exchange}:{symbol}")
                return {"status": "error", "message": f"Failed to subscribe to {exchange}:{symbol}"}
            
            return {"status": "success", "message": f"Subscribed to {exchange}:{symbol}"}
            
        except Exception as e:
            self.logger.error(f"Error subscribing to {symbol}: {e}")
            return {"status": "error", "message": f"Error subscribing to {symbol}: {e}"}
    
    def unsubscribe(self, symbol: str, exchange: str, mode: int = None) -> Dict[str, Any]:
        """
        Unsubscribe from market data for a symbol.
        
        Args:
            symbol (str): Symbol identifier
            exchange (str): Exchange identifier
            mode (int, optional): The mode to unsubscribe from. If None, will unsubscribe from all modes.
            
        Returns:
            dict: Unsubscription status
            
        Note:
            This method signature was standardized to match Angel/Zerodha adapters.
            The previous signature was: 
                unsubscribe(symbol, exchange, token=None)
            The token parameter is now handled internally using the subscription tracking mechanism.
        """
        self.logger.info(f"Processing unsubscribe for {exchange}:{symbol} with mode={mode}")
        
        try:
            # First, check if we already have this symbol in our subscription tracking
            # as that token would be most accurate for unsubscription
            stored_token = None
            with self.lock:
                if symbol in self.subscribed_symbols:
                    stored_data = self.subscribed_symbols[symbol]
                    if stored_data["exchange"] == exchange:  # Make sure we match exchange too
                        stored_token = stored_data["token"]
                        
            # If we found the stored token, use that. Otherwise resolve it.
            # IMPORTANT: token parameter was previously a method parameter, now handled internally
            actual_token = stored_token if stored_token is not None else self.resolve_token(symbol, exchange, None)
            
            # Handle case where we still couldn't resolve a token
            if actual_token is None:
                self.logger.warning(f"Could not resolve token for {exchange}:{symbol}")
                return {"status": "error", "message": f"Could not resolve token for {exchange}:{symbol}"}
                
            if not self.connected or not self.ws_client:
                self.logger.warning(f"Cannot unsubscribe - not connected to {self.broker_name} WebSocket")
                return {"status": "error", "message": f"Not connected to {self.broker_name} WebSocket"}
                
            self.logger.info(f"Unsubscribing from token {actual_token} ({exchange}:{symbol})")
            # Unsubscribe from token with Dhan WebSocket
            self.ws_client.unsubscribe(actual_token)
            
            # Remove from subscription tracking but keep token mapping for in-flight messages
            with self.lock:
                if symbol in self.subscribed_symbols:
                    # Keep token mapping for a short while to handle in-flight messages
                    # The mapping will be cleaned up by the message handler when it sees
                    # the subscription is gone
                    del self.subscribed_symbols[symbol]
            
            self.logger.info(f"Unsubscribed from {exchange}:{symbol}")
            return {"status": "success", "message": f"Unsubscribed from {exchange}:{symbol}"}
            
        except Exception as e:
            self.logger.error(f"Error unsubscribing from {symbol}: {e}")
            return {"status": "error", "message": f"Error unsubscribing from {symbol}: {e}"}
    
    def _resubscribe(self):
        """
        Re-subscribe to all previously subscribed symbols after reconnection.
        """
        if not self.connected or not self.ws_client:
            return
            
        self.logger.info("Resubscribing to previously subscribed symbols")
        
        with self.lock:
            # Group tokens by mode for bulk subscription
            mode_tokens = {}
            
            for symbol, data in self.subscribed_symbols.items():
                token = data["token"]
                mode = data["mode"]
                
                dhan_mode = self.mode_map.get(mode, DhanWebSocket.MODE_FULL)
                
                if dhan_mode not in mode_tokens:
                    mode_tokens[dhan_mode] = []
                    
                mode_tokens[dhan_mode].append(token)
            
            # Subscribe mode by mode
            for mode, tokens in mode_tokens.items():
                if tokens:
                    self.ws_client.subscribe_tokens(tokens, mode)
                    self.logger.info(f"Resubscribed {len(tokens)} symbols in mode '{mode}'")
        
        self.logger.info("Resubscription complete")
    
    def _on_connect(self):
        """
        Callback handler for WebSocket connection event.
        """
        self.logger.info("🟢 WebSocket connected callback triggered")
        self.connected = True
        
    def _on_disconnect(self):
        """
        Callback handler for WebSocket disconnection event.
        Attempts to reconnect if needed.
        """
        self.logger.warning("🔴 WebSocket disconnected callback triggered")
        self.connected = False
        
        # Attempt to reconnect if we're still running
        if self.running:
            # Start reconnection in a separate thread to avoid blocking
            reconnect_thread = threading.Thread(
                target=self._try_reconnect,
                name=f"{self.broker_name}_reconnect_thread",
                daemon=True
            )
            reconnect_thread.start()
            
    def _on_error(self, error):
        """
        Callback handler for WebSocket error event.
        
        Args:
            error: Error object or message from WebSocket
        """
        self.logger.error(f"🚨 WebSocket error callback triggered: {error}")
        
        # Attempt to reconnect on error if still running
        if self.running and self.ws_client:
            if not self.ws_client.is_connected():
                self._try_reconnect()
    
    def _on_ticks(self, ticks: List[Dict[str, Any]]):
        """
        Callback handler for tick data from WebSocket.
        Processes and publishes tick data to ZeroMQ.
        
        Args:
            ticks (List[Dict]): List of tick data dictionaries
        """
        try:
            if not ticks:
                self.logger.warning("No ticks received in _on_ticks callback")
                return
                
            self.logger.info(f"🎯 Received {len(ticks)} ticks from Dhan WebSocket")
            
            # Debug: Log raw tick data
            for i, tick in enumerate(ticks):
                self.logger.info(f"Raw tick {i+1}: {tick}")
            
            # Process each tick
            for tick in ticks:
                token = tick.get("instrument_token") or tick.get("token")
                if not token:
                    self.logger.warning(f"Tick missing token: {tick}")
                    continue
                    
                # Find symbol from token and handle cleanup
                with self.lock:
                    # Debug: Show current token mappings
                    self.logger.info(f"Looking up token {token} (type: {type(token).__name__})")
                    self.logger.info(f"Current token_to_symbol mappings: {self.token_to_symbol}")
                    self.logger.info(f"Current subscribed_symbols: {list(self.subscribed_symbols.keys())}")
                    
                    # Try direct lookup with both string and int formats for robustness
                    symbol_exchange = self.token_to_symbol.get(str(token)) or self.token_to_symbol.get(int(token))
                    
                    if not symbol_exchange:
                        # Enhanced debug info for token mapping
                        token_keys = list(self.token_to_symbol.keys())
                        token_types = [(k, type(k).__name__) for k in token_keys]
                        self.logger.warning(f"❌ TOKEN MAPPING FAILURE: Received token {token} (type: {type(token).__name__}) not found")
                        self.logger.warning(f"Available tokens: {token_types}")
                        
                        # Try more aggressive lookup methods
                        for k, v in self.token_to_symbol.items():
                            try:
                                if int(k) == int(token):
                                    self.logger.info(f"✅ Found match using int conversion: {k} -> {v}")
                                    symbol_exchange = v
                                    break
                            except (ValueError, TypeError):
                                pass
                        
                        if not symbol_exchange:
                            self.logger.error(f"❌ CRITICAL: No symbol found for token {token}, skipping tick")
                            continue  # Still no match, skip this tick
                    
                    # Check if this symbol is still subscribed
                    symbol, exchange = symbol_exchange
                    if symbol not in self.subscribed_symbols:
                        # Symbol is no longer subscribed, clean up token mapping
                        self.logger.info(f"Cleaning up token mapping for unsubscribed symbol {symbol}")
                        try:
                            del self.token_to_symbol[str(token)]
                        except KeyError:
                            pass
                        try:
                            del self.token_to_symbol[int(token)]
                        except KeyError:
                            pass
                        continue  # Skip processing this tick
                        
                symbol, exchange = symbol_exchange
                
                # Add symbol and exchange to tick data
                tick["symbol"] = symbol
                
                # Store Dhan's exchange code
                dhan_exchange = tick.get("exchange")
                
                # Get original subscription exchange for topic generation
                subscription_exchange = exchange
                
                # Convert to OpenAlgo format for data field
                data_exchange = self._map_data_exchange(subscription_exchange)
                
                # Set the data exchange field in the tick
                tick["exchange"] = data_exchange
                
                self.logger.info(f"Processing tick for {symbol}: price={tick.get('last_price')}, token={token}, exchange={subscription_exchange}")
                
                # Get mode from subscribed_symbols tracking
                subscription = self.subscribed_symbols.get(symbol, {})
                mode = subscription.get('mode', 1)  # Default to LTP mode
                
                # Map numeric mode to string format
                mode_str = {
                    1: 'LTP',
                    2: 'QUOTE',
                    3: 'DEPTH'
                }.get(mode, 'LTP')
                
                # Normalize tick format to OpenAlgo standard
                normalized_tick = self._normalize_tick(tick)
                
                # Set mode based on packet type
                packet_type = tick.get('packet_type', '')
                if packet_type == 'market_update' or packet_type == 'quote':
                    mode_str = 'QUOTE'
                elif 'depth' in normalized_tick and isinstance(normalized_tick.get('depth', {}), dict):
                    mode_str = 'DEPTH'
                self.logger.debug(f"Packet type {packet_type} mapped to mode {mode_str}")
                
                # Add mode to normalized tick for proper handling
                normalized_tick['mode'] = mode_str
                
                # Generate topics using both formats for maximum compatibility
                # Format 1: With broker name (for WebSocket server with broker filtering)
                broker_topic = self._generate_topic(symbol, subscription_exchange, mode_str)
                
                # Format 2: Without broker name (for polling compatibility)
                legacy_topic = f"{subscription_exchange}_{symbol}_{mode_str}"
                
                # Debug log to verify correct topic and data structure
                self.logger.info(f"Publishing to topic: {broker_topic}")
                self.logger.info(f"Publishing to legacy topic: {legacy_topic}")
                self.logger.info(f"Data structure: {normalized_tick}")
                self.logger.info(f"Subscription exchange: {subscription_exchange} -> Topic: {broker_topic}, Data exchange: {data_exchange}")
                
                # Publish to both topic formats for maximum compatibility
                # Topic with broker name for filtering in WebSocket server
                self.publish_market_data(broker_topic, normalized_tick)
                # Legacy topic format for polling compatibility
                self.publish_market_data(legacy_topic, normalized_tick)
                
                # Debug log for troubleshooting polling data issues
                if mode_str.lower() == 'ltp':
                    self.logger.debug(f"LTP Data should be available for polling: {subscription_exchange}:{symbol}")
                
        except Exception as e:
            self.logger.error(f"Error processing ticks: {e}")
    
    def _generate_topic(self, symbol: str, exchange: str, mode_str: str) -> str:
        """
        Generate topic for market data publishing.
        Uses the newer format including broker name for maximum client compatibility.
        
        Args:
            symbol: The trading symbol
            exchange: The exchange code in OpenAlgo format
            mode_str: The subscription mode (LTP, QUOTE, DEPTH)
            
        Returns:
            str: Properly formatted topic string
        """
        # Use new format with broker name: BROKER_EXCHANGE_SYMBOL_MODE
        return f"{self.broker_name}_{exchange}_{symbol}_{mode_str}"
    
    def _map_data_exchange(self, subscription_exchange: str) -> str:
        """
        Map subscription exchange to data exchange for client compatibility.
        
        Args:
            subscription_exchange: Original subscription exchange
            
        Returns:
            str: Data exchange code for consistent mapping
        """
        # Map NSE_INDEX/BSE_INDEX to NSE/BSE for data compatibility
        if subscription_exchange == "NSE_INDEX":
            return "NSE"
        elif subscription_exchange == "BSE_INDEX":
            return "BSE"
        return subscription_exchange
    
    def _normalize_tick(self, tick: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize Dhan tick data to OpenAlgo format.
        
        This method handles OHLC data that may come in different formats:
        - Nested under 'ohlc' dictionary
        - Directly in the tick root
        - With different field names (e.g., 'traded_volume' vs 'volume')
        
        Args:
            tick (Dict): Dhan tick data
            
        Returns:
            Dict: Normalized tick data with consistent field names and formats
        """
        try:
            # Debug log for troubleshooting
            self.logger.debug(f"Raw tick data: {tick}")
            
            # Ensure exchange is in OpenAlgo format
            exchange = tick.get("exchange")
            if exchange:
                openalgo_exchange = get_openalgo_exchange(exchange)
            else:
                openalgo_exchange = exchange
            
            # Safely get numeric values with validation
            def safe_float(value, default=0.0):
                try:
                    if value is None:
                        return default
                    fval = float(value)
                    # Validate the float is a reasonable price
                    if abs(fval) > 1e10:  # Arbitrarily large number
                        self.logger.warning(f"Suspicious price value: {fval}")
                        return default
                    return fval
                except (ValueError, TypeError):
                    return default
            
            # Get the last price with validation
            last_price = safe_float(tick.get("last_price"), 0.0)
            
            # Get timestamp - Dhan uses 'last_trade_time' for quote data
            timestamp = tick.get("timestamp") or tick.get("last_trade_time")
            
            # Create base normalized tick
            normalized = {
                "symbol": tick.get("symbol"),
                "exchange": openalgo_exchange,
                "token": tick.get("token") or tick.get("instrument_token"),
                "ltt": timestamp,
                "timestamp": timestamp,
                "ltp": round(last_price, 2),  # Use 'ltp' key for compatibility with get_ltp()
                "volume": int(tick.get("volume", 0)),  # Direct volume field
                "oi": int(tick.get("open_interest", 0))
            }
            
            # Extract OHLC data - check both nested 'ohlc' and root level
            ohlc = tick.get("ohlc", {})
            if not ohlc and any(k in tick for k in ["open", "high", "low", "close"]):
                ohlc = tick  # Use root level if ohlc dict is empty but fields exist at root
            
            # Safely extract and round OHLC values
            normalized.update({
                "open": round(safe_float(ohlc.get("open", 0)), 2),
                "high": round(safe_float(ohlc.get("high", 0)), 2),
                "low": round(safe_float(ohlc.get("low", 0)), 2),
                "close": round(safe_float(ohlc.get("close", 0)), 2)
            })
            
            # Add market depth if available
            if "depth" in tick:
                try:
                    depth_data = tick["depth"]
                    buy_orders = depth_data.get("buy", [])
                    sell_orders = depth_data.get("sell", [])
                    
                    # Debug log for depth data processing
                    self.logger.info(f"Processing depth data for {normalized.get('symbol')}: buy_levels={len(buy_orders)}, sell_levels={len(sell_orders)}")
                    
                    # Format depth data with validation
                    def format_levels(levels, side):
                        formatted = []
                        for i, level in enumerate(levels[:20]):  # Support up to 20 levels for 20-level depth
                            try:
                                price = safe_float(level.get("price"))
                                quantity = int(level.get("quantity", 0))
                                orders = int(level.get("orders", 1))
                                
                                # Only add valid levels (price > 0 and quantity > 0)
                                if price > 0 and quantity > 0:
                                    formatted.append({
                                        "price": round(price, 2),
                                        "quantity": quantity,
                                        "orders": orders,
                                        "level": i + 1
                                    })
                                    self.logger.debug(f"Added {side} level {i+1}: price={price}, qty={quantity}, orders={orders}")
                            except Exception as e:
                                self.logger.warning(f"Error formatting {side} level {i}: {e}")
                        
                        self.logger.info(f"Formatted {len(formatted)} valid {side} levels")
                        return formatted
                    
                    buy_levels = format_levels(buy_orders, "buy")
                    sell_levels = format_levels(sell_orders, "sell")
                    
                    # Only add depth if we have valid levels
                    if buy_levels or sell_levels:
                        normalized["depth"] = {
                            "buy": buy_levels,
                            "sell": sell_levels
                        }
                        
                        # Calculate total buy/sell quantities
                        normalized["total_buy_quantity"] = sum(level.get("quantity", 0) for level in buy_orders)
                        normalized["total_sell_quantity"] = sum(level.get("quantity", 0) for level in sell_orders)
                        
                        # Set best bid/ask
                        if buy_levels:
                            normalized["bid"] = buy_levels[0]["price"]
                            normalized["bid_qty"] = buy_levels[0]["quantity"]
                        if sell_levels:
                            normalized["ask"] = sell_levels[0]["price"]
                            normalized["ask_qty"] = sell_levels[0]["quantity"]
                        
                        self.logger.info(f"✅ Depth data added to normalized tick for {normalized.get('symbol')}: {len(buy_levels)} buy, {len(sell_levels)} sell levels")
                    else:
                        self.logger.warning(f"❌ No valid depth levels found for {normalized.get('symbol')}")
                        
                except Exception as e:
                    self.logger.error(f"Error processing depth data for {normalized.get('symbol')}: {e}")
                    # Continue without depth data if there's an error
            else:
                self.logger.debug(f"No depth data in tick for {normalized.get('symbol')}")
            
            self.logger.debug(f"Normalized tick: {normalized}")
            return normalized
            
        except Exception as e:
            self.logger.error(f"Error normalizing tick data: {e}\nOriginal tick: {tick}", exc_info=True)
            # Return minimal valid data with error flag
            return {
                "symbol": tick.get("symbol", "UNKNOWN"),
                "exchange": tick.get("exchange", "UNKNOWN"),
                "token": tick.get("token") or tick.get("instrument_token", 0),
                "error": str(e),
                "ltp": 0.0,
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "close": 0.0,
                "volume": 0
            }
    
    def _try_reconnect(self):
        """
        Try to reconnect to WebSocket server with exponential backoff.
        This method runs in a separate thread to avoid blocking the main thread.
        """
        with self.lock:  # Ensure thread safety
            if not self.running:
                self.logger.info("Not attempting reconnect as adapter is shutting down")
                return
                
            if self.reconnect_attempts >= self.max_reconnect_attempts:
                self.logger.error("Maximum reconnection attempts reached")
                self.disconnect()  # Give up and disconnect completely
                return
                
            # Calculate delay with exponential backoff
            delay = self.reconnect_delay * (2 ** self.reconnect_attempts)
            self.reconnect_attempts += 1
            
            self.logger.info(f"Attempting to reconnect in {delay} seconds (attempt {self.reconnect_attempts})")
            
            # Wait before reconnecting
            time.sleep(delay)
            
            if not self.running:
                self.logger.info("Aborting reconnect as adapter is shutting down")
                return
                
            try:
                # Clean up existing connection
                if self.ws_client:
                    try:
                        self.ws_client.stop()
                    except Exception as e:
                        self.logger.error(f"Error stopping WebSocket client during reconnect: {e}")
                    finally:
                        self.ws_client = None
                
                # Attempt to reconnect
                self.logger.info("Attempting to establish new WebSocket connection...")
                connection_result = self.connect()
                
                # Reset reconnect attempts if successful
                if connection_result.get("status") == "success":
                    self.logger.info("Successfully reconnected to WebSocket server")
                    self.reconnect_attempts = 0  # Reset counter on successful reconnect
                else:
                    self.logger.error(f"Failed to reconnect: {connection_result.get('message', 'Unknown error')}")
                    # Schedule next reattempt if still running
                    if self.running:
                        self._on_disconnect()
                        
            except Exception as e:
                self.logger.error(f"Error during reconnection attempt: {e}")
                # Schedule next reattempt if still running
                if self.running:
                    self._on_disconnect()
    
    def is_connected(self):
        """
        Check if adapter is connected to WebSocket.
        
        Returns:
            bool: True if connected, False otherwise.
        """
        if not self.ws_client:
            return False
            
        return self.ws_client.is_connected() and self.connected
    
    def validate_tick_parsing(self, ticker_symbols=None, timeout=30):
        """
        Validate that tick parsing is working correctly for different modes.
        
        This method subscribes to the provided symbols in different modes,
        then logs the first few ticks received for each mode to validate parsing.
        
        Args:
            ticker_symbols: List of symbols to test with (e.g. ['NSE:RELIANCE', 'NSE:INFY'])
                           If None, uses a default set of common symbols
            timeout: Time in seconds to wait for ticks
            
        Returns:
            Dict with validation results
        """
        try:
            self.logger.info("Starting tick parsing validation...")
            
            # Use some default symbols if none provided
            if not ticker_symbols:
                ticker_symbols = [
                    'NSE:RELIANCE', 'NSE:INFY', 'NSE:TCS', 
                    'NSE:SBIN', 'NSE:HDFCBANK'
                ]
            
            results = {
                'subscription_success': False,
                'modes_received': set(),
                'ticks_received': 0,
                'errors': []
            }
            
            # Create a collector for validation
            received_ticks = []
            
            def validation_callback(tick):
                received_ticks.append(tick)
                mode = tick.get('mode', 'unknown')
                results['modes_received'].add(mode)
                results['ticks_received'] += 1
                self.logger.info(f"Validation tick received: mode={mode}, token={tick.get('token')}, ltp={tick.get('last_price')}")
            
            # Backup original callbacks
            original_callbacks = {}
            for mode in [1, 2, 3, 4, 5]:  # OpenAlgo modes
                if mode in self.callbacks:
                    original_callbacks[mode] = self.callbacks[mode].copy()
                else:
                    original_callbacks[mode] = []
                # Set validation callback
                self.callbacks[mode] = [validation_callback]
            
            try:
                # Try subscribing in different modes
                self.logger.info(f"Subscribing to {ticker_symbols} for validation...")
                
                # Test each mode separately
                for mode in [1, 2, 3, 4]:  # Test ltp, quote, depth, full
                    try:
                        self.logger.info(f"Testing mode: {mode}")
                        # Subscribe to symbols in this mode
                        for symbol in ticker_symbols:
                            self.subscribe(symbol, mode=mode)
                        
                        # Wait for some ticks
                        start_time = time.time()
                        while time.time() - start_time < timeout/4:  # Divide timeout by modes
                            if results['ticks_received'] > 0:
                                self.logger.info(f"Received {results['ticks_received']} ticks for mode {mode}")
                                break
                            time.sleep(0.1)
                        
                        # Unsubscribe after test
                        for symbol in ticker_symbols:
                            self.unsubscribe(symbol, mode=mode)
                            
                        time.sleep(1)  # Give time for unsubscribe to complete
                        
                    except Exception as e:
                        error_msg = f"Error testing mode {mode}: {str(e)}"
                        results['errors'].append(error_msg)
                        self.logger.error(error_msg)
                
                results['subscription_success'] = True
                
            finally:
                # Restore original callbacks
                for mode, callbacks in original_callbacks.items():
                    if mode in self.callbacks:
                        self.callbacks[mode] = callbacks
                    
                # Try to unsubscribe from everything just in case
                try:
                    for mode in [1, 2, 3, 4, 5]:
                        for symbol in ticker_symbols:
                            self.unsubscribe(symbol, mode=mode)
                except Exception as e:
                    self.logger.error(f"Error during cleanup: {e}")
            
            # Summarize results
            self.logger.info(f"Tick validation complete. Received {results['ticks_received']} ticks")
            self.logger.info(f"Modes received: {results['modes_received']}")
            
            # Include sample ticks in result
            if received_ticks:
                # Group by mode
                sample_ticks = {}
                for tick in received_ticks[:10]:  # Get first 10 ticks max
                    mode = tick.get('mode', 'unknown')
                    if mode not in sample_ticks:
                        sample_ticks[mode] = []
                    sample_ticks[mode].append(tick)
                
                results['sample_ticks'] = sample_ticks
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error in validate_tick_parsing: {e}")
            return {'success': False, 'error': str(e)}
    
    def _generate_topic(self, symbol: str, exchange: str, mode_str: str) -> str:
        """
        Generate topic for market data publishing.
        Uses original exchange format for maximum client compatibility.
        
        Args:
            symbol: Symbol name
            exchange: Exchange code
            mode_str: Mode string (LTP, QUOTE, DEPTH)
            
        Returns:
            Properly formatted ZeroMQ topic string
        """
        # Format topic string as EXCHANGE_SYMBOL_MODE (all uppercase)
        return f"{exchange}_{symbol}_{mode_str}".upper()

    def _map_data_exchange(self, exchange: str) -> str:
        """
        Map exchange code to appropriate data exchange for client compatibility.
        
        Args:
            exchange: Original exchange code
            
        Returns:
            Mapped exchange for data field
        """
        # Ensure index exchanges are properly formatted
        if exchange in ['NSE_INDEX', 'BSE_INDEX', 'IDX_I']:
            if 'NSE' in exchange:
                return 'NSE_INDEX'  # Standardize NSE index
            elif 'BSE' in exchange:
                return 'BSE_INDEX'  # Standardize BSE index
        return exchange  # Return original for non-index exchanges
    
    def __del__(self):
        """Destructor to ensure proper cleanup."""
        try:
            self.disconnect()
        except:
            pass