import json
import os
import time
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
import pandas as pd
import pytz

from broker.fivepaisa.mapping.transform_data import map_exchange, map_exchange_type
from database.token_db import get_br_symbol, get_oa_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


# Retrieve the BROKER_API_KEY environment variable
broker_api_key = os.getenv("BROKER_API_KEY")
api_key, user_id, client_id = broker_api_key.split(":::")


def normalize_exchange_for_query(symbol: str, exchange: str) -> str:
    """
    Normalize exchange for symbol lookup in database.
    Indices need to use NSE_INDEX or BSE_INDEX instead of NSE/BSE.

    Args:
        symbol: Trading symbol
        exchange: Exchange (NSE, BSE, etc.)

    Returns:
        str: Normalized exchange for database query
    """
    # Common index symbols
    index_symbols = [
        "NIFTY",
        "BANKNIFTY",
        "FINNIFTY",
        "MIDCPNIFTY",
        "NIFTYNXT50",
        "SENSEX",
        "BANKEX",
        "SENSEX50",
        "INDIAVIX",
    ]

    # Match only on an EXACT symbol name. A substring test ("NIFTY" in symbol)
    # is too broad: it wrongly remaps tradeable cash instruments such as
    # NIFTYBEES / JUNIORBEES to *_INDEX, so their (non-index) token is never
    # found and history comes back empty. Real index spot names are enumerated
    # above, so exact membership is both sufficient and safe.
    if symbol.upper() in index_symbols:
        if exchange == "NSE":
            return "NSE_INDEX"
        elif exchange == "BSE":
            return "BSE_INDEX"

    return exchange


# Base URL for 5Paisa API
BASE_URL = "https://Openapi.5paisa.com"


