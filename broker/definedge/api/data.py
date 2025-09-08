import http.client
import json
import pandas as pd
from datetime import datetime, timedelta
from database.token_db import get_br_symbol, get_token, get_oa_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

def authenticate_broker(api_token, api_secret, otp):
    """
    Authenticate with DefinedGe Securities broker
    Returns: (auth_token, error_message)
    """
    try:
        from broker.definedge.api.auth_api import authenticate_broker as auth_broker
        return auth_broker(api_token, api_secret, otp)
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        return None, str(e)

def get_quotes(symbol, exchange, auth_token):
    """Get real-time quotes for a symbol"""
    try:
        api_session_key, susertoken, api_token = auth_token.split(":::")

        # Use httpx client for consistency
        from utils.httpx_client import get_httpx_client
        client = get_httpx_client()

        # Get token for the symbol
        from database.token_db import get_token
        token_id = get_token(symbol, exchange)
        
        logger.info(f"Getting quotes for {symbol} ({exchange}) with token: {token_id}")

        # Handle index symbols - map to their respective exchanges
        api_exchange = exchange
        if exchange == 'NSE_INDEX':
            api_exchange = 'NSE'
        elif exchange == 'BSE_INDEX':
            api_exchange = 'BSE'
        elif exchange == 'MCX_INDEX':
            api_exchange = 'MCX'

        headers = {
            'Authorization': api_session_key
        }

        # Use the correct Definedge quotes endpoint: /dart/v1/quotes/{exchange}/{token}
        # According to API docs, the relative URL is /quotes/{exchange}/{token}
        # But the full path includes /dart/v1
        url = f"https://integrate.definedgesecurities.com/dart/v1/quotes/{api_exchange}/{token_id}"
        
        response = client.get(url, headers=headers)
        
        logger.debug(f"Quotes API Response Status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Quotes API error: Status {response.status_code}, Response: {response.text}")
            return {"status": "error", "message": f"API returned status {response.status_code}"}
        
        logger.debug(f"Quotes API Response: {response.text}")
        
        return response.json()

    except Exception as e:
        logger.error(f"Error getting quotes: {e}")
        return {"status": "error", "message": str(e)}

