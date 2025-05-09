import json
import os
from datetime import datetime, timedelta
import pandas as pd
import logging
import requests
from typing import Dict, List, Any, Union, Optional
import importlib
import time

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
    """Use Groww SDK to make API requests
    
    This function initializes the Groww SDK and uses it to make API requests
    instead of directly using requests. The SDK handles the endpoints and authentication.
    
    Args:
        endpoint (str): API endpoint (not used with SDK but kept for compatibility)
        auth_token (str): Authentication token
        method (str): HTTP method (GET, POST, etc., not used with SDK but kept for compatibility)
        params (dict): Parameters for the API call
        data (dict): Request body data (not used with SDK but kept for compatibility)
        debug (bool): Enable additional debugging
        
    Returns:
        dict: Response data from the Groww SDK
    """
    logger.info(f"Using Groww SDK for API request to endpoint: {endpoint}")
    
    try:
        # Import the SDK
        growwapi = importlib.import_module('growwapi')
        GrowwAPI = getattr(growwapi, 'GrowwAPI')
        
        # Initialize the SDK with auth token
        api = GrowwAPI(auth_token)
        
        # Log request details
        logger.info(f"SDK request params: {params}")
        
        # Use the SDK's generic request method if available
        # Or simulate based on endpoint and method
        if hasattr(api, 'request'):
            # If the SDK has a generic request method, use it
            result = api.request(endpoint, params=params, data=data, method=method)
        else:
            # Handle specific endpoints that we know about
            if 'quote' in endpoint.lower():
                # Extract parameters for quote
                exchange = params.get('exchange')
                segment = params.get('segment')
                trading_symbol = params.get('trading_symbol') or params.get('symbol')
                
                if not all([exchange, segment, trading_symbol]):
                    raise ValueError(f"Missing required parameters for quote: {params}")
                
                logger.info(f"Getting quote for {trading_symbol} on {exchange} ({segment})")
                result = api.get_quote(exchange=exchange, segment=segment, trading_symbol=trading_symbol)
            else:
                # For other endpoints, we would need to map them to SDK functions
                raise ValueError(f"Unmapped SDK endpoint: {endpoint}")
        
        # Log the response structure
        if isinstance(result, dict):
            logger.info(f"SDK response keys: {list(result.keys())[:10]}")
            for key in list(result.keys())[:3]:  # Only show first 3 keys for brevity
                try:
                    if isinstance(result[key], dict):
                        logger.info(f"Subkeys for {key}: {list(result[key].keys())[:10]}")
                except Exception:
                    pass
        
        return result
    
    except ImportError:
        logger.error("Failed to import Groww SDK. Please install with: pip install growwapi")
        raise ImportError("Groww SDK not installed. Please install with: pip install growwapi")
    
    except Exception as e:
        logger.error(f"Groww SDK error: {str(e)}")
        if debug:
            logger.error(f"Endpoint: {endpoint}, Params: {params}")
        raise Exception(f"Groww SDK Error: {str(e)}")



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
        Get real-time quotes for a list of symbols using Groww SDK.
        
        This implementation uses the official Groww SDK to fetch market data.
        
        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds
            
        Returns:
            Dict[str, Any]: Quote data in OpenAlgo format
        """
        logger.info(f"Getting quotes using Groww SDK for: {symbol_list}")
        
        # Try to import the Groww SDK
        try:
            growwapi = importlib.import_module('growwapi')
            GrowwAPI = getattr(growwapi, 'GrowwAPI')
            logger.info("Successfully imported Groww SDK")
        except ImportError:
            logger.error("Failed to import growwapi. Please install it with: pip install growwapi")
            raise ImportError("Groww SDK not installed. Please install it with: pip install growwapi")
        except Exception as e:
            logger.error(f"Error importing Groww SDK: {str(e)}")
            raise
        
        # Initialize the GrowwAPI with the auth token
        groww_api = GrowwAPI(self.auth_token)
        
        # Get the exchange and segment constants from the SDK
        EXCHANGE_NSE = getattr(groww_api, 'EXCHANGE_NSE', 'NSE')
        EXCHANGE_BSE = getattr(groww_api, 'EXCHANGE_BSE', 'BSE')
        SEGMENT_CASH = getattr(groww_api, 'SEGMENT_CASH', 'CASH')
        SEGMENT_FNO = getattr(groww_api, 'SEGMENT_FNO', 'FNO')
        
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
        
        # Process all symbols using the Groww SDK
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
                
                # Make API call using Groww SDK
                start_time = time.time()
                try:
                    response = groww_api.get_quote(
                        exchange=groww_exchange,
                        segment=segment,
                        trading_symbol=trading_symbol
                    )
                    print(f"Groww API response: {response}")
                    elapsed = time.time() - start_time
                    logger.info(f"Got response from Groww API in {elapsed:.2f}s")
                    
                    if response:
                        logger.info(f"Successfully retrieved quote for {symbol} on {exchange}")
                        # Log a sample of the data structure
                        if isinstance(response, dict):
                            logger.info(f"Response keys: {list(response.keys())[:10]}")
                    else:
                        logger.warning(f"Empty response for {symbol} on {exchange}")
                        response = {}
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
                    continue
                
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
                
                # Extract OHLC data from the nested structure for easier access
                ohlc = response.get('ohlc', {})
                
                # Create quote_item in OpenAlgo format from Groww response
                quote_item = {
                    'symbol': symbol,
                    'exchange': exchange,
                    'token': token,
                    'ltp': safe_float(response.get('last_price')),
                    'open': safe_float(ohlc.get('open')),
                    'high': safe_float(ohlc.get('high')),
                    'low': safe_float(ohlc.get('low')),
                    'close': safe_float(ohlc.get('close')),
                    'prev_close': safe_float(ohlc.get('close')),  # Using previous day's close
                    'change': safe_float(response.get('day_change')),
                    'change_percent': safe_float(response.get('day_change_perc')),
                    'volume': safe_int(response.get('volume')),
                    'bid_price': safe_float(response.get('bid_price')),
                    'bid_qty': safe_int(response.get('bid_quantity')),
                    'ask_price': safe_float(response.get('offer_price')),
                    'ask_qty': safe_int(response.get('offer_quantity')),
                    'total_buy_qty': safe_float(response.get('total_buy_quantity')),
                    'total_sell_qty': safe_float(response.get('total_sell_quantity')),
                    'timestamp': response.get('last_trade_time', int(datetime.now().timestamp() * 1000))
                }
                
                # Actually add the quote_item to the quote_data list
                quote_data.append(quote_item)
                
                # Add circuit limits if available
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
                
            except Exception as e:
                logger.error(f"Error processing Groww API data for {sym}: {str(e)}")
                # Add empty quote data with error message
                quote_data.append({
                    'symbol': symbol if 'symbol' in locals() else str(sym),
                    'exchange': exchange if 'exchange' in locals() else 'Unknown',
                    'error': str(e),
                    'ltp': 0
                })
        
        # No data case
        if not quote_data:
            logger.warning("No quote data found for the requested symbols")
            return {
                "status": "error",
                "message": "No data retrieved"
            }
            
        # Single quote - Format exactly as specified by OpenAlgo API, without nesting
        if len(quote_data) == 1:
            quote = quote_data[0]
            logger.info(f"Returning data for {quote.get('symbol', 'unknown')} in OpenAlgo format")
            
            # Direct format without nested data structure
            return {
                "ask": quote.get('ask_price', 0),
                "bid": quote.get('bid_price', 0),
                "high": quote.get('high', 0),
                "low": quote.get('low', 0),
                "ltp": quote.get('ltp', 0),
                "open": quote.get('open', 0),
                "prev_close": quote.get('prev_close', 0),
                "volume": quote.get('volume', 0),
                "status": "success"
            }
        
        # Multiple quotes - return in standard format
        logger.info(f"Returning data for {len(quote_data)} symbols")
        return {
            "status": "success",
            "data": quote_data
        }

    def get_market_depth(self, symbol_list, timeout: int = 5) -> Dict[str, Any]:
        """
        Get market depth for a symbol or list of symbols using Groww API.
        This leverages the get_quotes method since Groww's quote API includes depth information.
        
        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds
            
        Returns:
            Dict[str, Any]: Market depth data in OpenAlgo format
        """
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
            
            return {
                "status": "success",
                "data": depth_data,
                "message": f"Retrieved depth data for {len(depth_data)} symbols"
            }
        else:
            # Return the error from get_quotes
            return quotes_response

    def get_depth(self, symbol_list, timeout: int = 5) -> Dict[str, Any]:
        """
        Alias for get_market_depth. Maintains API compatibility.
        
        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds
            
        Returns:
            Dict[str, Any]: Market depth data in OpenAlgo format
        """
        return self.get_market_depth(symbol_list, timeout)