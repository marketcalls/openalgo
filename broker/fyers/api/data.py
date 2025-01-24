import http.client
import json
import os
from database.token_db import get_br_symbol, get_oa_symbol
import pandas as pd
from datetime import datetime
import urllib.parse
import time

def get_api_response(endpoint, auth, method="GET", payload=''):
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_KEY')

    conn = http.client.HTTPSConnection("api-t1.fyers.in")
    headers = {
        'Authorization': f'{api_key}:{AUTH_TOKEN}',
        'Content-Type': 'application/json'
    }

    conn.request(method, endpoint, payload, headers)
    res = conn.getresponse()
    data = res.read()
    return json.loads(data.decode("utf-8"))

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Fyers data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Fyers resolutions
        self.timeframe_map = {
            # Seconds - Use 'S' suffix for seconds timeframes
            '5s': '5S', '10s': '10S', '15s': '15S', '30s': '30S', '45s': '45S',
            # Minutes
            '1m': '1', '2m': '2', '3m': '3', '5m': '5',
            '10m': '10', '15m': '15', '20m': '20', '30m': '30',
            # Hours
            '1h': '60', '2h': '120', '4h': '240',
            # Daily
            'D': '1D'
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
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            
            # URL encode the symbol to handle special characters
            encoded_symbol = urllib.parse.quote(br_symbol)
            
            response = get_api_response(f"/data/quotes?symbols={encoded_symbol}", self.auth_token)
            
            if response.get('s') != 'ok':
                raise Exception(f"Error from Fyers API: {response.get('message', 'Unknown error')}")
            
            # Get first quote from response
            quote = response.get('d', [{}])[0]
            v = quote.get('v', {})
            
            # Return simplified quote data
            return {
                'bid': v.get('bid', 0),
                'ask': v.get('ask', 0), 
                'open': v.get('open_price', 0),
                'high': v.get('high_price', 0),
                'low': v.get('low_price', 0),
                'ltp': v.get('lp', 0),
                'prev_close': v.get('prev_close_price', 0),
                'volume': v.get('volume', 0)
            }
            
        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}")

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Candle interval in common format:
                     Seconds: 5s, 10s, 15s, 30s, 45s
                     Minutes: 1m, 2m, 3m, 5m, 10m, 15m, 20m, 30m
                     Hours: 1h, 2h, 4h
                     Daily: D
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp (epoch), open, high, low, close, volume]
        """
        try:
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            print(f"Using broker symbol: {br_symbol}")
            
            # Check for unsupported timeframes first
            if interval in ['W', 'M']:
                raise Exception(f"Timeframe '{interval}' is not supported by Fyers. Supported timeframes are:\n"
                              "Seconds: 5s, 10s, 15s, 30s, 45s\n"
                              "Minutes: 1m, 2m, 3m, 5m, 10m, 15m, 20m, 30m\n"
                              "Hours: 1h, 2h, 4h\n"
                              "Daily: D")
            
            # Validate and map interval
            resolution = self.timeframe_map.get(interval)
            if not resolution:
                supported = {
                    'Seconds': ['5s', '10s', '15s', '30s', '45s'],
                    'Minutes': ['1m', '2m', '3m', '5m', '10m', '15m', '20m', '30m'],
                    'Hours': ['1h', '2h', '4h'],
                    'Daily': ['D']
                }
                error_msg = "Unsupported timeframe. Supported timeframes:\n"
                for category, timeframes in supported.items():
                    error_msg += f"{category}: {', '.join(timeframes)}\n"
                raise Exception(error_msg)
            
            # Convert dates to datetime objects
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            current_dt = pd.Timestamp.now()
            
            # Adjust end date if it's in the future
            if end_dt > current_dt:
                print(f"Warning: End date {end_dt.date()} is in the future. Adjusting to current date {current_dt.date()}")
                end_dt = current_dt
            
            # Validate date range
            if start_dt > end_dt:
                raise Exception(f"Start date {start_dt.date()} cannot be after end date {end_dt.date()}")
            
            # Initialize empty list to store DataFrames
            dfs = []
            
            # Determine chunk size based on resolution
            if resolution == '1D':
                chunk_days = 300  # Reduced from 200 to be safer
            else:
                chunk_days = 60   # Reduced from 60 to be safer
            
            # Process data in chunks
            current_start = start_dt
            retry_count = 0
            max_retries = 3
            
            while current_start <= end_dt:
                try:
                    # Calculate chunk end date
                    current_end = min(current_start + pd.Timedelta(days=chunk_days-1), end_dt)
                    
                    # Format dates for API call
                    chunk_start = current_start.strftime('%Y-%m-%d')
                    chunk_end = current_end.strftime('%Y-%m-%d')
                    
                    print(f"Fetching {resolution} data for {exchange}:{br_symbol} from {chunk_start} to {chunk_end}")
                    
                    # URL encode the symbol to handle special characters
                    encoded_symbol = urllib.parse.quote(br_symbol)
                    
                    # Construct endpoint with query parameters
                    endpoint = (f"/data/history?"
                              f"symbol={encoded_symbol}&"
                              f"resolution={resolution}&"
                              f"date_format=1&"  # Keep epoch format
                              f"range_from={chunk_start}&"
                              f"range_to={chunk_end}")
                    
                    print(f"Making request to endpoint: {endpoint}")
                    response = get_api_response(endpoint, self.auth_token)
                    
                    if response.get('s') != 'ok':
                        error_msg = response.get('message', 'Unknown error')
                        print(f"Error for chunk {chunk_start} to {chunk_end}: {error_msg}")
                        
                        if retry_count < max_retries:
                            retry_count += 1
                            print(f"Retrying... Attempt {retry_count} of {max_retries}")
                            time.sleep(2 * retry_count)  # Exponential backoff
                            continue
                        
                        # If max retries reached, move to next chunk
                        retry_count = 0
                        current_start = current_end + pd.Timedelta(days=1)
                        time.sleep(1)
                        continue
                    
                    # Reset retry count on success
                    retry_count = 0
                    
                    # Get candles from response
                    candles = response.get('candles', [])
                    if candles:
                        # Convert list of lists to DataFrame with epoch timestamp
                        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                        dfs.append(df)
                        print(f"Got {len(candles)} candles for period {chunk_start} to {chunk_end}")
                    else:
                        print(f"No data available for period {chunk_start} to {chunk_end}")
                    
                    # Add a small delay between chunks to avoid rate limiting
                    time.sleep(0.5)
                    
                    # Move to next chunk
                    current_start = current_end + pd.Timedelta(days=1)
                    
                except Exception as e:
                    print(f"Error fetching chunk {chunk_start} to {chunk_end}: {str(e)}")
                    if retry_count < max_retries:
                        retry_count += 1
                        print(f"Retrying... Attempt {retry_count} of {max_retries}")
                        time.sleep(2 * retry_count)
                        continue
                    
                    # If max retries reached, move to next chunk
                    retry_count = 0
                    current_start = current_end + pd.Timedelta(days=1)
                    time.sleep(1)
                    continue
            
            # If no data was found, return empty DataFrame
            if not dfs:
                print("No data was collected for the entire period")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Combine all chunks
            final_df = pd.concat(dfs, ignore_index=True)
            
            # Sort by timestamp and remove duplicates
            final_df = final_df.sort_values('timestamp').drop_duplicates(subset=['timestamp'], keep='first')
            
            print(f"Successfully collected data: {len(final_df)} total candles")
            return final_df
            
        except Exception as e:
            error_msg = f"Error fetching historical data: {str(e)}"
            print(error_msg)
            raise Exception(error_msg)

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data with OHLC, volume and open interest
        """
        try:
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            
            # URL encode the symbol to handle special characters
            encoded_symbol = urllib.parse.quote(br_symbol)
            
            response = get_api_response(f"/data/depth?symbol={encoded_symbol}&ohlcv_flag=1", self.auth_token)
            
            if response.get('s') != 'ok':
                raise Exception(f"Error from Fyers API: {response.get('message', 'Unknown error')}")
            
            depth_data = response.get('d', {}).get(br_symbol, {})
            
            # Get bids and asks, pad with zeros if less than 5 entries
            bids = depth_data.get('bids', [])
            asks = depth_data.get('ask', [])
            
            # Ensure 5 entries for bids and asks
            empty_entry = {'price': 0, 'quantity': 0}
            bids_formatted = [{'price': b['price'], 'quantity': b['volume']} for b in bids[:5]]
            asks_formatted = [{'price': a['price'], 'quantity': a['volume']} for a in asks[:5]]
            
            while len(bids_formatted) < 5:
                bids_formatted.append(empty_entry)
            while len(asks_formatted) < 5:
                asks_formatted.append(empty_entry)
            
            # Return depth data with OHLC, volume and open interest
            return {
                'bids': bids_formatted,
                'asks': asks_formatted,
                'totalbuyqty': depth_data.get('totalbuyqty', 0),
                'totalsellqty': depth_data.get('totalsellqty', 0),
                'high': depth_data.get('h', 0),
                'low': depth_data.get('l', 0),
                'ltp': depth_data.get('ltp', 0),
                'ltq': depth_data.get('ltq', 0),  # Last Traded Quantity
                'open': depth_data.get('o', 0),
                'prev_close': depth_data.get('c', 0),
                'volume': depth_data.get('v', 0),
                'oi': int(depth_data.get('oi', 0))
            }
            
        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")
