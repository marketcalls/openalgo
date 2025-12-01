import json
import os
import urllib.parse
from database.token_db import get_br_symbol, get_oa_symbol, get_brexchange
from broker.fivepaisaxts.database.master_contract_db import SymToken, db_session
from flask import session  
import pandas as pd
from datetime import datetime, timedelta
from utils.httpx_client import get_httpx_client
from database.auth_db import get_feed_token
from broker.fivepaisaxts.baseurl import MARKET_DATA_URL
import pytz
from utils.logging import get_logger

logger = get_logger(__name__)

# Configure logging
logger = get_logger(__name__)

def get_api_response(endpoint, auth, method="GET", payload='', feed_token=None, params=None):
    AUTH_TOKEN = auth
    FEED_TOKEN = feed_token
    if feed_token:
        logger.debug("Feed token provided")
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'authorization': FEED_TOKEN if feed_token else AUTH_TOKEN,
        'Content-Type': 'application/json'
    }

    
    base_url = MARKET_DATA_URL  # Default to market data URL

    url = f"{base_url}{endpoint}"
    
    try:
        # Log request details
        logger.debug("=== API Request Details ===")
        logger.debug(f"URL: {url}")
        logger.debug(f"Method: {method}")
        logger.debug(f"Headers: {json.dumps(headers, indent=2)}")
        if params:
            logger.debug(f"Query Params: {json.dumps(params, indent=2)}")
        if payload and payload != '':
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError:
                    logger.error("Failed to parse payload as JSON")
                    raise Exception("Invalid payload format")
            logger.debug(f"Payload: {json.dumps(payload, indent=2)}")

        # Perform the request
        if method.upper() == "GET":
            response = client.get(url, headers=headers, params=params)
        elif method.upper() == "POST":
            response = client.post(url, headers=headers, json=payload)
        else:
            response = client.request(method, url, headers=headers, json=payload)

        # Log response details
        logger.debug("=== API Response Details ===")
        logger.debug(f"Status Code: {response.status_code}")
        logger.debug(f"Response Headers: {dict(response.headers)}")
        logger.debug(f"Response Body: {response.text}")

        # Add status attribute for compatibility
        response.status = response.status_code
        return response.json()

    except Exception as e:
        logger.error(f"API request failed: {str(e)}")
        raise

