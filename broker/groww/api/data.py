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
        print(f'exchange: {exchange}')
        if exchange == "NSE":
            exchange_segment = "NSE_EQ"
        elif exchange == "BSE":
            exchange_segment = "BSE_EQ"
        elif exchange == "NSE_INDEX":
            exchange_segment = "IDX_I"
        elif exchange == "BSE_INDEX":
            exchange_segment = "IDX_I"
        else:
            raise ValueError(f"Unsupported exchange: {exchange}")
            
        return security_id, exchange_segment

    def _convert_date_to_utc(self, date_str: str) -> str:
        """Convert IST date to UTC date for API request"""
        # Simply return the date string as the API expects YYYY-MM-DD format
        return date_str

    def _convert_timestamp_to_ist(self, timestamp: int) -> int:
        """Convert UTC timestamp to IST timestamp"""
        # Convert to datetime in UTC
        utc_dt = datetime.utcfromtimestamp(timestamp)
        # Add IST offset (+5:30)
        ist_dt = utc_dt + timedelta(hours=5, minutes=30)
        # Return new timestamp
        return int(ist_dt.timestamp())

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

    def _get_exchange_segment(self, exchange: str) -> str:
        """Get exchange segment based on exchange"""
        exchange_map = {
            'NSE': 'NSE_EQ',      # NSE Cash
            'BSE': 'BSE_EQ',      # BSE Cash
            'NFO': 'NSE_FNO',     # NSE F&O
            'BFO': 'BSE_FNO',     # BSE F&O
            'MCX': 'MCX_COMM',    # MCX Commodity
            'CDS': 'NSE_CURRENCY',  # NSE Currency
            'BCD': 'BSE_CURRENCY',   # BSE Currency
            'NSE_INDEX': 'IDX_I',  # NSE Index
            'BSE_INDEX': 'IDX_I'   # BSE Index
        }
        return exchange_map.get(exchange)

    def _get_instrument_type(self, exchange: str, symbol: str) -> str:
        """Get instrument type based on exchange and symbol"""
        # For cash market (NSE, BSE)
        if exchange in ['NSE', 'BSE']:
            return 'EQUITY'
        
        elif exchange in ['NSE_INDEX', 'BSE_INDEX']:
            return 'INDEX'


            
        # For F&O market (NFO, BFO)
        elif exchange in ['NFO', 'BFO']:
            # First check for options (CE/PE at the end)
            if symbol.endswith('CE') or symbol.endswith('PE'):
                # For index options like NIFTY23JAN20200CE
                if any(index in symbol for index in [
                    'NIFTY', 'NIFTYNXT50', 'FINNIFTY', 'BANKNIFTY', 
                    'MIDCPNIFTY', 'INDIAVIX', 'SENSEX', 'BANKEX', 'SENSEX50']):
                    return 'OPTIDX'
                # For stock options
                return 'OPTSTK'
            # Then check for futures
            else:
                # For index futures like NIFTY23JAN
                if any(index in symbol for index in [
                    'NIFTY', 'NIFTYNXT50', 'FINNIFTY', 'BANKNIFTY', 
                    'MIDCPNIFTY', 'INDIAVIX', 'SENSEX', 'BANKEX', 'SENSEX50']):
                    return 'FUTIDX'
                # For stock futures
                return 'FUTSTK'
        
        # For commodity market (MCX)
        elif exchange == 'MCX':
            # For commodity options on futures
            if symbol.endswith('CE') or symbol.endswith('PE'):
                return 'OPTFUT'
            # For commodity futures
            return 'FUTCOM'
        
        # For currency market (CDS, BCD)
        elif exchange in ['CDS', 'BCD']:
            # For currency options
            if symbol.endswith('CE') or symbol.endswith('PE'):
                return 'OPTCUR'
            # For currency futures
            return 'FUTCUR'
        
        raise Exception(f"Unsupported exchange: {exchange}")

    def _is_trading_day(self, date_str: str) -> bool:
        """Check if the given date is a trading day (not weekend)"""
        date = datetime.strptime(date_str, "%Y-%m-%d")
        return date.weekday() < 5  # 0-4 are Monday to Friday

    def _adjust_dates(self, start_date: str, end_date: str) -> tuple:
        """Adjust dates to nearest trading days"""
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        
        # If start date is weekend, move to next Monday
        while start.weekday() >= 5:
            start += timedelta(days=1)
            
        # If end date is weekend, move to previous Friday
        while end.weekday() >= 5:
            end -= timedelta(days=1)
            
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    def _get_intraday_time_range(self, date_str: str) -> tuple:
        """
        Get intraday time range in IST for a given date
        Args:
            date_str: Date string in YYYY-MM-DD format
        Returns:
            tuple: (start_date, end_date) in YYYY-MM-DD format
        """
        # Simply return the same date for both start and end
        # The API will handle the full day's data automatically
        return date_str, date_str

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
            # Check if interval is supported
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(f"Unsupported interval '{interval}'. Supported intervals are: {', '.join(supported)}")

            # Adjust dates for trading days
            start_date, end_date = self._adjust_dates(start_date, end_date)
            
            # If both dates are weekends, return empty DataFrame
            if not self._is_trading_day(start_date) and not self._is_trading_day(end_date):
                logger.info("Both start and end dates are non-trading days")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

            # If start and end dates are same, increase end date by one day
            if start_date == end_date:
                end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                end_date = end_dt.strftime("%Y-%m-%d")
                logger.info(f"Start and end dates are same, increasing end date to: {end_date}")

            # Convert symbol to broker format and get securityId
            security_id = get_token(symbol, exchange)
            if not security_id:
                raise Exception(f"Could not find security ID for {symbol} on {exchange}")
            print(f'exchange: {exchange}')
            # Get exchange segment and instrument type
            exchange_segment = self._get_exchange_segment(exchange)
            if not exchange_segment:
                raise Exception(f"Unsupported exchange: {exchange}")
            print(f'exchange segment: {exchange_segment}')
            instrument_type = self._get_instrument_type(exchange, symbol)
            
            all_candles = []

            # Choose endpoint and prepare request data
            if interval == 'D':
                # For daily data, use historical endpoint
                endpoint = "/v2/charts/historical"
                
                # Convert dates to UTC for API request
                utc_start_date = self._convert_date_to_utc(start_date)
                # For end date, add one day to include the end date in results
                end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
                utc_end_date = self._convert_date_to_utc(end_dt.strftime("%Y-%m-%d"))
                
                request_data = {
                    "securityId": str(security_id),
                    "exchangeSegment": exchange_segment,
                    "instrument": instrument_type,
                    "fromDate": utc_start_date,
                    "toDate": utc_end_date
                }
                
                # Add expiryCode only for EQUITY
                if instrument_type == 'EQUITY':
                    request_data["expiryCode"] = 0
                
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
                    # Convert UTC timestamp to IST
                    ist_timestamp = self._convert_timestamp_to_ist(timestamps[i])
                    all_candles.append({
                        'timestamp': ist_timestamp,
                        'open': float(opens[i]) if opens[i] else 0,
                        'high': float(highs[i]) if highs[i] else 0,
                        'low': float(lows[i]) if lows[i] else 0,
                        'close': float(closes[i]) if closes[i] else 0,
                        'volume': int(float(volumes[i])) if volumes[i] else 0
                    })
            else:
                # For intraday data
                endpoint = "/v2/charts/intraday"
                
                if start_date == (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"):
                    # For same day intraday data, use exact time range in IST
                    from_time = start_date
                    to_time = end_date  # This will be the next day as adjusted above
                    
                    request_data = {
                        "securityId": str(security_id),
                        "exchangeSegment": exchange_segment,
                        "instrument": instrument_type,
                        "interval": self.timeframe_map[interval],
                        "fromDate": from_time,
                        "toDate": to_time
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
                            # Convert UTC timestamp to IST
                            ist_timestamp = self._convert_timestamp_to_ist(timestamps[i])
                            all_candles.append({
                                'timestamp': ist_timestamp,
                                'open': float(opens[i]) if opens[i] else 0,
                                'high': float(highs[i]) if highs[i] else 0,
                                'low': float(lows[i]) if lows[i] else 0,
                                'close': float(closes[i]) if closes[i] else 0,
                                'volume': int(float(volumes[i])) if volumes[i] else 0
                            })
                    except Exception as e:
                        logger.error(f"Error fetching intraday data: {str(e)}")
                else:
                    # For multiple days, split into chunks
                    date_chunks = self._get_intraday_chunks(start_date, end_date)
                    
                    for chunk_start, chunk_end in date_chunks:
                        # Skip if both dates are non-trading days
                        if not self._is_trading_day(chunk_start) and not self._is_trading_day(chunk_end):
                            continue

                        # Get time range for each day
                        from_time, _ = self._get_intraday_time_range(chunk_start)
                        _, to_time = self._get_intraday_time_range(chunk_end)

                        request_data = {
                            "securityId": str(security_id),
                            "exchangeSegment": exchange_segment,
                            "instrument": instrument_type,
                            "interval": self.timeframe_map[interval],
                            "fromDate": from_time,
                            "toDate": to_time
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
                                # Convert UTC timestamp to IST
                                ist_timestamp = self._convert_timestamp_to_ist(timestamps[i])
                                all_candles.append({
                                    'timestamp': ist_timestamp,
                                    'open': float(opens[i]) if opens[i] else 0,
                                    'high': float(highs[i]) if highs[i] else 0,
                                    'low': float(lows[i]) if lows[i] else 0,
                                    'close': float(closes[i]) if closes[i] else 0,
                                    'volume': int(float(volumes[i])) if volumes[i] else 0
                                })
                        except Exception as e:
                            logger.error(f"Error fetching chunk {chunk_start} to {chunk_end}: {str(e)}")
                            continue

            # For daily timeframe, check if today's date is within the range
            if interval == 'D':
                today = datetime.now().strftime("%Y-%m-%d")
                if start_date <= today <= end_date:
                    logger.info("Today's date is within range for daily timeframe, fetching current day data from quotes API")
                    try:
                        # Get today's data from quotes API
                        quotes = self.get_quotes(symbol, exchange)
                        if quotes and quotes.get('ltp', 0) > 0:  # Only add if we got valid data
                            today_candle = {
                                'timestamp': int(datetime.strptime(today + " 15:30:00", "%Y-%m-%d %H:%M:%S").timestamp()),
                                'open': float(quotes.get('open', 0)),
                                'high': float(quotes.get('high', 0)),
                                'low': float(quotes.get('low', 0)),
                                'close': float(quotes.get('ltp', 0)),  # Use LTP as current close
                                'volume': int(quotes.get('volume', 0))
                            }
                            all_candles.append(today_candle)
                    except Exception as e:
                        logger.error(f"Error fetching today's data from quotes: {str(e)}")

            # Create DataFrame from all candles
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
                
            except Exception as e:
                if "not subscribed" in str(e).lower():
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
                        'error': str(e)
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