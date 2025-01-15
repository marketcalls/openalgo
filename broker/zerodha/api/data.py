import http.client
import json
import os
import urllib.parse
from database.token_db import get_br_symbol, get_oa_symbol
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_api_response(endpoint, auth, method="GET", payload=''):
    AUTH_TOKEN = auth
    conn = http.client.HTTPSConnection("api.kite.trade")
    headers = {
        'X-Kite-Version': '3',
        'Authorization': f'token {AUTH_TOKEN}',
        'Content-Type': 'application/json'
    }

    try:
        conn.request(method, endpoint, payload, headers)
        res = conn.getresponse()
        data = res.read()
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        logger.error(f"API request failed: {str(e)}")
        raise

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Zerodha data handler with authentication token"""
        self.auth_token = auth_token

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
            logger.info(f"Fetching quotes for {exchange}:{br_symbol}")
            
            # URL encode the symbol to handle special characters
            encoded_symbol = urllib.parse.quote(f"{exchange}:{br_symbol}")
            
            response = get_api_response(f"/quote?i={encoded_symbol}", self.auth_token)
            
            if not response or response.get('status') != 'success':
                raise Exception(f"Error from Zerodha API: {response.get('message', 'Unknown error')}")
            
            # Get quote data from response
            quote = response.get('data', {}).get(f"{exchange}:{br_symbol}", {})
            if not quote:
                raise Exception("No quote data found")
            
            # Return quote data in standardized format
            return {
                'ask': quote.get('depth', {}).get('sell', [{}])[0].get('price', 0),
                'bid': quote.get('depth', {}).get('buy', [{}])[0].get('price', 0),
                'high': quote.get('ohlc', {}).get('high', 0),
                'low': quote.get('ohlc', {}).get('low', 0),
                'ltp': quote.get('last_price', 0),
                'open': quote.get('ohlc', {}).get('open', 0),
                'prev_close': quote.get('ohlc', {}).get('close', 0),
                'volume': quote.get('volume', 0)
            }
            
        except Exception as e:
            logger.error(f"Error fetching quotes: {str(e)}")
            raise Exception(f"Error fetching quotes: {str(e)}")

    def get_market_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data
        """
        try:
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            logger.info(f"Fetching market depth for {exchange}:{br_symbol}")
            
            # URL encode the symbol to handle special characters
            encoded_symbol = urllib.parse.quote(f"{exchange}:{br_symbol}")
            
            response = get_api_response(f"/quote?i={encoded_symbol}", self.auth_token)
            
            if not response or response.get('status') != 'success':
                raise Exception(f"Error from Zerodha API: {response.get('message', 'Unknown error')}")
            
            # Get quote data from response
            quote = response.get('data', {}).get(f"{exchange}:{br_symbol}", {})
            if not quote:
                raise Exception("No market depth data found")
            
            depth = quote.get('depth', {})
            
            # Format asks and bids data
            asks = []
            bids = []
            
            # Process sell orders (asks)
            sell_orders = depth.get('sell', [])
            for i in range(5):
                if i < len(sell_orders):
                    asks.append({
                        'price': sell_orders[i].get('price', 0),
                        'quantity': sell_orders[i].get('quantity', 0)
                    })
                else:
                    asks.append({'price': 0, 'quantity': 0})
                    
            # Process buy orders (bids)
            buy_orders = depth.get('buy', [])
            for i in range(5):
                if i < len(buy_orders):
                    bids.append({
                        'price': buy_orders[i].get('price', 0),
                        'quantity': buy_orders[i].get('quantity', 0)
                    })
                else:
                    bids.append({'price': 0, 'quantity': 0})
            
            # Return market depth data in standardized format
            return {
                'asks': asks,
                'bids': bids,
                'high': quote.get('ohlc', {}).get('high', 0),
                'low': quote.get('ohlc', {}).get('low', 0),
                'ltp': quote.get('last_price', 0),
                'ltq': quote.get('last_quantity', 0),
                'oi': quote.get('oi', 0),
                'open': quote.get('ohlc', {}).get('open', 0),
                'prev_close': quote.get('ohlc', {}).get('close', 0),
                'totalbuyqty': sum(order.get('quantity', 0) for order in buy_orders),
                'totalsellqty': sum(order.get('quantity', 0) for order in sell_orders),
                'volume': quote.get('volume', 0)
            }
            
        except Exception as e:
            logger.error(f"Error fetching market depth: {str(e)}")
            raise Exception(f"Error fetching market depth: {str(e)}")

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Alias for get_market_depth to maintain compatibility with common API"""
        return self.get_market_depth(symbol, exchange)
