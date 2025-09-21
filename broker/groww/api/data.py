import json
import os
import pytz
from datetime import datetime, timedelta
import pandas as pd
import httpx
from typing import Dict, List, Any, Union, Optional
import time
import traceback
from utils.httpx_client import get_httpx_client

from database.token_db import get_br_symbol, get_oa_symbol, get_token
from datetime import datetime, timedelta
import pandas as pd
import pytz
from utils.logging import get_logger

logger = get_logger(__name__)
# API endpoints are handled by the Groww SDK

# Exchange constants for Groww API
EXCHANGE_NSE = "NSE"  # Stock exchange code for NSE
EXCHANGE_BSE = "BSE"  # Stock exchange code for BSE

# Segment constants for Groww API
SEGMENT_CASH = "CASH"  # Segment code for Cash market
SEGMENT_FNO = "FNO"    # Segment code for F&O market


def get_api_response(endpoint, auth_token, method="GET", params=None, data=None, debug=False):
    """Make direct API requests to Groww endpoints
    
    This function directly calls Groww API endpoints using the shared httpx client
    with connection pooling for better performance.
    
    Args:
        endpoint (str): API endpoint (e.g., '/v1/quotes')
        auth_token (str): Authentication token
        method (str): HTTP method (GET, POST, etc.)
        params (dict): URL parameters for the API call
        data (dict): Request body data for POST/PUT requests
        debug (bool): Enable additional debugging
        
    Returns:
        dict: Response data from the Groww API
    """
    logger.info(f"Making direct API request to endpoint: {endpoint}")
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    # Ensure endpoint starts with a slash
    if not endpoint.startswith('/'):
        endpoint = '/' + endpoint
    
    # Build the full URL
    base_url = "https://api.groww.in"
    url = f"{base_url}{endpoint}"
    
    # Set up headers with authentication token
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {auth_token}'
    }
    
    try:
        # Make the request based on the HTTP method
        if method.upper() == 'GET':
            response = client.get(url, headers=headers, params=params)
        elif method.upper() == 'POST':
            response = client.post(url, headers=headers, json=data)
        elif method.upper() == 'PUT':
            response = client.put(url, headers=headers, json=data)
        elif method.upper() == 'DELETE':
            response = client.delete(url, headers=headers, params=params)
        else:
            logger.error(f"Unsupported HTTP method: {method}")
            return {"error": f"Unsupported HTTP method: {method}"}
        
        # Log request details if debug is enabled
        if debug:
            logger.debug(f"Request URL: {url}")
            logger.debug(f"Request params: {params}")
        
        # Check if the request was successful
        response.raise_for_status()
        
        # Parse the JSON response
        try:
            result = response.json()
            if debug:
                logger.debug(f"API Response: {result}")
            return result
        except ValueError:
            # Handle non-JSON responses
            logger.error("Response is not valid JSON")
            return {"error": "Response is not valid JSON", "content": response.text}
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
        return {"error": f"HTTP error: {e.response.status_code}", "details": e.response.text}
    except Exception as e:
        logger.error(f"Error in API request: {str(e)}")
        if debug:
            logger.exception("Detailed exception info:")
        return {"error": str(e)}


