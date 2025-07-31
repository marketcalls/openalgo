import json
import os
import urllib.parse
import httpx
from database.token_db import get_br_symbol, get_token
from broker.paytm.database.master_contract_db import SymToken, db_session
import pandas as pd
from datetime import datetime, timedelta
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def get_api_response(endpoint, auth, method="GET", payload=''):
    AUTH_TOKEN = auth
    base_url = "https://developer.paytmmoney.com"
    headers = {
        'x-jwt-token': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    try:
        # Log the complete request details for Postman
        logger.debug("=== API Request Details ===")
        logger.debug(f"URL: {base_url}{endpoint}")
        logger.debug(f"Method: {method}")
        logger.debug(f"Headers: {json.dumps(headers, indent=2)}")
        if payload:
            logger.debug(f"Payload: {payload}")

        client = get_httpx_client()
        # Use a longer timeout for Paytm API requests
        timeout = httpx.Timeout(60.0, connect=30.0)
        if method == "GET":
            response = client.get(f"{base_url}{endpoint}", headers=headers, timeout=timeout)
        else:
            response = client.post(f"{base_url}{endpoint}", headers=headers, content=payload, timeout=timeout)

        # Log the complete response
        logger.debug("=== API Response Details ===")
        logger.debug(f"Status Code: {response.status_code}")
        logger.debug(f"Response Headers: {dict(response.headers)}")
        response_data = response.json()
        logger.debug(f"Response Body: {json.dumps(response_data, indent=2)}")

        return response_data
    except Exception as e:
        logger.exception(f"API request failed for endpoint {endpoint}: {e}")
        raise

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Paytm data handler with authentication token"""
        self.auth_token = auth_token
        
        # PAYTM does not support historical data API
        # Empty timeframe map since historical data is not supported
        self.timeframe_map = {}
        
        # Market timing configuration for different exchanges
        self.market_timings = {
            'NSE': {
                'start': '09:15:00',
                'end': '15:30:00'
            },
            'BSE': {
                'start': '09:15:00',
                'end': '15:30:00'
            },
            'NFO': {
                'start': '09:15:00',
                'end': '15:30:00'
            },
            'CDS': {
                'start': '09:00:00',
                'end': '17:00:00'
            },
            'BCD': {
                'start': '09:00:00',
                'end': '17:00:00'
            }
        }
        
        # Default market timings if exchange not found
        self.default_market_timings = {
            'start': '09:15:00',
            'end': '15:29:59'
        }

    def get_market_timings(self, exchange: str) -> dict:
        """Get market start and end times for given exchange"""
        return self.market_timings.get(exchange, self.default_market_timings)

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Quote data with required fields
        """
        try:
            # Convert symbol to broker format
            token = get_token(symbol, exchange)
            logger.debug(f"Fetching quotes for {exchange}:{token}")

            br_symbol = get_br_symbol(symbol, exchange)
            # Determine opt_type based on symbol format
            parts = br_symbol.split('-')
            if len(parts) > 2:
                if parts[-1] in ['CE', 'PE']:
                    opt_type = 'OPTION'
                elif 'FUT' in parts[-1]:
                    opt_type = 'FUTURE'
                else:
                    opt_type = 'EQUITY'
            else:
                opt_type = 'EQUITY'
            
            # URL encode the symbol to handle special characters
            # Paytm expects the symbol to be in the format "exchange:symbol" E,g: NSE:335:EQUITY
            # 	INDEX, EQUITY, ETF, FUTURE, OPTION
            # Before the encoded_symbol line, add:
            if exchange == 'NFO' or exchange == 'NSE_INDEX':
                request_exchange = 'NSE'
            elif exchange == 'BFO' or exchange == 'BSE_INDEX':
                request_exchange = 'BSE'
            else:
                request_exchange = exchange
            encoded_symbol = urllib.parse.quote(f"{request_exchange}:{token}:{opt_type}")
            
            response = get_api_response(f"/data/v1/price/live?mode=QUOTE&pref={encoded_symbol}", self.auth_token)
            
            if not response or not response.get('data', []):
                error_msg = f"Error from Paytm API: {response.get('message', 'Unknown error')}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            
            # Return quote data
            quote = response.get('data', [])[0] if response.get('data') else {}
            if not quote:
                error_msg = f"No quote data found for {symbol}"
                logger.error(error_msg)
                raise Exception(error_msg)

            return {
                'ask': 0,  # Not available in new format
                'bid': 0,  # Not available in new format
                'high': quote.get('ohlc', {}).get('high', 0),
                'low': quote.get('ohlc', {}).get('low', 0),
                'ltp': quote.get('last_price', 0),
                'open': quote.get('ohlc', {}).get('open', 0),
                'prev_close': quote.get('ohlc', {}).get('close', 0),
                'volume': quote.get('volume_traded', 0)
            }
            
        except Exception as e:
            logger.exception(f"Error fetching quotes for {symbol}: {e}")
            raise


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
            token = get_token(symbol, exchange)
            logger.debug(f"Fetching market depth for {exchange}:{token}")

            br_symbol = get_br_symbol(symbol, exchange)
            # Determine opt_type based on symbol format
            parts = br_symbol.split('-')
            if len(parts) > 2:
                if parts[-1] in ['CE', 'PE']:
                    opt_type = 'OPTION'
                elif 'FUT' in parts[-1]:
                    opt_type = 'FUTURE'
                else:
                    opt_type = 'EQUITY'
            else:
                opt_type = 'EQUITY'
            
            # URL encode the symbol to handle special characters
            # Paytm expects the symbol to be in the format "exchange:symbol" E,g: NSE:335:EQUITY
            # 	INDEX, EQUITY, ETF, FUTURE, OPTION
            # Before the encoded_symbol line, add:
            if exchange == 'NFO' or exchange == 'NSE_INDEX':
                request_exchange = 'NSE'
            elif exchange == 'BFO' or exchange == 'BSE_INDEX':
                request_exchange = 'BSE'
            else:
                request_exchange = exchange
            encoded_symbol = urllib.parse.quote(f"{request_exchange}:{token}:{opt_type}")
            
            response = get_api_response(f"/data/v1/price/live?mode=FULL&pref={encoded_symbol}", self.auth_token)
            
            if not response or not response.get('data', []):
                error_msg = f"Error from Paytm API: {response.get('message', 'Unknown error')}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            
            # Return quote data
            quote = response.get('data', [])[0] if response.get('data') else {}
            if not quote:
                error_msg = f"No market depth data found for {symbol}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
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
            
            # Return market depth data
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
            logger.exception(f"Error fetching market depth for {symbol}: {e}")
            raise

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Alias for get_market_depth to maintain compatibility with common API"""
        return self.get_market_depth(symbol, exchange)

    def get_history(self, symbol: str, exchange: str, timeframe: str, from_date: str, to_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol and timeframe
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            timeframe: Timeframe (e.g., 1m, 5m, 15m, 60m, D)
            from_date: Start date in format YYYY-MM-DD
            to_date: End date in format YYYY-MM-DD
        Returns:
            pd.DataFrame: Historical data with OHLCV
        """
        raise NotImplementedError("Paytm does not support historical data API")

    def get_intervals(self) -> list:
        """Get available intervals/timeframes for historical data
        
        Returns:
            list: List of available intervals
        """
        raise NotImplementedError("Paytm does not support historical data API")
