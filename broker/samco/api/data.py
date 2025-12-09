import httpx
import json
import os
import pandas as pd
import time
from datetime import datetime, timedelta
from database.token_db import get_br_symbol, get_token, get_oa_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Samco API base URL
BASE_URL = "https://tradeapi.samco.in"


def safe_float(value, default=0):
    """Convert string to float, handling commas and empty values"""
    if value is None or value == '':
        return default
    try:
        if isinstance(value, str):
            value = value.replace(',', '')
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value, default=0):
    """Convert string to int, handling commas and empty values"""
    if value is None or value == '':
        return default
    try:
        if isinstance(value, str):
            value = value.replace(',', '')
        return int(float(value))
    except (ValueError, TypeError):
        return default


def get_api_response(endpoint, auth, method="GET", payload=None):
    """Helper function to make API calls to Samco"""
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'x-session-token': auth
    }

    url = f"{BASE_URL}{endpoint}"

    try:
        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, headers=headers, json=payload)
        else:
            response = client.request(method, url, headers=headers, json=payload)

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        if response.status_code == 403:
            logger.debug(f"Debug - API returned 403 Forbidden. Headers: {headers}")
            logger.debug(f"Debug - Response text: {response.text}")
            raise Exception("Authentication failed. Please check your session token.")

        return json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Debug - Failed to parse response. Status code: {response.status_code}")
        logger.debug(f"Debug - Response text: {response.text}")
        raise Exception(f"Failed to parse API response (status {response.status_code})")


class BrokerData:
    def __init__(self, auth_token):
        """Initialize Samco data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Samco resolutions
        self.timeframe_map = {
            # Minutes
            '1m': '1',
            '5m': '5',
            '10m': '10',
            '15m': '15',
            '30m': '30',
            # Hours
            '1h': '60',
            # Daily
            'D': 'DAY'
        }

    def _get_index_name(self, symbol: str) -> str:
        """Map OpenAlgo index symbols to Samco index names"""
        index_map = {
            'NIFTY': 'Nifty 50',
            'BANKNIFTY': 'Nifty Bank',
            'NIFTY 50': 'Nifty 50',
            'NIFTY BANK': 'Nifty Bank',
            'SENSEX': 'SENSEX',
            'BANKEX': 'BANKEX',
            'FINNIFTY': 'Nifty Fin Service',
            'MIDCPNIFTY': 'NIFTY MID SELECT'
        }
        return index_map.get(symbol.upper(), symbol)

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
            # Handle index quotes separately
            if exchange in ['NSE_INDEX', 'BSE_INDEX']:
                return self._get_index_quotes(symbol, exchange)

            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)

            # Build query parameters
            params = f"symbolName={br_symbol}"
            if exchange and exchange != 'NSE':
                params += f"&exchange={exchange}"

            response = get_api_response(f"/quote/getQuote?{params}",
                                       self.auth_token,
                                       "GET")

            if response.get('status') != 'Success':
                raise Exception(f"Error from Samco API: {response.get('statusMessage', 'Unknown error')}")

            # Extract quote data from response
            quote = response.get('quoteDetails', {})
            if not quote:
                raise Exception("No quote data received")

            # Parse best bids and asks
            bids = quote.get('bestBids', [])
            asks = quote.get('bestAsks', [])

            # Return quote in common format
            return {
                'bid': safe_float(bids[0].get('price')) if bids else 0,
                'ask': safe_float(asks[0].get('price')) if asks else 0,
                'open': safe_float(quote.get('openValue')),
                'high': safe_float(quote.get('highValue')),
                'low': safe_float(quote.get('lowValue')),
                'ltp': safe_float(quote.get('lastTradedPrice')),
                'prev_close': safe_float(quote.get('previousClose')),
                'volume': safe_int(quote.get('totalTradedVolume')),
                'oi': safe_int(quote.get('openInterest'))
            }

        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}")

    def _get_index_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for index symbols
        Args:
            symbol: Index symbol (e.g., NIFTY, BANKNIFTY, SENSEX)
            exchange: Exchange (NSE_INDEX or BSE_INDEX)
        Returns:
            dict: Quote data with required fields
        """
        try:
            # Map to Samco index name
            index_name = self._get_index_name(symbol)

            response = get_api_response(f"/quote/indexQuote?indexName={index_name}",
                                       self.auth_token,
                                       "GET")

            if response.get('status') != 'Success':
                raise Exception(f"Error from Samco API: {response.get('statusMessage', 'Unknown error')}")

            # Extract index details
            index_details = response.get('indexDetails', [])
            if not index_details:
                raise Exception("No index data received")

            quote = index_details[0]

            # Return quote in common format (indices don't have bid/ask)
            return {
                'bid': 0,
                'ask': 0,
                'open': safe_float(quote.get('openValue')),
                'high': safe_float(quote.get('highValue')),
                'low': safe_float(quote.get('lowValue')),
                'ltp': safe_float(quote.get('spotPrice')),
                'prev_close': safe_float(quote.get('closeValue')),
                'volume': safe_int(quote.get('totalTradedVolume')),
                'oi': 0
            }

        except Exception as e:
            raise Exception(f"Error fetching index quotes: {str(e)}")

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
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)

            # Build query parameters
            params = f"symbolName={br_symbol}"
            if exchange and exchange != 'NSE':
                params += f"&exchange={exchange}"

            response = get_api_response(f"/quote/getQuote?{params}",
                                       self.auth_token,
                                       "GET")

            if response.get('status') != 'Success':
                raise Exception(f"Error from Samco API: {response.get('statusMessage', 'Unknown error')}")

            # Extract quote data
            quote = response.get('quoteDetails', {})
            if not quote:
                raise Exception("No depth data received")

            # Format bids and asks with exactly 5 entries each
            bids = []
            asks = []

            # Process buy orders (top 5)
            buy_orders = quote.get('bestBids', [])
            for i in range(5):
                if i < len(buy_orders):
                    bid = buy_orders[i]
                    bids.append({
                        'price': safe_float(bid.get('price')),
                        'quantity': safe_int(bid.get('quantity'))
                    })
                else:
                    bids.append({'price': 0, 'quantity': 0})

            # Process sell orders (top 5)
            sell_orders = quote.get('bestAsks', [])
            for i in range(5):
                if i < len(sell_orders):
                    ask = sell_orders[i]
                    asks.append({
                        'price': safe_float(ask.get('price')),
                        'quantity': safe_int(ask.get('quantity'))
                    })
                else:
                    asks.append({'price': 0, 'quantity': 0})

            # Return depth data in common format matching REST API response
            return {
                'bids': bids,
                'asks': asks,
                'high': safe_float(quote.get('highValue')),
                'low': safe_float(quote.get('lowValue')),
                'ltp': safe_float(quote.get('lastTradedPrice')),
                'ltq': safe_int(quote.get('lastTradedQuantity')),
                'open': safe_float(quote.get('openValue')),
                'prev_close': safe_float(quote.get('previousClose')),
                'volume': safe_int(quote.get('totalTradedVolume')),
                'oi': safe_int(quote.get('openInterest')),
                'totalbuyqty': safe_int(quote.get('totalBuyQuantity')),
                'totalsellqty': safe_int(quote.get('totalSellQuantity'))
            }

        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")

    def get_history(self, symbol: str, exchange: str, interval: str,
                   start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
            interval: Candle interval (1m, 5m, 10m, 15m, 30m, 1h, D)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume, oi]
        """
        # Placeholder - historical data endpoint to be implemented based on Samco docs
        raise NotImplementedError("Historical data not yet implemented for Samco broker")
