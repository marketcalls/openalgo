import os
import json
import time
import os
from datetime import datetime
import pandas as pd
import threading
import httpx
from typing import Dict, List, Any, Union, Tuple, Optional
from requests.exceptions import Timeout, HTTPError
from utils.logging import get_logger

logger = get_logger(__name__)


# Mock token map for testing
ALICEBLUE_TOKEN_MAP = {
    ('NSE', 'YESBANK'): '5998089',
    ('NSE', 'RELIANCE'): '2885634',
    ('NSE', 'INFY'): '1594561',
    ('BSE', 'RELIANCE'): '500325',
    ('NSE', 'NIFTY50'): '26000',
    ('NSE', 'BANKNIFTY'): '26009'
}

# Token retrieval function 
def get_token(symbol, exchange):
    """Get token for a symbol and exchange"""
    try:
        # First try the local token map
        key = (exchange, symbol)
        if key in ALICEBLUE_TOKEN_MAP:
            return ALICEBLUE_TOKEN_MAP[key]
            
        # Could also try to import the database function
        # but we'll just return None for now if not in our map
        return None
    except Exception as e:
        logger.error(f"Error getting token: {str(e)}")
        return None
from datetime import datetime, timedelta

from utils.httpx_client import get_httpx_client
from database.token_db import get_token, get_br_symbol, get_oa_symbol
from .alicebluewebsocket import AliceBlueWebSocket

# AliceBlue API URLs
BASE_URL = "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/"
SCRIP_DETAILS_URL = BASE_URL + "ScripDetails/getScripQuoteDetails"
HISTORICAL_API_URL = BASE_URL + "chart/history"

# Global websocket instance for reuse
_web_socket = None
_web_socket_lock = threading.Lock()

