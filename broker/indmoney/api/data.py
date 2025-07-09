import json
import os
from datetime import datetime, timedelta
import pandas as pd
from database.token_db import get_token
import httpx
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from broker.indmoney.api.baseurl import get_url

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
        raise Exception(f"Failed to make request to Indmoney API: {str(req_error)}")
    
    # Add status attribute for compatibility with existing codebase
    res.status = res.status_code
    
    logger.info(f"Response status: {res.status}")
    logger.info(f"Raw response text: {res.text}")
    
    # Check if response is successful
    if res.status_code != 200:
        logger.error(f"HTTP Error {res.status_code}: {res.text}")
        raise Exception(f"Indmoney API HTTP Error {res.status_code}: {res.text}")
    
    # Try to parse JSON response
    try:
        response = json.loads(res.text)
        logger.info(f"Parsed JSON response keys: {list(response.keys())}")
        logger.info(f"Response status field: '{response.get('status')}'")
        logger.info(f"Status field type: {type(response.get('status'))}")
        logger.info(f"Status field length: {len(str(response.get('status')))}")
        logger.info(f"Status field repr: {repr(response.get('status'))}")
        
        # Check if this is a successful data response even without explicit status
        if 'data' in response and isinstance(response['data'], list) and len(response['data']) > 0:
            logger.info("Response contains data array, treating as successful")
            # For historical data responses that don't have explicit status, add it
            if 'status' not in response:
                response['status'] = 'success'
                logger.info("Added missing status field to successful data response")
        
        # Log full response only for smaller responses to avoid spam
        if len(res.text) < 5000:
            logger.info(f"Full JSON response: {json.dumps(response, indent=2)}")
        else:
            logger.info(f"Large response received ({len(res.text)} chars), logging summary only")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        logger.error(f"Response text that failed to parse: {res.text}")
        raise Exception(f"Indmoney API returned invalid JSON: {str(e)}")
    
    # Handle Indmoney API error responses
    response_status = response.get('status')
    
    # Check if this is a successful data response even without explicit status
    if 'data' in response and isinstance(response['data'], list) and len(response['data']) > 0:
        logger.info("Response contains valid data array, treating as successful")
        # For historical data responses that don't have explicit status, add it
        if 'status' not in response or response_status != 'success':
            response['status'] = 'success'
            logger.info("Added/corrected missing status field to successful data response")
        return response
    
    # Only check status if there's no valid data
    if response_status != 'success':
        error_message = response.get('message', response.get('error', 'Unknown error'))
        error_code = response.get('code', 'unknown')
        logger.error(f"API Error - Status: '{response_status}' (code: {error_code}): {error_message}")
        logger.error(f"Full error response: {json.dumps(response, indent=2)}")
        raise Exception(f"Indmoney API Error ({error_code}): {error_message}")
    else:
        logger.info(f"API response successful with status: '{response_status}'")
    
    return response

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Indmoney data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Indmoney resolutions
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
        """Convert symbol and exchange to Indmoney scrip code format"""
        # Get security ID/token for the symbol
        security_id = get_token(symbol, exchange)
        if not security_id:
            raise Exception(f"Could not find security ID for {symbol} on {exchange}")
        
        # Map exchange to Indmoney segment
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

    def _clean_number(self, value, default=0):
        """Clean comma-separated number strings and convert to appropriate type"""
        if value is None:
            return default
        
        # Convert to string and remove commas
        clean_value = str(value).replace(',', '').strip()
        
        # Handle empty or invalid values
        if not clean_value or clean_value == '':
            return default
            
        try:
            # Try to convert to float first, then to int if it's a whole number
            float_val = float(clean_value)
            if float_val.is_integer():
                return int(float_val)
            return float_val
        except (ValueError, AttributeError):
            return default

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
                # Try the /full endpoint first for comprehensive quote data
                full_response = get_api_response("/market/quotes/full", self.auth_token, "GET", params)
                logger.info(f"Full quotes response: {full_response}")
                full_data = full_response.get('data', {}).get(scrip_code, {})
                
                if full_data and any(key in full_data for key in ['ltp', 'live_price', 'open', 'high', 'low']):
                    # Extract data from full quotes response
                    result = {
                        'ltp': self._clean_number(full_data.get('live_price', full_data.get('ltp', 0))),
                        'open': self._clean_number(full_data.get('day_open', 0)),
                        'high': self._clean_number(full_data.get('day_high', 0)),
                        'low': self._clean_number(full_data.get('day_low', 0)),
                        'volume': self._clean_number(full_data.get('volume', 0)),
                        'prev_close': self._clean_number(full_data.get('prev_close', full_data.get('close', 0))),
                        'oi': self._clean_number(full_data.get('oi', full_data.get('open_interest', 0))),
                        'bid': 0,  # Will try to get from market depth if available
                        'ask': 0   # Will try to get from market depth if available
                    }
                    
                    # Try to extract bid/ask from market depth if available in full response
                    market_depth_container = full_data.get('market_depth', {})
                    market_depth = market_depth_container.get(scrip_code, {})
                    depth_levels = market_depth.get('depth', [])
                    
                    if depth_levels and len(depth_levels) > 0:
                        first_level = depth_levels[0]
                        if 'buy' in first_level:
                            result['bid'] = self._clean_number(first_level['buy'].get('price', 0))
                        if 'sell' in first_level:
                            result['ask'] = self._clean_number(first_level['sell'].get('price', 0))
                    
                    logger.info(f"Successfully fetched full quotes: {result}")
                    return result
                
            except Exception as full_error:
                logger.warning(f"Full quotes endpoint failed, falling back to separate calls: {str(full_error)}")
                
            # Fallback to separate LTP and market depth calls
            ltp_data = {}
            bid_price = 0
            ask_price = 0
            
            # Get LTP data
            try:
                ltp_response = get_api_response("/market/quotes/ltp", self.auth_token, "GET", params)
                logger.info(f"LTP Response: {ltp_response}")
                ltp_data = ltp_response.get('data', {}).get(scrip_code, {})
            except Exception as ltp_error:
                logger.warning(f"Could not fetch LTP data: {str(ltp_error)}")
            
            # Get market depth for bid/ask
            try:
                depth_response = get_api_response("/market/quotes/mkt", self.auth_token, "GET", params)
                depth_raw = depth_response.get('data', {}).get(scrip_code, {})
                
                # Handle the extra nesting level in market depth
                market_depth_container = depth_raw.get('market_depth', {})
                market_depth = market_depth_container.get(scrip_code, {})
                depth_levels = market_depth.get('depth', [])
                
                if depth_levels and len(depth_levels) > 0:
                    first_level = depth_levels[0]
                    if 'buy' in first_level and 'price' in first_level['buy']:
                        bid_price = self._clean_number(first_level['buy']['price'])
                    if 'sell' in first_level and 'price' in first_level['sell']:
                        ask_price = self._clean_number(first_level['sell']['price'])
                        
                logger.info(f"Extracted bid: {bid_price}, ask: {ask_price}")
                        
            except Exception as depth_error:
                logger.warning(f"Could not fetch depth data for quotes: {str(depth_error)}")
            
            # Build the final result
            result = {
                'ltp': self._clean_number(ltp_data.get('live_price', 0)) if ltp_data else 0,
                'open': 0,  # OHLC data not available from LTP endpoint
                'high': 0,
                'low': 0,
                'volume': 0,  # Volume not available from LTP endpoint
                'oi': 0,  # Open interest not available
                'bid': bid_price,
                'ask': ask_price,
                'prev_close': 0  # Previous close not available from LTP endpoint
            }
            
            logger.info(f"Final quotes result: {result}")
            return result
                
        except Exception as e:
            logger.error(f"Error in get_quotes: {str(e)}", exc_info=True)
            # Return default structure with error info
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
                # Get market depth from Indmoney API
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
                # Indmoney has an extra nesting level with the scrip code
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
                        
                        # Use _clean_number to handle comma-separated values
                        bids.append({
                            'price': self._clean_number(buy_data.get('price', 0)),
                            'quantity': self._clean_number(buy_data.get('quantity', 0))
                        })
                        
                        asks.append({
                            'price': self._clean_number(sell_data.get('price', 0)),
                            'quantity': self._clean_number(sell_data.get('quantity', 0))
                        })
                    else:
                        bids.append({'price': 0, 'quantity': 0})
                        asks.append({'price': 0, 'quantity': 0})
                
                # Calculate total buy/sell quantities
                # Try to get from aggregate data first, then calculate from depth
                try:
                    total_buy = aggregate.get('total_buy', '0')
                    total_sell = aggregate.get('total_sell', '0')
                    
                    # Use _clean_number to handle comma-separated values
                    totalbuyqty = self._clean_number(total_buy) if total_buy else sum(bid['quantity'] for bid in bids)
                    totalsellqty = self._clean_number(total_sell) if total_sell else sum(ask['quantity'] for ask in asks)
                except:
                    # Fallback to calculation from depth
                    totalbuyqty = sum(bid['quantity'] for bid in bids)
                    totalsellqty = sum(ask['quantity'] for ask in asks)
                
                # Build final result - use LTP data if available, otherwise use bid/ask prices
                ltp_price = 0
                if quotes_data and 'live_price' in quotes_data:
                    ltp_price = self._clean_number(quotes_data.get('live_price', 0))
                elif bids and bids[0]['price'] > 0:
                    # If no LTP available, use best bid price as approximation
                    ltp_price = bids[0]['price']
                
                result = {
                    'bids': bids,
                    'asks': asks,
                    'ltp': ltp_price,
                    'ltq': 0,  # Last traded quantity not available in Indmoney API
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
                     Minutes: 1m, 5m, 15m, 30m
                     Hours: 1h, 2h, 3h, 4h
                     Days: D
            start_date: Start date (YYYY-MM-DD) in IST
            end_date: End date (YYYY-MM-DD) in IST
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume, oi]
        """
        try:
            # Map OpenAlgo intervals to Indmoney intervals
            interval_map = {
                '1m': '1minute',
                '2m': '2minute', 
                '3m': '3minute',
                '4m': '4minute',
                '5m': '5minute',
                '10m': '10minute',
                '15m': '15minute',
                '30m': '30minute',
                '1h': '60minute',
                '2h': '120minute',
                '3h': '180minute', 
                '4h': '240minute',
                'D': '1day'
            }
            
            if interval not in interval_map:
                supported = list(interval_map.keys())
                raise Exception(f"Unsupported interval '{interval}'. Supported intervals are: {', '.join(supported)}")
            
            indmoney_interval = interval_map[interval]
            scrip_code = self._get_scrip_code(symbol, exchange)
            
            logger.info(f"Getting history for symbol: {symbol}, exchange: {exchange}")
            logger.info(f"Interval: {interval} -> {indmoney_interval}")
            logger.info(f"Date range: {start_date} to {end_date}")
            logger.info(f"Using scrip code: {scrip_code}")
            
            # Convert dates to Unix timestamps (milliseconds) in IST
            start_timestamp = self._date_to_timestamp_ms(start_date)
            end_timestamp = self._date_to_timestamp_ms(end_date, end_of_day=True)
            
            logger.info(f"Timestamp range: {start_timestamp} to {end_timestamp}")
            
            # Check if date range exceeds Indmoney limits
            max_ranges = {
                '1second': 1, '5second': 1, '10second': 1, '15second': 1,  # 1 day
                '1minute': 7, '2minute': 7, '3minute': 7, '4minute': 7, '5minute': 7,  # 7 days
                '10minute': 7, '15minute': 7, '30minute': 7,  # 7 days
                '60minute': 14, '120minute': 14, '180minute': 14, '240minute': 14,  # 14 days
                '1day': 365, '1week': 365, '1month': 365  # 1 year
            }
            
            max_days = max_ranges.get(indmoney_interval, 7)
            date_chunks = self._split_date_range(start_date, end_date, max_days)
            
            logger.info(f"Split into {len(date_chunks)} chunks: {date_chunks}")
            
            all_candles = []
            
            for chunk_start, chunk_end in date_chunks:
                try:
                    chunk_start_ts = self._date_to_timestamp_ms(chunk_start)
                    chunk_end_ts = self._date_to_timestamp_ms(chunk_end, end_of_day=True)
                    
                    params = {
                        'scrip-codes': scrip_code,
                        'start_time': str(chunk_start_ts),
                        'end_time': str(chunk_end_ts)
                    }
                    
                    endpoint = f"/market/historical/{indmoney_interval}"
                    logger.info(f"Fetching chunk {chunk_start} to {chunk_end}")
                    logger.info(f"Request params: {params}")
                    
                    response = get_api_response(endpoint, self.auth_token, "GET", params)
                    
                    # Extract candles from response - handle actual Indmoney format
                    candles_data = response.get('data', [])
                    logger.info(f"Received {len(candles_data)} candles for chunk")
                    
                    # Transform Indmoney candle format to OpenAlgo format
                    chunk_candles = []
                    for candle in candles_data:
                        try:
                            # Handle the actual format: {"ts": timestamp, "o": open, "h": high, "l": low, "c": close, "v": volume}
                            if isinstance(candle, dict) and 'ts' in candle:
                                # Indmoney returns timestamp in seconds already
                                timestamp_seconds = int(candle.get('ts', 0))
                                
                                chunk_candles.append({
                                    'timestamp': timestamp_seconds,
                                    'open': float(candle.get('o', 0)),
                                    'high': float(candle.get('h', 0)), 
                                    'low': float(candle.get('l', 0)),
                                    'close': float(candle.get('c', 0)),
                                    'volume': int(candle.get('v', 0)),
                                    'oi': 0  # Open interest not available in Indmoney historical data
                                })
                            # Also handle documented format as fallback
                            elif isinstance(candle, list) and len(candle) >= 6:
                                # Convert timestamp from milliseconds to seconds
                                timestamp_seconds = int(candle[0] / 1000)
                                
                                chunk_candles.append({
                                    'timestamp': timestamp_seconds,
                                    'open': float(candle[1]),
                                    'high': float(candle[2]), 
                                    'low': float(candle[3]),
                                    'close': float(candle[4]),
                                    'volume': int(candle[5]) if candle[5] else 0,
                                    'oi': 0  # Open interest not available in Indmoney historical data
                                })
                        except Exception as candle_error:
                            logger.error(f"Error processing individual candle {candle}: {str(candle_error)}")
                            continue
                    
                    logger.info(f"Successfully processed {len(chunk_candles)} candles from chunk")
                    all_candles.extend(chunk_candles)
                    
                except Exception as chunk_error:
                    logger.error(f"Error fetching chunk {chunk_start} to {chunk_end}: {str(chunk_error)}")
                    logger.error(f"Chunk error type: {type(chunk_error).__name__}")
                    logger.error(f"Chunk error details: {repr(chunk_error)}")
                    import traceback
                    logger.error(f"Full traceback: {traceback.format_exc()}")
                    continue

            logger.info(f"Total candles collected from all chunks: {len(all_candles)}")
            
            # Create DataFrame from all candles
            if all_candles:
                df = pd.DataFrame(all_candles)
                # Sort by timestamp and remove duplicates
                df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)
                logger.info(f"Successfully fetched {len(df)} candles after deduplication")
                logger.info(f"Sample data: {df.head(3).to_dict('records') if len(df) > 0 else 'No data'}")
            else:
                df = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                logger.warning("No historical data received from any chunks")
            
            return df
            
        except Exception as e:
            logger.error(f"Error fetching historical data: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")
    
    def _date_to_timestamp_ms(self, date_str: str, end_of_day: bool = False) -> int:
        """Convert date string to Unix timestamp in milliseconds (IST)"""
        from datetime import datetime
        
        if end_of_day:
            # For end date, use end of day (23:59:59)
            dt = datetime.strptime(f"{date_str} 23:59:59", "%Y-%m-%d %H:%M:%S")
        else:
            # For start date, use start of day (00:00:00)
            dt = datetime.strptime(f"{date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")
        
        # Convert to Unix timestamp and then to milliseconds
        timestamp_ms = int(dt.timestamp() * 1000)
        return timestamp_ms
    
    def _split_date_range(self, start_date: str, end_date: str, max_days: int) -> list:
        """Split date range into chunks based on Indmoney API limits"""
        from datetime import datetime, timedelta
        
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        chunks = []
        
        current = start
        while current < end:
            chunk_end = min(current + timedelta(days=max_days - 1), end)
            chunks.append((
                current.strftime("%Y-%m-%d"),
                chunk_end.strftime("%Y-%m-%d")
            ))
            current = chunk_end + timedelta(days=1)
        
        return chunks