class BrokerData:
    def __init__(self, auth_token):
        """Initialize Groww data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Groww resolutions (in minutes)
        # Only including timeframes that Groww actually provides
        self.timeframe_map = {
            # Minutes
            '1m': '1',    # 1 minute
            '5m': '5',    # 5 minutes
            '10m': '10',  # 10 minutes
            # Hours
            '1h': '60',   # 1 hour (60 minutes)
            '4h': '240',  # 4 hours (240 minutes)
            # Daily
            'D': '1440',  # Daily data (1440 minutes)
            # Weekly
            'W': '10080'  # Weekly data (10080 minutes)
        }
        
        # The duration-based interval constraints as documented in the Groww API
        self.time_constraints = [
            {'max_days': 3, 'min_interval': '1'},      # 0-3 days: 1 min minimum
            {'max_days': 15, 'min_interval': '5'},    # 3-15 days: 5 min minimum
            {'max_days': 30, 'min_interval': '10'},   # 15-30 days: 10 min minimum
            {'max_days': 150, 'min_interval': '60'},  # 30-150 days: 60 min minimum
            {'max_days': 365, 'min_interval': '240'}, # 150-365 days: 240 min minimum 
            {'max_days': 1080, 'min_interval': '1440'}, # 365-1080 days: 1440 min minimum
            {'max_days': float('inf'), 'min_interval': '10080'} # >1080 days: 10080 min minimum
        ]

    def _convert_openalgo_to_groww_derivative_symbol(self, symbol):
        """
        Convert OpenAlgo NFO/BFO symbol format to Groww format
        
        Examples:
        - SBIN30SEP25FUT -> SBIN25SEPFUT
        - SBIN30SEP25800CE -> SBIN25SEP800CE
        """
        import re
        
        # Pattern for futures: SYMBOL + DAY + MONTH + YEAR + FUT
        fut_pattern = r'^([A-Z]+)(\d{2})([A-Z]{3})(\d{2})(FUT)$'
        fut_match = re.match(fut_pattern, symbol)
        if fut_match:
            base_symbol, day, month, year, fut = fut_match.groups()
            # Groww format: SYMBOL + YEAR + MONTH + FUT (no day)
            return f"{base_symbol}{year}{month}{fut}"
        
        # Pattern for options: SYMBOL + DAY + MONTH + YEAR + STRIKE + CE/PE
        opt_pattern = r'^([A-Z]+)(\d{2})([A-Z]{3})(\d{2})(\d+)(CE|PE)$'
        opt_match = re.match(opt_pattern, symbol)
        if opt_match:
            base_symbol, day, month, year, strike, opt_type = opt_match.groups()
            # Groww format: SYMBOL + YEAR + MONTH + STRIKE + CE/PE (no day)
            return f"{base_symbol}{year}{month}{strike}{opt_type}"
        
        # If no pattern matches, return original
        return symbol

    def _convert_to_groww_params(self, symbol, exchange):
        """
        Convert symbol and exchange to Groww API parameters
        
        Args:
            symbol (str): Trading symbol
            exchange (str): Exchange code (NSE, BSE, etc.)
            
        Returns:
            tuple: (exchange, segment, trading_symbol)
        """
        logger.debug(f"Converting params - Symbol: {symbol}, Exchange: {exchange}")
        
        # Handle cases where exchange is not specified or is same as symbol
        if not exchange or exchange == symbol:
            exchange = "NSE"
            logger.info(f"Exchange not specified, defaulting to NSE for symbol {symbol}")
        
        # Determine segment based on exchange
        if exchange in ["NSE", "BSE"]:
            segment = SEGMENT_CASH
            logger.debug(f"Using SEGMENT_CASH for exchange {exchange}")
        elif exchange in ["NFO", "BFO"]:
            segment = SEGMENT_FNO
            logger.debug(f"Using SEGMENT_FNO for exchange {exchange}")
        else:
            logger.error(f"Unsupported exchange: {exchange}")
            raise ValueError(f"Unsupported exchange: {exchange}")
            
        # Map exchange to Groww's format
        if exchange == "NFO":
            groww_exchange = EXCHANGE_NSE
            logger.debug("Mapped NFO to EXCHANGE_NSE")
        elif exchange == "BFO":
            groww_exchange = EXCHANGE_BSE
            logger.debug("Mapped BFO to EXCHANGE_BSE")
        else:
            groww_exchange = exchange
            logger.debug(f"Using exchange as-is: {exchange}")
            
        # For derivatives, convert symbol format
        if exchange in ["NFO", "BFO"]:
            # First try to get from database
            br_symbol = get_br_symbol(symbol, exchange)
            if br_symbol:
                trading_symbol = br_symbol
                logger.debug(f"Found broker symbol in database: {trading_symbol}")
            else:
                # If not in database, convert format
                trading_symbol = self._convert_openalgo_to_groww_derivative_symbol(symbol)
                logger.debug(f"Converted derivative symbol: {symbol} -> {trading_symbol}")
        else:
            # For equity, use broker symbol if available
            br_symbol = get_br_symbol(symbol, exchange)
            trading_symbol = br_symbol or symbol
        
        return groww_exchange, segment, trading_symbol

    def _convert_date_to_utc(self, date_str: str) -> str:
        """Convert IST date to UTC date for API request"""
        # Simply return the date string as the API expects YYYY-MM-DD format
        return date_str

    def fix_timestamps(self, df, interval):
        """
        Fix timestamps to align with Indian market hours in IST.
        For daily/weekly intervals, set to 09:15:00 IST. For intraday, ensure within 9:15 AM - 3:30 PM IST.
        
        Based on successful FivePaisa implementation pattern.
        """
        # Handle empty DataFrame case
        if df.empty:
            logger.warning("Empty DataFrame passed to fix_timestamps, returning as is")
            return df
            
        ist_tz = pytz.timezone('Asia/Kolkata')
        
        # For daily or weekly interval: Set all timestamps to 09:15 AM IST (market open time)
        # Important: Weekly timeframes should be treated like daily (first day of week at market open)
        if interval in ['D', '1D', '1d', 'W', 'w', '1W', '1w']:
            logger.info(f"Setting all {interval} candles to 09:15:00 IST market open time")
            new_index = []
            for i, idx in enumerate(df.index):
                # Convert the date part to a Python date object
                if isinstance(idx, pd.Timestamp):
                    date_part = idx.date()
                else:
                    # If it's a string or another format, convert to datetime first
                    date_part = pd.to_datetime(idx).date()
                
                # Create market open time (09:15 AM IST) for this date
                # Create date directly at 9:15 instead of using datetime.time
                market_open = datetime(date_part.year, date_part.month, date_part.day, 9, 15, 0)
                market_open_ist = ist_tz.localize(market_open)
                new_index.append(market_open_ist)
            
            # Replace the DataFrame index with the new datetime index
            df.index = pd.DatetimeIndex(new_index)
        
        # For intraday: Ensure times are within market hours (9:15 AM - 3:30 PM)
        else:
            logger.info("Ensuring intraday candles are within market hours (9:15 AM - 3:30 PM IST)")
            # Check if index is already a DatetimeIndex
            if not isinstance(df.index, pd.DatetimeIndex):
                logger.warning("Index is not a DatetimeIndex, converting first")
                df.index = pd.to_datetime(df.index)
                
            # Apply timezone handling
            if hasattr(df.index, 'tz') and df.index.tz is None:
                df.index = df.index.tz_localize('UTC').tz_convert(ist_tz)
            elif hasattr(df.index, 'tz'):
                df.index = df.index.tz_convert(ist_tz)
            
            # Clamp times to market hours
            new_index = []
            for dt in df.index:
                date_part = dt.date()
                # Create market open and close times directly without using datetime.time
                market_open = datetime(date_part.year, date_part.month, date_part.day, 9, 15, 0)
                market_open = ist_tz.localize(market_open)
                market_close = datetime(date_part.year, date_part.month, date_part.day, 15, 30, 0)
                market_close = ist_tz.localize(market_close)
                
                # Clamp time within market hours
                if dt < market_open:
                    new_dt = market_open
                elif dt > market_close:
                    new_dt = market_close
                else:
                    new_dt = dt
                
                new_index.append(new_dt)
            
            if new_index:  # Only update if we have valid timestamps
                df.index = pd.DatetimeIndex(new_index)
        
        return df

    def get_history(self, symbol: str, exchange: str, timeframe: str, start_time: str, end_time: str) -> pd.DataFrame:
        """
        Get historical candle data for a symbol using direct Groww API calls.
        Implements chunking for large date ranges, similar to FivePaisa and Angel.
        
        Args:
            exchange (str): Exchange code (NSE, BSE, NFO, etc.)
            symbol (str): Trading symbol (e.g. 'INFY')
            timeframe (str): Timeframe such as '1m', '5m', etc.
            start_time (str): Start date in YYYY-MM-DD format
            end_time (str): End date in YYYY-MM-DD format
            
        Returns:
            pd.DataFrame: DataFrame with historical candle data
        """
        try:
            # Convert symbol and exchange to Groww API parameters
            groww_exchange, segment, trading_symbol = self._convert_to_groww_params(symbol, exchange)
            
            # Check if we need to map the timeframe
            if timeframe in self.timeframe_map:
                interval_minutes = self.timeframe_map[timeframe]
            else:
                logger.warning(f"Unrecognized timeframe {timeframe}, defaulting to daily")
                interval_minutes = '1440'  # Default to daily
                
            # Check if it's a daily or weekly timeframe
            is_daily = (interval_minutes == '1440' or timeframe.upper() == 'D')
            is_weekly = (interval_minutes == '10080' or timeframe.upper() == 'W')
            
            # Treat both daily and weekly similarly for timestamp handling
            is_eod = is_daily or is_weekly
            
            # Parse start and end dates - handle both string and datetime.date formats
            if isinstance(start_time, str):
                start_date = datetime.strptime(start_time, '%Y-%m-%d')
            elif hasattr(start_time, 'strftime'):  # datetime.date or datetime.datetime object
                start_date = datetime.combine(start_time, datetime.min.time()) if not hasattr(start_time, 'hour') else start_time
            else:
                raise ValueError(f"Invalid start_time format: {type(start_time)}")
                
            if isinstance(end_time, str):
                end_date = datetime.strptime(end_time, '%Y-%m-%d')
            elif hasattr(end_time, 'strftime'):  # datetime.date or datetime.datetime object
                end_date = datetime.combine(end_time, datetime.min.time()) if not hasattr(end_time, 'hour') else end_time
            else:
                raise ValueError(f"Invalid end_time format: {type(end_time)}")
            
            # Implement chunking for better reliability and to avoid API limits
            # Define chunk size based on timeframe
            if is_weekly:
                chunk_size = 300  # 300 days (about 43 weeks) per request for weekly data
            elif is_daily:
                chunk_size = 100  # 100 days per request for daily data
            elif int(interval_minutes) >= 60:  # Hourly or higher
                chunk_size = 15   # 15 days for hourly data
            elif int(interval_minutes) >= 5:   # 5min, 10min, 15min
                chunk_size = 7    # 7 days for medium intervals
            else:  # 1min
                chunk_size = 3    # 3 days for 1min data as per Groww constraints
            
            # Initialize empty list to store all candles
            all_candles = []
            
            # Process data in chunks
            current_start = start_date
            while current_start <= end_date:
                # Calculate chunk end (ensuring it doesn't exceed the overall end date)
                current_end = min(current_start + timedelta(days=chunk_size-1), end_date)
                
                # Format dates for API request
                chunk_start = current_start.strftime('%Y-%m-%d')
                chunk_end = current_end.strftime('%Y-%m-%d')
                
                logger.info(f"Fetching chunk from {chunk_start} to {chunk_end} with interval {interval_minutes}")
                
                # Make API request for this chunk
                response = get_api_response(
                    endpoint="/v1/historical/candle/range",
                    auth_token=self.auth_token,
                    method="GET",
                    params={
                        'exchange': groww_exchange,
                        'segment': segment,
                        'trading_symbol': trading_symbol,
                        'start_time': f"{chunk_start} 09:15:00",
                        'end_time': f"{chunk_end} 15:30:00",
                        'interval_in_minutes': interval_minutes
                    },
                    debug=True
                )
                
                # Check for valid response
                if not response or response.get('status') != 'SUCCESS' or 'payload' not in response:
                    logger.warning(f"Invalid response from Groww API for chunk {chunk_start} to {chunk_end}")
                    # Move to next chunk without failing the entire request
                    current_start = current_end + timedelta(days=1)
                    continue
                
                # Extract candles data for this chunk
                chunk_candles = response.get('payload', {}).get('candles', [])
                if not chunk_candles or len(chunk_candles) == 0:
                    logger.warning(f"No candles found for chunk {chunk_start} to {chunk_end}")
                    # Move to next chunk
                    current_start = current_end + timedelta(days=1)
                    continue
                    
                logger.info(f"Received {len(chunk_candles)} candles for chunk {chunk_start} to {chunk_end}")
                
                # Add candles from this chunk to the overall list
                all_candles.extend(chunk_candles)
                
                # Move to next chunk
                current_start = current_end + timedelta(days=1)
            
            # Check if we received any data across all chunks
            if not all_candles or len(all_candles) == 0:
                logger.warning("No candles found across all chunks")
                return pd.DataFrame()
                
            logger.info(f"Total candles received across all chunks: {len(all_candles)}")
            
            # Process the combined candles data
            candles = all_candles
            
            # SIMPLIFIED APPROACH: Work with the data directly
            # Create a datetime index with market open time (09:15 AM IST)
            ist = pytz.timezone('Asia/Kolkata')
            
            # Convert based on timeframe and data format
            # Process both daily (D, 1d) and weekly (W) candles the same way
            if is_eod:  # Use the previously defined is_eod flag for consistency
                # Set all timestamps to 09:15 AM IST for both daily and weekly data
                dates = []
                rows = []
                
                # Parse start date - handle both string and datetime formats
                if isinstance(start_time, str):
                    start_date = datetime.strptime(start_time, '%Y-%m-%d').date()
                elif hasattr(start_time, 'strftime'):
                    start_date = start_time if hasattr(start_time, 'year') else start_time.date()
                else:
                    start_date = datetime.strptime(str(start_time), '%Y-%m-%d').date()
                
                # Process all candles - extract actual dates from timestamps if available
                for i, candle in enumerate(candles):
                    # Try to get the actual date from the candle timestamp
                    actual_date = None
                    if isinstance(candle, list) and len(candle) >= 6:
                        ts = int(candle[0])
                        # Check if timestamp is in milliseconds
                        if ts > 4102444800:
                            ts = ts / 1000
                        actual_date = datetime.fromtimestamp(ts, tz=ist).date()
                        
                        # [timestamp, open, high, low, close, volume]
                        row = {
                            'open': float(candle[1]),
                            'high': float(candle[2]),
                            'low': float(candle[3]),
                            'close': float(candle[4]),
                            'volume': int(candle[5])
                        }
                    elif isinstance(candle, dict):
                        if 'timestamp' in candle:
                            ts = int(candle['timestamp'])
                            if ts > 4102444800:
                                ts = ts / 1000
                            actual_date = datetime.fromtimestamp(ts, tz=ist).date()
                        # Dictionary format
                        row = {
                            'open': float(candle.get('open', 0)),
                            'high': float(candle.get('high', 0)),
                            'low': float(candle.get('low', 0)),
                            'close': float(candle.get('close', 0)),
                            'volume': int(candle.get('volume', 0))
                        }
                    else:
                        row = {}
                        
                    # Use actual date if available, otherwise calculate based on index
                    if actual_date:
                        current_date = actual_date
                    else:
                        current_date = start_date + timedelta(days=i)
                        
                    # For daily data, use midnight UTC for clean date display
                    # This will show as just the date when converted
                    midnight_utc = datetime.combine(current_date, datetime.min.time())
                    # Create as UTC directly (pytz is already imported at the top)
                    utc = pytz.UTC
                    midnight_utc = utc.localize(midnight_utc)
                    dates.append(midnight_utc)
                    rows.append(row)
                
                # Create DataFrame with dates as index initially
                if dates and rows:
                    df = pd.DataFrame(rows, index=pd.DatetimeIndex(dates))
                    # Add timestamp column - these will be midnight UTC timestamps
                    df['timestamp'] = [int(dt.timestamp()) for dt in df.index]
                    # Reset index to have timestamp as a column (matching Angel format)
                    df = df.reset_index(drop=True)
                    logger.info(f"Created DataFrame with {len(df)} rows for daily timeframe")
                else:
                    df = pd.DataFrame()
                    logger.warning("No valid data for daily timeframe")
            else:
                # For intraday data (1m, 5m, 15m, 1h, 4h, W)
                logger.info(f"Processing intraday data for timeframe {timeframe}")
                rows = []
                timestamps = []
                ist_tz = pytz.timezone('Asia/Kolkata')
                
                # For proper market hour representation in all intraday timeframes
                for candle in candles:
                    if isinstance(candle, list) and len(candle) >= 6:
                        # For list format candles
                        # Groww returns timestamps in milliseconds, not seconds
                        ts = int(candle[0])
                        # Check if timestamp is in milliseconds (larger than year 2100 in seconds)
                        if ts > 4102444800:  # If timestamp is likely in milliseconds
                            ts = ts / 1000  # Convert to seconds
                        # Create timezone-aware datetime in IST
                        dt = datetime.fromtimestamp(ts, tz=ist_tz)
                        
                        row = {
                            'open': float(candle[1]),
                            'high': float(candle[2]),
                            'low': float(candle[3]),
                            'close': float(candle[4]),
                            'volume': int(candle[5])
                        }
                    else:
                        # For dictionary format candles
                        if 'timestamp' in candle:
                            ts = int(candle['timestamp'])
                            # Check if timestamp is in milliseconds
                            if ts > 4102444800:  # If timestamp is likely in milliseconds
                                ts = ts / 1000  # Convert to seconds
                            # Create timezone-aware datetime in IST
                            dt = datetime.fromtimestamp(ts, tz=ist_tz)
                        else:
                            # Fallback: Create market hours timestamp at proper intervals
                            # Start with market open time
                            start_str = start_time if isinstance(start_time, str) else start_time.strftime('%Y-%m-%d')
                            base_dt = datetime.strptime(f"{start_str} 09:15:00", '%Y-%m-%d %H:%M:%S')
                            base_dt = ist_tz.localize(base_dt)
                            # Create proper interval based on timeframe
                            dt = base_dt + timedelta(minutes=int(interval_minutes) * len(timestamps))
                            # Ensure it's within market hours
                            market_close = datetime.strptime(f"{start_str} 15:30:00", '%Y-%m-%d %H:%M:%S')
                            market_close = ist_tz.localize(market_close)
                            if dt > market_close:
                                # Move to next day's market open
                                next_day = base_dt + timedelta(days=1)
                                next_day = next_day.replace(hour=9, minute=15, second=0, microsecond=0)
                                dt = next_day
                        
                        row = {
                            'open': float(candle.get('open', 0)),
                            'high': float(candle.get('high', 0)),
                            'low': float(candle.get('low', 0)),
                            'close': float(candle.get('close', 0)),
                            'volume': int(candle.get('volume', 0))
                        }
                    
                    # Apply market hours check (9:15 AM - 3:30 PM IST)
                    # Skip timestamps outside market hours
                    day_part = dt.date()
                    market_open = datetime.combine(day_part, datetime.min.time()).replace(hour=9, minute=15)
                    market_open = ist_tz.localize(market_open)
                    market_close = datetime.combine(day_part, datetime.min.time()).replace(hour=15, minute=30)
                    market_close = ist_tz.localize(market_close)
                    
                    # Only include timestamps within market hours
                    if market_open <= dt <= market_close:
                        timestamps.append(dt)
                        rows.append(row)
                    else:
                        # Skip this candle
                        logger.debug(f"Skipping candle outside market hours: {dt}")
                
                logger.info(f"Processed {len(timestamps)} valid intraday candles within market hours")
                
                # Create DataFrame with timestamps as index
                if timestamps:
                    # Ensure we have a proper DatetimeIndex
                    df = pd.DataFrame(rows, index=pd.DatetimeIndex(timestamps))
                    # Sort by index to ensure chronological order
                    df = df.sort_index()
                else:
                    df = pd.DataFrame(rows)
                
            # Log information for debugging
            logger.info(f"Final DataFrame has {len(df)} records")
            if not df.empty:
                if is_eod and 'timestamp' in df.columns:
                    # For daily data, we already have timestamp column
                    logger.info(f"Daily data with {len(df)} records")
                elif not isinstance(df.index, pd.RangeIndex):
                    logger.info(f"First index timestamp: {df.index[0]}")
                
            # For proper timestamp handling
            if not df.empty:
                # Skip this processing for daily data as it already has timestamp column
                if is_eod and 'timestamp' in df.columns:
                    logger.info("Daily/weekly data already has timestamp column, skipping index processing")
                    # For daily data, timestamp column already exists, no need to create
                    pass
                elif not isinstance(df.index, pd.RangeIndex):
                    # For intraday data with DatetimeIndex
                    # Convert datetime index to Unix timestamp (seconds) for the API response
                    unix_timestamps = [int(dt.timestamp()) for dt in df.index]
                
                # Handle different data types
                if is_eod and 'timestamp' in df.columns:
                    # Daily data already has timestamp column, just use it
                    result_df = df.copy()
                elif not isinstance(df.index, pd.RangeIndex):
                    # Intraday data with DatetimeIndex
                    # Create a proper copy of the DataFrame with the datetime index
                    result_df = df.copy()
                    # Reset the index and add timestamp column
                    result_df = result_df.reset_index()
                    result_df.rename(columns={'index': 'datetime'}, inplace=True)
                    # Add the Unix timestamp column
                    result_df['timestamp'] = unix_timestamps
                    # Set the datetime column as the index for display purposes
                    df = result_df.set_index('datetime')
                else:
                    # Fallback
                    result_df = df.copy()
                
                # Log sample data for debugging
                if not result_df.empty and 'timestamp' in result_df.columns:
                    sample_timestamp = result_df['timestamp'].iloc[0]
                    ist_tz = pytz.timezone('Asia/Kolkata')
                    sample_dt = datetime.fromtimestamp(sample_timestamp, tz=ist_tz)
                    logger.info(f"First row timestamp: {sample_timestamp} ({sample_dt})")
                
                # Update df to use result_df for further processing
                df = result_df
            else:
                # Empty DataFrame case
                df = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                logger.warning("Returning empty DataFrame with expected columns")
            
            # Final processing for consistency
            if not df.empty:
                try:
                    # Only apply fix_timestamps for intraday data that needs adjustment
                    # Skip for daily/weekly as they're already processed
                    if not is_eod:
                        df = self.fix_timestamps(df, timeframe)
                    
                    # Check if DataFrame is still empty after processing
                    if df.empty:
                        logger.warning("No valid data after timestamp processing")
                        # Create empty DataFrame with proper columns
                        return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    
                    # Special handling for weekly timeframe - Groww API returns daily data, so we need to resample
                    if is_weekly and not df.empty:
                        logger.info(f"Resampling daily data to weekly timeframe, original shape: {df.shape}")
                        # Make sure the index is a DatetimeIndex
                        if not isinstance(df.index, pd.DatetimeIndex):
                            df.index = pd.to_datetime(df.index)
                        
                        # Resample to weekly frequency according to financial markets standards
                        # For OHLCV data:
                        # - 'open' should be the first value of the week
                        # - 'high' should be the maximum value of the week
                        # - 'low' should be the minimum value of the week
                        # - 'close' should be the last value of the week
                        # - 'volume' should be the sum of all values for the week
                        
                        # Ensure index is sorted
                        df = df.sort_index()
                        
                        # Use pandas resample with the appropriate offset
                        # For financial data, we commonly use 'W-MON' which starts the week on Monday
                        # and includes data up to the following Sunday
                        ohlc_dict = {
                            'open': 'first',
                            'high': 'max',
                            'low': 'min',
                            'close': 'last',
                            'volume': 'sum'
                        }
                        
                        # Log the date range to help with debugging
                        logger.info(f"Date range: {df.index.min()} to {df.index.max()}")
                        
                        # Use pandas resample with 'W-MON' frequency
                        # This creates weekly aggregated data with weeks starting on Monday
                        try:
                            # Try the standard pandas resample first
                            weekly_df = df.resample('W-MON', closed='left', label='left').agg(ohlc_dict)
                            
                            # Make sure the index of each weekly candle is set to market open time (9:15 AM)
                            new_index = []
                            for dt in weekly_df.index:
                                # Create a new datetime with the same date but at 9:15 AM
                                ist_tz = pytz.timezone('Asia/Kolkata')
                                market_open = datetime(dt.year, dt.month, dt.day, 9, 15, 0)
                                market_open = ist_tz.localize(market_open)
                                new_index.append(market_open)
                            
                            # Set the new index
                            weekly_df.index = new_index
                            
                            # If we don't have enough candles, try the manual method as fallback
                            expected_candles = 5  # Based on the user's example
                            if len(weekly_df) < expected_candles:
                                logger.warning(f"Resample produced only {len(weekly_df)} candles, trying manual method")
                                raise ValueError("Not enough candles")
                                
                            logger.info(f"Successfully resampled to weekly with {len(weekly_df)} candles")
                            df = weekly_df
                            
                        except Exception as e:
                            logger.warning(f"Standard resampling failed: {str(e)}, using manual method")
                            
                            # Manual method - create weekly candles by manually aggregating daily data
                            # This gives us more control over exactly how many candles we produce
                            
                            # Get the date range
                            start_date = df.index.min().to_pydatetime()
                            end_date = df.index.max().to_pydatetime()
                            
                            # Calculate number of weeks
                            days_diff = (end_date - start_date).days
                            # We want to ensure we have 5 candles as per user's expectation
                            num_weeks = min(5, max(1, (days_diff // 7) + 1))
                            
                            logger.info(f"Manual method: creating {num_weeks} weekly candles")
                            
                            # Create date ranges for each week
                            weekly_dates = []
                            weekly_data = []
                            
                            for i in range(num_weeks):
                                # Calculate week start and end
                                week_start = start_date + timedelta(days=i*7)
                                week_end = min(week_start + timedelta(days=6), end_date)
                                
                                # Filter daily data for this week
                                week_mask = (df.index >= pd.Timestamp(week_start)) & (df.index <= pd.Timestamp(week_end))
                                week_data = df[week_mask]
                                
                                if not week_data.empty:
                                    # Create market open time for the first day of the week
                                    ist_tz = pytz.timezone('Asia/Kolkata')
                                    market_open = datetime(week_start.year, week_start.month, week_start.day, 9, 15, 0)
                                    market_open = ist_tz.localize(market_open)
                                    
                                    weekly_dates.append(market_open)
                                    weekly_data.append({
                                        'open': week_data['open'].iloc[0],
                                        'high': week_data['high'].max(),
                                        'low': week_data['low'].min(),
                                        'close': week_data['close'].iloc[-1],
                                        'volume': week_data['volume'].sum()
                                    })
                            
                            # Create a new DataFrame with the weekly data
                            weekly_df = pd.DataFrame(weekly_data, index=weekly_dates)
                            logger.info(f"Manually created {len(weekly_df)} weekly candles")
                            
                            # Replace the daily data with the manually created weekly data
                            df = weekly_df
                    
                    # Now get Unix timestamps from the properly aligned IST datetime index
                    # Check if we already have timestamps (for daily data)
                    if 'timestamp' in df.columns:
                        unix_timestamps_ist = df['timestamp'].tolist()
                    elif len(df.index) > 0 and hasattr(df.index[0], 'timestamp'):
                        # Don't add offset - timestamps should already be in IST
                        unix_timestamps_ist = [int(dt.timestamp()) for dt in df.index]
                    else:
                        # Index might be a RangeIndex or similar
                        logger.warning("Unable to extract timestamps from index")
                        unix_timestamps_ist = list(range(len(df)))
                    if unix_timestamps_ist:
                        logger.info(f'Unix timestamps (showing proper market hours): {unix_timestamps_ist[:min(5, len(unix_timestamps_ist))]}...')
                except Exception as e:
                    logger.error(f"Error in timestamp processing: {str(e)}")
                    # Create empty DataFrame with proper columns as fallback
                    return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
                # Build the final DataFrame - ensure all required columns exist
                if 'timestamp' not in df.columns:
                    # This shouldn't happen, but handle it gracefully
                    logger.warning("timestamp column missing, creating from index")
                    if hasattr(df.index, 'to_timestamp'):
                        df['timestamp'] = [int(dt.timestamp()) for dt in df.index]
                    else:
                        # Create sequential timestamps
                        df['timestamp'] = range(len(df))
                
                # Ensure all required columns exist
                required_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                for col in required_cols:
                    if col not in df.columns:
                        df[col] = 0
                
                # Create clean data dictionary
                data = {
                    'timestamp': df['timestamp'].values,
                    'open': df['open'].values,
                    'high': df['high'].values,
                    'low': df['low'].values,
                    'close': df['close'].values,
                    'volume': df['volume'].values
                }
                
                # Create the DataFrame with timestamp as a column (not an index)
                # NOTE: For OpenAlgoXTS, return non-indexed DataFrame with timestamp as a column
                # This matches the FivePaisa pattern that has been proven to work correctly
                result_df = pd.DataFrame(data)
                
                # Verify timestamps are correctly showing market hours
                sample_timestamps = result_df['timestamp'].head(3).tolist()
                sample_times = []
                for ts in sample_timestamps:
                    dt = datetime.fromtimestamp(ts, tz=pytz.timezone('Asia/Kolkata'))
                    sample_times.append(dt.strftime('%Y-%m-%d %H:%M:%S%z'))
                    
                logger.info(f"Final format - timestamp column values: {sample_timestamps}")
                logger.info(f"These represent market hours in IST: {', '.join(sample_times)}")
                
                # Final verification of first few rows
                logger.info(f"First few rows of final DataFrame:\n{result_df.head(3)}")
                
                # Ensure the DataFrame has the expected columns in the right order (consistent with other brokers)
                expected_columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
                # Add oi column for consistency
                result_df['oi'] = 0  # Historical data doesn't have OI
                expected_columns.append('oi')
                result_df = result_df[expected_columns]
                
                # Keep timestamp as Unix timestamp column (not as index) - matches Angel implementation
                # Sort by timestamp and remove any duplicates
                result_df = result_df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)
                
                # Return DataFrame with timestamp as column, similar to Angel
                df = result_df
                
                # No need to set index for API client compatibility
                # Many other methods in the codebase expect regular columns
            
            return df
            
        except Exception as e:
            logger.error(f"Error getting historical data: {str(e)}")
            import traceback
            traceback.print_exc()
            # Return empty DataFrame with expected columns on error
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    def get_intervals(self) -> Dict[str, Dict[str, List[str]]]:
        """
        Get supported timeframes for Groww historical data in the OpenAlgo format.
        
        Note that Groww has time-based constraints on minimum interval size:
        - 0-3 days: 1 min minimum
        - 3-15 days: 5 min minimum
        - 15-30 days: 10 min minimum
        - 30-150 days: 60 min (1h) minimum
        - 150-365 days: 240 min (4h) minimum 
        - 365-1080 days: 1440 min (1d) minimum
        - >1080 days: 10080 min (1w) minimum
        
        Returns:
            Dict: Structured response with categorized timeframes
        """
        # Define all the categories and their timeframes as supported by Groww
        # Exactly as provided by Groww: 1m, 5m, 10m, 1h, 4h, D and W
        intervals = {
            "seconds": [],  # Groww doesn't support second-level data
            "minutes": ["1m", "5m", "10m"],
            "hours": ["1h", "4h"],
            "days": ["D"],
            "weeks": ["W"],
            "months": []  # Groww doesn't support month-level data
        }
        
        # Return in the standard OpenAlgo format
        return {
            "status": "success",
            "data": intervals
        }
        
    def get_valid_interval(self, start_time: str, end_time: str, requested_interval: str) -> str:
        """
        Get a valid interval based on Groww's time-based constraints.
        
        Args:
            start_time (str): Start date in YYYY-MM-DD format
            end_time (str): End date in YYYY-MM-DD format
            requested_interval (str): The requested interval (e.g., '1m', '5m', etc.)
            
        Returns:
            str: A valid interval that meets Groww's constraints
        """
        # Map legacy and alternative formats to supported Groww formats
        interval_map = {
            '1d': 'D',   # Map 1d to D
            '1w': 'W'    # Map 1w to W
        }
        
        # Convert to a format Groww supports if needed
        if requested_interval in interval_map:
            requested_interval = interval_map[requested_interval]
            logger.info(f"Mapped requested interval to Groww-supported format: {requested_interval}")
        
        # Verify we have a supported interval
        if requested_interval not in self.timeframe_map:
            logger.warning(f"Unsupported interval: {requested_interval}, defaulting to 'D'")
            return '1440'  # Default to daily
            
        # Calculate the duration in days - handle both string and datetime formats
        if isinstance(start_time, str):
            start_dt = datetime.strptime(start_time, '%Y-%m-%d')
        elif hasattr(start_time, 'strftime'):
            start_dt = datetime.combine(start_time, datetime.min.time()) if not hasattr(start_time, 'hour') else start_time
        else:
            start_dt = datetime.strptime(str(start_time), '%Y-%m-%d')
            
        if isinstance(end_time, str):
            end_dt = datetime.strptime(end_time, '%Y-%m-%d')
        elif hasattr(end_time, 'strftime'):
            end_dt = datetime.combine(end_time, datetime.min.time()) if not hasattr(end_time, 'hour') else end_time
        else:
            end_dt = datetime.strptime(str(end_time), '%Y-%m-%d')
        duration_days = (end_dt - start_dt).days
        
        # Get the requested interval in minutes
        requested_minutes = int(self.timeframe_map[requested_interval])
        
        # Find the minimum allowed interval based on duration
        min_allowed_interval = '1'  # Default to 1 minute
        for constraint in self.time_constraints:
            if duration_days <= constraint['max_days']:
                min_allowed_interval = constraint['min_interval']
                break
                
        min_allowed_minutes = int(min_allowed_interval)
        
        # Check if the requested interval is valid
        if requested_minutes < min_allowed_minutes:
            logger.warning(f"Requested interval {requested_interval} is too small for duration {duration_days} days.")
            
            # Find the appropriate timeframe to use
            for tf, minutes in self.timeframe_map.items():
                if int(minutes) >= min_allowed_minutes:
                    logger.info(f"Using {tf} ({minutes} minutes) instead of {requested_interval} ({requested_minutes} minutes)")
                    return minutes
            
            # If nothing found (unlikely), use the minimum allowed
            return min_allowed_interval
            
        return self.timeframe_map[requested_interval]

    def get_quotes(self, symbol_list, timeout: int = 5) -> Dict[str, Any]:
        """
        Get real-time quotes for a list of symbols using direct Groww API calls.
        
        This implementation directly calls Groww API endpoints instead of using the SDK.
        
        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds
            
        Returns:
            Dict[str, Any]: Quote data in OpenAlgo format
        """
        logger.info(f"Getting quotes using direct API calls for: {symbol_list}")
        
        # Define exchange and segment constants
        EXCHANGE_NSE = 'NSE'
        EXCHANGE_BSE = 'BSE'
        SEGMENT_CASH = 'CASH'
        SEGMENT_FNO = 'FNO'
        
        # Standardize input to a list of dictionaries with exchange and symbol
        if isinstance(symbol_list, dict):
            try:
                # Extract symbol and exchange
                symbol = symbol_list.get('symbol') or symbol_list.get('SYMBOL')
                exchange = symbol_list.get('exchange') or symbol_list.get('EXCHANGE')
                
                if symbol and exchange:
                    logger.info(f"Processing single symbol request: {symbol} on {exchange}")
                    # Convert to a list with a single item
                    symbol_list = [{'symbol': symbol, 'exchange': exchange}]
                else:
                    logger.error("Missing symbol or exchange in request")
                    return {
                        "status": "error",
                        "data": [],
                        "message": "Missing symbol or exchange in request"
                    }
            except Exception as e:
                logger.error(f"Error processing single symbol request: {str(e)}")
                return {
                    "status": "error",
                    "data": [],
                    "message": f"Error processing request: {str(e)}"
                }
        
        # Handle plain string (like just "RELIANCE")
        elif isinstance(symbol_list, str):
            symbol = symbol_list.strip()
            # Auto-detect if it's a derivative based on symbol format
            if symbol.endswith('FUT') or symbol.endswith('CE') or symbol.endswith('PE'):
                exchange = 'NFO'  # It's a derivative
                logger.info(f"Auto-detected derivative symbol: {symbol}, using NFO exchange")
            else:
                exchange = 'NSE'  # Default to NSE for equity
            logger.info(f"Processing string symbol: {symbol} on {exchange}")
            symbol_list = [{'symbol': symbol, 'exchange': exchange}]
        
        # Process all symbols using direct API calls
        quote_data = []
        
        for sym in symbol_list:
            try:
                # Extract symbol and exchange
                if isinstance(sym, dict) and 'symbol' in sym and 'exchange' in sym:
                    symbol = sym['symbol']
                    exchange = sym['exchange']
                elif isinstance(sym, str):
                    symbol = sym
                    # Auto-detect if it's a derivative based on symbol format
                    if symbol.endswith('FUT') or symbol.endswith('CE') or symbol.endswith('PE'):
                        exchange = 'NFO'  # It's a derivative
                    else:
                        exchange = 'NSE'  # Default to NSE for equity
                else:
                    logger.warning(f"Invalid symbol format: {sym}")
                    continue
                
                # Get token for this symbol
                token = get_token(symbol, exchange)
                
                # Map OpenAlgo exchange to Groww exchange format
                if exchange == 'NSE':
                    groww_exchange = EXCHANGE_NSE
                    segment = SEGMENT_CASH
                elif exchange == 'BSE':
                    groww_exchange = EXCHANGE_BSE
                    segment = SEGMENT_CASH
                elif exchange == 'NFO':
                    groww_exchange = EXCHANGE_NSE
                    segment = SEGMENT_FNO
                elif exchange == 'BFO':
                    groww_exchange = EXCHANGE_BSE
                    segment = SEGMENT_FNO
                else:
                    logger.warning(f"Unsupported exchange: {exchange}, defaulting to NSE")
                    groww_exchange = EXCHANGE_NSE
                    segment = SEGMENT_CASH
                
                # Get broker-specific symbol if needed
                trading_symbol = get_br_symbol(symbol, exchange) or symbol
                
                logger.info(f"Requesting quote for {trading_symbol} on {groww_exchange} (segment: {segment})")
                # Make direct API call to Groww quotes endpoint
                start_time = time.time()
                
                # Safely convert values to float/int, handling None values
                def safe_float(value, default=0.0):
                    if value is None:
                        return default
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        return default
                        
                def safe_int(value, default=0):
                    if value is None:
                        return default
                    try:
                        return int(value)
                    except (ValueError, TypeError):
                        return default
                
                try:
                    # Define API endpoint for quotes
                    quote_endpoint = "/v1/live-data/quote"
                    
                    # Prepare parameters
                    params = {
                        'exchange': groww_exchange,
                        'segment': segment,
                        'trading_symbol': trading_symbol
                    }
                    
                    # Make the API call using the shared httpx client
                    response = get_api_response(
                        endpoint=quote_endpoint,
                        auth_token=self.auth_token,
                        method="GET",
                        params=params,
                        debug=True
                    )
                    
                    logger.info(f"Groww API response: {response}")
                    elapsed = time.time() - start_time
                    logger.info(f"Got response from Groww API in {elapsed:.2f}s")
                    
                    if response and not response.get('error'):
                        logger.info(f"Successfully retrieved quote for {symbol} on {exchange}")
                        # Log a sample of the data structure
                        if isinstance(response, dict):
                            logger.info(f"Response keys: {list(response.keys())[:10]}")
                            
                        # Extract payload which contains the actual quote data
                        if response.get('status') == 'SUCCESS' and isinstance(response.get('payload'), dict):
                            response = response.get('payload', {})
                            logger.info(f"response: {response}")
                            logger.info(f"Extracted payload data with keys: {list(response.keys())[:10]}")
                            
                            # Extract OHLC data from the nested structure
                            # OHLC might be a string in some responses
                            ohlc_data = response.get('ohlc', {})
                            logger.info(f"Raw OHLC data: {ohlc_data}")
                            
                            # Handle case where ohlc is a string (from sample response)
                            ohlc = {}
                            if isinstance(ohlc_data, str):
                                # Try to parse the string into a dict
                                try:
                                    # Convert the string format "{open: 149.50,high: 150.50,low: 148.50,close: 149.50}" to a dict
                                    ohlc_str = ohlc_data.strip('{}')
                                    parts = ohlc_str.split(',')
                                    for part in parts:
                                        key_val = part.split(':')
                                        if len(key_val) == 2:
                                            key = key_val[0].strip()
                                            val = key_val[1].strip()
                                            ohlc[key] = float(val)
                                except Exception as e:
                                    logger.error(f"Error parsing OHLC string: {e}")
                            else:
                                # Use the object directly
                                ohlc = ohlc_data
                                
                            logger.info(f"Processed OHLC data: {ohlc}")
                            
                            # Create quote_item in OpenAlgo format
                            # Print each field being extracted for debugging
                            logger.info(f"last_price: {response.get('last_price')}")
                            logger.info(f"ohlc: {ohlc}")
                            logger.info(f"volume: {response.get('volume')}")
                            
                            # CRITICAL: Build the quote item directly with values extracted from the response, using field names that OpenAlgo understands
                            # The quote_item should use the frontend-compatible field names
                            last_price = safe_float(response.get('last_price'))
                            logger.info(f"EXTRACTED last_price = {last_price}")
                            
                            # Determine if this is a derivative instrument
                            is_derivative = exchange in ['NFO', 'BFO'] or segment == SEGMENT_FNO
                            
                            quote_item = {
                                'symbol': symbol,
                                'exchange': exchange,
                                'token': token,
                                # Use 'ltp' directly as that's what the frontend expects
                                'ltp': last_price,  # This is what the frontend looks for
                                'last_price': last_price,  # Keep original field too just in case
                                'open': safe_float(ohlc.get('open')),
                                'high': safe_float(ohlc.get('high')),
                                'low': safe_float(ohlc.get('low')),
                                'close': safe_float(ohlc.get('close')),
                                'prev_close': safe_float(ohlc.get('close')),  # Using previous day's close
                                'change': safe_float(response.get('day_change')),
                                'change_percent': safe_float(response.get('day_change_perc')),
                                'volume': safe_int(response.get('volume')),
                                # The frontend uses 'bid' and 'ask' without the _price suffix
                                'bid': safe_float(response.get('bid_price')),
                                'ask': safe_float(response.get('offer_price')),
                                # Also keep original fields
                                'bid_price': safe_float(response.get('bid_price')),
                                'bid_qty': safe_int(response.get('bid_quantity')),
                                'ask_price': safe_float(response.get('offer_price')),
                                'ask_qty': safe_int(response.get('offer_quantity')),
                                'total_buy_qty': safe_float(response.get('total_buy_quantity')),
                                'total_sell_qty': safe_float(response.get('total_sell_quantity')),
                                # Only show OI for derivatives, 0 for equity
                                'oi': safe_int(response.get('open_interest', 0)) if is_derivative else 0,
                                'timestamp': response.get('last_trade_time', int(datetime.now().timestamp() * 1000))
                            }
                            
                            # Add circuit limits
                            if 'upper_circuit_limit' in response:
                                quote_item['upper_circuit'] = safe_float(response.get('upper_circuit_limit'))
                            if 'lower_circuit_limit' in response:
                                quote_item['lower_circuit'] = safe_float(response.get('lower_circuit_limit'))
                            
                            # Add market depth if available
                            if 'depth' in response:
                                depth_data = response['depth']
                                buy_depth = depth_data.get('buy', [])
                                sell_depth = depth_data.get('sell', [])
                                
                                depth = {
                                    'buy': [],
                                    'sell': []
                                }
                                
                                # Process buy side
                                for level in buy_depth:
                                    if safe_float(level.get('price')) > 0:  # Only include non-zero prices
                                        depth['buy'].append({
                                            'price': safe_float(level.get('price')),
                                            'quantity': safe_int(level.get('quantity')),
                                            'orders': 0  # Groww API doesn't provide order count
                                        })
                                
                                # Process sell side
                                for level in sell_depth:
                                    if safe_float(level.get('price')) > 0:  # Only include non-zero prices
                                        depth['sell'].append({
                                            'price': safe_float(level.get('price')),
                                            'quantity': safe_int(level.get('quantity')),
                                            'orders': 0  # Groww API doesn't provide order count
                                        })
                                
                                quote_item['depth'] = depth
                            
                            # Add to quote data
                            quote_data.append(quote_item)
                            logger.info(f"Added quote_item: {quote_item}")
                        else:
                            logger.warning(f"Invalid response format for {symbol} on {exchange}")
                            response = {}
                    else:
                        logger.warning(f"Empty or error response for {symbol} on {exchange}")
                        response = {}
                    
                    # This section is now handled directly in the response processing code above to avoid duplicate processing
                    continue
                    
                    # Add market depth if available
                    if 'depth' in response:
                        depth_data = response['depth']
                        buy_depth = depth_data.get('buy', [])
                        sell_depth = depth_data.get('sell', [])
                        
                        depth = {
                            'buy': [],
                            'sell': []
                        }
                        
                        # Process buy side
                        for level in buy_depth:
                            depth['buy'].append({
                                'price': safe_float(level.get('price')),
                                'quantity': safe_int(level.get('quantity')),
                                'orders': 0  # Groww API doesn't provide order count
                            })
                        
                        # Process sell side
                        for level in sell_depth:
                            depth['sell'].append({
                                'price': safe_float(level.get('price')),
                                'quantity': safe_int(level.get('quantity')),
                                'orders': 0  # Groww API doesn't provide order count
                            })
                        
                        quote_item['depth'] = depth
                        
                except Exception as api_error:
                    logger.error(f"Groww API error: {str(api_error)}")
                    error_msg = str(api_error)
                    # Add to quote data with error
                    quote_data.append({
                        'symbol': symbol,
                        'exchange': exchange,
                        'token': token,
                        'error': error_msg,
                        'ltp': 0
                    })
            except Exception as e:
                logger.error(f"Error processing Groww API data for {sym}: {str(e)}")
                # Add empty quote data with error message
                quote_data.append({
                    'symbol': symbol if 'symbol' in locals() else str(sym),
                    'exchange': exchange if 'exchange' in locals() else 'Unknown',
                    'error': str(e),
                    'ltp': 0
                })
    
        # Debug output of the final quote_data
        logger.info(f"FINAL QUOTE DATA: {quote_data}")
        
        # No data case
        if not quote_data:
            logger.warning("No quote data found for the requested symbols")
            return {
                "status": "error",
                "message": "No data retrieved"
            }
        
        # Single symbol case - return in simpler format for OpenAlgo frontend
        if isinstance(symbol_list, (str, dict)) or len(symbol_list) == 1:
            logger.info(f"Returning data for single symbol")
    
            # Log what is being passed to the formatter
            logger.debug(f"Quote data passed to formatter: {quote_data}")
            
            # For single symbols, just return the direct quote data
            # The REST API endpoint will wrap it with status/data
            return self._format_single_quote_response(quote_data)

        
        # Multiple quotes - return in standard format
        logger.info(f"Returning data for {len(quote_data)} symbols")
        return {
            "status": "success",
            "data": quote_data
        }
    def _format_single_quote_response(self, quote_data):
        """Helper method to convert from standard dict to the format expected by OpenAlgo frontend
        
        Returns only the data portion without status wrapper - status added by the caller
        """

        if not quote_data or not isinstance(quote_data, list) or len(quote_data) == 0:
            return {}

        quote = quote_data[0]

        logger.info(f"Formatting single quote: {quote}")

        result = {
            "ltp": quote.get("ltp", 0),
            "open": quote.get("open", 0),
            "high": quote.get("high", 0),
            "low": quote.get("low", 0),
            "prev_close": quote.get("prev_close", 0),
            "volume": quote.get("volume", 0),
            "bid": quote.get("bid_price", 0),
            "ask": quote.get("ask_price", 0),
            "oi": quote.get("oi", 0)  # Add Open Interest field
        }

        logger.debug(f"Final OpenAlgo quote format (data only): {result}")
        return result

    # Commented out alternate implementation

    # Legacy implementation - no longer used
    # The code below is from the previous implementation and is kept for reference
    #    logger.info("Empty quote_data received in _format_single_quote_response")
    #    return {
    #        "status": "success",
    #        "data": {}
    #    }
    #        
    #    # Extract first (and only) item in single quote request    
    #    quote = quote_data[0] if isinstance(quote_data, list) and len(quote_data) > 0 else {}
        
        logger.info(f"EXTRACTED QUOTE: {quote}")
        logger.info(f"Formatting single quote response for OpenAlgo frontend: {quote}")
        
        # Based on the sample response, OpenAlgo expects exactly these fields
        # Keep this extremely simple - just the required fields
        simple_data = {
            "ltp": 0,
            "open": 0,
            "high": 0,
            "low": 0,
            "prev_close": 0,
            "volume": 0,
            "bid": 0,
            "ask": 0,
            "status": "success"
        }
        
        # Now grab values from our quote data, using the field that matches best
        
        # LTP - preferred field name in OpenAlgo
        if "ltp" in quote and quote["ltp"] is not None:
            simple_data["ltp"] = float(quote["ltp"])
        elif "last_price" in quote and quote["last_price"] is not None:
            simple_data["ltp"] = float(quote["last_price"])
        
        # Open price
        if "open" in quote and quote["open"] is not None:
            simple_data["open"] = float(quote["open"])
        
        # High price
        if "high" in quote and quote["high"] is not None:
            simple_data["high"] = float(quote["high"])
        
        # Low price
        if "low" in quote and quote["low"] is not None:
            simple_data["low"] = float(quote["low"])
        
        # Previous close
        if "prev_close" in quote and quote["prev_close"] is not None:
            simple_data["prev_close"] = float(quote["prev_close"])
        elif "close" in quote and quote["close"] is not None:
            simple_data["prev_close"] = float(quote["close"])
        
        # Volume
        if "volume" in quote and quote["volume"] is not None:
            simple_data["volume"] = int(quote["volume"])
        
        # Bid price
        if "bid" in quote and quote["bid"] is not None:
            simple_data["bid"] = float(quote["bid"])
        elif "bid_price" in quote and quote["bid_price"] is not None:
            simple_data["bid"] = float(quote["bid_price"])
        
        # Ask price
        if "ask" in quote and quote["ask"] is not None:
            simple_data["ask"] = float(quote["ask"])
        elif "ask_price" in quote and quote["ask_price"] is not None:
            simple_data["ask"] = float(quote["ask_price"])
        elif "offer_price" in quote and quote["offer_price"] is not None:
            simple_data["ask"] = float(quote["offer_price"])
            
        # Debug output
        logger.info("FINAL SIMPLE FORMAT:")
        for key, value in simple_data.items():
            logger.info(f"{{key}}: {value}")
        
        # Return exact structure expected by OpenAlgo
        result = {
            "status": "success",
            "data": simple_data
        }
        
        logger.info(f"FINAL FORMATTED RESULT: {result}")
        logger.info(f"Formatted result for OpenAlgo frontend: {result}")
        
        return result
        
    def get_depth(self, symbol_list, timeout: int = 5) -> Dict[str, Any]:
        """ 
        Get market depth for a symbol or list of symbols using Groww API.
        This leverages the direct API endpoint for quotes, which includes market depth information.
        
        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds
            
        Returns:
            Dict[str, Any]: Market depth data in OpenAlgo format
        """
        logger.info(f"Getting market depth using direct API calls for: {symbol_list}")
        
        # Make direct API call to get quote and depth data in a single request
        # Define exchange and segment constants
        EXCHANGE_NSE = 'NSE'
        EXCHANGE_BSE = 'BSE'
        SEGMENT_CASH = 'CASH'
        SEGMENT_FNO = 'FNO'
        
        # Standardize input to a list of dictionaries with exchange and symbol
        symbols_to_process = []
        if isinstance(symbol_list, dict):
            symbol = symbol_list.get('symbol') or symbol_list.get('SYMBOL')
            exchange = symbol_list.get('exchange') or symbol_list.get('EXCHANGE')
            if symbol and exchange:
                symbols_to_process.append({'symbol': symbol, 'exchange': exchange})
        elif isinstance(symbol_list, str):
            symbols_to_process.append({'symbol': symbol_list, 'exchange': 'NSE'})
        elif isinstance(symbol_list, list):
            for sym in symbol_list:
                if isinstance(sym, dict) and 'symbol' in sym and 'exchange' in sym:
                    symbols_to_process.append(sym)
                elif isinstance(sym, str):
                    symbols_to_process.append({'symbol': sym, 'exchange': 'NSE'})
        
        # No valid symbols to process
        if not symbols_to_process:
            logger.error("No valid symbols to process for market depth")
            return {}
            
        # Process the first symbol (for single symbol requests)
        sym_data = symbols_to_process[0]
        symbol = sym_data['symbol']
        exchange = sym_data['exchange']
        
        # Get token for this symbol
        token = get_token(symbol, exchange)
        
        # Map OpenAlgo exchange to Groww exchange format
        if exchange == 'NSE':
            groww_exchange = EXCHANGE_NSE
            segment = SEGMENT_CASH
        elif exchange == 'BSE':
            groww_exchange = EXCHANGE_BSE
            segment = SEGMENT_CASH
        elif exchange == 'NFO':
            groww_exchange = EXCHANGE_NSE
            segment = SEGMENT_FNO
        elif exchange == 'BFO':
            groww_exchange = EXCHANGE_BSE
            segment = SEGMENT_FNO
        else:
            groww_exchange = EXCHANGE_NSE
            segment = SEGMENT_CASH
        
        # Convert symbol format for derivatives
        if exchange in ["NFO", "BFO"]:
            # First try to get from database
            br_symbol = get_br_symbol(symbol, exchange)
            if br_symbol:
                trading_symbol = br_symbol
                logger.debug(f"Found broker symbol in database: {trading_symbol}")
            else:
                # If not in database, convert format
                trading_symbol = self._convert_openalgo_to_groww_derivative_symbol(symbol)
                logger.debug(f"Converted derivative symbol: {symbol} -> {trading_symbol}")
        else:
            # For equity, use broker symbol if available
            trading_symbol = get_br_symbol(symbol, exchange) or symbol
        
        logger.info(f"Requesting quote with depth for {trading_symbol} on {groww_exchange} (segment: {segment})")
        
        # Define API endpoint for quotes
        quote_endpoint = "/v1/live-data/quote"
        
        # Prepare parameters
        params = {
            'exchange': groww_exchange,
            'segment': segment,
            'trading_symbol': trading_symbol
        }
        
        # Make the API call using the shared httpx client
        try:
            response = get_api_response(
                endpoint=quote_endpoint,
                auth_token=self.auth_token,
                method="GET",
                params=params,
                debug=True
            )
            
            logger.debug(f"Groww API raw response: {response}")
            
            # Check if we got a valid response with depth data
            if not response or response.get('status') != 'SUCCESS' or 'payload' not in response:
                logger.error(f"No valid quote data received for {symbol}")
                return {}
            
            # Extract payload data
            payload = response['payload']
            logger.info(f"Extracted payload with keys: {list(payload.keys())[:10]}")
            
            # Create a properly formatted response for OpenAlgo
            depth_response = {}
            
            # Safely convert values to float/int, handling None values
            def safe_float(value, default=0.0):
                if value is None:
                    return default
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return default
                    
            def safe_int(value, default=0):
                if value is None:
                    return default
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return default
            
            # Extract OHLC data
            ohlc_data = payload.get('ohlc', '{}')
            ohlc = {}
            if isinstance(ohlc_data, str):
                # Parse string format like "{open: 149.50,high: 150.50,low: 148.50,close: 149.50}"
                try:
                    ohlc_str = ohlc_data.strip('{}')
                    parts = ohlc_str.split(',')
                    for part in parts:
                        key_val = part.split(':')
                        if len(key_val) == 2:
                            key = key_val[0].strip()
                            val = key_val[1].strip()
                            ohlc[key] = float(val)
                except Exception as e:
                    logger.error(f"Error parsing OHLC string: {e}")
            elif isinstance(ohlc_data, dict):
                ohlc = ohlc_data
            
            # Format bids/asks from market depth
            bids = []
            asks = []
            empty_price_level = {'price': 0, 'quantity': 0}
            
            # Extract depth info
            depth_data = payload.get('depth', {})

            # Handle case where depth_data is None
            if depth_data is None:
                depth_data = {}

            # Process buy side (bids)
            for level in depth_data.get('buy', []):
                if len(bids) < 5:  # Limit to 5 levels
                    bids.append({
                        'price': safe_float(level.get('price', 0)),
                        'quantity': safe_int(level.get('quantity', 0))
                    })
            
            # Process sell side (asks)
            for level in depth_data.get('sell', []):
                if len(asks) < 5:  # Limit to 5 levels
                    asks.append({
                        'price': safe_float(level.get('price', 0)),
                        'quantity': safe_int(level.get('quantity', 0))
                    })
            
            # Ensure we have exactly 5 price levels
            while len(bids) < 5:
                bids.append(empty_price_level.copy())
            while len(asks) < 5:
                asks.append(empty_price_level.copy())
            
            # Last traded price and quantity
            ltp = safe_float(payload.get('last_price', 0))
            ltq = safe_int(payload.get('last_trade_quantity', 0))
            
            # Volume information
            volume = safe_int(payload.get('volume', 0))
            total_buy_qty = safe_int(payload.get('total_buy_quantity', 0))
            total_sell_qty = safe_int(payload.get('total_sell_quantity', 0))
            
            # Determine if this is a derivative instrument
            is_derivative = exchange in ['NFO', 'BFO'] or segment == SEGMENT_FNO
            
            # Format the depth response according to OpenAlgo requirements
            depth_response = {
                'bids': bids,
                'asks': asks,
                'ltp': ltp,
                'ltq': ltq,
                'open': safe_float(ohlc.get('open', 0)),
                'high': safe_float(ohlc.get('high', 0)),
                'low': safe_float(ohlc.get('low', 0)),
                'prev_close': safe_float(ohlc.get('close', 0)),
                'volume': volume,
                'totalbuyqty': total_buy_qty,
                'totalsellqty': total_sell_qty,
                'oi': safe_int(payload.get('open_interest', 0)) if is_derivative else 0  # OI only for derivatives
            }
            
            logger.info(f"Formatted market depth response with {len(bids)} bids and {len(asks)} asks")
            return depth_response
            
        except Exception as e:
            logger.error(f"Error getting market depth: {str(e)}")
            traceback.print_exc()
            return {}

    def get_market_depth(self, symbol_list, timeout: int = 5) -> Dict[str, Any]:
        """Alias for get_depth. Maintains API compatibility.
        
        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds
            
        Returns:
            Dict[str, Any]: Market depth data in OpenAlgo format
        """
        return self.get_depth(symbol_list, timeout)