import base64
import json
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
import pandas as pd

from broker.aliceblue.api.rate_limiter import apply_rate_limit
from database.auth_db import Auth
from database.token_db import get_br_symbol, get_brexchange, get_oa_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

from .alicebluewebsocket import AliceBlueWebSocket

logger = get_logger(__name__)

# AliceBlue V3 API URLs
BASE_URL = "https://a3.aliceblueonline.com/"
HISTORICAL_API_URL = BASE_URL + "open-api/od/ChartAPIService/api/chart/history"

# Live market-data WebSocket per broker session, shared across BrokerData
# instances. It has to live at module scope because quotes_service builds a new
# BrokerData for every request, so an instance attribute is always empty and the
# connection got rebuilt from scratch on each call. Keyed by session_id, so a
# re-login makes a new entry instead of reusing a socket authenticated with a
# dead token; bounded by the one broker session this instance can hold.
_WS_REGISTRY: dict = {}
_WS_REGISTRY_LOCK = threading.Lock()


def close_all_websockets():
    """Disconnect and drop every pooled market-data socket.

    For shutdown and for logout, where the session behind these connections is
    about to be revoked. Without it the sockets and their reader and heartbeat
    threads would outlive the session that authenticated them.
    """
    with _WS_REGISTRY_LOCK:
        sockets = list(_WS_REGISTRY.values())
        _WS_REGISTRY.clear()
    for ws in sockets:
        try:
            ws.disconnect()
        except Exception as exc:
            logger.warning(f"Error closing pooled AliceBlue WebSocket: {exc}")


