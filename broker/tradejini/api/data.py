import json
import os
import time
import threading
import logging
import pandas as pd
import websocket
from datetime import datetime, timedelta
from database.token_db import get_token, get_br_symbol, get_oa_symbol

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TradejiniWebSocket:
    def __init__(self):
        """Initialize WebSocket connection"""
        self.ws = None
        self.auth_token = None
        self.symbol_map = {}
        self.lock = threading.Lock()
        self.connected = False
        self.authenticated = False  # Track authentication status
        self.pending_subscriptions = []
        self.pending_requests = {}
        self.response_event = threading.Event()
        self.last_message_time = 0
        self.request_id = int(time.time() * 1000)
        self.ohlc_data = {}

    def _handle_auth_response(self, data):
        """Handle authentication response"""
        try:
            status = data.get('status', '').lower()
            if status == 'success':
                self.authenticated = True
                logger.info("Successfully authenticated with Tradejini WebSocket")
                # Process any pending subscriptions now that we're authenticated
                self._process_pending_subscriptions()
            else:
                error_msg = data.get('message', 'No error message')
                logger.error(f"Authentication failed: {error_msg}")
                self.authenticated = False
                
            # Signal that we've received an auth response
            self.response_event.set()
            
        except Exception as e:
            logger.error(f"Error handling auth response: {str(e)}", exc_info=True)

    def connect(self, auth_token):
        """Connect to Tradejini WebSocket"""
        try:
            self.auth_token = auth_token
            self.connected = False
            self.authenticated = False
            
            # Create WebSocket connection
            ws_url = "wss://api.tradejini.com/v2.1/stream"
            logger.info(f"Initiating WebSocket connection to Tradejini with token: {auth_token[:10]}...")
            
            # Initialize WebSocket with headers
            header = {
                'User-Agent': 'Mozilla/5.0',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept': '*/*',
                'Connection': 'Upgrade',
                'Upgrade': 'websocket'
            }
            
            # Initialize WebSocket
            self.ws = websocket.WebSocketApp(
                ws_url,
                header=header,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            
            # Start WebSocket connection in a separate thread
            ws_thread = threading.Thread(target=self.ws.run_forever)
            ws_thread.daemon = True
            ws_thread.start()
            
            # Wait for connection
            if not self.response_event.wait(10):
                logger.error("Failed to connect to Tradejini WebSocket within timeout")
                return False
                
            # Wait for authentication
            auth_timeout = time.time() + 10  # 10 seconds for auth
            while not self.authenticated and time.time() < auth_timeout:
                time.sleep(0.1)
                
            if not self.authenticated:
                logger.error("WebSocket authentication failed")
                return False
                
            logger.info("WebSocket connection established successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error connecting to WebSocket: {str(e)}", exc_info=True)
            return False

    def on_open(self, ws):
        """Handle WebSocket open event"""
        try:
            logger.info("WebSocket connection established with Tradejini")
            self.connected = True
            self.last_message_time = time.time()
            
            # Send authentication message
            request_id = str(int(time.time() * 1000))
            auth_msg = {
                "type": "auth",
                "token": self.auth_token,
                "client_id": "openalgo",
                "source": "web",
                "request_id": request_id
            }
            
            # Add to pending requests
            self.pending_requests[request_id] = {
                'event': threading.Event(),
                'data': None,
                'error': None
            }
            
            # Send authentication message
            if not self._send_json(auth_msg):
                logger.error("Failed to send authentication message")
                return
                
            logger.info("Authentication message sent successfully")
            
        except Exception as e:
            logger.error(f"Error in on_open: {str(e)}", exc_info=True)
            self.connected = False
            if hasattr(self, 'on_error'):
                self.on_error(ws, str(e))

    def on_message(self, ws, message):
        """Handle incoming WebSocket messages"""
        try:
            # Log raw message for debugging
            logger.debug(f"Received WebSocket message: {message[:500]}...")
            
            try:
                data = json.loads(message)
                logger.debug(f"Parsed WebSocket data: {data}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse message as JSON: {e}")
                return
                
            msg_type = data.get('type')
            request_id = data.get('request_id')
            
            # Handle different message types
            if msg_type == 'auth':
                self._handle_auth_response(data)
            elif msg_type == 'L1':
                self._process_quote(data)
            elif msg_type == 'L5':
                self._process_depth(data)
            elif msg_type == 'OHLC':
                self._process_ohlc(data)
            elif msg_type == 'error':
                error_msg = data.get('message', 'Unknown error')
                logger.error(f"WebSocket error: {error_msg}")
                if request_id and request_id in self.pending_requests:
                    self.pending_requests[request_id]['error'] = error_msg
                    self.pending_requests[request_id]['event'].set()
            elif request_id and request_id in self.pending_requests:
                # Handle successful response to a request
                self.pending_requests[request_id]['data'] = data
                self.pending_requests[request_id]['event'].set()
            else:
                logger.debug(f"Received unhandled message type: {msg_type}")
                
        except Exception as e:
            logger.error(f"Error in on_message: {str(e)}", exc_info=True)

    def on_error(self, ws, error):
        """Handle WebSocket errors"""
        error_msg = f"Tradejini WebSocket error: {error}"
        logger.error(error_msg)
        print(f"\n!!! WEBSOCKET ERROR: {error_msg}")
        
        # Handle specific error cases
        if isinstance(error, socket.gaierror):
            logger.error("DNS resolution failed - please check your network connection")
        elif isinstance(error, ConnectionRefusedError):
            logger.error("Connection refused - please check if the WebSocket server is running")
        
        self.connected = False
        self.authenticated = False

    def on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket close"""
        logger.info(f"Tradejini WebSocket connection closed: {close_status_code} - {close_msg}")
        self.connected = False
        self.authenticated = False

    def _send_json(self, data):
        """Send JSON data through WebSocket with request tracking"""
        try:
            if not self.connected:
                logger.error("WebSocket not connected")
                return False
                
            json_data = json.dumps(data)
            logger.debug(f"Sending WebSocket message: {json_data[:500]}...")
            
            try:
                self.ws.send(json_data)
                return True
            except Exception as e:
                logger.error(f"Error sending message: {str(e)}")
                self.connected = False
                return False
                
        except Exception as e:
            logger.error(f"Error in _send_json: {str(e)}", exc_info=True)
            return False

    def _process_historical_data(self, data):
        """Process historical OHLC data"""
        try:
            request_id = data.get('request_id')
            status = data.get('status', '').lower()
            
            if status == 'success':
                candles = data.get('data', [])
                df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                # Convert timestamp from milliseconds to datetime
                if not df.empty and 'timestamp' in df.columns:
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                
                with self.lock:
                    if request_id in self.pending_requests:
                        self.pending_requests[request_id]['data'] = df
                        self.pending_requests[request_id]['event'].set()
                        logger.info(f"Received historical data for request {request_id}: {len(df)} candles")
            else:
                error_msg = data.get('message', 'Unknown error')
                logger.error(f"Error in historical data request {request_id}: {error_msg}")
                with self.lock:
                    if request_id in self.pending_requests:
                        self.pending_requests[request_id]['error'] = error_msg
                        self.pending_requests[request_id]['event'].set()
                        
        except Exception as e:
            logger.error(f"Error processing historical data: {str(e)}\nRaw data: {data}", exc_info=True)
            with self.lock:
                if request_id in self.pending_requests:
                    self.pending_requests[request_id]['error'] = str(e)
                    self.pending_requests[request_id]['event'].set()

    def _process_quote(self, data):
        """Process quote data"""
        try:
            symbol = f"{data.get('token')}_{data.get('exchSeg')}"
            quote_data = {
                'bid': float(data.get('bidPrice', 0)),
                'ask': float(data.get('askPrice', 0)),
                'open': float(data.get('open', 0)),
                'high': float(data.get('high', 0)),
                'low': float(data.get('low', 0)),
                'ltp': float(data.get('ltp', 0)),
                'prev_close': float(data.get('close', 0)),
                'volume': int(data.get('vol', 0)),
                'timestamp': data.get('ltt')
            }
            logger.debug(f"Processed quote for {symbol}: {quote_data}")
            
            with self.lock:
                self.last_quote = quote_data
                logger.info(f"Updated last_quote for {symbol}")
                
        except Exception as e:
            logger.error(f"Error processing quote: {str(e)}\nRaw data: {data}", exc_info=True)

    def _process_depth(self, data):
        """Process market depth data"""
        try:
            bids = []
            asks = []
            
            # Process bids (up to 5 levels)
            for i in range(5):
                if i < len(data.get('bidPrices', [])) and i < len(data.get('bidQtys', [])):
                    bids.append({
                        'price': float(data['bidPrices'][i]),
                        'quantity': int(data['bidQtys'][i])
                    })
            
            # Process asks (up to 5 levels)
            for i in range(5):
                if i < len(data.get('askPrices', [])) and i < len(data.get('askQtys', [])):
                    asks.append({
                        'price': float(data['askPrices'][i]),
                        'quantity': int(data['askQtys'][i])
                    })
            
            with self.lock:
                self.last_depth = {
                    'bids': bids,
                    'asks': asks,
                    'totalbuyqty': sum(bid['quantity'] for bid in bids),
                    'totalsellqty': sum(ask['quantity'] for ask in asks),
                    'ltp': float(data.get('ltp', 0)),
                    'volume': int(data.get('vol', 0))
                }
        except Exception as e:
            logger.error(f"Error processing depth: {e}")

    def subscribe_quotes(self, tokens):
        """
        Subscribe to quote updates for given tokens
        
        Args:
            tokens: List of dicts with 'token' and 'exchange' or list of token strings
        """
        if not self.connected:
            logger.error("WebSocket not connected")
            return False
            
        try:
            # Format tokens for subscription
            formatted_tokens = []
            for token in tokens:
                if isinstance(token, dict) and 'token' in token and 'exchange' in token:
                    token_str = str(token['token'])
                    exchange = token['exchange']
                    formatted_tokens.append({"t": token_str, "exch": exchange})
                    logger.info(f"Subscribing to {token_str} on {exchange}")
                elif isinstance(token, str):
                    # Assume format "TOKEN:EXCHANGE" or just TOKEN (default to NSE)
                    parts = token.split(':')
                    if len(parts) == 2:
                        token_str = parts[0].strip()
                        exchange = parts[1].strip()
                    else:
                        token_str = token.strip()
                        exchange = "NSE"
                    formatted_tokens.append({"t": token_str, "exch": exchange})
                    logger.info(f"Subscribing to {token_str} on {exchange}")
            
            if not formatted_tokens:
                logger.error("No valid tokens provided for subscription")
                return False
                
            # Create subscription message
            request_id = str(int(time.time() * 1000))
            sub_msg = {
                "type": "L1",
                "action": "sub",
                "tokens": formatted_tokens,
                "request_id": request_id
            }
            
            # Add to pending requests
            self.pending_requests[request_id] = {
                'event': threading.Event(),
                'data': None,
                'error': None
            }
            
            # Send subscription message
            if not self._send_json(sub_msg):
                return False
                
            # Wait for response with timeout
            if not self.pending_requests[request_id]['event'].wait(5):  # Reduced timeout to 5 seconds
                logger.warning("Timeout waiting for subscription confirmation")
                return False
                
            # Check for errors
            if self.pending_requests[request_id].get('error'):
                logger.error(f"Subscription failed: {self.pending_requests[request_id]['error']}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error in subscribe_quotes: {str(e)}", exc_info=True)
            return False
        finally:
            # Clean up pending request
            if 'request_id' in locals() and request_id in self.pending_requests:
                del self.pending_requests[request_id]

    def subscribe_ohlc(self, tokens, interval):
        """
        Subscribe to OHLC data for given tokens and interval
        
        Args:
            tokens: List of dicts with 'token' and 'exchange' or list of token strings
            interval: Chart interval (1m, 5m, 15m, 30m, 60m, 1d)
        """
        if not self.connected:
            logger.error("WebSocket not connected")
            return False
            
        try:
            # Format tokens for subscription
            formatted_tokens = []
            for token in tokens:
                if isinstance(token, dict) and 'token' in token and 'exchange' in token:
                    token_str = str(token['token'])
                    exchange = token['exchange']
                    formatted_tokens.append({"t": token_str, "exch": exchange})
                    logger.info(f"Subscribing to OHLC {token_str} on {exchange} with interval {interval}")
                elif isinstance(token, str):
                    # Assume format "TOKEN:EXCHANGE" or just TOKEN (default to NSE)
                    parts = token.split(':')
                    if len(parts) == 2:
                        token_str = parts[0].strip()
                        exchange = parts[1].strip()
                    else:
                        token_str = token.strip()
                        exchange = "NSE"
                    formatted_tokens.append({"t": token_str, "exch": exchange})
                    logger.info(f"Subscribing to OHLC {token_str} on {exchange} with interval {interval}")
            
            if not formatted_tokens:
                logger.error("No valid tokens provided for OHLC subscription")
                return False
                
            # Create subscription message
            request_id = str(int(time.time() * 1000))
            sub_msg = {
                "type": "OHLC",
                "action": "sub",
                "tokens": formatted_tokens,
                "chartInterval": interval,
                "request_id": request_id
            }
            
            # Add to pending requests
            self.pending_requests[request_id] = {
                'event': threading.Event(),
                'data': None,
                'error': None
            }
            
            # Send subscription message
            if not self._send_json(sub_msg):
                return False
                
            # Wait for response with timeout
            if not self.pending_requests[request_id]['event'].wait(10):
                logger.warning("Timeout waiting for OHLC subscription confirmation")
                return False
                
            # Check for errors
            if self.pending_requests[request_id].get('error'):
                logger.error(f"OHLC subscription failed: {self.pending_requests[request_id]['error']}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error in subscribe_ohlc: {str(e)}", exc_info=True)
            return False
        finally:
            # Clean up pending request
            if 'request_id' in locals() and request_id in self.pending_requests:
                del self.pending_requests[request_id]

    def unsubscribe_ohlc(self, interval):
        """
        Unsubscribe from OHLC data for a specific interval
        
        Args:
            interval: Chart interval to unsubscribe from (1m, 5m, 15m, 30m, 60m, 1d)
        """
        try:
            request_id = str(int(time.time() * 1000))
            unsub_msg = {
                "type": "OHLC",
                "action": "unsub",
                "chartInterval": interval,
                "request_id": request_id
            }
            
            # Add to pending requests
            self.pending_requests[request_id] = {
                'event': threading.Event(),
                'data': None,
                'error': None
            }
            
            # Send unsubscribe message
            if not self._send_json(unsub_msg):
                return False
                
            # Wait for response with timeout
            if not self.pending_requests[request_id]['event'].wait(10):
                logger.warning("Timeout waiting for OHLC unsubscription confirmation")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error in unsubscribe_ohlc: {str(e)}", exc_info=True)
            return False
        finally:
            # Clean up pending request
            if 'request_id' in locals() and request_id in self.pending_requests:
                del self.pending_requests[request_id]

    def _process_ohlc(self, data):
        """Process OHLC data packet"""
        try:
            ohlc_data = {
                'token': str(data.get('token', '')),
                'exchange': data.get('exchSeg', ''),
                'open': float(data.get('open', 0)),
                'high': float(data.get('high', 0)),
                'low': float(data.get('low', 0)),
                'close': float(data.get('close', 0)),
                'volume': int(data.get('vol', 0)),
                'timestamp': data.get('time', ''),
                'interval': data.get('chartInterval', '')
            }
            
            symbol = f"{ohlc_data['token']}_{ohlc_data['exchange']}"
            
            # Store the latest OHLC data
            with self.lock:
                if not hasattr(self, 'ohlc_data'):
                    self.ohlc_data = {}
                if symbol not in self.ohlc_data:
                    self.ohlc_data[symbol] = {}
                self.ohlc_data[symbol][ohlc_data['interval']] = ohlc_data
                
            logger.debug(f"Processed OHLC data for {symbol} ({ohlc_data['interval']}): {ohlc_data}")
            
            # Trigger callback if set
            if hasattr(self, 'on_ohlc'):
                self.on_ohlc(ohlc_data)
                
        except Exception as e:
            logger.error(f"Error processing OHLC data: {str(e)}\nRaw data: {data}", exc_info=True)

    def _send_message(self, message):
        """Send message to WebSocket with request tracking"""
        try:
            request_id = self._send_json(message)
            if not request_id:
                return False
                
            # If this is a request that expects a response
            if 'request_id' in message and message.get('expect_response', True):
                try:
                    # Wait for response with timeout
                    if not self.pending_requests[request_id]['event'].wait(10):  # 10 second timeout
                        logger.warning(f"Timeout waiting for response to request {request_id}")
                        return False
                        
                    # Check for errors in the response
                    if self.pending_requests[request_id].get('error'):
                        logger.error(f"Request {request_id} failed: {self.pending_requests[request_id]['error']}")
                        return False
                        
                    return True
                finally:
                    # Clean up the pending request
                    if request_id in self.pending_requests:
                        del self.pending_requests[request_id]
            return True
            
        except Exception as e:
            logger.error(f"Error in _send_message: {str(e)}", exc_info=True)
            return False

    def subscribe_quote(self, symbol, exchange, token):
        """Subscribe to real-time quotes for a single symbol"""
        return self.subscribe_quotes([{"token": token, "exchange": exchange}])
        
    def subscribe_depth(self, symbol, exchange, token):
        """Subscribe to market depth"""
        try:
            # Create subscription message
            request_id = str(int(time.time() * 1000))
            sub_msg = {
                "type": "L5",
                "action": "sub",
                "tokens": [{"t": str(token), "exch": exchange}],
                "request_id": request_id
            }
            
            # Add to pending requests
            self.pending_requests[request_id] = {
                'event': threading.Event(),
                'data': None,
                'error': None
            }
            
            # Send subscription message
            if not self._send_json(sub_msg):
                return False
                
            # Wait for response with timeout
            if not self.pending_requests[request_id]['event'].wait(10):
                logger.warning("Timeout waiting for depth subscription confirmation")
                return False
                
            # Check for errors
            if self.pending_requests[request_id].get('error'):
                logger.error(f"Depth subscription failed: {self.pending_requests[request_id]['error']}")
                return False
                
            return True
            
        except Exception as e:
            logger.error(f"Error in subscribe_depth: {str(e)}", exc_info=True)
            return False
        finally:
            # Clean up pending request
            if 'request_id' in locals() and request_id in self.pending_requests:
                del self.pending_requests[request_id]

    def request_historical_data(self, token, exchange, interval, from_date, to_date):
        """
        Request historical OHLC data
        
        Args:
            token: Trading symbol token
            exchange: Exchange (NSE, BSE, etc.)
            interval: Time interval (1m, 5m, 15m, 30m, 60m, 1d)
            from_date: Start date (YYYY-MM-DD or timestamp in ms)
            to_date: End date (YYYY-MM-DD or timestamp in ms)
            
        Returns:
            tuple: (success, data_or_error)
        """
        try:
            # Generate a unique request ID
            request_id = str(int(time.time() * 1000))
            
            # Create event to wait for response
            self.pending_requests[request_id] = {
                'event': threading.Event(),
                'data': None,
                'error': None
            }
            
            # Prepare historical data request
            hist_msg = {
                'type': 'historical',
                'request_id': request_id,
                'token': str(token),
                'exchange': exchange,
                'interval': interval,
                'from': from_date,
                'to': to_date,
                'expect_response': True
            }
            
            logger.info(f"Requesting historical data: {hist_msg}")
            
            # Send the request
            if not self._send_json(hist_msg):
                return False, "Failed to send historical data request"
            
            # Wait for response with timeout (30 seconds)
            if not self.pending_requests[request_id]['event'].wait(30):
                return False, "Request timed out"
            
            # Get response data
            result = self.pending_requests[request_id]
            
            if 'error' in result and result['error']:
                return False, result['error']
                
            return True, result.get('data', pd.DataFrame())
            
        except Exception as e:
            logger.error(f"Error in request_historical_data: {str(e)}", exc_info=True)
            return False, str(e)
        finally:
            # Clean up
            if 'request_id' in locals() and request_id in self.pending_requests:
                del self.pending_requests[request_id]

    def close(self):
        """Close WebSocket connection"""
        if self.ws:
            self.ws.close()
            self.connected = False
            self.authenticated = False

    def _process_pending_subscriptions(self):
        """Process any pending subscriptions after successful authentication"""
        with self.lock:
            if self.pending_subscriptions:
                logger.info(f"Processing {len(self.pending_subscriptions)} pending subscriptions")
                for sub_msg in self.pending_subscriptions:
                    self._send_json(sub_msg)
                self.pending_subscriptions = []

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Tradejini data handler with authentication token"""
        self.auth_token = auth_token
        self.ws = TradejiniWebSocket()
        
        # Map common timeframe format to Tradejini resolutions
        self.timeframe_map = {
            '1m': '1m',    # 1 minute
            '5m': '5m',    # 5 minutes
            '15m': '15m',  # 15 minutes
            '30m': '30m',  # 30 minutes
            '1h': '60m',   # 1 hour
            'D': '1d'      # Daily
        }

    def connect_websocket(self):
        """Initialize WebSocket connection if not already connected"""
        if not hasattr(self, 'ws') or not self.ws.connected:
            self.ws = TradejiniWebSocket()
            self.ws.connect(self.auth_token)

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Quote data with required fields
        """
        try:
            # Convert symbol to broker format and get token
            token = get_token(symbol, exchange)
            if not token:
                raise ValueError(f"Token not found for {symbol} on {exchange}")

            # Map exchange to Tradejini format
            exchange_map = {
                'NSE': 'NSE',
                'BSE': 'BSE',
                'NFO': 'NFO',
                'BFO': 'BFO',
                'CDS': 'CDS',
                'BCD': 'BCD',
                'MCD': 'MCD',
                'MCX': 'MCX',
                'NCO': 'NCO',
                'BCO': 'BCO',
                'NSE_INDEX': 'NSE',
                'BSE_INDEX': 'BSE'
            }
            
            tradejini_exchange = exchange_map.get(exchange)
            if not tradejini_exchange:
                raise ValueError(f"Unsupported exchange: {exchange}")

            # Connect to WebSocket if not already connected
            self.connect_websocket()
            
            # Subscribe to quotes
            self.ws.subscribe_quote(symbol, tradejini_exchange, token)
            
            # Wait for data to arrive
            timeout = time.time() + 5  # 5 seconds timeout
            while not self.ws.last_quote and time.time() < timeout:
                time.sleep(0.1)
            
            if not self.ws.last_quote:
                logger.warning("No quote data received from WebSocket")
                return {
                    'bid': 0, 'ask': 0, 'open': 0,
                    'high': 0, 'low': 0, 'ltp': 0,
                    'prev_close': 0, 'volume': 0
                }
            
            return self.ws.last_quote
            
        except Exception as e:
            logger.error(f"Error in get_quotes: {e}")
            return {
                'bid': 0, 'ask': 0, 'open': 0,
                'high': 0, 'low': 0, 'ltp': 0,
                'prev_close': 0, 'volume': 0
            }

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data with bids, asks and other details
        """
        try:
            # Get token for the symbol
            token = get_token(symbol, exchange)
            if not token:
                raise ValueError(f"Token not found for {symbol} on {exchange}")

            # Map exchange to Tradejini format
            exchange_map = {
                'NSE': 'NSE',
                'BSE': 'BSE',
                'NFO': 'NFO',
                'BFO': 'BFO',
                'CDS': 'CDS',
                'NSE_INDEX': 'NSE',
                'BSE_INDEX': 'BSE'
            }
            tradejini_exchange = exchange_map.get(exchange)
            if not tradejini_exchange:
                raise ValueError(f"Unsupported exchange: {exchange}")

            # Connect to WebSocket if not already connected
            self.connect_websocket()
            
            # Subscribe to market depth
            self.ws.subscribe_depth(symbol, tradejini_exchange, token)
            
            # Wait for data to arrive
            timeout = time.time() + 5  # 5 seconds timeout
            while not self.ws.last_depth and time.time() < timeout:
                time.sleep(0.1)
            
            # Return default structure if no data received
            default_depth = {
                'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'totalbuyqty': 0,
                'totalsellqty': 0,
                'ltp': 0,
                'ltq': 0,
                'volume': 0,
                'open': 0,
                'high': 0,
                'low': 0,
                'prev_close': 0,
                'oi': 0
            }
            
            return self.ws.last_depth or default_depth
            
        except Exception as e:
            logger.error(f"Error in get_depth: {e}")
            return {
                'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'totalbuyqty': 0,
                'totalsellqty': 0,
                'ltp': 0,
                'ltq': 0,
                'volume': 0,
                'open': 0,
                'high': 0,
                'low': 0,
                'prev_close': 0,
                'oi': 0
            }

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical OHLC data for given symbol

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE', 'TATASTEEL')
            exchange: Exchange (e.g., 'NSE', 'BSE')
            interval: Time interval ('1m', '5m', '15m', '30m', '60m', '1d')
            start_date: Start date in 'YYYY-MM-DD' format or timestamp in milliseconds
            end_date: End date in 'YYYY-MM-DD' format or timestamp in milliseconds

        Returns:
            pd.DataFrame: DataFrame with OHLCV data
        """
        try:
            # Convert dates to timestamp in milliseconds if they're strings
            if isinstance(start_date, str):
                start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
            else:
                start_ts = int(start_date)

            if isinstance(end_date, str):
                end_ts = int(pd.Timestamp(end_date).timestamp() * 1000)
            else:
                end_ts = int(end_date)

            # Get token for the symbol
            token = get_token(symbol, exchange)
            if not token:
                logger.error(f"Token not found for {symbol} on {exchange}")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            # Ensure WebSocket is connected
            if not self.ws.connected:
                self.ws.connect(self.auth_token)

            # Map interval to Tradejini format
            interval_map = {
                '1m': '1m',
                '5m': '5m',
                '15m': '15m',
                '30m': '30m',
                '60m': '60m',
                '1h': '60m',
                '1d': '1d',
                'D': '1d'
            }

            tj_interval = interval_map.get(interval, interval)

            # Request historical data
            success, result = self.ws.request_historical_data(
                token=token,
                exchange=exchange.upper(),
                interval=tj_interval,
                from_date=start_ts,
                to_date=end_ts
            )

            if not success:
                logger.error(f"Failed to get historical data: {result}")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            # Ensure we have the required columns
            if not result.empty:
                required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                for col in required_cols:
                    if col not in result.columns:
                        result[col] = 0.0

                # Ensure timestamp is datetime
                if not pd.api.types.is_datetime64_any_dtype(result['timestamp']):
                    result['timestamp'] = pd.to_datetime(result['timestamp'], unit='ms')

                # Sort by timestamp
                result = result.sort_values('timestamp')

                # Set timestamp as index
                result = result.set_index('timestamp')

                # Ensure numeric columns are float
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    result[col] = pd.to_numeric(result[col], errors='coerce')

                logger.info(f"Successfully retrieved {len(result)} rows of historical data for {symbol} ({exchange})")
                return result

            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

        except Exception as e:
            logger.error(f"Error in get_history: {str(e)}", exc_info=True)
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    def get_intervals(self) -> list:
        """
        Get list of supported intervals
        Returns:
            list: List of supported intervals
        """
        return list(self.timeframe_map.keys())

    def subscribe_ohlc(self, symbol: str, exchange: str, interval: str):
        """
        Subscribe to OHLC data for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Time interval ('1m', '5m', '15m', '30m', '60m', '1d')
        """
        try:
            token = get_token(symbol, exchange)
            if not token:
                raise ValueError(f"Token not found for {symbol} on {exchange}")
                
            # Map exchange to Tradejini format
            exchange_map = {
                'NSE': 'NSE',
                'BSE': 'BSE',
                'NFO': 'NFO',
                'BFO': 'BFO',
                'CDS': 'CDS',
                'BCD': 'BCD',
                'MCD': 'MCD',
                'MCX': 'MCX',
                'NCO': 'NCO',
                'BCO': 'BCO'
            }
            
            exchange = exchange_map.get(exchange, exchange)
            
            # Connect WebSocket if not connected
            self.connect_websocket()
            
            # Subscribe to OHLC data
            success = self.ws.subscribe_ohlc(
                tokens=[{"token": token, "exchange": exchange}],
                interval=interval
            )
            
            if not success:
                logger.error(f"Failed to subscribe to OHLC data for {symbol} ({exchange})")
                return False
                
            logger.info(f"Successfully subscribed to OHLC data for {symbol} ({exchange}) with interval {interval}")
            return True
            
        except Exception as e:
            logger.error(f"Error in subscribe_ohlc: {str(e)}", exc_info=True)
            return False
    
    def unsubscribe_ohlc(self, interval: str):
        """
        Unsubscribe from OHLC data for a specific interval
        
        Args:
            interval: Time interval to unsubscribe from ('1m', '5m', '15m', '30m', '60m', '1d')
        """
        try:
            if not hasattr(self, 'ws') or not self.ws.connected:
                logger.warning("WebSocket not connected")
                return False
                
            return self.ws.unsubscribe_ohlc(interval)
            
        except Exception as e:
            logger.error(f"Error in unsubscribe_ohlc: {str(e)}", exc_info=True)
            return False
    
    def get_ohlc(self, symbol: str, exchange: str, interval: str) -> dict:
        """
        Get the latest OHLC data for a symbol
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Time interval ('1m', '5m', '15m', '30m', '60m', '1d')
            
        Returns:
            dict: Latest OHLC data or empty dict if not available
        """
        try:
            if not hasattr(self, 'ws') or not self.ws.connected:
                logger.warning("WebSocket not connected")
                return {}
                
            token = get_token(symbol, exchange)
            if not token:
                logger.error(f"Token not found for {symbol} on {exchange}")
                return {}
                
            exchange_map = {
                'NSE': 'NSE',
                'BSE': 'BSE',
                'NFO': 'NFO',
                'BFO': 'BFO',
                'CDS': 'CDS',
                'BCD': 'BCD',
                'MCD': 'MCD',
                'MCX': 'MCX',
                'NCO': 'NCO',
                'BCO': 'BCO'
            }
            exchange = exchange_map.get(exchange, exchange)
            
            symbol_key = f"{token}_{exchange}"
            
            with self.ws.lock:
                if hasattr(self.ws, 'ohlc_data') and symbol_key in self.ws.ohlc_data:
                    return self.ws.ohlc_data[symbol_key].get(interval, {})
                
            return {}
            
        except Exception as e:
            logger.error(f"Error in get_ohlc: {str(e)}", exc_info=True)
            return {}
