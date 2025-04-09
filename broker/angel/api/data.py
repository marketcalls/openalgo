import httpx
import json
import os
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
from database.token_db import get_br_symbol, get_token, get_oa_symbol
from utils.httpx_client import get_httpx_client

def get_api_response(endpoint, auth, method="GET", payload=''):
    """Helper function to make API calls to Angel One"""
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_KEY')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'Authorization': f'Bearer {AUTH_TOKEN}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-UserType': 'USER',
        'X-SourceID': 'WEB',
        'X-ClientLocalIP': 'CLIENT_LOCAL_IP',
        'X-ClientPublicIP': 'CLIENT_PUBLIC_IP',
        'X-MACAddress': 'MAC_ADDRESS',
        'X-PrivateKey': api_key
    }

    if isinstance(payload, dict):
        payload = json.dumps(payload)

    url = f"https://apiconnect.angelbroking.com{endpoint}"
    
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
            print(f"Debug - API returned 403 Forbidden. Headers: {headers}")
            print(f"Debug - Response text: {response.text}")
            raise Exception("Authentication failed. Please check your API key and auth token.")
            
        return json.loads(response.text)
    except json.JSONDecodeError:
        print(f"Debug - Failed to parse response. Status code: {response.status_code}")
        print(f"Debug - Response text: {response.text}")
        raise Exception(f"Failed to parse API response (status {response.status_code})")

