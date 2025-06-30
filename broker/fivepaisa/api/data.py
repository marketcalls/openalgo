import json
from datetime import datetime, timedelta
import os
from typing import Dict, Any, Optional
import httpx
import pytz
from utils.httpx_client import get_httpx_client
from database.token_db import get_br_symbol, get_token, get_oa_symbol
from broker.fivepaisa.mapping.transform_data import map_exchange, map_exchange_type
import traceback
import pandas as pd
from utils.logging import get_logger

logger = get_logger(__name__)


# Retrieve the BROKER_API_KEY environment variable
broker_api_key = os.getenv('BROKER_API_KEY')
api_key, user_id, client_id = broker_api_key.split(':::')

# Base URL for 5Paisa API
BASE_URL = "https://Openapi.5paisa.com"

def get_api_response(endpoint: str, auth: str, method: str = "GET", payload: str = '') -> dict:
    """Generic function to make API calls to 5Paisa using shared httpx client
    
    Args:
        endpoint (str): API endpoint path
        auth (str): Authentication token
        method (str, optional): HTTP method. Defaults to "GET".
        payload (str, optional): Request payload. Defaults to ''.
        
    Returns:
        dict: JSON response from the API
    """
    try:
        # Get the shared httpx client
        client = get_httpx_client()
        
        headers = {
            'Authorization': f'bearer {auth}',
            'Content-Type': 'application/json'
        }
        
        # Make request based on method
        if method.upper() == "GET":
            response = client.get(
                f"{BASE_URL}{endpoint}",
                headers=headers
            )
        else:  # POST
            response = client.post(
                f"{BASE_URL}{endpoint}",
                content=payload,  # Use content since payload is already JSON string
                headers=headers
            )
            
        response.raise_for_status()
        return response.json()
        
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
        raise
    except httpx.RequestError as e:
        logger.error(f"Request error occurred: {e}")
        raise
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise

