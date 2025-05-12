import json
import os
from datetime import datetime, timedelta
import pandas as pd
import logging
import httpx
from typing import Dict, List, Any, Union, Optional
import time
from utils.httpx_client import get_httpx_client

from database.token_db import get_br_symbol, get_oa_symbol, get_token

# Configure logging
logger = logging.getLogger(__name__)
# API endpoints are handled by the Groww SDK

# Exchange constants for Groww API
EXCHANGE_NSE = "NSE"  # Stock exchange code for NSE
EXCHANGE_BSE = "BSE"  # Stock exchange code for BSE

# Segment constants for Groww API
SEGMENT_CASH = "CASH"  # Segment code for Cash market
SEGMENT_FNO = "FNO"    # Segment code for F&O market


def get_api_response(endpoint, auth_token, method="GET", params=None, data=None, debug=False):
    """Make direct API requests to Groww endpoints
    
    This function directly calls Groww API endpoints using the shared httpx client
    with connection pooling for better performance.
    
    Args:
        endpoint (str): API endpoint (e.g., '/v1/quotes')
        auth_token (str): Authentication token
        method (str): HTTP method (GET, POST, etc.)
        params (dict): URL parameters for the API call
        data (dict): Request body data for POST/PUT requests
        debug (bool): Enable additional debugging
        
    Returns:
        dict: Response data from the Groww API
    """
    logger.info(f"Making direct API request to endpoint: {endpoint}")
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    # Ensure endpoint starts with a slash
    if not endpoint.startswith('/'):
        endpoint = '/' + endpoint
    
    # Build the full URL
    base_url = "https://api.groww.in"
    url = f"{base_url}{endpoint}"
    
    # Set up headers with authentication token
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {auth_token}'
    }
    
    try:
        # Make the request based on the HTTP method
        if method.upper() == 'GET':
            response = client.get(url, headers=headers, params=params)
        elif method.upper() == 'POST':
            response = client.post(url, headers=headers, json=data)
        elif method.upper() == 'PUT':
            response = client.put(url, headers=headers, json=data)
        elif method.upper() == 'DELETE':
            response = client.delete(url, headers=headers, params=params)
        else:
            logger.error(f"Unsupported HTTP method: {method}")
            return {"error": f"Unsupported HTTP method: {method}"}
        
        # Log request details if debug is enabled
        if debug:
            logger.debug(f"Request URL: {url}")
            logger.debug(f"Request params: {params}")
        
        # Check if the request was successful
        response.raise_for_status()
        
        # Parse the JSON response
        try:
            result = response.json()
            if debug:
                logger.debug(f"API Response: {result}")
            return result
        except ValueError:
            # Handle non-JSON responses
            logger.error("Response is not valid JSON")
            return {"error": "Response is not valid JSON", "content": response.text}
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
        return {"error": f"HTTP error: {e.response.status_code}", "details": e.response.text}
    except Exception as e:
        logger.error(f"Error in API request: {str(e)}")
        if debug:
            logger.exception("Detailed exception info:")
        return {"error": str(e)}


