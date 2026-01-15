import httpx
import json
import os
import pandas as pd
import time
import asyncio
from datetime import datetime, timedelta
import urllib.parse
from database.token_db import get_token, get_br_symbol, get_oa_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from concurrent.futures import ThreadPoolExecutor

# Toggle between async and threaded approach
USE_ASYNC = True  # Set to True to use asyncio (better performance)

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="POST", payload=None):
    """
    Common function to make API calls to Zebu using httpx with connection pooling
    """
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_KEY')

    if payload is None:
        data = {
            "uid": api_key
        }
    else:
        data = payload
        data["uid"] = api_key

    payload_str = "jData=" + json.dumps(data) + "&jKey=" + AUTH_TOKEN

    # Get the shared httpx client
    client = get_httpx_client()

    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    url = f"https://go.mynt.in{endpoint}"

    response = client.request(method, url, content=payload_str, headers=headers)
    data = response.text

    return json.loads(data)

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Zebu data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Zebu resolutions
        # Note: Weekly and Monthly intervals are not supported
        self.timeframe_map = {
            # Minutes
            '1m': '1',    # 1 minute
            '3m': '3',    # 3 minutes
            '5m': '5',    # 5 minutes
            '10m': '10',  # 10 minutes
            '15m': '15',  # 15 minutes
            '30m': '30',  # 30 minutes
            # Hours
            '1h': '60',   # 1 hour (60 minutes)
            '2h': '120',  # 2 hours (120 minutes)
            '4h': '240',  # 4 hours (240 minutes)
            # Daily
            'D': 'D'      # Daily data
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Simplified quote data with required fields
        """
        try:
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)

            # Convert OpenAlgo exchange to broker exchange for API calls
            api_exchange = exchange
            if exchange == "NSE_INDEX":
                api_exchange = "NSE"
            elif exchange == "BSE_INDEX":
                api_exchange = "BSE"

            payload = {
                "uid": os.getenv('BROKER_API_KEY'),
                "exch": api_exchange,
                "token": token
            }
            
            response = get_api_response("/NorenWClientTP/GetQuotes", self.auth_token, payload=payload)
            
            if response.get('stat') != 'Ok':
                raise Exception(f"Error from Zebu API: {response.get('emsg', 'Unknown error')}")
            
            # Return simplified quote data
            return {
                'bid': float(response.get('bp1', 0)),
                'ask': float(response.get('sp1', 0)),
                'open': float(response.get('o', 0)),
                'high': float(response.get('h', 0)),
                'low': float(response.get('l', 0)),
                'ltp': float(response.get('lp', 0)),
                'prev_close': float(response.get('c', 0)) if 'c' in response else 0,
                'volume': int(response.get('v', 0)),
                'oi': int(response.get('oi', 0))
            }
            
        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}")

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols with automatic batching
        Zebu API Rate Limit: 10 requests per second per user

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            # Zebu API rate limit: 10 requests per second per user
            BATCH_SIZE = 10  # Process 10 symbols per batch (matches rate limit)
            RATE_LIMIT_DELAY = 1.0  # 1 second delay between batches

            if len(symbols) > BATCH_SIZE:
                logger.debug(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
                all_results = []

                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i:i + BATCH_SIZE]
                    logger.info(f"Processing batch {i//BATCH_SIZE + 1}: symbols {i+1} to {min(i+BATCH_SIZE, len(symbols))}")

                    batch_results = self._process_quotes_batch(batch)
                    all_results.extend(batch_results)

                    # Rate limit delay between batches
                    if i + BATCH_SIZE < len(symbols):
                        time.sleep(RATE_LIMIT_DELAY)

                logger.info(f"Successfully processed {len(all_results)} quotes in {(len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE} batches")
                return all_results
            else:
                return self._process_quotes_batch(symbols)

        except Exception as e:
            logger.exception(f"Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _fetch_single_quote_sync(self, symbol: str, exchange: str, api_exchange: str, token: str, api_key: str) -> dict:
        """
        Fetch quote for a single symbol synchronously (for ThreadPoolExecutor)
        """
        try:
            data = {
                "uid": api_key,
                "exch": api_exchange,
                "token": token
            }

            payload_str = "jData=" + json.dumps(data) + "&jKey=" + self.auth_token
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            url = "https://go.mynt.in/NorenWClientTP/GetQuotes"

            # Use httpx.post for sync requests
            http_response = httpx.post(url, content=payload_str, headers=headers, timeout=10.0)
            response = http_response.json()

            if response.get('stat') != 'Ok':
                return {
                    'symbol': symbol,
                    'exchange': exchange,
                    'error': response.get('emsg', 'Unknown error')
                }

            return {
                'symbol': symbol,
                'exchange': exchange,
                'data': {
                    'bid': float(response.get('bp1', 0)),
                    'ask': float(response.get('sp1', 0)),
                    'open': float(response.get('o', 0)),
                    'high': float(response.get('h', 0)),
                    'low': float(response.get('l', 0)),
                    'ltp': float(response.get('lp', 0)),
                    'prev_close': float(response.get('c', 0)) if 'c' in response else 0,
                    'volume': int(response.get('v', 0)),
                    'oi': int(response.get('oi', 0))
                }
            }

        except Exception as e:
            return {
                'symbol': symbol,
                'exchange': exchange,
                'error': str(e)
            }

    async def _fetch_single_quote_async(self, client: httpx.AsyncClient, symbol: str, exchange: str, api_exchange: str, token: str, api_key: str) -> dict:
        """
        Fetch quote for a single symbol asynchronously
        """
        try:
            data = {
                "uid": api_key,
                "exch": api_exchange,
                "token": token
            }

            payload_str = "jData=" + json.dumps(data) + "&jKey=" + self.auth_token
            headers = {'Content-Type': 'application/x-www-form-urlencoded'}
            url = "https://go.mynt.in/NorenWClientTP/GetQuotes"

            # Use async httpx client
            http_response = await client.post(url, content=payload_str, headers=headers)
            response = http_response.json()

            if response.get('stat') != 'Ok':
                logger.warning(f"Error fetching quote for {symbol}@{exchange}: {response.get('emsg', 'Unknown error')}")
                return {
                    'symbol': symbol,
                    'exchange': exchange,
                    'error': response.get('emsg', 'Unknown error')
                }

            return {
                'symbol': symbol,
                'exchange': exchange,
                'data': {
                    'bid': float(response.get('bp1', 0)),
                    'ask': float(response.get('sp1', 0)),
                    'open': float(response.get('o', 0)),
                    'high': float(response.get('h', 0)),
                    'low': float(response.get('l', 0)),
                    'ltp': float(response.get('lp', 0)),
                    'prev_close': float(response.get('c', 0)) if 'c' in response else 0,
                    'volume': int(response.get('v', 0)),
                    'oi': int(response.get('oi', 0))
                }
            }

        except Exception as e:
            logger.warning(f"Error processing quote for {symbol}@{exchange}: {str(e)}")
            return {
                'symbol': symbol,
                'exchange': exchange,
                'error': str(e)
            }

    async def _process_quotes_batch_async(self, symbols: list, api_key: str) -> list:
        """
        Process a batch of symbols using async httpx
        """
        results = []

        # High connection limits for maximum concurrency
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=100)
        async with httpx.AsyncClient(timeout=10.0, limits=limits) as client:
            tasks = [
                self._fetch_single_quote_async(
                    client,
                    item['symbol'],
                    item['exchange'],
                    item['api_exchange'],
                    item['token'],
                    api_key
                )
                for item in symbols
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error dicts
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append({
                    'symbol': symbols[i]['symbol'],
                    'exchange': symbols[i]['exchange'],
                    'error': str(result)
                })
            else:
                final_results.append(result)

        return final_results

    def _process_quotes_batch(self, symbols: list) -> list:
        """
        Process a single batch of symbols using concurrent API calls
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys (max 40)
        Returns:
            list: List of quote data for the batch
        """
        skipped_symbols = []
        prepared_symbols = []

        # Pre-fetch API key
        api_key = os.getenv('BROKER_API_KEY')

        # Step 1: Pre-resolve all tokens sequentially (database access)
        for item in symbols:
            symbol = item['symbol']
            exchange = item['exchange']

            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)

            if not br_symbol or not token:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: could not resolve broker symbol or token")
                skipped_symbols.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'error': 'Could not resolve broker symbol or token'
                })
                continue

            # Map exchange to API format
            api_exchange = exchange
            if exchange == "NSE_INDEX":
                api_exchange = "NSE"
            elif exchange == "BSE_INDEX":
                api_exchange = "BSE"

            prepared_symbols.append({
                'symbol': symbol,
                'exchange': exchange,
                'api_exchange': api_exchange,
                'token': token
            })

        if not prepared_symbols:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        # Step 2: Make concurrent API calls
        if USE_ASYNC:
            # Async approach with httpx.AsyncClient
            results = asyncio.run(self._process_quotes_batch_async(prepared_symbols, api_key))
        else:
            # ThreadPoolExecutor approach
            with ThreadPoolExecutor(max_workers=min(len(prepared_symbols), 20)) as executor:
                futures = [
                    executor.submit(
                        self._fetch_single_quote_sync,
                        item['symbol'],
                        item['exchange'],
                        item['api_exchange'],
                        item['token'],
                        api_key
                    )
                    for item in prepared_symbols
                ]
                results = [f.result() for f in futures]

        return skipped_symbols + results

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
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)

            # Convert OpenAlgo exchange to broker exchange for API calls
            api_exchange = exchange
            if exchange == "NSE_INDEX":
                api_exchange = "NSE"
            elif exchange == "BSE_INDEX":
                api_exchange = "BSE"

            payload = {
                "uid": os.getenv('BROKER_API_KEY'),
                "exch": api_exchange,
                "token": token
            }
            
            response = get_api_response("/NorenWClientTP/GetQuotes", self.auth_token, payload=payload)
            
            if response.get('stat') != 'Ok':
                raise Exception(f"Error from Zebu API: {response.get('emsg', 'Unknown error')}")
            
            # Format bids and asks data
            bids = []
            asks = []
            
            # Process top 5 bids and asks
            for i in range(1, 6):
                bids.append({
                    'price': float(response.get(f'bp{i}', 0)),
                    'quantity': int(response.get(f'bq{i}', 0))
                })
                asks.append({
                    'price': float(response.get(f'sp{i}', 0)),
                    'quantity': int(response.get(f'sq{i}', 0))
                })
            
            # Return depth data
            return {
                'bids': bids,
                'asks': asks,
                'totalbuyqty': sum(bid['quantity'] for bid in bids),
                'totalsellqty': sum(ask['quantity'] for ask in asks),
                'high': float(response.get('h', 0)),
                'low': float(response.get('l', 0)),
                'ltp': float(response.get('lp', 0)),
                'ltq': int(response.get('ltq', 0)),  # Last Traded Quantity
                'open': float(response.get('o', 0)),
                'prev_close': float(response.get('c', 0)) if 'c' in response else 0,
                'volume': int(response.get('v', 0)),
                'oi': int(response.get('oi', 0))  # Open Interest from Zebu
            }
            
        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Candle interval in common format:
                     Minutes: 1m, 3m, 5m, 10m, 15m, 30m
                     Hours: 1h, 2h, 4h
                     Days: D
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Check if interval is supported
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(f"Unsupported interval '{interval}'. Supported intervals are: {', '.join(supported)}")

            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)
            
            # Convert dates to epoch timestamps
            # Handle both string and date object inputs
            if isinstance(start_date, str):
                start_ts = int(datetime.strptime(start_date + " 00:00:00", '%Y-%m-%d %H:%M:%S').timestamp())
            else:
                # If it's a date object, combine with time
                start_dt = datetime.combine(start_date, datetime.min.time())
                start_ts = int(start_dt.timestamp())

            if isinstance(end_date, str):
                end_ts = int(datetime.strptime(end_date + " 23:59:59", '%Y-%m-%d %H:%M:%S').timestamp())
            else:
                # If it's a date object, combine with end of day time
                end_dt = datetime.combine(end_date, datetime.max.time().replace(microsecond=0))
                end_ts = int(end_dt.timestamp())

            # For daily data, use EODChartData endpoint
            if interval == 'D':
                payload = {
                    "sym": f"{exchange}:{br_symbol}",
                    "from": str(start_ts),
                    "to": str(end_ts)
                }
                
                logger.debug(f"EOD Payload: {payload}")  # Debug print
                try:
                    response = get_api_response("/NorenWClientTP/EODChartData", self.auth_token, payload=payload)
                    logger.debug(f"EOD Response: {response}")  # Debug print
                except Exception as e:
                    logger.error(f"Error in EOD request: {e}")
                    response = []  # Continue with empty response to try quotes
            else:
                # For intraday data, use TPSeries endpoint
                payload = {
                    "uid": os.getenv('BROKER_API_KEY'),
                    "exch": exchange,
                    "token": token,
                    "st": str(start_ts),
                    "et": str(end_ts),
                    "intrv": self.timeframe_map[interval]
                }
                
                logger.debug(f"Intraday Payload: {payload}")  # Debug print
                response = get_api_response("/NorenWClientTP/TPSeries", self.auth_token, payload=payload)
                logger.debug(f"Intraday Response: {response}")  # Debug print

            # Convert response to DataFrame
            data = []
            for candle in response:
                if isinstance(candle, str):
                    candle = json.loads(candle)
                
                try:
                    if interval == 'D':
                        # EOD data format
                        timestamp = int(candle.get('ssboe', 0))
                        data.append({
                            'timestamp': timestamp,
                            'open': float(candle.get('into', 0)),
                            'high': float(candle.get('inth', 0)),
                            'low': float(candle.get('intl', 0)),
                            'close': float(candle.get('intc', 0)),
                            'volume': float(candle.get('intv', 0)),
                            'oi': float(candle.get('oi', 0))
                        })
                    else:
                        # Skip candles with all zero values
                        if (float(candle.get('into', 0)) == 0 and
                            float(candle.get('inth', 0)) == 0 and
                            float(candle.get('intl', 0)) == 0 and
                            float(candle.get('intc', 0)) == 0):
                            continue

                        # Intraday format
                        timestamp = int(datetime.strptime(candle['time'], '%d-%m-%Y %H:%M:%S').timestamp())
                        data.append({
                            'timestamp': timestamp,
                            'open': float(candle.get('into', 0)),
                            'high': float(candle.get('inth', 0)),
                            'low': float(candle.get('intl', 0)),
                            'close': float(candle.get('intc', 0)),
                            'volume': float(candle.get('intv', 0)),
                            'oi': float(candle.get('oi', 0))
                        })
                except (KeyError, ValueError) as e:
                    logger.error(f"Error parsing candle data: {e}, Candle: {candle}")
                    continue

            df = pd.DataFrame(data)
            if df.empty:
                df = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])

            # For daily data, append today's data from quotes if it's missing
            if interval == 'D':
                today_ts = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
                
                # Only get today's data if it's within the requested range
                if today_ts >= start_ts and today_ts <= end_ts:
                    if df.empty or df['timestamp'].max() < today_ts:
                        try:
                            # Get today's data from quotes
                            payload = {
                                "exch": exchange,
                                "token": token
                            }
                            quotes_response = get_api_response("/NorenWClientTP/GetQuotes", self.auth_token, payload=payload)
                            logger.debug(f"Quotes Response: {quotes_response}")  # Debug print
                            
                            if quotes_response and quotes_response.get('stat') == 'Ok':
                                today_data = {
                                    'timestamp': today_ts,
                                    'open': float(quotes_response.get('o', 0)),
                                    'high': float(quotes_response.get('h', 0)),
                                    'low': float(quotes_response.get('l', 0)),
                                    'close': float(quotes_response.get('lp', 0)),  # Use LTP as close
                                    'volume': float(quotes_response.get('v', 0)),
                                    'oi': float(quotes_response.get('oi', 0))
                                }
                                logger.info(f"Today's quote data: {today_data}")
                                # Append today's data
                                df = pd.concat([df, pd.DataFrame([today_data])], ignore_index=True)
                                logger.info("Added today's data from quotes")
                        except Exception as e:
                            logger.info(f"Error fetching today's data from quotes: {e}")
                else:
                    logger.info(f"Today ({today_ts}) is outside requested range ({start_ts} to {end_ts})")

            # Sort by timestamp
            df = df.sort_values('timestamp')
            return df
            
        except Exception as e:
            logger.error(f"Error in get_history: {e}")  # Add debug logging
            raise Exception(f"Error fetching historical data: {str(e)}")
