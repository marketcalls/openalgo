import json
import os
import pandas as pd
from datetime import datetime, timedelta
from database.token_db import get_token, get_br_symbol, get_symbol
import traceback
import time
import httpx
from utils.logging import get_logger
from utils.httpx_client import get_httpx_client

logger = get_logger(__name__)

def get_api_response(endpoint, auth, method="POST", payload=None, custom_timeout=None):
    """
    Common function to make API calls to Firstock using shared httpx client with connection pooling
    """
    try:
        api_key = os.getenv('BROKER_API_KEY')
        if not api_key:
            raise Exception("BROKER_API_KEY not found in environment variables")
            
        api_key = api_key[:-4]  # Firstock specific requirement

        if payload is None:
            data = {
                "userId": api_key
            }
        else:
            data = payload
            data["userId"] = api_key

        # Debug print
        logger.info(f"Endpoint: {endpoint}")
        logger.info(f"Payload: {json.dumps(data, indent=2)}")
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        # Use the full endpoint path as provided
        url = f"https://api.firstock.in/V1{endpoint}"
        
        # For historical data endpoints, use a dedicated client with much longer timeout
        # This bypasses the shared client's 30-second timeout which causes ReadTimeout errors
        if endpoint == "/timePriceSeries" or custom_timeout:
            import httpx
            # Use a dedicated client with very long timeout for historical data
            timeout_value = custom_timeout or 600  # 10 minutes timeout for historical data
            # Create a dedicated client with proper connection limits and long timeout
            with httpx.Client(
                timeout=httpx.Timeout(timeout_value, connect=30.0),  # Long read timeout, normal connect timeout
                limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
                http1=True,  # Use HTTP/1.1 for better compatibility
                http2=False
            ) as temp_client:
                response = temp_client.request(method, url, json=data, headers=headers)
        else:
            # Get the shared httpx client with connection pooling for regular requests
            client = get_httpx_client()
            response = client.request(method, url, json=data, headers=headers)
        
        # Add status attribute for compatibility
        response.status = response.status_code
        
        # Debug print
        response_text = response.text
        logger.info(f"Raw Response: {response_text}")
        
        if not response_text:
            return {"status": "error", "message": "Empty response from server"}
            
        response_data = response.json()
        logger.info(f"Response: {json.dumps(response_data, indent=2)}")
        
        return response_data

    except Exception as e:
        if "timeout" in str(e).lower():
            logger.error("Request timeout while calling Firstock API")
            raise Exception("Request timeout - please try again with smaller date range")
        elif "connection" in str(e).lower():
            logger.error("Connection error while calling Firstock API")
            raise Exception("Connection error - please check your internet connection")
        else:
            logger.error(f"API Error: {e}")
            logger.info(f"Traceback: {traceback.format_exc()}")
            raise

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Firstock data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Firstock resolutions
        self.timeframe_map = {
            # Minutes
            '1m': '1',    # 1 minute
            '3m': '3',    # 3 minutes
            '5m': '5',    # 5 minutes
            '10m': '10',  # 10 minutes
            '15m': '15',  # 15 minutes
            '30m': '30',  # 30 minutes
            # Hours
            '1h': '60',   # 1 hour (60 minutes)
            '2h': '120',  # 2 hours (120 minutes)
            '4h': '240',  # 4 hours (240 minutes)
            # Daily
            'D': 'DAY'    # Daily data
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Simplified quote data with required fields including Open Interest
        """
        try:
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            
            # Map exchange to Firstock format (NSE_INDEX -> NSE)
            firstock_exchange = 'NSE' if exchange == 'NSE_INDEX' else exchange
            
            payload = {
                "userId": os.getenv('BROKER_API_KEY')[:-4],
                "exchange": firstock_exchange,
                "tradingSymbol": br_symbol,
                "jKey": self.auth_token
            }
            
            response = get_api_response("/getQuote", self.auth_token, payload=payload)
            
            if response.get('status') != 'success':
                raise Exception(f"Error from Firstock API: {response.get('error', {}).get('message', 'Unknown error')}")
            
            quote_data = response.get('data', {})
            
            # Debug logging to check response structure
            if not quote_data:
                logger.warning(f"Empty quote data received for {br_symbol} on {firstock_exchange}")
                logger.debug(f"Full response: {response}")
            
            # Create the quote data without any wrapping - let the API handle the wrapping
            return {
                "ask": float(quote_data.get('bestSellPrice1', 0)),
                "bid": float(quote_data.get('bestBuyPrice1', 0)),
                "high": float(quote_data.get('dayHighPrice', 0)),
                "low": float(quote_data.get('dayLowPrice', 0)),
                "ltp": float(quote_data.get('lastTradedPrice', 0)),
                "open": float(quote_data.get('dayOpenPrice', 0)),
                "prev_close": float(quote_data.get('dayClosePrice', 0)),
                "volume": int(quote_data.get('volume', 0)),
                "oi": int(float(quote_data.get('openInterest', 0)))
            }
            
        except Exception as e:
            logger.error(f"Error fetching quotes: {e}")
            return {"status": "error", "message": str(e)}

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data with bids, asks and other details
        """
        try:
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            
            # Map exchange to Firstock format (NSE_INDEX -> NSE)
            firstock_exchange = 'NSE' if exchange == 'NSE_INDEX' else exchange
            
            payload = {
                "userId": os.getenv('BROKER_API_KEY')[:-4],
                "exchange": firstock_exchange,
                "tradingSymbol": br_symbol,
                "jKey": self.auth_token
            }
            
            response = get_api_response("/getQuote", self.auth_token, payload=payload)
            
            if response.get('status') != 'success':
                raise Exception(f"Error from Firstock API: {response.get('error', {}).get('message', 'Unknown error')}")
            
            quote_data = response.get('data', {})
            
            # Format bids and asks data
            bids = []
            asks = []
            
            # Process top 5 bids and asks
            for i in range(1, 6):
                bids.append({
                    'price': float(quote_data.get(f'bestBuyPrice{i}', 0)),
                    'quantity': int(quote_data.get(f'bestBuyQuantity{i}', 0))
                })
                asks.append({
                    'price': float(quote_data.get(f'bestSellPrice{i}', 0)),
                    'quantity': int(quote_data.get(f'bestSellQuantity{i}', 0))
                })
            
            # Return just the data - let the API handle the wrapping
            return {
                'asks': asks,
                'bids': bids,
                'high': float(quote_data.get('dayHighPrice', 0)),
                'low': float(quote_data.get('dayLowPrice', 0)),
                'ltp': float(quote_data.get('lastTradedPrice', 0)),
                'ltq': int(quote_data.get('lastTradedQuantity', 0)),
                'oi': float(quote_data.get('openInterest', 0)),
                'open': float(quote_data.get('dayOpenPrice', 0)),
                'prev_close': float(quote_data.get('dayClosePrice', 0)),
                'totalbuyqty': int(quote_data.get('totalBuyQuantity', 0)),
                'totalsellqty': int(quote_data.get('totalSellQuantity', 0)),
                'volume': int(quote_data.get('volume', 0))
            }
            
        except Exception as e:
            logger.error(f"Error fetching market depth: {e}")
            return {"status": "error", "message": str(e)}

    def get_history_chunked(self, symbol: str, exchange: str, interval: str, start_date, end_date, max_days: int = None) -> pd.DataFrame:
        """
        Get historical data for given symbol using chunked loading for periods longer than max_days.
        This is especially useful for 1-minute data which Firstock provides for 10 years but limits to 30 days per request.
        Optimized for Jupyter notebooks with better timeout handling.

        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Candle interval in common format:
                     Minutes: 1m, 3m, 5m, 10m, 15m, 30m
                     Hours: 1h, 2h, 4h
                     Days: D
            start_date: Start date (YYYY-MM-DD string or datetime.date/datetime object)
            end_date: End date (YYYY-MM-DD string or datetime.date/datetime object)
            max_days: Maximum days per chunk (default: auto-determined based on interval)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Convert dates to datetime objects - handle both string and date/datetime inputs
            if isinstance(start_date, str):
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            elif hasattr(start_date, 'date'):
                # datetime object
                start_dt = start_date if isinstance(start_date, datetime) else datetime.combine(start_date, datetime.min.time())
            else:
                # date object
                start_dt = datetime.combine(start_date, datetime.min.time())

            if isinstance(end_date, str):
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            elif hasattr(end_date, 'date'):
                # datetime object
                end_dt = end_date if isinstance(end_date, datetime) else datetime.combine(end_date, datetime.min.time())
            else:
                # date object
                end_dt = datetime.combine(end_date, datetime.min.time())
            
            # Auto-determine optimal chunk size based on interval if not specified
            # Smaller chunks for Jupyter notebooks to avoid timeouts
            if max_days is None:
                if interval == '1m':
                    max_days = 2  # Extra small chunks for 1-minute data to prevent timeouts
                elif interval in ['3m', '5m']:
                    max_days = 5  # Very small chunks for high-frequency data in notebooks
                elif interval in ['10m', '15m', '30m']:
                    max_days = 10  # Small chunks for medium-frequency data
                else:
                    max_days = 20  # Medium chunks for hourly/daily data
            
            # Calculate total days
            total_days = (end_dt - start_dt).days + 1
            
            logger.info(f"Requesting {interval} data for {symbol} from {start_date} to {end_date} ({total_days} days)")
            logger.info(f"Using chunk size: {max_days} days (optimized for Jupyter notebooks)")
            
            # If within limit, use regular method
            if total_days <= max_days:
                logger.info(f"Date range within {max_days} day limit, using single request")
                return self.get_history(symbol, exchange, interval, start_date, end_date)
            
            # Split into chunks
            logger.info(f"Date range exceeds {max_days} day limit, using chunked loading")
            all_data = []
            current_start = start_dt
            chunk_count = 0
            failed_chunks = 0
            
            while current_start <= end_dt:
                # Calculate chunk end date (max_days - 1 because we include both start and end dates)
                chunk_end = min(current_start + timedelta(days=max_days - 1), end_dt)
                
                chunk_start_str = current_start.strftime('%Y-%m-%d')
                chunk_end_str = chunk_end.strftime('%Y-%m-%d')
                chunk_count += 1
                
                print(f"📊 Fetching chunk {chunk_count}: {chunk_start_str} to {chunk_end_str}")
                
                try:
                    # Fetch data for this chunk
                    chunk_data = self.get_history(symbol, exchange, interval, chunk_start_str, chunk_end_str)
                    
                    if not chunk_data.empty:
                        all_data.append(chunk_data)
                        print(f"✅ Chunk {chunk_count}: Retrieved {len(chunk_data)} candles")
                    else:
                        print(f"⚠️  Chunk {chunk_count}: No data returned")
                        
                except Exception as e:
                    failed_chunks += 1
                    print(f"❌ Error fetching chunk {chunk_count} ({chunk_start_str} to {chunk_end_str}): {e}")
                    logger.error(f"Error fetching chunk {chunk_count} ({chunk_start_str} to {chunk_end_str}): {e}")
                    
                    # If too many chunks fail, suggest smaller chunk size
                    if failed_chunks >= 3:
                        print(f"⚠️  Multiple chunks failing. Consider using smaller chunk size (current: {max_days} days)")
                    
                    # Continue with next chunk instead of failing completely
                    
                # Add small delay between chunks to avoid overwhelming the API
                if current_start < end_dt:  # Don't delay after the last chunk
                    time.sleep(0.5)  # Shorter delay for notebooks
                    
                # Move to next chunk (add 1 day to avoid overlap)
                current_start = chunk_end + timedelta(days=1)
            
            # Combine all chunks
            if not all_data:
                print("❌ No data retrieved from any chunks")
                if failed_chunks > 0:
                    print(f"All {failed_chunks} chunks failed. This might be due to:")
                    print("1. Network connectivity issues")
                    print("2. API rate limiting")
                    print("3. Invalid symbol or date range")
                    print("4. Firstock API service issues")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Concatenate all DataFrames
            combined_df = pd.concat(all_data, ignore_index=True)
            
            # Remove duplicates based on timestamp (in case of overlap)
            combined_df = combined_df.drop_duplicates(subset=['timestamp']).reset_index(drop=True)
            
            # Sort by timestamp
            combined_df = combined_df.sort_values('timestamp').reset_index(drop=True)
            
            success_rate = ((chunk_count - failed_chunks) / chunk_count) * 100 if chunk_count > 0 else 0
            print(f"🎉 Chunked loading complete: Retrieved {len(combined_df)} total candles from {chunk_count} chunks")
            print(f"📈 Success rate: {success_rate:.1f}% ({chunk_count - failed_chunks}/{chunk_count} chunks successful)")
            
            if failed_chunks > 0:
                print(f"⚠️  {failed_chunks} chunks failed - data may be incomplete")
            
            if len(combined_df) > 0:
                start_time = datetime.fromtimestamp(combined_df['timestamp'].min())
                end_time = datetime.fromtimestamp(combined_df['timestamp'].max())
                print(f"📅 Final data range: {start_time} to {end_time}")
            
            return combined_df
            
        except Exception as e:
            logger.error(f"Error in get_history_chunked: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise Exception(f"Error fetching chunked historical data: {str(e)}")

    def get_history_intraday_chunks(self, symbol: str, exchange: str, start_date, end_date) -> pd.DataFrame:
        """
        Special handler for 1-minute data that chunks by hours within each day to avoid timeouts.

        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            start_date: Start date (YYYY-MM-DD string or datetime.date/datetime object)
            end_date: End date (YYYY-MM-DD string or datetime.date/datetime object)
        Returns:
            pd.DataFrame: Historical 1-minute data
        """
        try:
            logger.info(f"Using intraday chunking for 1m data from {start_date} to {end_date}")

            # Convert dates - handle both string and date/datetime inputs
            if isinstance(start_date, str):
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            elif hasattr(start_date, 'date'):
                # datetime object
                start_dt = start_date if isinstance(start_date, datetime) else datetime.combine(start_date, datetime.min.time())
            else:
                # date object
                start_dt = datetime.combine(start_date, datetime.min.time())

            if isinstance(end_date, str):
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            elif hasattr(end_date, 'date'):
                # datetime object
                end_dt = end_date if isinstance(end_date, datetime) else datetime.combine(end_date, datetime.min.time())
            else:
                # date object
                end_dt = datetime.combine(end_date, datetime.min.time())
            
            all_data = []
            current_date = start_dt
            
            while current_date <= end_dt:
                date_str = current_date.strftime('%d-%m-%Y')  # Firstock uses DD-MM-YYYY format
                logger.info(f"Processing date: {date_str}")
                
                # Define trading session chunks using full day to avoid hardcoded timings
                time_chunks = [
                    ("00:00:00", "23:59:59")  # Full day - let API determine available data
                ]
                
                for start_time, end_time in time_chunks:
                    try:
                        # Prepare request for this chunk
                        br_symbol = get_br_symbol(symbol, exchange)
                        firstock_exchange = 'NSE' if exchange == 'NSE_INDEX' else exchange
                        
                        payload = {
                            "userId": os.getenv('BROKER_API_KEY')[:-4],
                            "jKey": self.auth_token,
                            "exchange": firstock_exchange,
                            "tradingSymbol": br_symbol,
                            "startTime": f"{start_time} {date_str}",
                            "endTime": f"{end_time} {date_str}",
                            "interval": "1mi"  # 1-minute interval
                        }
                        
                        logger.info(f"Fetching chunk: {start_time} to {end_time} on {date_str}")
                        
                        # Make request with long timeout to prevent ReadTimeout errors
                        response = get_api_response("/timePriceSeries", self.auth_token, payload=payload, custom_timeout=600)
                        
                        if response.get('status') == 'success':
                            chunk_data = []
                            for candle in response.get('data', []):
                                try:
                                    # Handle timestamp
                                    if 'epochTime' in candle:
                                        timestamp = int(candle['epochTime'])
                                    elif 'time' in candle:
                                        dt = datetime.fromisoformat(candle['time'].replace('T', ' '))
                                        timestamp = int(dt.timestamp())
                                    else:
                                        continue
                                    
                                    chunk_data.append({
                                        'timestamp': timestamp,
                                        'open': float(candle.get('open', 0)),
                                        'high': float(candle.get('high', 0)),
                                        'low': float(candle.get('low', 0)),
                                        'close': float(candle.get('close', 0)),
                                        'volume': int(candle.get('volume', 0))
                                    })
                                except Exception as e:
                                    logger.error(f"Error processing candle: {e}")
                                    continue
                            
                            if chunk_data:
                                all_data.extend(chunk_data)
                                logger.info(f"Retrieved {len(chunk_data)} candles for chunk")
                        else:
                            logger.warning(f"Failed to get data for chunk: {response.get('message', 'Unknown error')}")
                            
                    except Exception as e:
                        logger.error(f"Error fetching chunk {start_time}-{end_time} on {date_str}: {e}")
                        continue
                    
                    # Small delay between chunks
                    time.sleep(0.5)
                
                # Move to next day
                current_date += timedelta(days=1)
            
            # Convert to DataFrame
            if not all_data:
                logger.warning("No data retrieved from any chunks")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            df = pd.DataFrame(all_data)
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            logger.info(f"Total 1m candles retrieved: {len(df)}")
            return df
            
        except Exception as e:
            logger.error(f"Error in get_history_intraday_chunks: {e}")
            raise Exception(f"Error fetching 1m historical data: {str(e)}")

    def get_history(self, symbol: str, exchange: str, interval: str, start_date, end_date) -> pd.DataFrame:
        """
        Get historical data for given symbol using new Firstock API

        Automatically switches to chunked loading for large date ranges to prevent timeouts.
        This ensures compatibility with existing code while handling large requests efficiently.

        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Candle interval in common format:
                     Minutes: 1m, 3m, 5m, 10m, 15m, 30m
                     Hours: 1h, 2h, 4h
                     Days: D
            start_date: Start date (YYYY-MM-DD string or datetime.date/datetime object)
            end_date: End date (YYYY-MM-DD string or datetime.date/datetime object)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Convert dates to datetime objects for validation - handle both string and date/datetime inputs
            if isinstance(start_date, str):
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            elif hasattr(start_date, 'date'):
                # datetime object
                start_dt = start_date if isinstance(start_date, datetime) else datetime.combine(start_date, datetime.min.time())
            else:
                # date object
                start_dt = datetime.combine(start_date, datetime.min.time())

            if isinstance(end_date, str):
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            elif hasattr(end_date, 'date'):
                # datetime object
                end_dt = end_date if isinstance(end_date, datetime) else datetime.combine(end_date, datetime.min.time())
            else:
                # date object
                end_dt = datetime.combine(end_date, datetime.min.time())
            
            # Calculate date range in days
            date_range_days = (end_dt - start_dt).days + 1
            
            # Set chunk size based on interval - very aggressive chunking for Firstock
            # For 1m data, we'll use intraday chunking to handle even single day timeouts
            if interval == '1m':
                logger.info("Using special intraday chunking for 1-minute data")
                return self.get_history_intraday_chunks(symbol, exchange, start_date, end_date)
            
            interval_limits = {
                '3m': 2,     # THREE_MINUTE - very small chunks
                '5m': 3,     # FIVE_MINUTE - very small chunks  
                '10m': 5,    # TEN_MINUTE - very small chunks
                '15m': 7,    # FIFTEEN_MINUTE - very small chunks
                '30m': 10,   # THIRTY_MINUTE - very small chunks
                '1h': 15,    # ONE_HOUR - smaller than Angel
                '2h': 15,    # TWO_HOUR
                '4h': 15,    # FOUR_HOUR
                'D': 30      # ONE_DAY - much smaller than Angel
            }
            
            chunk_days = interval_limits.get(interval, 30)  # Default to 30 days
            
            # If date range is within chunk limit, use single request
            if date_range_days <= chunk_days:
                return self._get_single_history_chunk(symbol, exchange, interval, start_date, end_date)
            
            # For large date ranges, use automatic chunking
            logger.info(f"Large date range detected ({date_range_days} days). Using automatic chunking with {chunk_days}-day chunks.")
            
            # Initialize empty list to store DataFrames
            dfs = []
            
            # Process data in chunks
            current_start = start_dt
            chunk_count = 0
            successful_chunks = 0
            
            while current_start <= end_dt:
                # Calculate chunk end date
                current_end = min(current_start + timedelta(days=chunk_days-1), end_dt)
                
                chunk_start_str = current_start.strftime('%Y-%m-%d')
                chunk_end_str = current_end.strftime('%Y-%m-%d')
                chunk_count += 1
                
                logger.info(f"📊 Fetching chunk {chunk_count}: {chunk_start_str} to {chunk_end_str}")
                
                try:
                    # Fetch chunk
                    chunk_df = self._get_single_history_chunk(symbol, exchange, interval, chunk_start_str, chunk_end_str)
                    
                    if not chunk_df.empty:
                        dfs.append(chunk_df)
                        successful_chunks += 1
                        logger.info(f"✅ Chunk {chunk_count} successful: {len(chunk_df)} records")
                    else:
                        logger.warning(f"⚠️ Chunk {chunk_count} returned no data")
                        
                except Exception as chunk_error:
                    logger.error(f"❌ Chunk {chunk_count} failed: {str(chunk_error)}")
                
                # Move to next chunk
                current_start = current_end + timedelta(days=1)
                
                # Add delay between chunks to be API-friendly
                if current_start <= end_dt:
                    # Longer delay for 1-minute data to avoid rate limiting
                    delay = 1.0 if interval == '1m' else 0.5
                    time.sleep(delay)
            
            # Combine all chunks
            if not dfs:
                logger.error("No data retrieved from any chunks")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Concatenate all DataFrames
            combined_df = pd.concat(dfs, ignore_index=True)
            
            # Remove duplicates and sort by timestamp
            combined_df = combined_df.drop_duplicates(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
            
            success_rate = (successful_chunks / chunk_count) * 100 if chunk_count > 0 else 0
            logger.info(f"🎯 Chunked loading complete: {len(combined_df)} total records")
            logger.info(f"📈 Success rate: {success_rate:.1f}% ({successful_chunks}/{chunk_count} chunks successful)")
            
            return combined_df
            
        except Exception as e:
            logger.error(f"Error in get_history: {str(e)}")
            return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    def _get_single_history_chunk(self, symbol: str, exchange: str, interval: str, start_date, end_date) -> pd.DataFrame:
        """
        Get historical data for given symbol using new Firstock API
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Candle interval in common format:
                     Minutes: 1m, 3m, 5m, 10m, 15m, 30m
                     Hours: 1h, 2h, 4h
                     Days: D
            start_date: Start date (YYYY-MM-DD string or datetime.date/datetime object)
            end_date: End date (YYYY-MM-DD string or datetime.date/datetime object)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)

            # Convert dates to datetime objects - handle both string and date/datetime inputs
            if isinstance(start_date, str):
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            elif hasattr(start_date, 'date'):
                # datetime object
                start_dt = start_date if isinstance(start_date, datetime) else datetime.combine(start_date, datetime.min.time())
            else:
                # date object
                start_dt = datetime.combine(start_date, datetime.min.time())

            if isinstance(end_date, str):
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            elif hasattr(end_date, 'date'):
                # datetime object
                end_dt = end_date if isinstance(end_date, datetime) else datetime.combine(end_date, datetime.min.time())
            else:
                # date object
                end_dt = datetime.combine(end_date, datetime.min.time())
            
            # Check if date range exceeds 30 days and warn user
            total_days = (end_dt - start_dt).days + 1
            if total_days > 30:
                logger.warning(f"Date range ({total_days} days) exceeds Firstock's 30-day limit. Consider using get_history_chunked() for better results, especially in Jupyter notebooks.")
            
            data = []
            
            # Handle daily vs intraday intervals
            if interval == 'D':
                # Daily data: use "1d" interval and format times as required by new API
                api_interval = "1d"
                # For daily data, use 00:00:00 format as shown in API docs
                start_str = f"00:00:00 {start_dt.strftime('%d-%m-%Y')}"
                end_str = f"00:00:00 {end_dt.strftime('%d-%m-%Y')}"
            else:
                # Map common timeframe to new API format
                interval_map = {
                    '1m': '1mi',   '3m': '3mi',   '5m': '5mi',
                    '10m': '10mi', '15m': '15mi', '30m': '30mi',
                    '1h': '60mi',  '2h': '120mi', '4h': '240mi'
                }
                
                if interval not in interval_map:
                    supported = list(interval_map.keys()) + ['D']
                    raise Exception(f"Unsupported interval '{interval}'. Supported intervals are: {', '.join(supported)}")
                
                api_interval = interval_map[interval]
                # Intraday data: use full day time range to allow API to determine available data
                # This removes dependency on specific market hours and supports special sessions
                start_str = f"00:00:00 {start_dt.strftime('%d-%m-%Y')}"
                end_str = f"23:59:59 {end_dt.strftime('%d-%m-%Y')}"
            
            logger.info(f"Getting {interval} data for {br_symbol} from {start_str} to {end_str}")
            
            # Map exchange to Firstock format (NSE_INDEX -> NSE)
            firstock_exchange = 'NSE' if exchange == 'NSE_INDEX' else exchange
            
            # Prepare payload according to new API format
            payload = {
                "userId": os.getenv('BROKER_API_KEY')[:-4],
                "jKey": self.auth_token,
                "exchange": firstock_exchange,
                "tradingSymbol": br_symbol,
                "startTime": start_str,
                "endTime": end_str,
                "interval": api_interval
            }
            
            # Use the new timePriceSeries endpoint
            response = get_api_response("/timePriceSeries", self.auth_token, payload=payload)
            
            if response.get('status') != 'success':
                error_msg = response.get('message', 'Unknown error')
                logger.error(f"API error: {error_msg}")
                raise Exception(f"Error from Firstock API: {error_msg}")
            
            # Process response data according to new API format
            for candle in response.get('data', []):
                try:
                    # Handle timestamp - new API provides epochTime
                    if 'epochTime' in candle:
                        timestamp = int(candle['epochTime'])
                    elif 'time' in candle:
                        # Parse time format from new API
                        if interval == 'D':
                            # Daily format: "00:00:00 23-04-2025"
                            time_str = candle['time']
                            if ' ' in time_str:
                                date_part = time_str.split(' ')[1]  # Get date part
                                dt = datetime.strptime(date_part, '%d-%m-%Y')
                                # Use the timestamp as provided by the API without adjusting to market hours
                                # This ensures we use whatever time the exchange actually operated
                                pass
                            else:
                                # ISO format: "2025-02-10T09:15:00"
                                dt = datetime.fromisoformat(time_str.replace('T', ' '))
                        else:
                            # Intraday format: "2025-02-10T09:15:00" 
                            dt = datetime.fromisoformat(candle['time'].replace('T', ' '))
                        timestamp = int(dt.timestamp())
                    else:
                        logger.warning(f"No timestamp found in candle: {candle}")
                        continue
                    
                    # Debug logging for daily data timestamps
                    if interval == 'D':
                        debug_dt = datetime.fromtimestamp(timestamp)
                        logger.info(f"DEBUG: Daily candle timestamp: {timestamp} -> {debug_dt}")
                    
                    # Extract OHLCV data according to new API format
                    data.append({
                        'timestamp': timestamp,
                        'open': float(candle.get('open', 0)),
                        'high': float(candle.get('high', 0)),
                        'low': float(candle.get('low', 0)),
                        'close': float(candle.get('close', 0)),
                        'volume': int(candle.get('volume', 0))
                    })
                    
                except (ValueError, TypeError, KeyError) as e:
                    logger.error(f"Error processing candle {candle}: {e}")
                    continue
            
            if not data:
                logger.info("No historical data available for the requested period")
                return pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            # Convert to DataFrame and sort by timestamp
            df = pd.DataFrame(data)
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            # Ensure timestamp is Unix timestamp (integer)
            # The API should return Unix timestamps, but let's ensure it
            if df['timestamp'].dtype != 'int64':
                logger.warning(f"Timestamp dtype is {df['timestamp'].dtype}, converting to int64")
                df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')
            
            # For daily timeframe, adjust timestamp to show market opening time (9:15 AM IST)
            if interval == 'D':
                # Convert Unix timestamp to datetime
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
                # Ensure it's at 9:15 AM IST
                df['timestamp'] = df['timestamp'].dt.normalize() + pd.Timedelta(hours=9, minutes=15)
                # Convert back to Unix timestamp
                df['timestamp'] = df['timestamp'].astype('int64') // 10**9
            
            # Log summary
            logger.info(f"Retrieved {len(df)} candles")
            if len(df) > 0:
                start_time = datetime.fromtimestamp(df['timestamp'].min())
                end_time = datetime.fromtimestamp(df['timestamp'].max())
                logger.info(f"Data range: {start_time} to {end_time}")
            
            return df
            
        except Exception as e:
            logger.error(f"Error in get_history: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise Exception(f"Error fetching historical data: {str(e)}")