class BrokerData:
    def __init__(self, auth_token):
        """Initialize Groww data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Groww resolutions (if applicable)
        self.timeframe_map = {
            # Minutes
            '1m': '1',    # 1 minute
            '5m': '5',    # 5 minutes
            '15m': '15',  # 15 minutes
            '30m': '30',  # 30 minutes
            '1h': '60',   # 1 hour (60 minutes)
            # Daily
            'D': 'D'      # Daily data
        }

    def _convert_to_groww_params(self, symbol, exchange):
        """
        Convert symbol and exchange to Groww API parameters
        
        Args:
            symbol (str): Trading symbol
            exchange (str): Exchange code (NSE, BSE, etc.)
            
        Returns:
            tuple: (exchange, segment, trading_symbol)
        """
        logger.debug(f"Converting params - Symbol: {symbol}, Exchange: {exchange}")
        
        # Handle cases where exchange is not specified or is same as symbol
        if not exchange or exchange == symbol:
            exchange = "NSE"
            logger.info(f"Exchange not specified, defaulting to NSE for symbol {symbol}")
        
        # Determine segment based on exchange
        if exchange in ["NSE", "BSE"]:
            segment = SEGMENT_CASH
            logger.debug(f"Using SEGMENT_CASH for exchange {exchange}")
        elif exchange in ["NFO", "BFO"]:
            segment = SEGMENT_FNO
            logger.debug(f"Using SEGMENT_FNO for exchange {exchange}")
        else:
            logger.error(f"Unsupported exchange: {exchange}")
            raise ValueError(f"Unsupported exchange: {exchange}")
            
        # Map exchange to Groww's format
        if exchange == "NFO":
            groww_exchange = EXCHANGE_NSE
            logger.debug("Mapped NFO to EXCHANGE_NSE")
        elif exchange == "BFO":
            groww_exchange = EXCHANGE_BSE
            logger.debug("Mapped BFO to EXCHANGE_BSE")
        else:
            groww_exchange = exchange
            logger.debug(f"Using exchange as-is: {exchange}")
            
        # Get broker-specific symbol if needed
        br_symbol = get_br_symbol(symbol, exchange)
        trading_symbol = br_symbol or symbol
        
        return groww_exchange, segment, trading_symbol

    def _convert_date_to_utc(self, date_str: str) -> str:
        """Convert IST date to UTC date for API request"""
        # Simply return the date string as the API expects YYYY-MM-DD format
        return date_str

    def get_history(self, symbol: str, exchange: str, timeframe: str, start_time: str, end_time: str) -> pd.DataFrame:
        """
        Get historical candle data for a symbol using Groww SDK.
        
        Args:
            exchange (str): Exchange code (NSE, BSE, NFO, etc.)
            token (str): Trading symbol (e.g. 'INFY')
            timeframe (str): Timeframe such as '1m', '5m', etc.
            start_time (str): Start date in YYYY-MM-DD format
            end_time (str): End date in YYYY-MM-DD format
            
        Returns:
            pd.DataFrame: DataFrame with historical candle data
        """
        try:
            logger.debug(f"get_history called with params - Exchange: {exchange}, Symbol: {symbol}, Timeframe: {timeframe}")
            logger.debug(f"Date range: {start_time} to {end_time}")
            
            # Import Groww SDK
            growwapi = importlib.import_module('growwapi')
            GrowwAPI = getattr(growwapi, 'GrowwAPI')
            logger.info("Successfully imported Groww SDK for historical data")
            
            # Initialize Groww API
            groww_api = GrowwAPI(self.auth_token)
            logger.info("Initialized Groww API for historical data")
            
            # Convert date strings to datetime objects
            start_dt = datetime.strptime(start_time, '%Y-%m-%d')
            end_dt = datetime.strptime(end_time, '%Y-%m-%d')
            
            # Convert to milliseconds timestamp for Groww API
            start_time_ms = int(start_dt.timestamp() * 1000)
            end_time_ms = int(end_dt.timestamp() * 1000)
            logger.debug(f"Converted dates to milliseconds: {start_time} -> {start_time_ms}, {end_time} -> {end_time_ms}")
            
            # Get interval in minutes from timeframe
            if timeframe not in self.timeframe_map:
                logger.error(f"Unsupported timeframe: {timeframe}")
                raise ValueError(f"Unsupported timeframe: {timeframe}")
            interval_minutes = int(self.timeframe_map[timeframe])
            logger.debug(f"Using interval of {interval_minutes} minutes")
            
            # Convert exchange and get segment
            groww_exchange, segment, trading_symbol = self._convert_to_groww_params(symbol, exchange)
            logger.info(f"Converted parameters - Exchange: {groww_exchange}, Segment: {segment}, Symbol: {trading_symbol}")
            
            # Get historical data from Groww
            logger.info(f"Requesting historical data for {trading_symbol} on {groww_exchange}")
            historical_data = groww_api.get_historical_candle_data(
                trading_symbol=trading_symbol,
                exchange=groww_exchange,
                segment=segment,
                start_time=start_time_ms,
                end_time=end_time_ms,
                interval_in_minutes=interval_minutes
            )
            logger.debug(f"Raw response from Groww API: {historical_data}")
            
            # Check if we got valid data
            if not historical_data or 'candles' not in historical_data:
                logger.error(f"No historical data received for {trading_symbol}")
                return pd.DataFrame()
            
            # Convert candles to DataFrame
            # Candle format: [timestamp, open, high, low, close, volume]
            candles = historical_data['candles']
            df = pd.DataFrame(
                candles,
                columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
            )
            
            # Convert timestamp from epoch seconds to datetime
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            
            # Set timestamp as index
            df.set_index('timestamp', inplace=True)
            
            logger.info(f"Successfully retrieved {len(df)} candles for {trading_symbol}")
            return df
            
        except Exception as e:
            logger.error(f"Error getting historical data: {str(e)}")
            raise

    def get_intervals(self) -> List[str]:
        """
        Get list of supported timeframes.
        
        Returns:
            List[str]: List of supported timeframe strings
        """
        return list(self.timeframe_map.keys())

    def get_quotes(self, symbol_list, timeout: int = 5) -> Dict[str, Any]:
        """
        Get real-time quotes for a list of symbols using direct Groww API calls.
        
        This implementation directly calls Groww API endpoints instead of using the SDK.
        
        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds
            
        Returns:
            Dict[str, Any]: Quote data in OpenAlgo format
        """
        logger.info(f"Getting quotes using direct API calls for: {symbol_list}")
        
        # Define exchange and segment constants
        EXCHANGE_NSE = 'NSE'
        EXCHANGE_BSE = 'BSE'
        SEGMENT_CASH = 'CASH'
        SEGMENT_FNO = 'FNO'
        
        # Standardize input to a list of dictionaries with exchange and symbol
        if isinstance(symbol_list, dict):
            try:
                # Extract symbol and exchange
                symbol = symbol_list.get('symbol') or symbol_list.get('SYMBOL')
                exchange = symbol_list.get('exchange') or symbol_list.get('EXCHANGE')
                
                if symbol and exchange:
                    logger.info(f"Processing single symbol request: {symbol} on {exchange}")
                    # Convert to a list with a single item
                    symbol_list = [{'symbol': symbol, 'exchange': exchange}]
                else:
                    logger.error("Missing symbol or exchange in request")
                    return {
                        "status": "error",
                        "data": [],
                        "message": "Missing symbol or exchange in request"
                    }
            except Exception as e:
                logger.error(f"Error processing single symbol request: {str(e)}")
                return {
                    "status": "error",
                    "data": [],
                    "message": f"Error processing request: {str(e)}"
                }
        
        # Handle plain string (like just "RELIANCE")
        elif isinstance(symbol_list, str):
            symbol = symbol_list.strip()
            exchange = 'NSE'  # Default to NSE for Indian stocks
            logger.info(f"Processing string symbol: {symbol} on {exchange}")
            symbol_list = [{'symbol': symbol, 'exchange': exchange}]
        
        # Process all symbols using direct API calls
        quote_data = []
        
        for sym in symbol_list:
            try:
                # Extract symbol and exchange
                if isinstance(sym, dict) and 'symbol' in sym and 'exchange' in sym:
                    symbol = sym['symbol']
                    exchange = sym['exchange']
                elif isinstance(sym, str):
                    symbol = sym
                    exchange = 'NSE'  # Default to NSE
                else:
                    logger.warning(f"Invalid symbol format: {sym}")
                    continue
                
                # Get token for this symbol
                token = get_token(symbol, exchange)
                
                # Map OpenAlgo exchange to Groww exchange format
                if exchange == 'NSE':
                    groww_exchange = EXCHANGE_NSE
                    segment = SEGMENT_CASH
                elif exchange == 'BSE':
                    groww_exchange = EXCHANGE_BSE
                    segment = SEGMENT_CASH
                elif exchange == 'NFO':
                    groww_exchange = EXCHANGE_NSE
                    segment = SEGMENT_FNO
                elif exchange == 'BFO':
                    groww_exchange = EXCHANGE_BSE
                    segment = SEGMENT_FNO
                else:
                    logger.warning(f"Unsupported exchange: {exchange}, defaulting to NSE")
                    groww_exchange = EXCHANGE_NSE
                    segment = SEGMENT_CASH
                
                # Get broker-specific symbol if needed
                trading_symbol = get_br_symbol(symbol, exchange) or symbol
                
                logger.info(f"Requesting quote for {trading_symbol} on {groww_exchange} (segment: {segment})")
                # Make direct API call to Groww quotes endpoint
                start_time = time.time()
                
                # Safely convert values to float/int, handling None values
                def safe_float(value, default=0.0):
                    if value is None:
                        return default
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        return default
                        
                def safe_int(value, default=0):
                    if value is None:
                        return default
                    try:
                        return int(value)
                    except (ValueError, TypeError):
                        return default
                
                try:
                    # Define API endpoint for quotes
                    quote_endpoint = "/v1/live-data/quote"
                    
                    # Prepare parameters
                    params = {
                        'exchange': groww_exchange,
                        'segment': segment,
                        'trading_symbol': trading_symbol
                    }
                    
                    # Make the API call using the shared httpx client
                    response = get_api_response(
                        endpoint=quote_endpoint,
                        auth_token=self.auth_token,
                        method="GET",
                        params=params,
                        debug=True
                    )
                    
                    print(f"Groww API response: {response}")
                    elapsed = time.time() - start_time
                    logger.info(f"Got response from Groww API in {elapsed:.2f}s")
                    
                    if response and not response.get('error'):
                        logger.info(f"Successfully retrieved quote for {symbol} on {exchange}")
                        # Log a sample of the data structure
                        if isinstance(response, dict):
                            logger.info(f"Response keys: {list(response.keys())[:10]}")
                            
                        # Extract payload which contains the actual quote data
                        if response.get('status') == 'SUCCESS' and isinstance(response.get('payload'), dict):
                            response = response.get('payload', {})
                            print(f"response: {response}")
                            logger.info(f"Extracted payload data with keys: {list(response.keys())[:10]}")
                            
                            # Extract OHLC data from the nested structure
                            # OHLC might be a string in some responses
                            ohlc_data = response.get('ohlc', {})
                            logger.info(f"Raw OHLC data: {ohlc_data}")
                            
                            # Handle case where ohlc is a string (from sample response)
                            ohlc = {}
                            if isinstance(ohlc_data, str):
                                # Try to parse the string into a dict
                                try:
                                    # Convert the string format "{open: 149.50,high: 150.50,low: 148.50,close: 149.50}" to a dict
                                    ohlc_str = ohlc_data.strip('{}')
                                    parts = ohlc_str.split(',')
                                    for part in parts:
                                        key_val = part.split(':')
                                        if len(key_val) == 2:
                                            key = key_val[0].strip()
                                            val = key_val[1].strip()
                                            ohlc[key] = float(val)
                                except Exception as e:
                                    logger.error(f"Error parsing OHLC string: {e}")
                            else:
                                # Use the object directly
                                ohlc = ohlc_data
                                
                            logger.info(f"Processed OHLC data: {ohlc}")
                            
                            # Create quote_item in OpenAlgo format
                            # Print each field being extracted for debugging
                            print(f"last_price: {response.get('last_price')}")
                            print(f"ohlc: {ohlc}")
                            print(f"volume: {response.get('volume')}")
                            
                            # CRITICAL: Build the quote item directly with values extracted from the response, using field names that OpenAlgo understands
                            # The quote_item should use the frontend-compatible field names
                            last_price = safe_float(response.get('last_price'))
                            print(f"EXTRACTED last_price = {last_price}")
                            
                            quote_item = {
                                'symbol': symbol,
                                'exchange': exchange,
                                'token': token,
                                # Use 'ltp' directly as that's what the frontend expects
                                'ltp': last_price,  # This is what the frontend looks for
                                'last_price': last_price,  # Keep original field too just in case
                                'open': safe_float(ohlc.get('open')),
                                'high': safe_float(ohlc.get('high')),
                                'low': safe_float(ohlc.get('low')),
                                'close': safe_float(ohlc.get('close')),
                                'prev_close': safe_float(ohlc.get('close')),  # Using previous day's close
                                'change': safe_float(response.get('day_change')),
                                'change_percent': safe_float(response.get('day_change_perc')),
                                'volume': safe_int(response.get('volume')),
                                # The frontend uses 'bid' and 'ask' without the _price suffix
                                'bid': safe_float(response.get('bid_price')),
                                'ask': safe_float(response.get('offer_price')),
                                # Also keep original fields
                                'bid_price': safe_float(response.get('bid_price')),
                                'bid_qty': safe_int(response.get('bid_quantity')),
                                'ask_price': safe_float(response.get('offer_price')),
                                'ask_qty': safe_int(response.get('offer_quantity')),
                                'total_buy_qty': safe_float(response.get('total_buy_quantity')),
                                'total_sell_qty': safe_float(response.get('total_sell_quantity')),
                                'timestamp': response.get('last_trade_time', int(datetime.now().timestamp() * 1000))
                            }
                            
                            # Add circuit limits
                            if 'upper_circuit_limit' in response:
                                quote_item['upper_circuit'] = safe_float(response.get('upper_circuit_limit'))
                            if 'lower_circuit_limit' in response:
                                quote_item['lower_circuit'] = safe_float(response.get('lower_circuit_limit'))
                            
                            # Add market depth if available
                            if 'depth' in response:
                                depth_data = response['depth']
                                buy_depth = depth_data.get('buy', [])
                                sell_depth = depth_data.get('sell', [])
                                
                                depth = {
                                    'buy': [],
                                    'sell': []
                                }
                                
                                # Process buy side
                                for level in buy_depth:
                                    if safe_float(level.get('price')) > 0:  # Only include non-zero prices
                                        depth['buy'].append({
                                            'price': safe_float(level.get('price')),
                                            'quantity': safe_int(level.get('quantity')),
                                            'orders': 0  # Groww API doesn't provide order count
                                        })
                                
                                # Process sell side
                                for level in sell_depth:
                                    if safe_float(level.get('price')) > 0:  # Only include non-zero prices
                                        depth['sell'].append({
                                            'price': safe_float(level.get('price')),
                                            'quantity': safe_int(level.get('quantity')),
                                            'orders': 0  # Groww API doesn't provide order count
                                        })
                                
                                quote_item['depth'] = depth
                            
                            # Add to quote data
                            quote_data.append(quote_item)
                            print(f"Added quote_item: {quote_item}")
                        else:
                            logger.warning(f"Invalid response format for {symbol} on {exchange}")
                            response = {}
                    else:
                        logger.warning(f"Empty or error response for {symbol} on {exchange}")
                        response = {}
                    
                    # This section is now handled directly in the response processing code above to avoid duplicate processing
                    continue
                    
                    # Add market depth if available
                    if 'depth' in response:
                        depth_data = response['depth']
                        buy_depth = depth_data.get('buy', [])
                        sell_depth = depth_data.get('sell', [])
                        
                        depth = {
                            'buy': [],
                            'sell': []
                        }
                        
                        # Process buy side
                        for level in buy_depth:
                            depth['buy'].append({
                                'price': safe_float(level.get('price')),
                                'quantity': safe_int(level.get('quantity')),
                                'orders': 0  # Groww API doesn't provide order count
                            })
                        
                        # Process sell side
                        for level in sell_depth:
                            depth['sell'].append({
                                'price': safe_float(level.get('price')),
                                'quantity': safe_int(level.get('quantity')),
                                'orders': 0  # Groww API doesn't provide order count
                            })
                        
                        quote_item['depth'] = depth
                        
                except Exception as api_error:
                    logger.error(f"Groww API error: {str(api_error)}")
                    error_msg = str(api_error)
                    # Add to quote data with error
                    quote_data.append({
                        'symbol': symbol,
                        'exchange': exchange,
                        'token': token,
                        'error': error_msg,
                        'ltp': 0
                    })
            except Exception as e:
                logger.error(f"Error processing Groww API data for {sym}: {str(e)}")
                # Add empty quote data with error message
                quote_data.append({
                    'symbol': symbol if 'symbol' in locals() else str(sym),
                    'exchange': exchange if 'exchange' in locals() else 'Unknown',
                    'error': str(e),
                    'ltp': 0
                })
    
        # Debug output of the final quote_data
        print(f"FINAL QUOTE DATA: {quote_data}")
        
        # No data case
        if not quote_data:
            logger.warning("No quote data found for the requested symbols")
            return {
                "status": "error",
                "message": "No data retrieved"
            }
        
        # Single symbol case - return in simpler format for OpenAlgo frontend
        if isinstance(symbol_list, (str, dict)) or len(symbol_list) == 1:
            logger.info(f"Returning data for single symbol")
    
            # Log what is being passed to the formatter
            logger.debug(f"Quote data passed to formatter: {quote_data}")
            
            # For single symbols, just return the direct quote data
            # The REST API endpoint will wrap it with status/data
            return self._format_single_quote_response(quote_data)

        
        # Multiple quotes - return in standard format
        logger.info(f"Returning data for {len(quote_data)} symbols")
        return {
            "status": "success",
            "data": quote_data
        }
    def _format_single_quote_response(self, quote_data):
        """Helper method to convert from standard dict to the format expected by OpenAlgo frontend
        
        Returns only the data portion without status wrapper - status added by the caller
        """

        if not quote_data or not isinstance(quote_data, list) or len(quote_data) == 0:
            return {}

        quote = quote_data[0]

        logger.info(f"Formatting single quote: {quote}")

        result = {
            "ltp": quote.get("ltp", 0),
            "open": quote.get("open", 0),
            "high": quote.get("high", 0),
            "low": quote.get("low", 0),
            "prev_close": quote.get("prev_close", 0),
            "volume": quote.get("volume", 0),
            "bid": quote.get("bid_price", 0),
            "ask": quote.get("ask_price", 0)
        }

        logger.debug(f"Final OpenAlgo quote format (data only): {result}")
        return result

    # Commented out alternate implementation

    # Legacy implementation - no longer used
    # The code below is from the previous implementation and is kept for reference
    #    print("Empty quote_data received in _format_single_quote_response")
    #    return {
    #        "status": "success",
    #        "data": {}
    #    }
    #        
    #    # Extract first (and only) item in single quote request    
    #    quote = quote_data[0] if isinstance(quote_data, list) and len(quote_data) > 0 else {}
        
        print(f"EXTRACTED QUOTE: {quote}")
        logger.info(f"Formatting single quote response for OpenAlgo frontend: {quote}")
        
        # Based on the sample response, OpenAlgo expects exactly these fields
        # Keep this extremely simple - just the required fields
        simple_data = {
            "ltp": 0,
            "open": 0,
            "high": 0,
            "low": 0,
            "prev_close": 0,
            "volume": 0,
            "bid": 0,
            "ask": 0,
            "status": "success"
        }
        
        # Now grab values from our quote data, using the field that matches best
        
        # LTP - preferred field name in OpenAlgo
        if "ltp" in quote and quote["ltp"] is not None:
            simple_data["ltp"] = float(quote["ltp"])
        elif "last_price" in quote and quote["last_price"] is not None:
            simple_data["ltp"] = float(quote["last_price"])
        
        # Open price
        if "open" in quote and quote["open"] is not None:
            simple_data["open"] = float(quote["open"])
        
        # High price
        if "high" in quote and quote["high"] is not None:
            simple_data["high"] = float(quote["high"])
        
        # Low price
        if "low" in quote and quote["low"] is not None:
            simple_data["low"] = float(quote["low"])
        
        # Previous close
        if "prev_close" in quote and quote["prev_close"] is not None:
            simple_data["prev_close"] = float(quote["prev_close"])
        elif "close" in quote and quote["close"] is not None:
            simple_data["prev_close"] = float(quote["close"])
        
        # Volume
        if "volume" in quote and quote["volume"] is not None:
            simple_data["volume"] = int(quote["volume"])
        
        # Bid price
        if "bid" in quote and quote["bid"] is not None:
            simple_data["bid"] = float(quote["bid"])
        elif "bid_price" in quote and quote["bid_price"] is not None:
            simple_data["bid"] = float(quote["bid_price"])
        
        # Ask price
        if "ask" in quote and quote["ask"] is not None:
            simple_data["ask"] = float(quote["ask"])
        elif "ask_price" in quote and quote["ask_price"] is not None:
            simple_data["ask"] = float(quote["ask_price"])
        elif "offer_price" in quote and quote["offer_price"] is not None:
            simple_data["ask"] = float(quote["offer_price"])
            
        # Debug output
        print("FINAL SIMPLE FORMAT:")
        for key, value in simple_data.items():
            print(f"{key}: {value}")
        
        # Return exact structure expected by OpenAlgo
        result = {
            "status": "success",
            "data": simple_data
        }
        
        print(f"FINAL FORMATTED RESULT: {result}")
        logger.info(f"Formatted result for OpenAlgo frontend: {result}")
        
        return result
        
    def get_depth(self, symbol_list, timeout: int = 5) -> Dict[str, Any]:
        """ 
        Get market depth for a symbol or list of symbols using Groww API.
        This leverages the direct API endpoint for quotes, which includes market depth information.
        
        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds
            
        Returns:
            Dict[str, Any]: Market depth data in OpenAlgo format
        """
        logger.info(f"Getting market depth using direct API calls for: {symbol_list}")
        
        # Reuse get_quotes as it already contains market depth data
        quotes_response = self.get_quotes(symbol_list, timeout)
        
        if quotes_response.get("status") == "success":
            depth_data = []
            
            for quote in quotes_response.get("data", []):
                if "depth" in quote:
                    # Quote already contains properly formatted depth data
                    depth_item = {
                        "symbol": quote.get("symbol"),
                        "exchange": quote.get("exchange"),
                        "token": quote.get("token"),
                        "depth": quote.get("depth"),
                        "ltp": quote.get("ltp", 0),
                        "total_buy_qty": quote.get("total_buy_qty", 0),
                        "total_sell_qty": quote.get("total_sell_qty", 0),
                        "timestamp": quote.get("timestamp")
                    }
                    depth_data.append(depth_item)
                else:
                    # No depth data available, create empty structure
                    depth_item = {
                        "symbol": quote.get("symbol"),
                        "exchange": quote.get("exchange"),
                        "token": quote.get("token"),
                        "depth": {
                            "buy": [],
                            "sell": []
                        },
                        "ltp": quote.get("ltp", 0),
                        "total_buy_qty": quote.get("total_buy_qty", 0),
                        "total_sell_qty": quote.get("total_sell_qty", 0),
                        "timestamp": quote.get("timestamp")
                    }
                    depth_data.append(depth_item)
            
            # Single symbol case
            if isinstance(symbol_list, (str, dict)) or len(symbol_list) == 1:
                logger.info(f"Returning depth data for single symbol")
                return {
                    "status": "success",
                    "data": depth_data[0] if depth_data else {}
                }
            
            # Multiple symbols case
            return {
                "status": "success",
                "data": depth_data
            }

    def get_market_depth(self, symbol_list, timeout: int = 5) -> Dict[str, Any]:
        """Alias for get_depth. Maintains API compatibility.
        
        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds
            
        Returns:
            Dict[str, Any]: Market depth data in OpenAlgo format
        """
        return self.get_depth(symbol_list, timeout)