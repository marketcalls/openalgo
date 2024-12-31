import http.client
import json
import os
from datetime import datetime, timedelta
import pandas as pd
from database.token_db import get_br_symbol, get_oa_symbol, get_token
from broker.dhan.mapping.transform_data import map_exchange_type
import urllib.parse
import logging
import jwt
import requests

# Configure logging
logger = logging.getLogger(__name__)


def get_api_response(endpoint, auth, method="POST", payload=''):
    AUTH_TOKEN = auth
    client_id = os.getenv('BROKER_API_KEY')
    
    if not client_id:
        raise Exception("Could not extract client ID from auth token")
    
    conn = http.client.HTTPSConnection("api.dhan.co")
    headers = {
        'access-token': AUTH_TOKEN,
        'client-id': client_id,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    
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
    if response.get('status') == 'failed':
        error_data = response.get('data', {})  
        error_code = list(error_data.keys())[0] if error_data else 'unknown'
        error_message = error_data.get(error_code, 'Unknown error')
        
        error_mapping = {
            '806': "Data APIs not subscribed. Please subscribe to Dhan's market data service.",
            '810': "Authentication failed: Invalid client ID",
            '401': "Invalid or expired access token",
            '820': "Market data subscription required",
            '821': "Market data subscription required"
        }
        
        error_msg = error_mapping.get(error_code, f"Dhan API Error {error_code}: {error_message}")
        logger.error(f"API Error: {error_msg}")
        raise Exception(error_msg)
    
    return response

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Dhan data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Dhan resolutions
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

    def _get_intraday_chunks(self, start_date: str, end_date: str) -> list:
        """Split date range into 5-day chunks for intraday data"""
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        chunks = []
        
        while start < end:
            chunk_end = min(start + timedelta(days=5), end)
            chunks.append((
                start.strftime("%Y-%m-%d"),
                chunk_end.strftime("%Y-%m-%d")
            ))
            start = chunk_end
            
        return chunks

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
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Check if interval is supported
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(f"Unsupported interval '{interval}'. Supported intervals are: {', '.join(supported)}")

            # Convert symbol to broker format and get securityId
            security_id = get_token(symbol, exchange)
            if not security_id:
                raise Exception(f"Could not find security ID for {symbol} on {exchange}")
            
            # Map exchange to Dhan's format
            exchange_map = {
                'NSE': 'NSE_EQ',
                'BSE': 'BSE_EQ',
                'NFO': 'NSE_FNO',
                'MCX': 'MCX_COMM'
            }
            exchange_segment = exchange_map.get(exchange)
            if not exchange_segment:
                raise Exception(f"Unsupported exchange: {exchange}")

            all_candles = []

            # Choose endpoint and prepare request data
            if interval == 'D':
                # For daily data, make a single request
                endpoint = "/v2/charts/historical"
                request_data = {
                    "securityId": str(security_id),
                    "exchangeSegment": exchange_segment,
                    "instrument": "EQUITY",
                    "expiryCode": 0,
                    "fromDate": start_date,
                    "toDate": end_date
                }
                
                logger.info(f"Making daily history request to {endpoint}")
                logger.info(f"Request data: {json.dumps(request_data, indent=2)}")
                
                response = get_api_response(endpoint, self.auth_token, "POST", json.dumps(request_data))
                
                # Process response
                timestamps = response.get('timestamp', [])
                opens = response.get('open', [])
                highs = response.get('high', [])
                lows = response.get('low', [])
                closes = response.get('close', [])
                volumes = response.get('volume', [])

                for i in range(len(timestamps)):
                    all_candles.append({
                        'timestamp': timestamps[i],
                        'open': float(opens[i]) if opens[i] else 0,
                        'high': float(highs[i]) if highs[i] else 0,
                        'low': float(lows[i]) if lows[i] else 0,
                        'close': float(closes[i]) if closes[i] else 0,
                        'volume': int(float(volumes[i])) if volumes[i] else 0
                    })
            else:
                # For intraday data, split into 5-day chunks
                endpoint = "/v2/charts/intraday"
                date_chunks = self._get_intraday_chunks(start_date, end_date)
                
                for chunk_start, chunk_end in date_chunks:
                    request_data = {
                        "securityId": str(security_id),
                        "exchangeSegment": exchange_segment,
                        "instrument": "EQUITY",
                        "interval": self.timeframe_map[interval],
                        "fromDate": chunk_start,
                        "toDate": chunk_end
                    }
                    
                    logger.info(f"Making intraday history request to {endpoint}")
                    logger.info(f"Request data: {json.dumps(request_data, indent=2)}")
                    
                    try:
                        response = get_api_response(endpoint, self.auth_token, "POST", json.dumps(request_data))
                        
                        # Process response
                        timestamps = response.get('timestamp', [])
                        opens = response.get('open', [])
                        highs = response.get('high', [])
                        lows = response.get('low', [])
                        closes = response.get('close', [])
                        volumes = response.get('volume', [])

                        for i in range(len(timestamps)):
                            all_candles.append({
                                'timestamp': timestamps[i],
                                'open': float(opens[i]) if opens[i] else 0,
                                'high': float(highs[i]) if highs[i] else 0,
                                'low': float(lows[i]) if lows[i] else 0,
                                'close': float(closes[i]) if closes[i] else 0,
                                'volume': int(float(volumes[i])) if volumes[i] else 0
                            })
                    except Exception as e:
                        logger.error(f"Error fetching chunk {chunk_start} to {chunk_end}: {str(e)}")
                        continue  # Continue with next chunk if one fails

            # Convert all candles to DataFrame
            df = pd.DataFrame(all_candles)
            if df.empty:
                df = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            else:
                # Sort by timestamp and remove duplicates
                df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)

            return df

        except Exception as e:
            logger.error(f"Error fetching historical data: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")

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