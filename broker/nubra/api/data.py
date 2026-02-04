import json
import os
import time
import urllib.parse
from datetime import datetime, timedelta

import httpx
import pandas as pd

from database.token_db import get_br_symbol, get_oa_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="GET", payload=""):
    """Helper function to make API calls to Nubra"""
    AUTH_TOKEN = auth
    device_id = "OPENALGO"  # Fixed device ID

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-device-id": device_id,
    }

    if isinstance(payload, dict):
        payload = json.dumps(payload)

    # Nubra base URL
    url = f"https://api.nubra.io{endpoint}"

    try:
        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, headers=headers, content=payload)
        else:
            response = client.request(method, url, headers=headers, content=payload)

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        if response.status_code == 403:
            logger.debug(f"Debug - API returned 403 Forbidden. Headers: {headers}")
            logger.debug(f"Debug - Response text: {response.text}")
            raise Exception("Authentication failed. Please check your auth token.")

        return json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Debug - Failed to parse response. Status code: {response.status_code}")
        logger.debug(f"Debug - Response text: {response.text}")
        raise Exception(f"Failed to parse API response (status {response.status_code})")


class BrokerData:
    def __init__(self, auth_token):
        """Initialize Angel data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Angel resolutions
        self.timeframe_map = {
            # Minutes
            "1m": "ONE_MINUTE",
            "3m": "THREE_MINUTE",
            "5m": "FIVE_MINUTE",
            "10m": "TEN_MINUTE",
            "15m": "FIFTEEN_MINUTE",
            "30m": "THIRTY_MINUTE",
            # Hours
            "1h": "ONE_HOUR",
            # Daily
            "D": "ONE_DAY",
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol using Nubra's orderbooks API.
        
        Nubra API: GET /orderbooks/{ref_id}?levels=1
        
        Note: Nubra's orderbook API requires numeric ref_id. Index symbols 
        don't have ref_id in Nubra's API, so quotes are not available for indices.
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX)
        Returns:
            dict: Quote data with required fields
        """
        try:
            # Check if this is an index - Nubra orderbook API doesn't support indices
            # Return zeros gracefully instead of throwing an error
            if exchange.endswith('_INDEX'):
                logger.info(f"Index quotes not available from Nubra for {symbol} on {exchange}")
                return {
                    "bid": 0,
                    "ask": 0,
                    "open": 0,
                    "high": 0,
                    "low": 0,
                    "ltp": 0,
                    "prev_close": 0,
                    "volume": 0,
                    "oi": 0,
                }

            # Get token (ref_id) for the symbol
            token = get_token(symbol, exchange)
            
            if not token:
                raise Exception(f"Could not find token for symbol {symbol} on {exchange}")

            # Verify token is numeric (ref_id) - indices have text tokens which won't work
            if not str(token).isdigit():
                raise Exception(f"Invalid token '{token}' for {symbol}. Nubra orderbook API requires numeric ref_id.")

            logger.info(f"Fetching quotes for {symbol} on {exchange} with token {token}")

            # Call Nubra's orderbooks API with 1 level of depth for quotes
            response = get_api_response(
                f"/orderbooks/{token}?levels=1", self.auth_token, "GET"
            )
            
            logger.debug(f"Nubra orderbooks response: {response}")

            # Extract orderBook data from response
            orderbook = response.get("orderBook", {})
            
            # Check if we got valid data
            if not orderbook:
                logger.warning(f"Empty orderbook response for {symbol} on {exchange}")
                raise Exception("No quote data received")

            # Parse bid/ask from arrays
            # Nubra format: {"p": price, "q": quantity, "o": num_orders}
            # Prices are in paise, need to convert to rupees (divide by 100)
            bids = orderbook.get("bid", [])
            asks = orderbook.get("ask", [])
            
            # For some instruments, bid/ask might be empty - that's ok, we still have LTP
            bid_price = float(bids[0].get("p", 0)) / 100 if bids else 0
            ask_price = float(asks[0].get("p", 0)) / 100 if asks else 0
            ltp = float(orderbook.get("ltp", 0)) / 100

            # Return quote in OpenAlgo format
            # Note: Nubra doesn't provide open/high/low/close/oi in orderbook API
            return {
                "bid": bid_price,
                "ask": ask_price,
                "open": 0,  # Not available in Nubra orderbook API
                "high": 0,  # Not available in Nubra orderbook API
                "low": 0,   # Not available in Nubra orderbook API
                "ltp": ltp,
                "prev_close": 0,  # Not available in Nubra orderbook API
                "volume": int(orderbook.get("volume", 0)),
                "oi": 0,  # Not available in Nubra orderbook API
            }

        except Exception as e:
            logger.error(f"Error fetching quotes for {symbol} on {exchange}: {str(e)}")
            raise Exception(f"Error fetching quotes: {str(e)}")

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols by making concurrent requests.
        Nubra does not have a batch quote API, so we fetch individually in parallel.
        
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            import concurrent.futures
            
            # Limit concurrency to avoid hitting rate limits too hard
            # Nubra Limit: ~10 requests/sec for standard users
            MAX_WORKERS = 5
            
            results = []
            
            def fetch_single_quote(item):
                symbol = item["symbol"]
                exchange = item["exchange"]
                try:
                    quote_data = self.get_quotes(symbol, exchange)
                    return {
                        "symbol": symbol,
                        "exchange": exchange,
                        "data": quote_data
                    }
                except Exception as e:
                    logger.warning(f"Failed to fetch quote for {symbol}: {e}")
                    return {
                        "symbol": symbol,
                        "exchange": exchange,
                        "error": str(e)
                    }

            # Use ThreadPoolExecutor for concurrent requests
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                # Submit all tasks
                future_to_symbol = {executor.submit(fetch_single_quote, item): item for item in symbols}
                
                # Collect results as they complete
                for future in concurrent.futures.as_completed(future_to_symbol):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        logger.error(f"Generate quote exception: {e}")
            
            return results

        except Exception as e:
            logger.exception("Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _process_quotes_batch(self, symbols: list) -> list:
        """
        Deprecated: This was an Angel-specific batch method.
        Redirecting to get_multiquotes for compatibility.
        """
        return self.get_multiquotes(symbols)

    def get_history(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
            interval: Candle interval (1m, 3m, 5m, 10m, 15m, 30m, 1h, D)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            include_oi: Include open interest data (only for F&O contracts)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume, oi (if requested)]
        """
        try:
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)

            token = get_token(symbol, exchange)
            logger.debug(f"Debug - Broker Symbol: {br_symbol}, Token: {token}")

            if exchange == "NSE_INDEX":
                exchange = "NSE"
            elif exchange == "BSE_INDEX":
                exchange = "BSE"
            elif exchange == "MCX_INDEX":
                exchange = "MCX"

            # Check for unsupported timeframes
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(
                    f"Timeframe '{interval}' is not supported by Angel. Supported timeframes are: {', '.join(supported)}"
                )

            # Convert dates to datetime objects
            from_date = pd.to_datetime(start_date)
            to_date = pd.to_datetime(end_date)

            # Set start time to 00:00 for the start date
            from_date = from_date.replace(hour=0, minute=0)

            # If end_date is today, set the end time to current time
            current_time = pd.Timestamp.now()
            if to_date.date() == current_time.date():
                to_date = current_time.replace(
                    second=0, microsecond=0
                )  # Remove seconds and microseconds
            else:
                # For past dates, set end time to 23:59
                to_date = to_date.replace(hour=23, minute=59)

            # Initialize empty list to store DataFrames
            dfs = []

            # Set chunk size based on interval as per Angel API documentation
            interval_limits = {
                "1m": 30,  # ONE_MINUTE
                "3m": 60,  # THREE_MINUTE
                "5m": 100,  # FIVE_MINUTE
                "10m": 100,  # TEN_MINUTE
                "15m": 200,  # FIFTEEN_MINUTE
                "30m": 200,  # THIRTY_MINUTE
                "1h": 400,  # ONE_HOUR
                "D": 2000,  # ONE_DAY
            }

            chunk_days = interval_limits.get(interval)
            if not chunk_days:
                supported = list(interval_limits.keys())
                raise Exception(
                    f"Interval '{interval}' not supported. Supported intervals: {', '.join(supported)}"
                )

            # Process data in chunks
            current_start = from_date
            while current_start <= to_date:
                # Calculate chunk end date
                current_end = min(current_start + timedelta(days=chunk_days - 1), to_date)

                # Prepare payload for historical data API
                payload = {
                    "exchange": exchange,
                    "symboltoken": token,
                    "interval": self.timeframe_map[interval],
                    "fromdate": current_start.strftime("%Y-%m-%d %H:%M"),
                    "todate": current_end.strftime("%Y-%m-%d %H:%M"),
                }
                logger.debug(f"Debug - Fetching chunk from {current_start} to {current_end}")
                logger.debug(f"Debug - API Payload: {payload}")

                try:
                    response = get_api_response(
                        "/rest/secure/angelbroking/historical/v1/getCandleData",
                        self.auth_token,
                        "POST",
                        payload,
                    )
                    logger.info(f"Debug - API Response Status: {response.get('status')}")

                    # Check if response is empty or invalid
                    if not response:
                        logger.debug(
                            f"Debug - Empty response for chunk {current_start} to {current_end}"
                        )
                        current_start = current_end + timedelta(days=1)
                        continue

                    if not response.get("status"):
                        logger.info(
                            f"Debug - Error response: {response.get('message', 'Unknown error')}"
                        )
                        current_start = current_end + timedelta(days=1)
                        continue

                except Exception as chunk_error:
                    logger.error(
                        f"Debug - Error fetching chunk {current_start} to {current_end}: {str(chunk_error)}"
                    )
                    current_start = current_end + timedelta(days=1)
                    continue

                if not response.get("status"):
                    raise Exception(
                        f"Error from Angel API: {response.get('message', 'Unknown error')}"
                    )

                # Extract candle data and create DataFrame
                data = response.get("data", [])
                if data:
                    chunk_df = pd.DataFrame(
                        data, columns=["timestamp", "open", "high", "low", "close", "volume"]
                    )
                    dfs.append(chunk_df)
                    logger.debug(f"Debug - Received {len(data)} candles for chunk")
                else:
                    logger.debug("Debug - No data received for chunk")

                # Move to next chunk
                current_start = current_end + timedelta(days=1)

                # Rate limit delay between chunks (0.5 seconds)
                if current_start <= to_date:
                    time.sleep(0.5)

            # If no data was found, return empty DataFrame
            if not dfs:
                logger.debug("Debug - No data received from API")
                return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

            # Combine all chunks
            df = pd.concat(dfs, ignore_index=True)

            # Convert timestamp to datetime
            df["timestamp"] = pd.to_datetime(df["timestamp"])

            # For daily timeframe, convert UTC to IST by adding 5 hours and 30 minutes
            if interval == "D":
                df["timestamp"] = df["timestamp"] + pd.Timedelta(hours=5, minutes=30)

            # Convert timestamp to Unix epoch
            df["timestamp"] = df["timestamp"].astype("int64") // 10**9  # Convert to Unix epoch

            # Ensure numeric columns and proper order
            numeric_columns = ["open", "high", "low", "close", "volume"]
            df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric)

            # Sort by timestamp and remove duplicates
            df = (
                df.sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"])
                .reset_index(drop=True)
            )

            # Always fetch OI data for F&O contracts
            if exchange in ["NFO", "BFO", "CDS", "MCX"]:
                try:
                    oi_df = self.get_oi_history(symbol, exchange, interval, start_date, end_date)
                    if not oi_df.empty:
                        # Merge OI data with candle data
                        df = pd.merge(df, oi_df, on="timestamp", how="left")
                        # Fill any missing OI values with 0
                        df["oi"] = df["oi"].fillna(0).astype(int)
                    else:
                        # Add empty OI column if no data available
                        df["oi"] = 0
                except Exception as oi_error:
                    logger.error(f"Debug - Error fetching OI data: {str(oi_error)}")
                    # Add empty OI column on error
                    df["oi"] = 0

            # Reorder columns to match REST API format
            if "oi" in df.columns:
                df = df[["close", "high", "low", "open", "timestamp", "volume", "oi"]]
            else:
                # Add OI column with zeros if not present
                df["oi"] = 0
                df = df[["close", "high", "low", "open", "timestamp", "volume", "oi"]]

            return df

        except Exception as e:
            logger.error(f"Debug - Error: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")

    def get_oi_history(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        Get historical OI data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NFO, BFO, CDS, MCX)
            interval: Candle interval (1m, 3m, 5m, 10m, 15m, 30m, 1h, D)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical OI data with columns [timestamp, oi]
        """
        try:
            # Get token for the symbol
            token = get_token(symbol, exchange)

            # Convert dates to datetime objects
            from_date = pd.to_datetime(start_date)
            to_date = pd.to_datetime(end_date)

            # Set start time to 00:00 for the start date
            from_date = from_date.replace(hour=0, minute=0)

            # If end_date is today, set the end time to current time
            current_time = pd.Timestamp.now()
            if to_date.date() == current_time.date():
                to_date = current_time.replace(second=0, microsecond=0)
            else:
                # For past dates, set end time to 23:59
                to_date = to_date.replace(hour=23, minute=59)

            # Initialize empty list to store DataFrames
            dfs = []

            # Set chunk size based on interval (same as candle data)
            interval_limits = {
                "1m": 30,  # ONE_MINUTE
                "3m": 60,  # THREE_MINUTE
                "5m": 100,  # FIVE_MINUTE
                "10m": 100,  # TEN_MINUTE
                "15m": 200,  # FIFTEEN_MINUTE
                "30m": 200,  # THIRTY_MINUTE
                "1h": 400,  # ONE_HOUR
                "D": 2000,  # ONE_DAY
            }

            chunk_days = interval_limits.get(interval)
            if not chunk_days:
                raise Exception(f"Interval '{interval}' not supported for OI data")

            # Process data in chunks
            current_start = from_date
            while current_start <= to_date:
                # Calculate chunk end date
                current_end = min(current_start + timedelta(days=chunk_days - 1), to_date)

                # Prepare payload for OI data API
                payload = {
                    "exchange": exchange,
                    "symboltoken": token,
                    "interval": self.timeframe_map[interval],
                    "fromdate": current_start.strftime("%Y-%m-%d %H:%M"),
                    "todate": current_end.strftime("%Y-%m-%d %H:%M"),
                }

                try:
                    response = get_api_response(
                        "/rest/secure/angelbroking/historical/v1/getOIData",
                        self.auth_token,
                        "POST",
                        payload,
                    )

                    if not response or not response.get("status"):
                        logger.debug(
                            f"Debug - No OI data for chunk {current_start} to {current_end}"
                        )
                        current_start = current_end + timedelta(days=1)
                        continue

                except Exception as chunk_error:
                    logger.error(f"Debug - Error fetching OI chunk: {str(chunk_error)}")
                    current_start = current_end + timedelta(days=1)
                    continue

                # Extract OI data and create DataFrame
                data = response.get("data", [])
                if data:
                    chunk_df = pd.DataFrame(data)
                    # Rename 'time' to 'timestamp' for consistency
                    chunk_df.rename(columns={"time": "timestamp"}, inplace=True)
                    dfs.append(chunk_df)

                # Move to next chunk
                current_start = current_end + timedelta(days=1)

                # Rate limit delay between chunks (0.5 seconds)
                if current_start <= to_date:
                    time.sleep(0.5)

            # If no data was found, return empty DataFrame
            if not dfs:
                return pd.DataFrame(columns=["timestamp", "oi"])

            # Combine all chunks
            df = pd.concat(dfs, ignore_index=True)

            # Convert timestamp to datetime
            df["timestamp"] = pd.to_datetime(df["timestamp"])

            # For daily timeframe, convert UTC to IST by adding 5 hours and 30 minutes
            if interval == "D":
                df["timestamp"] = df["timestamp"] + pd.Timedelta(hours=5, minutes=30)

            # Convert timestamp to Unix epoch
            df["timestamp"] = df["timestamp"].astype("int64") // 10**9

            # Ensure oi column is numeric
            df["oi"] = pd.to_numeric(df["oi"])

            # Sort by timestamp and remove duplicates
            df = (
                df.sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"])
                .reset_index(drop=True)
            )

            return df

        except Exception as e:
            logger.error(f"Debug - Error fetching OI data: {str(e)}")
            # Return empty DataFrame on error
            return pd.DataFrame(columns=["timestamp", "oi"])

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol using Nubra's orderbooks API.
        
        Nubra API: GET /orderbooks/{ref_id}?levels=5
        
        Note: Nubra's orderbook API requires numeric ref_id. Index symbols 
        don't have ref_id in Nubra's API, so depth is not available for indices.
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX)
        Returns:
            dict: Market depth data with bids, asks and other details
        """
        try:
            # Check if this is an index - Nubra orderbook API doesn't support indices
            # Return zeros gracefully instead of throwing an error
            if exchange.endswith('_INDEX'):
                logger.info(f"Index depth not available from Nubra for {symbol} on {exchange}")
                return {
                    "bids": [{"price": 0, "quantity": 0} for _ in range(5)],
                    "asks": [{"price": 0, "quantity": 0} for _ in range(5)],
                    "high": 0,
                    "low": 0,
                    "ltp": 0,
                    "ltq": 0,
                    "open": 0,
                    "prev_close": 0,
                    "volume": 0,
                    "oi": 0,
                    "totalbuyqty": 0,
                    "totalsellqty": 0,
                }

            # Get token (ref_id) for the symbol
            token = get_token(symbol, exchange)
            
            if not token:
                raise Exception(f"Could not find token for symbol {symbol} on {exchange}")

            # Verify token is numeric (ref_id) - indices have text tokens which won't work
            if not str(token).isdigit():
                raise Exception(f"Invalid token '{token}' for {symbol}. Nubra orderbook API requires numeric ref_id.")

            logger.info(f"Fetching depth for {symbol} on {exchange} with token {token}")

            # Call Nubra's orderbooks API with 5 levels of depth
            response = get_api_response(
                f"/orderbooks/{token}?levels=5", self.auth_token, "GET"
            )

            # Extract orderBook data from response
            orderbook = response.get("orderBook", {})
            if not orderbook:
                raise Exception("No depth data received")

            # Parse bid/ask from arrays
            # Nubra format: {"p": price in paise, "q": quantity, "o": num_orders}
            bid_orders = orderbook.get("bid", [])
            ask_orders = orderbook.get("ask", [])
            
            # Format bids and asks with exactly 5 entries each
            # Convert price from paise to rupees (divide by 100)
            bids = []
            asks = []

            # Process buy orders (top 5)
            for i in range(5):  # Ensure exactly 5 entries
                if i < len(bid_orders):
                    bid = bid_orders[i]
                    bids.append({
                        "price": float(bid.get("p", 0)) / 100,
                        "quantity": int(bid.get("q", 0))
                    })
                else:
                    bids.append({"price": 0, "quantity": 0})

            # Process sell orders (top 5)
            for i in range(5):  # Ensure exactly 5 entries
                if i < len(ask_orders):
                    ask = ask_orders[i]
                    asks.append({
                        "price": float(ask.get("p", 0)) / 100,
                        "quantity": int(ask.get("q", 0))
                    })
                else:
                    asks.append({"price": 0, "quantity": 0})

            # Calculate total buy and sell quantities
            totalbuyqty = sum(bid.get("q", 0) for bid in bid_orders)
            totalsellqty = sum(ask.get("q", 0) for ask in ask_orders)
            
            # LTP and other values - convert from paise to rupees
            ltp = float(orderbook.get("ltp", 0)) / 100
            ltq = int(orderbook.get("ltq", 0))
            volume = int(orderbook.get("volume", 0))

            # Return depth data in OpenAlgo format
            # Note: Nubra orderbook API doesn't provide open/high/low/close/oi
            return {
                "bids": bids,
                "asks": asks,
                "high": 0,  # Not available in Nubra orderbook API
                "low": 0,   # Not available in Nubra orderbook API
                "ltp": ltp,
                "ltq": ltq,
                "open": 0,  # Not available in Nubra orderbook API
                "prev_close": 0,  # Not available in Nubra orderbook API
                "volume": volume,
                "oi": 0,  # Not available in Nubra orderbook API
                "totalbuyqty": totalbuyqty,
                "totalsellqty": totalsellqty,
            }

        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")