class BrokerData:
    """
    BrokerData class for AliceBlue broker.
    Handles market data operations including quotes, market depth, and historical data.
    """

    # Timeframes that require resampling from 1-minute data
    _RESAMPLE_TIMEFRAMES = {
        "3m": 3,
        "5m": 5,
        "10m": 10,
        "15m": 15,
        "30m": 30,
        "1h": 60,
    }

    def __init__(self, auth_token=None):
        self.token_mapping = {}
        self.session_id = auth_token  # Store the session ID from authentication
        # AliceBlue natively supports 1-minute and daily data.
        # Other intraday timeframes are resampled from 1-minute data.
        self.timeframe_map = {
            "1m": "1",
            "3m": "1",   # resampled from 1m
            "5m": "1",   # resampled from 1m
            "10m": "1",  # resampled from 1m
            "15m": "1",  # resampled from 1m
            "30m": "1",  # resampled from 1m
            "1h": "1",   # resampled from 1m
            "D": "D",  # V3 API uses 'D' for daily (docs text says '1D' but API rejects it)
        }

    def get_websocket(self, force_new=False):
        """
        Get or create the global WebSocket instance.

        Args:
            force_new (bool): Force creation of a new WebSocket connection even if one exists

        Returns:
            AliceBlueWebSocket: WebSocket client instance or None if creation fails
        """
        # The live connection lives in a module-level registry, NOT on self.
        #
        # services/quotes_service.py constructs a fresh BrokerData per request,
        # so the old `self._websocket` cache could never hit: every quotes call
        # invalidated, recreated, reconnected and re-authenticated the whole
        # session. Measured 692ms of that churn wrapped around 64ms of actual
        # data, and it spent two REST calls (invalidateWsSess + createWsSess)
        # each time - against a documented budget of 1800 requests / 15 minutes
        # for everything except orders, an option chain polling every 5s burned
        # roughly a fifth of the quota producing nothing.
        #
        # Keyed by session_id so a re-login gets a fresh connection rather than
        # reusing one authenticated with a dead token. Bounded by definition:
        # OpenAlgo is single-user, single-broker per instance.
        if not self.session_id:
            logger.error("Session ID not available. Please login first.")
            return None

        if not force_new:
            with _WS_REGISTRY_LOCK:
                cached = _WS_REGISTRY.get(self.session_id)
            if cached is not None and cached.is_websocket_connected():
                return cached

        try:
            # Drop whatever was registered for this session before replacing it,
            # so a stale socket and its threads are not left behind.
            with _WS_REGISTRY_LOCK:
                stale = _WS_REGISTRY.pop(self.session_id, None)
            if stale is not None:
                try:
                    stale.disconnect()
                except Exception as e:
                    logger.warning(f"Error closing existing WebSocket: {str(e)}")

            # Get user ID (clientId/UCC) for WebSocket authentication
            auth_obj = Auth.query.filter_by(broker='aliceblue', is_revoked=False).first()
            user_id = auth_obj.user_id if auth_obj else None

            # Fallback: extract UCC from JWT token
            if not user_id and self.session_id:
                try:
                    payload_b64 = self.session_id.split(".")[1]
                    payload_b64 += "=" * (-len(payload_b64) % 4)
                    payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                    user_id = payload.get("ucc")
                    if user_id:
                        logger.info(f"Extracted UCC from JWT: {user_id}")
                except Exception as e:
                    logger.warning(f"Failed to extract UCC from JWT: {e}")

            if not user_id:
                logger.error("Missing user_id (clientId) for AliceBlue WebSocket. Please re-login.")
                return None

            # Create new websocket connection
            logger.info("Creating new WebSocket connection for AliceBlue")
            ws = AliceBlueWebSocket(user_id, self.session_id)
            ws.connect()

            # Wait for connection to establish. Poll at 50ms rather than 500ms:
            # the handshake completes in ~250ms live, so the coarse tick was
            # rounding every connect up to half a second.
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not ws.is_connected:
                time.sleep(0.05)

            if not ws.is_connected:
                logger.error("Failed to connect WebSocket within timeout")
                try:
                    ws.disconnect()
                except Exception:
                    pass
                return None

            # Register this session and evict any other. OpenAlgo is
            # single-user/single-broker, so a second session_id means the token
            # rolled over (AliceBlue expires it around 3am) and the previous
            # socket is authenticated with a dead one. Leaving it registered
            # would strand a socket plus its reader and heartbeat threads every
            # single day in a worker that never restarts.
            with _WS_REGISTRY_LOCK:
                superseded = [
                    (sid, sock) for sid, sock in _WS_REGISTRY.items() if sid != self.session_id
                ]
                for sid, _ in superseded:
                    del _WS_REGISTRY[sid]
                _WS_REGISTRY[self.session_id] = ws

            for _, sock in superseded:
                logger.info("Closing AliceBlue WebSocket for a superseded session")
                try:
                    sock.disconnect()
                except Exception as exc:
                    logger.warning(f"Error closing superseded WebSocket: {exc}")

            self._websocket = ws  # kept for callers that still read the attribute

            logger.info("WebSocket connection established successfully")
            return ws

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

    def _try_fetch_quote_via_ws(self, api_exchange: str, token: str, br_symbol: str, symbol: str, exchange: str) -> dict | None:
        """Attempt a single WebSocket quote fetch. Returns quote dict or None."""
        websocket = None
        instruments = None
        subscribed = False
        try:
            websocket = self.get_websocket()
            if not websocket or not websocket.is_connected:
                logger.warning("WebSocket not connected, reconnecting...")
                websocket = self.get_websocket(force_new=True)

            if not websocket or not websocket.is_connected:
                logger.error("WebSocket connection unavailable")
                return None

            class Instrument:
                def __init__(self, exchange, token, symbol=None):
                    self.exchange = exchange
                    self.token = token
                    self.symbol = symbol

            instrument = Instrument(exchange=api_exchange, token=token, symbol=br_symbol)
            instruments = [instrument]

            logger.info(f"Subscribing to {api_exchange}:{symbol} with token {token}")
            success = websocket.subscribe(instruments, is_depth=False)

            if not success:
                logger.warning(f"Subscribe failed for {symbol} on {exchange}")
                return None

            subscribed = True

            # Wait for data to arrive
            time.sleep(2.0)

            quote = websocket.get_quote(api_exchange, token)
            return quote

        except Exception as e:
            logger.warning(f"WebSocket quote attempt failed for {symbol}: {e}")
            return None
        finally:
            # Always unsubscribe to avoid dangling subscriptions
            if subscribed and websocket and instruments:
                try:
                    websocket.unsubscribe(instruments, is_depth=False)
                except Exception as unsub_err:
                    logger.warning(f"Failed to unsubscribe {symbol} on cleanup: {unsub_err}")

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol with retry logic.

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE', 'NIFTY')
            exchange: Exchange (e.g., NSE, BSE, NFO, NSE_INDEX, BSE_INDEX)

        Returns:
            dict: Quote data in OpenAlgo standard format
        """
        MAX_RETRIES = 2  # Total attempts (1 original + 1 retry)

        try:
            br_symbol = get_br_symbol(symbol, exchange) or symbol
            token = self._normalize_token(get_token(symbol, exchange))

            if not token:
                raise Exception(f"Token not found for {symbol} on {exchange}")

            api_exchange = self._map_exchange(exchange)

            # Attempt quote fetch with retry
            quote = None
            for attempt in range(1, MAX_RETRIES + 1):
                quote = self._try_fetch_quote_via_ws(api_exchange, token, br_symbol, symbol, exchange)
                if quote:
                    break
                if attempt < MAX_RETRIES:
                    logger.info(f"Retrying quote fetch for {symbol} (attempt {attempt + 1}/{MAX_RETRIES})")
                    # Force a fresh WebSocket connection on retry.
                    # get_websocket(force_new=True) cleanly disconnects the old
                    # instance before creating a new one.
                    self.get_websocket(force_new=True)
                    time.sleep(1.0)

            if not quote:
                raise Exception(f"No quote data received for {symbol} on {exchange} after {MAX_RETRIES} attempts")

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
        subscribed = False
        ws = None

        # Get WebSocket connection
        ws = self.get_websocket()
        if not ws or not ws.is_connected:
            logger.warning("WebSocket not connected, reconnecting...")
            ws = self.get_websocket(force_new=True)

        if not ws or not ws.is_connected:
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

        try:
            # Subscribe to all instruments at once with retry
            logger.info(f"Subscribing to {len(instruments)} symbols via WebSocket")
            success = ws.subscribe(instruments, is_depth=False)

            if not success:
                # Retry once with a fresh connection — update ws reference
                logger.warning("First subscription attempt failed, retrying with fresh connection...")
                ws = self.get_websocket(force_new=True)
                if ws and ws.is_connected:
                    success = ws.subscribe(instruments, is_depth=False)

            if not success:
                logger.error("Failed to send subscription request after retry")
                for key, info in symbol_map.items():
                    results.append(
                        {"symbol": info["symbol"], "exchange": info["exchange"], "error": "Subscription failed"}
                    )
                return skipped_symbols + results

            subscribed = True

            # Poll until every subscribed instrument has a quote, rather than
            # sleeping a fixed duration and hoping. The old code slept
            # min(max(n * 0.08, 2), 20) unconditionally - 6.4s for an 80-strike
            # option chain, and a full 2s even for 3 symbols whose ticks had
            # already arrived. The deadline below is that same worst case, so
            # nothing waits longer than before; the common case returns as soon
            # as the data is actually there.
            deadline_seconds = min(max(len(instruments) * 0.08, 2), 20)
            poll_interval = 0.05
            deadline = time.monotonic() + deadline_seconds
            expected = list(symbol_map.keys())

            while time.monotonic() < deadline:
                if all(ws.get_quote(*key.split(":")) for key in expected):
                    break
                time.sleep(poll_interval)

            waited = deadline_seconds - max(deadline - time.monotonic(), 0)
            logger.debug(
                f"Quote data for {len(instruments)} instruments after {waited:.2f}s "
                f"(deadline {deadline_seconds:.1f}s)"
            )

            # Helper to format a quote dict
            def _format_quote(q):
                return {
                    "bid": float(q.get("bid", 0)),
                    "ask": float(q.get("ask", 0)),
                    "open": float(q.get("open", 0)),
                    "high": float(q.get("high", 0)),
                    "low": float(q.get("low", 0)),
                    "ltp": float(q.get("ltp", 0)),
                    "prev_close": float(q.get("close", 0)),
                    "volume": int(q.get("volume", 0)),
                    "oi": int(q.get("open_interest", 0)),
                }

            # Collect results from WebSocket — first pass
            missing_keys = []
            for key, info in symbol_map.items():
                api_exchange, token = key.split(":")
                quote = ws.get_quote(api_exchange, token)

                if quote:
                    results.append(
                        {"symbol": info["symbol"], "exchange": info["exchange"], "data": _format_quote(quote)}
                    )
                else:
                    missing_keys.append(key)

            # Retry pass for symbols that didn't return data on first attempt
            if missing_keys:
                logger.info(f"{len(missing_keys)}/{len(symbol_map)} symbols missing after first pass, retrying...")
                # Same idea as the first pass: poll for the stragglers up to the
                # old fixed 3s rather than always burning it.
                straggler_deadline = time.monotonic() + 3.0
                while time.monotonic() < straggler_deadline:
                    if all(ws.get_quote(*key.split(":")) for key in missing_keys):
                        break
                    time.sleep(0.05)

                for key in missing_keys:
                    api_exchange, token = key.split(":")
                    info = symbol_map[key]
                    quote = ws.get_quote(api_exchange, token)

                    if quote:
                        results.append(
                            {"symbol": info["symbol"], "exchange": info["exchange"], "data": _format_quote(quote)}
                        )
                    else:
                        results.append(
                            {"symbol": info["symbol"], "exchange": info["exchange"], "error": "No data received"}
                        )

            received_count = len([r for r in results if 'data' in r])
            logger.info(
                f"Retrieved quotes for {received_count}/{len(symbol_map)} symbols"
            )
            return skipped_symbols + results

        finally:
            # Always unsubscribe to avoid dangling subscriptions
            if subscribed and ws and instruments:
                try:
                    logger.info(f"Unsubscribing from {len(instruments)} symbols")
                    ws.unsubscribe(instruments, is_depth=False)
                except Exception as unsub_err:
                    logger.warning(f"Failed to unsubscribe batch on cleanup: {unsub_err}")

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

            # CRITICAL: get_token() returns float-like values (e.g. '3045.0')
            # AliceBlue API requires clean integer tokens (e.g. '3045')
            try:
                token = str(int(float(token)))
            except (ValueError, TypeError):
                token = str(token)  # fallback to string as-is

            logger.debug(f"Found token {token} for {symbol}:{exchange}")

            # Convert exchange for AliceBlue API.
            #
            # Indices need a "::index" suffix on the exchange - "NSE::index",
            # not "NSE". Without it the chart API answers "No data available"
            # for every index token, on every exchange spelling, resolution and
            # date range, which is what made index history look like a broker
            # limitation (see #1776). It is not: the suffix is undocumented in
            # the REST reference but is what AliceBlue's own SDK sends, from
            # Ant-A3-tradehub-sdk-production TradeMaster/TradeSync.py:
            #
            #   "exchange": instrument.exchange if not indices
            #               else f"{instrument.exchange}::index"
            #
            # Verified live: NIFTY 50, NIFTY BANK, INDIA VIX, NIFTY FIN SERVICE,
            # NIFTY MIDCAP SELECT, SENSEX and BANKEX all return daily and 1m
            # candles, back 2 years.
            #
            # The suffix is index-only - "NSE::index" with an equity token
            # returns no data, exactly as "NSE" with an index token does.
            if exchange == "NSE_INDEX":
                exchange = "NSE::index"
            elif exchange == "BSE_INDEX":
                exchange = "BSE::index"
            elif exchange == "MCX_INDEX":
                # MCXENERGY and MCXMETAL return nothing either way, so this is
                # for consistency rather than data we have seen.
                exchange = "MCX::index"

            # Check for exchange limitations based on AliceBlue API documentation.
            #
            # BSE used to be blocked here alongside BCD. It should not have been:
            # probed against a live account, BSE serves history on every
            # timeframe (issue #1775, bug C).
            #
            #   BSE RELIANCE  D  365d -> 247 rows
            #   BSE RELIANCE  5m  30d -> 1621 rows
            #   BSE RELIANCE  1m   5d -> 1706 rows
            #
            # The block meant no BSE history anywhere - charts, /api/v1/history,
            # Historify, indicators - and it failed before issuing a request, so
            # nothing in the logs suggested the data was actually available.
            # BCD stays blocked; that one is genuinely unsupported.
            # BFO (BSE F&O) was already allowed through.
            if exchange == "BCD":
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
                    f"Unsupported timeframe: {timeframe}. AliceBlue supports: {', '.join(supported)}"
                )
                return pd.DataFrame()

            # Determine whether we need to resample from 1-minute data
            needs_resample = timeframe in self._RESAMPLE_TIMEFRAMES

            # Get the AliceBlue resolution format (always "1" for intraday, "D" for daily)
            aliceblue_timeframe = self.timeframe_map[timeframe]

            # V3 API auth: Bearer {session_token}
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


            # Convert timestamps to milliseconds as required by AliceBlue V3 API
            # V3 docs example: "from": "1660128489000" (13-digit milliseconds)
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
                                dt = dt.replace(hour=23, minute=59, second=59)
                            else:
                                # For daily data, start at midnight (00:00:00)
                                # For intraday data, start at market open (09:15:00)
                                if aliceblue_timeframe == "D":
                                    dt = dt.replace(hour=0, minute=0, second=0)
                                else:
                                    dt = dt.replace(hour=9, minute=15, second=0)

                        # Localize to IST timezone (AliceBlue expects IST timestamps)
                        dt_ist = ist.localize(dt)

                        # Convert to Unix timestamp in milliseconds
                        result = str(int(dt_ist.timestamp() * 1000))
                        logger.debug(f"Converted '{timestamp}' to {result} (Date: {dt_ist})")
                        return result
                    except (ValueError, Exception) as e:
                        logger.error(f"Error parsing timestamp string '{timestamp}': {e}")
                        logger.error(f"Timestamp type: {type(timestamp)}, value: {repr(timestamp)}")
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

            start_ts = convert_to_unix_ms(start_date, is_end_date=False)
            end_ts = convert_to_unix_ms(end_date, is_end_date=True)

            # Log the conversion for debugging
            logger.debug(
                f"Date conversion - Start: {start_date} -> {start_ts}, End: {end_date} -> {end_ts}"
            )

            # Validate that dates are not in the future
            current_time_ms = int(time.time() * 1000)
            if int(start_ts) > current_time_ms:
                logger.error(
                    f"Start date {start_date} is in the future. Historical data is only available for past dates."
                )
                return pd.DataFrame()

            # If end date is in future, cap it to current time
            if int(end_ts) > current_time_ms:
                logger.warning(f"End date {end_date} is in the future. Capping to current time.")
                end_ts = str(current_time_ms)

            # Daily needs a day boundary, not a wall-clock instant. Verified
            # against a live account - identical request, only "to" differs:
            #
            #   to = midnight            -> 246 rows
            #   to = now (intraday ms)   -> 0 rows, {"emsg": "No data available"}
            #
            # Same for BHEL and RELIANCE, so it is not symbol-specific. Because
            # the cap above rewrites "to" to the wall clock whenever the range
            # ends today, and virtually every real request ends today, daily
            # history came back empty for every cash symbol. Past-year ranges
            # worked only because their end date was already a past midnight,
            # which is what made this look like "AliceBlue refuses the current
            # calendar year" (issue #1775, bug A). It is not the year - it is
            # the time of day on the "to" timestamp.
            if timeframe == "D":
                day_boundary = int(
                    pd.Timestamp(int(end_ts), unit="ms").normalize().timestamp() * 1000
                )
                if day_boundary != int(end_ts):
                    # Round up to the following midnight so today's session is
                    # still inside the window.
                    end_ts = str(day_boundary + 86400000)

            # Ensure start and end times are different and valid
            if start_ts == end_ts:
                logger.warning(
                    f"Start and end timestamps are the same: {start_ts}. Adjusting end time."
                )
                # If they're the same, add one day to the end time
                end_ts = str(int(end_ts) + 86400000)  # Add 24 hours in milliseconds

            # For intraday data, ensure minimum time range
            if timeframe != "D":
                time_diff_ms = int(end_ts) - int(start_ts)
                min_range_ms = 3600000  # Minimum 1 hour for intraday data

                if time_diff_ms < min_range_ms:
                    logger.warning(
                        f"Time range too small ({time_diff_ms}ms). Extending to minimum 1 hour for intraday data."
                    )
                    end_ts = str(int(start_ts) + min_range_ms)

            # Prepare request payload according to AliceBlue V3 API docs
            payload = {
                "token": str(token),  # Token should be the instrument token
                "exchange": exchange,  # Exchange should be NSE, NFO, etc.
                "from": start_ts,
                "to": end_ts,
                "resolution": aliceblue_timeframe,
            }

            logger.debug(f"Historical API request: {symbol}:{exchange} res={aliceblue_timeframe} token={token} payload={payload}")

            # Make request to historical API
            client = get_httpx_client()
            try:
                # Historical data is a non-order request, so it draws on the
                # 1800/15min budget like quotes and books do.
                apply_rate_limit()
                response = client.post(HISTORICAL_API_URL, headers=headers, json=payload, timeout=15)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as http_err:
                logger.error(f"HTTP Error: {http_err}")
                logger.error(f"Response body: {http_err.response.text[:500]}")
                return pd.DataFrame()
            except Exception as req_err:
                logger.error(f"Request failed: {type(req_err).__name__}: {req_err}")
                return pd.DataFrame()

            # Check if response contains valid data
            if str(data.get("stat", "")).lower() in ["not_ok", "not ok"] or "result" not in data:
                error_msg = data.get("emsg", "Unknown error")
                logger.warning(f"Historical data response for {symbol}:{exchange}: {error_msg}")

                # Provide more helpful error messages based on the error
                if "No data available" in error_msg or "market time" in error_msg.lower() or "Session" in error_msg:
                    if exchange in ["MCX", "NFO", "CDS"]:
                        logger.error(
                            f"No data available. For {exchange}, AliceBlue only provides data for current expiry contracts."
                        )
                        logger.error(
                            f"Symbol '{symbol}' might be an expired contract or not a current expiry."
                        )
                    elif exchange == "BCD":
                        logger.error(
                            f"AliceBlue does not support historical data for {exchange} exchange yet."
                        )
                    else:
                        logger.error(f"No historical data available for {symbol} on {exchange}.")

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

            logger.debug(f"Received {len(df)} rows from AliceBlue for {symbol}:{exchange}")

            # Convert time column to datetime
            # AliceBlue returns time as string in format 'YYYY-MM-DD HH:MM:SS'
            df["timestamp"] = pd.to_datetime(df["timestamp"])

            # Handle different timeframes for timestamp conversion
            if timeframe == "D":
                # A daily bar is midnight IST. Localize to IST exactly as the
                # intraday branch below does, rather than adding 5:30 to a naive
                # value and letting pandas read it as UTC.
                #
                # The old form shifted the wrong way: normalize gave
                # 2026-08-03 00:00 naive, +5:30 made it 05:30, and casting to
                # int64 treated that as UTC. The SDK then handed back
                # "2026-08-03 05:30:00", tz-naive, where the same call at 1m
                # correctly returned "2026-08-07 09:15:00+05:30" as
                # datetime64[ns, Asia/Kolkata]. Daily was both offset and
                # missing its timezone, and inconsistent with intraday from the
                # same broker.
                import pytz as _pytz_daily

                _ist_daily = _pytz_daily.timezone("Asia/Kolkata")
                df["timestamp"] = df["timestamp"].dt.normalize()
                df["timestamp"] = df["timestamp"].dt.tz_localize(_ist_daily)
                df["timestamp"] = df["timestamp"].astype("int64") // 10**9
            else:
                # For intraday data, adjust timestamps to represent the start of the candle
                # AliceBlue provides end-of-candle timestamps (XX:XX:59), we need start (XX:XX:00)
                df["timestamp"] = df["timestamp"].dt.floor("min")

                # AliceBlue timestamps are in IST - localize them for correct epoch conversion
                import pytz
                ist = pytz.timezone("Asia/Kolkata")
                df["timestamp"] = df["timestamp"].dt.tz_localize(ist)

                # Convert to Unix epoch (seconds since 1970)
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

            # Add OI column with zeros — AliceBlue's historical API does NOT return OI.
            # This means OI Profile's "Daily OI Change" will show current OI as the
            # full change amount (since previous day OI always = 0).
            df["oi"] = 0

            # Return columns in the order matching Angel broker format
            df = df[["close", "high", "low", "open", "timestamp", "volume", "oi"]]

            # Resample to requested timeframe if needed
            if needs_resample:
                resample_minutes = self._RESAMPLE_TIMEFRAMES[timeframe]
                logger.info(f"Resampling 1m data to {timeframe} ({resample_minutes}m intervals)")
                try:
                    # Convert timestamp back to datetime for resampling
                    import pytz as _pytz2
                    _ist2 = _pytz2.timezone("Asia/Kolkata")
                    df["dt"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(_ist2)
                    df = df.set_index("dt")

                    resampled = df.resample(f"{resample_minutes}min", label="left", closed="left").agg(
                        {
                            "open": "first",
                            "high": "max",
                            "low": "min",
                            "close": "last",
                            "volume": "sum",
                            "oi": "last",
                        }
                    ).dropna(subset=["open"])

                    # Convert back to unix timestamps
                    resampled["timestamp"] = resampled.index.astype("int64") // 10**9
                    resampled = resampled.reset_index(drop=True)
                    df = resampled[["close", "high", "low", "open", "timestamp", "volume", "oi"]]
                    logger.info(f"Resampled to {len(df)} candles at {timeframe}")
                except Exception as resample_err:
                    logger.error(f"Resampling to {timeframe} failed: {resample_err}. Returning 1m data.")

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
