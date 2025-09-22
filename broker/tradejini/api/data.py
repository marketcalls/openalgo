import json
import os
import time
import threading
import pandas as pd
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple, Union
from database.token_db import get_token, get_br_symbol, get_oa_symbol, get_symbol
from utils.httpx_client import get_httpx_client
from broker.tradejini.api.nxtradstream import NxtradStream
from utils.logging import get_logger

logger = get_logger(__name__)

class TradejiniWebSocket:
    def __init__(self):
        """Initialize WebSocket connection using official Tradejini SDK"""
        self.nx_stream = None
        self.auth_token = None
        self.lock = threading.Lock()
        self.connected = False
        self.authenticated = False
        self.last_quote = None
        self.last_depth = None
        self.nxtrad_host = 'api.tradejini.com'
        
        # L1 cache for storing quote data like in original SDK
        self.L1_dict = {}
        self.L5_dict = {}
        
    def connect(self, auth_token):
        """Connect to Tradejini WebSocket using official SDK"""
        try:
            self.auth_token = auth_token
            
            # Get API key from environment if not provided in token
            api_key = os.environ.get('BROKER_API_SECRET', '')
            
            # Format the auth token exactly as per TradeJini requirements
            if ':' not in auth_token and api_key:
                auth_header = f"{api_key}:{auth_token}"
                logger.info("Using API key from BROKER_API_SECRET environment variable")
            elif ':' in auth_token:
                auth_header = auth_token
                logger.info("Using provided API key and access token")
            else:
                error_msg = "Invalid auth token format. Expected 'api_key:access_token' or set BROKER_API_SECRET"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            logger.info(f"Connecting to Tradejini WebSocket using official SDK")
            
            # Create NxtradStream instance with callbacks using official SDK
            self.nx_stream = NxtradStream(
                self.nxtrad_host,
                stream_cb=self._on_data,
                connect_cb=self._on_connection
            )
            
            # Connect with formatted auth token
            logger.info(f"Connecting with auth token format: {auth_header.split(':')[0][:4]}***:{auth_header.split(':')[1][:4]}***")
            self.nx_stream.connect(auth_header)
            
            # Wait for connection
            max_wait = 15
            wait_count = 0
            while not self.connected and wait_count < max_wait:
                time.sleep(1)
                wait_count += 1
                if wait_count % 5 == 0:
                    logger.info(f"Still waiting for connection... ({wait_count}/{max_wait})")
            
            if self.connected:
                logger.info("Successfully connected to Tradejini WebSocket")
                return True
            else:
                logger.error("Failed to connect to Tradejini WebSocket within timeout")
                return False
                
        except Exception as e:
            logger.error(f"Error connecting to WebSocket: {str(e)}", exc_info=True)
            return False

    def _on_connection(self, nx_stream, event):
        """Handle connection events from official SDK"""
        try:
            logger.info(f"Connection event: {event}")
            
            if event.get('s') == "connected":
                self.connected = True
                self.authenticated = True
                logger.info("WebSocket connected and authenticated")
                
            elif event.get('s') == "error":
                self.connected = False
                self.authenticated = False
                logger.error(f"WebSocket error: {event.get('reason', 'Unknown error')}")
                
            elif event.get('s') == "closed":
                self.connected = False
                self.authenticated = False
                reason = event.get('reason', 'Unknown reason')
                logger.warning(f"WebSocket closed: {reason}")
                
                # Auto-reconnect if not unauthorized
                if reason != "Unauthorized Access":
                    logger.info("Attempting to reconnect...")
                    time.sleep(5)
                    if self.nx_stream:
                        self.nx_stream.reconnect()
                        
        except Exception as e:
            logger.error(f"Error in connection callback: {str(e)}", exc_info=True)

    def _on_data(self, nx_stream, data):
        """Handle incoming data from official SDK"""
        try:
            if not isinstance(data, dict):
                return
                
            msg_type = data.get('msgType', '')
            symbol = data.get('symbol', '')
            
            logger.debug(f"Received {msg_type} data for {symbol}")
            
            with self.lock:
                if msg_type == 'L1':
                    # Store quote data exactly like original SDK
                    self.L1_dict[symbol] = data
                    self.last_quote = data
                    logger.info(f"Updated L1 data for {symbol}: LTP={data.get('ltp', 0)}")
                    
                elif msg_type == 'L5':
                    # Store depth data
                    self.L5_dict[symbol] = data
                    self.last_depth = data
                    logger.info(f"Updated L5 data for {symbol}")
                    
        except Exception as e:
            logger.error(f"Error processing data: {str(e)}", exc_info=True)

    def subscribe_quotes(self, tokens):
        """Subscribe to L1 quotes using official SDK"""
        try:
            if not self.connected or not self.nx_stream:
                logger.error("WebSocket not connected")
                return False
            
            # Format tokens exactly like original SDK
            formatted_tokens = []
            for token in tokens:
                if isinstance(token, str):
                    formatted_tokens.append(token)
                else:
                    formatted_tokens.append(str(token))
            
            logger.info(f"Subscribing to L1 quotes for tokens: {formatted_tokens}")
            
            # Subscribe using official SDK
            success = self.nx_stream.subscribeL1(formatted_tokens)
            
            if success:
                logger.info("L1 subscription successful")
                return True
            else:
                logger.error("L1 subscription failed")
                return False
                
        except Exception as e:
            logger.error(f"Error subscribing to quotes: {str(e)}", exc_info=True)
            return False

    def subscribe_depth(self, symbol, exchange, token):
        """Subscribe to L5 market depth using official SDK"""
        try:
            if not self.connected or not self.nx_stream:
                logger.error("WebSocket not connected")
                return False
            
            # Format token as per Tradejini requirement
            formatted_token = f"{token}_{exchange}"
            
            logger.info(f"Subscribing to L5 depth for {formatted_token}")
            
            # Subscribe using official SDK
            success = self.nx_stream.subscribeL2([formatted_token])
            
            if success:
                logger.info("L5 subscription successful")
                return True
            else:
                logger.error("L5 subscription failed")
                return False
                
        except Exception as e:
            logger.error(f"Error subscribing to depth: {str(e)}", exc_info=True)
            return False

    def close(self):
        """Close WebSocket connection"""
        try:
            if self.nx_stream:
                self.nx_stream.disconnect()
            self.connected = False
            self.authenticated = False
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error closing WebSocket: {str(e)}")