def get_security_info(symbol, exchange, auth_token):
    """Get security information"""
    try:
        api_session_key, susertoken, api_token = auth_token.split(":::")

        conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

        headers = {
            'Authorization': api_session_key,
            'Content-Type': 'application/json'
        }

        payload = json.dumps({
            "exchange": exchange,
            "tradingsymbol": symbol
        })

        conn.request("POST", "/dart/v1/security_info", payload, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")

        return json.loads(data)

    except Exception as e:
        logger.error(f"Error getting security info: {e}")
        return {"status": "error", "message": str(e)}

def get_margin_info(auth_token):
    """Get margin information"""
    try:
        api_session_key, susertoken, api_token = auth_token.split(":::")

        conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

        headers = {
            'Authorization': api_session_key,
            'Content-Type': 'application/json'
        }

        conn.request("GET", "/dart/v1/margin", '', headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")

        return json.loads(data)

    except Exception as e:
        logger.error(f"Error getting margin info: {e}")
        return {"status": "error", "message": str(e)}

def get_limits(auth_token):
    """Get account limits"""
    try:
        api_session_key, susertoken, api_token = auth_token.split(":::")

        conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

        headers = {
            'Authorization': api_session_key,
            'Content-Type': 'application/json'
        }

        conn.request("GET", "/dart/v1/limits", '', headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")

        return json.loads(data)

    except Exception as e:
        logger.error(f"Error getting limits: {e}")
        return {"status": "error", "message": str(e)}

class BrokerData:
    def __init__(self, auth_token):
        """Initialize DefinedGe data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to DefinedGe resolutions
        # Definedge only supports: 1m, 5m, 15m, 30m, 1h, D
        self.timeframe_map = {
            # Minutes
            '1m': 'minute',
            '5m': 'minute',
            '15m': 'minute',
            '30m': 'minute',
            # Hours
            '1h': 'minute',
            # Daily
            'D': 'day'
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
        Returns:
            dict: Quote data with required fields
        """
        try:
            # Use the updated get_quotes function with correct endpoint
            response = get_quotes(symbol, exchange, self.auth_token)
            
            logger.info(f"Raw quotes response: {response}")
            
            if response.get('status') == 'error':
                raise Exception(response.get('message', 'Unknown error'))
            
            # Check if response has SUCCESS status
            if response.get('status') != 'SUCCESS':
                raise Exception(f"API returned status: {response.get('status', 'Unknown')}")
            
            # Map Definedge response fields to OpenAlgo format
            # Definedge fields based on the documentation:
            # - best_bid_price1 -> bid
            # - best_ask_price1 -> ask  
            # - day_open -> open
            # - day_high -> high
            # - day_low -> low
            # - ltp -> ltp
            # - Previous close might be calculated or use day_open
            # - volume -> volume
            # - OI is not in equity but might be in derivatives
            
            return {
                'bid': float(response.get('best_bid_price1', 0)),
                'ask': float(response.get('best_ask_price1', 0)),
                'open': float(response.get('day_open', 0)),
                'high': float(response.get('day_high', 0)),
                'low': float(response.get('day_low', 0)),
                'ltp': float(response.get('ltp', 0)),
                'prev_close': float(response.get('day_open', response.get('ltp', 0))),  # Use day_open as prev_close
                'volume': int(response.get('volume', 0)),
                'oi': 0  # OI might not be available for equity, set to 0
            }
            
        except Exception as e:
            logger.error(f"Error in get_quotes: {str(e)}")
            raise Exception(f"Error fetching quotes: {str(e)}")

    def get_history(self, symbol: str, exchange: str, interval: str, 
                   start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
            interval: Candle interval (1m, 3m, 5m, 10m, 15m, 30m, 1h, D)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume, oi]
        """
        try:
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)
            
            logger.debug(f"Debug - Broker Symbol: {br_symbol}, Token: {token}")

            # Check for unsupported timeframes
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                logger.warning(f"Timeframe '{interval}' is not supported by Definedge. Supported timeframes are: {', '.join(supported)}")
                # Return empty DataFrame instead of raising exception
                return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])
            
            # Convert dates to datetime objects
            from_date = pd.to_datetime(start_date)
            to_date = pd.to_datetime(end_date)
            
            # For intraday data, set specific times
            if interval != 'D':
                # Set start time to 09:15 (market open) for the start date
                from_date = from_date.replace(hour=9, minute=15)
                
                # If end_date is today, set the end time to current time
                current_time = pd.Timestamp.now()
                if to_date.date() == current_time.date():
                    to_date = current_time.replace(second=0, microsecond=0)
                else:
                    # For past dates, set end time to 15:30 (market close)
                    to_date = to_date.replace(hour=15, minute=30)
            else:
                # For daily data, use 00:00
                from_date = from_date.replace(hour=0, minute=0)
                to_date = to_date.replace(hour=0, minute=0)
            
            # Initialize empty list to store DataFrames
            dfs = []
            
            # Set chunk size based on interval
            # Definedge limits: Daily (20 years), Intraday (6 months), Tick (2 days)
            # Definedge only supports: 1m, 5m, 15m, 30m, 1h, D
            interval_limits = {
                '1m': 30,    # minute - 30 days per chunk
                '5m': 90,    # 5 minutes - 90 days per chunk
                '15m': 150,  # 15 minutes - 150 days per chunk
                '30m': 180,  # 30 minutes - 180 days per chunk (6 months max)
                '1h': 180,   # 60 minutes - 180 days per chunk (6 months max)
                'D': 365     # day - 365 days per chunk
            }
            
            chunk_days = interval_limits.get(interval, 30)
            
            # Map interval to Definedge timeframe
            # Definedge only accepts 'minute', 'day', or 'tick' as timeframe
            # For all minute-based intervals, we get 1-minute data and resample
            timeframe = self.timeframe_map.get(interval, 'day')
            
            # Get auth token
            api_session_key, susertoken, api_token = self.auth_token.split(":::")
            
            # Process data in chunks
            current_start = from_date
            while current_start <= to_date:
                # Calculate chunk end date
                current_end = min(current_start + timedelta(days=chunk_days-1), to_date)
                
                # Format dates for Definedge API (ddMMyyyyHHmm)
                from_date_str = current_start.strftime('%d%m%Y%H%M')
                to_date_str = current_end.strftime('%d%m%Y%H%M')
                
                # Build URL for Definedge historical data API
                # Format: /sds/history/{segment}/{token}/{timeframe}/{from}/{to}
                # Definedge only accepts 'minute', 'day', or 'tick' as timeframe
                # Handle index symbols - NSE_INDEX should be mapped to NSE
                segment = exchange.upper()
                if segment == 'NSE_INDEX':
                    segment = 'NSE'
                elif segment == 'BSE_INDEX':
                    segment = 'BSE'
                elif segment == 'MCX_INDEX':
                    segment = 'MCX'
                
                url = f"https://data.definedgesecurities.com/sds/history/{segment}/{token}/{timeframe}/{from_date_str}/{to_date_str}"
                
                logger.debug(f"Debug - Fetching chunk from {current_start} to {current_end}")
                logger.debug(f"Debug - API URL: {url}")
                logger.debug(f"Debug - Headers: Authorization key present: {bool(api_session_key)}")
                
                try:
                    # Use httpx client for consistency
                    from utils.httpx_client import get_httpx_client
                    client = get_httpx_client()
                    
                    headers = {
                        'Authorization': api_session_key
                    }
                    
                    response = client.get(url, headers=headers)
                    
                    logger.debug(f"Debug - Response status: {response.status_code}")
                    logger.debug(f"Debug - Response headers: {dict(response.headers)}")
                    logger.debug(f"Debug - Response text length: {len(response.text)}")
                    
                    if response.status_code != 200:
                        logger.warning(f"Debug - Definedge API returned status {response.status_code}")
                        logger.warning(f"Debug - Response body: {response.text}")
                        current_start = current_end + timedelta(days=1)
                        continue
                    
                    # Parse CSV response
                    # Format for day/minute: Dateandtime, Open, High, Low, Close, Volume, OI
                    # Format for tick: UTC(seconds), LTP, LTQ, OI
                    csv_data = response.text.strip()
                    
                    if not csv_data:
                        logger.debug(f"Debug - Empty response for chunk {current_start} to {current_end}")
                        current_start = current_end + timedelta(days=1)
                        continue
                    
                    # Log first few lines of CSV for debugging
                    csv_lines = csv_data.split('\n')[:5]
                    logger.debug(f"Debug - First few lines of CSV: {csv_lines}")
                    logger.debug(f"Debug - Total lines in CSV: {len(csv_data.split('\n'))}")
                    logger.debug(f"Debug - Timeframe: {timeframe}, Interval: {interval}")
                    
                    # Parse CSV data
                    from io import StringIO
                    
                    if timeframe == 'tick':
                        # For tick data: UTC(seconds), LTP, LTQ, OI
                        chunk_df = pd.read_csv(StringIO(csv_data), 
                                              names=['timestamp', 'close', 'volume', 'oi'],
                                              header=None)
                        # For tick data, we need to set OHLC as same as close
                        chunk_df['open'] = chunk_df['close']
                        chunk_df['high'] = chunk_df['close']
                        chunk_df['low'] = chunk_df['close']
                    else:
                        # For day/minute data: Dateandtime, Open, High, Low, Close, Volume, OI (only 6 columns, no OI for equity)
                        # Check number of columns in the CSV
                        first_line = csv_lines[0] if csv_lines else ""
                        num_columns = len(first_line.split(','))
                        
                        if num_columns == 6:
                            # No OI column (equity data)
                            chunk_df = pd.read_csv(StringIO(csv_data), 
                                                  names=['datetime', 'open', 'high', 'low', 'close', 'volume'],
                                                  header=None)
                            chunk_df['oi'] = 0  # Add OI column with 0 values
                        else:
                            # With OI column (derivatives data)
                            chunk_df = pd.read_csv(StringIO(csv_data), 
                                                  names=['datetime', 'open', 'high', 'low', 'close', 'volume', 'oi'],
                                                  header=None)
                        
                        # Convert datetime string to timestamp
                        # Definedge format is ddMMyyyyHHmm (e.g., 010920250915 = 01-09-2025 09:15)
                        chunk_df['datetime'] = chunk_df['datetime'].astype(str)
                        
                        # For daily data, the format is the same as minute data but with 0000 for time
                        if timeframe == 'day':
                            # Daily data has format ddMMyyyyHHmm with 0000 for time
                            # e.g., 10920250000 = 01-09-2025 00:00
                            sample_date = chunk_df['datetime'].iloc[0] if not chunk_df.empty else ""
                            logger.debug(f"Debug - Sample date for daily data: '{sample_date}', length: {len(str(sample_date))}")
                            
                            if len(str(sample_date)) == 11:
                                # Format is ddMMyyyyHHmm (11 digits for dates after year 999)
                                # First digit is day (1-3), so prepend 0 if needed
                                chunk_df['datetime'] = chunk_df['datetime'].astype(str).str.zfill(12)
                                chunk_df['timestamp'] = pd.to_datetime(chunk_df['datetime'], 
                                                                      format='%d%m%Y%H%M',
                                                                      errors='coerce')
                            elif len(str(sample_date)) == 12:
                                # Format is already ddMMyyyyHHmm (12 digits)
                                chunk_df['timestamp'] = pd.to_datetime(chunk_df['datetime'], 
                                                                      format='%d%m%Y%H%M',
                                                                      errors='coerce')
                            else:
                                # Try the standard format anyway
                                chunk_df['timestamp'] = pd.to_datetime(chunk_df['datetime'], 
                                                                      format='%d%m%Y%H%M',
                                                                      errors='coerce')
                        else:
                            # Minute data has format ddMMyyyyHHmm
                            chunk_df['timestamp'] = pd.to_datetime(chunk_df['datetime'], 
                                                                  format='%d%m%Y%H%M',
                                                                  errors='coerce')
                        
                        # Drop the datetime column
                        chunk_df = chunk_df.drop('datetime', axis=1)
                        
                        # Remove rows with invalid timestamps
                        chunk_df = chunk_df.dropna(subset=['timestamp'])
                    
                    # Log DataFrame info after parsing
                    logger.debug(f"Debug - DataFrame shape after parsing: {chunk_df.shape}")
                    logger.debug(f"Debug - DataFrame columns: {chunk_df.columns.tolist()}")
                    if not chunk_df.empty:
                        logger.debug(f"Debug - First row of DataFrame: {chunk_df.iloc[0].to_dict() if len(chunk_df) > 0 else 'Empty'}")
                    
                    # Check if we have valid data
                    if chunk_df.empty:
                        logger.info(f"Debug - No valid data after parsing CSV for {timeframe} timeframe")
                        logger.info(f"Debug - This might be due to incorrect date parsing")
                        current_start = current_end + timedelta(days=1)
                        continue
                    
                    # For minute intervals other than 1m, we need to resample
                    # Definedge returns 1-minute data that we resample to the desired interval
                    if interval != 'D' and timeframe == 'minute' and interval != '1m':
                        interval_minutes = {
                            '5m': 5,
                            '15m': 15,
                            '30m': 30,
                            '1h': 60
                        }
                        
                        if interval in interval_minutes:
                            try:
                                # Ensure timestamp is datetime
                                if not pd.api.types.is_datetime64_any_dtype(chunk_df['timestamp']):
                                    chunk_df['timestamp'] = pd.to_datetime(chunk_df['timestamp'])
                                
                                # Remove any NaT values before resampling
                                chunk_df = chunk_df.dropna(subset=['timestamp'])
                                
                                if not chunk_df.empty:
                                    chunk_df = chunk_df.set_index('timestamp')
                                    
                                    # Create a custom offset to align with market open at 09:15
                                    # This ensures 30m candles start at 09:15, not 09:00
                                    offset_minutes = 15  # Market opens at 09:15, so offset by 15 minutes
                                    
                                    # Resample with the offset to align with market hours
                                    resample_rule = f'{interval_minutes[interval]}min'
                                    # Use offset parameter to shift the bins to start at :15 and :45 for 30m
                                    # For other intervals, the offset ensures proper market alignment
                                    resampled = chunk_df.resample(resample_rule, offset=f'{offset_minutes}min')
                                    
                                    chunk_df = pd.DataFrame({
                                        'open': resampled['open'].first(),
                                        'high': resampled['high'].max(),
                                        'low': resampled['low'].min(),
                                        'close': resampled['close'].last(),
                                        'volume': resampled['volume'].sum(),
                                        'oi': resampled['oi'].last()
                                    }).dropna()
                                    
                                    chunk_df = chunk_df.reset_index()
                            except Exception as resample_error:
                                logger.debug(f"Debug - Error during resampling: {str(resample_error)}")
                                # Continue with original 1-minute data if resampling fails
                    
                    # Don't convert timestamp to Unix epoch here - keep as datetime for now
                    # We'll convert it later after combining all chunks, similar to Angel
                    if 'timestamp' in chunk_df.columns:
                        if chunk_df['timestamp'].dtype == 'object':
                            chunk_df['timestamp'] = pd.to_datetime(chunk_df['timestamp'])
                        elif pd.api.types.is_numeric_dtype(chunk_df['timestamp']):
                            # Convert Unix timestamp to datetime for consistency
                            chunk_df['timestamp'] = pd.to_datetime(chunk_df['timestamp'], unit='s')
                        elif not pd.api.types.is_datetime64_any_dtype(chunk_df['timestamp']):
                            chunk_df['timestamp'] = pd.to_datetime(chunk_df['timestamp'])
                    
                    if not chunk_df.empty:
                        # Log the date range of data received
                        min_ts = chunk_df['timestamp'].min()
                        max_ts = chunk_df['timestamp'].max()
                        logger.debug(f"Debug - Chunk data range: {min_ts} to {max_ts}")
                        logger.debug(f"Debug - Received {len(chunk_df)} candles for chunk {current_start.date()} to {current_end.date()}")
                        dfs.append(chunk_df)
                    else:
                        logger.debug(f"Debug - Empty DataFrame after processing chunk")
                    
                except Exception as chunk_error:
                    logger.error(f"Debug - Error fetching chunk {current_start} to {current_end}: {str(chunk_error)}")
                    current_start = current_end + timedelta(days=1)
                    continue
                
                # Move to next chunk
                current_start = current_end + timedelta(days=1)
            
            # If no data was found, return empty DataFrame
            if not dfs:
                logger.debug("Debug - No data received from API, returning empty DataFrame")
                return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])
            
            logger.debug(f"Debug - Total chunks collected: {len(dfs)}")
            
            # Combine all chunks
            df = pd.concat(dfs, ignore_index=True)
            logger.debug(f"Debug - Combined DataFrame shape: {df.shape}")
            
            # Ensure timestamp is datetime type (it should already be)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Handle timestamps based on interval type
            if interval == 'D':
                # For daily timeframe, ensure timestamps are at midnight
                df['timestamp'] = pd.to_datetime(df['timestamp']).dt.normalize()
                # Don't add any offset for daily data - keep at midnight
                # Convert to Unix epoch (treating as naive timestamp, will be interpreted as UTC)
                df['timestamp'] = df['timestamp'].astype('int64') // 10**9
            else:
                # For intraday intervals (minute data)
                # Definedge returns timestamps in IST (Indian Standard Time)
                # We need to localize them as IST and convert to UTC before converting to Unix epoch
                # This ensures the OpenAlgo client interprets them correctly
                # Localize as IST (the timestamps from Definedge are in IST)
                df['timestamp'] = df['timestamp'].dt.tz_localize('Asia/Kolkata')
                # Convert to UTC for storage as Unix epoch
                df['timestamp'] = df['timestamp'].dt.tz_convert('UTC')
                # Now convert to Unix epoch (this will be in UTC)
                df['timestamp'] = df['timestamp'].astype('int64') // 10**9  # Convert to Unix epoch in seconds
            
            # Ensure numeric columns
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_columns:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            # Ensure OI column exists and is numeric
            if 'oi' not in df.columns:
                df['oi'] = 0
            else:
                df['oi'] = pd.to_numeric(df['oi'], errors='coerce').fillna(0).astype(int)
            
            # Sort by timestamp and remove duplicates
            if 'timestamp' in df.columns:
                df = df.sort_values('timestamp').drop_duplicates(subset=['timestamp']).reset_index(drop=True)
            
            # Reorder columns to match OpenAlgo format (timestamp should be 5th column)
            # Order: close, high, low, open, timestamp, volume, oi
            df = df[['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi']]
            
            logger.debug(f"Debug - Final DataFrame shape: {df.shape}")
            logger.debug(f"Debug - Timestamp dtype: {df['timestamp'].dtype}")
            logger.info(f"Successfully fetched {len(df)} candles for {symbol}")
            
            return df
            
        except Exception as e:
            logger.warning(f"Debug - Definedge historical data error: {str(e)}")
            # Return empty DataFrame instead of raising exception to prevent system crashes
            return pd.DataFrame(columns=['close', 'high', 'low', 'open', 'timestamp', 'volume', 'oi'])

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
        Returns:
            dict: Market depth data with bids, asks and other details
        """
        try:
            # Get quotes data which includes depth information
            response = get_quotes(symbol, exchange, self.auth_token)
            
            logger.debug(f"Depth API response: {response}")
            
            if response.get('status') == 'error':
                raise Exception(response.get('message', 'Unknown error'))
            
            if response.get('status') != 'SUCCESS':
                raise Exception(f"API returned status: {response.get('status', 'Unknown')}")
            
            # Format bids and asks with exactly 5 entries each
            bids = []
            asks = []
            
            # Process buy orders (top 5) - Definedge format
            for i in range(1, 6):
                bid_price = response.get(f'best_bid_price{i}', 0)
                bid_qty = response.get(f'best_bid_qty{i}', 0)
                bids.append({
                    'price': float(bid_price) if bid_price else 0,
                    'quantity': int(bid_qty) if bid_qty else 0
                })
            
            # Process sell orders (top 5) - Definedge format
            for i in range(1, 6):
                ask_price = response.get(f'best_ask_price{i}', 0)
                ask_qty = response.get(f'best_ask_qty{i}', 0)
                asks.append({
                    'price': float(ask_price) if ask_price else 0,
                    'quantity': int(ask_qty) if ask_qty else 0
                })
            
            # Calculate total buy/sell quantities
            totalbuyqty = sum(bid['quantity'] for bid in bids)
            totalsellqty = sum(ask['quantity'] for ask in asks)
            
            # Return depth data in common format
            return {
                'bids': bids,
                'asks': asks,
                'high': float(response.get('day_high', 0)),
                'low': float(response.get('day_low', 0)),
                'ltp': float(response.get('ltp', 0)),
                'ltq': int(response.get('last_traded_qty', 0)),
                'open': float(response.get('day_open', 0)),
                'prev_close': float(response.get('day_open', 0)),  # Use day_open as prev_close
                'volume': int(response.get('volume', 0)),
                'oi': 0,  # OI might not be available for equity
                'totalbuyqty': totalbuyqty,
                'totalsellqty': totalsellqty
            }
            
        except Exception as e:
            logger.error(f"Error in get_depth: {str(e)}")
            raise Exception(f"Error fetching market depth: {str(e)}")
