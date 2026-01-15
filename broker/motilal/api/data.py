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
        # Motilal does not support historical data with date ranges
        # EOD API only returns current day's data, not historical ranges
        self.timeframe_map = {}

    def _detect_index_exchange(self, symbol: str) -> str:
        """
        Detect the specific index exchange (NSE_INDEX, BSE_INDEX, or MCX_INDEX) for an index symbol.

        Args:
            symbol: Index symbol (e.g., NIFTY, SENSEX, BANKEX)

        Returns:
            Specific index exchange (NSE_INDEX, BSE_INDEX, or MCX_INDEX)
        """
        # Common NSE indices
        nse_indices = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50']

        # Common BSE indices
        bse_indices = ['SENSEX', 'BANKEX', 'SENSEX50']

        # Common MCX indices
        mcx_indices = ['MCXMETLDEX', 'MCXENRGDEX']

        symbol_upper = symbol.upper()

        # Check if it's a known NSE index
        if any(idx in symbol_upper for idx in nse_indices):
            return 'NSE_INDEX'

        # Check if it's a known BSE index
        if any(idx in symbol_upper for idx in bse_indices):
            return 'BSE_INDEX'

        # Check if it's a known MCX index
        if any(idx in symbol_upper for idx in mcx_indices):
            return 'MCX_INDEX'

        # Try database lookup
        try:
            from database.symbol import SymToken
            from database.auth_db import db_session

            with db_session() as session:
                results = session.query(SymToken).filter(
                    SymToken.symbol == symbol
                ).all()

                for result in results:
                    if result.instrumenttype and 'INDEX' in result.instrumenttype.upper():
                        logger.debug(f"Found index in database: {symbol} -> {result.instrumenttype}")
                        return result.instrumenttype
        except Exception as e:
            logger.error(f"Error looking up index in database: {str(e)}")

        # Default to NSE_INDEX for unknown indices
        logger.warning(f"Could not determine specific index exchange for {symbol}, defaulting to NSE_INDEX")
        return 'NSE_INDEX'

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
                logger.debug("Using existing WebSocket connection")
                return self._websocket
            else:
                logger.debug("Existing WebSocket not connected, creating new connection")

        # Get credentials from environment
        client_id = os.getenv("BROKER_API_KEY", "")
        api_key = os.getenv("BROKER_API_SECRET", "")

        # Import and create WebSocket instance
        from .motilal_websocket import MotilalWebSocket
        self._websocket = MotilalWebSocket(client_id, self.auth_token, api_key)

        # Connect and wait for authentication
        self._websocket.connect()

        # Wait longer for connection to establish and authenticate
        # Check connection status every 0.5 seconds for up to 5 seconds
        max_wait = 5.0
        wait_interval = 0.5
        elapsed = 0

        while elapsed < max_wait:
            if self._websocket.is_connected:
                logger.debug(f"WebSocket connection established after {elapsed:.1f} seconds")
                return self._websocket
            time.sleep(wait_interval)
            elapsed += wait_interval

        # Connection may still be establishing
        if self._websocket.is_connected:
            logger.info("WebSocket connection established")
        else:
            logger.warning("WebSocket connection status uncertain after timeout")

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

            # Convert index exchanges to regular exchanges before API call
            # Motilal API doesn't accept NSE_INDEX, it expects NSE
            if exchange == 'NSE_INDEX':
                exchange = 'NSE'
            elif exchange == 'BSE_INDEX':
                exchange = 'BSE'
            elif exchange == 'MCX_INDEX':
                exchange = 'MCX'

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

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols using WebSocket
        Motilal WebSocket supports subscribing to multiple instruments

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            # Motilal WebSocket can handle multiple instruments
            # Using batch size of 100 for practical response times
            BATCH_SIZE = 100
            RATE_LIMIT_DELAY = 0.1  # Delay between batches in seconds

            if len(symbols) > BATCH_SIZE:
                logger.info(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
                all_results = []

                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i:i + BATCH_SIZE]
                    logger.debug(f"Processing batch {i//BATCH_SIZE + 1}: symbols {i+1} to {min(i+BATCH_SIZE, len(symbols))}")

                    batch_results = self._process_multiquotes_batch(batch)
                    all_results.extend(batch_results)

                    # Rate limit delay between batches
                    time.sleep(RATE_LIMIT_DELAY)

                logger.info(f"Successfully processed {len(all_results)} quotes")
                return all_results
            else:
                return self._process_multiquotes_batch(symbols)

        except Exception as e:
            logger.exception(f"Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _process_multiquotes_batch(self, symbols: list) -> list:
        """
        Process a batch of symbols using WebSocket subscription
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
        Returns:
            list: List of quote data for the batch
        """
        results = []
        skipped_symbols = []
        registered_scrips = []  # Track registered scrips for unregistration
        symbol_map = {}  # Map exchange:token to original symbol/exchange

        # Get WebSocket connection
        websocket = self.get_websocket()

        if not websocket or not websocket.is_connected:
            logger.warning("WebSocket not connected, reconnecting...")
            websocket = self.get_websocket(force_new=True)

        if not websocket or not websocket.is_connected:
            logger.error("Could not establish WebSocket connection")
            raise ConnectionError("WebSocket connection unavailable")

        # Step 1: Prepare and register all instruments
        for item in symbols:
            symbol = item.get('symbol')
            exchange = item.get('exchange')

            if not symbol or not exchange:
                logger.warning(f"Skipping entry due to missing symbol/exchange: {item}")
                skipped_symbols.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'data': None,
                    'error': 'Missing required symbol or exchange'
                })
                continue

            try:
                # Get token for this symbol
                token = get_token(symbol, exchange)
                if not token:
                    logger.warning(f"Skipping symbol {symbol} on {exchange}: could not resolve token")
                    skipped_symbols.append({
                        'symbol': symbol,
                        'exchange': exchange,
                        'data': None,
                        'error': 'Could not resolve token'
                    })
                    continue

                # Map exchange for Motilal API
                api_exchange = exchange
                if exchange == 'NSE_INDEX':
                    api_exchange = 'NSE'
                elif exchange == 'BSE_INDEX':
                    api_exchange = 'BSE'
                elif exchange == 'MCX_INDEX':
                    api_exchange = 'MCX'

                # Map OpenAlgo exchange to Motilal exchange
                from broker.motilal.mapping.transform_data import map_exchange
                motilal_exchange = map_exchange(api_exchange)

                # Determine exchange type (CASH or DERIVATIVES)
                exchange_type = "DERIVATIVES" if api_exchange in ['NFO', 'BFO', 'CDS', 'MCX'] else "CASH"

                # Get broker symbol
                br_symbol = get_br_symbol(symbol, exchange) or symbol

                # Register scrip for market data
                success = websocket.register_scrip(motilal_exchange, exchange_type, int(token), br_symbol)

                if success:
                    registered_scrips.append({
                        'motilal_exchange': motilal_exchange,
                        'exchange_type': exchange_type,
                        'token': int(token)
                    })

                    # Store mapping for response processing
                    key = f"{motilal_exchange}:{token}"
                    symbol_map[key] = {
                        'symbol': symbol,
                        'exchange': exchange,
                        'token': token
                    }
                else:
                    logger.warning(f"Failed to register {symbol} on {exchange}")
                    skipped_symbols.append({
                        'symbol': symbol,
                        'exchange': exchange,
                        'data': None,
                        'error': 'Registration failed'
                    })

            except Exception as e:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: {str(e)}")
                skipped_symbols.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'data': None,
                    'error': str(e)
                })
                continue

        if not registered_scrips:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        # Step 2: Wait for data to arrive
        wait_time = min(max(len(registered_scrips) * 0.1, 2), 5)  # Between 2-5 seconds
        logger.debug(f"Waiting {wait_time:.1f}s for quote data...")
        time.sleep(wait_time)

        # Step 3: Collect results from WebSocket
        for key, info in symbol_map.items():
            motilal_exchange, token = key.split(':')

            quote = websocket.get_quote(motilal_exchange, token)

            if quote:
                results.append({
                    'symbol': info['symbol'],
                    'exchange': info['exchange'],
                    'data': {
                        'bid': float(quote.get('bid', 0)),
                        'ask': float(quote.get('ask', 0)),
                        'open': float(quote.get('open', 0)),
                        'high': float(quote.get('high', 0)),
                        'low': float(quote.get('low', 0)),
                        'ltp': float(quote.get('ltp', 0)),
                        'prev_close': float(quote.get('prev_close', 0)),
                        'volume': int(quote.get('volume', 0)),
                        'oi': int(quote.get('open_interest', 0))
                    }
                })
            else:
                results.append({
                    'symbol': info['symbol'],
                    'exchange': info['exchange'],
                    'error': 'No data received'
                })

        # Step 4: Unregister all scrips after getting data
        logger.info(f"Unregistering {len(registered_scrips)} scrips")
        for scrip in registered_scrips:
            try:
                websocket.unregister_scrip(
                    scrip['motilal_exchange'],
                    scrip['exchange_type'],
                    scrip['token']
                )
            except Exception as e:
                logger.warning(f"Error unregistering scrip: {e}")

        logger.info(f"Retrieved quotes for {len([r for r in results if 'data' in r])}/{len(symbol_map)} symbols")
        return skipped_symbols + results

    def _get_default_depth(self):
        """Return default empty depth structure"""
        return {
            'bids': [],
            'asks': [],
            'totalbuyqty': 0,
            'totalsellqty': 0
        }

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol from Motilal Oswal using WebSocket.
        This follows the OpenAlgo standard structure matching Angel and other brokers.

        Args:
            symbol: Trading symbol (e.g., SBIN, NIFTY)
            exchange: Exchange (e.g., NSE, BSE, NFO, NSE_INDEX)

        Returns:
            dict: Market depth data in OpenAlgo standard format
        """
        logger.info(f"Getting market depth for: {symbol} on {exchange}")

        # Handle generic 'INDEX' exchange by detecting specific index exchange
        if exchange == 'INDEX':
            exchange = self._detect_index_exchange(symbol)
            logger.debug(f"Converted generic INDEX to {exchange} for {symbol}")

        # Get WebSocket connection with retry logic
        websocket = None
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                websocket = self.get_websocket()

                if websocket and websocket.is_connected:
                    logger.debug(f"WebSocket connected on attempt {retry_count + 1}")
                    break

                logger.warning(f"WebSocket not connected on attempt {retry_count + 1}, retrying...")

                # Force new connection on retry
                websocket = self.get_websocket(force_new=True)

                # Wait a bit longer for connection to establish
                time.sleep(2)

                if websocket and websocket.is_connected:
                    logger.debug(f"WebSocket connected after retry {retry_count + 1}")
                    break

                retry_count += 1

            except Exception as e:
                logger.error(f"WebSocket connection attempt {retry_count + 1} failed: {str(e)}")
                retry_count += 1
                time.sleep(1)

        if not websocket or not websocket.is_connected:
            logger.error(f"Could not establish WebSocket connection after {max_retries} attempts")
            # Return empty depth data instead of throwing error
            return {
                'bids': [{'price': 0, 'quantity': 0}] * 5,
                'asks': [{'price': 0, 'quantity': 0}] * 5,
                'high': 0,
                'low': 0,
                'ltp': 0,
                'ltq': 0,
                'open': 0,
                'prev_close': 0,
                'volume': 0,
                'oi': 0,
                'totalbuyqty': 0,
                'totalsellqty': 0
            }

        try:
            # Get token for this symbol
            token = get_token(symbol, exchange)

            if not token:
                raise Exception(f"Token not found for symbol: {symbol}, exchange: {exchange}")

            # Get broker symbol if different
            br_symbol = get_br_symbol(symbol, exchange) or symbol

            # Convert index exchanges to regular exchanges before API call
            # Motilal API doesn't accept NSE_INDEX, it expects NSE
            api_exchange = exchange
            if api_exchange == 'NSE_INDEX':
                api_exchange = 'NSE'
            elif api_exchange == 'BSE_INDEX':
                api_exchange = 'BSE'
            elif api_exchange == 'MCX_INDEX':
                api_exchange = 'MCX'

            # Map OpenAlgo exchange to Motilal exchange
            from broker.motilal.mapping.transform_data import map_exchange
            motilal_exchange = map_exchange(api_exchange)

            # Determine exchange type (CASH or DERIVATIVES)
            exchange_type = "DERIVATIVES" if api_exchange in ['NFO', 'BFO', 'CDS', 'MCX'] else "CASH"

            logger.info(f"Subscribing to market depth for {exchange}:{symbol} with token {token}")

            # Subscribe to market depth
            success = websocket.register_scrip(motilal_exchange, exchange_type, int(token), br_symbol)

            if not success:
                raise Exception(f"Failed to subscribe to market depth for {symbol} on {exchange}")

            # Wait for depth data to arrive
            # NOTE: Motilal's WebSocket broadcast feed typically only provides depth level 1 (best bid/ask)
            # Levels 2-5 may not be sent via WebSocket depending on subscription type
            logger.debug(f"Waiting for WebSocket depth data for {exchange}:{symbol}")
            logger.warning("⚠️ Motilal may only provide depth level 1 (best bid/ask) via WebSocket")

            # Wait for depth data to arrive (increased time for potential multiple levels)
            time.sleep(3.0)

            # Retrieve depth (may contain 1-5 levels depending on broker feed)
            depth = websocket.get_market_depth(motilal_exchange, token)

            # Log what we actually received
            if depth:
                bids_count = len([b for b in depth.get('bids', []) if b and b.get('price', 0) > 0])
                asks_count = len([a for a in depth.get('asks', []) if a and a.get('price', 0) > 0])
                logger.debug(f"📊 Received {bids_count} bid levels and {asks_count} ask levels for {symbol}")
            else:
                logger.warning(f"❌ No depth data received for {symbol}")

            # Also try to get quote data (OHLC, LTP, volume) for this symbol
            quote = websocket.get_quote(motilal_exchange, token)

            # Unsubscribe after getting the data to stop continuous streaming
            logger.info(f"Unsubscribing from depth for {exchange}:{symbol} after retrieving data")
            websocket.unregister_scrip(motilal_exchange, exchange_type, int(token))

            # Create a normalized depth structure in the OpenAlgo format
            # If depth is not available (e.g., for indices), use empty lists
            if depth:
                bids = depth.get('bids', [])
                asks = depth.get('asks', [])
            else:
                logger.warning(f"No market depth data available for {symbol} on {exchange}, using empty depth")
                bids = []
                asks = []

            # Extract quote data if available
            ltp = quote.get('ltp', 0) if quote else 0
            oi = 0  # OI comes separately from quote
            high = quote.get('high', 0) if quote else 0
            low = quote.get('low', 0) if quote else 0
            open_price = quote.get('open', 0) if quote else 0
            prev_close = quote.get('prev_close', 0) if quote else 0
            volume = quote.get('volume', 0) if quote else 0

            # Format bids and asks - ensure exactly 5 entries each (matching Angel format)
            formatted_bids = []
            formatted_asks = []

            # Process buy orders (ensure 5 entries)
            for i in range(5):
                if i < len(bids) and bids[i] is not None:
                    formatted_bids.append({
                        'price': bids[i].get('price', 0),
                        'quantity': bids[i].get('quantity', 0)
                    })
                else:
                    formatted_bids.append({'price': 0, 'quantity': 0})

            # Process sell orders (ensure 5 entries)
            for i in range(5):
                if i < len(asks) and asks[i] is not None:
                    formatted_asks.append({
                        'price': asks[i].get('price', 0),
                        'quantity': asks[i].get('quantity', 0)
                    })
                else:
                    formatted_asks.append({'price': 0, 'quantity': 0})

            # Calculate total buy and sell quantities
            total_buy_qty = sum(b.get('quantity', 0) for b in bids if b is not None)
            total_sell_qty = sum(a.get('quantity', 0) for a in asks if a is not None)

            # Return in Angel's OpenAlgo standard format (matching lines 524-537 of angel/api/data.py)
            return {
                'bids': formatted_bids,
                'asks': formatted_asks,
                'high': high,
                'low': low,
                'ltp': ltp,
                'ltq': 0,  # Last traded quantity not available in Motilal depth data
                'open': open_price,
                'prev_close': prev_close,
                'volume': volume,
                'oi': oi,
                'totalbuyqty': total_buy_qty,
                'totalsellqty': total_sell_qty
            }

        except Exception as e:
            logger.error(f"Error fetching market depth for {symbol} on {exchange}: {str(e)}")
            # Return empty depth data instead of throwing error
            return {
                'bids': [{'price': 0, 'quantity': 0}] * 5,
                'asks': [{'price': 0, 'quantity': 0}] * 5,
                'high': 0,
                'low': 0,
                'ltp': 0,
                'ltq': 0,
                'open': 0,
                'prev_close': 0,
                'volume': 0,
                'oi': 0,
                'totalbuyqty': 0,
                'totalsellqty': 0
            }

    def get_history(self, symbol: str, exchange: str, interval: str,
                   start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol and timeframe
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Time interval (e.g., 1m, 5m, 15m, 60m, D)
            start_date: Start date in format YYYY-MM-DD
            end_date: End date in format YYYY-MM-DD
        Returns:
            pd.DataFrame: Empty DataFrame (historical data not supported)
        """
        logger.info(f"Historical data not provided by Motilal Oswal for {symbol}")
        # Return empty DataFrame with expected columns
        return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])

    def get_intervals(self) -> list:
        """Get available intervals/timeframes for historical data

        Returns:
            list: Empty list (historical data not supported)
        """
        logger.info("Historical data intervals not provided by Motilal Oswal")
        return []

    def get_supported_intervals(self) -> dict:
        """Return supported intervals matching the format expected by intervals.py"""
        intervals = {
            'seconds': [],
            'minutes': [],
            'hours': [],
            'days': [],
            'weeks': [],
            'months': []
        }
        logger.warning("Motilal Oswal does not support historical data intervals")
        return intervals
