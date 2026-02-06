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
        """Initialize Nubra data handler with authentication token"""
        self.auth_token = auth_token
        # Map OpenAlgo timeframe format to Nubra intervals
        # Nubra supports: 1s, 1m, 2m, 3m, 5m, 15m, 30m, 1h, 1d, 1w, 1mt
        self.timeframe_map = {
            # Seconds
            "1s": "1s",
            # Minutes
            "1m": "1m",
            "2m": "2m",
            "3m": "3m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            # Hours
            "1h": "1h",
            # Daily
            "D": "1d",
            # Weekly
            "W": "1w",
            # Monthly
            "M": "1mt",
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
        Get historical data for given symbol using Nubra's timeseries API.
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX)
            interval: Candle interval (1m, 3m, 5m, 15m, 30m, 1h, D)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [close, high, low, open, timestamp, volume, oi]
        """
        try:
            # Convert symbol to broker format
            br_symbol = get_br_symbol(symbol, exchange)
            logger.debug(f"Debug - Broker Symbol: {br_symbol}")

            # Check for unsupported timeframes
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(
                    f"Timeframe '{interval}' is not supported by Nubra. Supported timeframes are: {', '.join(supported)}"
                )

            # Determine instrument type based on exchange
            original_exchange = exchange
            if exchange == "NSE_INDEX":
                instrument_type = "INDEX"
                api_exchange = "NSE"
            elif exchange == "BSE_INDEX":
                instrument_type = "INDEX"
                api_exchange = "BSE"
            elif exchange == "MCX_INDEX":
                instrument_type = "INDEX"
                api_exchange = "MCX"
            elif exchange in ["NFO", "BFO"]:
                # Determine if it's futures or options based on symbol pattern
                if "CE" in symbol or "PE" in symbol:
                    instrument_type = "OPT"
                else:
                    instrument_type = "FUT"
                api_exchange = exchange
            elif exchange in ["CDS", "BCD"]:
                instrument_type = "FUT"  # Currency derivatives
                api_exchange = exchange
            elif exchange == "MCX":
                instrument_type = "FUT"  # Commodity futures
                api_exchange = exchange
            else:
                instrument_type = "STOCK"
                api_exchange = exchange

            # Convert dates to ISO format for Nubra API
            from_date = pd.to_datetime(start_date)
            to_date = pd.to_datetime(end_date)

            # Set start time to market open (09:15 IST -> 03:45 UTC)
            from_date = from_date.replace(hour=3, minute=45, second=0, microsecond=0)
            
            # If end_date is today, set end time to current time
            current_time = pd.Timestamp.now()
            if to_date.date() == current_time.date():
                # Convert current IST to approximate UTC
                to_date = current_time - pd.Timedelta(hours=5, minutes=30)
            else:
                # For past dates, set end time to market close (15:30 IST -> 10:00 UTC)
                to_date = to_date.replace(hour=10, minute=0, second=0, microsecond=0)

            # Format dates as ISO strings with milliseconds
            start_iso = from_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
            end_iso = to_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")

            # Build Nubra timeseries request payload
            payload = {
                "query": [
                    {
                        "exchange": api_exchange,
                        "type": instrument_type,
                        "values": [br_symbol],
                        "fields": ["open", "high", "low", "close", "tick_volume"],
                        "startDate": start_iso,
                        "endDate": end_iso,
                        "interval": self.timeframe_map[interval],
                        "intraDay": False,
                        "realTime": False
                    }
                ]
            }

            logger.debug(f"Debug - Nubra timeseries request: {payload}")

            # Make API call to Nubra's timeseries endpoint
            response = get_api_response(
                "/charts/timeseries",
                self.auth_token,
                "POST",
                payload,
            )

            logger.debug(f"Debug - Nubra timeseries response: {response}")

            # Parse response
            if not response or response.get("message") != "charts":
                error_msg = response.get("message", "Unknown error") if response else "Empty response"
                raise Exception(f"Error from Nubra API: {error_msg}")

            # Extract result data
            result = response.get("result", [])
            if not result:
                logger.debug("Debug - No data in result array")
                return pd.DataFrame(columns=["close", "high", "low", "open", "timestamp", "volume", "oi"])

            # Get values array from first result
            values_array = result[0].get("values", [])
            if not values_array:
                logger.debug("Debug - No values in result")
                return pd.DataFrame(columns=["close", "high", "low", "open", "timestamp", "volume", "oi"])

            # Find the symbol data in values array
            symbol_data = None
            for val in values_array:
                if br_symbol in val:
                    symbol_data = val[br_symbol]
                    break

            if not symbol_data:
                logger.debug(f"Debug - Symbol {br_symbol} not found in response")
                return pd.DataFrame(columns=["close", "high", "low", "open", "timestamp", "volume", "oi"])

            # Extract OHLCV arrays
            # Nubra format: {"open": [{"ts": nanoseconds, "v": value_in_paise}, ...], ...}
            open_data = symbol_data.get("open", [])
            high_data = symbol_data.get("high", [])
            low_data = symbol_data.get("low", [])
            close_data = symbol_data.get("close", [])
            volume_data = symbol_data.get("tick_volume", []) or symbol_data.get("cumulative_volume", [])

            if not close_data:
                logger.debug("Debug - No candle data received")
                return pd.DataFrame(columns=["close", "high", "low", "open", "timestamp", "volume", "oi"])

            # Build a dictionary keyed by timestamp to align all fields
            candle_dict = {}
            
            # Process each field
            for item in open_data:
                ts = item.get("ts", 0)
                if ts not in candle_dict:
                    candle_dict[ts] = {"timestamp": ts, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}
                # Convert from paise to rupees
                candle_dict[ts]["open"] = float(item.get("v", 0)) / 100

            for item in high_data:
                ts = item.get("ts", 0)
                if ts not in candle_dict:
                    candle_dict[ts] = {"timestamp": ts, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}
                candle_dict[ts]["high"] = float(item.get("v", 0)) / 100

            for item in low_data:
                ts = item.get("ts", 0)
                if ts not in candle_dict:
                    candle_dict[ts] = {"timestamp": ts, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}
                candle_dict[ts]["low"] = float(item.get("v", 0)) / 100

            for item in close_data:
                ts = item.get("ts", 0)
                if ts not in candle_dict:
                    candle_dict[ts] = {"timestamp": ts, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}
                candle_dict[ts]["close"] = float(item.get("v", 0)) / 100

            for item in volume_data:
                ts = item.get("ts", 0)
                if ts in candle_dict:
                    candle_dict[ts]["volume"] = int(item.get("v", 0))

            # Convert dictionary to list and sort by timestamp
            candles = list(candle_dict.values())
            candles.sort(key=lambda x: x["timestamp"])

            # Create DataFrame
            df = pd.DataFrame(candles)

            if df.empty:
                return pd.DataFrame(columns=["close", "high", "low", "open", "timestamp", "volume", "oi"])

            # Convert nanosecond timestamp to datetime
            # Nubra timestamps are in nanoseconds
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ns")

            # For daily/weekly/monthly intervals, normalize to midnight (start of day)
            if interval in ["D", "W", "M"]:
                df["timestamp"] = df["timestamp"].dt.normalize()

            # Convert to Unix epoch (seconds)
            df["timestamp"] = df["timestamp"].astype("int64") // 10**9

            # Add OI column (Nubra doesn't provide OI in timeseries API)
            df["oi"] = 0

            # Ensure proper column types
            numeric_columns = ["open", "high", "low", "close", "volume"]
            df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric)
            df["oi"] = df["oi"].astype(int)

            # Sort by timestamp and remove duplicates
            df = (
                df.sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"])
                .reset_index(drop=True)
            )

            # Reorder columns to match OpenAlgo REST API format
            df = df[["close", "high", "low", "open", "timestamp", "volume", "oi"]]

            logger.info(f"Debug - Received {len(df)} candles for {symbol}")
            return df

        except Exception as e:
            logger.error(f"Debug - Error: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")

    def get_oi_history(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        Get historical OI data for given symbol.
        
        Note: Nubra's API does not provide a separate OI data endpoint.
        This method returns an empty DataFrame to maintain API compatibility.
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NFO, BFO, CDS, MCX)
            interval: Candle interval
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Empty DataFrame with columns [timestamp, oi]
        """
        logger.info(f"OI history not available from Nubra API for {symbol}")
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

    def get_intervals(self) -> list:
        """
        Get list of supported intervals for historical data.
        
        Based on Nubra API: 1s, 1m, 2m, 3m, 5m, 15m, 30m, 1h, 1d, 1w
        OpenAlgo supported: 1m, 3m, 5m, 15m, 30m, 1h, D
        
        Returns:
            list: List of supported interval strings
        """
        return list(self.timeframe_map.keys())


