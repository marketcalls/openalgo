import http.client
import json
import os
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
from database.token_db import get_token, get_br_symbol, get_oa_symbol

def get_api_response(endpoint, auth, method="POST", payload=None):
    """
    Common function to make API calls to Zebu
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

    conn = http.client.HTTPSConnection("go.mynt.in")  # Zebu API endpoint
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    conn.request(method, endpoint, payload_str, headers)
    res = conn.getresponse()
    data = res.read()
    
    return json.loads(data.decode("utf-8"))

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
            
            payload = {
                "uid": os.getenv('BROKER_API_KEY'),
                "exch": exchange,
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
                'volume': int(response.get('v', 0))
            }
            
        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}")

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
            
            payload = {
                "uid": os.getenv('BROKER_API_KEY'),
                "exch": exchange,
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
                'oi': 0  # Not provided in Zebu quotes response
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
            start_ts = int(datetime.strptime(start_date + " 00:00:00", '%Y-%m-%d %H:%M:%S').timestamp())
            end_ts = int(datetime.strptime(end_date + " 23:59:59", '%Y-%m-%d %H:%M:%S').timestamp())

            # For daily data, use EODChartData endpoint
            if interval == 'D':
                payload = {
                    "sym": f"{exchange}:{br_symbol}",
                    "from": start_ts,
                    "to": end_ts
                }
                response = get_api_response("/NorenWClientTP/EODChartData", self.auth_token, payload=payload)
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
                response = get_api_response("/NorenWClientTP/TPSeries", self.auth_token, payload=payload)
            
            if not isinstance(response, list):
                if response.get('stat') == 'Not_Ok':
                    raise Exception(f"Error from Zebu API: {response.get('emsg', 'Unknown error')}")
                raise Exception("Invalid response format from Zebu API")
            
            # Convert response to DataFrame
            data = []
            for candle in response:
                if isinstance(candle, str):
                    candle = json.loads(candle)
                
                # Parse timestamp based on interval
                if interval == 'D':
                    # Daily data format: "21-SEP-2022"
                    timestamp = int(candle.get('ssboe', 0))
                else:
                    # Intraday format: "dd-mm-yyyy HH:MM:SS"
                    timestamp = int(datetime.strptime(candle['time'], '%d-%m-%Y %H:%M:%S').timestamp())
                
                data.append({
                    'timestamp': timestamp,
                    'open': float(candle.get('into', 0)),
                    'high': float(candle.get('inth', 0)),
                    'low': float(candle.get('intl', 0)),
                    'close': float(candle.get('intc', 0)),
                    'volume': float(candle.get('intv', 0))
                })
            
            df = pd.DataFrame(data)
            if df.empty:
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Sort by timestamp in ascending order
            df = df.sort_values('timestamp')
            return df
            
        except Exception as e:
            raise Exception(f"Error fetching historical data: {str(e)}")
