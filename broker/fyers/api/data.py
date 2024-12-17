import http.client
import json
import os
from database.token_db import get_br_symbol, get_oa_symbol
import pandas as pd
from datetime import datetime

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

class FyersData:
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
            
            response = get_api_response(f"/data/quotes?symbols={br_symbol}", self.auth_token)
            
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
            
            endpoint = (f"/data/history?symbol={br_symbol}&resolution={resolution}"
                       f"&date_format=1&range_from={start_date}&range_to={end_date}")
            
            response = get_api_response(endpoint, self.auth_token)
            
            if response.get('s') != 'ok':
                raise Exception(f"Error from Fyers API: {response.get('message', 'Unknown error')}")
            
            # Convert to DataFrame with minimal columns
            candles = response.get('candles', [])
            if not candles:
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                
            # Return DataFrame with epoch timestamp
            return pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
        except Exception as e:
            raise Exception(f"Error fetching historical data: {str(e)}")

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
            
            response = get_api_response(f"/data/depth?symbol={br_symbol}&ohlcv_flag=1", self.auth_token)
            
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