class BrokerData:
    def __init__(self, auth_token):
        """Initialize 5Paisa data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to 5Paisa resolutions
        self.timeframe_map = {
            # Minutes
            '1m': '1', '3m': '3', '5m': '5',
            '10m': '10', '15m': '15', '30m': '30',
            # Hours
            '1h': '60',
            # Daily (support all variants)
            'D': '1D', 'd': '1D', '1d': '1D'
        }

    def get_market_depth(self, symbol: str, exchange: str) -> Optional[Dict[str, float]]:
        """
        Get market depth for a given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data
        """
        try:
            # Get token from symbol
            token = get_token(symbol, exchange)
            br_symbol = get_br_symbol(symbol, exchange)

            # Prepare request payload
            json_data = {
                "head": {
                    "key": api_key
                },
                "body": {
                    "ClientCode": client_id,
                    "Exchange": map_exchange(exchange),
                    "ExchangeType": map_exchange_type(exchange),
                    "ScripCode": token,
                    "ScripData": br_symbol if token == "0" else ""
                }
            }

            # Get the shared httpx client
            client = get_httpx_client()

            # Make API request
            headers = {
                'Authorization': f'bearer {self.auth_token}',
                'Content-Type': 'application/json'
            }
            response = client.post(
                f"{BASE_URL}/VendorsAPI/Service1.svc/V2/MarketDepth",
                json=json_data,
                headers=headers
            )
            response.raise_for_status()
            response = response.json()

            if response['head']['statusDescription'] != 'Success':
                logger.info(f"Market Depth Error: {response['head']['statusDescription']}")
                return None

            depth_data = response['body']
            if not depth_data or 'MarketDepthData' not in depth_data:
                logger.info("No depth data in response")
                return None

            # Get best bid and ask
            bid = ask = 0
            market_depth = depth_data['MarketDepthData']
            
            # BbBuySellFlag: 66 for Buy, 83 for Sell
            buy_orders = [order for order in market_depth if order['BbBuySellFlag'] == 66]
            sell_orders = [order for order in market_depth if order['BbBuySellFlag'] == 83]
            
            if buy_orders:
                # Get highest buy price
                bid = max(float(order['Price']) for order in buy_orders)
            if sell_orders:
                # Get lowest sell price
                ask = min(float(order['Price']) for order in sell_orders)
            
            logger.info(f"Extracted Bid: {bid}, Ask: {ask}")
            return {'bid': bid, 'ask': ask}

        except Exception as e:
            logger.error(f"Error fetching market depth: {e}")
            logger.info(f"Exception type: {type(e)}")
            import traceback
            logger.info(f"Traceback: {traceback.format_exc()}")
            return None

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data with OHLC, volume and open interest
        """
        try:
            # Get token from symbol
            token = get_token(symbol, exchange)
            br_symbol = get_br_symbol(symbol, exchange)

            # Get market snapshot for overall data
            snapshot_data = {
                "head": {
                    "key": api_key
                },
                "body": {
                    "ClientCode": client_id,
                    "Data": [
                        {
                            "Exchange": map_exchange(exchange),
                            "ExchangeType": map_exchange_type(exchange),
                            "ScripCode": token,
                            "ScripData": br_symbol if token == "0" else ""
                        }
                    ]
                }
            }

            # Get the shared httpx client
            client = get_httpx_client()

            # Make API request
            headers = {
                'Authorization': f'bearer {self.auth_token}',
                'Content-Type': 'application/json'
            }
            snapshot_response = client.post(
                f"{BASE_URL}/VendorsAPI/Service1.svc/MarketSnapshot",
                json=snapshot_data,
                headers=headers
            )
            snapshot_response.raise_for_status()
            snapshot_response = snapshot_response.json()

            if snapshot_response['head']['statusDescription'] != 'Success':
                raise Exception(f"Error from 5Paisa API: {snapshot_response['head']['statusDescription']}")

            quote_data = snapshot_response['body']['Data'][0]

            # Get market depth data
            depth_data = {
                "head": {
                    "key": api_key
                },
                "body": {
                    "ClientCode": client_id,
                    "Exchange": map_exchange(exchange),
                    "ExchangeType": map_exchange_type(exchange),
                    "ScripCode": token,
                    "ScripData": br_symbol if token == "0" else ""
                }
            }

            depth_response = client.post(
                f"{BASE_URL}/VendorsAPI/Service1.svc/V2/MarketDepth",
                json=depth_data,
                headers=headers
            )
            depth_response.raise_for_status()
            depth_response = depth_response.json()

            if depth_response['head']['statusDescription'] != 'Success':
                raise Exception(f"Error from 5Paisa API: {depth_response['head']['statusDescription']}")

            market_depth = depth_response['body'].get('MarketDepthData', [])
            
            # Initialize empty bids and asks arrays
            empty_entry = {"price": 0, "quantity": 0}
            bids = []
            asks = []

            # Process market depth data
            buy_orders = [order for order in market_depth if order['BbBuySellFlag'] == 66]  # 66 = Buy
            sell_orders = [order for order in market_depth if order['BbBuySellFlag'] == 83]  # 83 = Sell

            # Sort orders by price (highest buy, lowest sell)
            buy_orders.sort(key=lambda x: float(x['Price']), reverse=True)
            sell_orders.sort(key=lambda x: float(x['Price']))

            # Fill bids and asks arrays
            for order in buy_orders[:5]:
                bids.append({
                    "price": float(order['Price']),
                    "quantity": int(order['Quantity'])
                })

            for order in sell_orders[:5]:
                asks.append({
                    "price": float(order['Price']),
                    "quantity": int(order['Quantity'])
                })

            # Pad with empty entries if needed
            while len(bids) < 5:
                bids.append(empty_entry)
            while len(asks) < 5:
                asks.append(empty_entry)

            # Calculate total buy/sell quantities
            total_buy_qty = sum(int(order['Quantity']) for order in buy_orders)
            total_sell_qty = sum(int(order['Quantity']) for order in sell_orders)

            # Return standardized format
            return {
                "asks": asks,
                "bids": bids,
                "high": float(quote_data.get('High', 0)),
                "low": float(quote_data.get('Low', 0)),
                "ltp": float(quote_data.get('LastTradedPrice', 0)),
                "ltq": int(quote_data.get('LastTradedQty', 0)),
                "oi": int(quote_data.get('OpenInterest', 0)),
                "open": float(quote_data.get('Open', 0)),
                "prev_close": float(quote_data.get('PClose', 0)),
                "totalbuyqty": total_buy_qty,
                "totalsellqty": total_sell_qty,
                "volume": int(quote_data.get('Volume', 0))
            }

        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Quote data with bid, ask, ltp, open, high, low, prev_close, volume
        """
        try:
            # Get token from symbol
            token = get_token(symbol, exchange)
            br_symbol = get_br_symbol(symbol, exchange)

            # Prepare request payload
            json_data = {
                "head": {
                    "key": api_key
                },
                "body": {
                    "ClientCode": client_id,
                    "Data": [
                        {
                            "Exchange": map_exchange(exchange),
                            "ExchangeType": map_exchange_type(exchange),
                            "ScripCode": token,
                            "ScripData": br_symbol if token == "0" else ""
                        }
                    ]
                }
            }

            # Get the shared httpx client
            client = get_httpx_client()

            # Make API request for market snapshot
            headers = {
                'Authorization': f'bearer {self.auth_token}',
                'Content-Type': 'application/json'
            }
            response = client.post(
                f"{BASE_URL}/VendorsAPI/Service1.svc/MarketSnapshot",
                json=json_data,
                headers=headers
            )
            response.raise_for_status()
            response = response.json()

            # Check for successful response
            if response['head']['statusDescription'] != 'Success':
                return None

            # Extract quote data
            quote_data = response['body']['Data'][0]
            
            # Get bid/ask from market depth
            depth_data = self.get_market_depth(symbol, exchange)
            
            # Get previous close from PClose field
            prev_close = float(quote_data.get('PClose', 0))
            if prev_close == 0:  # Fallback options if PClose is not available
                prev_close = float(quote_data.get('PreviousClose', 0))
                if prev_close == 0:
                    prev_close = float(quote_data.get('Close', 0))
            
            # Return just the data without status
            return {
                'ask': depth_data['ask'] if depth_data else 0,
                'bid': depth_data['bid'] if depth_data else 0,
                'high': float(quote_data.get('High', 0)),
                'low': float(quote_data.get('Low', 0)),
                'ltp': float(quote_data.get('LastTradedPrice', 0)),
                'open': float(quote_data.get('Open', 0)),
                'prev_close': prev_close,
                'volume': int(quote_data.get('Volume', 0))
            }

        except Exception as e:
            logger.error(f"Error in get_quotes: {e}")
            return None

    def map_interval(self, interval: str) -> str:
        """Map openalgo interval to 5paisa interval"""
        interval_map = {
            "1m": "1m",
            "5m": "5m",
            "10m": "10m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            # Handle all daily timeframe variants
            "1d": "1d",
            "D": "1d",  
            "d": "1d"   # Also map lowercase 'd'
        }
        return interval_map.get(interval, "1d")

    def _process_raw_candles(self, raw_data, interval):
        """
        Process raw candle data in case of error
        Args:
            raw_data: Raw candle data from API error
            interval: Time interval (e.g., 1m, 5m, 15m, 30m, 1h, 1d)
        Returns:
            pd.DataFrame: Processed DataFrame
        """
        if not raw_data:
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
        # Convert to DataFrame
        df = pd.DataFrame(raw_data)
        
        # Convert string timestamps to datetime
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Timezone handling
        ist = pytz.timezone('Asia/Kolkata')
        df['timestamp'] = df['timestamp'].dt.tz_convert(ist)
        
        # Sort by timestamp
        df = df.sort_values('timestamp')
        
        # Reorder columns
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
        
        logger.info(f"Processed {len(df)} candles from raw data")
        return df
        
    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical candle data
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Time interval (e.g., 1m, 5m, 15m, 30m, 1h, 1d)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: DataFrame with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Normalize interval for consistent handling
            original_interval = interval
            
            # First normalize the interval to handle case insensitivity
            if interval.upper() == 'D':
                interval = '1d'  # Always use 1d internally for daily
                logger.debug(f"Debug: Converted interval from {original_interval} to {interval}")
                
            # Get token from symbol
            token = get_token(symbol, exchange)
            
            # Map interval
            fivepaisa_interval = self.map_interval(interval)
            logger.debug(f"Debug: Mapped {interval} to {fivepaisa_interval}")
            
            if not fivepaisa_interval:
                supported = ["1m", "5m", "15m", "30m", "1h", "1d"]
                raise Exception(f"Unsupported interval '{interval}'. Supported intervals: {', '.join(supported)}")
            
            # Convert 5paisa timeframe to our format
            resolution = self.timeframe_map.get(interval, '1D')
            logger.debug(f"Debug: Final API resolution: {resolution}")
            
            # No special handling needed for 10m interval anymore
            # Just use the native 10m interval from the API
            is_resampling_needed = False

            # For intraday, we need to specify both start and end date
            # Convert dates to datetime objects
            from_date = pd.to_datetime(start_date)
            to_date = pd.to_datetime(end_date)
            
            # Initialize chunk parameters based on interval
            # We're now using normalized interval where 'D' is always '1d'
            if interval == '1d':
                chunk_days = 100  # For daily data, fetch in 100-day chunks
                logger.debug("Debug: Using daily chunk size (100 days)")
            else:
                chunk_days = 30  # For intraday data, fetch in 30-day chunks
                logger.debug(f"Debug: Using intraday chunk size (30 days) for {interval}")
            
            # Initialize empty list to store DataFrames
            dfs = []
            
            # Process data in chunks
            current_start = from_date
            while current_start <= to_date:
                # Calculate chunk end date
                current_end = min(current_start + pd.Timedelta(days=chunk_days-1), to_date)
                
                # Format dates for API
                chunk_start = current_start.strftime('%Y-%m-%d')
                chunk_end = current_end.strftime('%Y-%m-%d')
                
                # Prepare URL for historical data
                url = f"/V2/historical/{map_exchange(exchange)}/{map_exchange_type(exchange)}/{token}/{fivepaisa_interval}"
                url += f"?from={chunk_start}&end={chunk_end}"
                
                logger.debug(f"Fetching chunk from {chunk_start} to {chunk_end}")  # Debug log
                
                try:
                    # Make API request
                    client = get_httpx_client()
                    headers = {
                        'Authorization': f'bearer {self.auth_token}',
                        'Content-Type': 'application/json'
                    }
                    response = client.get(
                        f"{BASE_URL}{url}",
                        headers=headers
                    )
                    response.raise_for_status()
                    response = response.json()
                    
                    if response.get('status') != 'success':
                        error_msg = response.get('message', 'Unknown error')
                        logger.error(f"Error for chunk {chunk_start} to {chunk_end}: {error_msg}")
                        current_start = current_end + pd.Timedelta(days=1)
                        continue
                    
                    candles = response.get('data', {}).get('candles', [])
                    if not candles:
                        logger.info(f"No data for chunk {chunk_start} to {chunk_end}")
                        current_start = current_end + pd.Timedelta(days=1)
                        continue
                    
                    # Transform candles
                    transformed_candles = []
                    for candle in candles:
                        try:
                            # Skip invalid candles
                            if len(candle) < 6:
                                continue
                                
                            # Parse date and values
                            dt = datetime.strptime(candle[0], "%Y-%m-%dT%H:%M:%S")
                            # Make the datetime timezone-aware (UTC)
                            dt = pytz.UTC.localize(dt)
                            
                            open_price = float(candle[1])
                            high_price = float(candle[2])
                            low_price = float(candle[3])
                            close_price = float(candle[4])
                            volume = int(candle[5])
                            
                            # Skip holidays and invalid data:
                            # 1. Zero volume
                            # 2. All prices are zero
                            # 3. High = Low (usually indicates no trading)
                            if (volume == 0 or 
                                (open_price == 0 and high_price == 0 and low_price == 0 and close_price == 0) or
                                (high_price == low_price)):
                                continue
                            
                            # Make timezone-aware in UTC
                            dt = dt.replace(tzinfo=pytz.UTC)
                            
                            # For all candles, we need proper market timing
                            # Convert to IST timezone first
                            ist = pytz.timezone('Asia/Kolkata')
                            dt = dt.astimezone(ist)
                            
                            # For daily candles, always set time to 9:15 AM IST (market open)
                            if interval.upper() == 'D':
                                dt = dt.replace(hour=9, minute=15, second=0)
                            else:
                                # For intraday, make sure we handle the timing correctly
                                # Create a reference time at 9:15 AM on the same date
                                market_open = dt.replace(hour=9, minute=15, second=0)
                                
                                # Check if the timestamp is outside of valid market hours
                                if dt.hour < 9 or (dt.hour == 9 and dt.minute < 15) or dt.hour > 15 or (dt.hour == 15 and dt.minute > 30):
                                    # Shift to market hours by making it relative to market open
                                    minutes_offset = (dt.hour * 60 + dt.minute) % (6 * 60 + 15)  # 6h15m market duration
                                    dt = market_open + timedelta(minutes=minutes_offset)
                            
                            # Convert to Unix timestamp in seconds
                            timestamp_sec = int(dt.timestamp())  # Simple Unix timestamp in seconds
                            
                            transformed_candle = {
                                "timestamp": timestamp_sec,  # Store as integer seconds
                                "open": open_price,
                                "high": high_price,
                                "low": low_price,
                                "close": close_price,
                                "volume": volume
                            }
                            transformed_candles.append(transformed_candle)
                            
                        except Exception as e:
                            logger.error(f"Error transforming candle {candle}: {e}")
                            continue
                    
                    if transformed_candles:
                        chunk_df = pd.DataFrame(transformed_candles)
                        # Ensure timestamp column exists and is first
                        if 'timestamp' not in chunk_df.columns:
                            logger.warning(f"Warning: Missing timestamp column in chunk. Columns: {chunk_df.columns}")
                            continue
                        dfs.append(chunk_df)
                        logger.info(f"Added {len(transformed_candles)} candles from chunk")
                    
                except Exception as e:
                    logger.error(f"Error processing chunk {chunk_start} to {chunk_end}: {e}")
                
                # Move to next chunk
                current_start = current_end + pd.Timedelta(days=1)
            
            # If no data was found, return empty DataFrame
            if not dfs:
                logger.info("No valid data found for the entire period")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Combine all chunks
            df = pd.concat(dfs, ignore_index=True)
            
            # Sort by timestamp and remove any duplicates
            df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)
            
            # A completely different approach to guarantee proper market hours
            # Convert timestamps to datetime first
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            
            # Convert UTC to IST by adding 5:30
            df['timestamp'] = df['timestamp'] + pd.Timedelta(hours=5, minutes=30)
            
            # Extract date component for reference
            df['date'] = df['timestamp'].dt.date
            
            # Add trading day sequence within each date
            df['seq'] = df.groupby('date').cumcount()
            
            # Handle daily vs intraday differently
            if interval.upper() == 'D':
                # For daily candles, always set to 9:15 AM
                df['timestamp'] = df.apply(lambda row: pd.Timestamp(
                    year=row['timestamp'].year,
                    month=row['timestamp'].month,
                    day=row['timestamp'].day,
                    hour=9, minute=15, second=0), axis=1)
            else:
                # For intraday, calculate proper interval
                interval_minutes = 5  # Default
                if 'm' in interval.lower():
                    try:
                        interval_minutes = int(interval.lower().replace('m', ''))
                    except:
                        interval_minutes = 5
                elif 'h' in interval.lower():
                    try:
                        interval_minutes = int(interval.lower().replace('h', '')) * 60
                    except:
                        interval_minutes = 60
                
                # Create properly sequenced timestamps within market hours
                def create_market_timestamp(row):
                    # Create base timestamp at 09:15 AM
                    base = pd.Timestamp(
                        year=row['timestamp'].year,
                        month=row['timestamp'].month,
                        day=row['timestamp'].day,
                        hour=9, minute=15, second=0)
                    
                    # Add sequence interval
                    minutes_to_add = row['seq'] * interval_minutes
                    new_ts = base + pd.Timedelta(minutes=minutes_to_add)
                    
                    # Make sure it's within market hours (9:15 AM - 3:30 PM)
                    market_close = base.replace(hour=15, minute=30)
                    if new_ts > market_close:
                        # If past market close, wrap to next day
                        extra_minutes = (new_ts - market_close).total_seconds() / 60
                        # Calculate how many trading days we need to add
                        trading_day_minutes = 6 * 60 + 15  # 6h15m per trading day
                        days_to_add = int(extra_minutes / trading_day_minutes) + 1
                        
                        # Start from 9:15 AM on the next day
                        next_day_base = base + pd.Timedelta(days=days_to_add)
                        next_day_base = next_day_base.replace(hour=9, minute=15)
                        
                        # Add remaining minutes
                        remaining_minutes = extra_minutes % trading_day_minutes
                        new_ts = next_day_base + pd.Timedelta(minutes=remaining_minutes)
                        
                        # Final check to ensure we're within market hours
                        if new_ts.hour > 15 or (new_ts.hour == 15 and new_ts.minute > 30):
                            new_ts = new_ts.replace(hour=15, minute=30)
                    
                    return new_ts
                
                # Apply the function to create proper timestamps
                df['timestamp'] = df.apply(create_market_timestamp, axis=1)
            
            # Drop the temporary columns
            df = df.drop(['date', 'seq'], axis=1)
            
            # Sort by the new timestamps
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            # For 10m interval, we directly get the API data now and fix the timestamps
            # No need for resampling from 5m data anymore
            if interval == '10m' and not df.empty:
                # Apply our timestamp fixing function with appropriate time alignment
                logger.debug("Debug: Fixing 10m timestamps")
                df = self.fix_timestamps(df, '10m')
            else:
                # Apply our timestamp fixing function as a final step
                logger.debug(f"Debug: Fixing timestamps for {interval}")
                df = self.fix_timestamps(df, interval)
                
            # Check after timestamp fixing
            if len(df) > 0:
                logger.info(f"Debug: First timestamp after fixing: {pd.to_datetime(df['timestamp'].iloc[0], unit='s')}")
            
            # Final check for daily data with wrong timestamps (03:45 instead of 09:15)
            # This is a direct fix for the case where uppercase D or lowercase d is used
            if (original_interval.upper() == 'D' or original_interval == 'd') and len(df) > 0:
                logger.debug("Debug: Applying final daily timestamp fix")
                # Convert to datetime for fixing
                temp_df = df.copy()
                temp_df['timestamp'] = pd.to_datetime(temp_df['timestamp'], unit='s')
                
                # Check if we have any early morning timestamps (like 03:45)
                early_morning = ((temp_df['timestamp'].dt.hour < 9) | 
                               ((temp_df['timestamp'].dt.hour == 9) & (temp_df['timestamp'].dt.minute < 15)))
                
                if early_morning.any():
                    logger.debug("Debug: Found early morning timestamps, fixing to 09:15")
                    # Set all timestamps to 09:15
                    temp_df['timestamp'] = temp_df['timestamp'].apply(lambda ts: 
                        ts.replace(hour=9, minute=15, second=0))
                    df['timestamp'] = temp_df['timestamp'].astype('int64') // 10**9
                else:
                    # Convert back to Unix timestamp in seconds
                    df['timestamp'] = df['timestamp'].astype('int64') // 10**9
            else:
                # Convert back to Unix timestamp in seconds
                df['timestamp'] = df['timestamp'].astype('int64') // 10**9
            
            # Ensure numeric columns are properly typed
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric)
            
            # Reorder columns to match expected format
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            
            logger.info(f"Returning {len(df)} total candles")
            return df

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error in get_history: {error_msg}\nTraceback: {traceback.format_exc()}")  # Debug log
            
            # Check if this is the timestamp conversion error with raw_data available
            if 'non convertible value' in error_msg and 'with the unit' in error_msg and hasattr(e, 'raw_data'):
                logger.error("Attempting to recover from timestamp conversion error using raw_data")
                try:
                    return self._process_raw_candles(e.raw_data, interval)
                except Exception as recovery_error:
                    logger.error(f"Recovery attempt failed: {recovery_error}")
            
            raise

    def fix_timestamps(self, df, interval):
        """
        Helper function to fix timestamps in any DataFrame
        Args:
            df: DataFrame with timestamp column
            interval: Time interval (e.g., 1m, 5m, 15m, 30m, 1h, 1d)
        Returns:
            DataFrame with fixed timestamps
        """
        # Make a copy to avoid modifying the original
        df = df.copy()
        
        # Ensure timestamp is a pandas datetime
        if pd.api.types.is_numeric_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        elif not pd.api.types.is_datetime64_dtype(df['timestamp']):
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
        # Add timezone info if not present
        if df['timestamp'].dt.tz is None:
            # Assume timestamps are in IST
            ist = pytz.timezone('Asia/Kolkata')
            df['timestamp'] = df['timestamp'].dt.tz_localize(ist)
            
        # Extract unique dates
        dates = df['timestamp'].dt.date.unique()
        
        # Check if we're getting daily candles with intraday interval
        is_daily_data = True
        # Group by date and check if there's only one candle per date
        date_counts = df.groupby(df['timestamp'].dt.date).size()
        if (date_counts > 1).any():
            # If any date has more than one candle, it's not daily data
            is_daily_data = False
            
        # Get interval in minutes
        interval_minutes = 5
        # Standardize how we check for daily interval
        is_daily_interval = interval.upper() == 'D' or interval == '1d' or interval == 'd'
        logger.debug(f"Debug: is_daily_interval={is_daily_interval}, is_daily_data={is_daily_data}, interval={interval}")
        
        if is_daily_interval or is_daily_data:
            # For daily or data that looks like daily (1 candle per day),
            # set all to 9:15 AM
            df['timestamp'] = df['timestamp'].apply(lambda ts: 
                ts.replace(hour=9, minute=15, second=0))
            return df
        else:
            # Parse interval
            if 'm' in interval.lower():
                try:
                    interval_minutes = int(interval.lower().replace('m', ''))
                except:
                    interval_minutes = 5
            elif 'h' in interval.lower():
                try:
                    interval_minutes = int(interval.lower().replace('h', '')) * 60
                except:
                    interval_minutes = 60
                    
        # Create new timestamps dictionary by date
        new_timestamps = {}
        
        for date in dates:
            # Get candles for this date
            mask = df['timestamp'].dt.date == date
            date_candles = df[mask]
            
            # Create proper sequence of timestamps based on interval
            # Market always opens at 9:15 AM
            market_open_hour = 9
            first_candle_minute = 15  # 9:15 AM
                
            market_open = pd.Timestamp(date).replace(hour=market_open_hour, minute=first_candle_minute, second=0)
            market_open = market_open.tz_localize(pytz.timezone('Asia/Kolkata'))
            
            # Store index to timestamp mapping
            idx_to_ts = {}
            for i, idx in enumerate(date_candles.index):
                new_ts = market_open + pd.Timedelta(minutes=i * interval_minutes)
                # Ensure we don't exceed market hours
                if new_ts.hour > 15 or (new_ts.hour == 15 and new_ts.minute > 30):
                    new_ts = market_open.replace(hour=15, minute=30)
                idx_to_ts[idx] = new_ts
                
            # Add to our dictionary
            new_timestamps.update(idx_to_ts)
            
        # Replace timestamps
        for idx, ts in new_timestamps.items():
            df.loc[idx, 'timestamp'] = ts
            
        # Sort by the new timestamps
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        return df
            
    def get_supported_intervals(self) -> list:
        """Get list of supported intervals"""
        return ["1m", "5m", "10m", "15m", "30m", "1h", "D"]
