import json
import logging
import time
import threading
import socketio
import requests
from typing import Dict, Any, Optional, List, Callable
from broker.jainamxts.baseurl import MARKET_DATA_URL,INTERACTIVE_URL,BASE_URL


class JainamXTSWebSocketClient:
    """
    JainamXTS Socket.IO client for market data streaming
    Based on the XTS Python SDK architecture using Socket.IO
    """
    
    # Base URL
    BASE_URL = BASE_URL
    
    # Socket.IO endpoints - Updated based on XTS API documentation
    # JainamXTS only has /apibinarymarketdata endpoint (no /apimarketdata)
    SOCKET_PATH = "/apibinarymarketdata/socket.io"
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
        Initialize the JainamXTS Socket.IO client
        
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
        self.logger = logging.getLogger("jainamxts_websocket")
        
        # Subscriptions tracking
        self.subscriptions = {}
        
        # Create Socket.IO client
        self._setup_socketio()
    
    def _setup_socketio(self):
        """Setup Socket.IO client with event handlers"""
        # Disable verbose Socket.IO logging (set to True for debugging)
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

        # Register handler for xts-binary-packet (JainamXTS specific binary format)
        # This is the main event for binary market data from JainamXTS
        self.sio.on('xts-binary-packet', self._on_xts_binary_packet)
        self.logger.info("[SETUP] Registered xts-binary-packet handler")

        # Add catch-all handler for any unhandled events
        self.sio.on('*', self._on_catch_all)
        self.logger.info("[SETUP] Socket.IO handlers registered")
    
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
            
            self.logger.debug(f"[MARKET DATA LOGIN] Attempting login to: {login_url}")
            
            response = requests.post(
                login_url,
                json=login_payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                self.logger.debug(f"[MARKET DATA LOGIN] Response: {result}")
                
                if result.get("type") == "success":
                    login_result = result.get("result", {})
                    self.market_data_token = login_result.get("token")
                    self.actual_user_id = login_result.get("userID")
                    
                    if self.market_data_token and self.actual_user_id:
                        self.logger.debug(f"[MARKET DATA LOGIN] Success! Token obtained, UserID: {self.actual_user_id}")
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
            # Use JSON format like fivepaisaxts - the socket sends JSON events (1512-json-full, etc.)
            publish_format = 'JSON'
            broadcast_mode = 'FULL'  # or 'PARTIAL'

            # Use the market data token and actual user ID from login response
            connection_url = f"{self.base_url}/?token={self.market_data_token}&userID={self.actual_user_id}&publishFormat={publish_format}&broadcastMode={broadcast_mode}"

            self.logger.info(f"Connecting to JainamXTS Socket.IO: {connection_url}")
            self.logger.info(f"Socket path: {self.SOCKET_PATH}")

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
            self.logger.error(f"Failed to connect to JainamXTS Socket.IO: {e}")
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
            self.logger.warning(f"Error during Socket.IO disconnect: {e}")
        
        # Clear subscriptions
        self.subscriptions.clear()
        
        self.logger.info("Disconnected from JainamXTS Socket.IO")
    
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

            self.logger.debug(f"[SUBSCRIPTION REQUEST] URL: {self.API_BASE_URL}")
            self.logger.debug(f"[SUBSCRIPTION REQUEST] Headers: Authorization={self.market_data_token[:20]}...")
            self.logger.debug(f"[SUBSCRIPTION REQUEST] Payload: {subscription_request}")

            response = requests.post(
                self.API_BASE_URL,
                json=subscription_request,
                headers=headers,
                timeout=10
            )

            self.logger.debug(f"[SUBSCRIPTION RESPONSE] Status: {response.status_code}")
            self.logger.debug(f"[SUBSCRIPTION RESPONSE] Raw: {response.text}")

            if response.status_code == 200:
                result = response.json()
                self.logger.debug(f"[SUBSCRIPTION SUCCESS] Code: {xts_message_code}, Instruments: {len(instruments)}")
                self.logger.debug(f"[SUBSCRIPTION SUCCESS] Full Response: {json.dumps(result, indent=2)}")

                # Process initial quote data from listQuotes if available
                if result.get('type') == 'success' and 'result' in result:
                    list_quotes = result['result'].get('listQuotes', [])
                    self.logger.debug(f"[INITIAL QUOTES] Found {len(list_quotes)} quotes in response")
                    for i, quote_str in enumerate(list_quotes):
                        self.logger.debug(f"[INITIAL QUOTE {i}] Raw: {quote_str}")
                        try:
                            quote_data = json.loads(quote_str)
                            self.logger.debug(f"[INITIAL QUOTE {i}] Parsed: {quote_data}")
                            # Add MessageCode based on subscription mode
                            if 'MessageCode' not in quote_data:
                                quote_data['MessageCode'] = xts_message_code
                            if self.on_data:
                                self.on_data(self, quote_data)
                        except json.JSONDecodeError as e:
                            self.logger.error(f"Error parsing initial quote: {e}")
                else:
                    self.logger.warning(f"[SUBSCRIPTION] Response type: {result.get('type')}, no listQuotes found")
            else:
                self.logger.error(f"[SUBSCRIPTION ERROR] Status: {response.status_code}, Response: {response.text}")
                
        except Exception as e:
            self.logger.error(f"[SUBSCRIPTION EXCEPTION] Error: {e}")
        
        self.logger.debug(f"Subscribed to {len(instruments)} instruments with XTS code {xts_message_code} (mode {mode})")
    
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
                self.logger.debug(f"[UNSUBSCRIPTION SUCCESS] Code: {xts_message_code}, Instruments: {len(instruments)}, Response: {result}")
            else:
                self.logger.error(f"[UNSUBSCRIPTION ERROR] Status: {response.status_code}, Response: {response.text}")
                
        except Exception as e:
            self.logger.error(f"[UNSUBSCRIPTION EXCEPTION] Error: {e}")
        
        self.logger.debug(f"Unsubscribed from {len(instruments)} instruments")
    
    def _on_connect(self):
        """Socket.IO connect event handler"""
        self.connected = True
        self.logger.debug("[SOCKET.IO] Connected successfully!")
        self.logger.debug(f"[SOCKET.IO] UserID: {self.actual_user_id}")
        self.logger.debug(f"[SOCKET.IO] Token: {self.market_data_token[:30] if self.market_data_token else 'None'}...")

        # Call external callback
        if self.on_open:
            self.on_open(self)
    
    def _on_disconnect(self):
        """Socket.IO disconnect event handler"""
        self.connected = False
        self.logger.debug("Disconnected from JainamXTS Socket.IO")
        
        # Call external callback
        if self.on_close:
            self.on_close(self)
    
    def _on_message_handler(self, data):
        """General message handler"""
        self.logger.debug(f"[GENERAL MESSAGE] Received: {data}")
        if self.on_message:
            self.on_message(self, data)
    
    # XTS specific message handlers for different market data types
    def _on_message_1501_json_full(self, data):
        """Handle 1501 JSON full messages (Touchline/Quote)"""
        self.logger.debug(f"[1501-JSON-FULL] Received Quote data: {str(data)[:500]}")
        self._process_xts_data(data, 1501)

    def _on_message_1501_json_partial(self, data):
        """Handle 1501 JSON partial messages"""
        self.logger.debug(f"[1501-JSON-PARTIAL] Received Quote partial: {str(data)[:500]}")
        self._process_xts_data(data, 1501)

    def _on_message_1502_json_full(self, data):
        """Handle 1502 JSON full messages (Market Depth)"""
        self.logger.debug(f"[1502-JSON-FULL] Received Market Depth data: {str(data)[:500]}")
        self._process_xts_data(data, 1502)

    def _on_message_1502_json_partial(self, data):
        """Handle 1502 JSON partial messages (Market Depth updates)"""
        self.logger.debug(f"[1502-JSON-PARTIAL] Received Market Depth partial: {str(data)[:500]}")
        self._process_xts_data(data, 1502)

    def _on_message_1505_json_full(self, data):
        """Handle 1505 JSON full messages (Market depth)"""
        self.logger.debug(f"[1505-JSON-FULL] Received Market depth: {str(data)[:500]}")
        self._process_xts_data(data, 1505)

    def _on_message_1505_json_partial(self, data):
        """Handle 1505 JSON partial messages"""
        self.logger.debug(f"[1505-JSON-PARTIAL] Received Depth partial: {str(data)[:500]}")
        self._process_xts_data(data, 1505)

    def _on_message_1510_json_full(self, data):
        """Handle 1510 JSON full messages (Open interest)"""
        self.logger.debug(f"[1510-JSON-FULL] Received Open interest: {str(data)[:500]}")
        self._process_xts_data(data, 1510)

    def _on_message_1510_json_partial(self, data):
        """Handle 1510 JSON partial messages"""
        self.logger.debug(f"[1510-JSON-PARTIAL] Received OI partial: {str(data)[:500]}")
        self._process_xts_data(data, 1510)

    def _on_message_1512_json_full(self, data):
        """Handle 1512 JSON full messages (LTP)"""
        self.logger.debug(f"[1512-JSON-FULL] Received LTP data: {str(data)[:500]}")
        self._process_xts_data(data, 1512)

    def _on_message_1512_json_partial(self, data):
        """Handle 1512 JSON partial messages"""
        self.logger.debug(f"[1512-JSON-PARTIAL] Received LTP partial: {str(data)[:500]}")
        self._process_xts_data(data, 1512)

    def _process_xts_data(self, data, message_code):
        """
        Process XTS data and ensure MessageCode is present

        Args:
            data: Raw data from websocket (can be string or dict)
            message_code: The XTS message code (1501, 1502, 1512, etc.)
        """
        # Parse JSON string if needed
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                self.logger.error(f"Failed to parse JSON for message code {message_code}: {e}")
                return

        # Ensure data is a dict
        if not isinstance(data, dict):
            self.logger.warning(f"Unexpected data type for message code {message_code}: {type(data)}")
            return

        # Add MessageCode if not present
        if 'MessageCode' not in data:
            data['MessageCode'] = message_code

        # Call the data handler
        if self.on_data:
            self.on_data(self, data)
    
    def _on_message_1105_json_full(self, data):
        """Handle 1105 JSON full messages (Binary market data)"""
        self.logger.debug(f"[1105-JSON-FULL] Received binary market data: {data}")
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
                    # Compare as strings to handle type mismatch (token may be stored as string)
                    sub_segment = instrument.get('exchangeSegment')
                    sub_instrument_id = str(instrument.get('exchangeInstrumentID', ''))
                    if (sub_segment == exchange_segment_int and
                        sub_instrument_id == str(instrument_id_int)):
                        is_subscribed = True
                        break
                if is_subscribed:
                    break
            
            if not is_subscribed:
                # Skip processing for unsubscribed instruments
                return
            
            # Parse field-value pairs only for subscribed instruments
            # Add MessageCode 1512 (LTP) for compatibility with adapter processing
            market_data = {
                'ExchangeSegment': exchange_segment_int,
                'ExchangeInstrumentID': instrument_id_int,
                'MessageCode': 1512  # 1105 data is essentially LTP data
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
            
            self.logger.debug(f"[1105-PROCESSED] Subscribed instrument data: {market_data}")
            
            # Call the standard data handler
            if self.on_data:
                self.on_data(self, market_data)
                
        except Exception as e:
            self.logger.error(f"Error processing 1105 data '{data}': {e}")
    
    def _on_xts_binary_packet(self, data):
        """
        Handle xts-binary-packet events (JainamXTS binary format)

        XTS Binary Packet Structure (from official documentation):
        Header (16 bytes):
        - Bytes 0-1: Packet type/version (uint16) - 4=uncompressed, 260(0x104)=LZ4 compressed
        - Bytes 2-3: Header MessageCode (uint16) - e.g., 1501, 1502
        - Bytes 4-5: ExchangeSegment (int16) - e.g., 1=NSECM
        - Bytes 6-9: ExchangeInstrumentID (int32) - e.g., 11536=TCS
        - Bytes 10-11: BookType (int16)
        - Bytes 12-13: XMarketType (int16)
        - Bytes 14-15: uncompressedPacketSize (uint16)
        - Bytes 16+: Payload (may be LZ4 compressed if PktType=260)

        For 1501 (Touchline): LTP at payload offset 85
        For 1502 (MarketDepth): LTP at payload offset 166
        """
        try:
            if not isinstance(data, bytes) or len(data) < 17:
                self.logger.warning(f"[XTS-BINARY] Invalid data: {type(data)}, len={len(data) if isinstance(data, bytes) else 'N/A'}")
                return

            import struct

            # Parse outer header (always uncompressed, 16 bytes)
            packet_type = struct.unpack('<H', data[0:2])[0]
            header_msg_code = struct.unpack('<H', data[2:4])[0]
            exchange_segment = struct.unpack('<h', data[4:6])[0]
            instrument_id = struct.unpack('<i', data[6:10])[0]
            book_type = struct.unpack('<h', data[10:12])[0]
            x_market_type = struct.unpack('<h', data[12:14])[0]
            uncompressed_size = struct.unpack('<H', data[14:16])[0]

            # Check if payload is LZ4 compressed (PktType 260 = 0x104, bit 0x100 indicates compression)
            is_compressed = (packet_type & 0x100) != 0

            self.logger.debug(f"[XTS-BINARY] Header: PktType={packet_type}, Compressed={is_compressed}, Code={header_msg_code}, Seg={exchange_segment}, InstID={instrument_id}")

            # Check if subscribed
            is_subscribed = False
            for sub in self.subscriptions.values():
                for instrument in sub.get('instruments', []):
                    if (instrument.get('exchangeSegment') == exchange_segment and
                        str(instrument.get('exchangeInstrumentID', '')) == str(instrument_id)):
                        is_subscribed = True
                        break
                if is_subscribed:
                    break

            if not is_subscribed:
                self.logger.debug(f"[XTS-BINARY] Skipping unsubscribed instrument: {exchange_segment}:{instrument_id}")
                return

            # Payload starts at byte 16 (after 16-byte header)
            HEADER_SIZE = 16
            compressed_payload = data[HEADER_SIZE:]

            # Skip compressed packets (LZ4 not available)
            if is_compressed:
                self.logger.debug(f"[XTS-BINARY] Skipping compressed packet (PktType={packet_type})")
                return

            payload = compressed_payload
            self.logger.debug(f"[XTS-BINARY] Uncompressed payload: {len(payload)} bytes")

            # Parse the payload based on message code
            # Payload starts with: MessageCode(2) + CommonDataA
            if len(payload) < 2:
                self.logger.warning(f"[XTS-BINARY] Payload too short: {len(payload)}")
                return

            actual_msg_code = struct.unpack('<H', payload[0:2])[0]
            self.logger.debug(f"[XTS-BINARY] Payload MessageCode: {actual_msg_code}")

            market_data = {
                'ExchangeSegment': exchange_segment,
                'ExchangeInstrumentID': instrument_id,
                'MessageCode': actual_msg_code,
                '_header_code': header_msg_code  # For OHLC parsing
            }

            # Parse based on message code from OUTER header (more reliable)
            # Use header_msg_code instead of actual_msg_code from payload
            # Based on packet analysis, LTP is at payload offset 164 for 1502

            if header_msg_code == 1512:  # LTP
                # 1512 LTP packets are simple - try LTP at offset 2 (after MessageCode)
                # or scan for the first valid price
                self.logger.debug(f"[XTS-BINARY] 1512 LTP: parsing LTP packet")
                self._parse_ltp_packet(payload, market_data)
            elif header_msg_code == 1501:  # Touchline
                # For 1501, parse OHLC first to get reference range, then find LTP within that range
                self.logger.debug(f"[XTS-BINARY] 1501 Touchline: parsing with OHLC validation")
                self._parse_touchline_with_ohlc(payload, market_data)
            elif header_msg_code == 1502:  # Market Depth
                # Based on scan results, LTP is at payload offset 166 for JainamXTS
                ltp_offset = 166
                self.logger.debug(f"[XTS-BINARY] 1502 MarketDepth: trying LTP at payload offset {ltp_offset}")
                if len(payload) >= ltp_offset + 80:
                    self._parse_touchline(payload, market_data, ltp_offset)
                else:
                    self._scan_and_parse(payload, market_data)
                # Parse depth data (bids/asks) from binary
                self._parse_depth(payload, market_data)
            elif header_msg_code == 1510:  # Open Interest
                self.logger.info(f"[XTS-BINARY] 1510 OpenInterest: scanning for prices")
                self._scan_and_parse(payload, market_data)
            else:
                self.logger.info(f"[XTS-BINARY] Message code {header_msg_code}: scanning for prices")
                self._scan_and_parse(payload, market_data)

            # Send data to adapter
            if 'LastTradedPrice' in market_data:
                # Remove internal field before sending
                market_data.pop('_header_code', None)
                self.logger.info(f"[XTS-BINARY] Sending: {market_data}")
                if self.on_data:
                    self.on_data(self, market_data)

        except Exception as e:
            self.logger.error(f"[XTS-BINARY] Error: {e}")
            import traceback
            self.logger.error(traceback.format_exc())

    def _parse_touchline(self, payload, market_data, ltp_offset):
        """Parse touchline/price data from payload at given offset"""
        import struct
        try:
            # LastTradedPrice (double, 8 bytes) at ltp_offset
            ltp = struct.unpack('<d', payload[ltp_offset:ltp_offset+8])[0]
            self.logger.debug(f"[XTS-BINARY] LTP at offset {ltp_offset}: {ltp}")

            if not (0.01 < ltp < 500000):
                self.logger.warning(f"[XTS-BINARY] Invalid LTP at offset {ltp_offset}: {ltp} - scanning for valid price")
                self._scan_and_parse(payload, market_data)
                return

            market_data['LastTradedPrice'] = round(ltp, 2)

            # For 1501 (Touchline/Quote) packets, OHLC are at fixed offsets after LTP
            # Based on scan analysis of 1501 packets:
            # Prices found at: 48, 70, 92, 132, 156, 164, 172, 180
            # Pattern: LTP at 48 or 92, Open~156, High~164, Low~172, Close~180

            msg_code = market_data.get('MessageCode', 0)
            header_code = market_data.get('_header_code', msg_code)

            # OHLC offsets based on packet type
            if header_code == 1501:
                # 1501 Touchline - OHLC at offsets 156, 164, 172, 180
                ohlc_offsets = {'Open': 156, 'High': 164, 'Low': 172, 'Close': 180}
            else:
                # 1502 MarketDepth - scan for OHLC
                ohlc_offsets = None

            if ohlc_offsets and max(ohlc_offsets.values()) + 8 <= len(payload):
                for field, offset in ohlc_offsets.items():
                    try:
                        val = struct.unpack('<d', payload[offset:offset+8])[0]
                        if 0.01 < val < 500000:
                            market_data[field] = round(val, 2)
                    except Exception:
                        pass

            self.logger.debug(f"[XTS-BINARY] Parsed: LTP={ltp:.2f}, O={market_data.get('Open', 0)}, H={market_data.get('High', 0)}, L={market_data.get('Low', 0)}, C={market_data.get('Close', 0)}")

        except Exception as e:
            self.logger.error(f"[XTS-BINARY] Error parsing touchline at offset {ltp_offset}: {e}")

    def _scan_and_parse(self, payload, market_data):
        """Scan payload for prices and parse the first valid LTP found"""
        import struct
        self.logger.debug(f"[XTS-BINARY] Scanning {len(payload)}-byte payload for prices...")
        found_prices = {}
        for off in range(0, min(len(payload) - 7, 400)):
            try:
                val = struct.unpack('<d', payload[off:off+8])[0]
                if 1 < val < 500000:
                    found_prices[off] = round(val, 2)
            except Exception:
                pass
        self.logger.debug(f"[XTS-BINARY] Found {len(found_prices)} prices at offsets: {found_prices}")

        # Try to parse from the first valid offset found
        if found_prices:
            first_offset = min(found_prices.keys())
            self.logger.debug(f"[XTS-BINARY] Trying to parse from offset {first_offset}")
            self._parse_touchline(payload, market_data, first_offset)

    def _parse_ltp_packet(self, payload, market_data):
        """Parse 1512 LTP packet - simplified structure with just LTP"""
        import struct
        try:
            # 1512 LTP packet structure is simpler than Touchline
            # Try common offsets for LTP: 2 (after MessageCode), 10, 18, 26
            # Also log hex dump for debugging
            self.logger.debug(f"[XTS-LTP] Payload hex (first 100 bytes): {payload[:100].hex()}")
            self.logger.debug(f"[XTS-LTP] Payload length: {len(payload)}")

            ltp = None
            ltp_offset = None

            # Try known offsets first
            for off in [2, 10, 18, 26, 34, 42]:
                if off + 8 <= len(payload):
                    try:
                        val = struct.unpack('<d', payload[off:off+8])[0]
                        if 0.01 < val < 500000:
                            ltp = val
                            ltp_offset = off
                            self.logger.debug(f"[XTS-LTP] Found LTP={val:.2f} at offset {off}")
                            break
                    except Exception:
                        pass

            # Fallback: scan for first valid price
            if ltp is None:
                self.logger.debug(f"[XTS-LTP] Known offsets failed, scanning...")
                for off in range(0, min(len(payload) - 7, 100)):
                    try:
                        val = struct.unpack('<d', payload[off:off+8])[0]
                        if 0.01 < val < 500000:
                            ltp = val
                            ltp_offset = off
                            self.logger.debug(f"[XTS-LTP] Scan found LTP={val:.2f} at offset {off}")
                            break
                    except Exception:
                        pass

            if ltp and ltp_offset is not None:
                market_data['LastTradedPrice'] = round(ltp, 2)
                self.logger.debug(f"[XTS-LTP] Parsed LTP={ltp:.2f} at offset {ltp_offset}")
            else:
                self.logger.warning(f"[XTS-LTP] Could not find valid LTP in payload")

        except Exception as e:
            self.logger.error(f"[XTS-LTP] Error parsing LTP packet: {e}")

    def _parse_touchline_with_ohlc(self, payload, market_data):
        """Parse 1501 Touchline packet - OHLC first, then find LTP within OHLC range"""
        import struct
        try:
            # First parse OHLC at fixed offsets to get reference range
            ohlc_offsets = {'Open': 156, 'High': 164, 'Low': 172, 'Close': 180}
            ohlc_values = []

            for field, offset in ohlc_offsets.items():
                if offset + 8 <= len(payload):
                    try:
                        val = struct.unpack('<d', payload[offset:offset+8])[0]
                        if 0.01 < val < 500000:
                            market_data[field] = round(val, 2)
                            ohlc_values.append(val)
                    except Exception:
                        pass

            # Determine valid LTP range from OHLC
            if ohlc_values:
                min_price = min(ohlc_values) * 0.95  # 5% below low
                max_price = max(ohlc_values) * 1.05  # 5% above high
                close_price = market_data.get('Close', 0)
            else:
                min_price = 0.01
                max_price = 500000
                close_price = 0

            self.logger.debug(f"[XTS-TOUCHLINE] OHLC range: {min_price:.2f} - {max_price:.2f}, Close={close_price}")

            # Scan for LTP within the valid range
            ltp = None
            ltp_offset = None

            # Try common offsets first
            for off in [2, 10, 18, 26, 34, 42, 48, 52]:
                if off + 8 <= len(payload):
                    try:
                        val = struct.unpack('<d', payload[off:off+8])[0]
                        if min_price < val < max_price:
                            ltp = val
                            ltp_offset = off
                            self.logger.debug(f"[XTS-TOUCHLINE] Found LTP={val:.2f} at offset {off}")
                            break
                    except Exception:
                        pass

            # Fallback: scan for price within OHLC range
            if ltp is None:
                for off in range(0, min(len(payload) - 7, 150)):
                    try:
                        val = struct.unpack('<d', payload[off:off+8])[0]
                        if min_price < val < max_price:
                            ltp = val
                            ltp_offset = off
                            self.logger.debug(f"[XTS-TOUCHLINE] Scan found LTP={val:.2f} at offset {off}")
                            break
                    except Exception:
                        pass

            # Last resort: use Close price as LTP
            if ltp is None and close_price > 0:
                ltp = close_price
                self.logger.debug(f"[XTS-TOUCHLINE] Using Close as LTP={ltp:.2f}")

            if ltp:
                market_data['LastTradedPrice'] = round(ltp, 2)
                self.logger.debug(f"[XTS-TOUCHLINE] Parsed: LTP={ltp:.2f}, O={market_data.get('Open', 0)}, H={market_data.get('High', 0)}, L={market_data.get('Low', 0)}, C={market_data.get('Close', 0)}")

        except Exception as e:
            self.logger.error(f"[XTS-TOUCHLINE] Error: {e}")

    def _parse_depth(self, payload, market_data):
        """Parse market depth (bid/ask) data from 1502 packet"""
        import struct
        try:
            ltp = market_data.get('LastTradedPrice', 0)
            if ltp <= 0:
                return

            # Log first 200 bytes of payload for analysis
            self.logger.debug(f"[XTS-DEPTH] Payload hex (first 200 bytes): {payload[:200].hex()}")
            self.logger.debug(f"[XTS-DEPTH] LTP={ltp}, Payload len={len(payload)}")

            # XTS 1502 MarketDepth structure:
            # Based on XTS SDK, the depth data starts after MessageCode(2)
            # Each Bid/Ask level: Price(8) + Size(8) + TotalOrders(4) + NumOrders(2) = 22 bytes
            # Or: Price(8) + Size(8) + Orders(2) = 18 bytes

            bids = []
            asks = []

            # XTS 1502 depth structure based on hex dump analysis:
            # Each level is 22 bytes: Price(8) + Qty(4) + Pad(2) + Orders(2) + Pad(6)
            # Depth data starts at offset 52 (after MessageCode and common data)
            DEPTH_START = 52
            LEVEL_SIZE = 22

            # Parse 5 bid levels
            for i in range(5):
                off = DEPTH_START + (i * LEVEL_SIZE)
                if off + LEVEL_SIZE > len(payload):
                    break
                try:
                    price = struct.unpack('<d', payload[off:off+8])[0]
                    if not (0.01 < price < 500000):
                        continue

                    qty = struct.unpack('<I', payload[off+8:off+12])[0]  # uint32 at offset 8
                    orders = struct.unpack('<H', payload[off+14:off+16])[0]  # uint16 at offset 14

                    # Validate
                    if qty > 100000000:
                        qty = 0
                    if orders > 50000:
                        orders = 0

                    bids.append({'Price': round(price, 2), 'Size': int(qty), 'TotalOrders': int(orders)})
                    self.logger.debug(f"[XTS-DEPTH] Bid {i+1}: Price={price:.2f}, Qty={qty}, Orders={orders}")
                except Exception as e:
                    self.logger.debug(f"[XTS-DEPTH] Error parsing bid {i+1} at offset {off}: {e}")

            # Parse 5 ask levels (after bids at offset 52 + 5*22 = 162)
            # Scan for ask prices since there may be a small gap between bids and asks
            ASK_START = DEPTH_START + (5 * LEVEL_SIZE)

            # Scan for ask prices (prices > LTP)
            for scan_off in range(ASK_START, min(len(payload) - 20, ASK_START + 100)):
                if len(asks) >= 5:
                    break
                try:
                    price = struct.unpack('<d', payload[scan_off:scan_off+8])[0]
                    if 0.01 < price < 500000 and price > ltp:
                        qty = struct.unpack('<I', payload[scan_off+8:scan_off+12])[0]
                        orders = struct.unpack('<H', payload[scan_off+14:scan_off+16])[0]

                        if qty > 100000000:
                            qty = 0
                        if orders > 50000:
                            orders = 0

                        asks.append({'Price': round(price, 2), 'Size': int(qty), 'TotalOrders': int(orders)})
                        self.logger.debug(f"[XTS-DEPTH] Ask found at {scan_off}: Price={price:.2f}, Qty={qty}, Orders={orders}")
                except Exception:
                    pass

            self.logger.debug(f"[XTS-DEPTH] Found {len(bids)} bids, {len(asks)} asks")

            # If fixed offset didn't work, fall back to scanning
            if len(bids) < 2 or len(asks) < 1:
                self.logger.debug(f"[XTS-BINARY] Fixed offset failed, scanning for depth prices...")
                bids, asks = self._scan_depth_prices(payload, ltp)

            # Sort bids descending, asks ascending
            bids.sort(key=lambda x: x['Price'], reverse=True)
            asks.sort(key=lambda x: x['Price'])

            # Take top 5 levels
            bids = bids[:5]
            asks = asks[:5]

            # Ensure we have both bids and asks
            if not bids:
                bids = [{'Price': round(ltp * 0.999, 2), 'Size': 0, 'TotalOrders': 0}]
            if not asks:
                asks = [{'Price': round(ltp * 1.001, 2), 'Size': 0, 'TotalOrders': 0}]

            market_data['Bids'] = bids
            market_data['Asks'] = asks

            self.logger.debug(f"[XTS-BINARY] Depth: {len(bids)} bids, {len(asks)} asks")

        except Exception as e:
            self.logger.error(f"[XTS-BINARY] Error parsing depth: {e}")

    def _scan_depth_prices(self, payload, ltp):
        """Fallback: scan for depth prices near LTP"""
        import struct
        bids = []
        asks = []

        for off in range(0, min(len(payload) - 7, 200)):
            try:
                price = struct.unpack('<d', payload[off:off+8])[0]
                if 0.01 < price < 500000 and abs(price - ltp) / ltp < 0.05:
                    level = {'Price': round(price, 2), 'Size': 0, 'TotalOrders': 0}
                    if price <= ltp:
                        bids.append(level)
                    else:
                        asks.append(level)
            except Exception:
                pass

        return bids, asks

    def _on_catch_all(self, event, *args):
        """Catch-all handler for any unhandled Socket.IO events"""
        # Log ALL events to help debug
        self.logger.debug(f"[SOCKET.IO EVENT] Event: {event}")
        if args:
            for i, arg in enumerate(args):
                self.logger.debug(f"[SOCKET.IO EVENT] Arg[{i}]: Type={type(arg)}, Value={str(arg)[:500]}")
    
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