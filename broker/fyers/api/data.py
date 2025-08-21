import json
import os
import httpx
from database.token_db import get_br_symbol, get_oa_symbol
import pandas as pd
from datetime import datetime
import urllib.parse
import time
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def get_api_response(endpoint, auth, method="GET", payload=''):
    """
    Make API requests to Fyers API using shared connection pooling.
    
    Args:
        endpoint: API endpoint (e.g., /api/v2/positions)
        auth: Authentication token
        method: HTTP method (GET, POST, etc.)
        payload: Request payload as a string or dict
        
    Returns:
        dict: Parsed JSON response from the API
    """
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        AUTH_TOKEN = auth
        api_key = os.getenv('BROKER_API_KEY')
        
        url = f"https://api-t1.fyers.in{endpoint}"
        headers = {
            'Authorization': f'{api_key}:{AUTH_TOKEN}',
            'Content-Type': 'application/json'
        }
        
        logger.debug(f"Making {method} request to Fyers API: {url}")
        
        # Make the request
        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, headers=headers, json=payload if isinstance(payload, dict) else json.loads(payload))
        else:
            response = client.request(method, url, headers=headers, json=payload if isinstance(payload, dict) else json.loads(payload))
        
        # Add status attribute for compatibility
        response.status = response.status_code
        
        # Raise HTTPError for bad responses (4xx, 5xx)
        response.raise_for_status()
        
        # Parse and return the JSON response
        response_data = response.json()
        logger.debug(f"API response: {json.dumps(response_data, indent=2)}")
        return response_data
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP error during API request: {str(e)}")
        return {"s": "error", "message": f"HTTP error: {str(e)}"}
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        return {"s": "error", "message": f"Invalid JSON response: {str(e)}"}
    except Exception as e:
        logger.exception("An unexpected error occurred during API request")
        return {"s": "error", "message": f"General error: {str(e)}"}

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
            br_symbol = get_br_symbol(symbol, exchange)
            encoded_symbol = urllib.parse.quote(br_symbol)
            
            response = get_api_response(f"/data/quotes?symbols={encoded_symbol}", self.auth_token)
            logger.debug(f"Fyers quotes API response: {response}")

            if response.get('s') != 'ok':
                error_msg = f"Error from Fyers API: {response.get('message', 'Unknown error')}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            quote_data = response.get('d', [{}])[0]
            v = quote_data.get('v', {})
            
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
            logger.exception(f"Error fetching quotes for {exchange}:{symbol}")
            raise Exception(f"Error fetching quotes: {e}")


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
            logger.debug(f"Using broker symbol: {br_symbol}")
            
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
                logger.warning(f"Warning: End date {end_dt.date()} is in the future. Adjusting to current date {current_dt.date()}")
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
                    
                    logger.debug(f"Fetching {resolution} data for {exchange}:{br_symbol} from {chunk_start} to {chunk_end}")
                    
                    # URL encode the symbol to handle special characters
                    encoded_symbol = urllib.parse.quote(br_symbol)
                    
                    # Determine if OI flag should be enabled based on exchange
                    # OI is only available for derivatives (NFO, BFO, MCX, CDS)
                    derivative_exchanges = ['NFO', 'BFO', 'MCX', 'CDS']
                    enable_oi = exchange in derivative_exchanges
                    
                    # Construct endpoint with query parameters
                    endpoint = (f"/data/history?"
                              f"symbol={encoded_symbol}&"
                              f"resolution={resolution}&"
                              f"date_format=1&"  # Keep epoch format
                               f"range_from={chunk_start}&"
                               f"range_to={chunk_end}&"
                               f"cont_flag=1")   # For continuous data
                    
                    # Add OI flag only for derivatives
                    if enable_oi:
                        endpoint += "&oi_flag=1"
                    
                    logger.debug(f"Making request to endpoint: {endpoint}")
                    response = get_api_response(endpoint, self.auth_token)
                    
                    if response.get('s') != 'ok':
                        error_msg = response.get('message', 'Unknown error')
                        logger.error(f"Error for chunk {chunk_start} to {chunk_end}: {error_msg}")
                        
                        if retry_count < max_retries:
                            retry_count += 1
                            logger.debug(f"Retrying... Attempt {retry_count} of {max_retries}")
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
                        # Handle dynamic column count based on whether OI is enabled
                        if enable_oi and len(candles[0]) == 7:
                            # Derivatives with OI: [timestamp, open, high, low, close, volume, oi]
                            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                        else:
                            # Equity without OI: [timestamp, open, high, low, close, volume]
                            df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                            # Add zero OI column for consistency
                            df['oi'] = 0
                        
                        dfs.append(df)
                        logger.debug(f"Got {len(candles)} candles for period {chunk_start} to {chunk_end}")
                    else:
                        logger.debug(f"No data available for period {chunk_start} to {chunk_end}")
                    
                    # Add a small delay between chunks to avoid rate limiting
                    time.sleep(0.5)
                    
                    # Move to next chunk
                    current_start = current_end + pd.Timedelta(days=1)
                    
                except Exception as e:
                    logger.error(f"Error fetching chunk {chunk_start} to {chunk_end}: {e}")
                    if retry_count < max_retries:
                        retry_count += 1
                        logger.debug(f"Retrying... Attempt {retry_count} of {max_retries}")
                        time.sleep(2 * retry_count)
                        continue
                    
                    # If max retries reached, move to next chunk
                    retry_count = 0
                    current_start = current_end + pd.Timedelta(days=1)
                    time.sleep(1)
                    continue
            
            # If no data was found, return empty DataFrame
            if not dfs:
                logger.warning("No data was collected for the entire period")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Combine all chunks
            final_df = pd.concat(dfs, ignore_index=True)
            
            # Sort by timestamp and remove duplicates
            final_df = final_df.sort_values('timestamp').drop_duplicates(subset=['timestamp'], keep='first')
            
            logger.info(f"Successfully collected data: {len(final_df)} total candles")
            return final_df
            
        except Exception as e:
            error_msg = f"Error fetching historical data for {exchange}:{symbol}"
            logger.exception(error_msg)
            raise Exception(f"{error_msg}: {e}")

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
            br_symbol = get_br_symbol(symbol, exchange)
            encoded_symbol = urllib.parse.quote(br_symbol)
            
            response = get_api_response(f"/data/depth?symbol={encoded_symbol}&ohlcv_flag=1", self.auth_token)
            logger.debug(f"Fyers depth API response: {response}")

            if response.get('s') != 'ok':
                error_msg = f"Error from Fyers API: {response.get('message', 'Unknown error')}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            depth_data = response.get('d', {}).get(br_symbol)
            if not depth_data:
                logger.warning(f"No market depth data found for {br_symbol} in API response.")
                return {}

            bids = depth_data.get('bids', [])
            asks = depth_data.get('asks', [])
            
            empty_entry = {'price': 0, 'quantity': 0}
            bids_formatted = [{'price': b['price'], 'quantity': b['volume']} for b in bids[:5]]
            asks_formatted = [{'price': a['price'], 'quantity': a['volume']} for a in asks[:5]]
            
            while len(bids_formatted) < 5:
                bids_formatted.append(empty_entry)
            while len(asks_formatted) < 5:
                asks_formatted.append(empty_entry)
            
            return {
                'bids': bids_formatted,
                'asks': asks_formatted,
                'totalbuyqty': depth_data.get('totalbuyqty', 0),
                'totalsellqty': depth_data.get('totalsellqty', 0),
                'high': depth_data.get('h', 0),
                'low': depth_data.get('l', 0),
                'ltp': depth_data.get('ltp', 0),
                'ltq': depth_data.get('ltq', 0),
                'open': depth_data.get('o', 0),
                'prev_close': depth_data.get('c', 0),
                'volume': depth_data.get('v', 0),
                'oi': int(depth_data.get('oi', 0))
            }
            
        except Exception as e:
            logger.exception(f"Error fetching market depth for {exchange}:{symbol}")
            raise Exception(f"Error fetching market depth: {e}")