class BrokerData:
    def __init__(self, auth_token):
        """Initialize Tradejini data handler with authentication token"""
        self.auth_token = auth_token
        self.ws = TradejiniWebSocket()
        
        # Map supported timeframe formats for Tradejini
        # Note: Tradejini only supports 1m, 5m, and 30m intervals
        self.timeframe_map = {
            '1m': '1m',    # 1 minute
            '5m': '5m',    # 5 minutes
            '30m': '30m'   # 30 minutes
        }

    def connect_websocket(self):
        """Initialize WebSocket connection if not already connected"""
        try:
            if hasattr(self, 'ws') and self.ws.connected:
                logger.debug("WebSocket is already connected")
                return True
                
            logger.info("Initializing new WebSocket connection...")
            
            # Initialize new WebSocket instance
            self.ws = TradejiniWebSocket()
            
            # Connect using the auth token
            logger.info("Connecting to TradeJini WebSocket...")
            success = self.ws.connect(self.auth_token)
            
            if success and self.ws.connected:
                logger.info("Successfully connected to TradeJini WebSocket")
                return True
            else:
                error_msg = "Failed to establish WebSocket connection"
                logger.error(error_msg)
                return False
                
        except Exception as e:
            error_msg = f"Error in connect_websocket: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False

    def _format_quote(self, quote_data: dict, symbol: str, exchange: str) -> dict:
        """Format quote data from Tradejini to OpenAlgo standard format"""
        try:
            logger.debug(f"Formatting quote data for {symbol}")

            # Extract values with defaults - matching OpenAlgo format
            ltp = float(quote_data.get('ltp', 0))
            open_price = float(quote_data.get('open', 0))
            high = float(quote_data.get('high', 0))
            low = float(quote_data.get('low', 0))
            prev_close = float(quote_data.get('close', 0))  # Use 'close' as prev_close
            volume = int(quote_data.get('vol', 0) or 0)
            oi = int(quote_data.get('OI', 0) or 0)  # Add Open Interest

            # Get bid/ask data
            bid = float(quote_data.get('bidPrice', 0))
            ask = float(quote_data.get('askPrice', 0))

            # Format the quote to match OpenAlgo response exactly
            formatted_quote = {
                'ask': ask,
                'bid': bid,
                'high': high,
                'low': low,
                'ltp': ltp,
                'open': open_price,
                'prev_close': prev_close,
                'volume': volume,
                'oi': oi  # Include OI in the response
            }

            logger.debug(f"Formatted quote for {symbol}: LTP={ltp}, Volume={volume}, OI={oi}")
            return formatted_quote

        except Exception as e:
            logger.error(f"Error formatting quote data: {str(e)}", exc_info=True)
            # Return minimal valid quote data in OpenAlgo format
            return {
                'ask': 0.0,
                'bid': 0.0,
                'high': 0.0,
                'low': 0.0,
                'ltp': 0.0,
                'open': 0.0,
                'prev_close': 0.0,
                'volume': 0,
                'oi': 0  # Include OI with default value
            }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """Get real-time quotes for given symbol"""
        try:
            logger.info(f"Getting quotes for {symbol} on {exchange}")
            
            # Get token for the symbol
            token = get_token(symbol, exchange)
            if not token:
                error_msg = f"Token not found for {symbol} on {exchange}"
                logger.error(error_msg)
                raise ValueError(error_msg)

            logger.info(f"Found token: {token} for {symbol} on {exchange}")

            # Connect to WebSocket if not already connected
            if not self.ws.connected:
                logger.info("WebSocket not connected, attempting to connect...")
                if not self.connect_websocket():
                    error_msg = "Failed to connect to WebSocket"
                    raise ConnectionError(error_msg)

            # Wait a moment for any initial setup messages to be processed
            logger.info("Waiting for initial setup to complete...")
            time.sleep(3)

            # Clear existing quote data
            with self.ws.lock:
                self.ws.last_quote = None
                self.ws.L1_dict.clear()  # Clear all cached data
                logger.info("Cleared all cached quote data")

            # Subscribe to quotes - format as per Tradejini requirements
            symbol_key = f"{token}_{exchange}"
            logger.info(f"Subscribing to quotes for: {symbol_key}")
            subscription_success = self.ws.subscribe_quotes([symbol_key])
            
            if not subscription_success:
                error_msg = "Failed to send subscription request"
                logger.error(error_msg)
                raise ConnectionError(error_msg)
            
            logger.info("Quote subscription sent successfully, waiting for data...")
            
            # Wait for quote data with retries
            max_retries = 40
            retry_count = 0
            
            # Possible symbol key formats the data might arrive with
            symbol_keys = [
                symbol_key,          # token_exchange format
                f"{token}_NSE",      # Most likely format
                f"{token}_{exchange}",
                str(token),
                f"{exchange}_{token}",
                f"NSE_{token}",
            ]
            
            logger.info(f"Will look for data with these symbol keys: {symbol_keys}")
            
            while retry_count < max_retries:
                time.sleep(1.0)
                
                with self.ws.lock:
                    # Check L1 cache with different key formats
                    for check_key in symbol_keys:
                        if check_key in self.ws.L1_dict:
                            quote_data = self.ws.L1_dict[check_key]
                            logger.info(f"Found quote in L1 cache with key '{check_key}': LTP={quote_data.get('ltp', 0)}")
                            return self._format_quote(quote_data, symbol, exchange)
                    
                    # Check last_quote as fallback
                    if self.ws.last_quote is not None:
                        quote_data = self.ws.last_quote
                        quote_symbol = quote_data.get('symbol', '')
                        logger.info(f"Found quote in last_quote with symbol: '{quote_symbol}'")
                        # Check if it matches any of our expected keys
                        if any(quote_symbol == key for key in symbol_keys):
                            logger.info(f"Quote matches expected symbol, LTP={quote_data.get('ltp', 0)}")
                            return self._format_quote(quote_data, symbol, exchange)
                        else:
                            logger.debug(f"Quote symbol '{quote_symbol}' doesn't match expected keys: {symbol_keys}")
                
                retry_count += 1
                if retry_count % 10 == 0:  # Log every 10 attempts
                    logger.info(f"Still waiting for quote data... (attempt {retry_count}/{max_retries})")
                    logger.info(f"L1 cache keys: {list(self.ws.L1_dict.keys())}")
                    if self.ws.last_quote:
                        logger.info(f"Last quote symbol: '{self.ws.last_quote.get('symbol', 'None')}'")
                    else:
                        logger.info(f"Last quote: None")

            # If no data received, return default quote in OpenAlgo format
            logger.warning(f"No quote data received for {symbol} after {max_retries} attempts")
            logger.info(f"Final L1 cache keys: {list(self.ws.L1_dict.keys())}")
            
            return {
                'ask': 0.0,
                'bid': 0.0,
                'high': 0.0,
                'low': 0.0,
                'ltp': 0.0,
                'open': 0.0,
                'prev_close': 0.0,
                'volume': 0
            }
            
        except Exception as e:
            logger.error(f"Error in get_quotes: {str(e)}", exc_info=True)
            return {
                'ask': 0.0,
                'bid': 0.0,
                'high': 0.0,
                'low': 0.0,
                'ltp': 0.0,
                'open': 0.0,
                'prev_close': 0.0,
                'volume': 0
            }

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Get market depth for given symbol"""
        try:
            logger.info(f"Getting depth for {symbol} on {exchange}")
            
            # Get token for the symbol
            token = get_token(symbol, exchange)
            if not token:
                raise ValueError(f"Token not found for {symbol} on {exchange}")

            # Connect to WebSocket if not already connected
            if not self.ws.connected:
                if not self.connect_websocket():
                    raise ConnectionError("Failed to establish WebSocket connection")
            
            # Clear existing depth data
            with self.ws.lock:
                self.ws.last_depth = None
                self.ws.L5_dict.clear()
            
            # Subscribe to market depth
            logger.info(f"Subscribing to depth for {symbol} (token: {token})")
            success = self.ws.subscribe_depth(symbol, exchange, token)
            
            if not success:
                raise ConnectionError("Failed to send depth subscription")
            
            logger.info("Depth subscription sent successfully, waiting for data...")
            
            # Wait for depth data
            max_retries = 20
            retry_count = 0
            symbol_key = f"{token}_{exchange}"
            
            while retry_count < max_retries:
                time.sleep(1.0)
                
                with self.ws.lock:
                    # Check L5 cache
                    if symbol_key in self.ws.L5_dict:
                        depth_data = self.ws.L5_dict[symbol_key]
                        logger.info(f"Found depth data for {symbol}")
                        return self._format_depth(depth_data, symbol, exchange)
                    
                    # Check last_depth as fallback
                    if self.ws.last_depth is not None:
                        logger.info(f"Found depth data in last_depth for {symbol}")
                        return self._format_depth(self.ws.last_depth, symbol, exchange)
                
                retry_count += 1
                if retry_count % 5 == 0:
                    logger.info(f"Still waiting for depth data... (attempt {retry_count}/{max_retries})")

            # Return default depth structure if no data received
            logger.warning(f"No depth data received for {symbol}")
            return self._get_default_depth()
            
        except Exception as e:
            logger.error(f"Error in get_depth: {str(e)}", exc_info=True)
            return self._get_default_depth()

    def _format_depth(self, depth_data: dict, symbol: str, exchange: str) -> dict:
        """Format depth data from Tradejini to OpenAlgo standard format"""
        try:
            logger.debug(f"Formatting depth data for {symbol}")
            
            # Extract bid and ask data
            bids_raw = depth_data.get('bid', [])
            asks_raw = depth_data.get('ask', [])
            
            # Format bids (buy orders) - OpenAlgo format (no 'orders' field)
            bids = []
            for bid in bids_raw[:5]:  # Top 5 levels
                bids.append({
                    'price': float(bid.get('price', 0)),
                    'quantity': int(bid.get('qty', 0))
                })
            
            # Ensure we have exactly 5 levels
            while len(bids) < 5:
                bids.append({'price': 0, 'quantity': 0})
            
            # Format asks (sell orders) - OpenAlgo format (no 'orders' field)
            asks = []
            for ask in asks_raw[:5]:  # Top 5 levels
                asks.append({
                    'price': float(ask.get('price', 0)),
                    'quantity': int(ask.get('qty', 0))
                })
            
            # Ensure we have exactly 5 levels
            while len(asks) < 5:
                asks.append({'price': 0, 'quantity': 0})
            
            # Calculate totals
            totalbuyqty = sum(bid['quantity'] for bid in bids)
            totalsellqty = sum(ask['quantity'] for ask in asks)
            
            # Get additional market data from depth_data or use defaults
            high = float(depth_data.get('high', 0))
            low = float(depth_data.get('low', 0))
            ltp = float(depth_data.get('ltp', 0))
            ltq = int(depth_data.get('ltq', 0))
            oi = int(depth_data.get('OI', 0))
            open_price = float(depth_data.get('open', 0))
            prev_close = float(depth_data.get('close', 0))
            volume = int(depth_data.get('vol', 0))
            
            # Format exactly like OpenAlgo sample
            formatted_depth = {
                'asks': asks,
                'bids': bids,
                'high': high,
                'low': low,
                'ltp': ltp,
                'ltq': ltq,
                'oi': oi,
                'open': open_price,
                'prev_close': prev_close,
                'totalbuyqty': totalbuyqty,
                'totalsellqty': totalsellqty,
                'volume': volume
            }
            
            logger.debug(f"Formatted depth for {symbol}: {len(bids)} bids, {len(asks)} asks")
            return formatted_depth
            
        except Exception as e:
            logger.error(f"Error formatting depth data: {str(e)}", exc_info=True)
            return self._get_default_depth()

    def _get_default_depth(self) -> dict:
        """Return default depth structure in OpenAlgo format"""
        return {
            'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
            'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
            'high': 0,
            'low': 0,
            'ltp': 0,
            'ltq': 0,
            'oi': 0,
            'open': 0,
            'prev_close': 0,
            'totalbuyqty': 0,
            'totalsellqty': 0,
            'volume': 0
        }

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Get historical OHLC data for given symbol using REST API"""
        try:
            def parse_timestamp(ts, is_start=True):
                try:
                    if isinstance(ts, str):
                        dt = pd.Timestamp(ts, tz='Asia/Kolkata')
                    else:
                        dt = pd.Timestamp(ts, unit='ms', tz='Asia/Kolkata')
                    
                    if is_start:
                        dt = dt.replace(hour=9, minute=15, second=0, microsecond=0)
                    else:
                        dt = dt.replace(hour=23, minute=59, second=59, microsecond=0)
                    
                    return int(dt.timestamp())
                    
                except Exception as e:
                    logger.error(f"Error parsing timestamp {ts}: {str(e)}", exc_info=True)
                    raise
            
            start_ts = parse_timestamp(start_date, is_start=True)
            end_ts = parse_timestamp(end_date, is_start=False)
            
            logger.debug(f"Requesting history for {symbol} from {start_ts} to {end_ts}")

            # Get token for the symbol
            token = get_token(symbol, exchange)
            if not token:
                logger.error(f"Token not found for {symbol} on {exchange}")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            # Map exchange to Tradejini format
            exchange_map = {
                'NSE': 'NSE', 'BSE': 'BSE', 'NFO': 'NFO', 'BFO': 'BFO',
                'CDS': 'CDS', 'BCD': 'BCD', 'MCD': 'MCD', 'MCX': 'MCX',
                'NCO': 'NCO', 'BCO': 'BCO'
            }
            exchange = exchange_map.get(exchange, exchange)

            # Get symbol in TradeJini format
            token_str = get_symbol(token, exchange)
            
            # Map interval to Tradejini format
            interval_map = {
                '1m': '1', '5m': '5', '15m': '15', '30m': '30'
            }
            tj_interval = interval_map.get(interval, interval)

            # Fetch historical data using REST API
            success, result = self._get_historical_data(
                symbol=token_str,
                exchange=exchange,
                interval=tj_interval,
                from_ts=start_ts,
                to_ts=end_ts
            )
            
            if not success:
                logger.error(f"Failed to fetch historical data: {result}")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            if not result:
                logger.warning(f"No data returned for {symbol} on {exchange}")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
            # Convert to pandas DataFrame
            df = pd.DataFrame(result)
            
            # Convert timestamps to datetime in IST and create DataFrame
            if 'timestamp' in df.columns and df['timestamp'].max() > 1e12:
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True).dt.tz_convert('Asia/Kolkata')
            else:
                # If no timestamp, generate based on interval
                start_dt = pd.Timestamp(start_ts, unit='s', tz='Asia/Kolkata')
                freq = interval.replace('m', 'T').replace('h', 'H').replace('d', 'D')
                df['datetime'] = pd.date_range(start=start_dt, periods=len(df), freq=freq)
            
            # Set datetime as index and sort
            df.set_index('datetime', inplace=True)
            df.sort_index(inplace=True)
            
            # Convert timestamp to seconds since epoch for backward compatibility
            if 'timestamp' in df.columns:
                df['timestamp'] = df.index.astype('int64') // 10**9
            
            # Ensure all required columns exist
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col not in df.columns:
                    df[col] = 0.0
                    
            # Reset index to include datetime as a column
            df = df.reset_index()
            
            # Convert to OpenAlgo format with timestamp in seconds
            result_data = []
            for _, row in df.iterrows():
                result_data.append({
                    'timestamp': int(row['datetime'].timestamp()),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': int(row.get('volume', 0))
                })
            
            return pd.DataFrame(result_data)
            
        except Exception as e:
            logger.error(f"Error in get_history: {str(e)}", exc_info=True)
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    def _get_historical_data(self, symbol: str, exchange: str, interval: str, from_ts: int, to_ts: int) -> Tuple[bool, Union[List[Dict[str, Any]], str]]:
        """Fetch historical OHLC data from TradeJini REST API"""
        try:
            # API endpoint
            base_url = "https://api.tradejini.com/v2"
            endpoint = "/api/mkt-data/chart/interval-data"
            url = f"{base_url}{endpoint}"
            
            # Get API key from environment
            api_key = os.getenv('BROKER_API_SECRET')
            if not api_key:
                error_msg = "BROKER_API_SECRET environment variable not set"
                logger.error(error_msg)
                return False, error_msg
                
            # Check if auth_token is available
            if not self.auth_token:
                error_msg = "Authentication token is not available. Please authenticate first."
                logger.error(error_msg)
                return False, error_msg
            
            # Get broker symbol from database
            symbol_id = get_br_symbol(symbol, exchange)
            if not symbol_id:
                error_msg = f"Broker symbol not found for {symbol} on {exchange}"
                logger.error(error_msg)
                return False, error_msg
            
            # Prepare query parameters
            params = {
                'id': symbol_id,
                'interval': interval,
                'from': from_ts,
                'to': to_ts
            }
            
            # Format auth header
            auth_header = f"{api_key}:{self.auth_token}"
            headers = {
                'Authorization': f'Bearer {auth_header}',
                'Accept': 'application/json'
            }
            
            logger.debug(f"Making historical data request to {url} with params: {params}")
            
            # Get the shared httpx client
            client = get_httpx_client()
            
            # Make the GET request
            response = client.get(
                url,
                params=params,
                headers=headers,
                timeout=30.0
            )
            
            logger.debug(f"Response status: {response.status_code}")
            response.raise_for_status()
            
            try:
                data = response.json()
                logger.debug(f"Parsed JSON response keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {e}")
                return False, f"Invalid JSON response: {str(e)}"
            
            # Check if the response is successful
            if data.get('s') != 'ok':
                error_msg = f"API Error: Status='{data.get('s')}', Message='{data.get('message', 'No error message')}'"
                logger.error(error_msg)
                return False, error_msg
            
            # Process the response data
            ohlc_data = []
            bars = data.get('d', {}).get('bars', [])
            logger.debug(f"Processing {len(bars)} bars from response")
            
            for bar in bars:
                if not isinstance(bar, list) or len(bar) < 5:
                    logger.warning(f"Skipping invalid bar format: {bar}")
                    continue
                    
                try:
                    # Parse the bar data [timestamp, open, high, low, close, volume]
                    timestamp = int(bar[0])
                    open_price = float(bar[1])
                    high = float(bar[2])
                    low = float(bar[3])
                    close = float(bar[4])
                    volume = int(bar[5]) if len(bar) > 5 else 0
                    
                    ohlc_data.append({
                        'timestamp': timestamp,
                        'open': open_price,
                        'high': high,
                        'low': low,
                        'close': close,
                        'volume': volume
                    })
                    
                except (IndexError, ValueError, TypeError) as e:
                    logger.warning(f"Error parsing bar data: {bar}, error: {str(e)}")
                    continue
            
            logger.info(f"Received {len(ohlc_data)} bars of historical data for {symbol_id}")
            return True, ohlc_data
            
        except httpx.HTTPStatusError as e:
            error_msg = f"HTTP error in _get_historical_data: {str(e)}"
            if hasattr(e, 'response'):
                error_msg += f" - {e.response.text}"
            logger.error(error_msg)
            return False, error_msg
        except httpx.RequestError as e:
            error_msg = f"Network error in _get_historical_data: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Unexpected error in _get_historical_data: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def get_intervals(self) -> list:
        """Get list of supported intervals"""
        return list(self.timeframe_map.keys())

    def close(self):
        """Close WebSocket connection"""
        if hasattr(self, 'ws') and self.ws:
            self.ws.close()