class BrokerData:  
    def __init__(self, auth_token):
        """Initialize Angel data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Angel resolutions
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
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)

            if exchange == 'NSE_INDEX':
                exchange = 'NSE'
            elif exchange == 'BSE_INDEX':
                exchange = 'BSE'
            elif exchange == 'MCX_INDEX':
                exchange = 'MCX'
            
            # Prepare payload for Angel's quote API
            payload = {
                "mode": "FULL",
                "exchangeTokens": {
                    exchange: [token]
                }
            }
            
            response = get_api_response("/rest/secure/angelbroking/market/v1/quote/", 
                                      self.auth_token, 
                                      "POST", 
                                      payload)
            
            if not response.get('status'):
                raise Exception(f"Error from Angel API: {response.get('message', 'Unknown error')}")
            
            # Extract quote data from response
            fetched_data = response.get('data', {}).get('fetched', [])
            if not fetched_data:
                raise Exception("No quote data received")
                
            quote = fetched_data[0]
            
            # Return quote in common format
            depth = quote.get('depth', {})
            bids = depth.get('buy', [])
            asks = depth.get('sell', [])
            
            return {
                'bid': float(bids[0].get('price', 0)) if bids else 0,
                'ask': float(asks[0].get('price', 0)) if asks else 0,
                'open': float(quote.get('open', 0)),
                'high': float(quote.get('high', 0)),
                'low': float(quote.get('low', 0)),
                'ltp': float(quote.get('ltp', 0)),
                'prev_close': float(quote.get('close', 0)),
                'volume': int(quote.get('tradeVolume', 0))
            }
            
        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}")

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
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)

            
            
            token = get_token(symbol, exchange)
            print(f"Debug - Broker Symbol: {br_symbol}, Token: {token}")

            if exchange == 'NSE_INDEX':
                exchange = 'NSE'
            elif exchange == 'BSE_INDEX':
                exchange = 'BSE'
            elif exchange == 'MCX_INDEX':
                exchange = 'MCX'

            
            # Check for unsupported timeframes
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(f"Timeframe '{interval}' is not supported by Angel. Supported timeframes are: {', '.join(supported)}")
            
            # Convert dates to datetime objects
            from_date = pd.to_datetime(start_date)
            to_date = pd.to_datetime(end_date)
            
            # Set start time to 00:00 for the start date
            from_date = from_date.replace(hour=0, minute=0)
            
            # If end_date is today, set the end time to current time
            current_time = pd.Timestamp.now()
            if to_date.date() == current_time.date():
                to_date = current_time.replace(second=0, microsecond=0)  # Remove seconds and microseconds
            else:
                # For past dates, set end time to 23:59
                to_date = to_date.replace(hour=23, minute=59)
            
            # Initialize empty list to store DataFrames
            dfs = []
            
            # Set chunk size based on interval as per Angel API documentation
            interval_limits = {
                '1m': 30,    # ONE_MINUTE
                '3m': 60,    # THREE_MINUTE
                '5m': 100,   # FIVE_MINUTE
                '10m': 100,  # TEN_MINUTE
                '15m': 200,  # FIFTEEN_MINUTE
                '30m': 200,  # THIRTY_MINUTE
                '1h': 400,   # ONE_HOUR
                'D': 2000    # ONE_DAY
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
                    "exchange": exchange,
                    "symboltoken": token,
                    "interval": self.timeframe_map[interval],
                    "fromdate": current_start.strftime('%Y-%m-%d %H:%M'),
                    "todate": current_end.strftime('%Y-%m-%d %H:%M')
                }
                print(f"Debug - Fetching chunk from {current_start} to {current_end}")
                print(f"Debug - API Payload: {payload}")
                
                try:
                    response = get_api_response("/rest/secure/angelbroking/historical/v1/getCandleData",
                                              self.auth_token,
                                              "POST",
                                              payload)
                    print(f"Debug - API Response Status: {response.get('status')}")
                    
                    # Check if response is empty or invalid
                    if not response:
                        print(f"Debug - Empty response for chunk {current_start} to {current_end}")
                        current_start = current_end + timedelta(days=1)
                        continue
                    
                    if not response.get('status'):
                        print(f"Debug - Error response: {response.get('message', 'Unknown error')}")
                        current_start = current_end + timedelta(days=1)
                        continue
                        
                except Exception as chunk_error:
                    print(f"Debug - Error fetching chunk {current_start} to {current_end}: {str(chunk_error)}")
                    current_start = current_end + timedelta(days=1)
                    continue
                
                if not response.get('status'):
                    raise Exception(f"Error from Angel API: {response.get('message', 'Unknown error')}")
                
                # Extract candle data and create DataFrame
                data = response.get('data', [])
                if data:
                    chunk_df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    dfs.append(chunk_df)
                    print(f"Debug - Received {len(data)} candles for chunk")
                else:
                    print(f"Debug - No data received for chunk")
                
                # Move to next chunk
                current_start = current_end + timedelta(days=1)
                
            # If no data was found, return empty DataFrame
            if not dfs:
                print("Debug - No data received from API")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Combine all chunks
            df = pd.concat(dfs, ignore_index=True)
            
            # Convert timestamp to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # For daily timeframe, convert UTC to IST by adding 5 hours and 30 minutes
            if interval == 'D':
                df['timestamp'] = df['timestamp'] + pd.Timedelta(hours=5, minutes=30)
            
            # Convert timestamp to Unix epoch
            df['timestamp'] = df['timestamp'].astype('int64') // 10**9  # Convert to Unix epoch
            
            # Ensure numeric columns and proper order
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric)
            
            # Sort by timestamp and remove duplicates
            df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)
            
            # Reorder columns to match REST API format
            df = df[['close', 'high', 'low', 'open', 'timestamp', 'volume']]
            
            return df
            
        except Exception as e:
            print(f"Debug - Error: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
        Returns:
            dict: Market depth data with bids, asks and other details
        """
        try:
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)

            if exchange == 'NSE_INDEX':
                exchange = 'NSE'
            elif exchange == 'BSE_INDEX':
                exchange = 'BSE'
            elif exchange == 'MCX_INDEX':
                exchange = 'MCX'
            
            # Prepare payload for market depth API
            payload = {
                "mode": "FULL",
                "exchangeTokens": {
                    exchange: [token]
                }
            }
            
            response = get_api_response("/rest/secure/angelbroking/market/v1/quote/",
                                      self.auth_token,
                                      "POST",
                                      payload)
            
            if not response.get('status'):
                raise Exception(f"Error from Angel API: {response.get('message', 'Unknown error')}")
            
            # Extract depth data
            fetched_data = response.get('data', {}).get('fetched', [])
            if not fetched_data:
                raise Exception("No depth data received")
                
            quote = fetched_data[0]
            depth = quote.get('depth', {})
            
            # Format bids and asks with exactly 5 entries each
            bids = []
            asks = []
            
            # Process buy orders (top 5)
            buy_orders = depth.get('buy', [])
            for i in range(5):  # Ensure exactly 5 entries
                if i < len(buy_orders):
                    bid = buy_orders[i]
                    bids.append({
                        'price': bid.get('price', 0),
                        'quantity': bid.get('quantity', 0)
                    })
                else:
                    bids.append({'price': 0, 'quantity': 0})
            
            # Process sell orders (top 5)
            sell_orders = depth.get('sell', [])
            for i in range(5):  # Ensure exactly 5 entries
                if i < len(sell_orders):
                    ask = sell_orders[i]
                    asks.append({
                        'price': ask.get('price', 0),
                        'quantity': ask.get('quantity', 0)
                    })
                else:
                    asks.append({'price': 0, 'quantity': 0})
            
            # Return depth data in common format matching REST API response
            return {
                'bids': bids,
                'asks': asks,
                'high': quote.get('high', 0),
                'low': quote.get('low', 0),
                'ltp': quote.get('ltp', 0),
                'ltq': quote.get('lastTradeQty', 0),
                'open': quote.get('open', 0),
                'prev_close': quote.get('close', 0),
                'volume': quote.get('tradeVolume', 0),
                'oi': quote.get('opnInterest', 0),
                'totalbuyqty': quote.get('totBuyQuan', 0),
                'totalsellqty': quote.get('totSellQuan', 0)
            }
            
        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")