class BrokerData:
    def __init__(self, auth_token, feed_token=None, user_id=None):
        """Initialize FivepaisaXTS data handler with authentication token"""
        self.auth_token = auth_token
        self.feed_token = feed_token
        self.user_id = user_id
        
        # Map common timeframe format to FivepaisaXTS intervals
        self.timeframe_map = {
            "1s": "1", "1m": "60", "2m": "120", "3m": "180", "5m": "300",
                "10m": "600", "15m": "900", "30m": "1800", "60m": "3600",
                "D": "D"
        }
        

    def _get_instrument_token(self, symbol: str, exchange: str) -> tuple:
        """
        Helper method to get instrument token and exchange segment
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            tuple: (token_info, exchange_segment)
        """
        # Exchange segment mapping
        exchange_segment_map = {
            "NSE": 1,
            "NSE_INDEX": 1,  # NSE indices use the same segment as NSE
            "NFO": 2,
            "CDS": 3,
            "BSE": 11,
            "BSE_INDEX": 11,  # BSE indices use the same segment as BSE
            "BFO": 12,
            "MCX": 51
        }
        
        # Convert symbol to broker format
        br_symbol = get_br_symbol(symbol, exchange)
        
        brexchange = exchange_segment_map.get(exchange)
        if brexchange is None:
            raise Exception(f"Unknown exchange segment: {exchange}")
            
        # Get exchange_token from database
        with db_session() as session:
            symbol_info = session.query(SymToken).filter(
                SymToken.exchange == exchange,
                SymToken.brsymbol == br_symbol
            ).first()
            
            if not symbol_info:
                raise Exception(f"Could not find exchange token for {exchange}:{br_symbol}")
            
            return symbol_info, brexchange

    def _fetch_market_data(self, token: dict, message_code: int) -> dict:
        """
        Helper method to fetch market data from FivepaisaXTS API
        Args:
            token: Dictionary containing exchangeSegment and exchangeInstrumentID
            message_code: XTS message code (e.g., 1502 for market data, 1510 for OI)
        Returns:
            dict: Parsed market data
        """
        try:
            payload = {
                "instruments": [token],
                "xtsMessageCode": message_code,
                "publishFormat": "JSON"
            }
            
            response = get_api_response(
                "/instruments/quotes",
                self.auth_token,
                method="POST",
                payload=payload,
                feed_token=self.feed_token
            )
            
            if not response or response.get('type') != 'success':
                error_msg = response.get('description', 'Unknown error') if response else 'No response'
                logger.warning(f"Error fetching market data (code {message_code}): {error_msg}")
                return None
                
            # Handle empty listQuotes array
            list_quotes = response.get('result', {}).get('listQuotes', [])
            if not list_quotes:
                logger.warning(f"Empty listQuotes in response (code {message_code})")
                return None
                
            raw_data = list_quotes[0]
            if not raw_data:
                logger.warning(f"No data in response (code {message_code})")
                return None
                
            return json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            
        except Exception as e:
            logger.error(f"Error in _fetch_market_data (code {message_code}): {str(e)}", exc_info=True)
            return None

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol including Open Interest
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Quote data with required fields including OI
        """
        try:
            # Get instrument token and exchange segment
            symbol_info, brexchange = self._get_instrument_token(symbol, exchange)

            # Prepare token for API requests
            token = {
                "exchangeSegment": brexchange,
                "exchangeInstrumentID": symbol_info.token
            }

            # Fetch market data (xtsMessageCode 1502)
            market_data = self._fetch_market_data(token, 1502)
            if not market_data:
                raise Exception("Failed to fetch market data")

            # Fetch Open Interest data (xtsMessageCode 1510) - non-blocking
            oi_data = None
            try:
                oi_data = self._fetch_market_data(token, 1510)
            except Exception as e:
                logger.warning(f"Failed to fetch OI data: {str(e)}")

            # Process market data
            touchline = market_data.get('Touchline', {})
            quote_data = {
                'ask': touchline.get('AskInfo', {}).get('Price', 0),
                'bid': touchline.get('BidInfo', {}).get('Price', 0),
                'high': touchline.get('High', 0),
                'low': touchline.get('Low', 0),
                'ltp': touchline.get('LastTradedPrice', 0),
                'open': touchline.get('Open', 0),
                'prev_close': touchline.get('Close', 0),
                'volume': touchline.get('TotalTradedQuantity', 0),
                'oi': 0  # Default value if OI data is not available
            }

            # Add OI data if available
            if oi_data and 'OpenInterest' in oi_data:
                quote_data['oi'] = oi_data['OpenInterest']
                logger.debug(f"Added OI data: {quote_data['oi']}")

            return quote_data

        except Exception as e:
            logger.error(f"Error fetching quotes: {str(e)}")
            raise Exception(f"Error fetching quotes: {str(e)}")

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols with automatic batching
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        import time

        try:
            BATCH_SIZE = 50  # XTS API limit: only 50 instruments allowed per request
            RATE_LIMIT_DELAY = 0.1  # Delay in seconds between batch API calls

            # If symbols exceed batch size, process in batches
            if len(symbols) > BATCH_SIZE:
                logger.info(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
                all_results = []

                # Split symbols into batches
                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i:i + BATCH_SIZE]
                    logger.debug(f"Processing batch {i//BATCH_SIZE + 1}: symbols {i+1} to {min(i+BATCH_SIZE, len(symbols))}")

                    # Process this batch
                    batch_results = self._process_multiquotes_batch(batch)
                    all_results.extend(batch_results)

                    # Rate limit delay between batches
                    if i + BATCH_SIZE < len(symbols):
                        time.sleep(RATE_LIMIT_DELAY)

                logger.info(f"Successfully processed {len(all_results)} quotes in {(len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE} batches")
                return all_results
            else:
                # Single batch processing
                return self._process_multiquotes_batch(symbols)

        except Exception as e:
            logger.exception(f"Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _process_multiquotes_batch(self, symbols: list) -> list:
        """
        Process a single batch of symbols for multiquotes (internal method)
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys (max 50)
        Returns:
            list: List of quote data for the batch
        """
        # Exchange segment mapping
        exchange_segment_map = {
            "NSE": 1,
            "NSE_INDEX": 1,
            "NFO": 2,
            "CDS": 3,
            "BSE": 11,
            "BSE_INDEX": 11,
            "BFO": 12,
            "MCX": 51
        }

        instruments = []
        symbol_map = {}  # Map instrument key to original symbol/exchange
        skipped_symbols = []  # Track symbols that couldn't be resolved

        for item in symbols:
            symbol = item.get('symbol')
            exchange = item.get('exchange')

            if not symbol or not exchange:
                logger.warning(f"Skipping entry due to missing symbol/exchange: {item}")
                skipped_symbols.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'data': None,
                    'error': 'Missing required symbol or exchange'
                })
                continue

            try:
                # Convert symbol to broker format
                br_symbol = get_br_symbol(symbol, exchange)

                brexchange = exchange_segment_map.get(exchange)
                if brexchange is None:
                    logger.warning(f"Skipping symbol {symbol} on {exchange}: unknown exchange segment")
                    skipped_symbols.append({
                        'symbol': symbol,
                        'exchange': exchange,
                        'data': None,
                        'error': f'Unknown exchange segment: {exchange}'
                    })
                    continue

                # Get exchange_token from database
                with db_session() as session:
                    symbol_info = session.query(SymToken).filter(
                        SymToken.exchange == exchange,
                        SymToken.brsymbol == br_symbol
                    ).first()

                    if not symbol_info:
                        logger.warning(f"Skipping symbol {symbol} on {exchange}: could not find token")
                        skipped_symbols.append({
                            'symbol': symbol,
                            'exchange': exchange,
                            'data': None,
                            'error': f'Could not find exchange token for {exchange}:{br_symbol}'
                        })
                        continue

                    instrument = {
                        "exchangeSegment": brexchange,
                        "exchangeInstrumentID": symbol_info.token
                    }
                    instruments.append(instrument)

                    # Create key for mapping response back to original symbol
                    instrument_key = f"{brexchange}_{symbol_info.token}"
                    symbol_map[instrument_key] = {
                        'symbol': symbol,
                        'exchange': exchange,
                        'br_symbol': br_symbol
                    }

            except Exception as e:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: {str(e)}")
                skipped_symbols.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'data': None,
                    'error': str(e)
                })
                continue

        # Return skipped symbols if no valid instruments
        if not instruments:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        results = []

        try:
            # Make API call for market data (xtsMessageCode 1502)
            payload = {
                "instruments": instruments,
                "xtsMessageCode": 1502,
                "publishFormat": "JSON"
            }

            response = get_api_response(
                "/instruments/quotes",
                self.auth_token,
                method="POST",
                payload=payload,
                feed_token=self.feed_token
            )

            if not response or response.get('type') != 'success':
                error_msg = response.get('description', 'Unknown error') if response else 'No response'
                logger.error(f"Error fetching multiquotes: {error_msg}")
                raise Exception(f"Error from FivepaisaXTS API: {error_msg}")

            # Parse response
            list_quotes = response.get('result', {}).get('listQuotes', [])

            for raw_data in list_quotes:
                try:
                    # Parse JSON if string
                    quote_data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data

                    # Extract instrument identifier
                    exchange_segment = quote_data.get('ExchangeSegment')
                    instrument_id = quote_data.get('ExchangeInstrumentID')
                    instrument_key = f"{exchange_segment}_{instrument_id}"

                    # Look up original symbol and exchange
                    original = symbol_map.get(instrument_key)
                    if not original:
                        logger.warning(f"Could not map response for instrument {instrument_key}")
                        continue

                    # Process market data
                    touchline = quote_data.get('Touchline', {})

                    result_item = {
                        'symbol': original['symbol'],
                        'exchange': original['exchange'],
                        'data': {
                            'ask': touchline.get('AskInfo', {}).get('Price', 0),
                            'bid': touchline.get('BidInfo', {}).get('Price', 0),
                            'high': touchline.get('High', 0),
                            'low': touchline.get('Low', 0),
                            'ltp': touchline.get('LastTradedPrice', 0),
                            'open': touchline.get('Open', 0),
                            'prev_close': touchline.get('Close', 0),
                            'volume': touchline.get('TotalTradedQuantity', 0),
                            'oi': 0  # OI requires separate API call (1510), set default
                        }
                    }
                    results.append(result_item)

                except Exception as e:
                    logger.warning(f"Error parsing quote data: {str(e)}")
                    continue

        except Exception as e:
            logger.error(f"Error in _process_multiquotes_batch: {str(e)}")
            raise

        # Include skipped symbols in results
        return skipped_symbols + results

    def get_history(self, symbol, exchange, timeframe, from_date, to_date):
        """Get historical data for a symbol"""
        try:
            
            # Map timeframe to compression value
            compression_map = {
                "1s": "1", "1m": "60", "2m": "120", "3m": "180", "5m": "300",
                "10m": "600", "15m": "900", "30m": "1800", "60m": "3600",
                "D": "D"
            }
            compression_value = compression_map.get(timeframe)
            if not compression_value:
                raise Exception(f"Unsupported timeframe: {timeframe}")

            
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            #token = get_token(symbol, exchange)
            #if not token:
             #   raise Exception(f"Could not find instrument token for {exchange}:{symbol}")

            # Map exchange segment
            segment_map = {
                "NSE": "NSECM",
                "BSE": "BSECM",
                "NFO": "NSEFO",
                "BFO": "BSEFO",
                "CDS": "NSECD",
                "MCX": "MCXFO",
                "NSE_INDEX": "NSECM",
                "BSE_INDEX": "BSECM"
            }
            exchange_segment = segment_map.get(exchange)
            if not exchange_segment:
                raise Exception(f"Unsupported exchange: {exchange}")
             # Get exchange_token from database
            with db_session() as session:
                symbol_info = session.query(SymToken).filter(
                    SymToken.exchange == exchange,
                    SymToken.brsymbol == br_symbol
                ).first()
                
                if not symbol_info:
                    raise Exception(f"Could not find exchange token for {exchange}:{br_symbol}")
                
                # Get the token for quotes
                token = symbol_info.token  # token = instrument ID

    
            # Convert dates to datetime objects with IST timezone
            start_date = pd.to_datetime(from_date).tz_localize('Asia/Kolkata')
            end_date = pd.to_datetime(to_date).tz_localize('Asia/Kolkata')

            # Use start of day for from_date
            from_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

            # Use end of day for to_date
            to_date = end_date.replace(hour=23, minute=59, second=59, microsecond=0)

            dfs = []
            current_start = from_date

            while current_start <= to_date:
                current_end = min(current_start + timedelta(days=6), to_date)

                # FivepaisaXTS expects MMM DD YYYY HHMMSS in IST
                from_str = current_start.strftime('%b %d %Y %H%M%S')
                to_str = current_end.strftime('%b %d %Y %H%M%S')

                logger.debug(f"Fetching {timeframe} data for {exchange}:{symbol}")
                logger.debug(f"Start Time (IST): {current_start}")
                logger.debug(f"End Time (IST): {current_end}")
                logger.debug(f"API Format - From: {from_str}, To: {to_str}")

                params = {
                    "exchangeSegment": exchange_segment,
                    "exchangeInstrumentID": token,
                    "startTime": from_str,
                    "endTime": to_str,
                    "compressionValue": compression_value
                }
                
                logger.debug(f"API Parameters: {json.dumps(params, indent=2)}")

                response = get_api_response("/instruments/ohlc", self.auth_token, method="GET", feed_token=self.feed_token, params=params)

                if not response or response.get('type') != 'success':
                    logger.error(f"API Response: {response}")
                    raise Exception(f"Error from FivepaisaXTS API: {response.get('description', 'Unknown error')}")

                # Parse dataResponse (pipe-delimited string)
                raw_data = response.get('result', {}).get('dataReponse', '')
                if not raw_data:
                    logger.warning(f"No data returned for period {from_str} to {to_str}")
                    current_start = current_end + timedelta(days=1)
                    continue

                rows = raw_data.strip().split(',')
                data = []
                for row in rows:
                    fields = row.split('|')
                    if len(fields) < 6:
                        continue
                    try:
                        data.append({
                            "timestamp": int(fields[0]),
                            "open": float(fields[1]),
                            "high": float(fields[2]),
                            "low": float(fields[3]),
                            "close": float(fields[4]),
                            "volume": int(fields[5])
                        })
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Error parsing row {row}: {e}")
                        continue

                if data:
                    df = pd.DataFrame(data)
                    dfs.append(df)

                current_start = current_end + timedelta(days=1)
            
            if not dfs:
                if compression_value == 'D' and to_date.date() == datetime.now().date():
                    # Get segment ID from exchange - use numeric values
                    #segment_id = 1 if exchange == "NSE" else 2  # 1 for NSECM, 2 for BSECM
                    # Exchange segment mapping
                    exchange_segment_map = {
                        "NSE": 1,
                        "NFO": 2,
                        "CDS": 3,
                        "BSE": 11,
                        "BFO": 12,
                        "MCX": 51
                    }

                    # Determine segment ID based on exchange
                    segment_id = exchange_segment_map.get(exchange)
                    logger.debug(f"Exchange: {{exchange}}, Segment ID: {segment_id}")
                    if segment_id is None:
                        raise ValueError(f"Unknown exchange: {exchange}")
                    payload = {
                        "instruments": [{
                            "exchangeSegment": segment_id,
                            "exchangeInstrumentID": token
                        }],
                        "xtsMessageCode": 1502,
                        "publishFormat": "JSON"
                    }
                    
                    response = get_api_response("/instruments/quotes", self.auth_token, method="POST", payload=payload, feed_token=self.feed_token)
                    
                    if not response or response.get('type') != 'success':
                        raise Exception(f"Error from FivepaisaXTS API: {response.get('description', 'Unknown error')}")
            
                    # Parse quote data from response
                    raw_quotes = response.get('result', {}).get('listQuotes', [])
                    if not raw_quotes:
                        raise Exception("No quote data found in listQuotes")
            
                    # Parse the JSON string in listQuotes
                    quote = json.loads(raw_quotes[0])
                    touchline = quote.get('Touchline', {})
                    logger.debug(f"Parsed Quote Data: {touchline}")
                    
                    if touchline:
                        # For daily data, set timestamp to midnight IST
                        today = datetime.now()
                        # First set to midnight
                        today = today.replace(hour=0, minute=0, second=0, microsecond=0)
                        # Add 5:30 hours to compensate for IST conversion that happens later
                        today = today + timedelta(hours=5, minutes=30)
                        
                        today_candle = {
                            "timestamp": int(today.timestamp()),
                            "open": touchline.get('Open'),
                            "high": touchline.get('High'),
                            "low": touchline.get('Low'),
                            "close": touchline.get('LastTradedPrice'),  # Use LTP as current close
                            "volume": touchline.get('TotalTradedQuantity', 0)
                        }
                        
                        return pd.DataFrame([today_candle], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    else:
                        raise Exception("No Touchline data in quote")
            final_df = pd.concat(dfs, ignore_index=True)

            # Sort by timestamp and remove duplicates
            final_df = final_df.sort_values('timestamp').drop_duplicates('timestamp').reset_index(drop=True)
            
            # Convert timestamps to datetime for manipulation
            final_df['timestamp'] = pd.to_datetime(final_df['timestamp'], unit='s')
            
            if compression_value == 'D':
                # For daily data, set to midnight (00:00:00)
                final_df['timestamp'] = final_df['timestamp'].apply(
                    lambda x: x.replace(hour=0, minute=0, second=0)
                )
            else:
                # For intraday data, subtract 5:30 hours to get to IST
                final_df['timestamp'] = final_df['timestamp'] - pd.Timedelta(hours=5, minutes=30)

                # Round timestamps down to the start of each candle interval
                interval_minutes = int(compression_value) // 60 if compression_value != 'D' else 0
                if interval_minutes > 0:
                    final_df['timestamp'] = final_df['timestamp'].dt.floor(f'{interval_minutes}min')
            
            # Convert back to Unix timestamp
            final_df['timestamp'] = final_df['timestamp'].astype('int64') // 10**9
            
            # Ensure numeric columns are properly typed
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            final_df[numeric_columns] = final_df[numeric_columns].apply(pd.to_numeric)
            
            # Log sample timestamps for verification
            sample_time = pd.to_datetime(final_df['timestamp'].iloc[0], unit='s')
            logger.debug(f"First candle: {sample_time.strftime('%Y-%m-%d') if compression_value == 'D' else sample_time}")
            
            return final_df


        except Exception as e:
            logger.error(f"Error fetching historical data: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")

    def get_intervals(self) -> list:
        """Get available intervals/timeframes for historical data
        
        Returns:
            list: List of available intervals
        """
        return ["1s", "1m", "2m", "3m", "5m", "10m", "15m", "30m", "60m", "D"]

    def get_market_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol via REST API
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data
        """
        try:
            logger.debug(f"=== Starting Market Depth Request ===")
            logger.debug(f"Symbol: {symbol}, Exchange: {exchange}")
            
            # Get feed token and user ID for request
            user_id = None
            feed_token = None
            
            # First check if we have user ID in the instance
            if hasattr(self, 'user_id') and self.user_id:
                user_id = self.user_id
                logger.debug(f"Using instance user_id: {user_id}")
            
            # Try to get from session if not found in instance
            if not user_id and hasattr(session, 'marketdata_userid') and session.get('marketdata_userid'):
                user_id = session.get('marketdata_userid')
                logger.debug(f"Using session user_id: {user_id}")
            
            # If no user ID is available, use the one from feed token authentication
            if not user_id and self.user_id:
                user_id = self.user_id
                logger.debug(f"Using feed token auth user_id: {user_id}")
            
            if not user_id:
                logger.error("No user ID available for market depth request")
                return None
            
            # Get feed token from instance
            if hasattr(self, 'feed_token') and self.feed_token:
                feed_token = self.feed_token
                logger.debug("Using instance feed_token")
            
            # Try to get from session if not found in instance
            if not feed_token and hasattr(session, 'marketdata_token') and session.get('marketdata_token'):
                feed_token = session.get('marketdata_token')
                logger.debug("Using session feed_token")
            
            # If still no feed token, try to get a new one
            if not feed_token:
                logger.info("No feed token available, attempting to get one")
                from database.auth_db import get_feed_token
                feed_token, new_user_id, error = get_feed_token()
                if error:
                    logger.error(f"Failed to get feed token: {error}")
                    raise Exception(f"Failed to get feed token: {error}")
                if not user_id and new_user_id:
                    user_id = new_user_id
                    logger.info(f"Got new user_id from feed token: {user_id}")
            
            # Log the user ID and feed token we're using
            logger.debug(f"Using user ID: {user_id}")
            logger.debug(f"Using feed token: {feed_token[:20]}..." if feed_token else "No feed token available")
            
            # Exchange segment mapping
            exchange_segment_map = {
                "NSE": 1,
                "NFO": 2,
                "CDS": 3,
                "BSE": 11,
                "BFO": 12,
                "MCX": 51
            }
            
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            logger.debug(f"Converted symbol {symbol} to broker format: {br_symbol}")
            
            brexchange = exchange_segment_map.get(exchange)
            logger.debug(f"Mapped exchange {exchange} to segment: {brexchange}")
            
            if brexchange is None:
                logger.error(f"Unknown exchange segment: {exchange}")
                raise Exception(f"Unknown exchange segment: {exchange}")
                
            # Get exchange_token from database
            logger.debug("Querying database for symbol token...")
            with db_session() as session:
                symbol_info = session.query(SymToken).filter(
                    SymToken.exchange == exchange,
                    SymToken.brsymbol == br_symbol
                ).first()
                
                if not symbol_info:
                    logger.error(f"Could not find exchange token for {exchange}:{br_symbol}")
                    raise Exception(f"Could not find exchange token for {exchange}:{br_symbol}")
                logger.debug(f"Found token {symbol_info.token} for {exchange}:{br_symbol}")

            # Get market depth via REST API
            logger.info("Getting market depth via REST API...")
            
            # Prepare token for API requests
            token = {
                'exchangeSegment': brexchange,
                'exchangeInstrumentID': symbol_info.token
            }
            
            # Fetch market data (xtsMessageCode 1502)
            market_data = self._fetch_market_data(token, 1502)
            if not market_data:
                logger.error("Failed to fetch market data for depth")
                raise Exception("Failed to fetch market data")
            
            # Fetch Open Interest data (xtsMessageCode 1510) - non-blocking
            oi = 0
            try:
                oi_data = self._fetch_market_data(token, 1510)
                if oi_data and 'OpenInterest' in oi_data:
                    oi = oi_data['OpenInterest']
                    logger.debug(f"Fetched OI for depth: {oi}")
            except Exception as e:
                logger.warning(f"Failed to fetch OI for depth: {str(e)}")
            
            # Process market data
            touchline = market_data.get("Touchline", {})
            
            # Extracting top 5 bids and asks
            bids = [
                {"price": b.get("Price", 0), "quantity": b.get("Size", 0)}
                for b in market_data.get("Bids", [])[:5]
            ]
            asks = [
                {"price": a.get("Price", 0), "quantity": a.get("Size", 0)}
                for a in market_data.get("Asks", [])[:5]
            ]

            # Return structured response with OI
            return {
                'bids': bids,
                'asks': asks,
                'high': touchline.get('High', 0),
                'low': touchline.get('Low', 0),
                'ltp': touchline.get('LastTradedPrice', 0),
                'ltq': touchline.get('LastTradedQunatity', 0),
                'open': touchline.get('Open', 0),
                'prev_close': touchline.get('Close', 0),
                'volume': touchline.get('TotalTradedQuantity', 0),
                'oi': oi,  # Include OI from separate API call
                'totalbuyqty': touchline.get('TotalBuyQuantity', 0),
                'totalsellqty': touchline.get('TotalSellQuantity', 0)
            }
            
        except Exception as e:
            logger.error(f"Error in get_market_depth: {str(e)}", exc_info=True)
            # Return empty structure on error
            empty_depth = {
                'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'totalbuyqty': 0,
                'totalsellqty': 0,
                'ltp': 0,
                'ltq': 0,
                'volume': 0,
                'open': 0,
                'high': 0,
                'low': 0,
                'prev_close': 0,
                'oi': 0
            }
            logger.info("Returning empty market depth structure")
            return empty_depth
            
        except Exception as e:
            logger.error(f"Error in get_market_depth: {str(e)}", exc_info=True)
            # Return empty structure on error
            empty_depth = {
                'bids': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'asks': [{'price': 0, 'quantity': 0} for _ in range(5)],
                'totalbuyqty': 0,
                'totalsellqty': 0,
                'ltp': 0,
                'ltq': 0,
                'volume': 0,
                'open': 0,
                'high': 0,
                'low': 0,
                'prev_close': 0,
                'oi': 0
            }
            logger.info("Returning empty market depth structure due to error")
            return empty_depth

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Alias for get_market_depth to maintain compatibility with common API"""
        return self.get_market_depth(symbol, exchange)
