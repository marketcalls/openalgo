import http.client
import json
import os
import pandas as pd
from datetime import datetime, timedelta
from database.token_db import get_token, get_br_symbol, get_symbol

def get_api_response(endpoint, auth, method="POST", payload=None):
    """
    Common function to make API calls to Firstock
    """
    conn = http.client.HTTPSConnection("connect.thefirstock.com")
    
    api_key = os.getenv('BROKER_API_KEY')
    api_key = api_key[:-4]  # Remove last 4 characters for Firstock
    
    if payload is None:
        payload = {
            "jKey": auth,
            "userId": api_key
        }
    
    headers = {'Content-Type': 'application/json'}
    
    try:
        conn.request(method, f"/api/V4{endpoint}", json.dumps(payload), headers)
        res = conn.getresponse()
        data = res.read()
        return json.loads(data.decode("utf-8"))
    except Exception as e:
        print(f"Error in API call: {str(e)}")
        return {"status": "failed", "error": str(e)}
    finally:
        conn.close()

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
            '1h': '60',   # 1 hour
            '2h': '120',  # 2 hours
            '4h': '240',  # 4 hours
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
