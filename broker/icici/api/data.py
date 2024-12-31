import http.client
import hashlib
import json
from datetime import datetime, timedelta
import os
import pandas as pd
import logging
from database.token_db import get_br_symbol, get_oa_symbol

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BrokerData:
    def __init__(self, auth_token):
        """Initialize ICICI data handler with authentication token"""
        self.auth_token = auth_token
        self.api_key = os.getenv('BROKER_API_KEY')
        self.api_secret = os.getenv('BROKER_API_SECRET')
        
        # Map common timeframe format to ICICI resolutions
        self.timeframe_map = {
            '1m': '1', 
            '5m': '5',
            '15m': '15',
            '30m': '30',
            '1h': '60',
            'D': '1D'
        }

    def _generate_headers(self, payload=''):
        """Generate authentication headers for ICICI API"""
        time_stamp = datetime.utcnow().isoformat()[:19] + '.000Z'
        checksum = hashlib.sha256((time_stamp + payload + self.api_secret).encode("utf-8")).hexdigest()

        return {
            'Content-Type': 'application/json',
            'X-Checksum': 'token ' + checksum,
            'X-Timestamp': time_stamp,
            'X-AppKey': self.api_key,
            'X-SessionToken': self.auth_token
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO)
            For NFO symbols, symbol should contain expiry and option info
        Returns:
            dict: Simplified quote data with required fields
        """
        try:
            # Convert symbol to broker format and extract NFO details
            br_symbol = get_br_symbol(symbol, exchange)
            
            # Prepare request payload
            payload_data = {
                "stock_code": br_symbol,
                "exchange_code": exchange
            }
            
            # Add additional fields for derivatives
            if exchange == "NFO":
                # ICICI expects symbol parts split by :::
                symbol_parts = br_symbol.split(':::')
                if len(symbol_parts) >= 2:
                    payload_data["stock_code"] = symbol_parts[0]
                    payload_data["expiry_date"] = symbol_parts[1]
                    
                    if symbol.endswith("FUT"):
                        payload_data["product_type"] = "futures"
                        payload_data["right"] = "others"
                        payload_data["strike_price"] = "0"
                    elif symbol.endswith("CE") or symbol.endswith("PE"):
                        payload_data["product_type"] = "options"
                        payload_data["right"] = "call" if symbol.endswith("CE") else "put"
                        payload_data["strike_price"] = symbol_parts[2] if len(symbol_parts) > 2 else "0"

            payload = json.dumps(payload_data, separators=(',', ':'))

            # Make API request
            conn = http.client.HTTPSConnection("api.icicidirect.com")
            headers = self._generate_headers(payload)
            
            conn.request("GET", "/breezeapi/api/v1/quotes", payload, headers)
            res = conn.getresponse()
            data = json.loads(res.read().decode("utf-8"))
            
            if data.get('Status') != 200:
                raise Exception(f"Error from ICICI API: {data.get('Error', 'Unknown error')}")
            
            quote = data.get('Success', [{}])[0]
            
            # Helper function to safely convert to float/int
            def safe_float(value, default=0.0):
                try:
                    return float(value) if value is not None else default
                except (ValueError, TypeError):
                    return default
                    
            def safe_int(value, default=0):
                try:
                    return int(value) if value is not None else default
                except (ValueError, TypeError):
                    return default
            
            # Return standardized quote format matching expected output
            return {
                'bid': safe_float(quote.get('best_bid_price')),
                'ask': safe_float(quote.get('best_offer_price')),
                'open': safe_float(quote.get('open')),
                'high': safe_float(quote.get('high')),
                'low': safe_float(quote.get('low')),
                'ltp': safe_float(quote.get('ltp')),
                'prev_close': safe_float(quote.get('previous_close')),
                'volume': safe_int(quote.get('total_quantity_traded'))
            }
            
        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}")

    def get_history(self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        Get historical data using ICICI's v2 historical charts API
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO)
            interval: Candle interval (1m, 5m, 15m, 30m, 1h, D)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            logger.info(f"Getting history for {symbol} ({exchange})")
            logger.info(f"Interval: {interval}, Date Range: {start_date} to {end_date}")
            
            # Map interval to ICICI format
            icici_interval_map = {
                '1m': '1minute',
                '5m': '5minute',
                '15m': '15minute',
                '30m': '30minute',
                'D': '1day'
            }
            
            if interval not in icici_interval_map:
                logger.error(f"Unsupported interval: {interval}")
                raise ValueError(f"Unsupported interval: {interval}")
            icici_interval = icici_interval_map[interval]
            logger.info(f"ICICI interval: {icici_interval}")
            
            # Convert dates to match ICICI format
            def format_start_date(date_str):
                dt = pd.to_datetime(date_str)
                return dt.strftime('%Y-%m-%dT00:00:00.000Z')
                
            def format_end_date(date_str):
                dt = pd.to_datetime(date_str)
                return dt.strftime('%Y-%m-%dT23:59:59.000Z')  # Use 23:59:59 for end date
            
            # Convert symbol to broker format and extract NFO details
            br_symbol = get_br_symbol(symbol, exchange)
            
            # Prepare query parameters
            query_params = {
                'stock_code': br_symbol,
                'exch_code': exchange,
                'interval': icici_interval,
                'from_date': format_start_date(start_date),
                'to_date': format_end_date(end_date)
            }
            
            # Add NFO specific parameters
            if exchange == "NFO":
                # ICICI expects symbol parts split by :::
                symbol_parts = br_symbol.split(':::')
                if len(symbol_parts) >= 2:
                    query_params['stock_code'] = symbol_parts[0]
                    query_params['expiry_date'] = format_start_date(symbol_parts[1])  # Use start date format for expiry
                    
                    if symbol.endswith("FUT"):
                        query_params['product_type'] = "Futures"
                        query_params['right'] = "others"
                        query_params['strike_price'] = "0"
                    elif symbol.endswith("CE") or symbol.endswith("PE"):
                        query_params['product_type'] = "Options"
                        query_params['right'] = "Call" if symbol.endswith("CE") else "Put"
                        query_params['strike_price'] = symbol_parts[2] if len(symbol_parts) > 2 else "0"
            
            # Build query string
            query_string = "&".join([f"{k}={v}" for k, v in query_params.items()])
            logger.info(f"Query string: {query_string}")
            
            # Make API request
            conn = http.client.HTTPSConnection("breezeapi.icicidirect.com")
            headers = {
                'X-SessionToken': self.auth_token,
                'apikey': self.api_key
            }
            logger.info(f"Request headers: {headers}")
            logger.info(f"Making GET request to /api/v2/historicalcharts?{query_string}")
            
            conn.request("GET", f"/api/v2/historicalcharts?{query_string}", None, headers)
            res = conn.getresponse()
            logger.info(f"Response status code: {res.status}")
            logger.info(f"Response headers: {res.getheaders()}")
            
            raw_response = res.read().decode("utf-8")
            logger.info(f"Raw response: {raw_response}")
            
            try:
                data = json.loads(raw_response)
                logger.info(f"Response status: {data.get('Status')}")
                logger.debug(f"Full response: {data}")
                
                if data.get('Status') != 200:
                    error_msg = f"Error from ICICI API: {data.get('Error', 'Unknown error')}"
                    logger.error(error_msg)
                    raise Exception(error_msg)
                
                # Convert response to DataFrame
                candles = data.get('Success', [])
                logger.info(f"Received {len(candles)} candles")
                
                if not candles:
                    logger.warning("No data received from API")
                    return pd.DataFrame()
                
                # Process candles
                processed_candles = []
                for candle in candles:
                    # Convert IST timestamp to GMT
                    ist_dt = pd.to_datetime(candle['datetime'])
                    gmt_dt = ist_dt - pd.Timedelta(hours=5, minutes=30)  # Subtract IST offset
                    
                    processed_candles.append({
                        'timestamp': int(gmt_dt.timestamp()),
                        'open': float(candle['open']),
                        'high': float(candle['high']),
                        'low': float(candle['low']),
                        'close': float(candle['close']),
                        'volume': int(candle['volume'])
                    })
                
                df = pd.DataFrame(processed_candles)
                logger.info(f"Final DataFrame shape: {df.shape}")
                return df
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to decode JSON response: {e}")
                logger.error(f"Raw response was: {raw_response}")
                raise Exception(f"Invalid response from ICICI API: {raw_response}")
            
        except Exception as e:
            logger.error(f"Error in get_history: {str(e)}", exc_info=True)
            raise Exception(f"Error fetching historical data: {str(e)}")

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol using quotes endpoint since ICICI doesn't provide full depth
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data in standardized format
        """
        try:
            # Convert symbol to broker format and extract NFO details
            br_symbol = get_br_symbol(symbol, exchange)
            
            # Prepare request payload
            payload_data = {
                "stock_code": br_symbol,
                "exchange_code": exchange
            }
            
            # Add additional fields for derivatives
            if exchange == "NFO":
                symbol_parts = br_symbol.split(':::')
                if len(symbol_parts) >= 2:
                    payload_data["stock_code"] = symbol_parts[0]
                    payload_data["expiry_date"] = symbol_parts[1]
                    
                    if symbol.endswith("FUT"):
                        payload_data["product_type"] = "futures"
                        payload_data["right"] = "others"
                        payload_data["strike_price"] = "0"
                    elif symbol.endswith("CE") or symbol.endswith("PE"):
                        payload_data["product_type"] = "options"
                        payload_data["right"] = "call" if symbol.endswith("CE") else "put"
                        payload_data["strike_price"] = symbol_parts[2] if len(symbol_parts) > 2 else "0"

            payload = json.dumps(payload_data, separators=(',', ':'))

            # Make API request
            conn = http.client.HTTPSConnection("api.icicidirect.com")
            headers = self._generate_headers(payload)
            
            conn.request("GET", "/breezeapi/api/v1/quotes", payload, headers)
            res = conn.getresponse()
            data = json.loads(res.read().decode("utf-8"))
            
            if data.get('Status') != 200:
                raise Exception(f"Error from ICICI API: {data.get('Error', 'Unknown error')}")
            
            quote = data.get('Success', [{}])[0]
            
            def safe_float(value, default=0.0):
                try:
                    return float(value) if value is not None else default
                except (ValueError, TypeError):
                    return default
                    
            def safe_int(value, default=0):
                try:
                    return int(value) if value is not None else default
                except (ValueError, TypeError):
                    return default

            # Create empty depth arrays with 5 levels
            empty_levels = [{"price": 0, "quantity": 0} for _ in range(5)]
            
            # Get the first level from quotes, rest will be empty
            bids = empty_levels.copy()
            asks = empty_levels.copy()
            
            # Fill first level if available
            if quote.get('best_bid_price'):
                bids[0] = {
                    "price": safe_float(quote.get('best_bid_price')),
                    "quantity": safe_int(quote.get('best_bid_quantity'))
                }
            
            if quote.get('best_offer_price'):
                asks[0] = {
                    "price": safe_float(quote.get('best_offer_price')),
                    "quantity": safe_int(quote.get('best_offer_quantity'))
                }

            # Return standardized depth format
            return {
                "bids": bids,
                "asks": asks,
                "high": safe_float(quote.get('high')),
                "low": safe_float(quote.get('low')),
                "ltp": safe_float(quote.get('ltp')),
                "ltq": safe_int(quote.get('best_bid_quantity')),  # Using best bid quantity as LTQ
                "oi": 0,  # ICICI doesn't provide OI in quotes
                "open": safe_float(quote.get('open')),
                "prev_close": safe_float(quote.get('previous_close')),
                "totalbuyqty": 0,  # ICICI doesn't provide total buy quantity
                "totalsellqty": 0,  # ICICI doesn't provide total sell quantity
                "volume": safe_int(quote.get('total_quantity_traded'))
            }
            
        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")