class BrokerData:
    """
    BrokerData class for AliceBlue broker.
    Handles market data operations including quotes, market depth, and historical data.
    """
    
    def __init__(self, auth_token=None):
        self.token_mapping = {}
        self.session_id = auth_token  # Store the session ID from authentication
        # AliceBlue only supports 1-minute and daily data
        self.timeframe_map = {
            '1m': '1',      # 1-minute data
            'D': 'D'        # Daily data
        }
    
    def get_websocket(self, force_new=False):
        """
        Get or create the global WebSocket instance.
        
        Args:
            force_new (bool): Force creation of a new WebSocket connection even if one exists
        
        Returns:
            AliceBlueWebSocket: WebSocket client instance or None if creation fails
        """
        # Return existing connection if it's valid and not forced to create a new one
        if not force_new and hasattr(self, '_websocket') and self._websocket:
            if hasattr(self._websocket, 'is_connected') and self._websocket.is_connected:
                return self._websocket
        
        try:
            if not self.session_id:
                logger.error("Session ID not available. Please login first.")
                return None
            
            # Clean up any existing connection
            if hasattr(self, '_websocket') and self._websocket:
                try:
                    self._websocket.close()
                except Exception as e:
                    logger.warning(f"Error closing existing WebSocket: {str(e)}")
                
            # Get user ID from environment variable or fallback
            user_id = os.environ.get("BROKER_API_KEY", "")
            if not user_id:
                logger.error("Missing API secret (user ID) for AliceBlue WebSocket")
                return None
                
            # Create new websocket connection
            logger.info(f"Creating new WebSocket connection for AliceBlue")
            self._websocket = AliceBlueWebSocket(user_id, self.session_id)
            self._websocket.connect()
            
            # Wait for connection to establish
            wait_time = 0
            max_wait = 10  # Maximum 10 seconds to wait
            while wait_time < max_wait and not self._websocket.is_connected:
                time.sleep(0.5)
                wait_time += 0.5
            
            if not self._websocket.is_connected:
                logger.error("Failed to connect WebSocket within timeout")
                return None
                
            logger.info("WebSocket connection established successfully")
            return self._websocket
                
        except Exception as e:
            logger.error(f"Error creating WebSocket: {str(e)}")
            return None
    
    def get_quotes(self, symbol_list, timeout: int = 5) -> List[Dict[str, Any]]:
        """
        Get real-time quotes for a list of symbols using the WebSocket connection.
        Falls back to REST API if WebSocket is not available.
        
        Args:
            symbol_list: List of symbols or a single symbol dictionary with exchange and symbol
            timeout (int): Timeout in seconds
            
        Returns:
            List[Dict[str, Any]]: List of quote data for each symbol
        """
        logger.info(f"Original symbol_list: {symbol_list}")
        
        # Special case for Bruno API format with single symbol
        # Special case for OpenAlgo standard format: direct quote request via Bruno
        if isinstance(symbol_list, dict):
            try:
                # Extract symbol and exchange
                symbol = symbol_list.get('symbol') or symbol_list.get('SYMBOL')
                exchange = symbol_list.get('exchange') or symbol_list.get('EXCHANGE')
                
                if symbol and exchange:
                    logger.info(f"Processing single symbol request: {symbol} on {exchange}")
                    # Convert to a list with a single item to use the standard flow
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
        
        # Handle plain string (like just "YESBANK" or "TCS31JUL25FUT")
        elif isinstance(symbol_list, str):
            symbol = symbol_list.strip()
            
            # Auto-detect exchange based on symbol pattern
            if symbol.endswith('FUT'):
                # Futures contracts - NFO for equity futures, BFO for BSE futures
                exchange = 'NFO'  # Default to NFO for futures
            elif symbol.endswith('CE') or symbol.endswith('PE'):
                # Options contracts - NFO for equity options, BFO for BSE options
                exchange = 'NFO'  # Default to NFO for options
            elif 'USDINR' in symbol.upper() or 'EURINR' in symbol.upper():
                # Currency derivatives
                exchange = 'CDS'
            elif any(mcx_symbol in symbol.upper() for mcx_symbol in ['GOLD', 'SILVER', 'CRUDE', 'COPPER', 'ZINC', 'LEAD', 'NICKEL']):
                # Commodity futures
                exchange = 'MCX'
            else:
                # Default to NSE for equity stocks
                exchange = 'NSE'
                
            logger.info(f"Processing string symbol: {symbol} on {exchange} (auto-detected)")
            symbol_list = [{'symbol': symbol, 'exchange': exchange}]
        
        # For simple case, let's create mock data for testing
        # In a production system, you'd get this from the broker API
        quote_data = []
        
        for sym in symbol_list:
            # If it's a simple dict with symbol and exchange
            if isinstance(sym, dict) and 'symbol' in sym and 'exchange' in sym:
                symbol = sym['symbol']
                exchange = sym['exchange']
                
                # Get token for this symbol
                token = get_token(symbol, exchange)
                
                if token:
                    # Get WebSocket connection or create a new one
                    websocket = self.get_websocket()
                    
                    if not websocket or not websocket.is_connected:
                        logger.warning("WebSocket not connected, reconnecting...")
                        websocket = self.get_websocket(force_new=True)
                    
                    if websocket and websocket.is_connected:
                        # Create instrument for subscription
                        class Instrument:
                            def __init__(self, exchange, token, symbol=None):
                                self.exchange = exchange
                                self.token = token
                                self.symbol = symbol
                        
                        instrument = Instrument(exchange=exchange, token=token, symbol=symbol)
                        instruments = [instrument]
                        
                        # Subscribe to this instrument
                        logger.info(f"Subscribing to {exchange}:{symbol} with token {token}")
                        success = websocket.subscribe(instruments)
                        
                        if success:
                            # Wait longer for data to arrive, especially for first subscription
                            logger.info(f"Waiting for WebSocket data for {exchange}:{symbol}")
                            time.sleep(2.0)  # Increased wait time
                            
                            # Retrieve quote from WebSocket
                            logger.info(f"Attempting to retrieve quote for {exchange}:{token}")
                            quote = websocket.get_quote(exchange, token)
                            logger.info(f"Quote retrieval result: {quote is not None}")
                            
                            if quote:
                                # Format the response according to OpenAlgo standard format
                                quote_item = {
                                    'symbol': symbol,
                                    'exchange': exchange,
                                    'token': token,
                                    'ltp': float(quote.get('ltp', 0)),
                                    'open': float(quote.get('open', 0)),
                                    'high': float(quote.get('high', 0)),
                                    'low': float(quote.get('low', 0)),
                                    'close': float(quote.get('close', 0)),
                                    'prev_close': float(quote.get('close', 0)),  # Using close as prev_close
                                    'change': float(quote.get('change', 0)),
                                    'change_percent': float(quote.get('change_percent', 0)),
                                    'volume': int(quote.get('volume', 0)),
                                    'oi': int(quote.get('open_interest', 0)),
                                    'bid': float(quote.get('bid', 0)),
                                    'ask': float(quote.get('ask', 0)),
                                    'timestamp': datetime.now().isoformat()
                                }
                                
                                # Add market depth if available
                                if 'depth' in quote:
                                    quote_item['depth'] = quote['depth']
                                
                                quote_data.append(quote_item)
                                logger.info(f"Retrieved real-time quote for {symbol} on {exchange}")
                                
                                # Unsubscribe after getting the data to stop continuous streaming
                                logger.info(f"Unsubscribing from {exchange}:{symbol} after retrieving quote")
                                websocket.unsubscribe(instruments)
                            else:
                                logger.warning(f"No quote data received for {symbol} on {exchange}")
                                # Unsubscribe even if no data received to clean up subscription
                                logger.info(f"Unsubscribing from {exchange}:{symbol} due to no quote data")
                                websocket.unsubscribe(instruments)
                                # Create fallback data with zeros
                                quote_item = {
                                    'symbol': symbol,
                                    'exchange': exchange,
                                    'token': token,
                                    'ltp': 0.0,
                                    'open': 0.0,
                                    'high': 0.0,
                                    'low': 0.0,
                                    'close': 0.0,
                                    'change': 0.0,
                                    'change_percent': 0.0,
                                    'volume': 0,
                                    'oi': 0,
                                    'timestamp': datetime.now().isoformat()
                                }
                                quote_data.append(quote_item)
                        else:
                            logger.error(f"Failed to subscribe to {symbol} on {exchange}")
                            # No need to unsubscribe if subscription failed
                            # Create error data
                            quote_item = {
                                'symbol': symbol,
                                'exchange': exchange,
                                'token': token,
                                'error': "Failed to subscribe to the instrument",
                                'timestamp': datetime.now().isoformat()
                            }
                            quote_data.append(quote_item)
                    else:
                        logger.error("WebSocket connection unavailable")
                        quote_item = {
                            'symbol': symbol,
                            'exchange': exchange,
                            'token': token,
                            'error': "WebSocket connection unavailable",
                            'timestamp': datetime.now().isoformat()
                        }
                        quote_data.append(quote_item)
                else:
                    logger.error(f"Could not find token for {symbol} on {exchange}")
        
        # Return data directly (service layer will wrap it)
        # If there's no data, return empty response
        if not quote_data:
            return {}
        
        # For single symbol request (most common case), return in simplified format
        if len(quote_data) == 1:
            # Extract the first and only quote
            quote = quote_data[0]
            
            # Return the data directly without wrapping
            return {
                "ltp": quote.get('ltp', 0),
                "oi": quote.get('oi', 0),
                "open": quote.get('open', 0),
                "high": quote.get('high', 0),
                "low": quote.get('low', 0),
                "prev_close": quote.get('prev_close', 0) or quote.get('close', 0),
                "volume": quote.get('volume', 0),
                "bid": quote.get('bid', 0),
                "ask": quote.get('ask', 0)
            }
        
        # For multiple symbols, return the full list
        return quote_data
        
        # Support various input formats
        if not hasattr(symbol_list, '__iter__'):
            logger.error(f"symbol_list must be iterable, got {type(symbol_list)}")
            return []
        
        for sym in symbol_list:
            try:
                # Case 1: Dictionary with exchange and token
                if isinstance(sym, dict) and 'exchange' in sym and 'token' in sym:
                    normalized_symbols.append({
                        'exchange': sym['exchange'],
                        'token': sym['token'],
                        'symbol': sym.get('symbol', '')
                    })
                    
                # Case 2: Dictionary with exchange and symbol but no token (like from Bruno API request)
                elif isinstance(sym, dict) and 'exchange' in sym and 'symbol' in sym and 'token' not in sym:
                    try:
                        exchange = sym['exchange']
                        symbol_str = sym['symbol']
                        # Get token from database
                        token = get_token(symbol_str, exchange)
                        normalized_symbols.append({
                            'exchange': exchange,
                            'token': token,
                            'symbol': symbol_str
                        })
                        logger.info(f"Retrieved token {token} for {exchange}:{symbol_str}")
                    except Exception as e:
                        logger.error(f"Could not get token for {exchange}:{symbol_str}: {str(e)}")
                        
                # Case 3: Object with expected attributes
                elif hasattr(sym, 'exchange') and hasattr(sym, 'token'):
                    normalized_symbols.append({
                        'exchange': sym.exchange,
                        'token': sym.token,
                        'symbol': getattr(sym, 'symbol', '')
                    })
                    
                # Case 4: Single string with format "exchange:symbol"
                elif isinstance(sym, str) and ':' in sym:
                    parts = sym.split(':', 1)
                    if len(parts) == 2:
                        exchange = parts[0]
                        symbol_str = parts[1]
                        try:
                            # Try to get token from database
                            token = get_token(symbol_str, exchange)
                            normalized_symbols.append({
                                'exchange': exchange,
                                'token': token,
                                'symbol': symbol_str
                            })
                        except Exception as e:
                            logger.error(f"Could not get token for {sym}: {str(e)}")
                
                # Case 5: Simple string symbol (like 'YESBANK')
                elif isinstance(sym, str) and ':' not in sym:
                    symbol_str = sym.strip()
                    
                    # Handle different formats
                    if len(symbol_str.split()) > 1:
                        # It might be "NSE YESBANK" format
                        parts = symbol_str.split()
                        exchange, symbol_str = parts[0], parts[1]
                    else:
                        # Default to NSE for Indian symbols if no exchange specified
                        exchange = 'NSE'
                        
                    logger.info(f"Processing symbol: {symbol_str} on {exchange}")
                    
                    try:
                        # Try to get token from database
                        token = get_token(symbol_str, exchange)
                        if token:
                            normalized_symbols.append({
                                'exchange': exchange,
                                'token': token,
                                'symbol': symbol_str
                            })
                            logger.info(f"Successfully normalized {symbol_str} on {exchange} with token {token}")
                        else:
                            logger.error(f"Could not get token for {symbol_str} on {exchange}")
                    except Exception as e:
                        logger.error(f"Could not get token for {symbol_str} on {exchange}: {str(e)}")
                
                # Case 6: Could not parse
                else:
                    logger.warning(f"Could not parse symbol format: {type(sym)} - {sym}")
            except Exception as e:
                logger.error(f"Error processing symbol {sym}: {str(e)}")
        
        logger.info(f"Normalized {len(normalized_symbols)} symbols")
        
        results = []
        
        # First, try using WebSocket for faster data retrieval
        websocket = self.get_websocket()
        
        # Check if the websocket is connected
        if websocket and hasattr(websocket, 'is_connected') and websocket.is_connected:
            try:
                # Prepare instruments for subscription
                instruments = []
                for symbol in normalized_symbols:
                    # Create a simple object with exchange and token attributes
                    class Instrument:
                        def __init__(self, exchange, token, symbol=None):
                            self.exchange = exchange
                            self.token = token
                            self.symbol = symbol
                    
                    # Always get token from database to ensure we have correct token format
                    try:
                        # Get the token from database
                        token = get_token(symbol['symbol'], symbol['exchange'])
                        if token:
                            logger.info(f"Retrieved token {token} for {symbol['exchange']}:{symbol['symbol']}")
                            instruments.append(Instrument(
                                exchange=symbol['exchange'],
                                token=token,
                                symbol=symbol['symbol']
                            ))
                        else:
                            # Fall back to token in symbol dict if present
                            if 'token' in symbol and symbol['token']:
                                logger.info(f"Using provided token {symbol['token']} for {symbol['exchange']}:{symbol['symbol']}")
                                instruments.append(Instrument(
                                    exchange=symbol['exchange'],
                                    token=symbol['token'],
                                    symbol=symbol['symbol']
                                ))
                            else:
                                logger.error(f"Could not find token for {symbol['symbol']} on {symbol['exchange']}")
                    except Exception as e:
                        logger.error(f"Error getting token for {symbol['symbol']} on {symbol['exchange']}: {str(e)}")
                        continue
                
                # Skip if no valid instruments
                if not instruments:
                    logger.warning("No valid instruments to subscribe")
                    return []
                    
                # Subscribe to the instruments
                websocket.subscribe(instruments)
                
                # Wait for data to arrive
                time.sleep(1)  # Wait a bit for data to arrive
                
                # Collect quote data from WebSocket
                for i, instrument in enumerate(instruments):
                    if i >= len(symbol_list):
                        break
                        
                    exchange = instrument.exchange
                    token = instrument.token
                    symbol_name = getattr(instrument, 'symbol', '')
                    
                    quote = websocket.get_quote(exchange, token)
                    
                    if quote:
                        # Format the quote to match the expected structure
                        formatted_quote = {
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "exchange": exchange,
                            "symbol": symbol_name,
                            "ltp": quote.get('ltp', 0),
                            "close": quote.get('close', 0),
                            "open": quote.get('open', 0),
                            "high": quote.get('high', 0),
                            "low": quote.get('low', 0),
                            "volume": quote.get('volume', 0),
                            "bid": quote.get('bid', 0),  # Best bid may not be available
                            "ask": quote.get('ask', 0),  # Best ask may not be available
                            "total_buy_qty": quote.get('total_buy_quantity', 0),
                            "total_sell_qty": quote.get('total_sell_quantity', 0),
                            "open_interest": quote.get('open_interest', 0),
                            "average_price": quote.get('average_trade_price', 0),
                            "token": token
                        }
                        results.append(formatted_quote)
                    else:
                        logger.warning(f"No WebSocket quote data for {exchange}:{token}")
                        # Add to results with empty/default values
                        results.append({
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "exchange": exchange,
                            "symbol": symbol_name,
                            "ltp": 0,
                            "close": 0,
                            "open": 0,
                            "high": 0,
                            "low": 0,
                            "volume": 0,
                            "bid": 0,
                            "ask": 0,
                            "total_buy_qty": 0,
                            "total_sell_qty": 0,
                            "open_interest": 0,
                            "average_price": 0,
                            "token": token
                        })
                
                # If we got at least some data, return it
                if any(r.get('ltp', 0) > 0 for r in results):
                    return results
                
                # Otherwise, fall back to REST API
                logger.warning("No valid quote data from WebSocket, falling back to REST API")
            
            except Exception as e:
                logger.error(f"Error getting quotes via WebSocket: {str(e)}")
                # Continue to fallback REST API method
        
        # Fallback: Use REST API for quotes
        try:
            logger.info("Using REST API for quotes as WebSocket fallback")
            client = get_httpx_client()
            
            # Get user_id from environment variables and session_id from class instance
            user_id = os.environ.get("BROKER_API_SECRET")
            session_id = self.session_id
            
            if not user_id or not session_id:
                logger.error(f"Missing credentials for REST API - user_id: {'Yes' if user_id else 'No'}, session_id: {'Yes' if session_id else 'No'}")
                return results  # Return whatever we have so far
            
            # Make REST API calls for each symbol
            results = []
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {user_id} {session_id}"
            }
            
            for symbol in normalized_symbols:
                # Handle different possible formats of the symbol
                if isinstance(symbol, dict):
                    exchange = symbol.get('exchange')
                    token = symbol.get('token')
                    symbol_name = symbol.get('symbol', '')
                elif hasattr(symbol, 'exchange') and hasattr(symbol, 'token'):
                    exchange = symbol.exchange
                    token = symbol.token
                    symbol_name = getattr(symbol, 'symbol', '')
                else:
                    logger.error(f"Unsupported symbol format in REST fallback: {symbol}")
                    continue
                
                # Skip if we don't have both exchange and token
                if not exchange or not token:
                    logger.warning(f"Missing exchange or token in symbol for REST fallback: {symbol}")
                    continue
                
                payload = {
                    "exch": exchange,
                    "symbol": token
                }
                
                try:
                    response = client.post(SCRIP_DETAILS_URL, headers=headers, json=payload, timeout=timeout)
                    response.raise_for_status()
                    data = response.json()
                    
                    # Format the response to match our expected structure
                    quote = {
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "exchange": exchange,
                        "symbol": symbol_name,
                        "ltp": float(data.get('ltp', 0)),
                        "close": float(data.get('close', 0)),
                        "open": float(data.get('open', 0)),
                        "high": float(data.get('high', 0)),
                        "low": float(data.get('low', 0)),
                        "volume": int(data.get('volume', 0)),
                        "bid": float(data.get('bp', 0)),  # Best bid price
                        "ask": float(data.get('sp', 0)),  # Best ask price
                        "total_buy_qty": int(data.get('tbq', 0)),
                        "total_sell_qty": int(data.get('tsq', 0)),
                        "open_interest": int(data.get('oi', 0)),
                        "average_price": float(data.get('ap', 0)),
                        "token": token
                    }
                    results.append(quote)
                
                except (HTTPError, Timeout) as e:
                    logger.error(f"Error fetching quote for {exchange}:{token}: {str(e)}")
                    # Add empty quote to maintain order
                    results.append({
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "exchange": exchange,
                        "symbol": symbol_name,
                        "ltp": 0,
                        "close": 0,
                        "open": 0,
                        "high": 0,
                        "low": 0,
                        "volume": 0,
                        "bid": 0,
                        "ask": 0,
                        "total_buy_qty": 0,
                        "total_sell_qty": 0,
                        "open_interest": 0,
                        "average_price": 0,
                        "token": token
                    })
                    continue
        
        except Exception as e:
            logger.error(f"Error in REST API fallback for quotes: {str(e)}")
        
        return results
    
    def get_depth(self, symbol_list, timeout: int = 5):
        """
        Get market depth data for a list of symbols using the WebSocket connection.
        This is a wrapper for get_market_depth to maintain API compatibility.
        
        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds
            
        Returns:
            Dict with market depth data in the OpenAlgo standard format
        """
        return self.get_market_depth(symbol_list, timeout)
        
    def get_market_depth(self, symbol_list, timeout: int = 5):
        """
        Get market depth data for a list of symbols using the WebSocket connection.
        
        Args:
            symbol_list: List of symbols, single symbol dict with exchange and symbol, or a single symbol string
            timeout (int): Timeout in seconds
            
        Returns:
            Dict with market depth data in the OpenAlgo standard format
        """
        logger.info(f"Getting market depth for: {symbol_list}")
        
        # Standardize input format
        # Handle dictionary input (single symbol case)
        if isinstance(symbol_list, dict):
            try:
                # Extract symbol and exchange
                symbol = symbol_list.get('symbol') or symbol_list.get('SYMBOL')
                exchange = symbol_list.get('exchange') or symbol_list.get('EXCHANGE')
                
                if symbol and exchange:
                    logger.info(f"Processing single symbol depth request: {symbol} on {exchange}")
                    # Convert to a list with a single item to use the standard flow
                    symbol_list = [{'symbol': symbol, 'exchange': exchange}]
                else:
                    logger.error("Missing symbol or exchange in request")
                    return {
                        "status": "error",
                        "data": {},
                        "message": "Missing symbol or exchange in request"
                    }
            except Exception as e:
                logger.error(f"Error processing single symbol depth request: {str(e)}")
                return {
                    "status": "error",
                    "data": {},
                    "message": f"Error processing depth request: {str(e)}"
                }
        
        # Handle plain string (like just "YESBANK" or "TCS31JUL25FUT")
        elif isinstance(symbol_list, str):
            symbol = symbol_list.strip()
            
            # Auto-detect exchange based on symbol pattern (same logic as quotes)
            if symbol.endswith('FUT'):
                # Futures contracts - NFO for equity futures, BFO for BSE futures
                exchange = 'NFO'  # Default to NFO for futures
            elif symbol.endswith('CE') or symbol.endswith('PE'):
                # Options contracts - NFO for equity options, BFO for BSE options
                exchange = 'NFO'  # Default to NFO for options
            elif 'USDINR' in symbol.upper() or 'EURINR' in symbol.upper():
                # Currency derivatives
                exchange = 'CDS'
            elif any(mcx_symbol in symbol.upper() for mcx_symbol in ['GOLD', 'SILVER', 'CRUDE', 'COPPER', 'ZINC', 'LEAD', 'NICKEL']):
                # Commodity futures
                exchange = 'MCX'
            else:
                # Default to NSE for equity stocks
                exchange = 'NSE'
                
            logger.info(f"Processing string symbol depth: {symbol} on {exchange} (auto-detected)")
            symbol_list = [{'symbol': symbol, 'exchange': exchange}]
        
        # For simple case, prepare the instruments for WebSocket subscription
        depth_data = []
        
        # Get WebSocket connection
        websocket = self.get_websocket()
        
        if not websocket or not websocket.is_connected:
            logger.warning("WebSocket not connected, reconnecting...")
            websocket = self.get_websocket(force_new=True)
        
        if not websocket or not websocket.is_connected:
            logger.error("Could not establish WebSocket connection for market depth")
            return {
                "status": "error",
                "data": {},
                "message": "WebSocket connection unavailable"
            }
        
        # Process each symbol
        for sym in symbol_list:
            # If it's a simple dict with symbol and exchange
            if isinstance(sym, dict) and 'symbol' in sym and 'exchange' in sym:
                symbol = sym['symbol']
                exchange = sym['exchange']
                
                # Get token for this symbol
                token = get_token(symbol, exchange)
                
                if token:
                    # Create instrument for subscription
                    class Instrument:
                        def __init__(self, exchange, token, symbol=None):
                            self.exchange = exchange
                            self.token = token
                            self.symbol = symbol
                    
                    instrument = Instrument(exchange=exchange, token=token, symbol=symbol)
                    
                    # Subscribe to market depth
                    logger.info(f"Subscribing to market depth for {exchange}:{symbol} with token {token}")
                    
                    # Use the depth subscription (t='d')
                    success = websocket.subscribe([instrument], is_depth=True)
                    
                    if success:
                        # Wait longer for depth data to arrive
                        logger.info(f"Waiting for WebSocket depth data for {exchange}:{symbol}")
                        time.sleep(2.0)  # Increased wait time for depth data
                        
                        # Retrieve depth from WebSocket
                        depth = websocket.get_market_depth(exchange, token)
                        
                        if depth:
                            # Create a normalized depth structure in the OpenAlgo format
                            item = {
                                'symbol': symbol,
                                'exchange': exchange,
                                'token': token,
                                'timestamp': datetime.now().isoformat(),
                                'total_buy_qty': depth.get('total_buy_quantity', 0),
                                'total_sell_qty': depth.get('total_sell_quantity', 0),
                                'ltp': depth.get('ltp', 0),
                                'oi': depth.get('open_interest', 0),
                                'depth': {
                                    'buy': [],
                                    'sell': []
                                }
                            }
                            
                            # Format the buy orders
                            bids = depth.get('bids', [])
                            for bid in bids:
                                item['depth']['buy'].append({
                                    'price': bid.get('price', 0),
                                    'quantity': bid.get('quantity', 0),
                                    'orders': bid.get('orders', 0)
                                })
                                
                            # Format the sell orders
                            asks = depth.get('asks', [])
                            for ask in asks:
                                item['depth']['sell'].append({
                                    'price': ask.get('price', 0),
                                    'quantity': ask.get('quantity', 0),
                                    'orders': ask.get('orders', 0)
                                })
                            
                            depth_data.append(item)
                            logger.info(f"Retrieved market depth for {symbol} on {exchange}")
                            
                            # Unsubscribe after getting the data to stop continuous streaming
                            logger.info(f"Unsubscribing from depth for {exchange}:{symbol} after retrieving data")
                            websocket.unsubscribe([instrument], is_depth=True)
                        else:
                            logger.warning(f"No market depth received for {symbol} on {exchange}")
                            # Also unsubscribe even if no data received to clean up subscription
                            logger.info(f"Unsubscribing from depth for {exchange}:{symbol} due to no data")
                            websocket.unsubscribe([instrument], is_depth=True)
                    else:
                        logger.error(f"Failed to subscribe to market depth for {symbol} on {exchange}")
                else:
                    logger.error(f"Could not find token for {symbol} on {exchange}")
            else:
                logger.warning(f"Unsupported symbol format for market depth: {sym}")
        
        # Return data directly (service layer will wrap it)
        # If there's no data, return empty response
        if not depth_data:
            return {}
        
        # For single symbol request (most common case), return in simplified format
        if len(depth_data) == 1:
            # Extract the first and only depth item
            depth_item = depth_data[0]
            
            # Return the data directly without wrapping
            return {
                "symbol": depth_item.get('symbol', ''),
                "exchange": depth_item.get('exchange', ''),
                "ltp": depth_item.get('ltp', 0),
                "oi": depth_item.get('oi', 0),   
                "total_buy_qty": depth_item.get('total_buy_qty', 0),
                "total_sell_qty": depth_item.get('total_sell_qty', 0),
                "depth": depth_item.get('depth', {'buy': [], 'sell': []})
            }
        
        # For multiple symbols, return the full list
        return depth_data
    
    def get_history(self, symbol: str, exchange: str, timeframe: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical candle data for a symbol.
        
        Args:
            symbol (str): Trading symbol (e.g., 'TCS', 'RELIANCE')
            exchange (str): Exchange code (NSE, BSE, NFO, etc.)
            timeframe (str): Timeframe such as '1m', '5m', etc.
            start_date (str): Start date in YYYY-MM-DD format
            end_date (str): End date in YYYY-MM-DD format
            
        Returns:
            pd.DataFrame: DataFrame with historical candle data
        """
        try:
            logger.info(f"Getting historical data for {symbol}:{exchange}, timeframe: {timeframe}")
            logger.info(f"Date range: {start_date} to {end_date}")
            logger.info(f"Date types - start_date: {type(start_date)}, end_date: {type(end_date)}")
            
            # Get token for the symbol
            token = get_token(symbol, exchange)
            if not token:
                logger.error(f"Token not found for {symbol} on {exchange}")
                return pd.DataFrame()
            
            logger.info(f"Found token {token} for {symbol}:{exchange}")
            
            # Check for exchange limitations based on AliceBlue API documentation
            if exchange in ['BSE', 'BCD', 'BFO']:
                logger.error(f"Historical data not available for {exchange} exchange on AliceBlue")
                return pd.DataFrame()
            
            # For MCX, NFO, CDS - only current expiry contracts are supported
            if exchange in ['MCX', 'NFO', 'CDS']:
                logger.warning(f"Note: AliceBlue only provides historical data for current expiry contracts on {exchange}")
            
            # Check if timeframe is supported
            if timeframe not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                logger.error(f"Unsupported timeframe: {timeframe}. AliceBlue only supports: {', '.join(supported)}")
                return pd.DataFrame()
            
            # Get the AliceBlue resolution format
            aliceblue_timeframe = self.timeframe_map[timeframe]
            
            # Get credentials - AliceBlue historical API uses user_id in Bearer token
            from utils.config import get_broker_api_key, get_broker_api_secret

            # IMPORTANT: AliceBlue historical API uses user_id (BROKER_API_KEY), not client_id!
            # This is different from other APIs which use BROKER_API_SECRET
            user_id = get_broker_api_key()  # This should be '1412368' in your case
            auth_token = self.session_id  # This is the session token from login

            if not user_id or not auth_token:
                logger.error(f"Missing credentials for historical data - user_id: {'Yes' if user_id else 'No'}, auth_token: {'Yes' if auth_token else 'No'}")
                return pd.DataFrame()

            # Historical API uses different auth format: Bearer {user_id} {session_token}
            headers = {
                'Authorization': f'Bearer {user_id} {auth_token}',
                'Content-Type': 'application/json'
            }
            
            # Alternative: Try adding session token to payload as some historical APIs expect it
            # payload['sessionId'] = session_id
            
            # For indices, append ::index to the exchange
            exchange_str = f"{exchange}::index" if exchange.endswith("IDX") else exchange
            
            # Convert timestamps to milliseconds as required by AliceBlue API
            # Format: Unix timestamp in milliseconds (like 1660128489000)
            import time
            from datetime import datetime
            
            def convert_to_unix_ms(timestamp, is_end_date=False):
                """Convert various timestamp formats to Unix milliseconds in IST
                
                Args:
                    timestamp: The timestamp to convert
                    is_end_date: If True, sets time to end of day (23:59:59) for date-only strings
                """
                import pytz
                ist = pytz.timezone('Asia/Kolkata')
                
                logger.debug(f"Converting timestamp: {timestamp} (type: {type(timestamp)}, is_end_date: {is_end_date})")
                
                # Handle datetime.date objects from marshmallow schema
                if hasattr(timestamp, 'strftime'):
                    # It's a date or datetime object
                    timestamp = timestamp.strftime('%Y-%m-%d')
                    logger.debug(f"Converted date object to string: {timestamp}")
                
                if isinstance(timestamp, str):
                    # Handle date strings like '2025-07-03'
                    try:
                        if 'T' in timestamp or ' ' in timestamp:
                            # Handle datetime strings like '2025-07-03T10:30:00' or '2025-07-03 10:30:00'
                            dt = datetime.fromisoformat(timestamp.replace('T', ' '))
                        else:
                            # Handle date-only strings like '2025-07-03'
                            dt = datetime.strptime(timestamp, '%Y-%m-%d')
                            if is_end_date:
                                # Set to end of day (23:59:59) for end dates
                                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                            else:
                                # Set to start of day (00:00:00) for start dates
                                dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
                        
                        # Localize to IST timezone (AliceBlue expects IST timestamps)
                        dt_ist = ist.localize(dt)
                        
                        # Convert to Unix timestamp in seconds, then to milliseconds
                        result = str(int(dt_ist.timestamp() * 1000))
                        logger.debug(f"Converted '{timestamp}' to {result} (Date: {dt_ist})")
                        return result
                    except (ValueError, Exception) as e:
                        logger.error(f"Error parsing timestamp string '{timestamp}': {e}")
                        logger.error(f"Timestamp type: {type(timestamp)}, value: {repr(timestamp)}")
                        # Fallback to current time - THIS SHOULD NOT HAPPEN
                        logger.error("WARNING: Falling back to current time - this is likely a bug!")
                        return str(int(time.time() * 1000))
                elif isinstance(timestamp, (int, float)):
                    if timestamp > 1000000000000:
                        # Already in milliseconds
                        return str(int(timestamp))
                    elif timestamp > 1000000000:
                        # In seconds, convert to milliseconds
                        return str(int(timestamp * 1000))
                    else:
                        # Unknown format, assume seconds and convert
                        return str(int(timestamp * 1000))
                else:
                    # Fallback to current time
                    return str(int(time.time() * 1000))
            
            start_ms = convert_to_unix_ms(start_date, is_end_date=False)
            end_ms = convert_to_unix_ms(end_date, is_end_date=True)

            # Log the conversion for debugging
            logger.info(f"Date conversion - Start: {start_date} -> {start_ms}, End: {end_date} -> {end_ms}")

            # Validate that dates are not in the future
            current_time_ms = int(time.time() * 1000)
            if int(start_ms) > current_time_ms:
                logger.error(f"Start date {start_date} is in the future. Historical data is only available for past dates.")
                return pd.DataFrame()

            # If end date is in future, cap it to current time
            if int(end_ms) > current_time_ms:
                logger.warning(f"End date {end_date} is in the future. Capping to current time.")
                end_ms = str(current_time_ms)
            
            # Ensure start and end times are different and valid
            if start_ms == end_ms:
                logger.warning(f"Start and end timestamps are the same: {start_ms}. Adjusting end time.")
                # If they're the same, add one day to the end time
                end_ms = str(int(end_ms) + 86400000)  # Add 24 hours in milliseconds
            
            # For intraday data, ensure minimum time range
            if timeframe != 'D':
                time_diff_ms = int(end_ms) - int(start_ms)
                min_range_ms = 3600000  # Minimum 1 hour for intraday data
                
                if time_diff_ms < min_range_ms:
                    logger.warning(f"Time range too small ({time_diff_ms}ms). Extending to minimum 1 hour for intraday data.")
                    end_ms = str(int(start_ms) + min_range_ms)
            
            # Prepare request payload according to AliceBlue API docs
            payload = {
                "token": str(token),  # Token should be the instrument token
                "exchange": exchange,  # Exchange should be NSE, NFO, etc.
                "from": start_ms,
                "to": end_ms,
                "resolution": aliceblue_timeframe
            }
            
            # Debug logging
            logger.info(f"Making historical data request:")
            logger.info(f"URL: {HISTORICAL_API_URL}")
            logger.info(f"Headers: {headers}")
            logger.info(f"Payload: {payload}")
            
            # Make request to historical API
            client = get_httpx_client()
            response = client.post(HISTORICAL_API_URL, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            # Check if response contains valid data
            if data.get('stat') == 'Not_Ok' or 'result' not in data:
                error_msg = data.get('emsg', 'Unknown error')
                logger.error(f"Error in historical data response: {error_msg}")
                
                # Provide more helpful error messages based on the error
                if "No data available" in error_msg:
                    if exchange in ['MCX', 'NFO', 'CDS']:
                        logger.error(f"No data available. For {exchange}, AliceBlue only provides data for current expiry contracts.")
                        logger.error(f"Symbol '{symbol}' might be an expired contract or not a current expiry.")
                    elif exchange in ['BSE', 'BCD', 'BFO']:
                        logger.error(f"AliceBlue does not support historical data for {exchange} exchange yet.")
                    else:
                        logger.error(f"No historical data available for {symbol} on {exchange}.")
                        logger.error(f"This could be due to: 1) Symbol not traded in the date range, 2) Invalid symbol, or 3) Data not available during market hours (available from 5:30 PM to 8 AM on weekdays)")
                
                return pd.DataFrame()
            
            # Convert response to DataFrame
            df = pd.DataFrame(data['result'])
            
            # Rename columns to standard format
            # Use 'timestamp' instead of 'datetime' to match Angel and other brokers
            df = df.rename(columns={
                'time': 'timestamp',
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume'
            })

            # Ensure DataFrame has required columns
            if not all(col in df.columns for col in ['timestamp', 'open', 'high', 'low', 'close', 'volume']):
                logger.error(f"Missing required columns in historical data response")
                return pd.DataFrame()

            # Convert time column to datetime
            # AliceBlue returns time as string in format 'YYYY-MM-DD HH:MM:SS'
            df['timestamp'] = pd.to_datetime(df['timestamp'])

            # Handle different timeframes
            if timeframe == 'D':
                # For daily data, normalize to date only (no time component)
                # Set time to midnight to represent the date
                df['timestamp'] = df['timestamp'].dt.normalize()

                # Add IST offset (5:30 hours) for proper Unix timestamp conversion
                # This ensures the date is correctly represented
                df['timestamp'] = df['timestamp'] + pd.Timedelta(hours=5, minutes=30)
            else:
                # For intraday data, adjust timestamps to represent the start of the candle
                # AliceBlue provides end-of-candle timestamps (XX:XX:59), we need start (XX:XX:00)
                df['timestamp'] = df['timestamp'].dt.floor('min')

            # AliceBlue timestamps are in IST - need to localize them
            import pytz
            ist = pytz.timezone('Asia/Kolkata')

            # Localize to IST (AliceBlue provides IST timestamps without timezone info)
            df['timestamp'] = df['timestamp'].dt.tz_localize(ist)

            # Convert timestamp to Unix epoch (seconds since 1970)
            # This will correctly handle the IST timezone
            df['timestamp'] = df['timestamp'].astype('int64') // 10**9

            # Ensure numeric columns are properly typed
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric)

            # Sort by timestamp and remove any duplicates
            df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)

            # Add OI column with zeros (AliceBlue doesn't provide OI in historical data)
            df['oi'] = 0

            # Return columns in the order matching Angel broker format
            df = df[['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi']]

            return df
            
        except Exception as e:
            logger.error(f"Error fetching historical data: {str(e)}")
            return pd.DataFrame()
    
    def get_intervals(self) -> List[str]:
        """
        Get list of supported timeframes.
        
        Returns:
            List[str]: List of supported timeframe strings
        """
        return list(self.timeframe_map.keys())
