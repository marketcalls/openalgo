import httpx
import json
import os
import pandas as pd
import time
from datetime import datetime, timedelta
import urllib.parse
from database.token_db import get_br_symbol, get_token, get_oa_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="GET", payload=''):
    """Helper function to make API calls to Motilal Oswal"""
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_SECRET')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        'Authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'MOSL/V.1.1.0',
        'ApiKey': api_key,
        'ClientLocalIp': '1.2.3.4',
        'ClientPublicIp': '1.2.3.4',
        'MacAddress': '00:00:00:00:00:00',
        'SourceId': 'WEB',
        'OsName': 'Windows',
        'OsVersion': '10',
        'AppName': 'OpenAlgo',
        'AppVersion': '1.0.0'
    }

    if isinstance(payload, dict):
        payload = json.dumps(payload)

    url = f"https://openapi.motilaloswal.com{endpoint}"

    try:
        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, headers=headers, content=payload)
        else:
            response = client.request(method, url, headers=headers, content=payload)

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        if response.status_code == 403:
            logger.debug(f"API returned 403 Forbidden. Headers: {headers}")
            logger.debug(f"Response text: {response.text}")
            raise Exception("Authentication failed. Please check your API key and auth token.")

        return json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse response. Status code: {response.status_code}")
        logger.debug(f"Response text: {response.text}")
        raise Exception(f"Failed to parse API response (status {response.status_code})")

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Motilal Oswal data handler with authentication token"""
        self.auth_token = auth_token
        self._websocket = None

    def _auto_detect_exchange(self, symbol: str) -> str:
        """
        Auto-detect exchange for a symbol by looking up its instrumenttype in database.
        Returns the appropriate exchange based on instrumenttype.
        """
        try:
            # Import here to avoid circular imports
            from database.symbol import SymToken
            from database.auth_db import db_session

            # Query database for the symbol
            with db_session() as session:
                # First try to find any matching symbol
                results = session.query(SymToken).filter(
                    SymToken.symbol == symbol
                ).all()

                if results:
                    for result in results:
                        # Check instrumenttype to determine exchange
                        if result.instrumenttype:
                            instrument_type = result.instrumenttype.upper()
                            # If instrumenttype contains INDEX, use it as exchange
                            if 'INDEX' in instrument_type:
                                # instrumenttype like NSE_INDEX, BSE_INDEX, MCX_INDEX
                                return result.instrumenttype
                            else:
                                # For other types, use the exchange field
                                return result.exchange

                    # If no instrumenttype, return the exchange of first match
                    return results[0].exchange

                # If not found, make educated guess based on symbol pattern
                if 'GOLD' in symbol.upper() or 'SILVER' in symbol.upper() or 'CRUDE' in symbol.upper():
                    return 'MCX'  # Commodity symbols
                elif symbol.endswith('FUT'):
                    return 'NFO'
                elif symbol.endswith('CE') or symbol.endswith('PE'):
                    return 'NFO'
                elif 'USDINR' in symbol.upper() or 'EURINR' in symbol.upper():
                    return 'CDS'
                else:
                    return 'NSE'  # Default to NSE

        except Exception as e:
            logger.error(f"Error in auto-detecting exchange: {str(e)}")
            return 'NSE'  # Default fallback

    def get_websocket(self, force_new=False):
        """
        Get or create WebSocket instance for streaming market data.

        Args:
            force_new: Force creation of a new WebSocket connection

        Returns:
            MotilalWebSocket instance
        """
        # Return existing connection if valid
        if not force_new and self._websocket:
            if hasattr(self._websocket, 'is_connected') and self._websocket.is_connected:
                return self._websocket

        # Get credentials from environment
        client_id = os.getenv("BROKER_API_KEY", "")
        api_key = os.getenv("BROKER_API_SECRET", "")

        # Import and create WebSocket instance
        from .motilal_websocket import MotilalWebSocket
        self._websocket = MotilalWebSocket(client_id, self.auth_token, api_key)

        # Connect and wait for authentication
        self._websocket.connect()
        time.sleep(2)  # Wait for connection to establish

        logger.debug("WebSocket connection established")
        return self._websocket

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol from Motilal Oswal.

        Args:
            symbol: Trading symbol (OpenAlgo format)
            exchange: Exchange (NSE, BSE, NFO, BFO, CDS, MCX)

        Returns:
            dict: Quote data with required fields
            {
                'bid': float,
                'ask': float,
                'open': float,
                'high': float,
                'low': float,
                'ltp': float,
                'prev_close': float,
                'volume': int,
                'oi': int
            }
        """
        try:
            # Get token for the symbol
            token = get_token(symbol, exchange)

            if not token:
                raise Exception(f"Token not found for symbol: {symbol}, exchange: {exchange}")

            # Map OpenAlgo exchange to Motilal exchange
            from broker.motilal.mapping.transform_data import map_exchange
            motilal_exchange = map_exchange(exchange)

            # Prepare payload for Motilal's LTP API
            payload = {
                "exchange": motilal_exchange,
                "scripcode": int(token)
            }

            logger.debug(f"Fetching quotes for {symbol} ({token}) on {motilal_exchange}")

            # Make API call using the helper function
            response = get_api_response("/rest/report/v1/getltpdata",
                                      self.auth_token,
                                      "POST",
                                      payload)

            # Check response status
            if response.get('status') != 'SUCCESS':
                raise Exception(f"Error from Motilal API: {response.get('message', 'Unknown error')}, errorcode: {response.get('errorcode', '')}")

            # Extract quote data from response
            data = response.get('data', {})
            if not data:
                raise Exception("No quote data received from Motilal API")

            # IMPORTANT: Motilal returns values in paisa, convert to rupees (divide by 100)
            # Handle the case where values might be 0 or None
            def convert_paisa_to_rupees(value):
                """Convert paisa to rupees, handling None and 0 values"""
                if value is None or value == 0:
                    return 0.0
                return float(value) / 100.0

            # Return quote in OpenAlgo common format
            return {
                'bid': convert_paisa_to_rupees(data.get('bid', 0)),
                'ask': convert_paisa_to_rupees(data.get('ask', 0)),
                'open': convert_paisa_to_rupees(data.get('open', 0)),
                'high': convert_paisa_to_rupees(data.get('high', 0)),
                'low': convert_paisa_to_rupees(data.get('low', 0)),
                'ltp': convert_paisa_to_rupees(data.get('ltp', 0)),
                'prev_close': convert_paisa_to_rupees(data.get('close', 0)),  # Motilal uses 'close' for previous close
                'volume': int(data.get('volume', 0)),
                'oi': 0  # Motilal LTP API doesn't provide OI data
            }

        except Exception as e:
            logger.error(f"Error fetching quotes for {symbol} on {exchange}: {str(e)}")
            raise Exception(f"Error fetching quotes: {str(e)}")

    def _get_default_depth(self):
        """Return default empty depth structure"""
        return {
            'bids': [],
            'asks': [],
            'totalbuyqty': 0,
            'totalsellqty': 0
        }

    def get_market_depth(self, symbol_list, timeout: int = 5):
        """
        Get market depth data for a list of symbols using the WebSocket connection.
        This is the main implementation for market depth.

        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds

        Returns:
            Dict with market depth data in the OpenAlgo standard format
        """
        return self.get_depth(symbol_list, timeout)

    def get_depth(self, symbol_list, timeout: int = 5):
        """
        Get market depth data for a list of symbols using the WebSocket connection.
        This follows the OpenAlgo standard structure.

        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds

        Returns:
            Dict with market depth data in the OpenAlgo standard format
        """
        logger.info(f"Getting market depth for: {symbol_list}")

        # Standardize input format
        # Handle dictionary input (single symbol case)
        if isinstance(symbol_list, dict):
            try:
                # Extract symbol and exchange
                symbol = symbol_list.get('symbol') or symbol_list.get('SYMBOL')
                exchange = symbol_list.get('exchange') or symbol_list.get('EXCHANGE')

                if symbol and exchange:
                    logger.info(f"Processing single symbol depth request: {symbol} on {exchange}")
                    # Convert to a list with a single item to use the standard flow
                    symbol_list = [{'symbol': symbol, 'exchange': exchange}]
                else:
                    logger.error("Missing symbol or exchange in request")
                    return {}
            except Exception as e:
                logger.error(f"Error processing single symbol depth request: {str(e)}")
                return {}

        # Handle plain string (like just "SBIN" or "GOLDPETAL28NOV25FUT")
        elif isinstance(symbol_list, str):
            symbol = symbol_list.strip()
            # Use the helper function to auto-detect exchange based on database lookup
            exchange = self._auto_detect_exchange(symbol)
            logger.info(f"Processing string symbol depth: {symbol} on {exchange} (auto-detected)")
            symbol_list = [{'symbol': symbol, 'exchange': exchange}]

        # For simple case, prepare the instruments for WebSocket subscription
        depth_data = []

        # Get WebSocket connection
        websocket = self.get_websocket()

        if not websocket or not websocket.is_connected:
            logger.warning("WebSocket not connected, reconnecting...")
            websocket = self.get_websocket(force_new=True)

        if not websocket or not websocket.is_connected:
            logger.error("Could not establish WebSocket connection for market depth")
            return {}

        # Process each symbol
        for sym in symbol_list:
            # If it's a simple dict with symbol and exchange
            if isinstance(sym, dict) and 'symbol' in sym and 'exchange' in sym:
                symbol = sym['symbol']
                exchange = sym['exchange']

                # Get token for this symbol
                token = get_token(symbol, exchange)

                if token:
                    # Get broker symbol if different
                    br_symbol = get_br_symbol(symbol, exchange) or symbol

                    # Map OpenAlgo exchange to Motilal exchange
                    from broker.motilal.mapping.transform_data import map_exchange
                    motilal_exchange = map_exchange(exchange)

                    # Determine exchange type (CASH or DERIVATIVES)
                    exchange_type = "DERIVATIVES" if exchange in ['NFO', 'BFO', 'CDS', 'MCX'] else "CASH"

                    logger.info(f"Subscribing to market depth for {exchange}:{symbol} with token {token}")

                    # Subscribe to market depth
                    success = websocket.register_scrip(motilal_exchange, exchange_type, int(token), br_symbol)

                    if success:
                        # Wait for depth data to arrive
                        logger.info(f"Waiting for WebSocket depth data for {exchange}:{symbol}")
                        time.sleep(2.5)

                        # Retrieve depth from WebSocket
                        depth = websocket.get_market_depth(motilal_exchange, token)

                        if depth:
                            # Create a normalized depth structure in the OpenAlgo format
                            bids = depth.get('bids', [])
                            asks = depth.get('asks', [])

                            item = {
                                'symbol': symbol,
                                'exchange': exchange,
                                'token': token,
                                'timestamp': datetime.now().isoformat(),
                                'total_buy_qty': sum(b.get('quantity', 0) for b in bids),
                                'total_sell_qty': sum(a.get('quantity', 0) for a in asks),
                                'ltp': 0,  # LTP not available in depth packet
                                'oi': 0,   # OI not available in depth packet
                                'depth': {
                                    'buy': [],
                                    'sell': []
                                }
                            }

                            # Format the buy orders
                            for bid in bids:
                                item['depth']['buy'].append({
                                    'price': bid.get('price', 0),
                                    'quantity': bid.get('quantity', 0),
                                    'orders': bid.get('orders', 0)
                                })

                            # Format the sell orders
                            for ask in asks:
                                item['depth']['sell'].append({
                                    'price': ask.get('price', 0),
                                    'quantity': ask.get('quantity', 0),
                                    'orders': ask.get('orders', 0)
                                })

                            depth_data.append(item)
                            logger.debug(f"Retrieved market depth for {symbol} on {exchange}")

                            # Unsubscribe after getting the data to stop continuous streaming
                            logger.info(f"Unsubscribing from depth for {exchange}:{symbol} after retrieving data")
                            websocket.unregister_scrip(motilal_exchange, exchange_type, int(token))
                        else:
                            logger.warning(f"No market depth received for {symbol} on {exchange}")
                            # Also unsubscribe even if no data received to clean up subscription
                            logger.info(f"Unsubscribing from depth for {exchange}:{symbol} due to no data")
                            websocket.unregister_scrip(motilal_exchange, exchange_type, int(token))
                    else:
                        logger.error(f"Failed to subscribe to market depth for {symbol} on {exchange}")
                else:
                    logger.error(f"Could not find token for {symbol} on {exchange}")
            else:
                logger.warning(f"Unsupported symbol format for market depth: {sym}")

        # Return data directly (service layer will wrap it)
        # If there's no data, return empty response
        if not depth_data:
            return {}

        # For single symbol request (most common case), return in simplified format
        if len(depth_data) == 1:
            # Extract the first and only depth item
            depth_item = depth_data[0]

            # Return the data directly without wrapping
            return {
                "symbol": depth_item.get('symbol', ''),
                "exchange": depth_item.get('exchange', ''),
                "ltp": depth_item.get('ltp', 0),
                "oi": depth_item.get('oi', 0),
                "total_buy_qty": depth_item.get('total_buy_qty', 0),
                "total_sell_qty": depth_item.get('total_sell_qty', 0),
                "depth": depth_item.get('depth', {'buy': [], 'sell': []})
            }

        # For multiple symbols, return as list
        return {"data": depth_data}

    def get_history(self, symbol: str, exchange: str, interval: str,
                   start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol.

        Note: Motilal Oswal does NOT provide historical candle data via REST API.

        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
            interval: Candle interval (1m, 3m, 5m, 10m, 15m, 30m, 1h, D)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            pd.DataFrame: Empty dataframe

        Raises:
            Exception: Always raises exception as historical data is not supported
        """
        error_msg = (
            "Historical candle data is not available via REST API for Motilal Oswal. "
            "Motilal provides EOD (End of Day) data only. "
            "For intraday historical data, you may need to use third-party data providers."
        )
        logger.warning(f"History API called for {symbol} on {exchange}, but not supported")
        raise Exception(error_msg)
