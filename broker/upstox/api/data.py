import json
import os
import httpx
from utils.httpx_client import get_httpx_client
from database.token_db import get_token, get_br_symbol, get_oa_symbol
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
import numpy as np
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="GET", payload=''):
    """Common function to make API calls to Upstox v3 using httpx with connection pooling"""
    AUTH_TOKEN = auth
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'Authorization': f'Bearer {AUTH_TOKEN}',
        'Accept': 'application/json'
    }
    
    # Use v3 API base URL
    url = f"https://api.upstox.com/v3{endpoint}"
    logger.debug(f"Making {method} request to Upstox v3 API: {url}")
    
    if method == "GET":
        response = client.get(url, headers=headers)
    elif method == "POST":
        response = client.post(url, headers=headers, content=payload)
    elif method == "PUT":
        response = client.put(url, headers=headers, content=payload)
    elif method == "DELETE":
        response = client.delete(url, headers=headers)
    
    # Add status attribute for compatibility with existing code that expects http.client response
    response.status = response.status_code
    
    return response.json()

class BrokerData:
    def __init__(self, auth_token):
        """Initialize with auth token"""
        self.auth_token = auth_token
        
        # Map standard intervals to Upstox v3 intervals
        # V3 supports custom intervals with unit and interval parameters
        self.timeframe_map = {
            # Minutes - v3 supports 1-300 minutes
            '1m': {'unit': 'minutes', 'interval': '1'},
            '2m': {'unit': 'minutes', 'interval': '2'},
            '3m': {'unit': 'minutes', 'interval': '3'},
            '5m': {'unit': 'minutes', 'interval': '5'},
            '10m': {'unit': 'minutes', 'interval': '10'},
            '15m': {'unit': 'minutes', 'interval': '15'},
            '30m': {'unit': 'minutes', 'interval': '30'},
            '60m': {'unit': 'minutes', 'interval': '60'},
            # Hours - v3 supports 1-5 hours
            '1h': {'unit': 'hours', 'interval': '1'},
            '2h': {'unit': 'hours', 'interval': '2'},
            '3h': {'unit': 'hours', 'interval': '3'},
            '4h': {'unit': 'hours', 'interval': '4'},
            # Days/Weeks/Months - v3 supports interval 1 only
            'D': {'unit': 'days', 'interval': '1'},
            'W': {'unit': 'weeks', 'interval': '1'},
            'M': {'unit': 'months', 'interval': '1'}
        }

    def _get_instrument_key(self, symbol: str, exchange: str) -> str:
        """Get the correct instrument key for a symbol"""
        try:
            # Get token from database - this already includes the exchange prefix
            token = get_token(symbol, exchange)
            if not token:
                raise ValueError(f"No token found for {symbol} on {exchange}")
            
            logger.debug(f"Using instrument key: {token}")
            return token
            
        except Exception as e:
            logger.exception(f"Error getting instrument key for {symbol} on {exchange}")
            raise

    def _is_trading_day(self, date):
        """Check if given date is a trading day"""
        # Basic check for weekends
        if date.weekday() >= 5:  # 5 is Saturday, 6 is Sunday
            return False
        return True

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Quote data with standard fields
        """
        try:
            # Get the correct instrument key
            instrument_key = self._get_instrument_key(symbol, exchange)
            
            # URL encode the instrument key
            encoded_symbol = urllib.parse.quote(instrument_key)
            
            # Use v3 OHLC endpoint
            url = f"/market-quote/ohlc?instrument_key={encoded_symbol}&interval=1d"
            response = get_api_response(url, self.auth_token)
            
            if response.get('status') != 'success':
                error_msg = response.get('message', 'Unknown error')
                if 'errors' in response and response['errors']:
                    error = response['errors'][0]
                    error_msg = error.get('message', error_msg)
                    error_code = error.get('errorCode', 'NO_CODE')
                else:
                    error_code = response.get('code', 'NO_CODE')
                full_error_msg = f"API Error - Code: {error_code}, Message: {error_msg}"
                logger.exception(f"Failed to get quotes for {instrument_key}: {full_error_msg} | Response: {response}")
                raise Exception(full_error_msg)
            
            # Get quote data for the symbol
            quote_data = response.get('data', {})
            if not quote_data:
                raise Exception(f"No data received for instrument key: {instrument_key}")
            
            # Find the quote data - v3 OHLC uses the original instrument key format
            quote = None
            for key, value in quote_data.items():
                if value.get('instrument_token') == instrument_key:
                    quote = value
                    break
                    
            if not quote:
                raise Exception(f"No quote data found for instrument key: {instrument_key}")
            
            # Extract OHLC data from v3 response
            live_ohlc = quote.get('live_ohlc', {})
            prev_ohlc = quote.get('prev_ohlc', {})
            
            # Handle None values
            if live_ohlc is None:
                live_ohlc = {}
            if prev_ohlc is None:
                prev_ohlc = {}
            
            # Try to get bid/ask and OI from v2 quotes endpoint as fallback
            bid_price = 0
            ask_price = 0
            oi_value = 0
            try:
                # Use v2 quotes endpoint for bid/ask and OI data
                v2_url = f"/v2/market-quote/quotes?instrument_key={encoded_symbol}"
                client = get_httpx_client()
                headers = {
                    'Authorization': f'Bearer {self.auth_token}',
                    'Accept': 'application/json'
                }
                full_url = f"https://api.upstox.com{v2_url}"
                v2_response = client.get(full_url, headers=headers)
                v2_data = v2_response.json()
                
                if v2_data.get('status') == 'success':
                    v2_quote_data = v2_data.get('data', {})
                    for key, value in v2_quote_data.items():
                        if value.get('instrument_token') == instrument_key:
                            depth = value.get('depth', {})
                            if depth:
                                best_bid = depth.get('buy', [{}])[0] if depth.get('buy') else {}
                                best_ask = depth.get('sell', [{}])[0] if depth.get('sell') else {}
                                bid_price = best_bid.get('price', 0)
                                ask_price = best_ask.get('price', 0)
                            oi_value = value.get('oi', 0)
                            break
            except Exception as e:
                logger.debug(f"Could not get bid/ask/OI from v2 endpoint: {e}")
            
            # Return standard quote data format using live_ohlc for current data
            return {
                'ask': float(ask_price) if ask_price else 0,
                'bid': float(bid_price) if bid_price else 0,
                'high': float(live_ohlc.get('high', 0)) if live_ohlc.get('high') else 0,
                'low': float(live_ohlc.get('low', 0)) if live_ohlc.get('low') else 0,
                'ltp': float(quote.get('last_price', 0)) if quote.get('last_price') else 0,
                'open': float(live_ohlc.get('open', 0)) if live_ohlc.get('open') else 0,
                'prev_close': float(prev_ohlc.get('close', 0)) if prev_ohlc.get('close') else 0,
                'volume': int(live_ohlc.get('volume', 0)) if live_ohlc.get('volume') else 0,
                'oi': int(oi_value) if oi_value else 0
            }
            
        except Exception as e:
            logger.exception(f"Error fetching quotes for {symbol} on {exchange}")
            raise

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Time interval (e.g., 1m, 5m, 15m, 1h, 1d)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Get the correct instrument key
            instrument_key = self._get_instrument_key(symbol, exchange)
            logger.debug(f"Using instrument key: {instrument_key}")
            
            # Map standard interval to Upstox v3 format
            upstox_config = self.timeframe_map.get(interval)
            if not upstox_config:
                raise Exception(f"Invalid interval: {interval}")
            logger.debug(f"Using v3 config: {upstox_config}")
                
            # URL encode the instrument key
            encoded_symbol = urllib.parse.quote(instrument_key)
            
            # Parse dates
            end = datetime.strptime(end_date, '%Y-%m-%d')
            start = datetime.strptime(start_date, '%Y-%m-%d')
            current_date = datetime.now()
            logger.debug(f"Date range: {start} to {end}")
            
            # Get unit and interval for v3 API
            unit = upstox_config['unit']
            interval_value = upstox_config['interval']
            
            # Format dates for v3 API
            from_date = start.strftime('%Y-%m-%d')
            to_date = end.strftime('%Y-%m-%d')
            
            all_candles = []
            
            # Try intraday endpoint first for current day data
            if unit in ['minutes', 'hours'] and end.date() == current_date.date():
                logger.debug("Trying v3 intraday endpoint...")
                intraday_url = f"/historical-candle/intraday/{encoded_symbol}/{unit}/{interval_value}"
                logger.debug(f"Intraday URL: {intraday_url}")
                
                try:
                    intraday_response = get_api_response(intraday_url, self.auth_token)
                    logger.debug(f"Intraday Response: {intraday_response}")
                    
                    if intraday_response.get('status') == 'success':
                        intraday_candles = intraday_response.get('data', {}).get('candles', [])
                        logger.debug(f"Got {len(intraday_candles)} candles from intraday endpoint")
                        all_candles.extend(intraday_candles)
                except Exception as e:
                    logger.debug(f"Intraday endpoint failed: {e}")
            
            # Try historical endpoint for all other cases or if intraday failed
            if not all_candles or start.date() < current_date.date():
                logger.debug("Trying v3 historical endpoint...")
                
                # Historical endpoint URL format: /historical-candle/{instrument_key}/{unit}/{interval}/{to_date}/{from_date}
                historical_url = f"/historical-candle/{encoded_symbol}/{unit}/{interval_value}/{to_date}/{from_date}"
                logger.debug(f"Historical URL: {historical_url}")
                
                try:
                    historical_response = get_api_response(historical_url, self.auth_token)
                    logger.debug(f"Historical Response: {historical_response}")
                    
                    if historical_response.get('status') == 'success':
                        historical_candles = historical_response.get('data', {}).get('candles', [])
                        logger.debug(f"Got {len(historical_candles)} candles from historical endpoint")
                        all_candles.extend(historical_candles)
                except Exception as e:
                    logger.debug(f"Historical endpoint failed: {e}")
            
            logger.debug(f"Total candles: {len(all_candles)}")
            
            # Special case: If no historical data but requesting today's data only
            if not all_candles:
                # Check if we're only requesting today's data
                today = datetime.now().date()
                start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
                
                if start_date_obj == end_date_obj == today and interval == 'D':
                    logger.debug("No historical data but requesting only today's data - will try to get from quotes")
                    try:
                        # Get today's data from quotes
                        quotes = self.get_quotes(symbol, exchange)
                        logger.debug(f"Quotes response for today-only request: {quotes}")
                        
                        if quotes and quotes.get('ltp', 0) > 0:
                            today_ts_with_offset = int((datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=5, minutes=30)).timestamp())
                            
                            today_data = pd.DataFrame({
                                'timestamp': [today_ts_with_offset],
                                'open': [quotes.get('open', quotes.get('ltp', 0))],
                                'high': [quotes.get('high', quotes.get('ltp', 0))],
                                'low': [quotes.get('low', quotes.get('ltp', 0))],
                                'close': [quotes.get('ltp', 0)],
                                'volume': [quotes.get('volume', 0)],
                                'oi': [quotes.get('oi', 0)]
                            })
                            
                            # Keep timestamp as is (already in Unix epoch format)
                            # No need to convert since today_ts_with_offset is already Unix epoch
                            
                            # Reorder columns to match Angel format
                            today_data = today_data[['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi']]
                            
                            logger.debug(f"Created today's data from quotes: {today_data.to_dict()}")
                            return today_data
                        else:
                            logger.debug("No valid quotes data for today-only request")
                    except Exception as e:
                        logger.warning(f"Could not get today's data from quotes for today-only request: {e}")
                
                return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])
                
            # Convert candle data to DataFrame
            # Upstox v3 format: [timestamp, open, high, low, close, volume, oi]
            df = pd.DataFrame(all_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
            
            # Convert timestamp to datetime and handle timezone properly
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # For daily data, add +5:30 hours to match Flattrade format
            if interval == 'D' and not df.empty:
                df['timestamp'] = df['timestamp'] + pd.Timedelta(hours=5, minutes=30)
            
            # Convert to Unix epoch first
            if not df.empty:
                df['timestamp'] = df['timestamp'].astype(np.int64) // 10**9
            
            # Add today's data from quotes for daily data if needed
            if interval == 'D':
                # Check if today's data is requested
                today = datetime.now().date()
                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
                logger.debug(f"Today: {today}, End date: {end_date_obj}")
                
                if end_date_obj >= today:
                    # Check if today's data is missing from the DataFrame
                    today_ts_with_offset = int((datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=5, minutes=30)).timestamp())
                    logger.debug(f"Today's timestamp with offset: {today_ts_with_offset}")
                    
                    if df.empty:
                        logger.debug("DataFrame is empty, will add today's data")
                        today_exists = False
                    else:
                        today_exists = today_ts_with_offset in df['timestamp'].values
                        logger.debug(f"Today exists in DataFrame: {today_exists}")
                        logger.debug(f"Existing timestamps: {df['timestamp'].values}")
                    
                    if not today_exists:
                        try:
                            logger.debug("Attempting to get today's data from quotes")
                            # Get today's data from quotes
                            quotes = self.get_quotes(symbol, exchange)
                            logger.debug(f"Quotes response: {quotes}")
                            
                            if quotes and quotes.get('ltp', 0) > 0:
                                today_data = pd.DataFrame({
                                    'timestamp': [today_ts_with_offset],
                                    'open': [quotes.get('open', quotes.get('ltp', 0))],
                                    'high': [quotes.get('high', quotes.get('ltp', 0))],
                                    'low': [quotes.get('low', quotes.get('ltp', 0))],
                                    'close': [quotes.get('ltp', 0)],
                                    'volume': [quotes.get('volume', 0)],
                                    'oi': [quotes.get('oi', 0)]
                                })
                                df = pd.concat([df, today_data], ignore_index=True)
                                logger.debug(f"Added today's data from quotes for daily interval: {today_data.to_dict()}")
                            else:
                                logger.debug("No valid quotes data received")
                        except Exception as e:
                            logger.warning(f"Could not add today's data from quotes: {e}")
            
            # Keep OI column and reorder columns to match Angel format
            df = df[['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi']]
            
            # Remove duplicates and sort by timestamp
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
            
            return df
            
        except Exception as e:
            logger.exception(f"Error fetching historical data for {symbol} on {exchange}")
            raise

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for a symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data with buy and sell orders
        """
        try:
            # Get the correct instrument key
            instrument_key = self._get_instrument_key(symbol, exchange)
            
            # URL encode the instrument key
            encoded_symbol = urllib.parse.quote(instrument_key)
            
            # Use v2 quotes endpoint for depth data (v3 OHLC doesn't provide depth)
            url = f"/v2/market-quote/quotes?instrument_key={encoded_symbol}"
            # For depth, we still need to use v2 endpoint directly
            client = get_httpx_client()
            headers = {
                'Authorization': f'Bearer {self.auth_token}',
                'Accept': 'application/json'
            }
            full_url = f"https://api.upstox.com{url}"
            response = client.get(full_url, headers=headers)
            response = response.json()
            
            if response.get('status') != 'success':
                error_msg = response.get('message', 'Unknown error')
                if 'errors' in response and response['errors']:
                    error = response['errors'][0]
                    error_msg = error.get('message', error_msg)
                full_error_msg = f"API Error: {error_msg}"
                logger.exception(f"Failed to get market depth for {instrument_key}: {full_error_msg}")
                raise Exception(full_error_msg)
            
            # Get quote data for the symbol
            quote_data = response.get('data', {})
            if not quote_data:
                raise Exception(f"No data received for instrument key: {instrument_key}")
                
            # Find the quote data - Upstox uses exchange:symbol format for the key
            quote = None
            for key, value in quote_data.items():
                if value.get('instrument_token') == instrument_key:
                    quote = value
                    break
                    
            if not quote:
                raise Exception(f"No quote data found for instrument key: {instrument_key}")
            
            # Get depth data from v2 response
            depth = quote.get('depth', {})
            
            # Also try to get enhanced OHLC data from v3 API
            ohlc_data = {}
            try:
                # Use v3 OHLC endpoint for better OHLC data
                v3_url = f"/market-quote/ohlc?instrument_key={encoded_symbol}&interval=1d"
                v3_response = get_api_response(v3_url, self.auth_token)
                
                if v3_response.get('status') == 'success':
                    v3_quote_data = v3_response.get('data', {})
                    for key, value in v3_quote_data.items():
                        if value.get('instrument_token') == instrument_key:
                            live_ohlc = value.get('live_ohlc', {})
                            prev_ohlc = value.get('prev_ohlc', {})
                            
                            # Handle None values
                            if live_ohlc is None:
                                live_ohlc = {}
                            if prev_ohlc is None:
                                prev_ohlc = {}
                            
                            ohlc_data = {
                                'high': live_ohlc.get('high', 0),
                                'low': live_ohlc.get('low', 0),
                                'open': live_ohlc.get('open', 0),
                                'prev_close': prev_ohlc.get('close', 0),
                                'volume': live_ohlc.get('volume', 0),
                                'ltp': value.get('last_price', 0)
                            }
                            break
            except Exception as e:
                logger.debug(f"Could not get v3 OHLC data: {e}")
            
            # Return standard depth data format
            return {
                'asks': [{
                    'price': order.get('price', 0),
                    'quantity': order.get('quantity', 0)
                } for order in depth.get('sell', [])],
                'bids': [{
                    'price': order.get('price', 0),
                    'quantity': order.get('quantity', 0)
                } for order in depth.get('buy', [])],
                'high': ohlc_data.get('high', quote.get('ohlc', {}).get('high', 0)),
                'low': ohlc_data.get('low', quote.get('ohlc', {}).get('low', 0)),
                'ltp': ohlc_data.get('ltp', quote.get('last_price', 0)),
                'ltq': quote.get('last_quantity', 0),
                'oi': quote.get('oi', 0),
                'open': ohlc_data.get('open', quote.get('ohlc', {}).get('open', 0)),
                'prev_close': ohlc_data.get('prev_close', quote.get('ohlc', {}).get('close', 0)),
                'totalbuyqty': quote.get('total_buy_quantity', 0),
                'totalsellqty': quote.get('total_sell_quantity', 0),
                'volume': ohlc_data.get('volume', quote.get('volume', 0))
            }
            
        except Exception as e:
            logger.exception(f"Error fetching market depth for {symbol} on {exchange}")
            raise

    # Alias for get_depth to maintain compatibility
    get_market_depth = get_depth