def get_api_response(endpoint: str, auth: str, method: str = "GET", payload: str = "") -> dict:
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

        headers = {"Authorization": f"bearer {auth}", "Content-Type": "application/json"}

        # Make request based on method
        if method.upper() == "GET":
            response = client.get(f"{BASE_URL}{endpoint}", headers=headers)
        else:  # POST
            response = client.post(
                f"{BASE_URL}{endpoint}",
                content=payload,  # Use content since payload is already JSON string
                headers=headers,
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
            "1m": "1",
            "3m": "3",
            "5m": "5",
            "10m": "10",
            "15m": "15",
            "30m": "30",
            # Hours
            "1h": "60",
            # Daily (support all variants)
            "D": "1D",
            "d": "1D",
            "1d": "1D",
        }

    def get_market_depth(self, symbol: str, exchange: str) -> dict[str, float] | None:
        """
        Get market depth for a given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data
        """
        try:
            # Normalize exchange for index symbols
            normalized_exchange = normalize_exchange_for_query(symbol, exchange)

            # Get token from symbol
            token = get_token(symbol, normalized_exchange)
            br_symbol = get_br_symbol(symbol, normalized_exchange)

            # Prepare request payload
            json_data = {
                "head": {"key": api_key},
                "body": {
                    "ClientCode": client_id,
                    "Exchange": map_exchange(exchange),
                    "ExchangeType": map_exchange_type(normalized_exchange),
                    "ScripCode": token,
                    "ScripData": br_symbol if token == "0" else "",
                },
            }

            # Get the shared httpx client
            client = get_httpx_client()

            # Make API request
            headers = {
                "Authorization": f"bearer {self.auth_token}",
                "Content-Type": "application/json",
            }
            response = client.post(
                f"{BASE_URL}/VendorsAPI/Service1.svc/V2/MarketDepth",
                json=json_data,
                headers=headers,
            )
            response.raise_for_status()
            response = response.json()

            if response["head"]["statusDescription"] != "Success":
                logger.debug(f"Market Depth Error: {response['head']['statusDescription']}")
                return None

            depth_data = response["body"]
            if not depth_data or "MarketDepthData" not in depth_data:
                logger.info("No depth data in response")
                return None

            # Get best bid and ask
            bid = ask = 0
            market_depth = depth_data["MarketDepthData"]

            # BbBuySellFlag: 66 for Buy, 83 for Sell
            buy_orders = [order for order in market_depth if order["BbBuySellFlag"] == 66]
            sell_orders = [order for order in market_depth if order["BbBuySellFlag"] == 83]

            if buy_orders:
                # Get highest buy price
                bid = max(float(order["Price"]) for order in buy_orders)
            if sell_orders:
                # Get lowest sell price
                ask = min(float(order["Price"]) for order in sell_orders)

            logger.debug(f"Extracted Bid: {bid}, Ask: {ask}")
            return {"bid": bid, "ask": ask}

        except Exception as e:
            logger.exception(f"Error fetching market depth: {e}")
            logger.info(f"Exception type: {type(e)}")
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
            # Normalize exchange for index symbols
            normalized_exchange = normalize_exchange_for_query(symbol, exchange)

            # Get token from symbol
            token = get_token(symbol, normalized_exchange)
            br_symbol = get_br_symbol(symbol, normalized_exchange)

            # Get market snapshot for overall data
            snapshot_data = {
                "head": {"key": api_key},
                "body": {
                    "ClientCode": client_id,
                    "Data": [
                        {
                            "Exchange": map_exchange(exchange),
                            "ExchangeType": map_exchange_type(normalized_exchange),
                            "ScripCode": token,
                            "ScripData": br_symbol if token == "0" else "",
                        }
                    ],
                },
            }

            # Get the shared httpx client
            client = get_httpx_client()

            # Make API request
            headers = {
                "Authorization": f"bearer {self.auth_token}",
                "Content-Type": "application/json",
            }
            snapshot_response = client.post(
                f"{BASE_URL}/VendorsAPI/Service1.svc/MarketSnapshot",
                json=snapshot_data,
                headers=headers,
            )
            snapshot_response.raise_for_status()
            snapshot_response = snapshot_response.json()

            if snapshot_response["head"]["statusDescription"] != "Success":
                raise Exception(
                    f"Error from 5Paisa API: {snapshot_response['head']['statusDescription']}"
                )

            # Check if Data array exists and has elements
            if (
                not snapshot_response.get("body", {}).get("Data")
                or len(snapshot_response["body"]["Data"]) == 0
            ):
                raise Exception(f"No data returned for symbol {symbol} on exchange {exchange}")

            quote_data = snapshot_response["body"]["Data"][0]

            # Get market depth data
            depth_data = {
                "head": {"key": api_key},
                "body": {
                    "ClientCode": client_id,
                    "Exchange": map_exchange(exchange),
                    "ExchangeType": map_exchange_type(normalized_exchange),
                    "ScripCode": token,
                    "ScripData": br_symbol if token == "0" else "",
                },
            }

            depth_response = client.post(
                f"{BASE_URL}/VendorsAPI/Service1.svc/V2/MarketDepth",
                json=depth_data,
                headers=headers,
            )
            depth_response.raise_for_status()
            depth_response = depth_response.json()

            if depth_response["head"]["statusDescription"] != "Success":
                raise Exception(
                    f"Error from 5Paisa API: {depth_response['head']['statusDescription']}"
                )

            market_depth = depth_response["body"].get("MarketDepthData", [])

            # Initialize empty bids and asks arrays
            empty_entry = {"price": 0, "quantity": 0}
            bids = []
            asks = []

            # Process market depth data
            buy_orders = [
                order for order in market_depth if order["BbBuySellFlag"] == 66
            ]  # 66 = Buy
            sell_orders = [
                order for order in market_depth if order["BbBuySellFlag"] == 83
            ]  # 83 = Sell

            # Sort orders by price (highest buy, lowest sell)
            buy_orders.sort(key=lambda x: float(x["Price"]), reverse=True)
            sell_orders.sort(key=lambda x: float(x["Price"]))

            # Fill bids and asks arrays
            for order in buy_orders[:5]:
                bids.append({"price": float(order["Price"]), "quantity": int(order["Quantity"])})

            for order in sell_orders[:5]:
                asks.append({"price": float(order["Price"]), "quantity": int(order["Quantity"])})

            # Pad with empty entries if needed
            while len(bids) < 5:
                bids.append(empty_entry)
            while len(asks) < 5:
                asks.append(empty_entry)

            # Calculate total buy/sell quantities
            total_buy_qty = sum(int(order["Quantity"]) for order in buy_orders)
            total_sell_qty = sum(int(order["Quantity"]) for order in sell_orders)

            # Return standardized format
            return {
                "asks": asks,
                "bids": bids,
                "high": float(quote_data.get("High", 0)),
                "low": float(quote_data.get("Low", 0)),
                "ltp": float(quote_data.get("LastTradedPrice", 0)),
                "ltq": int(quote_data.get("LastTradedQty", 0)),
                "oi": int(quote_data.get("OpenInterest", 0)),
                "open": float(quote_data.get("Open", 0)),
                "prev_close": float(quote_data.get("PClose", 0)),
                "totalbuyqty": total_buy_qty,
                "totalsellqty": total_sell_qty,
                "volume": int(quote_data.get("Volume", 0)),
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
            # Normalize exchange for index symbols
            normalized_exchange = normalize_exchange_for_query(symbol, exchange)
            logger.debug(
                f"Getting quotes for {symbol} on {exchange} (normalized: {normalized_exchange})"
            )

            # Get token from symbol
            token = get_token(symbol, normalized_exchange)
            br_symbol = get_br_symbol(symbol, normalized_exchange)

            logger.debug(
                f"Token for {symbol} on {normalized_exchange}: {token}, BR Symbol: {br_symbol}"
            )

            # Prepare request payload
            json_data = {
                "head": {"key": api_key},
                "body": {
                    "ClientCode": client_id,
                    "Data": [
                        {
                            "Exchange": map_exchange(exchange),
                            "ExchangeType": map_exchange_type(normalized_exchange),
                            "ScripCode": token,
                            "ScripData": br_symbol if token == "0" else "",
                        }
                    ],
                },
            }

            logger.debug(
                f"API Request - Exchange: {map_exchange(exchange)}, ExchangeType: {map_exchange_type(normalized_exchange)}, ScripCode: {token}, ScripData: {br_symbol if token == '0' else ''}"
            )

            # Get the shared httpx client
            client = get_httpx_client()

            # Make API request for market snapshot
            headers = {
                "Authorization": f"bearer {self.auth_token}",
                "Content-Type": "application/json",
            }
            response = client.post(
                f"{BASE_URL}/VendorsAPI/Service1.svc/MarketSnapshot",
                json=json_data,
                headers=headers,
            )
            response.raise_for_status()
            response = response.json()

            # Check for successful response
            if response["head"]["statusDescription"] != "Success":
                logger.error(
                    f"API returned non-success status: {response['head']['statusDescription']}"
                )
                return None

            # Check if Data array exists and has elements
            if not response.get("body", {}).get("Data") or len(response["body"]["Data"]) == 0:
                logger.error(f"No data returned for symbol {symbol} on exchange {exchange}")
                logger.error(f"Response: {response}")
                return None

            # Extract quote data
            quote_data = response["body"]["Data"][0]

            # Get bid/ask from market depth
            depth_data = self.get_market_depth(symbol, exchange)

            # Get previous close from PClose field
            prev_close = float(quote_data.get("PClose", 0))
            if prev_close == 0:  # Fallback options if PClose is not available
                prev_close = float(quote_data.get("PreviousClose", 0))
                if prev_close == 0:
                    prev_close = float(quote_data.get("Close", 0))

            # Return just the data without status
            return {
                "ask": depth_data["ask"] if depth_data else 0,
                "bid": depth_data["bid"] if depth_data else 0,
                "high": float(quote_data.get("High", 0)),
                "low": float(quote_data.get("Low", 0)),
                "ltp": float(quote_data.get("LastTradedPrice", 0)),
                "open": float(quote_data.get("Open", 0)),
                "prev_close": prev_close,
                "volume": int(quote_data.get("Volume", 0)),
            }

        except Exception as e:
            logger.error(f"Error in get_quotes: {e}")
            return None

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols using 5paisa's MarketSnapshot API
        The API supports multiple symbols in a single request via the Data array

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            # 5paisa MarketSnapshot supports multiple symbols per request
            # Note: API returns empty for large batches (100+), 50 works reliably
            BATCH_SIZE = 50  # Symbols per API request
            RATE_LIMIT_DELAY = 0.5  # 500ms delay between batches

            if len(symbols) > BATCH_SIZE:
                logger.debug(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
                all_results = []

                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i : i + BATCH_SIZE]
                    logger.debug(
                        f"Processing batch {i // BATCH_SIZE + 1}: symbols {i + 1} to {min(i + BATCH_SIZE, len(symbols))}"
                    )

                    batch_results = self._process_quotes_batch(batch)
                    all_results.extend(batch_results)

                    # Rate limit delay between batches
                    if i + BATCH_SIZE < len(symbols):
                        time.sleep(RATE_LIMIT_DELAY)

                logger.debug(
                    f"Successfully processed {len(all_results)} quotes in {(len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE} batches"
                )
                return all_results
            else:
                return self._process_quotes_batch(symbols)

        except Exception as e:
            logger.exception("Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _process_quotes_batch(self, symbols: list) -> list:
        """
        Process a batch of symbols using 5paisa's MarketSnapshot endpoint
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
        Returns:
            list: List of quote data for the batch
        """
        skipped_symbols = []
        symbol_map = {}  # Map scrip_code to original symbol/exchange

        # Build the Data array for multi-quote request
        data_array = []
        for item in symbols:
            symbol = item["symbol"]
            exchange = item["exchange"]

            # Normalize exchange for index symbols
            normalized_exchange = normalize_exchange_for_query(symbol, exchange)

            # Get token and broker symbol
            token = get_token(symbol, normalized_exchange)
            br_symbol = get_br_symbol(symbol, normalized_exchange)

            if not token:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: could not resolve token")
                skipped_symbols.append(
                    {"symbol": symbol, "exchange": exchange, "error": "Could not resolve token"}
                )
                continue

            data_array.append(
                {
                    "Exchange": map_exchange(exchange),
                    "ExchangeType": map_exchange_type(normalized_exchange),
                    "ScripCode": token,
                    "ScripData": br_symbol if token == "0" else "",
                }
            )

            # Store mapping for response processing
            # Use composite key (token + exchange + symbol) to handle token "0" cases
            # where multiple symbols might have the same fallback token
            if token == "0":
                # For fallback cases, use ScripData (br_symbol) as key
                map_key = f"scripdata:{br_symbol}"
            else:
                map_key = str(token)

            symbol_map[map_key] = {
                "symbol": symbol,
                "exchange": exchange,
                "br_symbol": br_symbol,
                "token": token,
            }

        if not data_array:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        # Build request payload
        json_data = {
            "head": {"key": api_key},
            "body": {"ClientCode": client_id, "Data": data_array},
        }

        # Get the shared httpx client
        client = get_httpx_client()

        # Make API request
        headers = {"Authorization": f"bearer {self.auth_token}", "Content-Type": "application/json"}

        try:
            response = client.post(
                f"{BASE_URL}/VendorsAPI/Service1.svc/MarketSnapshot",
                json=json_data,
                headers=headers,
            )
            response.raise_for_status()
            response_data = response.json()

            if response_data["head"]["statusDescription"] != "Success":
                error_msg = response_data["head"].get("statusDescription", "Unknown error")
                logger.error(f"Error from 5Paisa MarketSnapshot API: {error_msg}")
                raise Exception(f"Error from 5Paisa API: {error_msg}")

            # Parse response and build results
            results = []
            quotes_data = response_data.get("body", {}).get("Data", [])

            for quote_item in quotes_data:
                # Get the scrip code from response
                scrip_code = str(quote_item.get("ScripCode", ""))
                scrip_data = quote_item.get("ScripData", "") or quote_item.get("Symbol", "")

                # Look up original symbol and exchange
                # First try by scrip_code, then by scripdata for token "0" cases
                original = symbol_map.get(scrip_code)
                if not original and scrip_code == "0" and scrip_data:
                    original = symbol_map.get(f"scripdata:{scrip_data}")

                if not original:
                    # Try to find by matching broker symbol in values
                    for key, info in symbol_map.items():
                        if info.get("br_symbol") == scrip_data:
                            original = info
                            break

                if not original:
                    logger.warning(
                        f"Could not map scrip code {scrip_code} (ScripData: {scrip_data}) to original symbol"
                    )
                    continue

                # Get previous close
                prev_close = float(quote_item.get("PClose", 0))
                if prev_close == 0:
                    prev_close = float(quote_item.get("PreviousClose", 0))
                    if prev_close == 0:
                        prev_close = float(quote_item.get("Close", 0))

                results.append(
                    {
                        "symbol": original["symbol"],
                        "exchange": original["exchange"],
                        "data": {
                            "bid": 0,  # MarketSnapshot doesn't include bid/ask
                            "ask": 0,
                            "open": float(quote_item.get("Open", 0)),
                            "high": float(quote_item.get("High", 0)),
                            "low": float(quote_item.get("Low", 0)),
                            "ltp": float(quote_item.get("LastTradedPrice", 0)),
                            "prev_close": prev_close,
                            "volume": int(quote_item.get("Volume", 0)),
                            "oi": int(quote_item.get("OpenInterest", 0)),
                        },
                    }
                )

            return skipped_symbols + results

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error in multiquotes: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"Error processing quotes batch: {e}")
            raise

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
            "d": "1d",  # Also map lowercase 'd'
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
            return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

        # Convert to DataFrame
        df = pd.DataFrame(raw_data)

        # Convert string timestamps to datetime
        df["timestamp"] = pd.to_datetime(df["timestamp"])

        # Timezone handling
        ist = pytz.timezone("Asia/Kolkata")
        df["timestamp"] = df["timestamp"].dt.tz_convert(ist)

        # Sort by timestamp
        df = df.sort_values("timestamp")

        # Reorder columns
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]

        logger.debug(f"Processed {len(df)} candles from raw data")
        return df

    def get_history(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
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
            if interval.upper() == "D":
                interval = "1d"  # Always use 1d internally for daily
                logger.debug(f"Debug: Converted interval from {original_interval} to {interval}")

            # Normalize exchange for index symbols. Index tokens are stored under
            # NSE_INDEX / BSE_INDEX in the symbol DB, so looking them up with the
            # raw NSE / BSE exchange returns the wrong (or no) token and the
            # historical API then returns nothing.
            normalized_exchange = normalize_exchange_for_query(symbol, exchange)
            is_index = normalized_exchange.endswith("_INDEX")

            # Get token from symbol
            token = get_token(symbol, normalized_exchange)

            # Map interval
            fivepaisa_interval = self.map_interval(interval)
            logger.debug(f"Debug: Mapped {interval} to {fivepaisa_interval}")

            if not fivepaisa_interval:
                supported = ["1m", "5m", "15m", "30m", "1h", "1d"]
                raise Exception(
                    f"Unsupported interval '{interval}'. Supported intervals: {', '.join(supported)}"
                )

            # Convert 5paisa timeframe to our format
            resolution = self.timeframe_map.get(interval, "1D")
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
            if interval == "1d":
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
                current_end = min(current_start + pd.Timedelta(days=chunk_days - 1), to_date)

                # Format dates for API
                chunk_start = current_start.strftime("%Y-%m-%d")
                chunk_end = current_end.strftime("%Y-%m-%d")

                # Prepare URL for historical data
                url = f"/V2/historical/{map_exchange(exchange)}/{map_exchange_type(exchange)}/{token}/{fivepaisa_interval}"
                url += f"?from={chunk_start}&end={chunk_end}"

                logger.debug(f"Fetching chunk from {chunk_start} to {chunk_end}")  # Debug log

                try:
                    # Make API request
                    client = get_httpx_client()
                    headers = {
                        "Authorization": f"bearer {self.auth_token}",
                        "Content-Type": "application/json",
                    }
                    response = client.get(f"{BASE_URL}{url}", headers=headers)
                    response.raise_for_status()
                    response = response.json()

                    if response.get("status") != "success":
                        error_msg = response.get("message", "Unknown error")
                        logger.error(f"Error for chunk {chunk_start} to {chunk_end}: {error_msg}")
                        current_start = current_end + pd.Timedelta(days=1)
                        continue

                    candles = response.get("data", {}).get("candles", [])
                    if not candles:
                        logger.debug(f"No data for chunk {chunk_start} to {chunk_end}")
                        current_start = current_end + pd.Timedelta(days=1)
                        continue

                    # Transform candles
                    transformed_candles = []
                    for candle in candles:
                        try:
                            # Skip invalid candles
                            if len(candle) < 6:
                                continue

                            # Parse the candle datetime. 5Paisa historical candles
                            # are stamped in IST wall-clock (e.g. 2026-06-17T09:15:00),
                            # so keep it naive here and localize per-branch below.
                            dt = datetime.strptime(candle[0], "%Y-%m-%dT%H:%M:%S")

                            open_price = float(candle[1])
                            high_price = float(candle[2])
                            low_price = float(candle[3])
                            close_price = float(candle[4])
                            volume = int(candle[5])

                            # Skip holidays and invalid data:
                            # 1. Zero volume
                            # 2. All prices are zero
                            # 3. High = Low (usually indicates no trading)
                            #
                            # Indices (NIFTY, SENSEX, INDIAVIX, ...) have no traded
                            # volume, so a zero-volume candle is valid data for them.
                            # Applying the volume/high==low filters to indices drops
                            # every candle. For indices we only skip fully-empty
                            # (all-zero OHLC) candles.
                            all_prices_zero = (
                                open_price == 0
                                and high_price == 0
                                and low_price == 0
                                and close_price == 0
                            )
                            if is_index:
                                # Indices have no traded volume; only fully-empty.
                                if all_prices_zero:
                                    continue
                            elif interval.upper() == "D":
                                # Daily non-index: a holiday/no-trade day shows up as
                                # flat or empty data, so the stricter filter is correct
                                # at this resolution.
                                if volume == 0 or all_prices_zero or (high_price == low_price):
                                    continue
                            else:
                                # Intraday non-index: a quiet minute legitimately has
                                # volume == 0 and/or high == low. Dropping those candles
                                # (combined with the old index-based timestamp rebuild)
                                # made intraday series appear to stop mid-session. Only
                                # drop genuinely empty candles.
                                if all_prices_zero:
                                    continue

                            # For daily candles, create timestamp at midnight UTC like Angel does
                            if interval.upper() == "D":
                                # Extract the date from the API timestamp
                                date_only = dt.date()
                                # Create datetime at midnight UTC (same as Angel broker)
                                dt_midnight = datetime(
                                    date_only.year, date_only.month, date_only.day, 0, 0, 0
                                )
                                dt_midnight = pytz.UTC.localize(dt_midnight)
                                timestamp_sec = int(dt_midnight.timestamp())
                            else:
                                # Intraday: localize the API's IST wall-clock time
                                # directly and keep it. We use the REAL candle time
                                # (no market-hours shifting, no index-based rebuild),
                                # so missing/filtered candles leave honest gaps instead
                                # of silently shifting the whole series earlier.
                                ist = pytz.timezone("Asia/Kolkata")
                                dt = ist.localize(dt)
                                timestamp_sec = int(dt.timestamp())

                            transformed_candle = {
                                "timestamp": timestamp_sec,  # Store as integer seconds
                                "open": open_price,
                                "high": high_price,
                                "low": low_price,
                                "close": close_price,
                                "volume": volume,
                            }
                            transformed_candles.append(transformed_candle)

                        except Exception as e:
                            logger.error(f"Error transforming candle {candle}: {e}")
                            continue

                    if transformed_candles:
                        chunk_df = pd.DataFrame(transformed_candles)
                        # Ensure timestamp column exists and is first
                        if "timestamp" not in chunk_df.columns:
                            logger.warning(
                                f"Warning: Missing timestamp column in chunk. Columns: {chunk_df.columns}"
                            )
                            continue
                        dfs.append(chunk_df)
                        logger.debug(f"Added {len(transformed_candles)} candles from chunk")

                except Exception as e:
                    logger.error(f"Error processing chunk {chunk_start} to {chunk_end}: {e}")

                # Move to next chunk
                current_start = current_end + pd.Timedelta(days=1)

            # If no data was found, return empty DataFrame
            if not dfs:
                logger.info("No valid data found for the entire period")
                return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

            # Combine all chunks
            df = pd.concat(dfs, ignore_index=True)

            # Sort by timestamp and remove any duplicates
            df = (
                df.sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"])
                .reset_index(drop=True)
            )

            # Sort by the new timestamps
            df = df.sort_values("timestamp").reset_index(drop=True)

            # For daily interval, normalize to date only (remove time component)
            # This matches Upstox and other brokers' behavior for daily data
            if original_interval.upper() == "D" or original_interval == "d":
                logger.debug("Debug: Processing daily interval - normalizing to date only")
                # Convert Unix timestamps to datetime
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
                # Add IST offset to get correct date
                df["timestamp"] = df["timestamp"] + pd.Timedelta(hours=5, minutes=30)
                # Extract only the date part, then convert back to datetime at midnight
                df["timestamp"] = df["timestamp"].apply(lambda x: x.date())
                df["timestamp"] = pd.to_datetime(df["timestamp"])
                # Convert to Unix timestamp (midnight)
                df["timestamp"] = df["timestamp"].apply(lambda x: int(x.timestamp()))
                logger.debug(
                    f"Debug: First timestamp value: {df['timestamp'].iloc[0] if len(df) > 0 else 'empty'}"
                )
            else:
                # Intraday timestamps are already the real IST candle times stored
                # as epoch seconds. Keep them verbatim — do NOT renumber by row
                # index (the old fix_timestamps() rebuilt every timestamp as
                # 09:15 + i*interval, which assumed a gapless series and truncated
                # the session whenever any candle was filtered out).
                df["timestamp"] = df["timestamp"].astype("int64")

            # Log first timestamp after processing
            if len(df) > 0:
                logger.debug(
                    f"Debug: First timestamp after fixing: {pd.to_datetime(df['timestamp'].iloc[0], unit='s')}"
                )

            # Ensure numeric columns are properly typed
            numeric_columns = ["open", "high", "low", "close", "volume"]
            df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric)

            # Add OI column (always 0 for stocks, set to 0 for consistency with Angel broker)
            df["oi"] = 0

            # Reorder columns to match Angel broker REST API format
            df = df[["close", "high", "low", "open", "timestamp", "volume", "oi"]]

            logger.debug(f"Returning {len(df)} total candles")
            return df

        except Exception as e:
            error_msg = str(e)
            logger.exception(
                f"Error in get_history: {error_msg}"
            )  # Debug log

            # Check if this is the timestamp conversion error with raw_data available
            if (
                "non convertible value" in error_msg
                and "with the unit" in error_msg
                and hasattr(e, "raw_data")
            ):
                logger.error("Attempting to recover from timestamp conversion error using raw_data")
                try:
                    return self._process_raw_candles(e.raw_data, interval)
                except Exception as recovery_error:
                    logger.error(f"Recovery attempt failed: {recovery_error}")

            raise

    def get_supported_intervals(self) -> list:
        """Get list of supported intervals"""
        return ["1m", "5m", "10m", "15m", "30m", "1h", "D"]
