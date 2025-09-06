import json
import os
import httpx
from utils.httpx_client import get_httpx_client
from database.token_db import get_token, get_br_symbol, get_oa_symbol
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import numpy as np
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="GET", payload=''):
    """Common function to make API calls to Upstox v3 using httpx with connection pooling"""
    AUTH_TOKEN = auth
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'Authorization': f'Bearer {AUTH_TOKEN}',
        'Accept': 'application/json'
    }
    
    # Use v3 API base URL
    url = f"https://api.upstox.com/v3{endpoint}"
    logger.debug(f"Making {method} request to Upstox v3 API: {url}")
    
    if method == "GET":
        response = client.get(url, headers=headers)
    elif method == "POST":
        response = client.post(url, headers=headers, content=payload)
    elif method == "PUT":
        response = client.put(url, headers=headers, content=payload)
    elif method == "DELETE":
        response = client.delete(url, headers=headers)
    
    # Add status attribute for compatibility with existing code that expects http.client response
    response.status = response.status_code
    
    return response.json()

class BrokerData:
    def __init__(self, auth_token):
        """Initialize with auth token"""
        self.auth_token = auth_token
        
        # Map standard intervals to Upstox v3 intervals
        # V3 supports custom intervals with unit and interval parameters
        self.timeframe_map = {
            # Minutes - v3 supports 1-300 minutes
            '1m': {'unit': 'minutes', 'interval': '1'},
            '2m': {'unit': 'minutes', 'interval': '2'},
            '3m': {'unit': 'minutes', 'interval': '3'},
            '5m': {'unit': 'minutes', 'interval': '5'},
            '10m': {'unit': 'minutes', 'interval': '10'},
            '15m': {'unit': 'minutes', 'interval': '15'},
            '30m': {'unit': 'minutes', 'interval': '30'},
            '60m': {'unit': 'minutes', 'interval': '60'},
            # Hours - v3 supports 1-5 hours
            '1h': {'unit': 'hours', 'interval': '1'},
            '2h': {'unit': 'hours', 'interval': '2'},
            '3h': {'unit': 'hours', 'interval': '3'},
            '4h': {'unit': 'hours', 'interval': '4'},
            # Days/Weeks/Months - v3 supports interval 1 only
            'D': {'unit': 'days', 'interval': '1'},
            'W': {'unit': 'weeks', 'interval': '1'},
            'M': {'unit': 'months', 'interval': '1'}
        }

    def _get_instrument_key(self, symbol: str, exchange: str) -> str:
        """Get the correct instrument key for a symbol"""
        try:
            # Get token from database - this already includes the exchange prefix
            token = get_token(symbol, exchange)
            if not token:
                raise ValueError(f"No token found for {symbol} on {exchange}")
            
            logger.debug(f"Using instrument key: {token}")
            return token
            
        except Exception as e:
            logger.exception(f"Error getting instrument key for {symbol} on {exchange}")
            raise

    def _is_trading_day(self, date):
        """Check if given date is a trading day"""
        # Basic check for weekends
        if date.weekday() >= 5:  # 5 is Saturday, 6 is Sunday
            return False
        return True

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Quote data with standard fields
        """
        try:
            # Get the correct instrument key
            instrument_key = self._get_instrument_key(symbol, exchange)
            
            # URL encode the instrument key
            encoded_symbol = urllib.parse.quote(instrument_key)
            
            # Use v3 OHLC endpoint
            url = f"/market-quote/ohlc?instrument_key={encoded_symbol}&interval=1d"
            response = get_api_response(url, self.auth_token)
            
            if response.get('status') != 'success':
                error_msg = response.get('message', 'Unknown error')
                if 'errors' in response and response['errors']:
                    error = response['errors'][0]
                    error_msg = error.get('message', error_msg)
                    error_code = error.get('errorCode', 'NO_CODE')
                else:
                    error_code = response.get('code', 'NO_CODE')
                full_error_msg = f"API Error - Code: {error_code}, Message: {error_msg}"
                logger.exception(f"Failed to get quotes for {instrument_key}: {full_error_msg} | Response: {response}")
                raise Exception(full_error_msg)
            
            # Get quote data for the symbol
            quote_data = response.get('data', {})
            if not quote_data:
                raise Exception(f"No data received for instrument key: {instrument_key}")
            
            # Find the quote data - v3 OHLC uses the original instrument key format
            quote = None
            for key, value in quote_data.items():
                if value.get('instrument_token') == instrument_key:
                    quote = value
                    break
                    
            if not quote:
                raise Exception(f"No quote data found for instrument key: {instrument_key}")
            
            # Extract OHLC data from v3 response
            live_ohlc = quote.get('live_ohlc', {})
            prev_ohlc = quote.get('prev_ohlc', {})
            
            # Handle None values
            if live_ohlc is None:
                live_ohlc = {}
            if prev_ohlc is None:
                prev_ohlc = {}
            
            # Try to get bid/ask and OI from v2 quotes endpoint as fallback
            bid_price = 0
            ask_price = 0
            oi_value = 0
            try:
                # Use v2 quotes endpoint for bid/ask and OI data
                v2_url = f"/v2/market-quote/quotes?instrument_key={encoded_symbol}"
                client = get_httpx_client()
                headers = {
                    'Authorization': f'Bearer {self.auth_token}',
                    'Accept': 'application/json'
                }
                full_url = f"https://api.upstox.com{v2_url}"
                v2_response = client.get(full_url, headers=headers)
                v2_data = v2_response.json()
                
                if v2_data.get('status') == 'success':
                    v2_quote_data = v2_data.get('data', {})
                    for key, value in v2_quote_data.items():
                        if value.get('instrument_token') == instrument_key:
                            depth = value.get('depth', {})
                            if depth:
                                best_bid = depth.get('buy', [{}])[0] if depth.get('buy') else {}
                                best_ask = depth.get('sell', [{}])[0] if depth.get('sell') else {}
                                bid_price = best_bid.get('price', 0)
                                ask_price = best_ask.get('price', 0)
                            oi_value = value.get('oi', 0)
                            break
            except Exception as e:
                logger.debug(f"Could not get bid/ask/OI from v2 endpoint: {e}")
            
            # Return standard quote data format using live_ohlc for current data
            return {
                'ask': float(ask_price) if ask_price else 0,
                'bid': float(bid_price) if bid_price else 0,
                'high': float(live_ohlc.get('high', 0)) if live_ohlc.get('high') else 0,
                'low': float(live_ohlc.get('low', 0)) if live_ohlc.get('low') else 0,
                'ltp': float(quote.get('last_price', 0)) if quote.get('last_price') else 0,
                'open': float(live_ohlc.get('open', 0)) if live_ohlc.get('open') else 0,
                'prev_close': float(prev_ohlc.get('close', 0)) if prev_ohlc.get('close') else 0,
                'volume': int(live_ohlc.get('volume', 0)) if live_ohlc.get('volume') else 0,
                'oi': int(oi_value) if oi_value else 0
            }
            
        except Exception as e:
            logger.exception(f"Error fetching quotes for {symbol} on {exchange}")
            raise

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol with automatic chunking based on Upstox API V3 limits
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Time interval (e.g., 1m, 5m, 15m, 1h, 1d)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume, oi]
        """
        try:
            # Get the correct instrument key
            instrument_key = self._get_instrument_key(symbol, exchange)
            logger.debug(f"Using instrument key: {instrument_key}")
            
            # Map standard interval to Upstox v3 format
            upstox_config = self.timeframe_map.get(interval)
            if not upstox_config:
                raise Exception(f"Invalid interval: {interval}")
            logger.debug(f"Using v3 config: {upstox_config}")
            
            # Convert dates to datetime objects
            from_date = pd.to_datetime(start_date)
            to_date = pd.to_datetime(end_date)
            
            # Get unit and interval for v3 API
            unit = upstox_config['unit']
            interval_value = int(upstox_config['interval'])
            
            # Set chunk size based on Upstox API V3 limits
            chunk_limits = {
                # Minutes 1-15: 1 month max
                ('minutes', 1): 30,   # 1m
                ('minutes', 2): 30,   # 2m  
                ('minutes', 3): 30,   # 3m
                ('minutes', 5): 30,   # 5m
                ('minutes', 10): 30,  # 10m
                ('minutes', 15): 30,  # 15m
                # Minutes >15: 1 quarter max
                ('minutes', 30): 90,  # 30m
                ('minutes', 60): 90,  # 60m
                # Hours: 1 quarter max
                ('hours', 1): 90,     # 1h
                ('hours', 2): 90,     # 2h
                ('hours', 3): 90,     # 3h
                ('hours', 4): 90,     # 4h
                # Days: 1 decade max
                ('days', 1): 3650,    # D (10 years)
                # Weeks/Months: No limit (use large chunk)
                ('weeks', 1): 7300,   # W (20 years)
                ('months', 1): 7300   # M (20 years)
            }
            
            chunk_days = chunk_limits.get((unit, interval_value))
            if not chunk_days:
                # Default to conservative 30 days for unknown intervals
                chunk_days = 30
                logger.warning(f"Unknown interval {unit}/{interval_value}, using default {chunk_days} days")
            
            logger.debug(f"Using chunk size: {chunk_days} days for {unit}/{interval_value}")
            
            # Initialize list to store DataFrames
            dfs = []
            
            # Process data in chunks
            current_start = from_date
            chunk_count = 0
            successful_chunks = 0
            
            while current_start <= to_date:
                chunk_count += 1
                # Calculate chunk end date
                current_end = min(current_start + timedelta(days=chunk_days-1), to_date)
                
                logger.debug(f"Processing chunk {chunk_count}: {current_start.date()} to {current_end.date()}")
                
                try:
                    chunk_df = self._fetch_chunk_data(instrument_key, unit, interval_value, 
                                                    current_start, current_end, symbol, exchange, interval)
                    
                    if not chunk_df.empty:
                        dfs.append(chunk_df)
                        successful_chunks += 1
                        logger.debug(f"Chunk {chunk_count}: Retrieved {len(chunk_df)} candles")
                    else:
                        logger.debug(f"Chunk {chunk_count}: No data received")
                        
                except Exception as chunk_error:
                    logger.error(f"Chunk {chunk_count} failed: {str(chunk_error)}")
                    # Continue with next chunk instead of failing completely
                
                # Move to next chunk
                current_start = current_end + timedelta(days=1)
            
            logger.info(f"Chunking complete: {successful_chunks}/{chunk_count} chunks successful")
            
            # If no data was retrieved, return empty DataFrame
            if not dfs:
                logger.debug("No data retrieved from any chunk")
                return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])
            
            # Combine all chunks
            df = pd.concat(dfs, ignore_index=True)
            
            # Remove duplicates and sort by timestamp
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            logger.info(f"Final result: {len(df)} total candles after deduplication")
            
            return df
            
        except Exception as e:
            logger.exception(f"Error fetching historical data for {symbol} on {exchange}")
            raise

    def _fetch_chunk_data(self, instrument_key: str, unit: str, interval_value: int, 
                         start_date: datetime, end_date: datetime, symbol: str, exchange: str, interval: str) -> pd.DataFrame:
        """
        Fetch historical data for a single chunk
        Args:
            instrument_key: Upstox instrument key
            unit: Time unit (minutes, hours, days, weeks, months)
            interval_value: Interval value
            start_date: Chunk start date
            end_date: Chunk end date
            symbol: Trading symbol (for fallback)
            exchange: Exchange (for fallback)
            interval: Original interval string (for fallback)
        Returns:
            pd.DataFrame: Chunk data
        """
        try:
            # URL encode the instrument key
            encoded_symbol = urllib.parse.quote(instrument_key)
            
            # Format dates for v3 API
            from_date = start_date.strftime('%Y-%m-%d')
            to_date = end_date.strftime('%Y-%m-%d')
            
            current_date = datetime.now()
            all_candles = []
            
            # Try intraday endpoint first for current day data
            if unit in ['minutes', 'hours'] and end_date.date() == current_date.date():
                logger.debug("Trying v3 intraday endpoint for current day...")
                intraday_url = f"/historical-candle/intraday/{encoded_symbol}/{unit}/{interval_value}"
                
                try:
                    intraday_response = get_api_response(intraday_url, self.auth_token)
                    logger.debug(f"Intraday response status: {intraday_response.get('status')}")
                    
                    if intraday_response.get('status') == 'success':
                        intraday_candles = intraday_response.get('data', {}).get('candles', [])
                        logger.info(f"Got {len(intraday_candles)} candles from intraday endpoint")
                        
                        # Debug: Log sample raw candle data immediately
                        if intraday_candles:
                            logger.info(f"Sample intraday candle: {intraday_candles[0]}")
                        
                        # Filter candles to chunk date range
                        filtered_candles = self._filter_candles_by_date(intraday_candles, start_date, end_date)
                        all_candles.extend(filtered_candles)
                        logger.info(f"Added {len(filtered_candles)} filtered candles")
                    else:
                        logger.debug(f"Intraday endpoint returned error: {intraday_response}")
                        
                except Exception as e:
                    logger.debug(f"Intraday endpoint failed: {e}")
                    logger.exception("Intraday endpoint exception details:")
            
            # Try historical endpoint for all other cases or if intraday failed
            if not all_candles or start_date.date() < current_date.date():
                logger.debug("Trying v3 historical endpoint...")
                
                # Historical endpoint URL format: /historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}
                historical_url = f"/historical-candle/{encoded_symbol}/{unit}/{interval_value}/{to_date}/{from_date}"
                
                try:
                    historical_response = get_api_response(historical_url, self.auth_token)
                    logger.debug(f"Historical response status: {historical_response.get('status')}")
                    
                    if historical_response.get('status') == 'success':
                        historical_candles = historical_response.get('data', {}).get('candles', [])
                        logger.info(f"Got {len(historical_candles)} candles from historical endpoint")
                        
                        # Debug: Log sample raw candle data immediately
                        if historical_candles:
                            logger.info(f"Sample historical candle: {historical_candles[0]}")
                        
                        all_candles.extend(historical_candles)
                        logger.info(f"Total candles after historical: {len(all_candles)}")
                    else:
                        logger.debug(f"Historical endpoint returned error: {historical_response}")
                        
                except Exception as e:
                    logger.debug(f"Historical endpoint failed: {e}")
                    logger.exception("Historical endpoint exception details:")
            
            # Handle special case for today's daily data - use intraday API for current day
            logger.info(f"Checking daily logic: unit={unit}, interval_value={interval_value}, original_interval={interval}")
            if unit == 'days' and interval == 'D':
                today = datetime.now().date()
                logger.info(f"Daily timeframe check: today={today}, start_date={start_date.date()}, end_date={end_date.date()}")
                if start_date.date() <= today <= end_date.date():
                    logger.info("Today is within date range, checking if today's data exists")
                    # Check if today's data is already in historical data
                    today_found = False
                    if all_candles:
                        for candle in all_candles:
                            try:
                                candle_date = pd.to_datetime(candle[0], unit='ms' if isinstance(candle[0], (int, float)) else None).date()
                                logger.debug(f"Checking candle date: {candle_date}")
                                if candle_date == today:
                                    today_found = True
                                    logger.debug("Today's data found in historical candles")
                                    break
                            except Exception as e:
                                logger.debug(f"Error parsing candle date: {e}")
                                continue
                    
                    # If today's data not found, get it from quotes API
                    if not today_found:
                        logger.info("Today's data not found, fetching from quotes API")
                        try:
                            quotes = self.get_quotes(symbol, exchange)
                            logger.info(f"Quotes API response: {quotes}")
                            
                            if quotes and quotes.get('ltp', 0) > 0:
                                # Create today's daily candle with midnight timestamp
                                today_ts = int((datetime.combine(today, datetime.min.time()) + timedelta(hours=5, minutes=30)).timestamp())
                                today_candle = [
                                    today_ts * 1000,  # Upstox uses milliseconds
                                    quotes.get('open', quotes.get('ltp', 0)),
                                    quotes.get('high', quotes.get('ltp', 0)),
                                    quotes.get('low', quotes.get('ltp', 0)),
                                    quotes.get('ltp', 0),
                                    quotes.get('volume', 0),
                                    quotes.get('oi', 0)
                                ]
                                all_candles.append(today_candle)
                                logger.info("Added today's daily candle from quotes API")
                            else:
                                logger.info("No valid quotes data available for today")
                                
                        except Exception as e:
                            logger.info(f"Could not get today's data from quotes API: {e}")
                            logger.exception("Quotes API exception details:")
            
            # Return empty DataFrame if no data
            if not all_candles:
                logger.debug("No candles data available for chunk")
                return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])
            
            # Debug: Log sample candle data to understand structure
            logger.info(f"Sample candle data (first 2): {all_candles[:2]}")
            logger.info(f"Total candles for processing: {len(all_candles)}")
            
            # Convert to DataFrame
            df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
            
            # Debug: Check timestamp column before conversion
            logger.info(f"Timestamp column types before conversion: {df['timestamp'].dtype}")
            logger.info(f"Sample timestamp values: {df['timestamp'].head(10).tolist()}")
            logger.info(f"Unique timestamp types: {df['timestamp'].apply(type).unique()}")
            
            # Convert timestamp from ISO 8601 string to Unix timestamp (seconds since epoch)
            # Upstox returns timestamps like '2024-12-09T15:29:00+05:30'
            try:
                # Convert to datetime first - handle mixed formats (strings and floats)
                def safe_to_datetime(ts):
                    try:
                        if isinstance(ts, str):
                            return pd.to_datetime(ts)
                        elif isinstance(ts, pd.Timestamp):
                            return ts
                        else:
                            # Numeric timestamp in milliseconds, convert to datetime
                            return pd.to_datetime(ts, unit='ms')
                    except Exception as e:
                        logger.warning(f"Error converting timestamp {ts}: {e}")
                        return pd.NaT
                
                df['timestamp'] = df['timestamp'].apply(safe_to_datetime)
                
                # Remove any NaT values
                df = df.dropna(subset=['timestamp'])
                
                # For daily timeframe, normalize to date only (remove time component)
                # This matches Angel's behavior for daily data
                if interval == 'D':
                    # Convert to date only (YYYY-MM-DD format) then back to datetime at midnight
                    # Use apply to handle mixed types safely
                    df['timestamp'] = df['timestamp'].apply(lambda x: x.date() if hasattr(x, 'date') else pd.to_datetime(x).date())
                    df['timestamp'] = pd.to_datetime(df['timestamp'])
                
                # Convert to Unix timestamp (seconds since epoch) - following Angel's pattern
                # Use apply to safely handle any remaining mixed types
                df['timestamp'] = df['timestamp'].apply(lambda x: int(x.timestamp()) if hasattr(x, 'timestamp') else int(pd.to_datetime(x).timestamp()))
                logger.info(f"Successfully converted {len(df)} timestamps to Unix timestamps")
            except Exception as e:
                logger.error(f"Failed to convert timestamps: {e}")
                # Fallback: try to handle mixed formats using the same safe approach
                def convert_timestamp(ts):
                    try:
                        if isinstance(ts, str):
                            # ISO 8601 string format
                            dt = pd.to_datetime(ts)
                        elif isinstance(ts, pd.Timestamp):
                            # pandas Timestamp object - already converted
                            dt = ts
                        else:
                            # Numeric format (milliseconds)
                            dt = pd.to_datetime(ts, unit='ms')
                        
                        # For daily, normalize to date only
                        if interval == 'D':
                            dt = pd.to_datetime(dt.date())
                        
                        return int(dt.timestamp())
                    except Exception as e:
                        logger.warning(f"Failed to convert timestamp {ts} ({type(ts)}): {e}")
                        return None
                
                df['timestamp'] = df['timestamp'].apply(convert_timestamp)
                
                # Handle NaN values - drop rows with invalid timestamps
                initial_count = len(df)
                df = df.dropna(subset=['timestamp'])
                dropped_count = initial_count - len(df)
                if dropped_count > 0:
                    logger.warning(f"Dropped {dropped_count} rows with invalid timestamps")
                
                df['timestamp'] = df['timestamp'].astype(int)
            
            # Ensure numeric columns
            numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'oi']
            df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric, errors='coerce').fillna(0)
            
            # Reorder columns to match Angel format
            df = df[['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi']]
            
            return df
            
        except Exception as e:
            logger.error(f"Error fetching chunk data: {str(e)}")
            return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])

    def _filter_candles_by_date(self, candles: list, start_date: datetime, end_date: datetime) -> list:
        """
        Filter candles to only include those within the specified date range
        """
        if not candles:
            return []
        
        filtered = []
        start_ts = start_date.timestamp() * 1000  # Convert to milliseconds
        end_ts = (end_date + timedelta(days=1)).timestamp() * 1000  # Include end date
        
        for candle in candles:
            candle_ts = candle[0]  # Timestamp is first element
            
            # Handle different timestamp formats
            if isinstance(candle_ts, str):
                # Convert ISO 8601 string to timestamp (milliseconds)
                try:
                    dt = pd.to_datetime(candle_ts)
                    candle_ts = dt.timestamp() * 1000
                except Exception as e:
                    logger.warning(f"Failed to parse timestamp {candle_ts}: {e}")
                    continue
            elif isinstance(candle_ts, (int, float)):
                # Already numeric, ensure it's in milliseconds
                if candle_ts < 1e12:  # If less than year 2001 in milliseconds, assume seconds
                    candle_ts = candle_ts * 1000
            else:
                logger.warning(f"Unknown timestamp format: {type(candle_ts)} - {candle_ts}")
                continue
                
            if start_ts <= candle_ts < end_ts:
                # Update the candle with the converted timestamp
                candle[0] = candle_ts
                filtered.append(candle)
        
        return filtered

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for a symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data with buy and sell orders
        """
        try:
            # Get the correct instrument key
            instrument_key = self._get_instrument_key(symbol, exchange)
            
            # URL encode the instrument key
            encoded_symbol = urllib.parse.quote(instrument_key)
            
            # Use v2 quotes endpoint for depth data (v3 OHLC doesn't provide depth)
            url = f"/v2/market-quote/quotes?instrument_key={encoded_symbol}"
            # For depth, we still need to use v2 endpoint directly
            client = get_httpx_client()
            headers = {
                'Authorization': f'Bearer {self.auth_token}',
                'Accept': 'application/json'
            }
            full_url = f"https://api.upstox.com{url}"
            response = client.get(full_url, headers=headers)
            response = response.json()
            
            if response.get('status') != 'success':
                error_msg = response.get('message', 'Unknown error')
                if 'errors' in response and response['errors']:
                    error = response['errors'][0]
                    error_msg = error.get('message', error_msg)
                full_error_msg = f"API Error: {error_msg}"
                logger.exception(f"Failed to get market depth for {instrument_key}: {full_error_msg}")
                raise Exception(full_error_msg)
            
            # Get quote data for the symbol
            quote_data = response.get('data', {})
            if not quote_data:
                raise Exception(f"No data received for instrument key: {instrument_key}")
                
            # Find the quote data - Upstox uses exchange:symbol format for the key
            quote = None
            for key, value in quote_data.items():
                if value.get('instrument_token') == instrument_key:
                    quote = value
                    break
                    
            if not quote:
                raise Exception(f"No quote data found for instrument key: {instrument_key}")
            
            # Get depth data from v2 response
            depth = quote.get('depth', {})
            
            # Also try to get enhanced OHLC data from v3 API
            ohlc_data = {}
            try:
                # Use v3 OHLC endpoint for better OHLC data
                v3_url = f"/market-quote/ohlc?instrument_key={encoded_symbol}&interval=1d"
                v3_response = get_api_response(v3_url, self.auth_token)
                
                if v3_response.get('status') == 'success':
                    v3_quote_data = v3_response.get('data', {})
                    for key, value in v3_quote_data.items():
                        if value.get('instrument_token') == instrument_key:
                            live_ohlc = value.get('live_ohlc', {})
                            prev_ohlc = value.get('prev_ohlc', {})
                            
                            # Handle None values
                            if live_ohlc is None:
                                live_ohlc = {}
                            if prev_ohlc is None:
                                prev_ohlc = {}
                            
                            ohlc_data = {
                                'high': live_ohlc.get('high', 0),
                                'low': live_ohlc.get('low', 0),
                                'open': live_ohlc.get('open', 0),
                                'prev_close': prev_ohlc.get('close', 0),
                                'volume': live_ohlc.get('volume', 0),
                                'ltp': value.get('last_price', 0)
                            }
                            break
            except Exception as e:
                logger.debug(f"Could not get v3 OHLC data: {e}")
            
            # Return standard depth data format
            return {
                'asks': [{
                    'price': order.get('price', 0),
                    'quantity': order.get('quantity', 0)
                } for order in depth.get('sell', [])],
                'bids': [{
                    'price': order.get('price', 0),
                    'quantity': order.get('quantity', 0)
                } for order in depth.get('buy', [])],
                'high': ohlc_data.get('high', quote.get('ohlc', {}).get('high', 0)),
                'low': ohlc_data.get('low', quote.get('ohlc', {}).get('low', 0)),
                'ltp': ohlc_data.get('ltp', quote.get('last_price', 0)),
                'ltq': quote.get('last_quantity', 0),
                'oi': quote.get('oi', 0),
                'open': ohlc_data.get('open', quote.get('ohlc', {}).get('open', 0)),
                'prev_close': ohlc_data.get('prev_close', quote.get('ohlc', {}).get('close', 0)),
                'totalbuyqty': quote.get('total_buy_quantity', 0),
                'totalsellqty': quote.get('total_sell_quantity', 0),
                'volume': ohlc_data.get('volume', quote.get('volume', 0))
            }
            
        except Exception as e:
            logger.exception(f"Error fetching market depth for {symbol} on {exchange}")
            raise

    # Alias for get_depth to maintain compatibility
    get_market_depth = get_depth
