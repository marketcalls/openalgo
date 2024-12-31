import http.client
import json
import os
from datetime import datetime, timedelta
import pandas as pd
from database.token_db import get_br_symbol, get_oa_symbol, get_token
import urllib.parse
import logging
import jwt

# Configure logging
logger = logging.getLogger(__name__)

def extract_client_id(auth_token):
    """Extract client ID from JWT token"""
    try:
        decoded = jwt.decode(auth_token, options={"verify_signature": False})
        return decoded.get('dhanClientId')
    except Exception as e:
        logger.error(f"Error decoding JWT: {str(e)}")
        return None

def get_api_response(endpoint, auth, method="POST", payload=None):
    """Make API request to Dhan"""
    AUTH_TOKEN = auth
    client_id = extract_client_id(AUTH_TOKEN)
    
    if not client_id:
        raise Exception("Could not extract client ID from auth token")
    
    conn = http.client.HTTPSConnection("api.dhan.co")
    headers = {
        'Content-Type': 'application/json',
        'access-token': AUTH_TOKEN,
        'client-id': client_id,
        'Accept': 'application/json'
    }
    
    if payload:
        payload = json.dumps(payload)
    
    logger.info(f"Making request to {endpoint}")
    logger.info(f"Headers: {headers}")
    logger.info(f"Payload: {payload}")
    
    conn.request(method, endpoint, payload, headers)
    res = conn.getresponse()
    data = res.read()
    
    response = json.loads(data.decode("utf-8"))
    
    logger.info(f"Response status: {res.status}")
    logger.info(f"Response: {json.dumps(response, indent=2)}")
    
    # Handle Dhan API error codes
    if response.get('errorCode'):
        error_code = response.get('errorCode')
        error_message = response.get('errorMessage', 'Unknown error')
        error_type = response.get('errorType', 'Unknown')
        
        error_mapping = {
            '806': "Data APIs not subscribed. Please subscribe to Dhan's market data service.",
            '810': "Authentication failed: Invalid client ID",
            '401': "Invalid or expired access token",
            '820': "Market data subscription required",
            '821': "Market data subscription required",
            'DH-907': "No data available for the specified parameters"
        }
        
        error_msg = error_mapping.get(error_code, f"Dhan API Error {error_code} ({error_type}): {error_message}")
        logger.error(f"API Error: {error_msg}")
        raise Exception(error_msg)
    
    return response

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Dhan data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Dhan intervals
        self.timeframe_map = {
            '1m': '1',
            '5m': '5',
            '15m': '15', 
            '25m': '25',
            '1h': '60',
            'D': 'D'  # Daily timeframe
        }
    
    def _convert_to_dhan_request(self, symbol, exchange):
        """Convert symbol and exchange to Dhan format"""
        br_symbol = get_br_symbol(symbol, exchange)
        # Extract security ID and determine exchange segment
        # This needs to be implemented based on your symbol mapping logic
        security_id = get_token(symbol, exchange)  # This should be mapped to Dhan's security ID
        
        if exchange == "NSE":
            exchange_segment = "NSE_EQ"
        elif exchange == "BSE":
            exchange_segment = "BSE_EQ"
        else:
            raise ValueError(f"Unsupported exchange: {exchange}")
            
        return security_id, exchange_segment

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """Get historical data from Dhan"""
        try:
            security_id, exchange_segment = self._convert_to_dhan_request(symbol, exchange)
            
            # Determine if we should use intraday or daily API
            is_intraday = interval in ['1m', '5m', '15m', '25m', '1h']
            
            if is_intraday:
                endpoint = "/v2/charts/intraday"
                payload = {
                    "securityId": security_id,
                    "exchangeSegment": exchange_segment,
                    "instrument": "EQUITY",
                    "interval": self.timeframe_map[interval],
                    "fromDate": start_date,
                    "toDate": end_date
                }
            else:
                endpoint = "/v2/charts/historical"
                payload = {
                    "securityId": security_id,
                    "exchangeSegment": exchange_segment,
                    "instrument": "EQUITY",
                    "expiryCode": 0,
                    "fromDate": start_date,
                    "toDate": end_date
                }
            
            try:
                response = get_api_response(endpoint, self.auth_token, payload=payload)
            except Exception as e:
                if "No data available" in str(e):
                    logger.warning(f"No data available for {symbol} on {start_date}")
                    return pd.DataFrame()  # Return empty DataFrame for no data
                raise  # Re-raise other exceptions
                
            # Check if we have the required fields for both intraday and daily
            required_fields = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            if not all(field in response for field in required_fields):
                logger.error(f"Missing required fields in response. Available fields: {response.keys()}")
                return pd.DataFrame()
            
            # Convert array-based response to list of dicts for both intraday and daily
            data = []
            for i in range(len(response['timestamp'])):
                data.append({
                    'timestamp': int(response['timestamp'][i]),  # Already in epoch format
                    'open': float(response['open'][i]),
                    'high': float(response['high'][i]),
                    'low': float(response['low'][i]),
                    'close': float(response['close'][i]),
                    'volume': int(float(response['volume'][i]))  # Convert to float first to handle scientific notation
                })
            
            if not data:
                logger.warning(f"No data available for {symbol}")
                return pd.DataFrame()
                
            df = pd.DataFrame(data)
            
            # Sort by timestamp
            df = df.sort_values('timestamp')
            
            # Reset index
            df = df.reset_index(drop=True)
            
            return df
            
        except Exception as e:
            logger.error(f"Error fetching history data: {str(e)}")
            logger.error(f"Payload: {payload}")
            raise Exception(f"Error fetching history data: {str(e)}")

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
            security_id = get_token(symbol, exchange)
            exchange_type = map_exchange_type(exchange)
            
            logger.info(f"Getting quotes for symbol: {symbol}, exchange: {exchange}")
            logger.info(f"Mapped security_id: {security_id}, exchange_type: {exchange_type}")
            
            payload = {
                exchange_type: [int(security_id)]
            }
            
            try:
                response = get_api_response("/v2/marketfeed/quote", self.auth_token, "POST", json.dumps(payload))
                quote_data = response.get('data', {}).get(exchange_type, {}).get(str(security_id), {})
                
                if not quote_data:
                    return {
                        'ltp': 0,
                        'open': 0,
                        'high': 0,
                        'low': 0,
                        'volume': 0,
                        'bid': 0,
                        'ask': 0,
                        'prev_close': 0
                    }
                
                # Transform to expected format
                result = {
                    'ltp': float(quote_data.get('last_price', 0)),
                    'open': float(quote_data.get('ohlc', {}).get('open', 0)),
                    'high': float(quote_data.get('ohlc', {}).get('high', 0)),
                    'low': float(quote_data.get('ohlc', {}).get('low', 0)),
                    'volume': int(quote_data.get('volume', 0)),
                    'bid': 0,  # Will be updated from depth
                    'ask': 0,  # Will be updated from depth
                    'prev_close': float(quote_data.get('ohlc', {}).get('close', 0))
                }
                
                # Update bid/ask from depth if available
                depth = quote_data.get('depth', {})
                if depth:
                    buy_orders = depth.get('buy', [])
                    sell_orders = depth.get('sell', [])
                    
                    if buy_orders:
                        result['bid'] = float(buy_orders[0].get('price', 0))
                    if sell_orders:
                        result['ask'] = float(sell_orders[0].get('price', 0))
                
                return result
                
            except Exception as api_error:
                if "not subscribed" in str(api_error).lower():
                    logger.error("Market data subscription error", exc_info=True)
                    return {
                        'ltp': 0,
                        'open': 0,
                        'high': 0,
                        'low': 0,
                        'volume': 0,
                        'bid': 0,
                        'ask': 0,
                        'prev_close': 0,
                        'error': str(api_error)
                    }
                raise
            
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
            security_id = get_token(symbol, exchange)
            exchange_type = map_exchange_type(exchange)
            
            logger.info(f"Getting depth for symbol: {symbol}, exchange: {exchange}")
            logger.info(f"Mapped security_id: {security_id}, exchange_type: {exchange_type}")
            
            payload = {
                exchange_type: [int(security_id)]
            }
            
            try:
                response = get_api_response("/v2/marketfeed/quote", self.auth_token, "POST", json.dumps(payload))
                quote_data = response.get('data', {}).get(exchange_type, {}).get(str(security_id), {})
                
                if not quote_data:
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
                
                depth = quote_data.get('depth', {})
                ohlc = quote_data.get('ohlc', {})
                
                # Prepare bids and asks arrays
                bids = []
                asks = []
                
                # Process buy orders
                buy_orders = depth.get('buy', [])
                for i in range(5):
                    if i < len(buy_orders):
                        bids.append({
                            'price': float(buy_orders[i].get('price', 0)),
                            'quantity': int(buy_orders[i].get('quantity', 0))
                        })
                    else:
                        bids.append({'price': 0, 'quantity': 0})
                
                # Process sell orders
                sell_orders = depth.get('sell', [])
                for i in range(5):
                    if i < len(sell_orders):
                        asks.append({
                            'price': float(sell_orders[i].get('price', 0)),
                            'quantity': int(sell_orders[i].get('quantity', 0))
                        })
                    else:
                        asks.append({'price': 0, 'quantity': 0})
                
                result = {
                    'bids': bids,
                    'asks': asks,
                    'ltp': float(quote_data.get('last_price', 0)),
                    'ltq': int(quote_data.get('last_quantity', 0)),
                    'volume': int(quote_data.get('volume', 0)),
                    'open': float(ohlc.get('open', 0)),
                    'high': float(ohlc.get('high', 0)),
                    'low': float(ohlc.get('low', 0)),
                    'prev_close': float(ohlc.get('close', 0)),
                    'oi': int(quote_data.get('oi', 0)),
                    'totalbuyqty': sum(bid['quantity'] for bid in bids),
                    'totalsellqty': sum(ask['quantity'] for ask in asks)
                }
                
                return result
                
            except Exception as api_error:
                if "not subscribed" in str(api_error).lower():
                    logger.error("Market data subscription error", exc_info=True)
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
                raise
                
        except Exception as e:
            logger.error(f"Error in get_depth: {str(e)}", exc_info=True)
            raise Exception(f"Error fetching market depth: {str(e)}")
