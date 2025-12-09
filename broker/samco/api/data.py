import httpx
import json
import os
import pandas as pd
import time
from datetime import datetime, timedelta
from database.token_db import get_br_symbol, get_token, get_oa_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Samco API base URL
BASE_URL = "https://tradeapi.samco.in"


def safe_float(value, default=0):
    """Convert string to float, handling commas and empty values"""
    if value is None or value == '':
        return default
    try:
        if isinstance(value, str):
            value = value.replace(',', '')
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value, default=0):
    """Convert string to int, handling commas and empty values"""
    if value is None or value == '':
        return default
    try:
        if isinstance(value, str):
            value = value.replace(',', '')
        return int(float(value))
    except (ValueError, TypeError):
        return default


def get_api_response(endpoint, auth, method="GET", payload=None):
    """Helper function to make API calls to Samco"""
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'x-session-token': auth
    }

    url = f"{BASE_URL}{endpoint}"

    try:
        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, headers=headers, json=payload)
        else:
            response = client.request(method, url, headers=headers, json=payload)

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        if response.status_code == 403:
            logger.debug(f"Debug - API returned 403 Forbidden. Headers: {headers}")
            logger.debug(f"Debug - Response text: {response.text}")
            raise Exception("Authentication failed. Please check your session token.")

        return json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Debug - Failed to parse response. Status code: {response.status_code}")
        logger.debug(f"Debug - Response text: {response.text}")
        raise Exception(f"Failed to parse API response (status {response.status_code})")


