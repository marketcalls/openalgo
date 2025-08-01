import threading
import json
import logging
import time
import base64
from typing import Dict, Any, Optional, List

from broker.ibulls.streaming.ibulls_websocket import IbullsWebSocketClient
from database.auth_db import get_auth_token, get_feed_token
from database.token_db import get_token

import sys
import os

# Add parent directory to path to allow imports
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper
from .ibulls_mapping import IbullsExchangeMapper, IbullsCapabilityRegistry
from database.token_db import get_symbol


class IbullsWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Ibulls XTS specific implementation of the WebSocket adapter"""
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("ibulls_websocket")
        self.ws_client = None
        self.user_id = None
        self.broker_name = "ibulls"
        self.reconnect_delay = 5  # Initial delay in seconds
        self.max_reconnect_delay = 60  # Maximum delay in seconds
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.running = False
        self.lock = threading.Lock()
        
        # Log the ZMQ port being used
        self.logger.info(f"Ibulls adapter initialized with ZMQ port: {self.zmq_port}")
    
    def initialize(self, broker_name: str, user_id: str, auth_data: Optional[Dict[str, str]] = None) -> None:
        """
        Initialize connection with Ibulls XTS WebSocket API
        
        Args:
            broker_name: Name of the broker (always 'ibulls' in this case)
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
            feed_token = get_feed_token(user_id)
            
            if not auth_token or not feed_token:
                self.logger.error(f"No authentication tokens found for user {user_id}")
                raise ValueError(f"No authentication tokens found for user {user_id}")
                
            # For XTS, we need API key and secret, not just tokens
            # These should be stored in environment variables or config
            api_key = os.getenv('BROKER_API_KEY_MARKET')
            api_secret = os.getenv('BROKER_API_SECRET_MARKET')
            
            if not api_key or not api_secret:
                self.logger.error("Missing BROKER_API_KEY_MARKET or BROKER_API_SECRET_MARKET environment variables")
                raise ValueError("Missing Ibulls XTS API credentials in environment variables")
                
        else:
            # Use provided tokens
            auth_token = auth_data.get('auth_token')
            feed_token = auth_data.get('feed_token')
            api_key = auth_data.get('api_key', os.getenv('BROKER_API_KEY_MARKET'))
            api_secret = auth_data.get('api_secret', os.getenv('BROKER_API_SECRET_MARKET'))
            
            if not auth_token or not feed_token:
                self.logger.error("Missing required authentication data")
                raise ValueError("Missing required authentication data")
        
        self.logger.info(f"Using API Key: {api_key[:10]}... for Ibulls XTS connection")
        
        # Create Ibulls WebSocket client with API credentials
        self.ws_client = IbullsWebSocketClient(
            api_key=api_key,
            api_secret=api_secret,
            user_id=user_id  # Pass the user_id, client will get actual userID from login
        )
        
        # Set callbacks
        self.ws_client.on_open = self._on_open
        self.ws_client.on_data = self._on_data
        self.ws_client.on_error = self._on_error
        self.ws_client.on_close = self._on_close
        self.ws_client.on_message = self._on_message
        
        self.running = True
    
    def _is_index_token(self, token: str, exchange_segment: int) -> bool:
        """
        Check if a token represents an index based on well-known index tokens
        
        Args:
            token: The instrument token
            exchange_segment: The exchange segment code
            
        Returns:
            bool: True if the token is likely an index
        """
        # Well-known NSE index tokens (segment 1)
        nse_index_tokens = {
            '26000': 'NIFTY',         # Nifty 50
            '26001': 'BANKNIFTY',     # Bank Nifty
            '26008': 'FINNIFTY',      # Fin Nifty
            '26037': 'MIDCPNIFTY',    # Midcap Nifty
            # Add more NSE index tokens as needed
        }
        
        # Well-known BSE index tokens (segment 11)
        bse_index_tokens = {
            '1': 'SENSEX',            # BSE Sensex
            '12': 'BANKEX',           # BSE Bankex
            # Add more BSE index tokens as needed
        }
        
        if exchange_segment == 1 and token in nse_index_tokens:
            return True
        elif exchange_segment == 11 and token in bse_index_tokens:
            return True
            
        return False
    
    def _extract_client_id_from_token(self, feed_token: str, fallback_user_id: str) -> str:
        """
        Extract the actual client ID from the JWT feed token
        
        Args:
            feed_token: JWT token containing client information
            fallback_user_id: Fallback user ID if extraction fails
            
        Returns:
            str: Actual client ID from the token
        """
        try:
            # JWT tokens have format: header.payload.signature
            # We need to decode the payload (middle part)
            parts = feed_token.split('.')
            if len(parts) != 3:
                self.logger.warning("Invalid JWT token format, using fallback user ID")
                return fallback_user_id
            
            # Decode the payload (base64 encoded)
            payload = parts[1]
            # Add padding if needed
            padding = 4 - (len(payload) % 4)
            if padding != 4:
                payload += '=' * padding
                
            decoded_payload = base64.b64decode(payload)
            payload_json = json.loads(decoded_payload.decode('utf-8'))
            
            # Extract userID from the payload
            # From the log, it looks like: "userID": "1048131_856F2F2AF32542B762129"
            actual_user_id = payload_json.get('userID')
            if actual_user_id:
                self.logger.info(f"Extracted client ID from token: {actual_user_id}")
                return actual_user_id
            else:
                self.logger.warning("userID not found in token payload, using fallback")
                return fallback_user_id
                
        except Exception as e:
            self.logger.error(f"Error extracting client ID from token: {e}")
            self.logger.info(f"Using fallback user ID: {fallback_user_id}")
            return fallback_user_id
    
    def connect(self) -> None:
        """Establish connection to Ibulls XTS WebSocket"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return
            
        threading.Thread(target=self._connect_with_retry, daemon=True).start()
        
    def _connect_with_retry(self) -> None:
        """Connect to Ibulls XTS WebSocket with retry logic"""
        while self.running and self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                self.logger.info(f"Connecting to Ibulls XTS WebSocket (attempt {self.reconnect_attempts + 1})")
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
        """Disconnect from Ibulls XTS WebSocket"""
        self.logger.info("*** DISCONNECT CALLED - Starting IBulls disconnect process ***")
        
        # Set running to False to prevent reconnection attempts
        self.running = False
        self.reconnect_attempts = self.max_reconnect_attempts  # Prevent reconnection attempts
        self.logger.info("Set running=False and max reconnect attempts to prevent auto-reconnection")
        
        # Disconnect Socket.IO client
        if hasattr(self, 'ws_client') and self.ws_client:
            try:
                self.logger.info("Disconnecting Socket.IO client...")
                self.ws_client.disconnect()
                self.logger.info("Socket.IO client disconnect call completed")
            except Exception as e:
                self.logger.error(f"Error during Socket.IO disconnect: {e}")
        else:
            self.logger.warning("No WebSocket client to disconnect")
            
        # Set connected flag to False
        self.connected = False
        self.logger.info("Set connected flag to False")
            
        # Clean up ZeroMQ resources
        self.logger.info("Starting cleanup of ZeroMQ resources...")
        self.cleanup_zmq()
        
        self.logger.info("*** DISCONNECT PROCESS COMPLETED ***")
        
    def cleanup_zmq(self) -> None:
        """Override cleanup_zmq to provide more detailed logging"""
        try:
            # Release the port from the bound ports set
            if hasattr(self, 'zmq_port'):
                with BaseBrokerWebSocketAdapter._port_lock:
                    if self.zmq_port in BaseBrokerWebSocketAdapter._bound_ports:
                        BaseBrokerWebSocketAdapter._bound_ports.remove(self.zmq_port)
                        self.logger.info(f"Released port {self.zmq_port} from bound ports registry")
            
            # Close the socket
            if hasattr(self, 'socket') and self.socket:
                self.socket.close(linger=0)  # Don't linger on close
                self.logger.info("ZeroMQ socket closed")
                
            # DO NOT terminate shared context - other instances may still need it
            # Context will be cleaned up when the process exits
                
            self.logger.info("IBulls WebSocket cleanup completed successfully")
        except Exception as e:
            self.logger.exception(f"Error cleaning up ZeroMQ resources: {e}")
    
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> Dict[str, Any]:
        """
        Subscribe to market data with Ibulls XTS specific implementation
        
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE', 'NFO')
            mode: Subscription mode - 1:LTP, 2:Quote, 3:Depth
            depth_level: Market depth level (5, 20)
            
        Returns:
            Dict: Response with status and error message if applicable
        """
        # Validate the mode
        if mode not in [1, 2, 3]:
            return self._create_error_response("INVALID_MODE", 
                                              f"Invalid mode {mode}. Must be 1 (LTP), 2 (Quote), or 3 (Depth)")
                                              
        # If depth mode, check if supported depth level
        if mode == 3 and depth_level not in [5, 20]:
            return self._create_error_response("INVALID_DEPTH", 
                                              f"Invalid depth level {depth_level}. Must be 5 or 20")
        
        # Map symbol to token using symbol mapper
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            return self._create_error_response("SYMBOL_NOT_FOUND", 
                                              f"Symbol {symbol} not found for exchange {exchange}")
            
        token = token_info['token']
        brexchange = token_info['brexchange']
        
        self.logger.info(f"Token mapping result: symbol={symbol}, exchange={exchange} -> token={token}, brexchange={brexchange}")
        
        # Check if the requested depth level is supported for this exchange
        is_fallback = False
        actual_depth = depth_level
        
        if mode == 3:  # Depth mode
            if not IbullsCapabilityRegistry.is_depth_level_supported(exchange, depth_level):
                # If requested depth is not supported, use the highest available
                actual_depth = IbullsCapabilityRegistry.get_fallback_depth_level(
                    exchange, depth_level
                )
                is_fallback = True
                
                self.logger.info(
                    f"Depth level {depth_level} not supported for {exchange}, "
                    f"using {actual_depth} instead"
                )
        
        # Log the input values for debugging
        self.logger.info(f"Subscription input - symbol: {symbol}, exchange: {exchange}, brexchange: {brexchange}")
        
        # Create instrument list for Ibulls XTS API
        exchange_type = IbullsExchangeMapper.get_exchange_type(brexchange)
        
        # Log the full mapping for debugging
        self.logger.info(f"Exchange mapping details:")
        self.logger.info(f"  - Input exchange: {exchange}")
        self.logger.info(f"  - Brexchange from DB: {brexchange}")
        self.logger.info(f"  - Mapped exchange type: {exchange_type}")
        self.logger.info(f"  - Symbol: {symbol}")
        
        # Ensure token is a string as expected by the API
        token_str = str(token) if token is not None else ""
        
        instruments = [{
            "exchangeSegment": exchange_type,
            "exchangeInstrumentID": token_str
        }]
        
        self.logger.info(f"Final subscription request for {symbol}.{exchange}:")
        self.logger.info(f"  - Exchange Segment: {exchange_type} (type: {type(exchange_type)})")
        self.logger.info(f"  - Instrument ID: {token_str}")
        self.logger.info(f"  - Full request: {instruments}")
        
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
                'token': token,
                'mode': mode,
                'depth_level': depth_level,
                'actual_depth': actual_depth,
                'instruments': instruments,
                'is_fallback': is_fallback
            }
            # Don't log the actual token value for security, but log its type and length
            token_info = f"type={type(token)}, len={len(str(token))}, value={str(token)[:4]}...{str(token)[-4:]}" if token else "None"
            self.logger.info(f"Stored subscription [{correlation_id}]: symbol={symbol}, exchange={exchange}, brexchange={brexchange}, token_info={token_info}, mode={mode}")
        
        # Subscribe if connected
        if self.connected and self.ws_client:
            try:
                self.ws_client.subscribe(correlation_id, mode, instruments)
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
    
    def _get_token(self, symbol: str, exchange: str) -> Optional[str]:
        """Get token for a symbol from the database
        
        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'BSE')
            
        Returns:
            str: Token for the symbol or None if not found
        """
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if token_info:
            return token_info['token']
        return None
        
    def _get_exchange_segment(self, exchange: str) -> str:
        """Get exchange segment code for XTS API
        
        Args:
            exchange: Exchange code (e.g., 'NSE', 'BSE')
            
        Returns:
            str: Exchange segment code for XTS API
        """
        return IbullsExchangeMapper.get_exchange_type(exchange)

    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2) -> Dict[str, Any]:
        """
        Unsubscribe from market data and disconnect from XTS server
        
        Args:
            symbol: Trading symbol
            exchange: Exchange code
            mode: Subscription mode
            
        Returns:
            Dict: Response with status
        """
        self.logger.info(f"Unsubscribing from {symbol} on {exchange} with mode {mode}")
        
        # Map symbol to token
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if not token_info:
            self.logger.error(f"Symbol {symbol} not found for exchange {exchange}")
            return self._create_error_response("SYMBOL_NOT_FOUND", 
                                              f"Symbol {symbol} not found for exchange {exchange}")
            
        token = token_info['token']
        brexchange = token_info['brexchange']
        
        # Create instrument list for Ibulls XTS API
        instruments = [{
            "exchangeSegment": IbullsExchangeMapper.get_exchange_type(brexchange),
            "exchangeInstrumentID": token
        }]
        
        # Generate correlation ID
        correlation_id = f"{symbol}_{exchange}_{mode}"
        
        # Remove from subscriptions
        with self.lock:
            if correlation_id in self.subscriptions:
                del self.subscriptions[correlation_id]
                self.logger.info(f"Removed {symbol}.{exchange} from subscription registry")
        
        # Unsubscribe if connected
        if self.connected and self.ws_client:
            try:
                self.logger.info(f"Sending unsubscribe request for {symbol}.{exchange} to XTS server")
                self.ws_client.unsubscribe(correlation_id, mode, instruments)
                self.logger.info(f"Successfully sent unsubscribe request for {symbol}.{exchange}")
                
                # Always disconnect and perform cleanup after unsubscription
                self.logger.info(f"Initiating disconnect and cleanup after unsubscription")
                self.disconnect()
                
                return self._create_success_response(
                    f"Unsubscribed from {symbol}.{exchange} and disconnected from XTS server",
                    symbol=symbol,
                    exchange=exchange,
                    mode=mode
                )
            except Exception as e:
                self.logger.error(f"Error unsubscribing from {symbol}.{exchange}: {e}")
                return self._create_error_response("UNSUBSCRIPTION_ERROR", str(e))
        else:
            self.logger.warning(f"Not connected to XTS server, skipping unsubscribe request")
            
        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}",
            symbol=symbol,
            exchange=exchange,
            mode=mode
        )
    
    def _on_open(self, wsapp) -> None:
        """Callback when connection is established"""
        self.logger.info("Connected to Ibulls XTS WebSocket")
        self.connected = True
        
        # Resubscribe to existing subscriptions if reconnecting
        self._resubscribe_all()
    
    def _resubscribe_all(self):
        """Resubscribe to all stored subscriptions"""
        with self.lock:
            for correlation_id, sub in self.subscriptions.items():
                try:
                    self.ws_client.subscribe(correlation_id, sub["mode"], sub["instruments"])
                    self.logger.info(f"Resubscribed to {sub['symbol']}.{sub['exchange']}")
                except Exception as e:
                    self.logger.error(f"Error resubscribing to {sub['symbol']}.{sub['exchange']}: {e}")
    
    def _on_error(self, wsapp, error) -> None:
        """Callback for WebSocket errors"""
        self.logger.error(f"Ibulls XTS WebSocket error: {error}")
    
    def _on_close(self, wsapp) -> None:
        """Callback when connection is closed"""
        self.logger.info("Ibulls XTS WebSocket connection closed")
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
            self.logger.info(f"RAW IBULLS DATA: Type: {type(message)}, Data: {message}")
            self.logger.info(f"Adapter state - Connected: {self.connected}, Subscriptions count: {len(self.subscriptions)}")
            
            # Handle different message types
            if isinstance(message, bytes):
                # Binary data - parse according to XTS protocol
                self.logger.info("Processing as binary data")
                self._process_binary_data(message)
                return
            elif isinstance(message, dict):
                # JSON data
                self.logger.info("Processing as JSON dict data")
                self._process_json_data(message)
                return
            elif isinstance(message, str):
                # String data - try to parse as JSON
                self.logger.info("Processing as string data")
                try:
                    data = json.loads(message)
                    self._process_json_data(data)
                    return
                except json.JSONDecodeError:
                    self.logger.warning(f"Received non-JSON string message: {message}")
                    return
            
            self.logger.warning(f"Received unknown message type: {type(message)}")
            
        except Exception as e:
            self.logger.error(f"Error processing market data: {e}", exc_info=True)
    
    def _process_binary_data(self, data: bytes):
        """Process binary market data from XTS"""
        # This would need to be implemented based on XTS binary protocol specification
        self.logger.debug(f"Processing binary data of length: {len(data)}")
        # For now, log and return - actual implementation would parse the binary format
    
    def _process_json_data(self, data: dict):
        """Process JSON market data"""
        try:
            # Extract basic information
            exchange_segment = data.get('ExchangeSegment')
            exchange_instrument_id = data.get('ExchangeInstrumentID')
            
            self.logger.debug(f"Processing market data: ExchangeSegment={exchange_segment}, ExchangeInstrumentID={exchange_instrument_id}")
            
            # Create reverse mapping from ExchangeSegment to exchange code
            # Based on Ibulls API documentation:
            # "NSECM": 1, "NSEFO": 2, "NSECD": 3, "BSECM": 11, "BSEFO": 12, "MCXFO": 51
            segment_to_exchange = {
                1: 'NSE',   # NSECM
                2: 'NFO',   # NSEFO
                3: 'CDS',   # NSECD
                11: 'BSE',  # BSECM
                12: 'BFO',  # BSEFO
                51: 'MCX'   # MCXFO
            }
            
            # Get the exchange from segment
            exchange = segment_to_exchange.get(exchange_segment)
            if not exchange:
                self.logger.warning(f"Unknown ExchangeSegment: {exchange_segment}")
                return
                
            self.logger.info(f"Mapped ExchangeSegment {exchange_segment} to exchange: {exchange}")
            
            # Check if this is an index token first
            token_str = str(exchange_instrument_id)
            symbol = None  # Initialize symbol to None
            
            # If it's a known index token, try the index exchange first
            if self._is_index_token(token_str, exchange_segment):
                if exchange_segment == 1:  # NSE segment
                    symbol = get_symbol(token_str, 'NSE_INDEX')
                    if symbol:
                        exchange = 'NSE_INDEX'
                        self.logger.info(f"Found index symbol {symbol} in NSE_INDEX for token {exchange_instrument_id}")
                elif exchange_segment == 11:  # BSE segment
                    symbol = get_symbol(token_str, 'BSE_INDEX')
                    if symbol:
                        exchange = 'BSE_INDEX'
                        self.logger.info(f"Found index symbol {symbol} in BSE_INDEX for token {exchange_instrument_id}")
            
            # If not found as index or not an index token, try regular exchange
            if not symbol:
                symbol = get_symbol(token_str, exchange)
            
            # If still not found on base exchange, try index exchange as fallback
            if not symbol:
                if exchange == 'NSE' and not self._is_index_token(token_str, exchange_segment):
                    # Try NSE_INDEX for NSE segment as fallback
                    symbol = get_symbol(token_str, 'NSE_INDEX')
                    if symbol:
                        exchange = 'NSE_INDEX'
                        self.logger.info(f"Found symbol {symbol} in NSE_INDEX for token {exchange_instrument_id}")
                elif exchange == 'BSE' and not self._is_index_token(token_str, exchange_segment):
                    # Try BSE_INDEX for BSE segment as fallback
                    symbol = get_symbol(token_str, 'BSE_INDEX')
                    if symbol:
                        exchange = 'BSE_INDEX'
                        self.logger.info(f"Found symbol {symbol} in BSE_INDEX for token {exchange_instrument_id}")
            
            if not symbol:
                self.logger.warning(f"Could not find symbol for token {exchange_instrument_id} on exchange {exchange}")
                return
                
            self.logger.info(f"Found symbol: {symbol} for token {exchange_instrument_id} on exchange {exchange}")
            
            # Determine mode based on MessageCode
            message_code = data.get('MessageCode')
            if message_code == 1512:  # LTP
                mode = 1
                mode_str = 'LTP'
            elif message_code == 1501:  # Quote  
                mode = 2
                mode_str = 'QUOTE'
            elif message_code == 1502:  # Depth
                mode = 3
                mode_str = 'DEPTH'
            else:
                self.logger.warning(f"Unknown MessageCode: {message_code}")
                return
                
            self.logger.info(f"Determined mode {mode} ({mode_str}) from MessageCode {message_code}")
            
            # Check if we have an active subscription for this symbol and mode (optional check)
            check_correlation_id = f"{symbol}_{exchange}_{mode}"
            if check_correlation_id not in self.subscriptions:
                self.logger.warning(f"No active subscription found for {check_correlation_id}, but publishing anyway")
                # We'll publish the data anyway since we received it
            
            # Create topic for ZeroMQ
            # Use standard topic format without broker prefix for WebSocket proxy routing
            topic = f"{exchange}_{symbol}_{mode_str}"
            
            # Normalize the data
            market_data = self._normalize_market_data(data, mode)
            
            # Add metadata
            market_data.update({
                'symbol': symbol,
                'exchange': exchange,
                'mode': mode,
                'timestamp': int(time.time() * 1000)
            })
            
            self.logger.info(f"Publishing market data: {market_data}")
            self.logger.info(f"Publishing to topic: {topic} on ZMQ port: {self.zmq_port}")
            
            # Log the socket state before publishing
            self.logger.info(f"ZMQ Socket State - Port: {getattr(self, 'zmq_port', 'Unknown')}, Connected: {getattr(self, 'connected', False)}")
            self.logger.info(f"Environment ZMQ_PORT: {os.environ.get('ZMQ_PORT', 'Not Set')}")
            
            # Publish to ZeroMQ
            self.publish_market_data(topic, market_data)
            self.logger.info(f"Published data successfully to ZMQ - Topic: {topic}, Data: {market_data}")
            
        except Exception as e:
            self.logger.error(f"Error processing JSON data: {e}", exc_info=True)
    
    def _normalize_market_data(self, message: Dict[str, Any], mode: int) -> Dict[str, Any]:
        """
        Normalize broker-specific data format to a common format
        
        Args:
            message: The raw message from the broker
            mode: Subscription mode
            
        Returns:
            Dict: Normalized market data
        """
        # For MessageCode 1502 (Depth mode), data is structured differently
        message_code = message.get('MessageCode')
        
        # For depth mode (MessageCode 1502), extract data from Touchline
        if message_code == 1502 and 'Touchline' in message:
            touchline = message.get('Touchline', {})
            ltp = touchline.get('LastTradedPrice', 0)
            ltt = touchline.get('LastTradedTime', 0)
            volume = touchline.get('TotalTradedQuantity', 0)
            open_price = touchline.get('Open', 0)
            high = touchline.get('High', 0)
            low = touchline.get('Low', 0)
            close = touchline.get('Close', 0)
            ltq = touchline.get('LastTradedQunatity', touchline.get('LastTradedQuantity', 0))
            avg_price = touchline.get('AverageTradedPrice', 0)
            total_buy_qty = touchline.get('TotalBuyQuantity', 0)
            total_sell_qty = touchline.get('TotalSellQuantity', 0)
            
            # Log touchline data for debugging
            self.logger.info(f"Extracted from Touchline - LTP: {ltp}, Volume: {volume}, Open: {open_price}")
        else:
            # For other message codes (1512, 1501), data is at root level
            ltp = message.get('LastTradedPrice', 0)
            ltt = message.get('LastTradedTime', 0)
            volume = message.get('TotalTradedQuantity', 0)
            open_price = message.get('Open', 0)
            high = message.get('High', 0)
            low = message.get('Low', 0)
            close = message.get('Close', 0)
            ltq = message.get('LastTradedQunatity', message.get('LastTradedQuantity', 0))
            avg_price = message.get('AveragePrice', message.get('AverageTradedPrice', 0))
            total_buy_qty = message.get('TotalBuyQuantity', 0)
            total_sell_qty = message.get('TotalSellQuantity', 0)
        
        if mode == 1:  # LTP mode
            return {
                'ltp': ltp,
                'ltt': ltt,
                'ltq': ltq
            }
        elif mode == 2:  # Quote mode
            return {
                'ltp': ltp,
                'ltt': ltt,
                'volume': volume,
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'last_quantity': ltq,
                'average_price': avg_price,
                'total_buy_quantity': total_buy_qty,
                'total_sell_quantity': total_sell_qty
            }
        elif mode == 3:  # Depth mode
            result = {
                'ltp': ltp,
                'ltt': ltt,
                'volume': volume,
                'open': open_price,
                'high': high,
                'low': low,
                'close': close,
                'oi': message.get('OpenInterest', 0),
                'upper_circuit': message.get('UpperCircuitLimit', 0),
                'lower_circuit': message.get('LowerCircuitLimit', 0)
            }
            
            # Add depth data if available
            if 'Bids' in message and 'Asks' in message:
                bids = message.get('Bids', [])
                asks = message.get('Asks', [])
                
                self.logger.info(f"Processing depth data - Bids count: {len(bids)}, Asks count: {len(asks)}")
                
                result['depth'] = {
                    'buy': self._extract_depth_data(bids, is_buy=True),
                    'sell': self._extract_depth_data(asks, is_buy=False)
                }
                
                # Log first bid and ask for debugging
                if bids and len(bids) > 0:
                    self.logger.info(f"First bid: Price={bids[0].get('Price')}, Size={bids[0].get('Size')}")
                if asks and len(asks) > 0:
                    self.logger.info(f"First ask: Price={asks[0].get('Price')}, Size={asks[0].get('Size')}")
            else:
                self.logger.warning(f"No depth data found in message. Keys present: {list(message.keys())}")
                
            return result
        else:
            return {}
    
    def _extract_depth_data(self, depth_list: List[Dict], is_buy: bool) -> List[Dict[str, Any]]:
        """
        Extract depth data from XTS message format
        
        Args:
            depth_list: List of depth levels
            is_buy: Whether this is buy or sell side
            
        Returns:
            List: List of depth levels with price, quantity, and orders
        """
        depth = []
        
        for level in depth_list:
            if isinstance(level, dict):
                # XTS uses 'Size' instead of 'Quantity' and 'TotalOrders' instead of 'OrderCount'
                depth.append({
                    'price': level.get('Price', 0),
                    'quantity': level.get('Size', 0),
                    'orders': level.get('TotalOrders', 0)
                })
        
        # Ensure we have at least 5 levels
        while len(depth) < 5:
            depth.append({
                'price': 0.0,
                'quantity': 0,
                'orders': 0
            })
        
        return depth[:20]  # Limit to maximum 20 levels