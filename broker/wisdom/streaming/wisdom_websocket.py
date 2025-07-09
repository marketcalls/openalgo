import json
import logging
import time
import threading
import socketio
import requests
from typing import Dict, Any, Optional, List, Callable
from broker.wisdom.baseurl import MARKET_DATA_URL,INTERACTIVE_URL,BASE_URL


class WisdomWebSocketClient:
    """
    Wisdom XTS Socket.IO client for market data streaming
    Based on the XTS Python SDK architecture using Socket.IO
    """
    
    # Base URL
    BASE_URL = BASE_URL
    
    # Socket.IO endpoints - Updated based on XTS API documentation
    SOCKET_PATH = "/apimarketdata/socket.io"
    API_BASE_URL = f"{MARKET_DATA_URL}/instruments/subscription"
    API_UNSUBSCRIBE_URL = f"{MARKET_DATA_URL}/instruments/subscription"  # Same endpoint, different method
    
    # Available Actions
    SUBSCRIBE_ACTION = 1
    UNSUBSCRIBE_ACTION = 0
    
    # Subscription Modes
    LTP_MODE = 1
    QUOTE_MODE = 2
    DEPTH_MODE = 3
    
    # Exchange Types (matching XTS API)
    NSE_EQ = 1
    NSE_FO = 2
    BSE_EQ = 3
    BSE_FO = 4
    MCX_FO = 5
    
    def __init__(self, api_key: str, api_secret: str, user_id: str, base_url: str = None):
        """
        Initialize the Wisdom XTS Socket.IO client
        
        Args:
            api_key: Market data API key
            api_secret: Market data API secret
            user_id: User ID (client ID)
            base_url: Base URL for the Socket.IO endpoint
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.user_id = user_id
        self.base_url = base_url or self.BASE_URL
        
        # Authentication tokens
        self.market_data_token = None
        self.feed_token = None
        self.actual_user_id = None
        
        # Connection state
        self.sio = None
        self.connected = False
        self.running = False
        
        # Callbacks
        self.on_open = None
        self.on_close = None
        self.on_error = None
        self.on_data = None
        self.on_message = None
        
        # Logger
        self.logger = logging.getLogger("wisdom_websocket")
        
        # Subscriptions tracking
        self.subscriptions = {}
        
        # Create Socket.IO client
        self._setup_socketio()
    
    def _setup_socketio(self):
        """Setup Socket.IO client with event handlers"""
        self.sio = socketio.Client(logger=False, engineio_logger=False)
        
        # Register event handlers
        self.sio.on('connect', self._on_connect)
        self.sio.on('disconnect', self._on_disconnect)
        self.sio.on('message', self._on_message_handler)
        
        # Register XTS specific message handlers
        self.sio.on('1501-json-full', self._on_message_1501_json_full)
        self.sio.on('1501-json-partial', self._on_message_1501_json_partial)
        self.sio.on('1502-json-full', self._on_message_1502_json_full)
        self.sio.on('1502-json-partial', self._on_message_1502_json_partial)
        self.sio.on('1505-json-full', self._on_message_1505_json_full)
        self.sio.on('1505-json-partial', self._on_message_1505_json_partial)
        self.sio.on('1510-json-full', self._on_message_1510_json_full)
        self.sio.on('1510-json-partial', self._on_message_1510_json_partial)
        self.sio.on('1512-json-full', self._on_message_1512_json_full)
        self.sio.on('1512-json-partial', self._on_message_1512_json_partial)
        
        # Register handler for 1105 events (binary market data)
        self.sio.on('1105-json-partial', self._on_message_1105_json_partial)
        self.sio.on('1105-json-full', self._on_message_1105_json_full)
        
        # Add catch-all handler for any unhandled events
        self.sio.on('*', self._on_catch_all)
    
    def marketdata_login(self):
        """
        Login to XTS market data API to get authentication tokens
        
        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            login_url = f"{self.base_url}/apibinarymarketdata/auth/login"
            
            login_payload = {
                "appKey": self.api_key,
                "secretKey": self.api_secret,
                "source": "WebAPI"
            }
            
            headers = {
                'Content-Type': 'application/json'
            }
            
            self.logger.info(f"[MARKET DATA LOGIN] Attempting login to: {login_url}")
            
            response = requests.post(
                login_url,
                json=login_payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                self.logger.info(f"[MARKET DATA LOGIN] Response: {result}")
                
                if result.get("type") == "success":
                    login_result = result.get("result", {})
                    self.market_data_token = login_result.get("token")
                    self.actual_user_id = login_result.get("userID")
                    
                    if self.market_data_token and self.actual_user_id:
                        self.logger.info(f"[MARKET DATA LOGIN] Success! Token obtained, UserID: {self.actual_user_id}")
                        return True
                    else:
                        self.logger.error(f"[MARKET DATA LOGIN] Missing token or userID in response")
                        return False
                else:
                    self.logger.error(f"[MARKET DATA LOGIN] API returned error: {result}")
                    return False
            else:
                self.logger.error(f"[MARKET DATA LOGIN] HTTP Error: {response.status_code}, Response: {response.text}")
                return False
                
        except Exception as e:
            self.logger.error(f"[MARKET DATA LOGIN] Exception: {e}")
            return False
    
    def connect(self):
        """Establish Socket.IO connection with proper authentication"""
        try:
            # First, login to market data API to get proper tokens
            if not self.marketdata_login():
                raise Exception("Market data login failed")
            
            # Build connection URL with proper market data token and user ID
            publish_format = 'JSON'
            broadcast_mode = 'FULL'  # or 'PARTIAL'
            
            # Use the market data token and actual user ID from login response
            connection_url = f"{self.base_url}/?token={self.market_data_token}&userID={self.actual_user_id}&publishFormat={publish_format}&broadcastMode={broadcast_mode}"
            
            self.logger.info(f"Connecting to Wisdom XTS Socket.IO: {connection_url}")
            
            # Connect to Socket.IO server
            self.sio.connect(
                connection_url,
                headers={},
                transports=['websocket'],
                namespaces=None,
                socketio_path=self.SOCKET_PATH
            )
            
            self.running = True
            
        except Exception as e:
            self.logger.error(f"Failed to connect to Wisdom XTS Socket.IO: {e}")
            if self.on_error:
                self.on_error(self, e)
            raise
    
    def disconnect(self):
        """Disconnect from Socket.IO"""
        self.running = False
        self.connected = False
        
        try:
            if self.sio and self.sio.connected:
                self.sio.disconnect()
                self.logger.info("Socket.IO client disconnected")
        except Exception as e:
            self.logger.warning(f"Error during Wisdom XTS Socket.IO disconnect: {e}")
        
        # Clear subscriptions
        self.subscriptions.clear()
        
        self.logger.info("Disconnected from Wisdom XTS Socket.IO")
    
    def subscribe(self, correlation_id: str, mode: int, instruments: List[Dict]):
        """
        Subscribe to market data using XTS HTTP API
        
        Args:
            correlation_id: Unique identifier for this subscription
            mode: Subscription mode (1=LTP, 2=Quote, 3=Depth)
            instruments: List of instruments to subscribe to
        """
        if not self.connected:
            raise RuntimeError("Socket.IO not connected")
        
        # Map mode to XTS message code
        # Based on XTS documentation:
        # 1501 = LTP/Touchline
        # 1502 = Market Depth
        # 1505 = Full Market Data
        # 1510 = Open Interest
        # 1512 = LTP
        mode_to_xts_code = {
            1: 1512,  # LTP mode -> 1512 (LTP)
            2: 1501,  # Quote mode -> 1501 (Full Market Data)  
            3: 1502   # Depth mode -> 1502 (Market Depth)
        }
        
        xts_message_code = mode_to_xts_code.get(mode, 1501)
        
        # Prepare subscription request
        subscription_request = {
            "instruments": instruments,
            "xtsMessageCode": xts_message_code
        }
        
        # Store subscription for reconnection
        self.subscriptions[correlation_id] = {
            "mode": mode,
            "instruments": instruments,
            "xts_message_code": xts_message_code
        }
        
        # Send subscription via HTTP POST (like the official XTS SDK)
        try:
            headers = {
                'Authorization': self.market_data_token,
                'Content-Type': 'application/json'
            }
            
            response = requests.post(
                self.API_BASE_URL,
                json=subscription_request,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                self.logger.info(f"[SUBSCRIPTION SUCCESS] Code: {xts_message_code}, Instruments: {len(instruments)}, Response: {result}")
                
                # Process initial quote data from listQuotes if available
                if result.get('type') == 'success' and 'result' in result:
                    list_quotes = result['result'].get('listQuotes', [])
                    for quote_str in list_quotes:
                        try:
                            quote_data = json.loads(quote_str)
                            self.logger.info(f"[INITIAL QUOTE] Processing initial quote: {quote_data}")
                            if self.on_data:
                                self.on_data(self, quote_data)
                        except json.JSONDecodeError as e:
                            self.logger.error(f"Error parsing initial quote: {e}")
            else:
                self.logger.error(f"[SUBSCRIPTION ERROR] Status: {response.status_code}, Response: {response.text}")
                
        except Exception as e:
            self.logger.error(f"[SUBSCRIPTION EXCEPTION] Error: {e}")
        
        self.logger.info(f"Subscribed to {len(instruments)} instruments with XTS code {xts_message_code} (mode {mode})")
    
    def unsubscribe(self, correlation_id: str, mode: int, instruments: List[Dict]):
        """
        Unsubscribe from market data using XTS HTTP API
        
        Args:
            correlation_id: Unique identifier for this subscription
            mode: Subscription mode
            instruments: List of instruments to unsubscribe from
        """
        if not self.connected:
            return
        
        # Get the XTS message code from stored subscription
        subscription = self.subscriptions.get(correlation_id, {})
        xts_message_code = subscription.get('xts_message_code', 1501)
        
        # Prepare unsubscription request
        unsubscription_request = {
            "instruments": instruments,
            "xtsMessageCode": xts_message_code
        }
        
        # Remove from subscriptions
        if correlation_id in self.subscriptions:
            del self.subscriptions[correlation_id]
        
        # Send unsubscription via HTTP PUT (different from subscription POST)
        try:
            headers = {
                'Authorization': self.market_data_token,
                'Content-Type': 'application/json'
            }
            
            # Use PUT method for unsubscription as per XTS API
            response = requests.put(
                self.API_UNSUBSCRIBE_URL,
                json=unsubscription_request,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                self.logger.info(f"[UNSUBSCRIPTION SUCCESS] Code: {xts_message_code}, Instruments: {len(instruments)}, Response: {result}")
            else:
                self.logger.error(f"[UNSUBSCRIPTION ERROR] Status: {response.status_code}, Response: {response.text}")
                
        except Exception as e:
            self.logger.error(f"[UNSUBSCRIPTION EXCEPTION] Error: {e}")
        
        self.logger.info(f"Unsubscribed from {len(instruments)} instruments")
    
    def _on_connect(self):
        """Socket.IO connect event handler"""
        self.connected = True
        self.logger.info("Connected to Wisdom XTS Socket.IO")
        
        # Call external callback
        if self.on_open:
            self.on_open(self)
    
    def _on_disconnect(self):
        """Socket.IO disconnect event handler"""
        self.connected = False
        self.logger.info("Disconnected from Wisdom XTS Socket.IO")
        
        # Call external callback
        if self.on_close:
            self.on_close(self)
    
    def _on_message_handler(self, data):
        """General message handler"""
        self.logger.info(f"[GENERAL MESSAGE] Received: {data}")
        if self.on_message:
            self.on_message(self, data)
    
    # XTS specific message handlers for different market data types
    def _on_message_1501_json_full(self, data):
        """Handle 1501 JSON full messages (LTP)"""
        self.logger.info(f"[1501-JSON-FULL] Received LTP data: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1501_json_partial(self, data):
        """Handle 1501 JSON partial messages"""
        self.logger.info(f"[1501-JSON-PARTIAL] Received LTP partial: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1502_json_full(self, data):
        """Handle 1502 JSON full messages (Market Depth)"""
        self.logger.info(f"[1502-JSON-FULL] Received Market Depth data: {data}")
        # Parse JSON string if needed
        if isinstance(data, str):
            try:
                data = json.loads(data)
                self.logger.info(f"[1502-JSON-FULL] Parsed depth data: {data}")
            except json.JSONDecodeError as e:
                self.logger.error(f"[1502-JSON-FULL] Failed to parse JSON: {e}")
                return
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1502_json_partial(self, data):
        """Handle 1502 JSON partial messages (Market Depth updates)"""
        self.logger.info(f"[1502-JSON-PARTIAL] Received Market Depth partial: {data}")
        # Parse JSON string if needed
        if isinstance(data, str):
            try:
                data = json.loads(data)
                self.logger.info(f"[1502-JSON-PARTIAL] Parsed depth update: {data}")
            except json.JSONDecodeError as e:
                self.logger.error(f"[1502-JSON-PARTIAL] Failed to parse JSON: {e}")
                return
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1505_json_full(self, data):
        """Handle 1505 JSON full messages (Market depth)"""
        self.logger.info(f"[1505-JSON-FULL] Received Market depth: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1505_json_partial(self, data):
        """Handle 1505 JSON partial messages"""
        self.logger.info(f"[1505-JSON-PARTIAL] Received Depth partial: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1510_json_full(self, data):
        """Handle 1510 JSON full messages (Open interest)"""
        self.logger.info(f"[1510-JSON-FULL] Received Open interest: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1510_json_partial(self, data):
        """Handle 1510 JSON partial messages"""
        self.logger.info(f"[1510-JSON-PARTIAL] Received OI partial: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1512_json_full(self, data):
        """Handle 1512 JSON full messages (Full market data)"""
        self.logger.info(f"[1512-JSON-FULL] Received Full market data: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1512_json_partial(self, data):
        """Handle 1512 JSON partial messages"""
        self.logger.info(f"[1512-JSON-PARTIAL] Received Full data partial: {data}")
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1105_json_full(self, data):
        """Handle 1105 JSON full messages (Binary market data)"""
        self.logger.info(f"[1105-JSON-FULL] Received binary market data: {data}")
        self._process_1105_data(data)
    
    def _on_message_1105_json_partial(self, data):
        """Handle 1105 JSON partial messages (Binary market data)"""
        self.logger.debug(f"[1105-JSON-PARTIAL] Received binary partial: {data}")
        self._process_1105_data(data)
    
    def _process_1105_data(self, data):
        """Process 1105 binary market data format: t:exchangeSegment_instrumentID,field:value,field:value"""
        try:
            if not isinstance(data, str):
                return
                
            # Parse format: t:12_1140025,110:2067.75,111:516.95
            parts = data.split(',')
            if not parts or not parts[0].startswith('t:'):
                return
                
            # Extract instrument info from first part
            instrument_part = parts[0][2:]  # Remove 't:'
            if '_' not in instrument_part:
                return
                
            exchange_segment, instrument_id = instrument_part.split('_', 1)
            
            # FILTER: Only process data for subscribed instruments
            exchange_segment_int = int(exchange_segment)
            instrument_id_int = int(instrument_id)
            
            # Check if we have any subscription for this instrument
            is_subscribed = False
            for sub in self.subscriptions.values():
                # Get instruments from the subscription
                for instrument in sub.get('instruments', []):
                    if (instrument.get('exchangeSegment') == exchange_segment_int and 
                        instrument.get('exchangeInstrumentID') == instrument_id_int):
                        is_subscribed = True
                        break
                if is_subscribed:
                    break
            
            if not is_subscribed:
                # Skip processing for unsubscribed instruments
                return
            
            # Parse field-value pairs only for subscribed instruments
            market_data = {
                'ExchangeSegment': exchange_segment_int,
                'ExchangeInstrumentID': instrument_id_int
            }
            
            # Map common field codes to standard names
            field_mapping = {
                '110': 'LastTradedPrice',  # LTP
                '111': 'LastTradedQuantity',  # LTQ
                '112': 'TotalTradedQuantity',  # Volume
                '113': 'AverageTradedPrice',
                '114': 'Open',
                '115': 'High', 
                '116': 'Low',
                '117': 'Close',
                '118': 'TotalBuyQuantity',
                '119': 'TotalSellQuantity'
            }
            
            for part in parts[1:]:
                if ':' in part:
                    field_code, value = part.split(':', 1)
                    field_name = field_mapping.get(field_code, f'Field_{field_code}')
                    try:
                        market_data[field_name] = float(value)
                    except ValueError:
                        market_data[field_name] = value
            
            self.logger.info(f"[1105-PROCESSED] Subscribed instrument data: {market_data}")
            
            # Call the standard data handler
            if self.on_data:
                self.on_data(self, market_data)
                
        except Exception as e:
            self.logger.error(f"Error processing 1105 data '{data}': {e}")
    
    def _on_catch_all(self, event, *args):
        """Catch-all handler for any unhandled Socket.IO events"""
        # Don't log connect/disconnect/joined events as they are handled separately
        if event not in ['connect', 'disconnect', 'joined', 'message']:
            self.logger.info(f"[CATCH-ALL] Unhandled event: {event}")
            if args:
                for i, arg in enumerate(args):
                    self.logger.info(f"  Arg[{i}]: Type={type(arg)}, Value={str(arg)[:200]}...")
    
    def resubscribe_all(self):
        """Resubscribe to all stored subscriptions after reconnection"""
        for correlation_id, sub_data in self.subscriptions.items():
            try:
                self.subscribe(
                    correlation_id,
                    sub_data["mode"],
                    sub_data["instruments"]
                )
            except Exception as e:
                self.logger.error(f"Error resubscribing {correlation_id}: {e}")