class BrokerData:
    def __init__(self, auth_token):
        """Initialize Samco data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Samco resolutions
        self.timeframe_map = {
            # Minutes
            '1m': '1',
            '5m': '5',
            '10m': '10',
            '15m': '15',
            '30m': '30',
            # Hours
            '1h': '60',
            # Daily
            'D': 'DAY'
        }

    def _get_index_name(self, symbol: str) -> str:
        """Map OpenAlgo index symbols to Samco index names"""
        index_map = {
            'NIFTY': 'Nifty 50',
            'BANKNIFTY': 'Nifty Bank',
            'NIFTY 50': 'Nifty 50',
            'NIFTY BANK': 'Nifty Bank',
            'SENSEX': 'SENSEX',
            'BANKEX': 'BANKEX',
            'FINNIFTY': 'Nifty Fin Service',
            'MIDCPNIFTY': 'NIFTY MID SELECT'
        }
        return index_map.get(symbol.upper(), symbol)

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
        Returns:
            dict: Quote data with required fields
        """
        try:
            # Handle index quotes separately
            if exchange in ['NSE_INDEX', 'BSE_INDEX']:
                return self._get_index_quotes(symbol, exchange)

            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)

            # Build query parameters
            params = f"symbolName={br_symbol}"
            if exchange and exchange != 'NSE':
                params += f"&exchange={exchange}"

            response = get_api_response(f"/quote/getQuote?{params}",
                                       self.auth_token,
                                       "GET")

            if response.get('status') != 'Success':
                raise Exception(f"Error from Samco API: {response.get('statusMessage', 'Unknown error')}")

            # Extract quote data from response
            quote = response.get('quoteDetails', {})
            if not quote:
                raise Exception("No quote data received")

            # Parse best bids and asks
            bids = quote.get('bestBids', [])
            asks = quote.get('bestAsks', [])

            # Return quote in common format
            return {
                'bid': safe_float(bids[0].get('price')) if bids else 0,
                'ask': safe_float(asks[0].get('price')) if asks else 0,
                'open': safe_float(quote.get('openValue')),
                'high': safe_float(quote.get('highValue')),
                'low': safe_float(quote.get('lowValue')),
                'ltp': safe_float(quote.get('lastTradedPrice')),
                'prev_close': safe_float(quote.get('previousClose')),
                'volume': safe_int(quote.get('totalTradedVolume')),
                'oi': safe_int(quote.get('openInterest'))
            }

        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}")

    def _get_index_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for index symbols
        Args:
            symbol: Index symbol (e.g., NIFTY, BANKNIFTY, SENSEX)
            exchange: Exchange (NSE_INDEX or BSE_INDEX)
        Returns:
            dict: Quote data with required fields
        """
        try:
            # Map to Samco index name
            index_name = self._get_index_name(symbol)

            response = get_api_response(f"/quote/indexQuote?indexName={index_name}",
                                       self.auth_token,
                                       "GET")

            if response.get('status') != 'Success':
                raise Exception(f"Error from Samco API: {response.get('statusMessage', 'Unknown error')}")

            # Extract index details
            index_details = response.get('indexDetails', [])
            if not index_details:
                raise Exception("No index data received")

            quote = index_details[0]

            # Return quote in common format (indices don't have bid/ask)
            return {
                'bid': 0,
                'ask': 0,
                'open': safe_float(quote.get('openValue')),
                'high': safe_float(quote.get('highValue')),
                'low': safe_float(quote.get('lowValue')),
                'ltp': safe_float(quote.get('spotPrice')),
                'prev_close': safe_float(quote.get('closeValue')),
                'volume': safe_int(quote.get('totalTradedVolume')),
                'oi': 0
            }

        except Exception as e:
            raise Exception(f"Error fetching index quotes: {str(e)}")

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol using Samco /marketDepth API
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
        Returns:
            dict: Market depth data with bids, asks and other details
        """
        try:
            # Index symbols don't have market depth - return quote data with empty depth
            if exchange in ['NSE_INDEX', 'BSE_INDEX']:
                quote_data = self._get_index_quotes(symbol, exchange)
                return {
                    'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                    'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                    'high': quote_data.get('high', 0),
                    'low': quote_data.get('low', 0),
                    'ltp': quote_data.get('ltp', 0),
                    'ltq': 0,
                    'open': quote_data.get('open', 0),
                    'prev_close': quote_data.get('prev_close', 0),
                    'volume': quote_data.get('volume', 0),
                    'oi': 0,
                    'totalbuyqty': 0,
                    'totalsellqty': 0
                }

            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)

            # Build payload for market depth API
            payload = {
                "symbolName": br_symbol
            }
            # Add exchange if not NSE (NSE is default)
            if exchange and exchange != 'NSE':
                payload["exchange"] = exchange

            response = get_api_response("/marketDepth",
                                       self.auth_token,
                                       "POST",
                                       payload)

            if response.get('status') != 'Success':
                raise Exception(f"Error from Samco API: {response.get('statusMessage', 'Unknown error')}")

            # Extract market depth data
            market_depth_details = response.get('MarketDepthDetails', {})
            depth = market_depth_details.get('marketDepth', {})
            if not depth:
                raise Exception("No depth data received")

            # Format bids and asks with exactly 5 entries each
            bids = []
            asks = []

            # Process buy orders (top 5) - bestFiveBid
            buy_orders = depth.get('bestFiveBid', [])
            for i in range(5):
                if i < len(buy_orders):
                    bid = buy_orders[i]
                    bids.append({
                        'price': safe_float(bid.get('bidPrice')),
                        'quantity': safe_int(bid.get('bidSize'))
                    })
                else:
                    bids.append({'price': 0, 'quantity': 0})

            # Process sell orders (top 5) - bestFiveAsk
            sell_orders = depth.get('bestFiveAsk', [])
            for i in range(5):
                if i < len(sell_orders):
                    ask = sell_orders[i]
                    asks.append({
                        'price': safe_float(ask.get('askPrice')),
                        'quantity': safe_int(ask.get('askSize'))
                    })
                else:
                    asks.append({'price': 0, 'quantity': 0})

            # Get LTP from quote API since marketDepth doesn't provide OHLC
            # We'll fetch additional quote data for complete response
            try:
                quote_data = self.get_quotes(symbol, exchange)
                ltp = quote_data.get('ltp', 0)
                open_price = quote_data.get('open', 0)
                high = quote_data.get('high', 0)
                low = quote_data.get('low', 0)
                prev_close = quote_data.get('prev_close', 0)
                volume = quote_data.get('volume', 0)
                oi = quote_data.get('oi', 0)
            except Exception:
                # If quote fetch fails, use zeros
                ltp = open_price = high = low = prev_close = volume = oi = 0

            # Return depth data in common format matching REST API response
            return {
                'bids': bids,
                'asks': asks,
                'high': high,
                'low': low,
                'ltp': ltp,
                'ltq': 0,  # Not available in marketDepth response
                'open': open_price,
                'prev_close': prev_close,
                'volume': volume,
                'oi': oi,
                'totalbuyqty': safe_int(depth.get('tBuyQty')),
                'totalsellqty': safe_int(depth.get('tSellQty'))
            }

        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols with automatic batching
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            BATCH_SIZE = 25  # Samco API limit per request
            RATE_LIMIT_DELAY = 0.2  # Rate limit: 5 requests per second

            # Separate index symbols from regular symbols
            index_symbols = []
            regular_symbols = []

            for item in symbols:
                if item['exchange'] in ['NSE_INDEX', 'BSE_INDEX']:
                    index_symbols.append(item)
                else:
                    regular_symbols.append(item)

            results = []

            # Process regular symbols via multiQuote API with batching
            if regular_symbols:
                if len(regular_symbols) > BATCH_SIZE:
                    logger.info(f"Processing {len(regular_symbols)} symbols in batches of {BATCH_SIZE}")

                    for i in range(0, len(regular_symbols), BATCH_SIZE):
                        batch = regular_symbols[i:i + BATCH_SIZE]
                        logger.debug(f"Processing batch {i//BATCH_SIZE + 1}: symbols {i+1} to {min(i+BATCH_SIZE, len(regular_symbols))}")

                        batch_results = self._process_multiquotes_batch(batch)
                        results.extend(batch_results)

                        # Rate limit delay between batches
                        if i + BATCH_SIZE < len(regular_symbols):
                            time.sleep(RATE_LIMIT_DELAY)

                    logger.info(f"Successfully processed {len(results)} quotes in {(len(regular_symbols) + BATCH_SIZE - 1) // BATCH_SIZE} batches")
                else:
                    regular_results = self._process_multiquotes_batch(regular_symbols)
                    results.extend(regular_results)

            # Process index symbols individually (multiQuote INDEX key needs index names)
            if index_symbols:
                index_results = self._process_index_quotes_batch(index_symbols)
                results.extend(index_results)

            return results

        except Exception as e:
            logger.exception("Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _process_multiquotes_batch(self, symbols: list) -> list:
        """
        Process a batch of regular symbols using Samco multiQuote API
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
        Returns:
            list: List of quote data for the batch
        """
        # Group symbols by exchange
        exchange_symbols = {}  # {exchange: [br_symbol1, br_symbol2, ...]}
        symbol_map = {}  # {exchange:br_symbol -> {symbol, exchange}}
        skipped_symbols = []

        for item in symbols:
            symbol = item['symbol']
            exchange = item['exchange']

            try:
                br_symbol = get_br_symbol(symbol, exchange)

                if not br_symbol:
                    logger.warning(f"Skipping symbol {symbol} on {exchange}: could not resolve broker symbol")
                    skipped_symbols.append({
                        'symbol': symbol,
                        'exchange': exchange,
                        'error': 'Could not resolve broker symbol'
                    })
                    continue

                # Map exchange for API (MFO is separate in Samco)
                api_exchange = exchange

                if api_exchange not in exchange_symbols:
                    exchange_symbols[api_exchange] = []
                exchange_symbols[api_exchange].append(br_symbol)

                # Store mapping for response parsing
                symbol_map[f"{api_exchange}:{br_symbol}"] = {
                    'symbol': symbol,
                    'exchange': exchange,
                    'br_symbol': br_symbol
                }

            except Exception as e:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: {str(e)}")
                skipped_symbols.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'error': str(e)
                })
                continue

        # Return skipped symbols if no valid symbols
        if not exchange_symbols:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        # Build payload for Samco multiQuote API
        payload = {}
        for exchange, br_symbols in exchange_symbols.items():
            payload[exchange] = br_symbols

        logger.info(f"Requesting multiquotes for {sum(len(s) for s in exchange_symbols.values())} instruments across {len(exchange_symbols)} exchanges")
        logger.debug(f"Payload: {payload}")

        # Make API call
        response = get_api_response("/quote/multiQuote",
                                   self.auth_token,
                                   "POST",
                                   payload)

        if response.get('status') != 'Success':
            error_msg = f"Error from Samco API: {response.get('statusMessage', 'Unknown error')}"
            logger.error(error_msg)
            logger.debug(f"Full API response: {response}")
            raise Exception(error_msg)

        # Parse response and build results
        results = []
        multi_quotes = response.get('multiQuotes', [])

        # Create a lookup by exchange:tradingSymbol for quick access
        quotes_by_symbol = {}
        for quote in multi_quotes:
            exchange = quote.get('exchange')
            trading_symbol = quote.get('tradingSymbol')
            symbol_name = quote.get('symbolName')
            if exchange and trading_symbol:
                quotes_by_symbol[f"{exchange}:{trading_symbol}"] = quote
                # Also map by symbolName for equity
                if symbol_name:
                    quotes_by_symbol[f"{exchange}:{symbol_name}"] = quote

        # Build results from symbol_map
        for key, original in symbol_map.items():
            quote = quotes_by_symbol.get(key)

            # Try alternate key formats
            if not quote:
                # Try with just the broker symbol
                for qkey, qval in quotes_by_symbol.items():
                    if original['br_symbol'] in qkey:
                        quote = qval
                        break

            if not quote:
                logger.warning(f"No quote data found for {original['symbol']} ({key})")
                results.append({
                    'symbol': original['symbol'],
                    'exchange': original['exchange'],
                    'error': 'No quote data available'
                })
                continue

            # Parse and format quote data
            result_item = {
                'symbol': original['symbol'],
                'exchange': original['exchange'],
                'data': {
                    'bid': safe_float(quote.get('bidPrice')),
                    'ask': safe_float(quote.get('askPrice')),
                    'open': safe_float(quote.get('open')),
                    'high': safe_float(quote.get('high')),
                    'low': safe_float(quote.get('low')),
                    'ltp': safe_float(quote.get('lastTradePrice')),
                    'prev_close': safe_float(quote.get('previousClose')),
                    'volume': safe_int(quote.get('totalTradeVolume')),
                    'oi': safe_int(quote.get('openInterest'))
                }
            }
            results.append(result_item)

        # Include skipped symbols in results
        return skipped_symbols + results

    def _process_index_quotes_batch(self, symbols: list) -> list:
        """
        Process index symbols using Samco indexQuote API
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys for indices
        Returns:
            list: List of quote data for index symbols
        """
        results = []

        for item in symbols:
            symbol = item['symbol']
            exchange = item['exchange']

            try:
                quote_data = self._get_index_quotes(symbol, exchange)
                results.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'data': quote_data
                })
            except Exception as e:
                logger.warning(f"Error fetching index quote for {symbol}: {str(e)}")
                results.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'error': str(e)
                })

        return results

    def get_history(self, symbol: str, exchange: str, interval: str,
                   start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX)
            interval: Candle interval (1m, 5m, 10m, 15m, 30m, 1h, D)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume, oi]
        """
        try:
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            logger.debug(f"Debug - Symbol: {symbol}, Exchange: {exchange}, Broker Symbol: {br_symbol}")

            # Convert dates to datetime objects
            from_date = pd.to_datetime(start_date)
            to_date = pd.to_datetime(end_date)
            current_date = pd.Timestamp.now().normalize()

            # Determine if this is an index symbol
            is_index = exchange in ['NSE_INDEX', 'BSE_INDEX']

            # For daily timeframe, use historical endpoint
            if interval == 'D':
                # Check if end_date is today - need to combine historical + intraday
                if to_date.date() == current_date.date() and from_date.date() < current_date.date():
                    logger.debug("Debug - Daily data including today - fetching historical + intraday")

                    yesterday = current_date - pd.Timedelta(days=1)
                    historical_df = self._get_historical_data(
                        symbol, br_symbol, exchange, interval,
                        from_date, yesterday, is_index
                    )

                    # For daily, we can skip intraday as historical usually has yesterday's data
                    return historical_df
                else:
                    return self._get_historical_data(symbol, br_symbol, exchange, interval, from_date, to_date, is_index)

            # For intraday timeframes (1m, 5m, etc.), use intraday endpoint
            # Samco intraday endpoint supports date range
            return self._get_intraday_data_range(symbol, br_symbol, exchange, interval, from_date, to_date, is_index)

        except Exception as e:
            logger.error(f"Debug - Error: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")

    def _get_historical_data(self, symbol: str, br_symbol: str, exchange: str, interval: str,
                             from_date: pd.Timestamp, to_date: pd.Timestamp, is_index: bool) -> pd.DataFrame:
        """
        Helper method to fetch historical data from Samco historical endpoint
        Args:
            symbol: Trading symbol (OpenAlgo format)
            br_symbol: Broker symbol
            exchange: Exchange
            interval: Candle interval
            from_date: Start datetime
            to_date: End datetime
            is_index: Whether this is an index symbol
        Returns:
            pd.DataFrame: Historical data
        """
        try:
            # Check for unsupported timeframes - Samco historical only supports daily
            if interval != 'D':
                logger.debug(f"Debug - Historical endpoint only supports daily data, interval '{interval}' not available")
                return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])

            # Format dates for Samco API (yyyy-MM-dd)
            from_date_str = from_date.strftime('%Y-%m-%d')
            to_date_str = to_date.strftime('%Y-%m-%d')

            if is_index:
                # Use index historical endpoint
                index_name = self._get_index_name(symbol)
                params = f"indexName={index_name}&fromDate={from_date_str}&toDate={to_date_str}"
                endpoint = f"/history/indexCandleData?{params}"
                data_key = 'indexCandleData'
            else:
                # Use regular historical endpoint
                params = f"symbolName={br_symbol}&fromDate={from_date_str}&toDate={to_date_str}"
                if exchange and exchange != 'NSE':
                    params += f"&exchange={exchange}"
                endpoint = f"/history/candleData?{params}"
                data_key = 'historicalCandleData'

            logger.debug(f"Debug - Historical API endpoint: {endpoint}")

            response = get_api_response(endpoint, self.auth_token, "GET")

            if response.get('status') != 'Success':
                logger.warning(f"Debug - Historical API error: {response.get('statusMessage', 'Unknown error')}")
                return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])

            # Extract candle data
            candles = response.get(data_key, [])
            if not candles:
                logger.debug("Debug - No historical data received")
                return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])

            # Convert to DataFrame
            df = pd.DataFrame(candles)
            logger.debug(f"Debug - Received {len(candles)} historical candles")

            # Rename date column to timestamp
            if 'date' in df.columns:
                df.rename(columns={'date': 'timestamp'}, inplace=True)

            # Parse timestamp
            df['timestamp'] = pd.to_datetime(df['timestamp'])

            # For daily timeframe, normalize to midnight (date only, no time component)
            df['timestamp'] = df['timestamp'].dt.normalize()

            # Convert to Unix epoch (UTC midnight for the date)
            df['timestamp'] = df['timestamp'].astype('int64') // 10**9

            # Ensure numeric columns
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

            # Add OI column if not present
            if 'oi' not in df.columns:
                df['oi'] = 0

            # Sort by timestamp and remove duplicates
            df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)

            # Reorder columns to match OpenAlgo format
            df = df[['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi']]

            return df

        except Exception as e:
            logger.error(f"Debug - Error in _get_historical_data: {str(e)}")
            raise

    def _get_intraday_data_range(self, symbol: str, br_symbol: str, exchange: str, interval: str,
                                   from_date: pd.Timestamp, to_date: pd.Timestamp, is_index: bool) -> pd.DataFrame:
        """
        Get intraday data for a date range using Samco intraday endpoint
        Args:
            symbol: Trading symbol (OpenAlgo format)
            br_symbol: Broker symbol
            exchange: Exchange
            interval: Candle interval
            from_date: Start date
            to_date: End date
            is_index: Whether this is an index symbol
        Returns:
            pd.DataFrame: Intraday data
        """
        try:
            from urllib.parse import quote

            # Set time components for the date range
            from_datetime = from_date.replace(hour=0, minute=0, second=0, microsecond=0)
            to_datetime = to_date.replace(hour=23, minute=59, second=59, microsecond=0)

            from_date_str = from_datetime.strftime('%Y-%m-%d %H:%M:%S')
            to_date_str = to_datetime.strftime('%Y-%m-%d %H:%M:%S')

            # URL encode the date strings (spaces become %20)
            from_date_encoded = quote(from_date_str)
            to_date_encoded = quote(to_date_str)

            # Map interval (default is 1 minute if not specified)
            interval_param = ""
            if interval and interval != '1m':
                # Samco accepts interval as minutes
                interval_map = {
                    '1m': '1',
                    '5m': '5',
                    '10m': '10',
                    '15m': '15',
                    '30m': '30',
                    '1h': '60'
                }
                interval_val = interval_map.get(interval)
                if interval_val:
                    interval_param = f"&interval={interval_val}"

            if is_index:
                # Use index intraday endpoint
                index_name = self._get_index_name(symbol)
                params = f"indexName={quote(index_name)}&fromDate={from_date_encoded}&toDate={to_date_encoded}{interval_param}"
                endpoint = f"/intraday/indexCandleData?{params}"
                data_key = 'indexIntraDayCandleData'
            else:
                # Use regular intraday endpoint
                params = f"symbolName={quote(br_symbol)}&fromDate={from_date_encoded}&toDate={to_date_encoded}{interval_param}"
                if exchange and exchange != 'NSE':
                    params += f"&exchange={exchange}"
                endpoint = f"/intraday/candleData?{params}"
                data_key = 'intradayCandleData'

            logger.debug(f"Debug - Intraday API endpoint: {endpoint}")

            response = get_api_response(endpoint, self.auth_token, "GET")

            if response.get('status') != 'Success':
                logger.warning(f"Debug - Intraday API error: {response.get('statusMessage', 'Unknown error')}")
                return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])

            # Extract candle data
            candles = response.get(data_key, [])
            if not candles:
                logger.debug("Debug - No intraday data received")
                return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])

            # Convert to DataFrame
            df = pd.DataFrame(candles)
            logger.debug(f"Debug - Received {len(candles)} intraday candles")

            # Rename dateTime column to timestamp
            if 'dateTime' in df.columns:
                df.rename(columns={'dateTime': 'timestamp'}, inplace=True)

            # Parse timestamp (format: "2019-11-11 10:01:00")
            df['timestamp'] = pd.to_datetime(df['timestamp'])

            # Convert to IST and then to UTC for epoch
            df['timestamp'] = df['timestamp'].dt.tz_localize('Asia/Kolkata')
            df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
            df['timestamp'] = df['timestamp'].dt.tz_localize(None)

            # Convert to Unix epoch
            df['timestamp'] = df['timestamp'].astype('int64') // 10**9

            # Ensure numeric columns
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(',', ''), errors='coerce').fillna(0)

            # Add OI column if not present
            if 'oi' not in df.columns:
                df['oi'] = 0

            # Sort by timestamp and remove duplicates
            df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)

            # Reorder columns to match OpenAlgo format
            df = df[['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi']]

            return df

        except Exception as e:
            logger.error(f"Debug - Error fetching intraday data: {str(e)}")
            raise Exception(f"Error fetching intraday data: {str(e)}")
