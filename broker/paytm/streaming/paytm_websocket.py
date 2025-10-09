import struct
import websocket
import ssl
import json
import time
import logging
import threading
from logzero import logger

class PaytmWebSocket(object):
    """
    Paytm Money WebSocket client for Live Market Data Streaming
    Based on Paytm Money API documentation
    """

    ROOT_URI = "wss://developer-ws.paytmmoney.com/broadcast/user/v1/data"
    HEART_BEAT_INTERVAL = 30  # Paytm sends ping every 30 seconds
    LITTLE_ENDIAN_BYTE_ORDER = "<"
    RESUBSCRIBE_FLAG = False

    # Action types
    ADD_ACTION = "ADD"
    REMOVE_ACTION = "REMOVE"

    # Mode types - Paytm uses string mode types
    MODE_LTP = "LTP"
    MODE_QUOTE = "QUOTE"
    MODE_FULL = "FULL"

    # Exchange types for Paytm
    EXCHANGE_NSE = "NSE"
    EXCHANGE_BSE = "BSE"

    # Scrip types
    SCRIP_INDEX = "INDEX"
    SCRIP_EQUITY = "EQUITY"
    SCRIP_ETF = "ETF"
    SCRIP_FUTURE = "FUTURE"
    SCRIP_OPTION = "OPTION"

    # Packet codes for different message types
    PACKET_CODE_LTP = 61
    PACKET_CODE_QUOTE = 62
    PACKET_CODE_FULL = 63
    PACKET_CODE_INDEX_LTP = 64
    PACKET_CODE_INDEX_QUOTE = 65
    PACKET_CODE_INDEX_FULL = 66

    wsapp = None
    subscriptions = {}
    current_retry_attempt = 0

    def __init__(self, public_access_token, max_retry_attempt=5, retry_delay=5, retry_multiplier=2):
        """
        Initialize the PaytmWebSocket instance

        Parameters
        ----------
        public_access_token: string
            Public access token received from Paytm Money API
        max_retry_attempt: int
            Maximum number of retry attempts
        retry_delay: int
            Initial retry delay in seconds
        retry_multiplier: int
            Multiplier for exponential backoff
        """
        self.public_access_token = public_access_token
        self.MAX_RETRY_ATTEMPT = max_retry_attempt
        self.retry_delay = retry_delay
        self.retry_multiplier = retry_multiplier
        self.DISCONNECT_FLAG = True
        self.last_pong_timestamp = None

        if not self._sanity_check():
            logger.error("Invalid initialization parameters. Provide a valid public access token.")
            raise Exception("Provide valid public access token")

    def _sanity_check(self):
        """Validate initialization parameters"""
        return bool(self.public_access_token)

    def _on_message(self, wsapp, message):
        """
        Handle incoming WebSocket messages

        Paytm sends binary data that needs to be parsed according to packet type
        """
        logger.debug(f"Received message type: {type(message)}")

        # Check if it's a text message (error/control message)
        if isinstance(message, str):
            try:
                parsed = json.loads(message)
                logger.debug(f"Received text message: {parsed}")
                if 'error' in parsed or 'message' in parsed:
                    logger.error(f"Server message: {parsed}")
            except json.JSONDecodeError:
                logger.debug(f"Received text: {message}")
            self.on_message(wsapp, message)
        # Binary data - market data packet
        elif isinstance(message, bytes):
            try:
                parsed_message = self._parse_binary_data(message)
                self.on_data(wsapp, parsed_message)
            except Exception as e:
                logger.error(f"Error parsing binary data: {e}")
        else:
            logger.warning(f"Unknown message type: {type(message)}")

    def _on_open(self, wsapp):
        """Callback when WebSocket connection is opened"""
        logger.info("Paytm WebSocket connection opened")
        if self.RESUBSCRIBE_FLAG:
            self.resubscribe()
        else:
            self.on_open(wsapp)

    def _on_error(self, wsapp, error):
        """Handle WebSocket errors with retry logic"""
        logger.error(f"WebSocket error: {error}")
        self.RESUBSCRIBE_FLAG = True

        if self.current_retry_attempt < self.MAX_RETRY_ATTEMPT:
            logger.warning(f"Attempting to reconnect (Attempt {self.current_retry_attempt + 1})...")
            self.current_retry_attempt += 1
            delay = self.retry_delay * (self.retry_multiplier ** (self.current_retry_attempt - 1))
            time.sleep(delay)

            try:
                self.close_connection()
                self.connect()
            except Exception as e:
                logger.error(f"Error during reconnect: {e}")
                if hasattr(self, 'on_error'):
                    self.on_error(wsapp, str(e) if str(e) else "Unknown error")
        else:
            self.close_connection()
            if hasattr(self, 'on_error'):
                self.on_error(wsapp, "Max retry attempts reached")

    def _on_close(self, wsapp, close_status_code=None, close_msg=None):
        """Callback when WebSocket connection is closed"""
        logger.info(f"WebSocket connection closed. Code: {close_status_code}, Message: {close_msg}")
        self.on_close(wsapp)

    def _on_ping(self, wsapp, message):
        """Handle ping from server"""
        logger.debug(f"Received ping: {message}")

    def _on_pong(self, wsapp, message):
        """Handle pong from server"""
        logger.debug(f"Received pong: {message}")
        self.last_pong_timestamp = time.time()

    def subscribe(self, preferences):
        """
        Subscribe to market data

        Parameters
        ----------
        preferences: list of dict
            List of preference dictionaries with the following structure:
            [
                {
                    "actionType": "ADD",
                    "modeType": "FULL",
                    "scripType": "INDEX",
                    "exchangeType": "NSE",
                    "scripId": "13"
                }
            ]
        """
        try:
            if not isinstance(preferences, list):
                preferences = [preferences]

            # Store subscriptions for resubscription
            for pref in preferences:
                key = f"{pref['exchangeType']}_{pref['scripId']}_{pref['modeType']}"
                self.subscriptions[key] = pref

            # Send subscription request
            self.wsapp.send(json.dumps(preferences))
            self.RESUBSCRIBE_FLAG = True
            logger.info(f"Subscribed to {len(preferences)} preferences")

        except Exception as e:
            logger.error(f"Error during subscribe: {e}")
            raise e

    def unsubscribe(self, preferences):
        """
        Unsubscribe from market data

        Parameters
        ----------
        preferences: list of dict
            List of preference dictionaries with actionType set to "REMOVE"
        """
        try:
            if not isinstance(preferences, list):
                preferences = [preferences]

            # Update action type to REMOVE
            for pref in preferences:
                pref['actionType'] = self.REMOVE_ACTION
                key = f"{pref['exchangeType']}_{pref['scripId']}_{pref['modeType']}"
                if key in self.subscriptions:
                    del self.subscriptions[key]

            # Send unsubscribe request
            self.wsapp.send(json.dumps(preferences))
            logger.info(f"Unsubscribed from {len(preferences)} preferences")

        except Exception as e:
            logger.error(f"Error during unsubscribe: {e}")
            raise e

    def resubscribe(self):
        """Resubscribe to all stored subscriptions"""
        try:
            if self.subscriptions:
                preferences = list(self.subscriptions.values())
                self.wsapp.send(json.dumps(preferences))
                logger.info(f"Resubscribed to {len(preferences)} preferences")
        except Exception as e:
            logger.error(f"Error during resubscribe: {e}")
            raise e

    def connect(self):
        """Establish WebSocket connection"""
        try:
            # Construct WebSocket URL with public access token
            url = f"{self.ROOT_URI}?x_jwt_token={self.public_access_token}"

            logger.debug(f"Connecting to Paytm WebSocket: {url}")

            self.wsapp = websocket.WebSocketApp(
                url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_ping=self._on_ping,
                on_pong=self._on_pong
            )

            # Run WebSocket in a separate thread to avoid blocking
            self.wsapp.run_forever(
                sslopt={"cert_reqs": ssl.CERT_NONE},
                ping_interval=self.HEART_BEAT_INTERVAL
            )

        except Exception as e:
            logger.error(f"Error during WebSocket connection: {e}")
            raise e

    def close_connection(self):
        """Close WebSocket connection"""
        self.RESUBSCRIBE_FLAG = False
        self.DISCONNECT_FLAG = True
        if self.wsapp:
            self.wsapp.close()
            logger.info("WebSocket connection closed")

    def _parse_binary_data(self, binary_data):
        """
        Parse binary data according to Paytm's packet structure

        Based on the documentation, different packet types have different structures:
        - LTP: 23 bytes
        - LTP INDEX: 23 bytes
        - QUOTE: 67 bytes
        - INDEX QUOTE: 43 bytes
        - FULL: 175 bytes
        - FULL INDEX: 39 bytes

        The first byte indicates the packet code/type
        """
        if len(binary_data) < 1:
            logger.error("Binary data too short")
            return {}

        packet_code = struct.unpack('B', binary_data[0:1])[0]

        logger.debug(f"Parsing packet code: {packet_code}, length: {len(binary_data)}")

        # Route to appropriate parser based on packet code
        if packet_code == self.PACKET_CODE_LTP:
            return self._parse_ltp_packet(binary_data)
        elif packet_code == self.PACKET_CODE_INDEX_LTP:
            return self._parse_index_ltp_packet(binary_data)
        elif packet_code == self.PACKET_CODE_QUOTE:
            return self._parse_quote_packet(binary_data)
        elif packet_code == self.PACKET_CODE_INDEX_QUOTE:
            return self._parse_index_quote_packet(binary_data)
        elif packet_code == self.PACKET_CODE_FULL:
            return self._parse_full_packet(binary_data)
        elif packet_code == self.PACKET_CODE_INDEX_FULL:
            return self._parse_index_full_packet(binary_data)
        else:
            logger.warning(f"Unknown packet code: {packet_code}")
            return {}

    def _unpack(self, binary_data, start, end, format_char):
        """Helper to unpack binary data"""
        return struct.unpack(self.LITTLE_ENDIAN_BYTE_ORDER + format_char, binary_data[start:end])[0]

    def _parse_ltp_packet(self, data):
        """Parse LTP packet (23 bytes)"""
        return {
            'packet_code': self._unpack(data, 0, 1, 'B'),
            'last_price': self._unpack(data, 1, 5, 'f'),
            'last_traded_time': self._unpack(data, 5, 9, 'I'),
            'security_id': self._unpack(data, 9, 13, 'I'),
            'tradable': self._unpack(data, 13, 14, 'B'),
            'mode': self._unpack(data, 14, 15, 'B'),
            'change_absolute': self._unpack(data, 15, 19, 'f'),
            'change_percent': self._unpack(data, 19, 23, 'f'),
            'subscription_mode': 1,
            'subscription_mode_val': 'LTP'
        }

    def _parse_index_ltp_packet(self, data):
        """Parse INDEX LTP packet (23 bytes)"""
        return {
            'packet_code': self._unpack(data, 0, 1, 'B'),
            'last_price': self._unpack(data, 1, 5, 'f'),
            'last_update_time': self._unpack(data, 5, 9, 'I'),
            'security_id': self._unpack(data, 9, 13, 'I'),
            'tradable': self._unpack(data, 13, 14, 'B'),
            'mode': self._unpack(data, 14, 15, 'B'),
            'change_absolute': self._unpack(data, 15, 19, 'f'),
            'change_percent': self._unpack(data, 19, 23, 'f'),
            'subscription_mode': 1,
            'subscription_mode_val': 'LTP',
            'is_index': True
        }

    def _parse_quote_packet(self, data):
        """Parse QUOTE packet (67 bytes)"""
        security_id = self._unpack(data, 9, 13, 'I')
        logger.debug(f"Parsing QUOTE: security_id bytes [9:13] = {data[9:13].hex()}, parsed as uint = {security_id}")

        parsed = {
            'packet_code': self._unpack(data, 0, 1, 'B'),
            'last_price': self._unpack(data, 1, 5, 'f'),
            'last_traded_time': self._unpack(data, 5, 9, 'I'),
            'security_id': security_id,
            'tradable': self._unpack(data, 13, 14, 'B'),
            'mode': self._unpack(data, 14, 15, 'B'),
            'last_traded_quantity': self._unpack(data, 15, 19, 'I'),
            'average_traded_price': self._unpack(data, 19, 23, 'f'),
            'volume_traded': self._unpack(data, 23, 27, 'I'),
            'total_buy_quantity': self._unpack(data, 27, 31, 'I'),
            'total_sell_quantity': self._unpack(data, 31, 35, 'I'),
            'open': self._unpack(data, 35, 39, 'f'),
            'close': self._unpack(data, 39, 43, 'f'),
            'high': self._unpack(data, 43, 47, 'f'),
            'low': self._unpack(data, 47, 51, 'f'),
            'change_absolute': self._unpack(data, 55, 59, 'f'),
            'change_percent': self._unpack(data, 51, 55, 'f'),
            '52_week_high': self._unpack(data, 59, 63, 'f'),
            '52_week_low': self._unpack(data, 63, 67, 'f'),
            'subscription_mode': 2,
            'subscription_mode_val': 'QUOTE'
        }
        return parsed

    def _parse_index_quote_packet(self, data):
        """Parse INDEX QUOTE packet (43 bytes)"""
        return {
            'packet_code': self._unpack(data, 0, 1, 'B'),
            'last_price': self._unpack(data, 1, 5, 'f'),
            'security_id': self._unpack(data, 5, 9, 'I'),
            'tradable': self._unpack(data, 9, 10, 'B'),
            'mode': self._unpack(data, 10, 11, 'B'),
            'open': self._unpack(data, 11, 15, 'f'),
            'close': self._unpack(data, 15, 19, 'f'),
            'high': self._unpack(data, 19, 23, 'f'),
            'low': self._unpack(data, 23, 27, 'f'),
            'change_absolute': self._unpack(data, 27, 31, 'f'),
            'change_percent': self._unpack(data, 31, 35, 'f'),
            '52_week_high': self._unpack(data, 35, 39, 'f'),
            '52_week_low': self._unpack(data, 39, 43, 'f'),
            'subscription_mode': 2,
            'subscription_mode_val': 'QUOTE',
            'is_index': True
        }

    def _parse_full_packet(self, data):
        """
        Parse FULL packet (175 bytes) - includes market depth

        Structure per Paytm documentation:
        Offset 0: Packet Code (byte)
        Offset 1-100: MBP_ROW_PACKET[] (5 × 20 bytes depth)
        Offset 101-104: last_price (Float)
        Offset 105-108: last_traded_time (Integer)
        Offset 109-112: security_id (Integer)
        Offset 113: tradable (byte)
        Offset 114: mode (byte)
        Offset 115-118: last_traded_quantity (Integer)
        Offset 119-122: average_traded_price (Float)
        Offset 123-126: volume_traded (Integer)
        Offset 127-130: total_buy_quantity (Integer)
        Offset 131-134: total_sell_quantity (Integer)
        Offset 135-138: open (Float)
        Offset 139-142: close (Float)
        Offset 143-146: high (Float)
        Offset 147-150: low (Float)
        Offset 151-154: change_percent (Float)
        Offset 155-158: change_absolute (Float)
        Offset 159-162: 52_week_high (Float)
        Offset 163-166: 52_week_low (Float)
        Offset 167-170: OI (Integer)
        Offset 171-174: OI_change (Integer)
        """

        # Parse market depth FIRST (offset 1-100)
        # MBP_ROW_PACKET structure: 20 bytes per level
        # Offset 0-3: Buy Quantity (int)
        # Offset 4-7: Sell Quantity (int)
        # Offset 8-9: Buy Orders (short)
        # Offset 10-11: Sell Orders (short)
        # Offset 12-15: Buy Price (float)
        # Offset 16-19: Sell Price (float)

        depth_start = 1  # After packet code
        buy_depth = []
        sell_depth = []

        for i in range(5):
            offset = depth_start + (i * 20)
            buy_depth.append({
                'quantity': self._unpack(data, offset, offset + 4, 'i'),
                'price': self._unpack(data, offset + 12, offset + 16, 'f'),
                'orders': self._unpack(data, offset + 8, offset + 10, 'h')
            })
            sell_depth.append({
                'quantity': self._unpack(data, offset + 4, offset + 8, 'i'),
                'price': self._unpack(data, offset + 16, offset + 20, 'f'),
                'orders': self._unpack(data, offset + 10, offset + 12, 'h')
            })

        # Parse QUOTE-like data (offset 101-166)
        security_id = self._unpack(data, 109, 113, 'I')
        logger.debug(f"Parsing FULL: security_id bytes [109:113] = {data[109:113].hex()}, parsed as uint = {security_id}")

        parsed = {
            'packet_code': self._unpack(data, 0, 1, 'B'),
            'last_price': self._unpack(data, 101, 105, 'f'),
            'last_traded_time': self._unpack(data, 105, 109, 'I'),
            'security_id': security_id,
            'tradable': self._unpack(data, 113, 114, 'B'),
            'mode': self._unpack(data, 114, 115, 'B'),
            'last_traded_quantity': self._unpack(data, 115, 119, 'I'),
            'average_traded_price': self._unpack(data, 119, 123, 'f'),
            'volume_traded': self._unpack(data, 123, 127, 'I'),
            'total_buy_quantity': self._unpack(data, 127, 131, 'I'),
            'total_sell_quantity': self._unpack(data, 131, 135, 'I'),
            'open': self._unpack(data, 135, 139, 'f'),
            'close': self._unpack(data, 139, 143, 'f'),
            'high': self._unpack(data, 143, 147, 'f'),
            'low': self._unpack(data, 147, 151, 'f'),
            'change_percent': self._unpack(data, 151, 155, 'f'),
            'change_absolute': self._unpack(data, 155, 159, 'f'),
            '52_week_high': self._unpack(data, 159, 163, 'f'),
            '52_week_low': self._unpack(data, 163, 167, 'f'),
            'subscription_mode': 3,
            'subscription_mode_val': 'FULL'
        }

        # Add depth data
        parsed['depth'] = {
            'buy': buy_depth,
            'sell': sell_depth
        }

        # Add OI data (offset 167-174)
        if len(data) >= 175:
            parsed['oi'] = self._unpack(data, 167, 171, 'I')
            parsed['oi_change'] = self._unpack(data, 171, 175, 'I')

        return parsed

    def _parse_index_full_packet(self, data):
        """Parse INDEX FULL packet (39 bytes)"""
        return {
            'packet_code': self._unpack(data, 0, 1, 'B'),
            'last_price': self._unpack(data, 1, 5, 'f'),
            'security_id': self._unpack(data, 5, 9, 'I'),
            'tradable': self._unpack(data, 9, 10, 'B'),
            'mode': self._unpack(data, 10, 11, 'B'),
            'open': self._unpack(data, 11, 15, 'f'),
            'close': self._unpack(data, 15, 19, 'f'),
            'high': self._unpack(data, 19, 23, 'f'),
            'low': self._unpack(data, 23, 27, 'f'),
            'change_percent': self._unpack(data, 27, 31, 'f'),
            'change_absolute': self._unpack(data, 31, 35, 'f'),
            'last_trade_time': self._unpack(data, 35, 39, 'I'),
            'subscription_mode': 3,
            'subscription_mode_val': 'FULL',
            'is_index': True
        }

    # Callback methods to be overridden
    def on_message(self, wsapp, message):
        """Override this method to handle text messages"""
        pass

    def on_data(self, wsapp, data):
        """Override this method to handle parsed market data"""
        pass

    def on_open(self, wsapp):
        """Override this method to handle connection open"""
        pass

    def on_close(self, wsapp):
        """Override this method to handle connection close"""
        pass

    def on_error(self, wsapp, error):
        """Override this method to handle errors"""
        pass
