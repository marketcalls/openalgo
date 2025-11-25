"""
Motilal Oswal WebSocket Client Implementation
Handles connection to Motilal Oswal's market data streaming API

Note: Motilal Oswal uses BINARY packets for market data subscriptions,
not JSON. This is different from their Trade WebSocket which uses JSON.
"""
import json
import logging
import threading
import time
import websocket
import ssl
import struct
from struct import pack, unpack
from datetime import datetime, timedelta
from typing import Dict, Optional
from utils.logging import get_logger

logger = get_logger(__name__)

class MotilalWebSocket:
    """
    WebSocket client for Motilal Oswal broker's market data API.
    Handles connection to the WebSocket server, authentication, subscription,
    and message parsing for market data.
    """

    # WebSocket endpoints
    # Market Data Broadcast WebSocket (uses BINARY packets)
    PRIMARY_URL = "wss://ws1feed.motilaloswal.com/jwebsocket/jwebsocket"
    UAT_URL = "wss://ws1feed.motilaloswal.com/jwebsocket/jwebsocket"  # UAT URL may differ

    # Note: Trade/Order WebSocket is at wss://openapi.motilaloswal.com/ws (uses JSON)

    # Maximum reconnection attempts
    MAX_RECONNECT_ATTEMPTS = 5

    # WebSocket version
    WEBSOCKET_VERSION = "1.0.0"

    def __init__(self, client_id: str, auth_token: str, api_key: str, use_uat: bool = False):
        """
        Initialize the Motilal Oswal WebSocket client.

        Args:
            client_id (str): Motilal Oswal client ID
            auth_token (str): Authentication token obtained from login
            api_key (str): API key (BROKER_API_SECRET)
            use_uat (bool): Whether to use UAT environment (default: False)
        """
        self.client_id = client_id
        self.auth_token = auth_token
        self.api_key = api_key
        self.ws_url = self.UAT_URL if use_uat else self.PRIMARY_URL

        # Connection state
        self.ws = None
        self.is_connected = False
        self.reconnect_count = 0
        self.lock = threading.Lock()
        self.last_message_time = datetime.now()

        # Subscription tracking
        self.subscribed_scrips = {}  # Format: "exchange|exchange_type|scripcode" -> instrument info
        self.subscribed_indices = set()  # Set of subscribed indices (NSE, BSE)
        self.subscriptions = {}  # Dictionary to track subscribed instruments

        # Data storage
        self.last_quotes = {}   # exchange:token -> quote data
        self.last_depth = {}    # exchange:token -> depth data
        self.last_oi = {}       # exchange:token -> OI data
        self.last_index = {}    # exchange:token -> index data

        # Threading
        self._connect_thread = None
        self._stop_event = threading.Event()
        self._heartbeat_thread = None

    def connect(self):
        """
        Establishes the WebSocket connection and starts the connection thread.
        """
        if self._connect_thread and self._connect_thread.is_alive():
            logger.info("Motilal WebSocket connection thread is already running")
            return

        # Reset the stop event
        self._stop_event.clear()

        # Start the connection in a separate thread
        self._connect_thread = threading.Thread(target=self._connect_with_retry)
        self._connect_thread.daemon = True
        self._connect_thread.start()

        # Start heartbeat thread
        self._start_heartbeat()

    def _connect_with_retry(self):
        """
        Attempts to connect to the WebSocket with exponential backoff retry logic.
        """
        attempt = 0

        while not self._stop_event.is_set() and attempt < self.MAX_RECONNECT_ATTEMPTS:
            try:
                logger.info(f"Connecting to Motilal Oswal WebSocket: {self.ws_url}")
                websocket.enableTrace(False)

                self.ws = websocket.WebSocketApp(
                    self.ws_url,
                    on_open=self.on_open,
                    on_message=self.on_message,
                    on_error=self.on_error,
                    on_close=self.on_close
                )

                # Reset reconnect count on successful connection attempt
                self.reconnect_count = 0

                # Run the WebSocket connection with SSL certificate verification disabled
                # Note: Disabled due to Motilal Oswal's expired SSL certificate
                self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})


                # If we're here, the connection was closed
                if self.is_connected:
                    # If it was a clean disconnect, break the retry loop
                    break

            except Exception as e:
                logger.error(f"Error connecting to Motilal WebSocket: {str(e)}")

            # If we should stop or connection was successful, break the retry loop
            if self._stop_event.is_set() or self.is_connected:
                break

            # Exponential backoff for reconnection attempts
            attempt += 1
            sleep_time = min(2 ** attempt, 30)  # Max 30 seconds between retries
            logger.debug(f"Reconnection attempt {attempt}/{self.MAX_RECONNECT_ATTEMPTS} failed. Retrying in {sleep_time}s")
            time.sleep(sleep_time)

        if attempt >= self.MAX_RECONNECT_ATTEMPTS and not self.is_connected:
            logger.error("Maximum reconnection attempts reached. Could not connect to Motilal WebSocket.")

    def disconnect(self):
        """
        Disconnects from the WebSocket and stops all threads.
        """
        self._stop_event.set()

        # Stop heartbeat thread
        if self._heartbeat_thread:
            self._heartbeat_thread = None

        if self.ws:
            logger.info("Closing Motilal WebSocket connection")
            # Send logout message before closing
            try:
                logout_msg = {
                    "clientid": self.client_id,
                    "action": "logout"
                }
                self.ws.send(json.dumps(logout_msg))
            except Exception as e:
                logger.error(f"Error sending logout message: {str(e)}")

            self.ws.close()

        self.is_connected = False
        logger.info("Motilal WebSocket disconnected")

    def on_open(self, ws):
        """
        Called when the WebSocket connection is established.
        Sends BINARY login packet to authenticate.

        Args:
            ws: WebSocket instance
        """
        logger.info("Motilal WebSocket connection opened")

        try:
            # Create binary login packet using struct.pack
            # Format: "=cHB15sB30sBBBB10sBBBBB45s"
            msg_type = "Q".encode()
            clientcode = self.client_id
            version = self.WEBSOCKET_VERSION

            # Pad strings to required lengths
            clientcode_15 = clientcode.ljust(15, " ").encode()
            clientcode_30 = clientcode.ljust(30, " ").encode()
            version_10 = version.ljust(10, " ").encode()
            padding_45 = (" " * 45).encode()

            # Build binary login packet
            login_packet = pack(
                "=cHB15sB30sBBBB10sBBBBB45s",
                msg_type,           # 'Q' for login
                111,                # Fixed value
                len(clientcode),    # Client code length
                clientcode_15,      # Client code (15 bytes)
                len(clientcode),    # Client code length (repeated)
                clientcode_30,      # Client code (30 bytes)
                1, 1, 1,           # Flags
                len(version),       # Version length
                version_10,         # Version (10 bytes)
                0, 0, 0, 0, 1,     # More flags
                padding_45          # Padding (45 bytes)
            )

            # Send binary login packet
            ws.send(login_packet, opcode=websocket.ABNF.OPCODE_BINARY)
            logger.debug(f"Motilal WebSocket binary login packet sent ({len(login_packet)} bytes)")
            logger.debug(f"Login packet (hex): {login_packet.hex()}")

            # Don't mark as connected yet - wait for server response

        except Exception as e:
            logger.error(f"Error sending login packet: {str(e)}")

    def on_message(self, ws, message):
        """
        Called when a message is received from the WebSocket.
        Parses BINARY message and updates the appropriate data storage.

        Args:
            ws: WebSocket instance
            message: BINARY message received from the WebSocket
        """
        try:
            self.last_message_time = datetime.now()

            # Motilal sends BINARY data, not JSON
            if isinstance(message, bytes):
                logger.debug(f"✓ Received binary message: {len(message)} bytes")
                logger.debug(f"Binary data (hex): {message.hex()}")

                # Mark as connected when we receive first message (login response)
                if not self.is_connected:
                    with self.lock:
                        self.is_connected = True
                    logger.info("✓ Motilal WebSocket connection authenticated (received binary response)")

                    # Resubscribe to any previous subscriptions
                    self._resubscribe()

                # Parse binary market data packets
                # The exact format depends on the data type, but we can identify by message structure
                if len(message) > 0:
                    msg_type = chr(message[0]) if message[0] < 128 else f"0x{message[0]:02x}"
                    logger.debug(f"Binary message type: {msg_type}, length: {len(message)}")

                    # Try to parse if it looks like market data
                    self._parse_binary_market_data(message)

            else:
                # Might be a text response (error, etc.)
                logger.debug(f"Received text message: {message[:200]}")
                try:
                    data = json.loads(message)
                    if "status" in data and data.get("status") == "ERROR":
                        error_msg = data.get("message", "Unknown error")
                        logger.error(f"Motilal WebSocket error: {error_msg}")
                except:
                    pass

        except Exception as e:
            logger.error(f"Error processing WebSocket message: {str(e)}")

    def _parse_binary_market_data(self, message: bytes):
        """
        Parse binary market data packets from Motilal Oswal.

        Packet structure (30 bytes minimum):
        - Byte 0: Exchange (1 char)
        - Bytes 1-4: Scrip code (4 bytes, little-endian int)
        - Bytes 5-8: Timestamp (4 bytes, little-endian int)
        - Byte 9: Message type (1 char)
        - Bytes 10-29: Message body (20 bytes, varies by type)

        Args:
            message: Binary message bytes
        """
        try:
            # Handle bulk messages (multiple 30-byte packets)
            packet_size = 30
            num_packets = len(message) // packet_size

            for i in range(num_packets):
                offset = i * packet_size
                packet = message[offset:offset + packet_size]

                if len(packet) < packet_size:
                    continue

                # Parse header (10 bytes)
                exchange_byte = packet[0:1].decode('utf-8', errors='ignore')
                scrip = int.from_bytes(packet[1:5], byteorder='little', signed=True)
                timestamp = int.from_bytes(packet[5:9], byteorder='little', signed=True)
                msgtype = packet[9:10].decode('utf-8', errors='ignore')

                # Parse body (20 bytes) based on message type
                body = packet[10:30]

                # Create key for storing data
                key = f"{exchange_byte}:{scrip}"

                # Look up the original subscription to get the symbol
                subscription_key = f"{self._map_exchange_back(exchange_byte)}|{scrip}"
                symbol = None
                with self.lock:
                    if subscription_key in self.subscriptions:
                        symbol = self.subscriptions[subscription_key].symbol

                # Log what we're parsing
                logger.debug(f"📊 Parsing packet: Exchange={exchange_byte}, Scrip={scrip}, MsgType='{msgtype}', Key={key}, Symbol={symbol}")

                # Detailed logging for subscribed scrips to analyze unknown packets
                subscription_key_check = f"{self._map_exchange_back(exchange_byte)}|{scrip}"
                with self.lock:
                    if subscription_key_check in self.subscriptions:
                        logger.debug(f"🔍 SUBSCRIBED SCRIP DATA: {key} ({symbol}) - MsgType='{msgtype}' (ASCII {ord(msgtype) if msgtype else 'None'}), BodyHex={body.hex()}")

                # Parse based on message type
                # Message types from Motilal SDK:
                # 'A' = LTP, 'B'-'F' = Depth levels 1-5, 'G' = OHLC, 'H' = Index, 'm' = OI
                if msgtype in ['B', 'C', 'D', 'E', 'F']:  # Market Depth levels 1-5
                    level = ord(msgtype) - ord('B') + 1  # B=1, C=2, D=3, E=4, F=5
                    logger.debug(f"✓ Parsing DEPTH level {level} (msgtype='{msgtype}') packet for {key}, Symbol: {symbol}")
                    self._parse_depth_level_packet(body, key, symbol, level)
                elif msgtype == 'A':  # LTP
                    logger.debug(f"✓ Parsing LTP packet for {key}")
                    self._parse_ltp_packet(body, key, symbol)
                elif msgtype == 'G':  # Day OHLC
                    logger.debug(f"✓ Parsing OHLC packet for {key}")
                    self._parse_ohlc_packet(body, key, symbol)
                elif msgtype == 'H':  # Index data
                    logger.debug(f"✓ Parsing INDEX packet for {key}")
                    self._parse_index_packet(body, key, symbol)
                elif msgtype == 'm':  # Open Interest
                    logger.debug(f"✓ Parsing OI packet for {key}")
                    self._parse_oi_packet(body, key, symbol)
                elif msgtype == 'W':  # DPR (circuit limits)
                    logger.debug(f"Skipping DPR packet for {key}")
                elif msgtype == '1':  # Heartbeat
                    logger.debug(f"Heartbeat received")
                elif msgtype == 'X':  # Unknown - need to investigate
                    logger.debug(f"Received message type 'X' for {key} - investigating")
                elif msgtype == 'g':  # Lowercase 'g' - possibly alternate OHLC or tick data
                    logger.debug(f"📦 Packet 'g' for {key}: {body.hex()}")
                elif msgtype == 'z':  # Lowercase 'z' - unknown supplementary data
                    logger.debug(f"📦 Packet 'z' for {key}: {body.hex()}")
                elif msgtype == 'Y':  # Uppercase 'Y' - exchange-specific data
                    logger.debug(f"📦 Packet 'Y' for {key}: {body.hex()}")
                else:
                    logger.warning(f"❌ Unknown message type '{msgtype}' (ASCII {ord(msgtype) if msgtype else 'None'}) for {key}, body: {body.hex()}")

        except Exception as e:
            logger.error(f"Error parsing binary market data: {str(e)}")

    def _map_exchange_back(self, exchange_char: str) -> str:
        """Map single character back to full exchange name"""
        mapping = {
            'N': 'NSE',
            'B': 'BSE',
            'M': 'MCX',
            'C': 'NSECD',
            'D': 'NCDEX',
            'G': 'BSEFO'
        }
        return mapping.get(exchange_char, exchange_char)

    def _parse_depth_level_packet(self, body: bytes, key: str, symbol: str, level: int):
        """
        Parse market depth packet for a specific level (20 bytes).

        Args:
            body: 20-byte packet body
            key: Exchange:Scrip key
            symbol: Trading symbol
            level: Depth level (1-5)
        """
        try:
            # Market depth format:
            # Bytes 0-3: BidRate (float)
            # Bytes 4-7: BidQty (int)
            # Bytes 8-9: BidOrder (short)
            # Bytes 10-13: OfferRate (float)
            # Bytes 14-17: OfferQty (int)
            # Bytes 18-19: OfferOrder (short)

            bid_rate = unpack('f', body[0:4])[0]
            bid_qty = int.from_bytes(body[4:8], byteorder='little', signed=True)
            bid_order = int.from_bytes(body[8:10], byteorder='little', signed=True)
            offer_rate = unpack('f', body[10:14])[0]
            offer_qty = int.from_bytes(body[14:18], byteorder='little', signed=True)
            offer_order = int.from_bytes(body[18:20], byteorder='little', signed=True)

            # Store depth data
            with self.lock:
                if key not in self.last_depth:
                    # Initialize with 5 empty levels
                    self.last_depth[key] = {
                        'bids': [None] * 5,
                        'asks': [None] * 5,
                        'symbol': symbol
                    }

                # Create bid/ask data for this level
                bid_data = {
                    'price': round(bid_rate, 2),
                    'quantity': bid_qty,
                    'orders': bid_order
                }
                ask_data = {
                    'price': round(offer_rate, 2),
                    'quantity': offer_qty,
                    'orders': offer_order
                }

                # Store at the correct level index (level-1 for 0-indexed array)
                level_index = level - 1
                if 0 <= level_index < 5:
                    self.last_depth[key]['bids'][level_index] = bid_data
                    self.last_depth[key]['asks'][level_index] = ask_data
                    logger.debug(f"📊 Depth level {level} stored for {key} ({symbol}): Bid={bid_data['price']}@{bid_qty}, Ask={ask_data['price']}@{offer_qty}")

        except Exception as e:
            logger.error(f"Error parsing depth level {level} packet: {str(e)}")

    def _parse_ltp_packet(self, body: bytes, key: str, symbol: str):
        """Parse LTP packet"""
        try:
            rate = unpack('f', body[0:4])[0]
            qty = int.from_bytes(body[4:8], byteorder='little', signed=True)

            with self.lock:
                if key not in self.last_quotes:
                    self.last_quotes[key] = {'symbol': symbol}
                self.last_quotes[key]['ltp'] = round(rate, 2)
                self.last_quotes[key]['volume'] = qty

            logger.debug(f"LTP updated for {key}: {rate}@{qty}")
        except Exception as e:
            logger.error(f"Error parsing LTP packet: {str(e)}")

    def _parse_ohlc_packet(self, body: bytes, key: str, symbol: str):
        """Parse OHLC packet"""
        try:
            open_price = unpack('f', body[0:4])[0]
            high_price = unpack('f', body[4:8])[0]
            low_price = unpack('f', body[8:12])[0]
            close_price = unpack('f', body[12:16])[0]

            with self.lock:
                if key not in self.last_quotes:
                    self.last_quotes[key] = {'symbol': symbol}
                self.last_quotes[key].update({
                    'open': round(open_price, 2),
                    'high': round(high_price, 2),
                    'low': round(low_price, 2),
                    'prev_close': round(close_price, 2)
                })

            logger.debug(f"OHLC updated for {key}")
        except Exception as e:
            logger.error(f"Error parsing OHLC packet: {str(e)}")

    def _parse_oi_packet(self, body: bytes, key: str, symbol: str):
        """Parse Open Interest packet"""
        try:
            oi = int.from_bytes(body[0:4], byteorder='little', signed=True)

            with self.lock:
                self.last_oi[key] = {'symbol': symbol, 'oi': oi}

            logger.debug(f"OI updated for {key}: {oi}")
        except Exception as e:
            logger.error(f"Error parsing OI packet: {str(e)}")

    def _parse_index_packet(self, body: bytes, key: str, symbol: str):
        """Parse Index data packet (for index symbols like NIFTY, SENSEX)"""
        try:
            # Index packet format (typically contains index value as float)
            index_value = unpack('f', body[0:4])[0]

            with self.lock:
                if key not in self.last_quotes:
                    self.last_quotes[key] = {'symbol': symbol}
                self.last_quotes[key]['ltp'] = round(index_value, 2)

            logger.debug(f"Index value updated for {key}: {index_value}")
        except Exception as e:
            logger.error(f"Error parsing index packet: {str(e)}")

    def _process_market_data(self, data: dict):
        """
        Process market data messages from WebSocket.

        Motilal provides different message types:
        - DayOHLC: Open, High, Low, PrevDayClose
        - LTP: Last Traded Price and related data
        - DPR: Daily Price Range (circuit limits)
        - MarketDepth: Bid/Ask levels
        - OpenInterest: OI data for derivatives
        - Index: Index values

        Args:
            data (dict): Market data from WebSocket
        """
        try:
            # Determine message type based on fields present
            exchange = data.get('Exchange', '')
            scrip_code = data.get('Scrip Code', '')
            timestamp = data.get('Time', '')

            if not exchange or not scrip_code:
                logger.debug("Message does not contain Exchange or Scrip Code, skipping")
                return

            # Create a unique key for this instrument (use single-char exchange to match binary parser)
            exchange_char = self._map_exchange_to_char(exchange)
            key = f"{exchange_char}:{scrip_code}"

            # Look up the original subscription to get the correct symbol
            subscription_key = f"{exchange}|{scrip_code}"
            original_instrument = None
            with self.lock:
                original_instrument = self.subscriptions.get(subscription_key)

            # Use subscription symbol if available
            symbol = None
            if original_instrument and hasattr(original_instrument, 'symbol'):
                symbol = original_instrument.symbol
                logger.debug(f"✓ Using subscription symbol: {symbol} for {subscription_key}")
            else:
                logger.warning(f"✗ No subscription symbol found for {subscription_key}")

            # Process DayOHLC data
            if 'Open' in data or 'High' in data or 'Low' in data or 'PrevDayClose' in data:
                self._process_dayohlc(data, key, symbol)

            # Process LTP data
            if 'LTP_Rate' in data:
                self._process_ltp(data, key, symbol)

            # Process DPR data (circuit limits)
            if 'UpperCktLimit' in data or 'LowerCktLimit' in data:
                self._process_dpr(data, key, symbol)

            # Process Market Depth data
            if 'BidRate' in data or 'OfferRate' in data:
                self._process_depth(data, key, symbol)

            # Process Open Interest data
            if 'Open Interest' in data:
                self._process_oi(data, key, symbol)

            # Process Index data
            if 'Rate' in data and 'LTP_Rate' not in data:  # Rate field without LTP_Rate indicates index
                self._process_index(data, key, symbol)

        except Exception as e:
            logger.error(f"Error processing market data: {str(e)}")

    def _process_dayohlc(self, data: dict, key: str, symbol: str = None):
        """Process Day OHLC data"""
        try:
            ohlc_data = {
                'exchange': data.get('Exchange', ''),
                'scrip_code': data.get('Scrip Code', ''),
                'symbol': symbol,
                'time': data.get('Time', ''),
                'open': float(data.get('Open', 0)) / 100.0,  # Convert paisa to rupees
                'high': float(data.get('High', 0)) / 100.0,
                'low': float(data.get('Low', 0)) / 100.0,
                'prev_close': float(data.get('PrevDayClose', 0)) / 100.0,
                'timestamp': datetime.now().isoformat()
            }

            with self.lock:
                if key not in self.last_quotes:
                    self.last_quotes[key] = {}
                self.last_quotes[key].update(ohlc_data)

            logger.debug(f"Updated OHLC data for {key}")
        except Exception as e:
            logger.error(f"Error processing Day OHLC data: {str(e)}")

    def _process_ltp(self, data: dict, key: str, symbol: str = None):
        """Process LTP (Last Traded Price) data"""
        try:
            ltp_data = {
                'exchange': data.get('Exchange', ''),
                'scrip_code': data.get('Scrip Code', ''),
                'symbol': symbol,
                'time': data.get('Time', ''),
                'ltp': float(data.get('LTP_Rate', 0)) / 100.0,  # Convert paisa to rupees
                'ltp_qty': int(data.get('LTP_Qty', 0)),
                'cumulative_qty': int(data.get('LTP_Cumulative Qty', 0)),
                'avg_trade_price': float(data.get('LTP_AvgTradePrice', 0)) / 100.0,
                'open_interest': int(data.get('LTP_Open Interest', 0)),
                'volume': int(data.get('LTP_Cumulative Qty', 0)),  # Use cumulative qty as volume
                'timestamp': datetime.now().isoformat()
            }

            with self.lock:
                if key not in self.last_quotes:
                    self.last_quotes[key] = {}
                self.last_quotes[key].update(ltp_data)

            logger.debug(f"✓ Updated LTP data for {key} - LTP: {ltp_data['ltp']}, Symbol: {symbol}, OI: {ltp_data['open_interest']}")
        except Exception as e:
            logger.error(f"Error processing LTP data: {str(e)}")

    def _process_dpr(self, data: dict, key: str, symbol: str = None):
        """Process DPR (Daily Price Range - circuit limits) data"""
        try:
            dpr_data = {
                'exchange': data.get('Exchange', ''),
                'scrip_code': data.get('Scrip Code', ''),
                'symbol': symbol,
                'time': data.get('Time', ''),
                'upper_circuit': float(data.get('UpperCktLimit', 0)) / 100.0,
                'lower_circuit': float(data.get('LowerCktLimit', 0)) / 100.0,
                'timestamp': datetime.now().isoformat()
            }

            with self.lock:
                if key not in self.last_quotes:
                    self.last_quotes[key] = {}
                self.last_quotes[key].update(dpr_data)

            logger.debug(f"Updated DPR data for {key}")
        except Exception as e:
            logger.error(f"Error processing DPR data: {str(e)}")

    def _process_depth(self, data: dict, key: str, symbol: str = None):
        """Process Market Depth data"""
        try:
            # Motilal provides depth data level by level
            # Each message contains one level of market depth
            level = int(data.get('Level', 1))

            bid_data = {
                'price': float(data.get('BidRate', 0)) / 100.0,
                'quantity': int(data.get('BidQty', 0)),
                'orders': int(data.get('BidOrder', 0))
            }

            ask_data = {
                'price': float(data.get('OfferRate', 0)) / 100.0,
                'quantity': int(data.get('OfferQty', 0)),
                'orders': int(data.get('OfferOrder', 0))
            }

            with self.lock:
                if key not in self.last_depth:
                    self.last_depth[key] = {
                        'exchange': data.get('Exchange', ''),
                        'scrip_code': data.get('Scrip Code', ''),
                        'symbol': symbol,
                        'time': data.get('Time', ''),
                        'bids': [],
                        'asks': [],
                        'timestamp': datetime.now().isoformat()
                    }

                # Ensure we have enough levels
                while len(self.last_depth[key]['bids']) < level:
                    self.last_depth[key]['bids'].append({'price': 0, 'quantity': 0, 'orders': 0})
                while len(self.last_depth[key]['asks']) < level:
                    self.last_depth[key]['asks'].append({'price': 0, 'quantity': 0, 'orders': 0})

                # Update the specific level (1-indexed, so subtract 1)
                self.last_depth[key]['bids'][level - 1] = bid_data
                self.last_depth[key]['asks'][level - 1] = ask_data
                self.last_depth[key]['time'] = data.get('Time', '')
                self.last_depth[key]['timestamp'] = datetime.now().isoformat()

            logger.debug(f"✓ Updated market depth level {level} for {key} - Symbol: {symbol}")
        except Exception as e:
            logger.error(f"Error processing market depth data: {str(e)}")

    def _process_oi(self, data: dict, key: str, symbol: str = None):
        """Process Open Interest data"""
        try:
            oi_data = {
                'exchange': data.get('Exchange', ''),
                'scrip_code': data.get('Scrip Code', ''),
                'symbol': symbol,
                'time': data.get('Time', ''),
                'open_interest': int(data.get('Open Interest', 0)),
                'oi_high': int(data.get('Open Interest High', 0)),
                'oi_low': int(data.get('Open Interest Low', 0)),
                'timestamp': datetime.now().isoformat()
            }

            with self.lock:
                self.last_oi[key] = oi_data

                # Also update in quotes if exists
                if key in self.last_quotes:
                    self.last_quotes[key]['open_interest'] = oi_data['open_interest']

            logger.debug(f"Updated OI data for {key} - OI: {oi_data['open_interest']}, Symbol: {symbol}")
        except Exception as e:
            logger.error(f"Error processing OI data: {str(e)}")

    def _process_index(self, data: dict, key: str, symbol: str = None):
        """Process Index data"""
        try:
            index_data = {
                'exchange': data.get('Exchange', ''),
                'scrip_code': data.get('Scrip Code', ''),
                'symbol': symbol,
                'time': data.get('Time', ''),
                'rate': float(data.get('Rate', 0)) / 100.0,  # Convert paisa to rupees
                'timestamp': datetime.now().isoformat()
            }

            with self.lock:
                self.last_index[key] = index_data

            logger.debug(f"Updated index data for {key} - Rate: {index_data['rate']}")
        except Exception as e:
            logger.error(f"Error processing index data: {str(e)}")

    def on_error(self, ws, error):
        """
        Called when an error occurs in the WebSocket connection.

        Args:
            ws: WebSocket instance
            error: Error information
        """
        logger.error(f"Motilal WebSocket error: {str(error)}")
        with self.lock:
            self.is_connected = False

    def on_close(self, ws, close_status_code, close_msg):
        """
        Called when the WebSocket connection is closed.

        Args:
            ws: WebSocket instance
            close_status_code: Status code for the close
            close_msg: Close message
        """
        with self.lock:
            self.is_connected = False

        logger.debug(f"Motilal WebSocket connection closed: {close_status_code}, {close_msg}")

        # Only attempt to reconnect if we didn't explicitly stop
        if not self._stop_event.is_set():
            self.reconnect_count += 1

            # Reconnect with exponential backoff
            sleep_time = min(2 ** self.reconnect_count, 30)
            logger.info(f"Attempting to reconnect in {sleep_time} seconds")

            def delayed_reconnect():
                time.sleep(sleep_time)
                if not self._stop_event.is_set():
                    self.connect()

            threading.Thread(target=delayed_reconnect, daemon=True).start()

    def register_scrip(self, exchange: str, exchange_type: str, scrip_code: int, symbol: str = None):
        """
        Register a scrip for market data updates using BINARY packet.

        Args:
            exchange (str): Exchange code (BSE, NSE, NSEFO, NSECD, MCX, BSEFO)
            exchange_type (str): Exchange type (CASH, DERIVATIVES)
            scrip_code (int): Scrip code/token
            symbol (str): OpenAlgo symbol (optional, for reference)

        Returns:
            bool: True if registration successful, False otherwise
        """
        with self.lock:
            if not self.is_connected:
                logger.error("Cannot register scrip: WebSocket is not connected")
                return False

            # Create subscription key
            subscription_key = f"{exchange}|{scrip_code}"

            # Store subscription
            self.subscriptions[subscription_key] = type('obj', (object,), {
                'exchange': exchange,
                'exchange_type': exchange_type,
                'scrip_code': scrip_code,
                'symbol': symbol
            })()

            # Also store in subscribed_scrips for resubscription
            full_key = f"{exchange}|{exchange_type}|{scrip_code}"
            self.subscribed_scrips[full_key] = {
                'exchange': exchange,
                'exchange_type': exchange_type,
                'scrip_code': scrip_code,
                'symbol': symbol
            }

            # Map exchange to single character
            # N=NSE, B=BSE, M=MCX, C=NSECD, D=NCDEX, G=BSEFO
            exchange_upper = exchange.upper()
            if exchange_upper == "NSECD":
                exchange_char = "C"
            elif exchange_upper == "NCDEX":
                exchange_char = "D"
            elif exchange_upper == "BSEFO":
                exchange_char = "G"
            else:
                exchange_char = exchange_upper[0]  # First character

            # Map exchange type to single character (C=CASH, D=DERIVATIVES)
            exchange_type_char = exchange_type.upper()[0]

            # Create binary register packet
            # Format: "=cHcciB" - msg_type, size, exchange, exchange_type, scrip_code, add_to_list
            try:
                msg_type = "D".encode()
                exchange_byte = exchange_char.encode()
                exchange_type_byte = exchange_type_char.encode()
                add_to_list = 1  # 1 for register, 0 for unregister

                register_packet = pack(
                    "=cHcciB",
                    msg_type,           # 'D' for data subscription
                    7,                  # Fixed size
                    exchange_byte,      # Exchange (1 char)
                    exchange_type_byte, # Exchange type (1 char)
                    scrip_code,         # Scrip code (int)
                    add_to_list         # 1 to add
                )

                self.ws.send(register_packet, opcode=websocket.ABNF.OPCODE_BINARY)
                logger.debug(f"Registered scrip: {exchange} {exchange_type} {scrip_code} (Symbol: {symbol})")
                return True
            except Exception as e:
                logger.error(f"Error sending register packet: {str(e)}")
                return False

    def unregister_scrip(self, exchange: str, exchange_type: str, scrip_code: int):
        """
        Unregister a scrip from market data updates using BINARY packet.

        Args:
            exchange (str): Exchange code
            exchange_type (str): Exchange type (CASH, DERIVATIVES)
            scrip_code (int): Scrip code/token

        Returns:
            bool: True if unregistration successful, False otherwise
        """
        with self.lock:
            if not self.is_connected:
                logger.error("Cannot unregister scrip: WebSocket is not connected")
                return False

            # Remove from subscriptions
            subscription_key = f"{exchange}|{scrip_code}"
            if subscription_key in self.subscriptions:
                del self.subscriptions[subscription_key]

            full_key = f"{exchange}|{exchange_type}|{scrip_code}"
            if full_key in self.subscribed_scrips:
                del self.subscribed_scrips[full_key]

            # Map exchange to single character
            exchange_upper = exchange.upper()
            if exchange_upper == "NSECD":
                exchange_char = "C"
            elif exchange_upper == "NCDEX":
                exchange_char = "D"
            elif exchange_upper == "BSEFO":
                exchange_char = "G"
            else:
                exchange_char = exchange_upper[0]

            # Map exchange type to single character
            exchange_type_char = exchange_type.upper()[0]

            # Create binary unregister packet (same format as register, but add_to_list = 0)
            try:
                msg_type = "D".encode()
                exchange_byte = exchange_char.encode()
                exchange_type_byte = exchange_type_char.encode()
                add_to_list = 0  # 0 for unregister

                unregister_packet = pack(
                    "=cHcciB",
                    msg_type,
                    7,
                    exchange_byte,
                    exchange_type_byte,
                    scrip_code,
                    add_to_list         # 0 to remove
                )

                self.ws.send(unregister_packet, opcode=websocket.ABNF.OPCODE_BINARY)
                logger.debug(f"Unregistered scrip: {exchange} {exchange_type} {scrip_code}")
                return True
            except Exception as e:
                logger.error(f"Error sending unregister packet: {str(e)}")
                return False

    def register_index(self, exchange: str):
        """
        Register an index for market data updates.

        Args:
            exchange (str): Exchange code (NSE, BSE)

        Returns:
            bool: True if registration successful, False otherwise
        """
        with self.lock:
            if not self.is_connected:
                logger.error("Cannot register index: WebSocket is not connected")
                return False

            self.subscribed_indices.add(exchange)

            # Send index registration message
            # Format: Mofsl.IndexRegister("NSE")
            index_msg = {
                "clientid": self.client_id,
                "action": "IndexRegister",
                "exchange": exchange
            }

            try:
                self.ws.send(json.dumps(index_msg))
                logger.debug(f"Registered index: {exchange}")
                return True
            except Exception as e:
                logger.error(f"Error sending index register message: {str(e)}")
                return False

    def unregister_index(self, exchange: str):
        """
        Unregister an index from market data updates.

        Args:
            exchange (str): Exchange code (NSE, BSE)

        Returns:
            bool: True if unregistration successful, False otherwise
        """
        with self.lock:
            if not self.is_connected:
                logger.error("Cannot unregister index: WebSocket is not connected")
                return False

            self.subscribed_indices.discard(exchange)

            # Send index unregistration message
            index_msg = {
                "clientid": self.client_id,
                "action": "IndexUnregister",
                "exchange": exchange
            }

            try:
                self.ws.send(json.dumps(index_msg))
                logger.debug(f"Unregistered index: {exchange}")
                return True
            except Exception as e:
                logger.error(f"Error sending index unregister message: {str(e)}")
                return False

    def _resubscribe(self):
        """
        Resubscribes to all previously subscribed scrips and indices after reconnection.
        """
        logger.debug(f"Resubscribing to {len(self.subscribed_scrips)} scrips and {len(self.subscribed_indices)} indices")

        # Resubscribe to scrips
        for full_key, scrip_info in self.subscribed_scrips.items():
            self.register_scrip(
                scrip_info['exchange'],
                scrip_info['exchange_type'],
                scrip_info['scrip_code'],
                scrip_info.get('symbol')
            )

        # Resubscribe to indices
        for exchange in self.subscribed_indices:
            self.register_index(exchange)

    def _start_heartbeat(self):
        """
        Start heartbeat thread to keep connection alive.
        Note: Disabled for now as Motilal's binary protocol heartbeat format is unclear.
        """
        # Heartbeat disabled - Motilal's market data WebSocket may not need it
        # The official SDK uses auto-reconnection instead
        logger.debug("Heartbeat disabled for binary WebSocket")

    def is_websocket_connected(self):
        """
        Checks if the WebSocket connection is currently active.

        Returns:
            bool: True if connected and receiving messages, False otherwise
        """
        with self.lock:
            if not self.is_connected:
                return False

            # Check if we've received messages in the last minute
            if self.last_message_time is None:
                return False

            time_since_last_message = datetime.now() - self.last_message_time
            return time_since_last_message < timedelta(minutes=1)

    def get_quote(self, exchange: str, scrip_code: str):
        """
        Get the latest quote for an instrument.

        Args:
            exchange (str): Exchange code (full name like NSE, MCX, etc.)
            scrip_code (str): Scrip code/token

        Returns:
            dict: Latest quote data or None if not available
        """
        # Convert exchange to single char for key lookup (binary parser stores with single-char exchange)
        exchange_char = self._map_exchange_to_char(exchange)
        key = f"{exchange_char}:{scrip_code}"
        with self.lock:
            quote = self.last_quotes.get(key)
            if quote:
                logger.debug(f"Retrieved quote for {key} - LTP: {quote.get('ltp', 'N/A')}, Symbol: {quote.get('symbol', 'N/A')}")
            else:
                logger.debug(f"No quote data available for {key}")
                logger.debug(f"Available quote keys: {list(self.last_quotes.keys())}")
            return quote

    def _map_exchange_to_char(self, exchange: str) -> str:
        """Map full exchange name to single character"""
        mapping = {
            'NSE': 'N',
            'BSE': 'B',
            'MCX': 'M',
            'NSECD': 'C',
            'NCDEX': 'D',
            'BSEFO': 'G',
            'NSEFO': 'N'  # NSEFO uses 'N' like NSE
        }
        exchange_upper = exchange.upper()
        return mapping.get(exchange_upper, exchange_upper[0] if exchange_upper else '')

    def get_market_depth(self, exchange: str, scrip_code: str):
        """
        Get the latest market depth for an instrument.

        Args:
            exchange (str): Exchange code (full name like NSE, MCX, etc.)
            scrip_code (str): Scrip code/token

        Returns:
            dict: Latest market depth data or None if not available
        """
        # Convert exchange to single char for key lookup
        exchange_char = self._map_exchange_to_char(exchange)
        key = f"{exchange_char}:{scrip_code}"
        logger.debug(f"Looking up depth with key: {key}")

        with self.lock:
            depth = self.last_depth.get(key)
            logger.debug(f"🔍 Looking for depth with key '{key}'. Available keys: {list(self.last_depth.keys())}")

            if depth:
                # Filter out None values from bids and asks arrays
                # Since we now store 5 levels, some may be None
                bids_raw = depth.get('bids', [])
                asks_raw = depth.get('asks', [])

                # Filter out None entries
                bids_filtered = [bid for bid in bids_raw if bid is not None]
                asks_filtered = [ask for ask in asks_raw if ask is not None]

                # Log detailed depth summary
                logger.debug(f"✓ Found depth data for {key}: {len(bids_filtered)} bid levels, {len(asks_filtered)} ask levels")
                for i, bid in enumerate(bids_filtered, 1):
                    logger.debug(f"  Bid Level {i}: Price={bid.get('price')}, Qty={bid.get('quantity')}, Orders={bid.get('orders')}")
                for i, ask in enumerate(asks_filtered, 1):
                    logger.debug(f"  Ask Level {i}: Price={ask.get('price')}, Qty={ask.get('quantity')}, Orders={ask.get('orders')}")

                logger.debug(f"Retrieved market depth for {key} - Bid levels: {len(bids_filtered)}, Ask levels: {len(asks_filtered)}, Symbol: {depth.get('symbol', 'N/A')}")

                # Return filtered depth
                return {
                    'bids': bids_filtered,
                    'asks': asks_filtered,
                    'symbol': depth.get('symbol')
                }
            else:
                logger.warning(f"❌ No depth data found for key '{key}'")
                logger.debug(f"No market depth data available for {key}")
                logger.debug(f"Available depth keys: {list(self.last_depth.keys())}")
                return None

    def get_open_interest(self, exchange: str, scrip_code: str):
        """
        Get the latest open interest for an instrument.

        Args:
            exchange (str): Exchange code (full name like NSE, MCX, etc.)
            scrip_code (str): Scrip code/token

        Returns:
            dict: Latest OI data or None if not available
        """
        # Convert exchange to single char for key lookup
        exchange_char = self._map_exchange_to_char(exchange)
        key = f"{exchange_char}:{scrip_code}"

        with self.lock:
            oi = self.last_oi.get(key)
            if oi:
                logger.debug(f"Retrieved OI for {key} - OI: {oi.get('open_interest', 'N/A')}, Symbol: {oi.get('symbol', 'N/A')}")
            else:
                logger.debug(f"No OI data available for {key}")
            return oi

    def get_index(self, exchange: str, index_code: str):
        """
        Get the latest index value.

        Args:
            exchange (str): Exchange code (full name like NSE, BSE, etc.)
            index_code (str): Index code

        Returns:
            dict: Latest index data or None if not available
        """
        # Convert exchange to single char for key lookup (binary parser stores with single-char exchange)
        exchange_char = self._map_exchange_to_char(exchange)
        key = f"{exchange_char}:{index_code}"
        with self.lock:
            index = self.last_index.get(key)
            if index:
                logger.debug(f"Retrieved index for {key} - Rate: {index.get('rate', 'N/A')}")
            else:
                logger.debug(f"No index data available for {key}")
            return index
