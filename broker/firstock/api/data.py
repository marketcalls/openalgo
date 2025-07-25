import json
import os
import pandas as pd
from datetime import datetime, timedelta
from database.token_db import get_token, get_br_symbol, get_symbol
import traceback
from utils.logging import get_logger
from utils.httpx_client import get_httpx_client

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="POST", payload=None):
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

        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        # Use the full endpoint path as provided
        url = f"https://api.firstock.in/V1{endpoint}"
        
        # Make request using shared httpx client
        response = client.request(method, url, json=data, headers=headers, timeout=30)
        
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
            raise Exception("Request timeout - please try again")
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

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Simplified quote data with required fields
        """
        try:
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            
            payload = {
                "userId": os.getenv('BROKER_API_KEY')[:-4],
                "exchange": exchange,
                "tradingSymbol": br_symbol,
                "jKey": self.auth_token
            }
            
            response = get_api_response("/getQuote", self.auth_token, payload=payload)
            
            if response.get('status') != 'success':
                raise Exception(f"Error from Firstock API: {response.get('error', {}).get('message', 'Unknown error')}")
            
            quote_data = response.get('data', {})
            
            # Create the quote data without any wrapping - let the API handle the wrapping
            return {
                "ask": float(quote_data.get('bestSellPrice1', 0)),
                "bid": float(quote_data.get('bestBuyPrice1', 0)),
                "high": float(quote_data.get('dayHighPrice', 0)),
                "low": float(quote_data.get('dayLowPrice', 0)),
                "ltp": float(quote_data.get('lastTradedPrice', 0)),
                "open": float(quote_data.get('dayOpenPrice', 0)),
                "prev_close": float(quote_data.get('dayClosePrice', 0)),
                "volume": int(quote_data.get('volume', 0))
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
            
            payload = {
                "userId": os.getenv('BROKER_API_KEY')[:-4],
                "exchange": exchange,
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

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data for given symbol using new Firstock API
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Candle interval in common format:
                     Minutes: 1m, 3m, 5m, 10m, 15m, 30m
                     Hours: 1h, 2h, 4h
                     Days: D
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            
            # Convert dates to datetime objects
            start_dt = datetime.strptime(start_date, '%Y-%m-%d')
            end_dt = datetime.strptime(end_date, '%Y-%m-%d')
            
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
                # Intraday data: use market hours format as shown in API docs
                start_str = f"09:15:00 {start_dt.strftime('%d-%m-%Y')}"
                end_str = f"15:29:00 {end_dt.strftime('%d-%m-%Y')}"
            
            logger.info(f"Getting {interval} data for {br_symbol} from {start_str} to {end_str}")
            
            # Prepare payload according to new API format
            payload = {
                "userId": os.getenv('BROKER_API_KEY')[:-4],
                "jKey": self.auth_token,
                "exchange": exchange,
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
                                # Set to market opening time for daily data (09:15:00 IST)
                                dt = dt.replace(hour=9, minute=15, second=0)
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
