import json
import os
from datetime import datetime, timedelta
import pandas as pd
from database.token_db import get_token
import httpx
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from broker.indstocks.api.baseurl import get_url

logger = get_logger(__name__)

def get_api_response(endpoint, auth, method="GET", params=None):
    AUTH_TOKEN = auth
    
    if not AUTH_TOKEN:
        raise Exception("Authentication token is required")
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    # Log token info for debugging (mask the actual token)
    token_preview = AUTH_TOKEN[:20] + "..." + AUTH_TOKEN[-10:] if len(AUTH_TOKEN) > 30 else AUTH_TOKEN
    logger.info(f"Using auth token: {token_preview}")
    
    headers = {
        'Authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    
    url = get_url(endpoint)
    
    logger.info(f"Making request to {url}")
    logger.info(f"Method: {method}")
    logger.info(f"Headers: {headers}")
    logger.info(f"Params: {params}")
    # Build query string for debugging
    if params:
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        logger.info(f"Full URL with params: {url}?{query_string}")
    else:
        logger.info(f"Full URL: {url}")
    
    try:
        if method == "GET":
            res = client.get(url, headers=headers, params=params)
        elif method == "POST":
            res = client.post(url, headers=headers, json=params)
        else:
            res = client.request(method, url, headers=headers, params=params)
        
        logger.info(f"Request completed. Status code: {res.status_code}")
        logger.info(f"Actual request URL: {res.url}")
        
    except Exception as req_error:
        logger.error(f"Request failed: {str(req_error)}")
        raise Exception(f"Failed to make request to IndStocks API: {str(req_error)}")
    
    # Add status attribute for compatibility with existing codebase
    res.status = res.status_code
    
    logger.info(f"Response status: {res.status}")
    logger.info(f"Raw response text: {res.text}")
    
    # Check if response is successful
    if res.status_code != 200:
        logger.error(f"HTTP Error {res.status_code}: {res.text}")
        raise Exception(f"IndStocks API HTTP Error {res.status_code}: {res.text}")
    
    # Try to parse JSON response
    try:
        response = json.loads(res.text)
        logger.info(f"Parsed JSON response: {json.dumps(response, indent=2)}")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        logger.error(f"Response text that failed to parse: {res.text}")
        raise Exception(f"IndStocks API returned invalid JSON: {str(e)}")
    
    # Handle IndStocks API error responses
    if response.get('status') != 'success':
        error_message = response.get('message', 'Unknown error')
        logger.error(f"API Error: {error_message}")
        raise Exception(f"IndStocks API Error: {error_message}")
    
    return response

class BrokerData:
    def __init__(self, auth_token):
        """Initialize IndStocks data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to IndStocks resolutions
        self.timeframe_map = {
            # Minutes
            '1m': '1',    # 1 minute
            '5m': '5',    # 5 minutes
            '15m': '15',  # 15 minutes
            '25m': '25',  # 25 minutes
            '1h': '60',   # 1 hour (60 minutes)
            # Daily
            'D': 'D'      # Daily data
        }

    def _get_scrip_code(self, symbol, exchange):
        """Convert symbol and exchange to IndStocks scrip code format"""
        # Get security ID/token for the symbol
        security_id = get_token(symbol, exchange)
        if not security_id:
            raise Exception(f"Could not find security ID for {symbol} on {exchange}")
        
        # Map exchange to IndStocks segment
        exchange_segment_map = {
            'NSE': 'NSE',
            'BSE': 'BSE',
            'NFO': 'NFO',
            'BFO': 'BFO',
            'MCX': 'MCX',
            'CDS': 'CDS',
            'BCD': 'BCD',
            'NSE_INDEX': 'NSE',
            'BSE_INDEX': 'BSE'
        }
        
        segment = exchange_segment_map.get(exchange)
        if not segment:
            raise Exception(f"Unsupported exchange: {exchange}")
        
        # Format: SEGMENT_INSTRUMENTTOKEN
        scrip_code = f"{segment}_{security_id}"
        logger.info(f"Generated scrip code: {scrip_code} for symbol: {symbol}, exchange: {exchange}")
        
        return scrip_code

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
            scrip_code = self._get_scrip_code(symbol, exchange)
            
            logger.info(f"Getting quotes for symbol: {symbol}, exchange: {exchange}")
            logger.info(f"Using scrip code: {scrip_code}")
            
            params = {
                'scrip-codes': scrip_code
            }
            
            try:
                # Get LTP data
                ltp_response = get_api_response("/market/quotes/ltp", self.auth_token, "GET", params)
                logger.info(f"LTP Response: {ltp_response}")
                ltp_data = ltp_response.get('data', {}).get(scrip_code, {})
                
                # Get market depth for bid/ask
                bid_price = 0
                ask_price = 0
                try:
                    depth_response = get_api_response("/market/quotes/mkt", self.auth_token, "GET", params)
                    depth_raw = depth_response.get('data', {}).get(scrip_code, {})
                    
                    # Handle the extra nesting level in market depth
                    market_depth_container = depth_raw.get('market_depth', {})
                    market_depth = market_depth_container.get(scrip_code, {})
                    depth_levels = market_depth.get('depth', [])
                    
                    if depth_levels and len(depth_levels) > 0:
                        first_level = depth_levels[0]
                        if 'buy' in first_level:
                            bid_price = float(first_level['buy'].get('price', 0))
                        if 'sell' in first_level:
                            ask_price = float(first_level['sell'].get('price', 0))
                except Exception as depth_error:
                    logger.warning(f"Could not fetch depth data for quotes: {str(depth_error)}")
                
                if not ltp_data:
                    return {
                        'ltp': 0,
                        'open': 0,
                        'high': 0,
                        'low': 0,
                        'volume': 0,
                        'bid': bid_price,  # Use bid/ask even if LTP fails
                        'ask': ask_price,
                        'prev_close': 0,
                        'oi': 0
                    }
                
                # Transform to expected format
                result = {
                    'ltp': float(ltp_data.get('live_price', 0)),
                    'open': 0,  # OHLC data not available from LTP endpoint
                    'high': 0,
                    'low': 0,
                    'volume': 0,  # Volume not available from LTP endpoint
                    'oi': 0,  # Open interest not available
                    'bid': bid_price,
                    'ask': ask_price,
                    'prev_close': 0  # Previous close not available from LTP endpoint
                }
                
                return result
                
            except Exception as e:
                logger.error(f"Error fetching quotes: {str(e)}")
                return {
                    'ltp': 0,
                    'open': 0,
                    'high': 0,
                    'low': 0,
                    'volume': 0,
                    'bid': 0,
                    'ask': 0,
                    'prev_close': 0,
                    'oi': 0,
                    'error': str(e)
                }
            
        except Exception as e:
            logger.error(f"Error in get_quotes: {str(e)}", exc_info=True)
            raise Exception(f"Error fetching quotes: {str(e)}")

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data with bids and asks
        """
        try:
            scrip_code = self._get_scrip_code(symbol, exchange)
            
            logger.info(f"Getting depth for symbol: {symbol}, exchange: {exchange}")
            logger.info(f"Using scrip code: {scrip_code}")
            
            params = {
                'scrip-codes': scrip_code
            }
            
            try:
                # Get market depth from IndStocks API
                depth_response = get_api_response("/market/quotes/mkt", self.auth_token, "GET", params)
                depth_data = depth_response.get('data', {}).get(scrip_code, {})
                
                # Try to get LTP data (since /market/quotes doesn't work, try /market/quotes/ltp)
                quotes_data = {}
                try:
                    ltp_response = get_api_response("/market/quotes/ltp", self.auth_token, "GET", params)
                    quotes_data = ltp_response.get('data', {}).get(scrip_code, {})
                except Exception as ltp_error:
                    logger.warning(f"Could not fetch LTP data: {str(ltp_error)}")
                    # If LTP also fails, we'll use default values
                
                if not depth_data:
                    return {
                        'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                        'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                        'ltp': 0,
                        'ltq': 0,
                        'volume': 0,
                        'open': 0,
                        'high': 0,
                        'low': 0,
                        'prev_close': 0,
                        'oi': 0,
                        'totalbuyqty': 0,
                        'totalsellqty': 0
                    }
                
                # Process market depth - handle the extra nesting level
                market_depth_container = depth_data.get('market_depth', {})
                # IndStocks has an extra nesting level with the scrip code
                market_depth = market_depth_container.get(scrip_code, {})
                depth_levels = market_depth.get('depth', [])
                aggregate = market_depth.get('aggregate', {})
                
                # Prepare bids and asks arrays
                bids = []
                asks = []
                
                # Process depth levels (up to 5 levels)
                for i in range(5):
                    if i < len(depth_levels):
                        level = depth_levels[i]
                        buy_data = level.get('buy', {})
                        sell_data = level.get('sell', {})
                        
                        # Clean quantity strings (remove commas and convert to int)
                        buy_qty_str = str(buy_data.get('quantity', '0')).replace(',', '').replace('.00', '')
                        sell_qty_str = str(sell_data.get('quantity', '0')).replace(',', '').replace('.00', '')
                        
                        bids.append({
                            'price': float(buy_data.get('price', 0)),
                            'quantity': int(float(buy_qty_str)) if buy_qty_str else 0
                        })
                        
                        asks.append({
                            'price': float(sell_data.get('price', 0)),
                            'quantity': int(float(sell_qty_str)) if sell_qty_str else 0
                        })
                    else:
                        bids.append({'price': 0, 'quantity': 0})
                        asks.append({'price': 0, 'quantity': 0})
                
                # Calculate total buy/sell quantities
                # Try to get from aggregate data first, then calculate from depth
                try:
                    total_buy = aggregate.get('total_buy', '0')
                    total_sell = aggregate.get('total_sell', '0')
                    
                    # Clean comma-separated values
                    totalbuyqty = int(str(total_buy).replace(',', '')) if total_buy else sum(bid['quantity'] for bid in bids)
                    totalsellqty = int(str(total_sell).replace(',', '')) if total_sell else sum(ask['quantity'] for ask in asks)
                except:
                    # Fallback to calculation from depth
                    totalbuyqty = sum(bid['quantity'] for bid in bids)
                    totalsellqty = sum(ask['quantity'] for ask in asks)
                
                # Build final result - use LTP data if available, otherwise use bid/ask prices
                ltp_price = 0
                if quotes_data and 'live_price' in quotes_data:
                    ltp_price = float(quotes_data.get('live_price', 0))
                elif bids and bids[0]['price'] > 0:
                    # If no LTP available, use best bid price as approximation
                    ltp_price = bids[0]['price']
                
                result = {
                    'bids': bids,
                    'asks': asks,
                    'ltp': ltp_price,
                    'ltq': 0,  # Last traded quantity not available in IndStocks API
                    'volume': 0,  # Volume not available in market depth endpoint
                    'open': 0,  # OHLC data not available in market depth endpoint
                    'high': 0,
                    'low': 0,
                    'prev_close': 0,
                    'oi': 0,  # Open interest not available
                    'totalbuyqty': totalbuyqty,
                    'totalsellqty': totalsellqty
                }
                
                return result
                
            except Exception as api_error:
                logger.error(f"API error in get_depth: {str(api_error)}")
                return {
                    'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                    'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                    'ltp': 0,
                    'ltq': 0,
                    'volume': 0,
                    'open': 0,
                    'high': 0,
                    'low': 0,
                    'prev_close': 0,
                    'oi': 0,
                    'totalbuyqty': 0,
                    'totalsellqty': 0,
                    'error': str(api_error)
                }
                
        except Exception as e:
            logger.error(f"Error in get_depth: {str(e)}", exc_info=True)
            raise Exception(f"Error fetching market depth: {str(e)}")

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Candle interval in common format:
                     Minutes: 1m, 5m, 15m, 25m
                     Hours: 1h
                     Days: D
            start_date: Start date (YYYY-MM-DD) in IST
            end_date: End date (YYYY-MM-DD) in IST
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Note: IndStocks historical data API endpoints are not documented in the provided documentation
            # This is a placeholder implementation that would need to be updated when the historical data API is available
            logger.warning("Historical data API not yet implemented for IndStocks")
            
            # Return empty DataFrame with expected columns
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
            
        except Exception as e:
            logger.error(f"Error fetching historical data: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")