import http.client
import json
import os
from database.token_db import get_br_symbol, get_token, get_oa_symbol
from broker.fivepaisa.mapping.transform_data import map_exchange, map_exchange_type

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
            dict: Market depth data with bids, asks, and other market data
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
                return None

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
                return None

            market_depth = depth_response['body'].get('MarketDepthData', [])
            
            # Initialize empty bids and asks arrays
            bids = [{"price": 0, "quantity": 0} for _ in range(5)]
            asks = [{"price": 0, "quantity": 0} for _ in range(5)]

            # Process market depth data
            buy_orders = [order for order in market_depth if order['BbBuySellFlag'] == 66]  # 66 = Buy
            sell_orders = [order for order in market_depth if order['BbBuySellFlag'] == 83]  # 83 = Sell

            # Sort orders by price (highest buy, lowest sell)
            buy_orders.sort(key=lambda x: float(x['Price']), reverse=True)
            sell_orders.sort(key=lambda x: float(x['Price']))

            # Fill bids and asks arrays
            for i in range(min(len(buy_orders), 5)):
                bids[i] = {
                    "price": float(buy_orders[i]['Price']),
                    "quantity": int(buy_orders[i]['Quantity'])
                }

            for i in range(min(len(sell_orders), 5)):
                asks[i] = {
                    "price": float(sell_orders[i]['Price']),
                    "quantity": int(sell_orders[i]['Quantity'])
                }

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
            print(f"Error in get_depth: {str(e)}")
            return None

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
