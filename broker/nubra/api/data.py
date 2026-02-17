import json
import os
import threading
import time
import urllib.parse
from datetime import datetime, timedelta

import httpx
import pandas as pd

from database.token_db import get_br_symbol, get_oa_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

from .nubrawebsocket import NubraWebSocket

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="GET", payload=""):
    """Helper function to make API calls to Nubra with 429 rate limit handling."""
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

    max_retries = 3
    base_delay = 1.0

    for attempt in range(max_retries):
        try:
            if method == "GET":
                response = client.get(url, headers=headers)
            elif method == "POST":
                response = client.post(url, headers=headers, content=payload)
            else:
                response = client.request(method, url, headers=headers, content=payload)

            # Handle rate limiting with exponential backoff
            if response.status_code == 429:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"Rate limit hit (429) on {endpoint}, retrying in {delay:.1f}s "
                    f"(attempt {attempt + 1}/{max_retries})"
                )
                if attempt < max_retries - 1:
                    time.sleep(delay)
                    continue
                else:
                    logger.error(f"Rate limit exceeded after {max_retries} retries on {endpoint}")
                    raise Exception(f"Rate limit exceeded on {endpoint}. Please reduce request frequency.")

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
        self._websocket = None
        self._ws_lock = threading.Lock()
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

    def close(self):
        """Close the WebSocket connection and release resources."""
        with self._ws_lock:
            if self._websocket:
                try:
                    self._websocket.close()
                except Exception:
                    pass
                self._websocket = None

    def __del__(self):
        """Safety net destructor to ensure WebSocket is cleaned up."""
        try:
            self.close()
        except Exception:
            pass

    def get_websocket(self, force_new=False):
        """
        Get or create the Nubra WebSocket instance for real-time data.

        Args:
            force_new: Force creation of a new connection

        Returns:
            NubraWebSocket instance or None if creation fails
        """
        with self._ws_lock:
            # Check if existing connection is valid
            if not force_new and self._websocket and self._websocket.is_connected:
                return self._websocket

            try:
                if not self.auth_token:
                    logger.error("Auth token not available for WebSocket")
                    return None

                # Clean up existing connection
                if self._websocket:
                    try:
                        self._websocket.close()
                    except Exception:
                        pass

                logger.info("Creating new Nubra WebSocket connection")
                ws = NubraWebSocket(self.auth_token)
                ws.connect()

                # Wait for connection via event (more efficient than polling)
                ws._connected_event.wait(timeout=10)

                if not ws.is_connected:
                    logger.warning("Nubra WebSocket connection timed out")
                    try:
                        ws.close()
                    except Exception:
                        pass
                    return None

                self._websocket = ws
                logger.info("Nubra WebSocket connected successfully")
                return self._websocket

            except Exception as e:
                logger.error(f"Error creating Nubra WebSocket: {e}")
                return None

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol.
        
        Strategy:
        1. Try WebSocket index channel first (works for indices AND instruments)
        2. Fall back to REST API /orderbooks/{ref_id} for instruments
        3. Return zeros if nothing works (e.g. index with no WS)
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX)
        Returns:
            dict: Quote data with required fields
        """
        try:
            # --- Attempt 1: WebSocket index channel ---
            ws_quote = self._get_quotes_via_websocket(symbol, exchange)
            if ws_quote:
                return ws_quote

            # --- Attempt 2: REST API (only for non-index symbols) ---
            if not exchange.endswith('_INDEX'):
                rest_quote = self._get_quotes_via_rest(symbol, exchange)
                if rest_quote:
                    return rest_quote

            # --- Fallback: return zeros ---
            logger.info(f"No quote data available for {symbol} on {exchange}")
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

        except Exception as e:
            logger.error(f"Error fetching quotes for {symbol} on {exchange}: {str(e)}")
            raise Exception(f"Error fetching quotes: {str(e)}")

    def _get_quotes_via_websocket(self, symbol: str, exchange: str) -> dict:
        """
        Try to get quotes via WebSocket channels.

        For indices: subscribes to OHLCV channel.
        For instruments: subscribes to BOTH index and orderbook channels in
        parallel, waits once, then checks both — eliminating the double
        subscribe/wait cycle that previously added ~5s latency.

        Uses try/finally to guarantee unsubscribe even on exceptions.

        Returns:
            dict: Quote data in OpenAlgo format, or None if not available
        """
        websocket = None
        subscribed_type = None  # Track what we subscribed to for cleanup
        br_symbol = None
        ws_exchange = None
        token_int = None
        orderbook_subscribed = False

        try:
            websocket = self.get_websocket()
            if not websocket or not websocket.is_connected:
                logger.debug("WebSocket not available, skipping WS quotes")
                return None

            # Determine the broker symbol and WS exchange
            br_symbol = get_br_symbol(symbol, exchange) or symbol
            if exchange == "NSE_INDEX":
                ws_exchange = "NSE"
            elif exchange == "BSE_INDEX":
                ws_exchange = "BSE"
            elif exchange in ("NFO", "CDS"):
                ws_exchange = "NSE"
            elif exchange == "BFO":
                ws_exchange = "BSE"
            else:
                ws_exchange = exchange

            is_index_request = exchange.endswith("_INDEX")

            if is_index_request:
                logger.info(f"Subscribing to WS OHLVC (1m) for {br_symbol} on {ws_exchange}")
                success = websocket.subscribe_ohlcv([br_symbol], "1m", ws_exchange)
                if success:
                    subscribed_type = "ohlcv"
            else:
                logger.info(f"Subscribing to WS index for {br_symbol} on {ws_exchange}")
                success = websocket.subscribe_index([br_symbol], ws_exchange)
                if success:
                    subscribed_type = "index"

                # Also subscribe to orderbook + greeks in parallel as fallback
                # (avoids a second subscribe/wait cycle if index channel yields no data)
                token = get_token(symbol, exchange)
                if token and str(token).isdigit():
                    token_int = int(token)
                    if websocket.subscribe_orderbook([token_int]):
                        websocket.change_orderbook_depth(5)
                        websocket.subscribe_greeks([token_int])
                        orderbook_subscribed = True

            if not success:
                return None

            # Single wait for all channels to deliver data
            time.sleep(2.0)

            # Check index/OHLCV channel first
            quote = websocket.get_quote(ws_exchange, br_symbol)

            if quote and quote.get("ltp", 0) > 0:
                logger.info(f"WS quote for {symbol}: LTP={quote['ltp']}")
                return {
                    "bid": float(quote.get("bid", 0)),
                    "ask": float(quote.get("ask", 0)),
                    "open": float(quote.get("open", 0)),
                    "high": float(quote.get("high", 0)),
                    "low": float(quote.get("low", 0)),
                    "ltp": float(quote.get("ltp", 0)),
                    "prev_close": float(quote.get("prev_close", 0)),
                    "volume": int(quote.get("volume", 0)),
                    "oi": int(quote.get("volume_oi", 0)),
                }

            # Check orderbook channel (already subscribed in parallel for instruments)
            if orderbook_subscribed and token_int is not None:
                depth = websocket.get_market_depth(token_int)
                if depth and depth.get("ltp", 0) > 0:
                    logger.info(f"WS quote (via depth) for {symbol}: LTP={depth['ltp']}")
                    best_bid = depth["bids"][0]["price"] if depth.get("bids") else 0
                    best_ask = depth["asks"][0]["price"] if depth.get("asks") else 0

                    return {
                        "bid": best_bid,
                        "ask": best_ask,
                        "open": float(depth.get("open", 0)),
                        "high": float(depth.get("high", 0)),
                        "low": float(depth.get("low", 0)),
                        "ltp": float(depth.get("ltp", 0)),
                        "prev_close": float(depth.get("prev_close", 0)),
                        "volume": int(depth.get("volume", 0)),
                        "oi": int(depth.get("oi", 0)),
                    }

            logger.debug(f"No WS quote data for {symbol} (checked index and orderbook)")
            return None

        except Exception as e:
            logger.warning(f"WebSocket quote failed for {symbol}: {e}")
            return None

        finally:
            # Guarantee unsubscribe even on exceptions
            if websocket:
                try:
                    if subscribed_type == "ohlcv" and br_symbol and ws_exchange:
                        websocket.unsubscribe_ohlcv([br_symbol], "1m", ws_exchange)
                    elif subscribed_type == "index" and br_symbol and ws_exchange:
                        websocket.unsubscribe_index([br_symbol], ws_exchange)
                    if orderbook_subscribed and token_int is not None:
                        websocket.unsubscribe_orderbook([token_int])
                        websocket.unsubscribe_greeks([token_int])
                except Exception:
                    pass

    def _get_quotes_via_rest(self, symbol: str, exchange: str) -> dict:
        """
        Get quotes via Nubra's REST orderbooks API.
        Original REST implementation preserved as fallback.
        
        Nubra API: GET /orderbooks/{ref_id}?levels=1
        
        Note: Nubra's orderbook API requires numeric ref_id. Index symbols 
        don't have ref_id in Nubra's API, so quotes are not available for indices.
        
        Returns:
            dict: Quote data in OpenAlgo format, or None if failed
        """
        try:
            # Indices not supported by REST orderbook API
            if exchange.endswith('_INDEX'):
                return None

            # Get token (ref_id) for the symbol
            token = get_token(symbol, exchange)
            
            if not token:
                logger.warning(f"Could not find token for symbol {symbol} on {exchange}")
                return None

            # Verify token is numeric (ref_id)
            if not str(token).isdigit():
                logger.warning(f"Invalid token '{token}' for {symbol}. REST API requires numeric ref_id.")
                return None

            logger.info(f"Fetching REST quotes for {symbol} on {exchange} with token {token}")

            # Call Nubra's orderbooks API with 1 level of depth for quotes
            response = get_api_response(
                f"/orderbooks/{token}?levels=1", self.auth_token, "GET"
            )
            
            # Extract orderBook data from response
            orderbook = response.get("orderBook", {})
            
            if not orderbook:
                logger.warning(f"Empty orderbook response for {symbol} on {exchange}")
                return None

            # Parse bid/ask from arrays
            # Prices are in paise, need to convert to rupees (divide by 100)
            bids = orderbook.get("bid", [])
            asks = orderbook.get("ask", [])
            
            bid_price = float(bids[0].get("p", 0)) / 100 if bids else 0
            ask_price = float(asks[0].get("p", 0)) / 100 if asks else 0
            ltp = float(orderbook.get("ltp", 0)) / 100

            return {
                "bid": bid_price,
                "ask": ask_price,
                "open": float(orderbook.get("open", 0)) / 100,
                "high": float(orderbook.get("high", 0)) / 100,
                "low": float(orderbook.get("low", 0)) / 100,
                "ltp": ltp,
                "prev_close": float(orderbook.get("prev_close", 0)) / 100,
                "volume": int(orderbook.get("volume", 0)),
                "oi": int(orderbook.get("oi", 0)),
            }

        except Exception as e:
            # Propagate authentication errors
            if "Authentication failed" in str(e):
                raise
            
            logger.error(f"REST quote error for {symbol} on {exchange}: {str(e)}")
            return None

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols using batch WebSocket subscriptions.

        Instead of subscribing/waiting/unsubscribing per symbol (2s+ each), this method
        batch-subscribes ALL symbols at once, waits a single 2s window, then retrieves
        all cached data. Falls back to REST for any symbols that didn't get WS data.
        Uses try/finally to guarantee batch unsubscribe even on exceptions.

        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        websocket = None
        all_tokens = []
        index_by_exchange = {}

        try:
            websocket = self.get_websocket()
            if not websocket or not websocket.is_connected:
                logger.info("WebSocket not available, using REST fallback for multiquotes")
                return self._get_multiquotes_sequential(symbols)

            results = []
            failed_symbols = []

            # Classify symbols: orderbook (instruments) vs OHLCV (indices)
            orderbook_items = []  # (symbol, exchange, token_int)
            index_items = []      # (symbol, exchange, br_symbol, ws_exchange)

            for item in symbols:
                symbol = item["symbol"]
                exchange = item["exchange"]

                if exchange.endswith("_INDEX"):
                    br_symbol = get_br_symbol(symbol, exchange) or symbol
                    ws_exchange = "NSE" if exchange == "NSE_INDEX" else "BSE"
                    index_items.append((symbol, exchange, br_symbol, ws_exchange))
                else:
                    token = get_token(symbol, exchange)
                    if token and str(token).isdigit():
                        orderbook_items.append((symbol, exchange, int(token)))
                    else:
                        failed_symbols.append(item)

            # --- Batch subscribe orderbook + greeks (instruments) ---
            all_tokens = [t[2] for t in orderbook_items]
            if all_tokens:
                websocket.subscribe_orderbook(all_tokens)
                websocket.change_orderbook_depth(5)
                websocket.subscribe_greeks(all_tokens)
                logger.info(f"Batch subscribed {len(all_tokens)} orderbook+greeks tokens")

            # --- Batch subscribe OHLCV (indices) ---
            for symbol, exchange, br_symbol, ws_exchange in index_items:
                index_by_exchange.setdefault(ws_exchange, []).append((symbol, exchange, br_symbol))

            for ws_exchange, syms in index_by_exchange.items():
                br_syms = [s[2] for s in syms]
                websocket.subscribe_ohlcv(br_syms, "1m", ws_exchange)

            # --- Single wait for all data to arrive ---
            time.sleep(2.0)

            # --- Collect orderbook results ---
            for symbol, exchange, token_int in orderbook_items:
                depth = websocket.get_market_depth(token_int)
                if depth and depth.get("ltp", 0) > 0:
                    best_bid = depth["bids"][0]["price"] if depth.get("bids") else 0
                    best_ask = depth["asks"][0]["price"] if depth.get("asks") else 0
                    results.append({
                        "symbol": symbol,
                        "exchange": exchange,
                        "data": {
                            "bid": best_bid,
                            "ask": best_ask,
                            "open": float(depth.get("open", 0)),
                            "high": float(depth.get("high", 0)),
                            "low": float(depth.get("low", 0)),
                            "ltp": float(depth.get("ltp", 0)),
                            "prev_close": float(depth.get("prev_close", 0)),
                            "volume": int(depth.get("volume", 0)),
                            "oi": int(depth.get("oi", 0)),
                        }
                    })
                else:
                    failed_symbols.append({"symbol": symbol, "exchange": exchange})

            # --- Collect index results ---
            for ws_exchange, syms in index_by_exchange.items():
                for symbol, exchange, br_symbol in syms:
                    quote = websocket.get_quote(ws_exchange, br_symbol)
                    if quote and quote.get("ltp", 0) > 0:
                        results.append({
                            "symbol": symbol,
                            "exchange": exchange,
                            "data": {
                                "bid": float(quote.get("bid", 0)),
                                "ask": float(quote.get("ask", 0)),
                                "open": float(quote.get("open", 0)),
                                "high": float(quote.get("high", 0)),
                                "low": float(quote.get("low", 0)),
                                "ltp": float(quote.get("ltp", 0)),
                                "prev_close": float(quote.get("prev_close", 0)),
                                "volume": int(quote.get("volume", 0)),
                                "oi": int(quote.get("volume_oi", 0)),
                            }
                        })
                    else:
                        failed_symbols.append({"symbol": symbol, "exchange": exchange})

            # --- REST fallback for any symbols that didn't get WS data ---
            if failed_symbols:
                logger.info(f"Batch WS: {len(failed_symbols)}/{len(symbols)} symbols need REST fallback")
                for item in failed_symbols:
                    sym = item["symbol"]
                    exch = item["exchange"]
                    try:
                        rest_quote = self._get_quotes_via_rest(sym, exch) if not exch.endswith("_INDEX") else None
                        results.append({
                            "symbol": sym,
                            "exchange": exch,
                            "data": rest_quote or {
                                "bid": 0, "ask": 0, "open": 0, "high": 0,
                                "low": 0, "ltp": 0, "prev_close": 0, "volume": 0, "oi": 0,
                            }
                        })
                    except Exception as e:
                        logger.warning(f"REST fallback failed for {sym}: {e}")
                        results.append({
                            "symbol": sym,
                            "exchange": exch,
                            "data": {
                                "bid": 0, "ask": 0, "open": 0, "high": 0,
                                "low": 0, "ltp": 0, "prev_close": 0, "volume": 0, "oi": 0,
                            }
                        })

            logger.info(f"Batch multiquotes: {len(results)} results for {len(symbols)} symbols")
            return results

        except Exception as e:
            logger.exception("Error fetching multiquotes (batch)")
            raise Exception(f"Error fetching multiquotes: {e}")

        finally:
            # Guarantee batch unsubscribe even on exceptions
            if websocket:
                try:
                    if all_tokens:
                        websocket.unsubscribe_orderbook(all_tokens)
                        websocket.unsubscribe_greeks(all_tokens)
                    for ws_exchange, syms in index_by_exchange.items():
                        br_syms = [s[2] for s in syms]
                        websocket.unsubscribe_ohlcv(br_syms, "1m", ws_exchange)
                except Exception:
                    pass

    def _get_multiquotes_sequential(self, symbols: list) -> list:
        """
        Fallback: fetch quotes one-by-one when WebSocket is not available.
        Uses REST API with thread pool for concurrency.
        """
        import concurrent.futures

        results = []

        def fetch_single_quote(item):
            symbol = item["symbol"]
            exchange = item["exchange"]
            try:
                quote_data = self.get_quotes(symbol, exchange)
                return {"symbol": symbol, "exchange": exchange, "data": quote_data}
            except Exception as e:
                logger.warning(f"Failed to fetch quote for {symbol}: {e}")
                return {"symbol": symbol, "exchange": exchange, "error": str(e)}

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_symbol = {executor.submit(fetch_single_quote, item): item for item in symbols}
            for future in concurrent.futures.as_completed(future_to_symbol):
                try:
                    results.append(future.result())
                except Exception as e:
                    logger.error(f"Generate quote exception: {e}")

        return results

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
        
        Data is fetched in chunks based on interval:
        - Intraday (1s to 1h): 30-day chunks (API limit: 3 months)
        - Daily: 365-day chunks (API limit: 10 years)
        - Weekly/Monthly: 1000-day chunks (API limit: 10 years)
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX)
            interval: Candle interval (1s, 1m, 2m, 3m, 5m, 15m, 30m, 1h, D, W, M)
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
            # Nubra only supports: NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX
            # For NFO/BFO, Nubra expects exchange=NSE/BSE with type=FUT/OPT
            if exchange == "NSE_INDEX":
                instrument_type = "INDEX"
                api_exchange = "NSE"
            elif exchange == "BSE_INDEX":
                instrument_type = "INDEX"
                api_exchange = "BSE"
            elif exchange == "NFO":
                # NFO maps to NSE with FUT/OPT type
                if "CE" in symbol or "PE" in symbol:
                    instrument_type = "OPT"
                else:
                    instrument_type = "FUT"
                api_exchange = "NSE"  # Nubra expects NSE for F&O
            elif exchange == "BFO":
                # BFO maps to BSE with FUT/OPT type
                if "CE" in symbol or "PE" in symbol:
                    instrument_type = "OPT"
                else:
                    instrument_type = "FUT"
                api_exchange = "BSE"  # Nubra expects BSE for F&O
            elif exchange in ["NSE", "BSE"]:
                instrument_type = "STOCK"
                api_exchange = exchange
            else:
                raise Exception(f"Exchange '{exchange}' is not supported by Nubra. Supported exchanges: NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX")

            # Convert dates to datetime objects
            from_date = pd.to_datetime(start_date)
            to_date = pd.to_datetime(end_date)

            # Set chunk size based on interval
            # Nubra limits: intraday = 3 months, daily+ = 10 years
            chunk_limits = {
                "1s": 7,      # 7 days for second data
                "1m": 30,     # 30 days for minute data
                "2m": 30,
                "3m": 60,
                "5m": 60,
                "15m": 60,
                "30m": 90,
                "1h": 90,     # 90 days for hourly
                "D": 365,     # 1 year chunks for daily
                "W": 1000,    # ~3 years for weekly
                "M": 1500,    # ~4 years for monthly
            }
            chunk_days = chunk_limits.get(interval, 30)

            # Initialize list to store all candle data
            all_candles = {}

            # Process data in chunks
            current_start = from_date
            while current_start <= to_date:
                # Calculate chunk end date
                current_end = min(current_start + timedelta(days=chunk_days - 1), to_date)

                # Set start time to market open (09:15 IST -> 03:45 UTC)
                chunk_start = current_start.replace(hour=3, minute=45, second=0, microsecond=0)
                
                # Set end time
                current_time = pd.Timestamp.now()
                if current_end.date() == current_time.date():
                    # Convert current IST to approximate UTC
                    chunk_end = current_time - pd.Timedelta(hours=5, minutes=30)
                else:
                    # For past dates, set end time to market close (15:30 IST -> 10:00 UTC)
                    chunk_end = current_end.replace(hour=10, minute=0, second=0, microsecond=0)

                # Format dates as ISO strings
                start_iso = chunk_start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                end_iso = chunk_end.strftime("%Y-%m-%dT%H:%M:%S.000Z")

                logger.debug(f"Debug - Fetching chunk from {start_iso} to {end_iso}")

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

                try:
                    # Make API call to Nubra's timeseries endpoint
                    response = get_api_response(
                        "/charts/timeseries",
                        self.auth_token,
                        "POST",
                        payload,
                    )

                    logger.debug(f"Nubra timeseries raw response: {json.dumps(response, indent=2) if isinstance(response, dict) else response}")

                    # Parse response
                    if response and response.get("message") == "charts":
                        result = response.get("result", [])
                        if result:
                            values_array = result[0].get("values", [])
                            symbol_data = None
                            for val in values_array:
                                if br_symbol in val:
                                    symbol_data = val[br_symbol]
                                    break

                            if symbol_data:
                                # Extract OHLCV arrays
                                open_data = symbol_data.get("open", [])
                                high_data = symbol_data.get("high", [])
                                low_data = symbol_data.get("low", [])
                                close_data = symbol_data.get("close", [])
                                volume_data = symbol_data.get("tick_volume", []) or symbol_data.get("cumulative_volume", [])

                                # Process each field and merge into all_candles
                                for item in open_data:
                                    ts = item.get("ts", 0)
                                    if ts not in all_candles:
                                        all_candles[ts] = {"timestamp": ts, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}
                                    all_candles[ts]["open"] = float(item.get("v", 0)) / 100

                                for item in high_data:
                                    ts = item.get("ts", 0)
                                    if ts not in all_candles:
                                        all_candles[ts] = {"timestamp": ts, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}
                                    all_candles[ts]["high"] = float(item.get("v", 0)) / 100

                                for item in low_data:
                                    ts = item.get("ts", 0)
                                    if ts not in all_candles:
                                        all_candles[ts] = {"timestamp": ts, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}
                                    all_candles[ts]["low"] = float(item.get("v", 0)) / 100

                                for item in close_data:
                                    ts = item.get("ts", 0)
                                    if ts not in all_candles:
                                        all_candles[ts] = {"timestamp": ts, "open": 0, "high": 0, "low": 0, "close": 0, "volume": 0}
                                    all_candles[ts]["close"] = float(item.get("v", 0)) / 100

                                for item in volume_data:
                                    ts = item.get("ts", 0)
                                    if ts in all_candles:
                                        all_candles[ts]["volume"] = int(item.get("v", 0))

                                logger.debug(f"Debug - Chunk received {len(close_data)} candles")

                except Exception as chunk_error:
                    logger.error(f"Debug - Error fetching chunk {current_start} to {current_end}: {str(chunk_error)}")

                # Move to next chunk
                current_start = current_end + timedelta(days=1)

                # Rate limit: 60 req/min = 1 req/sec (Nubra historical data limit)
                if current_start <= to_date:
                    time.sleep(1.0)

            # If no data was found, return empty DataFrame
            if not all_candles:
                logger.debug("Debug - No data received from API")
                return pd.DataFrame(columns=["close", "high", "low", "open", "timestamp", "volume", "oi"])

            # Convert dictionary to list and sort by timestamp
            candles = list(all_candles.values())
            candles.sort(key=lambda x: x["timestamp"])

            # Create DataFrame
            df = pd.DataFrame(candles)

            # Convert nanosecond timestamp to datetime
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
        Get market depth for given symbol.
        
        Strategy:
        1. Try WebSocket orderbook channel first (works for instruments)
        2. Fall back to REST API /orderbooks/{ref_id}?levels=5
        3. Return zeros for indices (no depth available)
        
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX)
        Returns:
            dict: Market depth data with bids, asks and other details
        """
        try:
            # --- Attempt 1: WebSocket orderbook channel (non-index only) ---
            if not exchange.endswith('_INDEX'):
                ws_depth = self._get_depth_via_websocket(symbol, exchange)
                if ws_depth:
                    return ws_depth

                # --- Attempt 2: REST API fallback ---
                rest_depth = self._get_depth_via_rest(symbol, exchange)
                if rest_depth:
                    return rest_depth

            # --- Fallback: return zeros (indices or no data) ---
            if exchange.endswith('_INDEX'):
                logger.info(f"Index depth not available for {symbol} on {exchange}")
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

        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")

    def _get_depth_via_websocket(self, symbol: str, exchange: str) -> dict:
        """
        Try to get market depth via WebSocket orderbook channel.
        Uses try/finally to guarantee unsubscribe even on exceptions.

        Returns:
            dict: Depth data in OpenAlgo format, or None if not available
        """
        websocket = None
        token_int = None
        subscribed = False

        try:
            websocket = self.get_websocket()
            if not websocket or not websocket.is_connected:
                logger.debug("WebSocket not available, skipping WS depth")
                return None

            # Get token (ref_id) for orderbook subscription
            token = get_token(symbol, exchange)
            if not token or not str(token).isdigit():
                logger.debug(f"No numeric token for {symbol}, can't use WS orderbook")
                return None

            token_int = int(token)
            logger.info(f"Subscribing to WS orderbook+greeks for token {token_int}")
            success = websocket.subscribe_orderbook([token_int])
            if not success:
                return None
            subscribed = True

            # Set orderbook depth (required to activate data flow, per SDK pattern)
            websocket.change_orderbook_depth(5)
            websocket.subscribe_greeks([token_int])

            # Poll for data (check every 0.5s, up to 5s)
            depth = None
            for _ in range(10):
                time.sleep(0.5)
                depth = websocket.get_market_depth(token_int)
                if depth and depth.get("ltp", 0) > 0:
                    break

            if depth and depth.get("ltp", 0) > 0:
                logger.info(f"WS depth for {symbol}: LTP={depth['ltp']}")

                bids = depth.get("bids", [{"price": 0, "quantity": 0}] * 5)
                asks = depth.get("asks", [{"price": 0, "quantity": 0}] * 5)

                formatted_bids = [{"price": float(b.get("price", 0)), "quantity": int(b.get("quantity", 0))} for b in bids[:5]]
                formatted_asks = [{"price": float(a.get("price", 0)), "quantity": int(a.get("quantity", 0))} for a in asks[:5]]

                return {
                    "bids": formatted_bids,
                    "asks": formatted_asks,
                    "high": float(depth.get("high", 0)),
                    "low": float(depth.get("low", 0)),
                    "ltp": float(depth.get("ltp", 0)),
                    "ltq": int(depth.get("ltq", 0)),
                    "open": float(depth.get("open", 0)),
                    "prev_close": float(depth.get("prev_close", 0)),
                    "volume": int(depth.get("volume", 0)),
                    "oi": int(depth.get("oi", 0)),
                    "totalbuyqty": int(depth.get("totalbuyqty", 0)),
                    "totalsellqty": int(depth.get("totalsellqty", 0)),
                }

            logger.debug(f"No WS depth data for {symbol}")
            return None

        except Exception as e:
            logger.warning(f"WebSocket depth failed for {symbol}: {e}")
            return None

        finally:
            # Guarantee unsubscribe even on exceptions
            if websocket and subscribed and token_int is not None:
                try:
                    websocket.unsubscribe_orderbook([token_int])
                    websocket.unsubscribe_greeks([token_int])
                except Exception:
                    pass

    def _get_depth_via_rest(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth via Nubra's REST orderbooks API.
        Original REST implementation preserved as fallback.
        
        Nubra API: GET /orderbooks/{ref_id}?levels=5
        
        Returns:
            dict: Depth data in OpenAlgo format, or None if failed
        """
        try:
            if exchange.endswith('_INDEX'):
                return None

            token = get_token(symbol, exchange)
            
            if not token:
                logger.warning(f"Could not find token for symbol {symbol} on {exchange}")
                return None

            if not str(token).isdigit():
                logger.warning(f"Invalid token '{token}' for {symbol}. REST requires numeric ref_id.")
                return None

            logger.info(f"Fetching REST depth for {symbol} on {exchange} with token {token}")

            response = get_api_response(
                f"/orderbooks/{token}?levels=5", self.auth_token, "GET"
            )

            logger.debug(f"Nubra REST depth raw response: {json.dumps(response, indent=2) if isinstance(response, dict) else response}")

            orderbook = response.get("orderBook", {})
            if not orderbook:
                logger.warning(f"Empty orderbook response for {symbol}. Raw: {str(response)[:200]}")
                return None

            # Parse bid/ask from arrays
            # Nubra format: {"p": price in paise, "q": quantity, "o": num_orders}
            bid_orders = orderbook.get("bid", [])
            ask_orders = orderbook.get("ask", [])
            
            bids = []
            asks = []

            for i in range(5):
                if i < len(bid_orders):
                    bid = bid_orders[i]
                    bids.append({
                        "price": float(bid.get("p", 0)) / 100,
                        "quantity": int(bid.get("q", 0))
                    })
                else:
                    bids.append({"price": 0, "quantity": 0})

            for i in range(5):
                if i < len(ask_orders):
                    ask = ask_orders[i]
                    asks.append({
                        "price": float(ask.get("p", 0)) / 100,
                        "quantity": int(ask.get("q", 0))
                    })
                else:
                    asks.append({"price": 0, "quantity": 0})

            totalbuyqty = sum(bid.get("q", 0) for bid in bid_orders)
            totalsellqty = sum(ask.get("q", 0) for ask in ask_orders)
            
            ltp = float(orderbook.get("ltp", 0)) / 100
            ltq = int(orderbook.get("ltq", 0))
            volume = int(orderbook.get("volume", 0))

            return {
                "bids": bids,
                "asks": asks,
                "high": float(orderbook.get("high", 0)) / 100,
                "low": float(orderbook.get("low", 0)) / 100,
                "ltp": ltp,
                "ltq": ltq,
                "open": float(orderbook.get("open", 0)) / 100,
                "prev_close": float(orderbook.get("prev_close", 0)) / 100,
                "volume": volume,
                "oi": int(orderbook.get("oi", 0)),
                "totalbuyqty": totalbuyqty,
                "totalsellqty": totalsellqty,
            }

        except Exception as e:
            logger.error(f"REST depth error for {symbol} on {exchange}: {str(e)}")
            return None

    def get_intervals(self) -> list:
        """
        Get list of supported intervals for historical data.
        
        Based on Nubra API: 1s, 1m, 2m, 3m, 5m, 15m, 30m, 1h, 1d, 1w
        OpenAlgo supported: 1m, 3m, 5m, 15m, 30m, 1h, D
        
        Returns:
            list: List of supported interval strings
        """
        return list(self.timeframe_map.keys())


