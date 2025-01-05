import http.client
import json
import os
import pandas as pd
from datetime import datetime, timedelta
from database.token_db import get_token, get_br_symbol, get_symbol
import traceback

def get_api_response(endpoint, auth, method="POST", payload=None):
    """
    Common function to make API calls to Firstock
    """
    try:
        api_key = os.getenv('BROKER_API_KEY')
        api_key = api_key[:-4]  # Firstock specific requirement

        if payload is None:
            data = {
                "userId": api_key
            }
        else:
            data = payload
            data["userId"] = api_key

        # Debug print
        print(f"Endpoint: {endpoint}")
        print(f"Payload: {json.dumps(data, indent=2)}")

        conn = http.client.HTTPSConnection("connect.thefirstock.com")
        headers = {'Content-Type': 'application/json'}

        # Convert payload to JSON string
        payload_str = json.dumps(data)

        # Use the full endpoint path as provided
        conn.request(method, f"/api/V4{endpoint}", payload_str, headers)
        res = conn.getresponse()
        data = res.read()
        
        # Debug print
        response = json.loads(data.decode("utf-8"))
        print(f"Response: {json.dumps(response, indent=2)}")
        
        return response

    except Exception as e:
        print(f"API Error: {str(e)}")
        raise

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Firstock data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Firstock resolutions
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
            'D': 'DAY'    # Daily data
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
            
            payload = {
                "userId": os.getenv('BROKER_API_KEY')[:-4],
                "exchange": exchange,
                "tradingSymbol": br_symbol,
                "jKey": self.auth_token
            }
            
            response = get_api_response("/getQuote", self.auth_token, payload=payload)
            
            if response.get('status') != 'success':
                raise Exception(f"Error from Firstock API: {response.get('error', {}).get('message', 'Unknown error')}")
            
            quote_data = response.get('data', {})
            
            # Create the quote data without any wrapping - let the API handle the wrapping
            return {
                "ask": float(quote_data.get('bestSellPrice1', 0)),
                "bid": float(quote_data.get('bestBuyPrice1', 0)),
                "high": float(quote_data.get('dayHighPrice', 0)),
                "low": float(quote_data.get('dayLowPrice', 0)),
                "ltp": float(quote_data.get('lastTradedPrice', 0)),
                "open": float(quote_data.get('dayOpenPrice', 0)),
                "prev_close": float(quote_data.get('dayClosePrice', 0)),
                "volume": int(quote_data.get('volume', 0))
            }
            
        except Exception as e:
            print(f"Error fetching quotes: {str(e)}")
            return {"status": "error", "message": str(e)}

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
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            
            payload = {
                "userId": os.getenv('BROKER_API_KEY')[:-4],
                "exchange": exchange,
                "tradingSymbol": br_symbol,
                "jKey": self.auth_token
            }
            
            response = get_api_response("/getQuote", self.auth_token, payload=payload)
            
            if response.get('status') != 'success':
                raise Exception(f"Error from Firstock API: {response.get('error', {}).get('message', 'Unknown error')}")
            
            quote_data = response.get('data', {})
            
            # Format bids and asks data
            bids = []
            asks = []
            
            # Process top 5 bids and asks
            for i in range(1, 6):
                bids.append({
                    'price': float(quote_data.get(f'bestBuyPrice{i}', 0)),
                    'quantity': int(quote_data.get(f'bestBuyQuantity{i}', 0))
                })
                asks.append({
                    'price': float(quote_data.get(f'bestSellPrice{i}', 0)),
                    'quantity': int(quote_data.get(f'bestSellQuantity{i}', 0))
                })
            
            # Return just the data - let the API handle the wrapping
            return {
                'asks': asks,
                'bids': bids,
                'high': float(quote_data.get('dayHighPrice', 0)),
                'low': float(quote_data.get('dayLowPrice', 0)),
                'ltp': float(quote_data.get('lastTradedPrice', 0)),
                'ltq': int(quote_data.get('lastTradedQuantity', 0)),
                'oi': float(quote_data.get('openInterest', 0)),
                'open': float(quote_data.get('dayOpenPrice', 0)),
                'prev_close': float(quote_data.get('dayClosePrice', 0)),
                'totalbuyqty': int(quote_data.get('totalBuyQuantity', 0)),
                'totalsellqty': int(quote_data.get('totalSellQuantity', 0)),
                'volume': int(quote_data.get('volume', 0))
            }
            
        except Exception as e:
            print(f"Error fetching market depth: {str(e)}")
            return {"status": "error", "message": str(e)}

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

            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            
            # Convert dates to timestamps
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            start_ts = int(start_dt.timestamp())
            end_ts = int(end_dt.replace(hour=23, minute=59, second=59).timestamp())
            
            data = []
            
            # For daily data, handle differently
            if interval == 'D':
                # Format dates for API (use full day range)
                start_str = start_dt.strftime('%d/%m/%Y') + ' 00:00:00'
                end_str = end_dt.strftime('%d/%m/%Y') + ' 23:59:59'
                
                print(f"Getting daily data for {br_symbol} from {start_str} to {end_str}")
                
                payload = {
                    "userId": os.getenv('BROKER_API_KEY')[:-4],
                    "exchange": exchange,
                    "tradingSymbol": br_symbol,
                    "startTime": start_str,
                    "endTime": end_str,
                    "interval": self.timeframe_map[interval],
                    "jKey": self.auth_token
                }
                
                response = get_api_response("/timePriceSeries", self.auth_token, payload=payload)
                if response.get('status') == 'success':
                    for candle in response.get('data', []):
                        try:
                            # For daily data, time comes in DD-MMM-YYYY format
                            dt = datetime.strptime(candle.get('time', ''), '%d-%b-%Y')
                            # Set to market close time (15:30) for consistency
                            dt = dt.replace(hour=15, minute=30, second=0)
                            candle_ts = int(dt.timestamp())
                            
                            # Only include data within the requested range
                            if start_ts <= candle_ts <= end_ts:
                                data.append({
                                    'timestamp': candle_ts,
                                    'open': float(candle.get('into', 0)),
                                    'high': float(candle.get('inth', 0)),
                                    'low': float(candle.get('intl', 0)),
                                    'close': float(candle.get('intc', 0)),
                                    'volume': float(candle.get('intv', 0))  # Changed to float as volume comes as decimal
                                })
                        except (ValueError, TypeError) as e:
                            print(f"Error processing candle: {e}")
                            continue
            else:
                # For intraday data
                # Add market hours to timestamps (9:15 AM to 3:30 PM IST)
                start_time = start_dt.replace(hour=9, minute=15, second=0)
                end_time = end_dt.replace(hour=15, minute=30, second=0)
                
                # Format for API
                start_str = start_time.strftime('%d/%m/%Y %H:%M:%S')
                end_str = end_time.strftime('%d/%m/%Y %H:%M:%S')
                
                print(f"Getting intraday data from {start_str} to {end_str}")
                
                payload = {
                    "userId": os.getenv('BROKER_API_KEY')[:-4],
                    "exchange": exchange,
                    "tradingSymbol": br_symbol,
                    "startTime": start_str,
                    "endTime": end_str,
                    "interval": self.timeframe_map[interval],
                    "jKey": self.auth_token
                }
                
                response = get_api_response("/timePriceSeries", self.auth_token, payload=payload)
                if response.get('status') == 'success':
                    for candle in response.get('data', []):
                        try:
                            # Use ssboe (timestamp) if available, otherwise parse time
                            timestamp = int(candle.get('ssboe', 0))
                            if not timestamp and 'time' in candle:
                                dt = datetime.strptime(candle['time'], '%d-%m-%Y %H:%M:%S')
                                timestamp = int(dt.timestamp())
                            
                            if not timestamp:
                                continue
                                
                            data.append({
                                'timestamp': timestamp,
                                'open': float(candle.get('into', 0)),
                                'high': float(candle.get('inth', 0)),
                                'low': float(candle.get('intl', 0)),
                                'close': float(candle.get('intc', 0)),
                                'volume': int(candle.get('intv', 0))
                            })
                        except (ValueError, TypeError) as e:
                            print(f"Error processing candle: {e}")
                            continue
            
            if not data:
                print("No data available")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Convert to DataFrame and sort
            df = pd.DataFrame(data)
            df = df.sort_values('timestamp')
            
            # Debug print
            print(f"Data shape: {df.shape}")
            print(f"Date range: {datetime.fromtimestamp(df['timestamp'].min())} to {datetime.fromtimestamp(df['timestamp'].max())}")
            
            return df
            
        except Exception as e:
            print(f"Error in get_history: {str(e)}")
            print(f"Traceback: {traceback.format_exc()}")
            raise Exception(f"Error fetching historical data: {str(e)}")
