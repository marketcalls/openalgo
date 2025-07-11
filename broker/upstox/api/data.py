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
    """Common function to make API calls to Upstox using httpx with connection pooling"""
    AUTH_TOKEN = auth
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'Authorization': f'Bearer {AUTH_TOKEN}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    url = f"https://api.upstox.com{endpoint}"
    logger.debug(f"Making {method} request to Upstox API: {url}")
    
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
        
        # Map standard intervals to Upstox intervals
        # Only include intervals that Upstox actually supports:
        # - 1-minute (intraday/1 month historical)
        # - 30-minute (intraday/1 year historical)
        # - Daily (1 year historical)
        # - Weekly (10 years historical)
        # - Monthly (10 years historical)
        self.timeframe_map = {
            # Minutes
            '1m': '1minute',   # Last month only
            '30m': '30minute', # Last year only
            # Days/Weeks/Months
            'D': 'day',       # Last year only
            'W': 'week',       # Last 10 years
            'M': 'month'       # Last 10 years
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
            
            # Use quotes endpoint
            url = f"/v2/market-quote/quotes?instrument_key={encoded_symbol}"
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
            
            # Upstox API returns data with instrument_key as the key
            quote = quote_data.get(instrument_key)

            if not quote:
                raise Exception(f"No quote data found for instrument key: {instrument_key} in response: {quote_data}")
            
            # Extract depth data - handle index instruments differently
            depth = quote.get('depth', {})
            
            # Check if this is an index instrument (NSE_INDEX or BSE_INDEX)
            is_index = 'INDEX' in instrument_key.split('|')[0]
            
            if is_index:
                # For index instruments, don't try to get bid/ask data (no order book)
                best_bid_price = 0
                best_ask_price = 0
            else:
                # For tradable instruments, extract bid/ask if available
                buy_orders = depth.get('buy', [])
                sell_orders = depth.get('sell', [])
                
                # Safely get the first bid/ask or default to 0
                best_bid_price = buy_orders[0].get('price', 0) if buy_orders else 0
                best_ask_price = sell_orders[0].get('price', 0) if sell_orders else 0
            
            # Return standard quote data format
            return {
                'ask': best_ask_price,
                'bid': best_bid_price,
                'high': quote.get('ohlc', {}).get('high', 0),
                'low': quote.get('ohlc', {}).get('low', 0),
                'ltp': quote.get('last_price', 0),
                'open': quote.get('ohlc', {}).get('open', 0),
                'prev_close': quote.get('ohlc', {}).get('close', 0),
                'volume': quote.get('volume', 0)
            }
            
        except Exception as e:
            logger.exception(f"Error fetching quotes for {symbol} on {exchange}")
            raise

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Time interval (e.g., 1m, 5m, 15m, 1h, 1d)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Get the correct instrument key
            instrument_key = self._get_instrument_key(symbol, exchange)
            logger.debug(f"Using instrument key: {instrument_key}")
            
            # Map standard interval to Upstox interval
            upstox_interval = self.timeframe_map.get(interval)
            if not upstox_interval:
                raise Exception(f"Invalid interval: {interval}")
            logger.debug(f"Using interval: {upstox_interval}")
                
            # URL encode the instrument key
            encoded_symbol = urllib.parse.quote(instrument_key)
            
            # Parse dates
            end = datetime.strptime(end_date, '%Y-%m-%d')
            start = datetime.strptime(start_date, '%Y-%m-%d')
            current_date = datetime.now()
            logger.debug(f"Date range: {start} to {end}")
            
            # Check if end date is today to fetch today's data as well
            is_today_requested = end.date() == current_date.date()
            
            # Validate date ranges based on interval
            if interval == '1m':
                # 1-minute: last month only
                max_start = end - timedelta(days=30)
                if start < max_start:
                    start = max_start
                    logger.debug(f"Adjusted start date to {start} for 1m interval")
            elif interval == '30m':
                # 30-minute: last year only
                max_start = end - timedelta(days=365)
                if start < max_start:
                    start = max_start
                    logger.debug(f"Adjusted start date to {start} for 30m interval")
            elif interval == 'D':
                # Daily: last year only
                max_start = end - timedelta(days=365)
                if start < max_start:
                    start = max_start
                    logger.debug(f"Adjusted start date to {start} for D interval")
            elif interval == 'W':
                # Weekly: last 10 years
                max_start = end - timedelta(days=3650)  # 10 years
                if start < max_start:
                    start = max_start
                    logger.debug(f"Adjusted start date to {start} for W interval")
            elif interval == 'M':
                # Monthly: last 10 years
                max_start = end - timedelta(days=3650)  # 10 years
                if start < max_start:
                    start = max_start
                    logger.debug(f"Adjusted start date to {start} for M interval")
            
            all_candles = []
            
            # Try intraday endpoint first if interval is 1m or 30m
            if interval in ['1m', '30m']:
                logger.debug("Trying intraday endpoint...")
                intraday_url = f"/v2/historical-candle/intraday/{encoded_symbol}/{upstox_interval}"
                logger.debug(f"Intraday URL: {intraday_url}")
                intraday_response = get_api_response(intraday_url, self.auth_token)
                logger.debug(f"Intraday Response: {intraday_response}")
                
                if intraday_response.get('status') == 'success':
                    intraday_candles = intraday_response.get('data', {}).get('candles', [])
                    logger.debug(f"Got {len(intraday_candles)} candles from intraday endpoint")
                    all_candles.extend(intraday_candles)
            
            # If no intraday data or need more historical data, try historical endpoint
            if not all_candles or start.date() < current_date.date():
                logger.debug("Trying historical endpoint...")
                # Format dates for historical endpoint
                from_date = start.strftime('%Y-%m-%d')
                to_date = end.strftime('%Y-%m-%d')
                
                # Historical endpoint URL format: /historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}
                historical_url = f"/v2/historical-candle/{encoded_symbol}/{upstox_interval}/{to_date}/{from_date}"
                logger.debug(f"Historical URL: {historical_url}")
                historical_response = get_api_response(historical_url, self.auth_token)
                logger.debug(f"Historical Response: {historical_response}")
                
                if historical_response.get('status') == 'success':
                    historical_candles = historical_response.get('data', {}).get('candles', [])
                    logger.debug(f"Got {len(historical_candles)} candles from historical endpoint")
                    all_candles.extend(historical_candles)
            
            logger.debug(f"Total candles: {len(all_candles)}")
            
            # Special case: If requesting only today's data (start and end dates are the same day and that day is today)
            today = datetime.now().date()
            if start.date() == end.date() == today and not all_candles:
                logger.debug("Special case: Requesting only today's data")
                try:
                    # Get today's data from quote endpoint
                    quote = self.get_quotes(symbol, exchange)
                    if quote and quote.get('ltp', 0) > 0:
                        # Create today's candle
                        today_datetime = pd.Timestamp.today().normalize()
                        
                        # Create a single candle for today
                        today_candle = [
                            today_datetime.strftime('%Y-%m-%dT%H:%M:%S'), 
                            quote.get('open', quote.get('ltp', 0)),
                            quote.get('high', quote.get('ltp', 0)),
                            quote.get('low', quote.get('ltp', 0)),
                            quote.get('ltp', 0),
                            quote.get('volume', 0),
                            0  # OI default
                        ]
                        all_candles.append(today_candle)
                        logger.debug("Added today's candle from quote data for single-day request")
                except Exception as e:
                    logger.warning(f"Could not add today's data for single-day request: {e}")
            
            if not all_candles:
                if start.date() == end.date() == today:
                    # If we still have no data for today, return a meaningful error
                    raise Exception("No data available for today. Market may not be open yet or quote data is unavailable.")
                return pd.DataFrame()  # Return empty DataFrame if no data for other date ranges
                
            # Convert candle data to DataFrame
            # Upstox format: [timestamp, open, high, low, close, volume, oi]
            df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
            
            # Convert timestamp to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Upstox returns IST timestamps, but we need to convert them to UTC 
            # for consistency with other brokers (SDK will convert back to IST)
            if not df.empty and interval in ['1m', '30m']:
                # Check if timestamps are timezone-aware
                if df['timestamp'].dt.tz is None:
                    # Assume IST (what Upstox returns) and convert to UTC
                    df['timestamp'] = df['timestamp'].dt.tz_localize('Asia/Kolkata').dt.tz_convert('UTC').dt.tz_localize(None)
                else:
                    # If already timezone-aware, convert to UTC
                    df['timestamp'] = df['timestamp'].dt.tz_convert('UTC').dt.tz_localize(None)
                
            # Handle daily data specifically - fix timestamp to show just the date (remove 18:30:00)
            if interval == 'D':
                # For daily timeframe, adjust timestamps to midnight
                df['timestamp'] = df['timestamp'].dt.normalize()  # Set to midnight
            
            # Add today's data if requested and not already in the dataset
            if is_today_requested and interval == 'D':
                # Check if today's data is already in the dataset
                today_date_str = pd.Timestamp.now().strftime('%Y-%m-%d')
                today_date = pd.to_datetime(today_date_str)
                
                # Check if today's date already exists in the dataframe
                today_exists = False
                if not df.empty:
                    # Compare dates after stripping time components
                    df_dates = df['timestamp'].dt.normalize()
                    today_exists = any(d.date() == today_date.date() for d in df_dates)
                    
                if not today_exists:
                    # Try to get today's data from quote endpoint
                    try:
                        quote = self.get_quotes(symbol, exchange)
                        if quote and quote.get('ltp', 0) > 0:
                            # Create today's candle with string timestamp to ensure compatibility
                            today_candle = pd.DataFrame({
                                'timestamp': [today_date],  # Use datetime object directly
                                'open': [quote.get('open', quote.get('ltp', 0))], 
                                'high': [quote.get('high', quote.get('ltp', 0))],
                                'low': [quote.get('low', quote.get('ltp', 0))],
                                'close': [quote.get('ltp', 0)],
                                'volume': [quote.get('volume', 0)],
                                'oi': [0]  # Default value
                            })
                            
                            # Append to dataframe
                            df = pd.concat([df, today_candle], ignore_index=True)
                            logger.debug("Added today's candle from quote data")
                    except Exception as e:
                        logger.warning(f"Could not add today's data: {e}")
            
            # Ensure all timestamps are consistent before converting to Unix epoch
            if not df.empty:
                # First make sure all timestamps are normalized for daily data
                if interval == 'D':
                    df['timestamp'] = df['timestamp'].dt.normalize()
                    
                # Make all timestamps timezone-naive if they aren't already
                # This is safe to call even if already timezone-naive
                if hasattr(df['timestamp'].dt, 'tz_localize') and df['timestamp'].dt.tz is not None:
                    df['timestamp'] = df['timestamp'].dt.tz_localize(None)
                
                # Convert to Unix epoch
                df['timestamp'] = df['timestamp'].astype(np.int64) // 10**9
            
            # Drop oi column and reorder columns to match expected format
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            
            # Remove duplicates and sort by timestamp
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
            
            return df
            
        except Exception as e:
            logger.exception(f"Error fetching historical data for {symbol} on {exchange}")
            raise

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
            
            # Use quotes endpoint to get depth
            url = f"/v2/market-quote/quotes?instrument_key={encoded_symbol}"
            response = get_api_response(url, self.auth_token)
            
            if response.get('status') != 'success':
                error_msg = response.get('message', 'Unknown error')
                if 'errors' in response and response['errors']:
                    error = response['errors'][0]
                    error_msg = error.get('message', error_msg)
                full_error_msg = f"API Error: {error_msg}"
                logger.exception(f"Failed to get market depth for {instrument_key}: {full_error_msg}")
                raise Exception(full_error_msg)
            
            # Get quote data for the symbol
            data = response.get('data', {}).get(instrument_key, {})
            if not data:
                raise Exception(f"No data received for instrument key: {instrument_key}")
            
            # Extract depth data
            depth = data.get('depth', {})
            buy_orders = depth.get('buy', [])
            sell_orders = depth.get('sell', [])
            
            # Format buy and sell orders safely
            bids = [{'price': b.get('price', 0), 'quantity': b.get('quantity', 0), 'orders': b.get('orders', 0)} for b in buy_orders[:5]]
            asks = [{'price': s.get('price', 0), 'quantity': s.get('quantity', 0), 'orders': s.get('orders', 0)} for s in sell_orders[:5]]
            
            # Return standard depth data format
            return {
                'asks': asks,
                'bids': bids,
                'high': data.get('ohlc', {}).get('high', 0),
                'low': data.get('ohlc', {}).get('low', 0),
                'ltp': data.get('last_price', 0),
                'ltq': data.get('last_quantity', 0),
                'oi': data.get('oi', 0),
                'open': data.get('ohlc', {}).get('open', 0),
                'prev_close': data.get('ohlc', {}).get('close', 0),
                'totalbuyqty': data.get('total_buy_quantity', 0),
                'totalsellqty': data.get('total_sell_quantity', 0),
                'volume': data.get('volume', 0)
            }
            
        except Exception as e:
            logger.exception(f"Error fetching market depth for {symbol} on {exchange}")
            raise

    # Alias for get_depth to maintain compatibility
    get_market_depth = get_depth
