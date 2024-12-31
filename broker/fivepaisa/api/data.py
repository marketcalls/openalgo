import http.client
import json
from datetime import datetime
import os
from database.token_db import get_br_symbol, get_token, get_oa_symbol
from broker.fivepaisa.mapping.transform_data import map_exchange, map_exchange_type
import traceback
import pandas as pd

# Retrieve the BROKER_API_KEY environment variable
broker_api_key = os.getenv('BROKER_API_KEY')
api_key, user_id, client_id = broker_api_key.split(':::')

def get_api_response(endpoint, auth, method="GET", payload=''):
    """Generic function to make API calls to 5Paisa"""
    AUTH_TOKEN = auth
    conn = http.client.HTTPSConnection("Openapi.5paisa.com")
    headers = {
        'Authorization': f'bearer {AUTH_TOKEN}',
        'Content-Type': 'application/json'
    }
    conn.request(method, endpoint, payload, headers)
    res = conn.getresponse()
    data = res.read()
    return json.loads(data.decode("utf-8"))

class BrokerData:
    def __init__(self, auth_token):
        """Initialize 5Paisa data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to 5Paisa resolutions
        self.timeframe_map = {
            # Minutes
            '1m': '1', '3m': '3', '5m': '5',
            '10m': '10', '15m': '15', '30m': '30',
            # Hours
            '1h': '60',
            # Daily
            'D': '1D'
        }

    def get_market_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for a given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data
        """
        try:
            # Get token from symbol
            token = get_token(symbol, exchange)
            br_symbol = get_br_symbol(symbol, exchange)

            # Prepare request payload
            json_data = {
                "head": {
                    "key": api_key
                },
                "body": {
                    "ClientCode": client_id,
                    "Exchange": map_exchange(exchange),
                    "ExchangeType": map_exchange_type(exchange),
                    "ScripCode": token,
                    "ScripData": br_symbol if token == "0" else ""
                }
            }

            # Make API request
            response = get_api_response(
                "/VendorsAPI/Service1.svc/V2/MarketDepth",
                self.auth_token,
                method="POST",
                payload=json.dumps(json_data)
            )

            if response['head']['statusDescription'] != 'Success':
                print(f"Market Depth Error: {response['head']['statusDescription']}")
                return None

            depth_data = response['body']
            if not depth_data or 'MarketDepthData' not in depth_data:
                print("No depth data in response")
                return None

            # Get best bid and ask
            bid = ask = 0
            market_depth = depth_data['MarketDepthData']
            
            # BbBuySellFlag: 66 for Buy, 83 for Sell
            buy_orders = [order for order in market_depth if order['BbBuySellFlag'] == 66]
            sell_orders = [order for order in market_depth if order['BbBuySellFlag'] == 83]
            
            if buy_orders:
                # Get highest buy price
                bid = max(float(order['Price']) for order in buy_orders)
            if sell_orders:
                # Get lowest sell price
                ask = min(float(order['Price']) for order in sell_orders)
            
            print(f"Extracted Bid: {bid}, Ask: {ask}")
            return {'bid': bid, 'ask': ask}

        except Exception as e:
            print(f"Error fetching market depth: {str(e)}")
            print(f"Exception type: {type(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            return None

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
            # Get token from symbol
            token = get_token(symbol, exchange)
            br_symbol = get_br_symbol(symbol, exchange)

            # Get market snapshot for overall data
            snapshot_data = {
                "head": {
                    "key": api_key
                },
                "body": {
                    "ClientCode": client_id,
                    "Data": [
                        {
                            "Exchange": map_exchange(exchange),
                            "ExchangeType": map_exchange_type(exchange),
                            "ScripCode": token,
                            "ScripData": br_symbol if token == "0" else ""
                        }
                    ]
                }
            }

            snapshot_response = get_api_response(
                "/VendorsAPI/Service1.svc/MarketSnapshot",
                self.auth_token,
                method="POST",
                payload=json.dumps(snapshot_data)
            )

            if snapshot_response['head']['statusDescription'] != 'Success':
                raise Exception(f"Error from 5Paisa API: {snapshot_response['head']['statusDescription']}")

            quote_data = snapshot_response['body']['Data'][0]

            # Get market depth data
            depth_data = {
                "head": {
                    "key": api_key
                },
                "body": {
                    "ClientCode": client_id,
                    "Exchange": map_exchange(exchange),
                    "ExchangeType": map_exchange_type(exchange),
                    "ScripCode": token,
                    "ScripData": br_symbol if token == "0" else ""
                }
            }

            depth_response = get_api_response(
                "/VendorsAPI/Service1.svc/V2/MarketDepth",
                self.auth_token,
                method="POST",
                payload=json.dumps(depth_data)
            )

            if depth_response['head']['statusDescription'] != 'Success':
                raise Exception(f"Error from 5Paisa API: {depth_response['head']['statusDescription']}")

            market_depth = depth_response['body'].get('MarketDepthData', [])
            
            # Initialize empty bids and asks arrays
            empty_entry = {"price": 0, "quantity": 0}
            bids = []
            asks = []

            # Process market depth data
            buy_orders = [order for order in market_depth if order['BbBuySellFlag'] == 66]  # 66 = Buy
            sell_orders = [order for order in market_depth if order['BbBuySellFlag'] == 83]  # 83 = Sell

            # Sort orders by price (highest buy, lowest sell)
            buy_orders.sort(key=lambda x: float(x['Price']), reverse=True)
            sell_orders.sort(key=lambda x: float(x['Price']))

            # Fill bids and asks arrays
            for order in buy_orders[:5]:
                bids.append({
                    "price": float(order['Price']),
                    "quantity": int(order['Quantity'])
                })

            for order in sell_orders[:5]:
                asks.append({
                    "price": float(order['Price']),
                    "quantity": int(order['Quantity'])
                })

            # Pad with empty entries if needed
            while len(bids) < 5:
                bids.append(empty_entry)
            while len(asks) < 5:
                asks.append(empty_entry)

            # Calculate total buy/sell quantities
            total_buy_qty = sum(int(order['Quantity']) for order in buy_orders)
            total_sell_qty = sum(int(order['Quantity']) for order in sell_orders)

            # Return standardized format
            return {
                "asks": asks,
                "bids": bids,
                "high": float(quote_data.get('High', 0)),
                "low": float(quote_data.get('Low', 0)),
                "ltp": float(quote_data.get('LastTradedPrice', 0)),
                "ltq": int(quote_data.get('LastTradedQty', 0)),
                "oi": int(quote_data.get('OpenInterest', 0)),
                "open": float(quote_data.get('Open', 0)),
                "prev_close": float(quote_data.get('PClose', 0)),
                "totalbuyqty": total_buy_qty,
                "totalsellqty": total_sell_qty,
                "volume": int(quote_data.get('Volume', 0))
            }

        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Quote data with bid, ask, ltp, open, high, low, prev_close, volume
        """
        try:
            # Get token from symbol
            token = get_token(symbol, exchange)
            br_symbol = get_br_symbol(symbol, exchange)

            # Prepare request payload
            json_data = {
                "head": {
                    "key": api_key
                },
                "body": {
                    "ClientCode": client_id,
                    "Data": [
                        {
                            "Exchange": map_exchange(exchange),
                            "ExchangeType": map_exchange_type(exchange),
                            "ScripCode": token,
                            "ScripData": br_symbol if token == "0" else ""
                        }
                    ]
                }
            }

            # Make API request for market snapshot
            response = get_api_response(
                "/VendorsAPI/Service1.svc/MarketSnapshot",
                self.auth_token,
                method="POST",
                payload=json.dumps(json_data)
            )

            # Check for successful response
            if response['head']['statusDescription'] != 'Success':
                return None

            # Extract quote data
            quote_data = response['body']['Data'][0]
            
            # Get bid/ask from market depth
            depth_data = self.get_market_depth(symbol, exchange)
            
            # Get previous close from PClose field
            prev_close = float(quote_data.get('PClose', 0))
            if prev_close == 0:  # Fallback options if PClose is not available
                prev_close = float(quote_data.get('PreviousClose', 0))
                if prev_close == 0:
                    prev_close = float(quote_data.get('Close', 0))
            
            # Return just the data without status
            return {
                'ask': depth_data['ask'] if depth_data else 0,
                'bid': depth_data['bid'] if depth_data else 0,
                'high': float(quote_data.get('High', 0)),
                'low': float(quote_data.get('Low', 0)),
                'ltp': float(quote_data.get('LastTradedPrice', 0)),
                'open': float(quote_data.get('Open', 0)),
                'prev_close': prev_close,
                'volume': int(quote_data.get('Volume', 0))
            }

        except Exception as e:
            print(f"Error in get_quotes: {str(e)}")
            return None

    def map_interval(self, interval: str) -> str:
        """Map openalgo interval to 5paisa interval"""
        interval_map = {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "1d": "1d"
        }
        return interval_map.get(interval, "1d")

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical candle data
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Time interval (e.g., 1m, 5m, 15m, 30m, 1h, 1d)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: DataFrame with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Get token from symbol
            token = get_token(symbol, exchange)
            
            # Map interval
            fivepaisa_interval = self.map_interval(interval)
            if not fivepaisa_interval:
                supported = ["1m", "5m", "15m", "30m", "1h", "1d"]
                raise Exception(f"Unsupported interval '{interval}'. Supported intervals: {', '.join(supported)}")
            
            # Prepare URL for historical data
            url = f"/V2/historical/{map_exchange(exchange)}/{map_exchange_type(exchange)}/{token}/{fivepaisa_interval}"
            url += f"?from={start_date}&end={end_date}"

            print(f"Historical URL: {url}")  # Debug log

            # Make API request
            response = get_api_response(
                url,
                self.auth_token,
                method="GET"
            )

            print(f"Historical Response: {json.dumps(response, indent=2)}")  # Debug log

            if response.get('status') != 'success':
                error_msg = response.get('message', 'Unknown error')
                raise Exception(f"Error from 5Paisa API: {error_msg}")

            candles = response.get('data', {}).get('candles', [])
            if not candles:
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            print(f"Raw Candles: {json.dumps(candles[:2], indent=2)}")  # Debug log first 2 candles
            
            # Transform candles to required format
            transformed_candles = []
            for candle in candles:
                try:
                    # Parse the date string and convert to Indian timezone
                    dt = datetime.strptime(candle[0], "%Y-%m-%dT%H:%M:%S")
                    # Convert to actual date (2023) instead of future date
                    year = dt.year - 1
                    dt = dt.replace(year=year)
                    timestamp = int(dt.timestamp())
                    
                    # Create candle with exact field order matching expected response
                    transformed_candle = {
                        "close": float(candle[4]),
                        "high": float(candle[2]),
                        "low": float(candle[3]),
                        "open": float(candle[1]),
                        "timestamp": timestamp,
                        "volume": int(candle[5])
                    }
                    transformed_candles.append(transformed_candle)
                except Exception as e:
                    print(f"Error transforming candle {candle}: {str(e)}")  # Debug log
                    continue

            if not transformed_candles:
                raise ValueError("Failed to transform any candles")

            print(f"Transformed Candles: {json.dumps(transformed_candles[:2], indent=2)}")  # Debug log first 2 candles
            
            # Convert to DataFrame and return
            df = pd.DataFrame(transformed_candles)
            # Reorder columns to match expected format
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            return df

        except Exception as e:
            print(f"Error in get_history: {str(e)}\nTraceback: {traceback.format_exc()}")  # Debug log
            raise

    def get_supported_intervals(self) -> list:
        """Get list of supported intervals"""
        return ["1m", "5m", "15m", "30m", "1h", "1d"]
