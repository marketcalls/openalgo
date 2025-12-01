import os
import json
import time
import pandas as pd
from datetime import datetime, timedelta
from utils.httpx_client import get_httpx_client
from broker.mstock.mapping.order_data import transform_positions_data, transform_holdings_data
from broker.mstock.api.mstockwebsocket import MstockWebSocket
from database.token_db import get_br_symbol, get_token, get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth_token, method="GET", payload=None):
    """Helper function to make API calls to mstock"""
    api_key = os.getenv('BROKER_API_SECRET')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'Bearer {auth_token}',
        'X-PrivateKey': api_key,
        'Accept': 'application/json'
    }

    url = f"https://api.mstock.trade/openapi/typeb{endpoint}"

    try:
        # Log the request details for debugging
        logger.debug(f"API Request - Method: {method}, URL: {url}")
        logger.debug(f"API Request - Payload: {payload}")

        if method == "GET":
            if payload:
                # For GET with JSON body, use json parameter
                response = client.request("GET", url, headers=headers, json=payload)
            else:
                response = client.get(url, headers=headers)
        elif method == "POST":
            # For POST, use json parameter to auto-encode
            response = client.post(url, headers=headers, json=payload)
        else:
            response = client.request(method, url, headers=headers, json=payload)

        logger.debug(f"API Response - Status: {response.status_code}")
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"API call failed: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"Response text: {e.response.text}")
        raise


def get_positions(auth_token):
    """
    Retrieves the user's positions using Type B authentication.
    """
    api_key = os.getenv('BROKER_API_SECRET')
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'Bearer {auth_token}',
        'X-PrivateKey': api_key,
    }

    try:
        client = get_httpx_client()
        response = client.get(
            'https://api.mstock.trade/openapi/typeb/portfolio/positions',
            headers=headers,
        )
        response.raise_for_status()
        positions = response.json()
        return transform_positions_data(positions), None
    except Exception as e:
        return None, str(e)

def get_holdings(auth_token):
    """
    Retrieves the user's holdings using Type B authentication.
    """
    api_key = os.getenv('BROKER_API_SECRET')
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'Bearer {auth_token}',
        'X-PrivateKey': api_key,
    }

    try:
        client = get_httpx_client()
        response = client.get(
            'https://api.mstock.trade/openapi/typeb/portfolio/holdings',
            headers=headers,
        )
        response.raise_for_status()
        holdings = response.json()
        return transform_holdings_data(holdings), None
    except Exception as e:
        return None, str(e)


