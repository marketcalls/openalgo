import http.client
import json
import os
import urllib.parse
from database.token_db import get_br_symbol, get_oa_symbol
from broker.zerodha.database.master_contract_db import SymToken, db_session
import logging
import pandas as pd
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ZerodhaPermissionError(Exception):
    """Custom exception for Zerodha API permission errors"""
    pass

class ZerodhaAPIError(Exception):
    """Custom exception for other Zerodha API errors"""
    pass

def get_api_response(endpoint, auth, method="GET", payload=''):
    AUTH_TOKEN = auth
    conn = http.client.HTTPSConnection("api.kite.trade")
    headers = {
        'X-Kite-Version': '3',
        'Authorization': f'token {AUTH_TOKEN}',
        'Content-Type': 'application/json'
    }

    try:
        # Log the complete request details for debugging
        logger.info("=== API Request Details ===")
        logger.info(f"URL: https://api.kite.trade{endpoint}")
        logger.info(f"Method: {method}")
        logger.info(f"Headers: {json.dumps(headers, indent=2)}")
        if payload:
            logger.info(f"Payload: {payload}")

        conn.request(method, endpoint, payload, headers)
        res = conn.getresponse()
        data = res.read()
        response = json.loads(data.decode("utf-8"))

        # Log the complete response
        logger.info("=== API Response Details ===")
        logger.info(f"Status Code: {res.status}")
        logger.info(f"Response Headers: {dict(res.getheaders())}")
        logger.info(f"Response Body: {json.dumps(response, indent=2)}")

        # Check for permission errors
        if response.get('status') == 'error':
            error_type = response.get('error_type')
            error_message = response.get('message', 'Unknown error')
            
            if error_type == 'PermissionException' or 'permission' in error_message.lower():
                raise ZerodhaPermissionError(f"API Permission denied: {error_message}.")
            else:
                raise ZerodhaAPIError(f"API Error: {error_message}")

        return response
    except ZerodhaPermissionError:
        raise
    except ZerodhaAPIError:
        raise
    except Exception as e:
        logger.error(f"API request failed: {str(e)}")
        raise ZerodhaAPIError(f"API request failed: {str(e)}")

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
            logger.info(f"Fetching quotes for {exchange}:{br_symbol}")
            
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
                'volume': quote.get('volume', 0)
            }
            
        except ZerodhaPermissionError as e:
            logger.error(f"Permission error fetching quotes: {str(e)}")
            raise
        except (ZerodhaAPIError, Exception) as e:
            logger.error(f"Error fetching quotes: {str(e)}")
            raise ZerodhaAPIError(f"Error fetching quotes: {str(e)}")

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
                    logger.info(f"All matching symbols in DB: {[(s.symbol, s.brsymbol, s.exchange, s.brexchange, s.token) for s in all_symbols]}")
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
                logger.info(f"Fetching {resolution} data for {exchange}:{symbol} from {from_str} to {to_str}")
                
                # Construct endpoint
                endpoint = f"/instruments/historical/{instrument_token}/{resolution}?from={from_str}&to={to_str}"
                logger.info(f"Making request to endpoint: {endpoint}")
                
                # Use get_api_response
                response = get_api_response(endpoint, self.auth_token)
                
                if not response or response.get('status') != 'success':
                    logger.error(f"API Response: {response}")
                    raise Exception(f"Error from Zerodha API: {response.get('message', 'Unknown error')}")
                
                # Convert to DataFrame
                candles = response.get('data', {}).get('candles', [])
                if candles:
                    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                    dfs.append(df)
                
                # Move to next chunk
                current_start = current_end + timedelta(days=1)
                
            # If no data was found, return empty DataFrame
            if not dfs:
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Combine all chunks
            final_df = pd.concat(dfs, ignore_index=True)
            
            # Convert timestamp to epoch properly using ISO format
            final_df['timestamp'] = pd.to_datetime(final_df['timestamp'], format='ISO8601')
            final_df['timestamp'] = final_df['timestamp'].astype('int64') // 10**9  # Convert nanoseconds to seconds
            
            # Sort by timestamp and remove duplicates
            final_df = final_df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)
            
            # Ensure volume is integer
            final_df['volume'] = final_df['volume'].astype(int)
            
            return final_df
                
        except ZerodhaPermissionError as e:
            logger.error(f"Permission error fetching historical data: {str(e)}")
            raise
        except (ZerodhaAPIError, Exception) as e:
            logger.error(f"Error fetching historical data: {str(e)}")
            raise ZerodhaAPIError(f"Error fetching historical data: {str(e)}")

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
            logger.info(f"Fetching market depth for {exchange}:{br_symbol}")
            
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
