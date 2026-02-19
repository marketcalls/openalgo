import json
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
import pandas as pd

from database.auth_db import Auth
from database.token_db import get_br_symbol, get_brexchange, get_oa_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

from .alicebluewebsocket import AliceBlueWebSocket

logger = get_logger(__name__)

# AliceBlue V2 API URLs
BASE_URL = "https://a3.aliceblueonline.com/"
HISTORICAL_API_URL = BASE_URL + "open-api/od/ChartAPIService/api/chart/history"


class BrokerData:
    """
    BrokerData class for AliceBlue broker.
    Handles market data operations including quotes, market depth, and historical data.
    """

    def __init__(self, auth_token=None):
        self.token_mapping = {}
        self.session_id = auth_token  # Store the session ID from authentication
        # AliceBlue only supports 1-minute and daily data
        self.timeframe_map = {
            "1m": "1",  # 1-minute data
            "D": "D",  # Daily data
        }

    def get_websocket(self, force_new=False):
        """
        Get or create the global WebSocket instance.

        Args:
            force_new (bool): Force creation of a new WebSocket connection even if one exists

        Returns:
            AliceBlueWebSocket: WebSocket client instance or None if creation fails
        """
        # Return existing connection if it's valid and not forced to create a new one
        if not force_new and hasattr(self, "_websocket") and self._websocket:
            if hasattr(self._websocket, "is_connected") and self._websocket.is_connected:
                return self._websocket

        try:
            if not self.session_id:
                logger.error("Session ID not available. Please login first.")
                return None

            # Clean up any existing connection
            if hasattr(self, "_websocket") and self._websocket:
                try:
                    self._websocket.disconnect()
                except Exception as e:
                    logger.warning(f"Error closing existing WebSocket: {str(e)}")

            # Get user ID (clientId) from the auth database
            # This is the numeric clientId (e.g., '1614986') stored during login,
            # NOT the appCode from BROKER_API_KEY
            auth_obj = Auth.query.filter_by(broker='aliceblue', is_revoked=False).first()
            user_id = auth_obj.user_id if auth_obj else None
            if not user_id:
                logger.error("Missing user_id (clientId) for AliceBlue WebSocket. Please re-login.")
                return None

            # Create new websocket connection
            logger.info("Creating new WebSocket connection for AliceBlue")
            self._websocket = AliceBlueWebSocket(user_id, self.session_id)
            self._websocket.connect()

            # Wait for connection to establish
            wait_time = 0
            max_wait = 10  # Maximum 10 seconds to wait
            while wait_time < max_wait and not self._websocket.is_connected:
                time.sleep(0.5)
                wait_time += 0.5

            if not self._websocket.is_connected:
                logger.error("Failed to connect WebSocket within timeout")
                return None

            logger.info("WebSocket connection established successfully")
            return self._websocket

        except Exception as e:
            logger.error(f"Error creating WebSocket: {str(e)}")
            return None

    @staticmethod
    def _normalize_token(token) -> str:
        """Normalize token to integer string (e.g. 3045.0 -> '3045')."""
        try:
            return str(int(float(token)))
        except (ValueError, TypeError):
            return str(token)

    def _map_exchange(self, exchange: str) -> str:
        """Map OpenAlgo exchange codes to AliceBlue API exchange codes."""
        exchange_map = {
            "NSE_INDEX": "NSE",
            "BSE_INDEX": "BSE",
            "MCX_INDEX": "MCX",
        }
        return exchange_map.get(exchange, exchange)

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol.

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE', 'NIFTY')
            exchange: Exchange (e.g., NSE, BSE, NFO, NSE_INDEX, BSE_INDEX)

        Returns:
            dict: Quote data in OpenAlgo standard format
        """
        try:
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange) or symbol
            token = self._normalize_token(get_token(symbol, exchange))

            if not token:
                raise Exception(f"Token not found for {symbol} on {exchange}")

            # Map exchange for AliceBlue WebSocket API
            api_exchange = self._map_exchange(exchange)

            # Get WebSocket connection
            websocket = self.get_websocket()
            if not websocket or not websocket.is_connected:
                logger.warning("WebSocket not connected, reconnecting...")
                websocket = self.get_websocket(force_new=True)

            if not websocket or not websocket.is_connected:
                raise Exception("WebSocket connection unavailable")

            # Create instrument for subscription
            class Instrument:
                def __init__(self, exchange, token, symbol=None):
                    self.exchange = exchange
                    self.token = token
                    self.symbol = symbol

            instrument = Instrument(exchange=api_exchange, token=token, symbol=br_symbol)
            instruments = [instrument]

            # Subscribe to tick data
            logger.info(f"Subscribing to {api_exchange}:{symbol} with token {token}")
            success = websocket.subscribe(instruments, is_depth=False)

            if not success:
                raise Exception(f"Failed to subscribe to {symbol} on {exchange}")

            # Wait for data to arrive
            time.sleep(2.0)

            # Retrieve quote from WebSocket
            quote = websocket.get_quote(api_exchange, token)

            # Unsubscribe after getting the data
            websocket.unsubscribe(instruments, is_depth=False)

            if not quote:
                raise Exception(f"No quote data received for {symbol} on {exchange}")

            # Return in OpenAlgo standard format (matching Angel broker)
            return {
                "bid": float(quote.get("bid", 0)),
                "ask": float(quote.get("ask", 0)),
                "open": float(quote.get("open", 0)),
                "high": float(quote.get("high", 0)),
                "low": float(quote.get("low", 0)),
                "ltp": float(quote.get("ltp", 0)),
                "prev_close": float(quote.get("close", 0)),
                "volume": int(quote.get("volume", 0)),
                "oi": int(quote.get("open_interest", 0)),
            }

        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}")

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols using WebSocket.

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            BATCH_SIZE = 100

            if len(symbols) > BATCH_SIZE:
                logger.info(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
                all_results = []

                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i : i + BATCH_SIZE]
                    logger.info(
                        f"Processing batch {i // BATCH_SIZE + 1}: symbols {i + 1} to {min(i + BATCH_SIZE, len(symbols))}"
                    )
                    batch_results = self._process_multiquotes_batch(batch)
                    all_results.extend(batch_results)

                logger.info(f"Successfully processed {len(all_results)} quotes")
                return all_results
            else:
                return self._process_multiquotes_batch(symbols)

        except Exception as e:
            logger.exception("Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _process_multiquotes_batch(self, symbols: list) -> list:
        """
        Process a batch of symbols using WebSocket subscription.

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
        Returns:
            list: List of quote data for the batch
        """
        results = []
        skipped_symbols = []
        instruments = []
        symbol_map = {}  # Map api_exchange:token -> original info

        # Get WebSocket connection
        websocket = self.get_websocket()
        if not websocket or not websocket.is_connected:
            logger.warning("WebSocket not connected, reconnecting...")
            websocket = self.get_websocket(force_new=True)

        if not websocket or not websocket.is_connected:
            logger.error("Could not establish WebSocket connection")
            raise ConnectionError("WebSocket connection unavailable")

        class Instrument:
            def __init__(self, exchange, token, symbol=None):
                self.exchange = exchange
                self.token = token
                self.symbol = symbol

        # Prepare all instruments
        for item in symbols:
            symbol = item["symbol"]
            exchange = item["exchange"]

            raw_token = get_token(symbol, exchange)
            if not raw_token:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: could not resolve token")
                skipped_symbols.append(
                    {"symbol": symbol, "exchange": exchange, "error": "Could not resolve token"}
                )
                continue

            token = self._normalize_token(raw_token)
            br_symbol = get_br_symbol(symbol, exchange) or symbol
            api_exchange = self._map_exchange(exchange)

            instrument = Instrument(exchange=api_exchange, token=token, symbol=br_symbol)
            instruments.append(instrument)

            symbol_map[f"{api_exchange}:{token}"] = {
                "symbol": symbol,
                "exchange": exchange,
                "token": token,
            }

        if not instruments:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        # Subscribe to all instruments at once
        logger.info(f"Subscribing to {len(instruments)} symbols via WebSocket")
        success = websocket.subscribe(instruments, is_depth=False)

        if not success:
            logger.error("Failed to send subscription request")
            for key, info in symbol_map.items():
                results.append(
                    {"symbol": info["symbol"], "exchange": info["exchange"], "error": "Subscription failed"}
                )
            return skipped_symbols + results

        # Wait for data to arrive
        wait_time = min(max(len(instruments) * 0.05, 2), 10)
        logger.debug(f"Waiting {wait_time:.1f}s for quote data...")
        time.sleep(wait_time)

        # Collect results from WebSocket
        for key, info in symbol_map.items():
            api_exchange, token = key.split(":")
            quote = websocket.get_quote(api_exchange, token)

            if quote:
                results.append(
                    {
                        "symbol": info["symbol"],
                        "exchange": info["exchange"],
                        "data": {
                            "bid": float(quote.get("bid", 0)),
                            "ask": float(quote.get("ask", 0)),
                            "open": float(quote.get("open", 0)),
                            "high": float(quote.get("high", 0)),
                            "low": float(quote.get("low", 0)),
                            "ltp": float(quote.get("ltp", 0)),
                            "prev_close": float(quote.get("close", 0)),
                            "volume": int(quote.get("volume", 0)),
                            "oi": int(quote.get("open_interest", 0)),
                        },
                    }
                )
            else:
                results.append(
                    {"symbol": info["symbol"], "exchange": info["exchange"], "error": "No data received"}
                )

        # Unsubscribe after getting data
        logger.info(f"Unsubscribing from {len(instruments)} symbols")
        websocket.unsubscribe(instruments, is_depth=False)

        logger.info(
            f"Retrieved quotes for {len([r for r in results if 'data' in r])}/{len(symbol_map)} symbols"
        )
        return skipped_symbols + results

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol.

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE', 'SBIN')
            exchange: Exchange (e.g., NSE, BSE, NFO, NSE_INDEX, BSE_INDEX)

        Returns:
            dict: Market depth data in OpenAlgo standard format
        """
        try:
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange) or symbol
            token = self._normalize_token(get_token(symbol, exchange))

            if not token:
                raise Exception(f"Token not found for {symbol} on {exchange}")

            # Map exchange for AliceBlue WebSocket API
            api_exchange = self._map_exchange(exchange)

            # Get WebSocket connection
            websocket = self.get_websocket()
            if not websocket or not websocket.is_connected:
                logger.warning("WebSocket not connected, reconnecting...")
                websocket = self.get_websocket(force_new=True)

            if not websocket or not websocket.is_connected:
                raise Exception("WebSocket connection unavailable")

            # Create instrument for subscription
            class Instrument:
                def __init__(self, exchange, token, symbol=None):
                    self.exchange = exchange
                    self.token = token
                    self.symbol = symbol

            instrument = Instrument(exchange=api_exchange, token=token, symbol=br_symbol)

            # Subscribe to depth data (is_depth=True sends t='d')
            logger.info(f"Subscribing to depth for {api_exchange}:{symbol} with token {token}")
            success = websocket.subscribe([instrument], is_depth=True)

            if not success:
                raise Exception(f"Failed to subscribe to depth for {symbol} on {exchange}")

            # Wait for depth data to arrive
            time.sleep(2.0)

            # Retrieve depth from WebSocket
            depth = websocket.get_market_depth(api_exchange, token)

            # Unsubscribe after getting the data
            websocket.unsubscribe([instrument], is_depth=True)

            if not depth:
                raise Exception(f"No market depth received for {symbol} on {exchange}")

            # Format bids and asks with exactly 5 entries each (matching Angel format)
            bids = []
            asks = []

            raw_bids = depth.get("bids", [])
            for i in range(5):
                if i < len(raw_bids):
                    bids.append({
                        "price": raw_bids[i].get("price", 0),
                        "quantity": raw_bids[i].get("quantity", 0),
                    })
                else:
                    bids.append({"price": 0, "quantity": 0})

            raw_asks = depth.get("asks", [])
            for i in range(5):
                if i < len(raw_asks):
                    asks.append({
                        "price": raw_asks[i].get("price", 0),
                        "quantity": raw_asks[i].get("quantity", 0),
                    })
                else:
                    asks.append({"price": 0, "quantity": 0})

            # Return in OpenAlgo standard format (matching Angel broker)
            return {
                "bids": bids,
                "asks": asks,
                "high": depth.get("high", 0) if "high" in depth else 0,
                "low": depth.get("low", 0) if "low" in depth else 0,
                "ltp": depth.get("ltp", 0),
                "ltq": depth.get("last_trade_quantity", 0),
                "open": depth.get("open", 0) if "open" in depth else 0,
                "prev_close": depth.get("close", 0) if "close" in depth else 0,
                "volume": depth.get("volume", 0) if "volume" in depth else 0,
                "oi": depth.get("open_interest", 0),
                "totalbuyqty": depth.get("total_buy_quantity", 0),
                "totalsellqty": depth.get("total_sell_quantity", 0),
            }

        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")

    def get_history(
        self, symbol: str, exchange: str, timeframe: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        Get historical candle data for a symbol.

        Args:
            symbol (str): Trading symbol (e.g., 'TCS', 'RELIANCE')
            exchange (str): Exchange code (NSE, BSE, NFO, etc.)
            timeframe (str): Timeframe such as '1m', '5m', etc.
            start_date (str): Start date in YYYY-MM-DD format
            end_date (str): End date in YYYY-MM-DD format

        Returns:
            pd.DataFrame: DataFrame with historical candle data
        """
        try:
            logger.debug(f"Getting historical data for {symbol}:{exchange}, timeframe: {timeframe}")
            logger.debug(f"Date range: {start_date} to {end_date}")
            logger.debug(f"Date types - start_date: {type(start_date)}, end_date: {type(end_date)}")

            # Get token for the symbol
            token = get_token(symbol, exchange)
            if not token:
                logger.error(f"Token not found for {symbol} on {exchange}")
                return pd.DataFrame()

            logger.debug(f"Found token {token} for {symbol}:{exchange}")

            # Convert exchange for AliceBlue API (same as Angel)
            if exchange == "NSE_INDEX":
                exchange = "NSE"
            elif exchange == "BSE_INDEX":
                exchange = "BSE"
            elif exchange == "MCX_INDEX":
                exchange = "MCX"

            # Check for exchange limitations based on AliceBlue API documentation
            if exchange in ["BSE", "BCD", "BFO"]:
                logger.error(f"Historical data not available for {exchange} exchange on AliceBlue")
                return pd.DataFrame()

            # For MCX, NFO, CDS - only current expiry contracts are supported
            if exchange in ["MCX", "NFO", "CDS"]:
                logger.warning(
                    f"Note: AliceBlue only provides historical data for current expiry contracts on {exchange}"
                )

            # Check if timeframe is supported
            if timeframe not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                logger.error(
                    f"Unsupported timeframe: {timeframe}. AliceBlue only supports: {', '.join(supported)}"
                )
                return pd.DataFrame()

            # Get the AliceBlue resolution format
            aliceblue_timeframe = self.timeframe_map[timeframe]

            # V2 API uses just the session token in Bearer header
            # Same format as all other V2 API calls
            auth_token = self.session_id

            if not auth_token:
                logger.error("Missing session token for historical data")
                return pd.DataFrame()

            headers = {
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json",
            }

            # Alternative: Try adding session token to payload as some historical APIs expect it
            # payload['sessionId'] = session_id

            # For indices, append ::index to the exchange
            exchange_str = f"{exchange}::index" if exchange.endswith("IDX") else exchange

            # Convert timestamps to milliseconds as required by AliceBlue API
            # Format: Unix timestamp in milliseconds (like 1660128489000)
            import time
            from datetime import datetime

            def convert_to_unix_ms(timestamp, is_end_date=False):
                """Convert various timestamp formats to Unix milliseconds in IST

                Args:
                    timestamp: The timestamp to convert
                    is_end_date: If True, sets time to end of day (23:59:59) for date-only strings
                """
                import pytz

                ist = pytz.timezone("Asia/Kolkata")

                logger.debug(
                    f"Converting timestamp: {timestamp} (type: {type(timestamp)}, is_end_date: {is_end_date})"
                )

                # Handle datetime.date objects from marshmallow schema
                if hasattr(timestamp, "strftime"):
                    # It's a date or datetime object
                    timestamp = timestamp.strftime("%Y-%m-%d")
                    logger.debug(f"Converted date object to string: {timestamp}")

                if isinstance(timestamp, str):
                    # Handle date strings like '2025-07-03'
                    try:
                        if "T" in timestamp or " " in timestamp:
                            # Handle datetime strings like '2025-07-03T10:30:00' or '2025-07-03 10:30:00'
                            dt = datetime.fromisoformat(timestamp.replace("T", " "))
                        else:
                            # Handle date-only strings like '2025-07-03'
                            dt = datetime.strptime(timestamp, "%Y-%m-%d")
                            if is_end_date:
                                # Set to end of day (23:59:59) for end dates
                                dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                            else:
                                # For intraday data, set to market open (09:15:00) for start dates
                                # This ensures we get full day data from market open
                                dt = dt.replace(hour=9, minute=15, second=0, microsecond=0)

                        # Localize to IST timezone (AliceBlue expects IST timestamps)
                        dt_ist = ist.localize(dt)

                        # Convert to Unix timestamp in seconds, then to milliseconds
                        result = str(int(dt_ist.timestamp() * 1000))
                        logger.debug(f"Converted '{timestamp}' to {result} (Date: {dt_ist})")
                        return result
                    except (ValueError, Exception) as e:
                        logger.error(f"Error parsing timestamp string '{timestamp}': {e}")
                        logger.error(f"Timestamp type: {type(timestamp)}, value: {repr(timestamp)}")
                        # Fallback to current time - THIS SHOULD NOT HAPPEN
                        logger.error(
                            "WARNING: Falling back to current time - this is likely a bug!"
                        )
                        return str(int(time.time() * 1000))
                elif isinstance(timestamp, (int, float)):
                    if timestamp > 1000000000000:
                        # Already in milliseconds
                        return str(int(timestamp))
                    elif timestamp > 1000000000:
                        # In seconds, convert to milliseconds
                        return str(int(timestamp * 1000))
                    else:
                        # Unknown format, assume seconds and convert
                        return str(int(timestamp * 1000))
                else:
                    # Fallback to current time
                    return str(int(time.time() * 1000))

            start_ms = convert_to_unix_ms(start_date, is_end_date=False)
            end_ms = convert_to_unix_ms(end_date, is_end_date=True)

            # Log the conversion for debugging
            logger.info(
                f"Date conversion - Start: {start_date} -> {start_ms}, End: {end_date} -> {end_ms}"
            )

            # Validate that dates are not in the future
            current_time_ms = int(time.time() * 1000)
            if int(start_ms) > current_time_ms:
                logger.error(
                    f"Start date {start_date} is in the future. Historical data is only available for past dates."
                )
                return pd.DataFrame()

            # If end date is in future, cap it to current time
            if int(end_ms) > current_time_ms:
                logger.warning(f"End date {end_date} is in the future. Capping to current time.")
                end_ms = str(current_time_ms)

            # Ensure start and end times are different and valid
            if start_ms == end_ms:
                logger.warning(
                    f"Start and end timestamps are the same: {start_ms}. Adjusting end time."
                )
                # If they're the same, add one day to the end time
                end_ms = str(int(end_ms) + 86400000)  # Add 24 hours in milliseconds

            # For intraday data, ensure minimum time range
            if timeframe != "D":
                time_diff_ms = int(end_ms) - int(start_ms)
                min_range_ms = 3600000  # Minimum 1 hour for intraday data

                if time_diff_ms < min_range_ms:
                    logger.warning(
                        f"Time range too small ({time_diff_ms}ms). Extending to minimum 1 hour for intraday data."
                    )
                    end_ms = str(int(start_ms) + min_range_ms)

            # Prepare request payload according to AliceBlue API docs
            payload = {
                "token": str(token),  # Token should be the instrument token
                "exchange": exchange,  # Exchange should be NSE, NFO, etc.
                "from": start_ms,
                "to": end_ms,
                "resolution": aliceblue_timeframe,
            }

            # Debug logging
            logger.debug("Making historical data request:")
            logger.debug(f"URL: {HISTORICAL_API_URL}")
            logger.debug(f"Headers: {headers}")
            logger.debug(f"Payload: {payload}")

            # Make request to historical API
            client = get_httpx_client()
            response = client.post(HISTORICAL_API_URL, headers=headers, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Check if response contains valid data
            if data.get("stat") == "Not_Ok" or "result" not in data:
                error_msg = data.get("emsg", "Unknown error")
                logger.error(f"Error in historical data response: {error_msg}")

                # Provide more helpful error messages based on the error
                if "No data available" in error_msg:
                    if exchange in ["MCX", "NFO", "CDS"]:
                        logger.error(
                            f"No data available. For {exchange}, AliceBlue only provides data for current expiry contracts."
                        )
                        logger.error(
                            f"Symbol '{symbol}' might be an expired contract or not a current expiry."
                        )
                    elif exchange in ["BSE", "BCD", "BFO"]:
                        logger.error(
                            f"AliceBlue does not support historical data for {exchange} exchange yet."
                        )
                    else:
                        logger.error(f"No historical data available for {symbol} on {exchange}.")
                        logger.error(
                            "This could be due to: 1) Symbol not traded in the date range, 2) Invalid symbol, or 3) Data not available during market hours (available from 5:30 PM to 8 AM on weekdays)"
                        )

                return pd.DataFrame()

            # Convert response to DataFrame
            df = pd.DataFrame(data["result"])

            # Rename columns to standard format
            # Use 'timestamp' instead of 'datetime' to match Angel and other brokers
            df = df.rename(
                columns={
                    "time": "timestamp",
                    "open": "open",
                    "high": "high",
                    "low": "low",
                    "close": "close",
                    "volume": "volume",
                }
            )

            # Ensure DataFrame has required columns
            if not all(
                col in df.columns for col in ["timestamp", "open", "high", "low", "close", "volume"]
            ):
                logger.error("Missing required columns in historical data response")
                return pd.DataFrame()

            # Log the first few rows of raw data to debug
            logger.info(
                f"First 3 rows of historical data from AliceBlue: {df.head(3).to_dict('records')}"
            )
            logger.info(f"Total rows received: {len(df)}")

            # Convert time column to datetime
            # AliceBlue returns time as string in format 'YYYY-MM-DD HH:MM:SS'
            df["timestamp"] = pd.to_datetime(df["timestamp"])

            # Handle different timeframes
            if timeframe == "D":
                # For daily data, normalize to date only (no time component)
                # Set time to midnight to represent the date
                df["timestamp"] = df["timestamp"].dt.normalize()

                # Add IST offset (5:30 hours) for proper Unix timestamp conversion
                # This ensures the date is correctly represented
                df["timestamp"] = df["timestamp"] + pd.Timedelta(hours=5, minutes=30)
            else:
                # For intraday data, adjust timestamps to represent the start of the candle
                # AliceBlue provides end-of-candle timestamps (XX:XX:59), we need start (XX:XX:00)
                df["timestamp"] = df["timestamp"].dt.floor("min")

            # AliceBlue timestamps are in IST - need to localize them
            import pytz

            ist = pytz.timezone("Asia/Kolkata")

            # Localize to IST (AliceBlue provides IST timestamps without timezone info)
            df["timestamp"] = df["timestamp"].dt.tz_localize(ist)

            # Convert timestamp to Unix epoch (seconds since 1970)
            # This will correctly handle the IST timezone
            df["timestamp"] = df["timestamp"].astype("int64") // 10**9

            # Ensure numeric columns are properly typed
            numeric_columns = ["open", "high", "low", "close", "volume"]
            df[numeric_columns] = df[numeric_columns].apply(pd.to_numeric)

            # Sort by timestamp and remove any duplicates
            df = (
                df.sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"])
                .reset_index(drop=True)
            )

            # Add OI column with zeros (AliceBlue doesn't provide OI in historical data)
            df["oi"] = 0

            # For intraday data, ensure we have data from market open (9:15 AM)
            if timeframe != "D" and not df.empty:
                from datetime import datetime, time, timedelta

                import pytz

                ist = pytz.timezone("Asia/Kolkata")

                # Get the date from the first timestamp
                first_timestamp = pd.to_datetime(df["timestamp"].iloc[0], unit="s")
                first_timestamp = first_timestamp.tz_localize("UTC").tz_convert(ist)

                # Create market open time for that date
                market_date = first_timestamp.date()
                market_open = ist.localize(datetime.combine(market_date, time(9, 15)))
                market_open_ts = int(market_open.timestamp())

                # If first data point is after 9:15 AM, pad with data from 9:15 AM
                if df["timestamp"].iloc[0] > market_open_ts:
                    logger.info(
                        "Padding data from market open (9:15 AM) to first available data point"
                    )

                    # Get the first available price as reference
                    first_price = df["open"].iloc[0]

                    # Create timestamps from 9:15 AM to first data point (1-minute intervals)
                    current_ts = market_open_ts
                    padding_data = []

                    while current_ts < df["timestamp"].iloc[0]:
                        padding_data.append(
                            {
                                "timestamp": current_ts,
                                "open": first_price,
                                "high": first_price,
                                "low": first_price,
                                "close": first_price,
                                "volume": 0,
                                "oi": 0,
                            }
                        )
                        current_ts += 60  # Add 1 minute

                    if padding_data:
                        # Create DataFrame from padding data
                        padding_df = pd.DataFrame(padding_data)
                        # Concatenate with original data
                        df = pd.concat([padding_df, df], ignore_index=True)
                        # Re-sort by timestamp
                        df = df.sort_values("timestamp").reset_index(drop=True)
                        logger.info(f"Added {len(padding_data)} data points from market open")

            # Return columns in the order matching Angel broker format
            df = df[["close", "high", "low", "open", "timestamp", "volume", "oi"]]

            return df

        except Exception as e:
            logger.error(f"Error fetching historical data: {str(e)}")
            return pd.DataFrame()

    def get_intervals(self) -> list[str]:
        """
        Get list of supported timeframes.

        Returns:
            List[str]: List of supported timeframe strings
        """
        return list(self.timeframe_map.keys())
