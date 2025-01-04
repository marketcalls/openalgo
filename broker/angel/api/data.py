import http.client
import json
import os
import pandas as pd
from datetime import datetime
import urllib.parse
from database.token_db import get_br_symbol, get_token, get_oa_symbol

def get_api_response(endpoint, auth, method="GET", payload=''):
    """Helper function to make API calls to Angel One"""
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_KEY')

    conn = http.client.HTTPSConnection("apiconnect.angelone.in")
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

    conn.request(method, endpoint, payload, headers)
    res = conn.getresponse()
    data = res.read()
    return json.loads(data.decode("utf-8"))

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
            
            # Check for unsupported timeframes
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(f"Timeframe '{interval}' is not supported by Angel. Supported timeframes are: {', '.join(supported)}")
            
            # Convert dates to required format (YYYY-MM-DD HH:mm)
            from_date = datetime.strptime(start_date, '%Y-%m-%d')
            to_date = datetime.strptime(end_date, '%Y-%m-%d')
            
            # Set time to market hours (9:15 AM to 3:30 PM)
            from_date = from_date.replace(hour=9, minute=15)
            to_date = to_date.replace(hour=15, minute=30)
            
            # Prepare payload for historical data API
            payload = {
                "exchange": exchange,
                "symboltoken": token,
                "interval": self.timeframe_map[interval],
                "fromdate": from_date.strftime('%Y-%m-%d %H:%M'),
                "todate": to_date.strftime('%Y-%m-%d %H:%M')
            }
            print(f"Debug - API Payload: {payload}")
            
            response = get_api_response("/rest/secure/angelbroking/historical/v1/getCandleData",
                                      self.auth_token,
                                      "POST",
                                      payload)
            print(f"Debug - API Response: {response}")
            
            if not response.get('status'):
                raise Exception(f"Error from Angel API: {response.get('message', 'Unknown error')}")
            
            # Extract candle data and create DataFrame
            data = response.get('data', [])
            if not data:
                print("Debug - No data received from API")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            print(f"Debug - Received {len(data)} candles")
            
            # Convert data to DataFrame
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Convert timestamp to datetime then to Unix epoch
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df['timestamp'] = df['timestamp'].astype('int64') // 10**9  # Convert to Unix epoch
            
            # Ensure numeric columns and proper order
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric)
            
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
