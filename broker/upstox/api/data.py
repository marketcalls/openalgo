import http.client
import json
import os
from database.token_db import get_token, get_br_symbol, get_oa_symbol
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import numpy as np

def get_api_response(endpoint, auth, method="GET", payload=''):
    """Common function to make API calls to Upstox"""
    AUTH_TOKEN = auth
    
    conn = http.client.HTTPSConnection("api.upstox.com")
    headers = {
        'Authorization': f'Bearer {AUTH_TOKEN}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    conn.request(method, endpoint, payload, headers)
    res = conn.getresponse()
    data = res.read()
    return json.loads(data.decode("utf-8"))

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
            
            print(f"Using instrument key: {token}")
            return token
            
        except Exception as e:
            print(f"Error getting instrument key: {e}")
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
                if 'errors' in response:
                    error = response['errors'][0]
                    error_msg = error.get('message', error_msg)
                    error_code = error.get('errorCode', 'NO_CODE')
                else:
                    error_code = response.get('code', 'NO_CODE')
                raise Exception(f"API Error - Code: {error_code}, Message: {error_msg}")
            
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
            
            # Extract depth data
            depth = quote.get('depth', {})
            best_bid = depth.get('buy', [{}])[0]
            best_ask = depth.get('sell', [{}])[0]
            
            # Return standard quote data format
            return {
                'ask': best_ask.get('price', 0),
                'bid': best_bid.get('price', 0),
                'high': quote.get('ohlc', {}).get('high', 0),
                'low': quote.get('ohlc', {}).get('low', 0),
                'ltp': quote.get('last_price', 0),
                'open': quote.get('ohlc', {}).get('open', 0),
                'prev_close': quote.get('ohlc', {}).get('close', 0),
                'volume': quote.get('volume', 0)
            }
            
        except Exception as e:
            print(f"Exception in get_quotes: {str(e)}")
            raise Exception(f"Error fetching quotes: {str(e)}")

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
            print(f"Using instrument key: {instrument_key}")
            
            # Map standard interval to Upstox interval
            upstox_interval = self.timeframe_map.get(interval)
            if not upstox_interval:
                raise Exception(f"Invalid interval: {interval}")
            print(f"Using interval: {upstox_interval}")
                
            # URL encode the instrument key
            encoded_symbol = urllib.parse.quote(instrument_key)
            
            # Parse dates
            end = datetime.strptime(end_date, '%Y-%m-%d')
            start = datetime.strptime(start_date, '%Y-%m-%d')
            current_date = datetime.now()
            print(f"Date range: {start} to {end}")
            
            # Validate date ranges based on interval
            if interval == '1m':
                # 1-minute: last month only
                max_start = end - timedelta(days=30)
                if start < max_start:
                    start = max_start
                    print(f"Adjusted start date to {start} for 1m interval")
            elif interval == '30m':
                # 30-minute: last year only
                max_start = end - timedelta(days=365)
                if start < max_start:
                    start = max_start
                    print(f"Adjusted start date to {start} for 30m interval")
            elif interval == 'D':
                # Daily: last year only
                max_start = end - timedelta(days=365)
                if start < max_start:
                    start = max_start
                    print(f"Adjusted start date to {start} for D interval")
            elif interval == 'W':
                # Weekly: last 10 years
                max_start = end - timedelta(days=3650)  # 10 years
                if start < max_start:
                    start = max_start
                    print(f"Adjusted start date to {start} for W interval")
            elif interval == 'M':
                # Monthly: last 10 years
                max_start = end - timedelta(days=3650)  # 10 years
                if start < max_start:
                    start = max_start
                    print(f"Adjusted start date to {start} for M interval")
            
            all_candles = []
            
            # Try intraday endpoint first if interval is 1m or 30m
            if interval in ['1m', '30m']:
                print("Trying intraday endpoint...")
                intraday_url = f"/v2/historical-candle/intraday/{encoded_symbol}/{upstox_interval}"
                print(f"Intraday URL: {intraday_url}")
                intraday_response = get_api_response(intraday_url, self.auth_token)
                print(f"Intraday Response: {intraday_response}")
                
                if intraday_response.get('status') == 'success':
                    intraday_candles = intraday_response.get('data', {}).get('candles', [])
                    print(f"Got {len(intraday_candles)} candles from intraday endpoint")
                    all_candles.extend(intraday_candles)
            
            # If no intraday data or need more historical data, try historical endpoint
            if not all_candles or start.date() < current_date.date():
                print("Trying historical endpoint...")
                # Format dates for historical endpoint
                from_date = start.strftime('%Y-%m-%d')
                to_date = end.strftime('%Y-%m-%d')
                
                # Historical endpoint URL format: /historical-candle/{instrument_key}/{interval}/{to_date}/{from_date}
                historical_url = f"/v2/historical-candle/{encoded_symbol}/{upstox_interval}/{to_date}/{from_date}"
                print(f"Historical URL: {historical_url}")
                historical_response = get_api_response(historical_url, self.auth_token)
                print(f"Historical Response: {historical_response}")
                
                if historical_response.get('status') == 'success':
                    historical_candles = historical_response.get('data', {}).get('candles', [])
                    print(f"Got {len(historical_candles)} candles from historical endpoint")
                    all_candles.extend(historical_candles)
            
            print(f"Total candles: {len(all_candles)}")
            
            if not all_candles:
                return pd.DataFrame()  # Return empty DataFrame if no data
                
            # Convert candle data to DataFrame
            # Upstox format: [timestamp, open, high, low, close, volume, oi]
            df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
            
            # Convert timestamp to datetime and handle timezone properly
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            # First convert to UTC, then to naive timestamp to avoid timezone issues
            if not df.empty:
            #    df['timestamp'] = df['timestamp'].dt.tz_localize(None)
                df['timestamp'] = df['timestamp'].astype(np.int64) // 10**9
            
            # Drop oi column and reorder columns to match expected format
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            
            # Remove duplicates and sort by timestamp
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
            
            return df
            
        except Exception as e:
            print(f"Exception in get_history: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")

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
            
            # Use quotes endpoint
            url = f"/v2/market-quote/quotes?instrument_key={encoded_symbol}"
            response = get_api_response(url, self.auth_token)
            
            if response.get('status') != 'success':
                error_msg = response.get('message', 'Unknown error')
                if 'errors' in response:
                    error = response['errors'][0]
                    error_msg = error.get('message', error_msg)
                    error_code = error.get('errorCode', 'NO_CODE')
                else:
                    error_code = response.get('code', 'NO_CODE')
                raise Exception(f"API Error - Code: {error_code}, Message: {error_msg}")
            
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
            
            # Get depth data
            depth = quote.get('depth', {})
            
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
                'high': quote.get('ohlc', {}).get('high', 0),
                'low': quote.get('ohlc', {}).get('low', 0),
                'ltp': quote.get('last_price', 0),
                'ltq': quote.get('last_quantity', 0),
                'oi': quote.get('oi', 0),
                'open': quote.get('ohlc', {}).get('open', 0),
                'prev_close': quote.get('ohlc', {}).get('close', 0),
                'totalbuyqty': quote.get('total_buy_quantity', 0),
                'totalsellqty': quote.get('total_sell_quantity', 0),
                'volume': quote.get('volume', 0)
            }
            
        except Exception as e:
            print(f"Exception in get_depth: {str(e)}")
            raise Exception(f"Error fetching market depth: {str(e)}")

    # Alias for get_depth to maintain compatibility
    get_market_depth = get_depth