class BrokerData:
    def __init__(self, auth_token):
        """Initialize mstock data handler with authentication token"""
        self.auth_token = auth_token
        self.websocket = MstockWebSocket(auth_token)
        # Map common timeframe format to mstock intervals
        self.timeframe_map = {
            # Minutes
            '1m': 'ONE_MINUTE',
            '3m': 'THREE_MINUTE',
            '5m': 'FIVE_MINUTE',
            '10m': 'TEN_MINUTE',
            '15m': 'FIFTEEN_MINUTE',
            '30m': 'THIRTY_MINUTE',
            # Hours
            '1h': 'ONE_HOUR',
            # Daily
            'D': 'ONE_DAY'
        }

        # Exchange code mapping for historical API (mstock uses NSE, NFO etc. as strings)
        self.exchange_map = {
            'NSE': 'NSE',
            'BSE': 'BSE',
            'NFO': 'NFO',
            'BFO': 'BFO',
            'CDS': 'CDS',
            'MCX': 'MCX',
            'NSE_INDEX': 'NSE',
            'BSE_INDEX': 'BSE',
            'MCX_INDEX': 'MCX'
        }

        # Exchange code mapping for intraday API (numeric codes)
        self.intraday_exchange_map = {
            'NSE': '1',
            'BSE': '4',
            'NFO': '2',
            'BFO': '5',
            'CDS': '3',
            'MCX': '6',
            'NSE_INDEX': '1',
            'BSE_INDEX': '4',
            'MCX_INDEX': '6'
        }

        # Interval mapping for intraday API (same as historical API format)
        self.intraday_interval_map = {
            '1m': 'ONE_MINUTE',
            '3m': 'THREE_MINUTE',
            '5m': 'FIVE_MINUTE',
            '10m': 'TEN_MINUTE',
            '15m': 'FIFTEEN_MINUTE',
            '30m': 'THIRTY_MINUTE',
            '1h': 'ONE_HOUR',
            'D': 'ONE_DAY'
        }

        # Exchange type mapping for WebSocket
        # 1=NSECM, 2=NSEFO, 3=BSECM, 4=BSEFO, 13=NSECD
        self.ws_exchange_map = {
            'NSE': 1,
            'NFO': 2,
            'BSE': 3,
            'BFO': 4,
            'CDS': 13,
            'MCX': 5,  # Assuming MCX
            'NSE_INDEX': 1,
            'BSE_INDEX': 3
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol using REST API
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
        Returns:
            dict: Quote data with required fields
        """
        try:
            # Get token for the symbol
            token = get_token(symbol, exchange)

            if not token:
                raise Exception(f"Token not found for symbol: {symbol}, exchange: {exchange}")

            # Map exchange for API
            quote_exchange_map = {
                'NSE': 'NSE',
                'BSE': 'BSE',
                'NFO': 'NFO',
                'BFO': 'BFO',
                'CDS': 'CDS',
                'MCX': 'MCX',
                'NSE_INDEX': 'NSE',
                'BSE_INDEX': 'BSE',
                'MCX_INDEX': 'MCX'
            }

            api_exchange = quote_exchange_map.get(exchange)
            if not api_exchange:
                raise Exception(f"Exchange '{exchange}' not supported for quotes")

            logger.debug(f"Fetching quotes for {symbol} (token: {token}, exchange: {api_exchange})")

            # Call REST API for quote
            payload = {
                "mode": "OHLC",
                "exchangeTokens": {api_exchange: [str(token)]}
            }

            response = get_api_response("/instruments/quote", self.auth_token, "GET", payload)

            if not response.get('status'):
                raise Exception(f"API error: {response.get('message', 'Unknown error')}")

            # Extract quote from response
            fetched = response.get('data', {}).get('fetched', [])

            if not fetched:
                raise Exception("No quote data received from API")

            quote_data = fetched[0]

            # Return in OpenAlgo standard format
            return {
                'bid': 0,  # Not provided in OHLC mode
                'ask': 0,  # Not provided in OHLC mode
                'open': float(quote_data.get('open', 0)),
                'high': float(quote_data.get('high', 0)),
                'low': float(quote_data.get('low', 0)),
                'ltp': float(quote_data.get('ltp', 0)),
                'prev_close': float(quote_data.get('close', 0)),
                'volume': int(quote_data.get('volume', 0)) if quote_data.get('volume') else 0,
                'oi': 0  # Not provided in OHLC mode
            }

        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}")

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols using REST API
        mstock REST API supports fetching multiple instruments in one call

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            # mstock WebSocket creates new connection per request
            # Using batch size of 100 for practical response times
            BATCH_SIZE = 500
            RATE_LIMIT_DELAY = 1.0  # Delay between batches in seconds

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
        Process a batch of symbols using REST API /instruments/quote
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
        Returns:
            list: List of quote data for the batch
        """
        results = []
        skipped_symbols = []
        symbol_map = {}  # Map token to original symbol/exchange

        # Exchange mapping for quote API (uses exchange names like NSE, BSE)
        quote_exchange_map = {
            'NSE': 'NSE',
            'BSE': 'BSE',
            'NFO': 'NFO',
            'BFO': 'BFO',
            'CDS': 'CDS',
            'MCX': 'MCX',
            'NSE_INDEX': 'NSE',
            'BSE_INDEX': 'BSE',
            'MCX_INDEX': 'MCX'
        }

        # Step 1: Prepare tokens grouped by exchange
        exchange_tokens = {}  # {"NSE": ["3045", "1594"], "BSE": ["500410"]}

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
                token = get_token(symbol, exchange)
                api_exchange = quote_exchange_map.get(exchange)

                if not token:
                    logger.warning(f"Skipping symbol {symbol} on {exchange}: could not resolve token")
                    skipped_symbols.append({
                        'symbol': symbol,
                        'exchange': exchange,
                        'data': None,
                        'error': 'Could not resolve token'
                    })
                    continue

                if not api_exchange:
                    logger.warning(f"Skipping symbol {symbol}: Exchange '{exchange}' not supported")
                    skipped_symbols.append({
                        'symbol': symbol,
                        'exchange': exchange,
                        'data': None,
                        'error': f"Exchange '{exchange}' not supported"
                    })
                    continue

                # Group tokens by exchange
                if api_exchange not in exchange_tokens:
                    exchange_tokens[api_exchange] = []
                exchange_tokens[api_exchange].append(str(token))

                # Store mapping for response processing
                symbol_map[str(token)] = {
                    'symbol': symbol,
                    'exchange': exchange,
                    'token': token
                }

            except Exception as e:
                logger.warning(f"Error preparing {symbol} on {exchange}: {str(e)}")
                skipped_symbols.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'data': None,
                    'error': str(e)
                })

        if not symbol_map:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        # Step 2: Call REST API for bulk quotes
        try:
            payload = {
                "mode": "OHLC",
                "exchangeTokens": exchange_tokens
            }

            logger.info(f"Fetching {len(symbol_map)} quotes via REST API")
            response = get_api_response("/instruments/quote", self.auth_token, "GET", payload)

            if not response.get('status'):
                raise Exception(f"API error: {response.get('message', 'Unknown error')}")

            # Step 3: Process response - fetched quotes
            fetched = response.get('data', {}).get('fetched', [])

            for quote_data in fetched:
                token_str = str(quote_data.get('symbolToken', ''))
                info = symbol_map.get(token_str)

                if info:
                    results.append({
                        'symbol': info['symbol'],
                        'exchange': info['exchange'],
                        'data': {
                            'bid': 0,  # Not provided in OHLC mode
                            'ask': 0,  # Not provided in OHLC mode
                            'open': float(quote_data.get('open', 0)),
                            'high': float(quote_data.get('high', 0)),
                            'low': float(quote_data.get('low', 0)),
                            'ltp': float(quote_data.get('ltp', 0)),
                            'prev_close': float(quote_data.get('close', 0)),
                            'volume': int(quote_data.get('volume', 0)) if quote_data.get('volume') else 0,
                            'oi': 0  # Not provided in OHLC mode
                        }
                    })
                    # Remove from symbol_map to track unfetched
                    del symbol_map[token_str]

            # Add unfetched symbols as errors
            for token_str, info in symbol_map.items():
                results.append({
                    'symbol': info['symbol'],
                    'exchange': info['exchange'],
                    'error': 'No data received'
                })

        except Exception as e:
            logger.error(f"Error calling quote API: {str(e)}")
            # Mark all remaining as errors
            for info in symbol_map.values():
                results.append({
                    'symbol': info['symbol'],
                    'exchange': info['exchange'],
                    'error': str(e)
                })

        logger.info(f"Retrieved quotes for {len([r for r in results if 'data' in r])}/{len(symbols)} symbols")
        return skipped_symbols + results

    def get_history(self, symbol: str, exchange: str, interval: str,
                   start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
            interval: Candle interval (1m, 3m, 5m, 10m, 15m, 30m, 1h, D)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume, oi]
        """
        try:
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)
            logger.debug(f"Debug - Symbol: {symbol}, Exchange: {exchange}, Broker Symbol: {br_symbol}, Token: {token}")

            # Validate token
            if not token or token == 'None' or str(token).strip() == '':
                raise Exception(f"Invalid or missing token for symbol '{symbol}' on exchange '{exchange}'. Token: {token}")

            # Convert dates to datetime objects
            from_date = pd.to_datetime(start_date)
            to_date = pd.to_datetime(end_date)
            current_date = pd.Timestamp.now().normalize()

            # Check if request is for current day only - use intraday endpoint
            if from_date.date() == to_date.date() == current_date.date():
                logger.debug("Debug - Using intraday endpoint for current day data")
                return self._get_intraday_data(symbol, br_symbol, exchange, interval)

            # Check if end_date is today and start_date is in the past
            # Need to fetch historical + intraday and combine
            if to_date.date() == current_date.date() and from_date.date() < current_date.date():
                logger.debug("Debug - Date range includes today - fetching historical + intraday")

                # Fetch historical data from start_date to yesterday
                yesterday = current_date - pd.Timedelta(days=1)
                historical_df = self._get_historical_data(
                    symbol, token, exchange, interval,
                    from_date, yesterday
                )

                # Fetch intraday data for today
                try:
                    intraday_df = self._get_intraday_data(symbol, br_symbol, exchange, interval)

                    # Combine historical and intraday data
                    if not historical_df.empty and not intraday_df.empty:
                        combined_df = pd.concat([historical_df, intraday_df], ignore_index=True)
                        combined_df = combined_df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)
                        return combined_df
                    elif not historical_df.empty:
                        return historical_df
                    elif not intraday_df.empty:
                        return intraday_df
                    else:
                        return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])
                except Exception as intraday_error:
                    logger.warning(f"Debug - Failed to fetch intraday data: {str(intraday_error)}")
                    # Return historical data only if intraday fails
                    return historical_df

            # For historical data only (past dates), use historical endpoint
            return self._get_historical_data(symbol, token, exchange, interval, from_date, to_date)

        except Exception as e:
            logger.error(f"Debug - Error: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")

    def _get_historical_data(self, symbol: str, token: str, exchange: str, interval: str,
                             from_date: pd.Timestamp, to_date: pd.Timestamp) -> pd.DataFrame:
        """
        Helper method to fetch historical data from mstock historical endpoint
        Args:
            symbol: Trading symbol
            token: Symbol token
            exchange: Exchange
            interval: Candle interval
            from_date: Start datetime
            to_date: End datetime
        Returns:
            pd.DataFrame: Historical data
        """
        try:
            # Map exchange
            mapped_exchange = self.exchange_map.get(exchange, exchange)

            # Check for unsupported timeframes
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(f"Timeframe '{interval}' is not supported by mstock. Supported timeframes are: {', '.join(supported)}")

            # Ensure from_date and to_date have proper time components
            # Set start time to 00:00 to capture all trading sessions
            if from_date.hour == 0 and from_date.minute == 0:
                from_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)

            # Set end time to 23:59 to capture all sessions for past dates
            if to_date.hour == 0 and to_date.minute == 0:
                to_date = to_date.replace(hour=23, minute=59, second=0, microsecond=0)

            # Initialize empty list to store DataFrames
            dfs = []

            # Set chunk size based on mstock's 1000 candle limit
            # Calculated conservatively to stay under 1000 candle limit per request
            # Based on typical trading session (~375 minutes/day for regular sessions)
            interval_limits = {
                '1m': 2,      # Conservative: ~2 days to stay under 1000 candles
                '3m': 8,      # ~8 days to stay under 1000 candles
                '5m': 13,     # ~13 days to stay under 1000 candles
                '10m': 26,    # ~26 days to stay under 1000 candles
                '15m': 40,    # ~40 days to stay under 1000 candles
                '30m': 76,    # ~76 days to stay under 1000 candles
                '1h': 166,    # ~166 days to stay under 1000 candles
                'D': 1000     # 1000 days for daily candles
            }

            chunk_days = interval_limits.get(interval)
            if not chunk_days:
                supported = list(interval_limits.keys())
                raise Exception(f"Interval '{interval}' not supported. Supported intervals: {', '.join(supported)}")

            # Process data in chunks
            current_start = from_date
            while current_start <= to_date:
                # Calculate chunk end date
                current_end = min(current_start + timedelta(days=chunk_days-1), to_date)

                # Prepare payload for historical data API
                payload = {
                    "exchange": mapped_exchange,
                    "symboltoken": token,
                    "interval": self.timeframe_map[interval],
                    "fromdate": current_start.strftime('%Y-%m-%d %H:%M'),
                    "todate": current_end.strftime('%Y-%m-%d %H:%M')
                }
                logger.debug(f"Debug - Fetching chunk from {current_start} to {current_end}")
                logger.debug(f"Debug - API Payload: {payload}")

                try:
                    response = get_api_response("/instruments/historical",
                                              self.auth_token,
                                              "GET",
                                              payload)
                    logger.info(f"Debug - API Response Status: {response.get('status')}")

                    # Check if response is empty or invalid
                    if not response:
                        logger.debug(f"Debug - Empty response for chunk {current_start} to {current_end}")
                        current_start = current_end + timedelta(days=1)
                        continue

                    if not response.get('status'):
                        logger.info(f"Debug - Error response: {response.get('message', 'Unknown error')}")
                        current_start = current_end + timedelta(days=1)
                        continue

                except Exception as chunk_error:
                    logger.error(f"Debug - Error fetching chunk {current_start} to {current_end}: {str(chunk_error)}")
                    current_start = current_end + timedelta(days=1)
                    continue

                # Extract candle data from response
                candles = response.get('data', {}).get('candles', [])
                if candles:
                    # Convert candles array to DataFrame
                    # Format: [timestamp, open, high, low, close, volume]
                    chunk_df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    dfs.append(chunk_df)
                    logger.debug(f"Debug - Received {len(candles)} candles for chunk")
                else:
                    logger.debug("Debug - No data received for chunk")

                # Move to next chunk
                current_start = current_end + timedelta(days=1)

            # If no data was found, return empty DataFrame
            if not dfs:
                logger.debug("Debug - No data received from API")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])

            # Combine all chunks
            df = pd.concat(dfs, ignore_index=True)

            # Parse timestamp from API response
            # mstock returns timestamps like "2024-01-01T09:15:00+05"
            df['timestamp'] = pd.to_datetime(df['timestamp'])

            # Debug: log first timestamp to see format
            if len(df) > 0:
                logger.debug(f"Debug - First timestamp from API: {df['timestamp'].iloc[0]}")
                logger.debug(f"Debug - Timestamp timezone: {df['timestamp'].dt.tz}")

            # Handle timezone conversion based on whether timestamps are tz-aware
            if df['timestamp'].dt.tz is not None:
                # Timestamps have timezone (e.g., +05:00)
                # Convert to UTC first for correct epoch calculation
                df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
                # Remove timezone info
                df['timestamp'] = df['timestamp'].dt.tz_localize(None)
            else:
                # Timestamps are tz-naive, treat as IST and convert to UTC
                df['timestamp'] = df['timestamp'].dt.tz_localize('Asia/Kolkata')
                df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
                df['timestamp'] = df['timestamp'].dt.tz_localize(None)

            # For daily timeframe, normalize to midnight (00:00:00)
            # This ensures timestamps display as dates without time
            if interval == 'D':
                df['timestamp'] = df['timestamp'].dt.normalize()

            # Convert to Unix epoch (seconds since 1970-01-01 00:00:00 UTC)
            df['timestamp'] = df['timestamp'].astype('int64') // 10**9

            # Ensure numeric columns
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric)

            # Sort by timestamp and remove duplicates
            df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)

            # Add OI column (0 for now, can be enhanced later for F&O)
            df['oi'] = 0

            # Reorder columns to match OpenAlgo format
            df = df[['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi']]

            return df

        except Exception as e:
            logger.error(f"Debug - Error in _get_historical_data: {str(e)}")
            raise

    def _get_intraday_data(self, symbol: str, br_symbol: str, exchange: str, interval: str) -> pd.DataFrame:
        """
        Get intraday data for current day using mstock intraday endpoint
        Args:
            symbol: Trading symbol (OpenAlgo format)
            br_symbol: Broker symbol
            exchange: Exchange
            interval: Candle interval
        Returns:
            pd.DataFrame: Intraday data
        """
        try:
            # Get token for the symbol
            token = get_token(symbol, exchange)
            logger.debug(f"Debug - Intraday: Symbol: {symbol}, Exchange: {exchange}, Token: {token}")

            # Validate token
            if not token or token == 'None' or str(token).strip() == '':
                raise Exception(f"Invalid or missing token for symbol '{symbol}' on exchange '{exchange}'. Token: {token}")

            # Map exchange to numeric code for intraday API
            exchange_code = self.intraday_exchange_map.get(exchange)
            if not exchange_code:
                raise Exception(f"Exchange '{exchange}' not supported for intraday data")

            # Map interval for intraday API
            intraday_interval = self.intraday_interval_map.get(interval)
            if not intraday_interval:
                raise Exception(f"Interval '{interval}' not supported for intraday data")

            # Prepare payload for intraday API
            # API requires symboltoken (not symbolname)
            payload = {
                "exchange": exchange_code,
                "symboltoken": token,
                "interval": intraday_interval
            }

            logger.debug(f"Debug - Intraday API Payload: {payload}")
            logger.debug(f"Debug - Symbol: {symbol}, Broker Symbol: {br_symbol}, Exchange: {exchange}")

            # Call intraday API using typeb endpoint
            api_key = os.getenv('BROKER_API_SECRET')
            client = get_httpx_client()

            headers = {
                'X-Mirae-Version': '1',
                'Authorization': f'Bearer {self.auth_token}',
                'X-PrivateKey': api_key,
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }

            url = "https://api.mstock.trade/openapi/typeb/instruments/intraday"

            response = client.post(url, headers=headers, json=payload)
            logger.debug(f"Debug - Intraday API Response Status: {response.status_code}")

            if response.status_code != 200:
                logger.error(f"Debug - Intraday API Error Response: {response.text}")

            response.raise_for_status()
            data = response.json()

            if not data.get('status'):
                raise Exception(f"Error from mstock intraday API: {data.get('message', 'Unknown error')}")

            # Extract candle data
            candles = data.get('data', {}).get('candles', [])
            if not candles:
                logger.debug("Debug - No intraday data received")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])

            # Convert candles to DataFrame
            # Format: [timestamp, open, high, low, close, volume]
            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            logger.debug(f"Debug - Received {len(candles)} intraday candles")

            # Parse timestamp (format: "2025-04-04 15:27")
            df['timestamp'] = pd.to_datetime(df['timestamp'])

            # Localize to IST and convert to UTC for epoch
            df['timestamp'] = df['timestamp'].dt.tz_localize('Asia/Kolkata')
            df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
            df['timestamp'] = df['timestamp'].dt.tz_localize(None)

            # Convert to Unix epoch
            df['timestamp'] = df['timestamp'].astype('int64') // 10**9

            # Ensure numeric columns
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric)

            # Sort by timestamp and remove duplicates
            df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)

            # Add OI column
            df['oi'] = 0

            # Reorder columns to match OpenAlgo format
            df = df[['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi']]

            return df

        except Exception as e:
            logger.error(f"Debug - Error fetching intraday data: {str(e)}")
            raise Exception(f"Error fetching intraday data: {str(e)}")

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol using WebSocket
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
        Returns:
            dict: Market depth data with bids, asks and other details
        """
        try:
            # Get token and exchange type
            token = get_token(symbol, exchange)
            exchange_type = self.ws_exchange_map.get(exchange)

            if not exchange_type:
                raise Exception(f"Exchange '{exchange}' not supported for depth")

            logger.debug(f"Fetching depth for {symbol} (token: {token}, exchange: {exchange_type})")

            # Fetch quote using WebSocket (mode 3 = Snap Quote for full data including depth)
            quote_data = self.websocket.fetch_quote(token, exchange_type, mode=3)

            if not quote_data:
                raise Exception("Failed to fetch depth data from WebSocket")

            # Format bids and asks - ensure exactly 5 entries each
            bids = []
            asks = []

            # Process top 5 bids
            for i in range(5):
                if i < len(quote_data['bids']):
                    bid = quote_data['bids'][i]
                    bids.append({
                        'price': bid.get('price', 0),
                        'quantity': bid.get('quantity', 0)
                    })
                else:
                    bids.append({'price': 0, 'quantity': 0})

            # Process top 5 asks
            for i in range(5):
                if i < len(quote_data['asks']):
                    ask = quote_data['asks'][i]
                    asks.append({
                        'price': ask.get('price', 0),
                        'quantity': ask.get('quantity', 0)
                    })
                else:
                    asks.append({'price': 0, 'quantity': 0})

            # Return depth data in OpenAlgo standard format
            return {
                'bids': bids,
                'asks': asks,
                'high': quote_data.get('high', 0),
                'low': quote_data.get('low', 0),
                'ltp': quote_data.get('ltp', 0),
                'ltq': quote_data.get('last_traded_qty', 0),
                'open': quote_data.get('open', 0),
                'prev_close': quote_data.get('close', 0),
                'volume': quote_data.get('volume', 0),
                'oi': quote_data.get('oi', 0),
                'totalbuyqty': int(quote_data.get('total_buy_qty', 0)),
                'totalsellqty': int(quote_data.get('total_sell_qty', 0))
            }

        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")
