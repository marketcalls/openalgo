import json
import os
import time
import urllib.parse
from database.token_db import get_br_symbol, get_oa_symbol
from broker.zerodha.database.master_contract_db import SymToken, db_session
import pandas as pd
from datetime import datetime, timedelta
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)




class ZerodhaPermissionError(Exception):
    """Custom exception for Zerodha API permission errors"""
    pass

class ZerodhaAPIError(Exception):
    """Custom exception for other Zerodha API errors"""
    pass

def get_api_response(endpoint, auth, method="GET", payload=None):
    """
    Make an API request to Zerodha's API using shared httpx client with connection pooling.
    
    Args:
        endpoint (str): API endpoint (e.g., '/quote')
        auth (str): Authentication token
        method (str): HTTP method (GET, POST, etc.)
        payload (dict, optional): Request payload for POST requests
        
    Returns:
        dict: API response data
        
    Raises:
        ZerodhaPermissionError: For permission-related errors
        ZerodhaAPIError: For other API errors
    """
    AUTH_TOKEN = auth
    base_url = 'https://api.kite.trade'
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'X-Kite-Version': '3',
        'Authorization': f'token {AUTH_TOKEN}',
        'Content-Type': 'application/json'
    }
    
    # Keep query params in URL to preserve duplicate keys (e.g., multiple i= for quotes)
    url = f"{base_url}{endpoint}"
    
    try:
        # Log the complete request details for debugging
        #logger.info("=== API Request Details ===")
        #logger.info(f"URL: {url}")
        #logger.info(f"Method: {method}")
        #logger.info(f"Headers: {json.dumps(headers, indent=2)}")
        if payload:
            logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
        
        # Make the request using the shared client
        if method.upper() == 'GET':
            response = client.get(
                url,
                headers=headers
            )
        elif method.upper() == 'POST':
            headers['Content-Type'] = 'application/json'
            response = client.post(
                url,
                headers=headers,
                json=payload
            )
        else:
            raise ZerodhaAPIError(f"Unsupported HTTP method: {method}")
            
        # Log the complete response
        #logger.info("=== API Response Details ===")
        logger.debug(f"Status Code: {response.status_code}")
        logger.debug(f"Response Headers: {dict(response.headers)}")
        logger.debug(f"Response Body: {response.text}")
        
        # Parse JSON response
        response_data = response.json()
        
        # Check for permission errors
        if response_data.get('status') == 'error':
            error_type = response_data.get('error_type')
            error_message = response_data.get('message', 'Unknown error')
            
            if error_type == 'PermissionException' or 'permission' in error_message.lower():
                raise ZerodhaPermissionError(f"API Permission denied: {error_message}.")
            else:
                raise ZerodhaAPIError(f"API Error: {error_message}")
                
        return response_data
        
    except ZerodhaPermissionError:
        raise
    except ZerodhaAPIError:
        raise
    except Exception as e:
        error_msg = str(e)
        logger.exception(f"API request failed: {error_msg}")
        
        # Try to extract more error details if available
        try:
            if hasattr(e, 'response') and e.response is not None:
                error_detail = e.response.json()
                error_msg = error_detail.get('message', error_msg)
        except:
            pass
            
        raise ZerodhaAPIError(f"API request failed: {error_msg}")

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Zerodha data handler with authentication token"""
        self.auth_token = auth_token
        
        # Map common timeframe format to Zerodha intervals
        self.timeframe_map = {
            # Minutes
            '1m': 'minute',
            '3m': '3minute',
            '5m': '5minute',
            '10m': '10minute',
            '15m': '15minute',
            '30m': '30minute',
            '60m': '60minute',
            # For flux scan to work for 1h interval
            '1h': '60minute',
            
            # Daily
            'D': 'day'
        }
        
        # Market timing configuration for different exchanges
        self.market_timings = {
            'NSE': {
                'start': '09:15:00',
                'end': '15:30:00'
            },
            'BSE': {
                'start': '09:15:00',
                'end': '15:30:00'
            },
            'NFO': {
                'start': '09:15:00',
                'end': '15:30:00'
            },
            'CDS': {
                'start': '09:00:00',
                'end': '17:00:00'
            },
            'BCD': {
                'start': '09:00:00',
                'end': '17:00:00'
            },
            'MCX': {
                'start': '09:00:00',
                'end': '23:30:00'
            }
        }
        
        # Default market timings if exchange not found
        self.default_market_timings = {
            'start': '00:00:00',
            'end': '23:59:59'
        }

    def get_market_timings(self, exchange: str) -> dict:
        """Get market start and end times for given exchange"""
        return self.market_timings.get(exchange, self.default_market_timings)

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
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            logger.debug(f"Fetching quotes for {exchange}:{br_symbol}")
            
            # Get exchange_token from database
            with db_session() as session:
                symbol_info = session.query(SymToken).filter(
                    SymToken.exchange == exchange,
                    SymToken.brsymbol == br_symbol
                ).first()
                
                if not symbol_info:
                    raise Exception(f"Could not find exchange token for {exchange}:{br_symbol}")
                
                # Split token to get exchange_token for quotes
                exchange_token = symbol_info.token.split('::::')[1]
            
            if(exchange=="NSE_INDEX"):
                exchange="NSE"  
            elif(exchange=="BSE_INDEX"):
                exchange="BSE"

            # URL encode the symbol to handle special characters
            encoded_symbol = urllib.parse.quote(f"{exchange}:{br_symbol}")
            
            response = get_api_response(f"/quote?i={encoded_symbol}", self.auth_token)
            
            # Get quote data from response
            quote = response.get('data', {}).get(f"{exchange}:{br_symbol}", {})
            if not quote:
                raise ZerodhaAPIError("No quote data found")
            
            # Return quote data
            return {
                'ask': quote.get('depth', {}).get('sell', [{}])[0].get('price', 0),
                'bid': quote.get('depth', {}).get('buy', [{}])[0].get('price', 0),
                'high': quote.get('ohlc', {}).get('high', 0),
                'low': quote.get('ohlc', {}).get('low', 0),
                'ltp': quote.get('last_price', 0),
                'open': quote.get('ohlc', {}).get('open', 0),
                'prev_close': quote.get('ohlc', {}).get('close', 0),
                'volume': quote.get('volume', 0),
                'oi': quote.get('oi', 0)
            }
            
        except ZerodhaPermissionError as e:
            # Log at debug level to avoid spam for personal API without data feed
            logger.debug(f"Permission error fetching quotes: {e}")
            raise
        except (ZerodhaAPIError, Exception) as e:
            logger.exception(f"Error fetching quotes: {e}")
            raise ZerodhaAPIError(f"Error fetching quotes: {e}")

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
        try:
            BATCH_SIZE = 500  # Zerodha API limit per request
            RATE_LIMIT_DELAY = 1.0  # 1 request per second = 500 symbols/second

            # If symbols exceed batch size, process in batches
            if len(symbols) > BATCH_SIZE:
                logger.info(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
                all_results = []

                # Split symbols into batches
                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i:i + BATCH_SIZE]
                    logger.debug(f"Processing batch {i//BATCH_SIZE + 1}: symbols {i+1} to {min(i+BATCH_SIZE, len(symbols))}")

                    # Process this batch
                    batch_results = self._process_quotes_batch(batch)
                    all_results.extend(batch_results)

                    # Rate limit delay between batches
                    if i + BATCH_SIZE < len(symbols):
                        time.sleep(RATE_LIMIT_DELAY)

                logger.info(f"Successfully processed {len(all_results)} quotes in {(len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE} batches")
                return all_results
            else:
                # Single batch processing
                return self._process_quotes_batch(symbols)

        except ZerodhaPermissionError as e:
            logger.debug(f"Permission error fetching multiquotes: {e}")
            raise
        except Exception as e:
            logger.exception(f"Error fetching multiquotes")
            raise ZerodhaAPIError(f"Error fetching multiquotes: {e}")

    def _process_quotes_batch(self, symbols: list) -> list:
        """
        Process a single batch of symbols (internal method)
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys (max 500)
        Returns:
            list: List of quote data for the batch
        """
        # Build list of exchange:symbol pairs and symbol map
        instruments = []
        symbol_map = {}  # Map "exchange:br_symbol" to original symbol/exchange
        skipped_symbols = []  # Track symbols that couldn't be resolved

        for item in symbols:
            symbol = item['symbol']
            exchange = item['exchange']
            br_symbol = get_br_symbol(symbol, exchange)
            logger.info(f"Symbol mapping: {symbol}@{exchange} -> br_symbol={br_symbol}")

            # Track symbols that couldn't be resolved
            if not br_symbol:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: could not resolve broker symbol")
                skipped_symbols.append({
                    'symbol': symbol,
                    'exchange': exchange,
                    'error': 'Could not resolve broker symbol'
                })
                continue

            # Normalize exchange for indices
            api_exchange = exchange
            if exchange == "NSE_INDEX":
                api_exchange = "NSE"
            elif exchange == "BSE_INDEX":
                api_exchange = "BSE"

            instrument_key = f"{api_exchange}:{br_symbol}"
            instruments.append(instrument_key)
            symbol_map[instrument_key] = {
                'symbol': symbol,
                'exchange': exchange,
                'br_symbol': br_symbol,
                'api_exchange': api_exchange
            }

        # Return skipped symbols if no valid instruments
        if not instruments:
            logger.warning("No valid instruments to fetch quotes for")
            return skipped_symbols

        # Build query string with multiple 'i' parameters
        # Format: /quote?i=NSE:SBIN&i=NSE:TCS&i=BSE:INFY
        query_params = '&'.join([f"i={urllib.parse.quote(inst)}" for inst in instruments])
        endpoint = f"/quote?{query_params}"

        # Log the instruments being requested
        logger.info(f"Requesting quotes for {len(instruments)} instruments")
        logger.info(f"Instruments: {instruments[:5]}..." if len(instruments) > 5 else f"Instruments: {instruments}")
        logger.info(f"Endpoint length: {len(endpoint)} characters")
        logger.info(f"Full endpoint: {endpoint}" if len(instruments) <= 10 else f"Endpoint (first 300 chars): {endpoint[:300]}...")

        # Make API call for this batch
        response = get_api_response(endpoint, self.auth_token)
        logger.info(f"Zerodha API response status: {response.get('status')}")
        logger.info(f"Zerodha API response data keys: {list(response.get('data', {}).keys())[:10]}")
        logger.info(f"Full Zerodha response: {json.dumps(response, indent=2)[:1000]}...")

        # Parse response and build results
        results = []
        quotes_data = response.get('data', {})

        for instrument_key, original in symbol_map.items():
            quote = quotes_data.get(instrument_key)

            if not quote:
                # Symbol not found in response, add error entry
                logger.warning(f"No quote data found for {instrument_key}")
                results.append({
                    'symbol': original['symbol'],
                    'exchange': original['exchange'],
                    'error': 'No quote data available'
                })
                continue

            # Parse and format quote data
            result_item = {
                'symbol': original['symbol'],
                'exchange': original['exchange'],
                'data': {
                    'ask': quote.get('depth', {}).get('sell', [{}])[0].get('price', 0),
                    'bid': quote.get('depth', {}).get('buy', [{}])[0].get('price', 0),
                    'high': quote.get('ohlc', {}).get('high', 0),
                    'low': quote.get('ohlc', {}).get('low', 0),
                    'ltp': quote.get('last_price', 0),
                    'open': quote.get('ohlc', {}).get('open', 0),
                    'prev_close': quote.get('ohlc', {}).get('close', 0),
                    'volume': quote.get('volume', 0),
                    'oi': quote.get('oi', 0)
                }
            }
            results.append(result_item)

        # Include skipped symbols in results
        return skipped_symbols + results

    def get_history(self, symbol: str, exchange: str, timeframe: str, from_date: str, to_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol and timeframe
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            timeframe: Timeframe (e.g., 1m, 5m, 15m, 60m, D)
            from_date: Start date in format YYYY-MM-DD
            to_date: End date in format YYYY-MM-DD
        Returns:
            pd.DataFrame: Historical data with OHLCV
        """
        try:
            # Convert timeframe to Zerodha format
            resolution = self.timeframe_map.get(timeframe)
            if not resolution:
                raise Exception(f"Unsupported timeframe: {timeframe}")
            

            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)

            # Get the token from database
            with db_session() as session:
                symbol_info = session.query(SymToken).filter(
                    SymToken.exchange == exchange,
                    SymToken.brsymbol == br_symbol
                ).first()
                
                if not symbol_info:
                    all_symbols = session.query(SymToken).filter(
                        SymToken.exchange == exchange
                    ).all()
                    logger.debug(f"All matching symbols in DB: {[(s.symbol, s.brsymbol, s.exchange, s.brexchange, s.token) for s in all_symbols]}")
                    raise Exception(f"Could not find instrument token for {exchange}:{symbol}")
                
                # Split token to get instrument_token for historical data
                instrument_token = symbol_info.token.split('::::')[0]

            if(exchange=="NSE_INDEX"):
                exchange="NSE"  
            elif(exchange=="BSE_INDEX"):
                exchange="BSE"

            # Convert dates to datetime objects
            start_date = pd.to_datetime(from_date)
            end_date = pd.to_datetime(to_date)
            
            # Initialize empty list to store DataFrames
            dfs = []
            
            # Process data in 60-day chunks
            current_start = start_date
            while current_start <= end_date:
                # Calculate chunk end date (60 days or remaining period)
                current_end = min(current_start + timedelta(days=59), end_date)
                
                # Format dates for API call
                from_str = current_start.strftime('%Y-%m-%d+00:00:00')
                to_str = current_end.strftime('%Y-%m-%d+23:59:59')
                
                # Log the request details
                logger.debug(f"Fetching {resolution} data for {exchange}:{symbol} from {from_str} to {to_str}")
                
                # Construct endpoint
                endpoint = f"/instruments/historical/{instrument_token}/{resolution}?from={from_str}&to={to_str}&oi=1"
                logger.debug(f"Making request to endpoint: {endpoint}")
                
                # Use get_api_response
                response = get_api_response(endpoint, self.auth_token)
                
                if not response or response.get('status') != 'success':
                    logger.error(f"API Response: {response}")
                    raise Exception(f"Error from Zerodha API: {response.get('message', 'Unknown error')}")
                
                # Convert to DataFrame
                candles = response.get('data', {}).get('candles', [])
                if candles:
                    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
                    dfs.append(df)
                
                # Move to next chunk
                current_start = current_end + timedelta(days=1)
                
            # If no data was found, return empty DataFrame
            if not dfs:
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'oi'])
            
            # Combine all chunks
            final_df = pd.concat(dfs, ignore_index=True)
            
            # Convert timestamp to epoch properly using ISO format
            final_df['timestamp'] = pd.to_datetime(final_df['timestamp'], format='ISO8601')
            
            # For daily timeframe, convert UTC to IST by adding 5 hours and 30 minutes
            if timeframe == 'D':
                final_df['timestamp'] = final_df['timestamp'] + pd.Timedelta(hours=5, minutes=30)
            
            final_df['timestamp'] = final_df['timestamp'].astype('int64') // 10**9  # Convert nanoseconds to seconds
            
            # Sort by timestamp and remove duplicates
            final_df = final_df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)
            
            # Ensure volume is integer
            final_df['volume'] = final_df['volume'].astype(int)
            final_df['oi'] = final_df['oi'].astype(int)
            
            return final_df
                
        except ZerodhaPermissionError as e:
            logger.exception(f"Permission error fetching historical data: {e}")
            raise
        except (ZerodhaAPIError, Exception) as e:
            logger.exception(f"Error fetching historical data: {e}")
            raise ZerodhaAPIError(f"Error fetching historical data: {e}")

    def get_market_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data
        """
        try:
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            logger.debug(f"Fetching market depth for {exchange}:{br_symbol}")
            
            # Get exchange_token from database
            with db_session() as session:
                symbol_info = session.query(SymToken).filter(
                    SymToken.exchange == exchange,
                    SymToken.brsymbol == br_symbol
                ).first()
                
                if not symbol_info:
                    raise Exception(f"Could not find exchange token for {exchange}:{br_symbol}")
                
                # Split token to get exchange_token for quotes
                exchange_token = symbol_info.token.split('::::')[1]
            
            if(exchange=="NSE_INDEX"):
                exchange="NSE"  
            elif(exchange=="BSE_INDEX"):
                exchange="BSE"
            
            # URL encode the symbol to handle special characters
            encoded_symbol = urllib.parse.quote(f"{exchange}:{br_symbol}")
            
            response = get_api_response(f"/quote?i={encoded_symbol}", self.auth_token)
            
            # Get quote data from response
            quote = response.get('data', {}).get(f"{exchange}:{br_symbol}", {})
            if not quote:
                raise ZerodhaAPIError("No market depth data found")
            
            depth = quote.get('depth', {})
            
            # Format asks and bids data
            asks = []
            bids = []
            
            # Process sell orders (asks)
            sell_orders = depth.get('sell', [])
            for i in range(5):
                if i < len(sell_orders):
                    asks.append({
                        'price': sell_orders[i].get('price', 0),
                        'quantity': sell_orders[i].get('quantity', 0)
                    })
                else:
                    asks.append({'price': 0, 'quantity': 0})
                    
            # Process buy orders (bids)
            buy_orders = depth.get('buy', [])
            for i in range(5):
                if i < len(buy_orders):
                    bids.append({
                        'price': buy_orders[i].get('price', 0),
                        'quantity': buy_orders[i].get('quantity', 0)
                    })
                else:
                    bids.append({'price': 0, 'quantity': 0})
            
            # Return market depth data
            return {
                'asks': asks,
                'bids': bids,
                'high': quote.get('ohlc', {}).get('high', 0),
                'low': quote.get('ohlc', {}).get('low', 0),
                'ltp': quote.get('last_price', 0),
                'ltq': quote.get('last_quantity', 0),
                'oi': quote.get('oi', 0),
                'open': quote.get('ohlc', {}).get('open', 0),
                'prev_close': quote.get('ohlc', {}).get('close', 0),
                'totalbuyqty': sum(order.get('quantity', 0) for order in buy_orders),
                'totalsellqty': sum(order.get('quantity', 0) for order in sell_orders),
                'volume': quote.get('volume', 0)
            }
            
        except ZerodhaPermissionError as e:
            logger.error(f"Permission error fetching market depth: {str(e)}")
            raise
        except (ZerodhaAPIError, Exception) as e:
            logger.error(f"Error fetching market depth: {str(e)}")
            raise ZerodhaAPIError(f"Error fetching market depth: {str(e)}")

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Alias for get_market_depth to maintain compatibility with common API"""
        return self.get_market_depth(symbol, exchange)
