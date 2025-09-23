import json
import os
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
    
    # For GET requests, include params in URL
    params = {}
    if method.upper() == 'GET' and '?' in endpoint:
        # Extract query params from endpoint
        path, query = endpoint.split('?', 1)
        params = dict(urllib.parse.parse_qsl(query))
        endpoint = path
    
    url = f"{base_url}{endpoint}"
    
    try:
        # Log the complete request details for debugging
        #logger.info("=== API Request Details ===")
        #logger.info(f"URL: {url}")
        #logger.info(f"Method: {method}")
        #logger.info(f"Headers: {json.dumps(headers, indent=2)}")
        if payload:
            logger.debug(f"Payload: {json.dumps(payload, indent=2)}")
        if params:
            logger.debug(f"Params: {json.dumps(params, indent=2)}")
        
        # Make the request using the shared client
        if method.upper() == 'GET':
            response = client.get(
                url,
                headers=headers,
                params=params
            )
        elif method.upper() == 'POST':
            headers['Content-Type'] = 'application/json'
            response = client.post(
                url,
                headers=headers,
                params=params,
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
            logger.exception(f"Permission error fetching quotes: {e}")
            raise
        except (ZerodhaAPIError, Exception) as e:
            logger.exception(f"Error fetching quotes: {e}")
            raise ZerodhaAPIError(f"Error fetching quotes: {e}")

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
