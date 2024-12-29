import http.client
import json
import os
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
from database.token_db import get_token, get_br_symbol, get_oa_symbol

def get_api_response(endpoint, auth, method="POST", payload=None):
    """
    Common function to make API calls to Shoonya
    """
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_KEY')
    api_key = api_key[:-2]  # Shoonya specific requirement

    if payload is None:
        data = {
            "uid": api_key,
            "actid": api_key
        }
    else:
        data = payload
        data["uid"] = api_key

    payload_str = "jData=" + json.dumps(data) + "&jKey=" + AUTH_TOKEN

    conn = http.client.HTTPSConnection("api.shoonya.com")
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}

    conn.request(method, endpoint, payload_str, headers)
    res = conn.getresponse()
    data = res.read()
    
    return json.loads(data.decode("utf-8"))

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Shoonya data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Shoonya resolutions
        self.timeframe_map = {
            '1m': '1',    # 1 minute
            '3m': '3',    # 3 minutes
            '5m': '5',    # 5 minutes
            '10m': '10',  # 10 minutes
            '15m': '15',  # 15 minutes
            '30m': '30',  # 30 minutes
            '1h': '60',   # 1 hour (60 minutes)
            '2h': '120',  # 2 hours (120 minutes)
            '4h': '240',  # 4 hours (240 minutes)
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
                "exch": exchange,
                "token": token
            }
            
            response = get_api_response("/NorenWClientTP/GetQuotes", self.auth_token, payload=payload)
            
            if response.get('stat') != 'Ok':
                raise Exception(f"Error from Shoonya API: {response.get('emsg', 'Unknown error')}")
            
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
                "exch": exchange,
                "token": token
            }
            
            response = get_api_response("/NorenWClientTP/GetQuotes", self.auth_token, payload=payload)
            
            if response.get('stat') != 'Ok':
                raise Exception(f"Error from Shoonya API: {response.get('emsg', 'Unknown error')}")
            
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
                'oi': 0  # Shoonya doesn't provide OI in quotes response
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
                # Format symbol for EOD data
                sym = f"{exchange}:{br_symbol}"
                
                payload = {
                    "sym": sym,
                    "from": str(start_ts),
                    "to": str(end_ts)
                }
                
                # Add debug logging
                print(f"EOD Request payload: {payload}")
                
                response = get_api_response("/NorenWClientTP/EODChartData", self.auth_token, payload=payload)
                
                # Parse EOD response
                if isinstance(response, list):
                    data = []
                    for item in response:
                        if isinstance(item, str):
                            item = json.loads(item)
                        data.append({
                            'timestamp': int(item['ssboe']),
                            'open': float(item['into']),
                            'high': float(item['inth']),
                            'low': float(item['intl']),
                            'close': float(item['intc']),
                            'volume': float(item['intv'])
                        })
                    return pd.DataFrame(data)
                else:
                    raise Exception(f"Invalid response format for EOD data: {response}")
            
            # For intraday data, use TPSeries endpoint
            else:
                # Add debug logging
                print(f"TPSeries Request payload:")
                print(f"Exchange: {exchange}")
                print(f"Token: {token}")
                print(f"Start timestamp: {start_ts}")
                print(f"End timestamp: {end_ts}")
                print(f"Interval: {self.timeframe_map[interval]}")
                
                payload = {
                    "uid": os.getenv('BROKER_API_KEY')[:-2],  # Required by Shoonya
                    "exch": exchange,
                    "token": token,
                    "st": str(start_ts),
                    "et": str(end_ts),
                    "intrv": self.timeframe_map[interval]
                }
                
                response = get_api_response("/NorenWClientTP/TPSeries", self.auth_token, payload=payload)
            
            # Add debug logging
            print(f"API Response: {response}")

            if not isinstance(response, list):
                if response.get('stat') == 'Not_Ok':
                    raise Exception(f"Error from Shoonya API: {response.get('emsg', 'Unknown error')}")
                raise Exception("Invalid response format from Shoonya API")
            
            # Convert response to DataFrame
            data = []
            for candle in response:
                if candle.get('stat') == 'Ok':
                    timestamp = datetime.strptime(candle['time'], '%d-%m-%Y %H:%M:%S').timestamp()
                    data.append({
                        'timestamp': int(timestamp),
                        'open': float(candle['into']),
                        'high': float(candle['inth']),
                        'low': float(candle['intl']),
                        'close': float(candle['intc']),
                        'volume': int(candle['intv'])
                    })
            
            df = pd.DataFrame(data)
            if df.empty:
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Sort by timestamp in ascending order
            df = df.sort_values('timestamp')
            return df
            
        except Exception as e:
            print(f"Error in get_history: {str(e)}")  # Add debug logging
            raise Exception(f"Error fetching historical data: {str(e)}")
