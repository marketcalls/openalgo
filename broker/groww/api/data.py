import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import httpx
import pandas as pd
import pytz

from broker.groww.api.order_api import _groww_error_message
from broker.groww.api.rate_limiter import groww_request
from database.token_db import get_br_symbol, get_oa_symbol, get_token
from database.token_db_enhanced import get_symbol_info
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)
# API endpoints are handled by the Groww SDK

# Exchange constants for Groww API
EXCHANGE_NSE = "NSE"  # Stock exchange code for NSE
EXCHANGE_BSE = "BSE"  # Stock exchange code for BSE

# Segment constants for Groww API
SEGMENT_CASH = "CASH"  # Segment code for Cash market
SEGMENT_FNO = "FNO"  # Segment code for F&O market


def get_api_response(
    endpoint, auth_token, method="GET", params=None, data=None, debug=False, category="live"
):
    """Make direct API requests to Groww endpoints

    This function directly calls Groww API endpoints using the shared httpx client
    with connection pooling for better performance.

    Args:
        endpoint (str): API endpoint (e.g., '/v1/quotes')
        auth_token (str): Authentication token
        method (str): HTTP method (GET, POST, etc.)
        params (dict): URL parameters for the API call
        data (dict): Request body data for POST/PUT requests
        debug (bool): Enable additional debugging

    Returns:
        dict: Response data from the Groww API
    """
    logger.info(f"Making direct API request to endpoint: {endpoint}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Ensure endpoint starts with a slash
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint

    # Build the full URL
    base_url = "https://api.groww.in"
    url = f"{base_url}{endpoint}"

    # Set up headers with authentication token
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {auth_token}",
        "X-API-VERSION": "1.0",
    }

    try:
        # Make the request based on the HTTP method
        if method.upper() in ("GET", "DELETE"):
            response = groww_request(client, method.upper(), url, category, headers=headers, params=params)
        elif method.upper() in ("POST", "PUT"):
            response = groww_request(client, method.upper(), url, category, headers=headers, json=data)
        else:
            logger.error(f"Unsupported HTTP method: {method}")
            return {"error": f"Unsupported HTTP method: {method}"}

        # Log request details if debug is enabled
        if debug:
            logger.debug(f"Request URL: {url}")
            logger.debug(f"Request params: {params}")

        # Check if the request was successful
        response.raise_for_status()

        # Parse the JSON response
        try:
            result = response.json()
            if debug:
                logger.debug(f"API Response: {result}")
            return result
        except ValueError:
            # Handle non-JSON responses
            logger.error("Response is not valid JSON")
            return {"error": "Response is not valid JSON", "content": response.text}
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
        return {"error": f"HTTP error: {e.response.status_code}", "details": e.response.text}
    except Exception as e:
        logger.error(f"Error in API request: {str(e)}")
        if debug:
            logger.exception("Detailed exception info:")
        return {"error": str(e)}


def _response_reason(response, fallback):
    """Groww's own reason for a failed get_api_response call, if it gave one."""
    if not isinstance(response, dict):
        return fallback
    details = response.get("details")
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except ValueError:
            details = None
    if isinstance(details, dict):
        reason = _groww_error_message(details, None)
        if reason:
            return reason
    return _groww_error_message(response, None) or fallback


class BrokerData:
    def __init__(self, auth_token):
        """Initialize Groww data handler with authentication token"""
        self.auth_token = auth_token
        # OpenAlgo interval -> Groww candle_interval (backtesting "Get Historical
        # Candle Data": 1minute ... 1month)
        self.timeframe_map = {
            "1m": "1minute",
            "2m": "2minute",
            "3m": "3minute",
            "5m": "5minute",
            "10m": "10minute",
            "15m": "15minute",
            "30m": "30minute",
            "1h": "1hour",
            "4h": "4hour",
            "D": "1day",
            "W": "1week",
        }

    def _convert_openalgo_to_groww_derivative_symbol(self, symbol):
        """
        Convert OpenAlgo NFO/BFO symbol format to Groww format

        Examples:
        - SBIN30SEP25FUT -> SBIN25SEPFUT
        - SBIN30SEP25800CE -> SBIN25SEP800CE
        """
        import re

        # Pattern for futures: SYMBOL + DAY + MONTH + YEAR + FUT
        fut_pattern = r"^([A-Z]+)(\d{2})([A-Z]{3})(\d{2})(FUT)$"
        fut_match = re.match(fut_pattern, symbol)
        if fut_match:
            base_symbol, day, month, year, fut = fut_match.groups()
            # Groww format: SYMBOL + YEAR + MONTH + FUT (no day)
            return f"{base_symbol}{year}{month}{fut}"

        # Pattern for options: SYMBOL + DAY + MONTH + YEAR + STRIKE + CE/PE
        opt_pattern = r"^([A-Z]+)(\d{2})([A-Z]{3})(\d{2})(\d+)(CE|PE)$"
        opt_match = re.match(opt_pattern, symbol)
        if opt_match:
            base_symbol, day, month, year, strike, opt_type = opt_match.groups()
            # Groww format: SYMBOL + YEAR + MONTH + STRIKE + CE/PE (no day)
            return f"{base_symbol}{year}{month}{strike}{opt_type}"

        # If no pattern matches, return original
        return symbol

    # Longest range one request may span, in days. Intraday uses the candles
    # endpoint (backtesting "Data Availability Limits": 1-5 min 30 days, 10-30
    # min 90 days, 1 hour+ 180 days); daily and weekly use candle/range
    # (historical-data: 1 day 1080 days, 1 week no limit).
    _MAX_DAYS = {
        "1minute": 30,
        "2minute": 30,
        "3minute": 30,
        "5minute": 30,
        "10minute": 90,
        "15minute": 90,
        "30minute": 90,
        "1hour": 180,
        "4hour": 180,
        "1440": 1080,
        "10080": 3650,
    }
    # Daily and weekly come from /v1/historical/candle/range. Its EOD candles
    # match NSE's bhavcopy; the candles endpoint's daily, weekly and monthly
    # candles leave open null on most days and can differ from NSE's close
    # (checked on RELIANCE, 1 Sep - 7 Oct 2026: 22 of 23 days had no open).
    # candle/range is marked deprecated, so these move once Groww fixes that.
    _EOD_MINUTES = {"D": "1440", "W": "10080"}
    # Length of each intraday candle, to tell a pre-open candle from one that
    # reaches into the regular session
    _INTERVAL_MINUTES = {
        "1minute": 1,
        "2minute": 2,
        "3minute": 3,
        "5minute": 5,
        "10minute": 10,
        "15minute": 15,
        "30minute": 30,
        "1hour": 60,
        "4hour": 240,
    }

    def _groww_symbol(self, symbol, exchange):
        """
        Groww symbol for an OpenAlgo symbol (backtesting "Groww Symbol Format").

        Stocks and indices are EXCHANGE-TRADINGSYMBOL (NSE-WIPRO, NSE-NIFTY).
        Futures are EXCHANGE-UNDERLYING-DDMonYY-FUT and options
        EXCHANGE-UNDERLYING-DDMonYY-STRIKE-CE/PE. Every CASH and FNO row of
        Groww's instrument file follows this, so it is built from the master
        contract instead of being stored. The underlying is the part of the
        OpenAlgo symbol before its expiry, which the master contract builds
        from Groww's underlying_symbol.

        Returns:
            tuple: (groww exchange, segment, groww symbol, trading symbol)
        """
        info = get_symbol_info(symbol, exchange)
        if info is None:
            raise ValueError(f"{symbol} is not in the {exchange} master contract")
        groww_exchange = info.brexchange or (
            "BSE" if exchange in ("BSE", "BFO", "BSE_INDEX") else "NSE"
        )

        if exchange not in ("NFO", "BFO"):
            return (
                groww_exchange,
                SEGMENT_CASH,
                f"{groww_exchange}-{info.brsymbol}",
                info.brsymbol,
            )

        match = re.match(r"^(.+?)(\d{2}[A-Z]{3}\d{2})(FUT|[\d.]+(CE|PE))$", info.symbol)
        if not match or not info.expiry:
            raise ValueError(
                f"{symbol} is not in OpenAlgo F&O format; download the master contract again"
            )
        underlying = match.group(1)
        expiry = datetime.strptime(info.expiry, "%d-%b-%y").strftime("%d%b%y")
        if info.instrumenttype == "FUT":
            groww_symbol = f"{groww_exchange}-{underlying}-{expiry}-FUT"
        else:
            strike = float(info.strike or 0)
            strike_str = str(int(strike)) if strike == int(strike) else str(strike)
            groww_symbol = f"{groww_exchange}-{underlying}-{expiry}-{strike_str}-{info.instrumenttype}"
        return groww_exchange, SEGMENT_FNO, groww_symbol, info.brsymbol

    # Intervals built from 15-minute candles (see get_history)
    _REBUCKETED = {"30minute", "1hour", "4hour"}

    @staticmethod
    def _rebucket(candles, minutes):
        """Combine 15-minute session candles into ``minutes``-long candles
        starting at 09:15 each day: first open, highest high, lowest low,
        last close, summed volume (None when Groww gave none, as for indices).
        """

        def pick(fn, a, b):
            return b if a is None else a if b is None else fn(a, b)

        buckets = {}
        for stamp, open_, high, low, close, volume in sorted(candles):
            market_open = stamp.replace(hour=9, minute=15, second=0, microsecond=0)
            offset = int((stamp - market_open).total_seconds() // 60) // minutes * minutes
            key = market_open + timedelta(minutes=offset)
            bucket = buckets.get(key)
            if bucket is None:
                buckets[key] = [key, open_, high, low, close, volume]
                continue
            bucket[2] = pick(max, bucket[2], high)
            bucket[3] = pick(min, bucket[3], low)
            bucket[4] = close
            bucket[5] = pick(lambda x, y: x + y, bucket[5], volume)
        return [tuple(bucket) for _, bucket in sorted(buckets.items())]

    @staticmethod
    def _to_date(value):
        """A datetime for a YYYY-MM-DD string, date or datetime."""
        if isinstance(value, str):
            return datetime.strptime(value, "%Y-%m-%d")
        if hasattr(value, "hour"):
            return value
        return datetime.combine(value, datetime.min.time())

    def _fetch_candles(self, symbol, path, params, start, end, max_days):
        """Every candle between start and end, one request per max_days chunk.

        Raises:
            ValueError: When Groww refuses a chunk; carries Groww's reason.
        """
        client = get_httpx_client()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.auth_token}",
            "X-API-VERSION": "1.0",
        }
        candles = []
        chunk_start = start
        while chunk_start.date() <= end.date():
            chunk_end = min(chunk_start + timedelta(days=max_days - 1), end)
            resp = groww_request(
                client,
                "GET",
                f"https://api.groww.in{path}",
                "history",
                headers=headers,
                params={
                    **params,
                    "start_time": f"{chunk_start:%Y-%m-%d} 00:00:00",
                    "end_time": f"{chunk_end:%Y-%m-%d} 23:59:59",
                },
                timeout=30,
            )
            try:
                body = resp.json()
            except ValueError:
                body = None
            if (
                resp.status_code != 200
                or not isinstance(body, dict)
                or body.get("status") != "SUCCESS"
            ):
                reason = _groww_error_message(body, f"HTTP {resp.status_code}")
                raise ValueError(f"Groww did not return history for {symbol}: {reason}")
            candles.extend((body.get("payload") or {}).get("candles") or [])
            chunk_start = chunk_end + timedelta(days=1)
        return candles

    def get_history(
        self, symbol: str, exchange: str, timeframe: str, start_time: str, end_time: str
    ) -> pd.DataFrame:
        """
        Historical candles for an OpenAlgo symbol.

        Intraday intervals come from GET /v1/historical/candles (backtesting
        docs), whose volume is per candle. Candles wholly inside the 09:00-09:15
        pre-open session are left out, so the day starts at 09:15; no other
        value is filled in or dropped. Its open-interest field is not used: on 2026-10-07 it summed
        the per-minute values over each candle and did not match Groww's quote.

        Daily and weekly come from GET /v1/historical/candle/range (see
        _EOD_MINUTES for why), stamped at midnight UTC of their date as
        before. Intraday timestamps are the IST candle start in epoch seconds.

        Args:
            symbol (str): OpenAlgo symbol
            exchange (str): OpenAlgo exchange
            timeframe (str): OpenAlgo interval, e.g. '1m', '15m', '1h', 'D'
            start_time (str): Start date, YYYY-MM-DD
            end_time (str): End date, YYYY-MM-DD

        Returns:
            pd.DataFrame: timestamp, open, high, low, close, volume

        Raises:
            ValueError: For an unsupported interval or symbol, or when Groww
                refuses a request; the message carries Groww's reason.
        """
        columns = ["timestamp", "open", "high", "low", "close", "volume"]
        interval = self.timeframe_map.get(timeframe)
        if interval is None:
            raise ValueError(
                f"Groww does not provide {timeframe} candles. "
                f"Supported intervals: {', '.join(self.timeframe_map)}"
            )
        groww_exchange, segment, groww_symbol, trading_symbol = self._groww_symbol(
            symbol, exchange
        )
        start = self._to_date(start_time)
        end = self._to_date(end_time)

        eod_minutes = self._EOD_MINUTES.get(timeframe)
        rows = []
        if eod_minutes:
            candles = self._fetch_candles(
                symbol,
                "/v1/historical/candle/range",
                {
                    "exchange": groww_exchange,
                    "segment": segment,
                    "trading_symbol": trading_symbol,
                    "interval_in_minutes": eod_minutes,
                },
                start,
                end,
                self._MAX_DAYS[eod_minutes],
            )
            ist = pytz.timezone("Asia/Kolkata")
            for candle in candles:
                ts = int(candle[0])
                if ts > 4102444800:  # milliseconds
                    ts //= 1000
                day = datetime.fromtimestamp(ts, tz=ist).date()
                midnight = pytz.UTC.localize(datetime.combine(day, datetime.min.time()))
                rows.append([int(midnight.timestamp()), *candle[1:6]])
        else:
            # Groww starts 30m/1h/4h candles on the clock hour, so the first one
            # of a day mixes the 09:00-09:15 pre-open session with regular
            # trading and carries a null open. Those intervals are built from
            # 15-minute candles instead (which split exactly at 09:15), aligned
            # to the 09:15 market open as other brokers' are.
            fetch_interval = interval if interval not in self._REBUCKETED else "15minute"
            candles = self._fetch_candles(
                symbol,
                "/v1/historical/candles",
                {
                    "exchange": groww_exchange,
                    "segment": segment,
                    "groww_symbol": groww_symbol,
                    "candle_interval": fetch_interval,
                },
                start,
                end,
                self._MAX_DAYS[fetch_interval],
            )
            ist = pytz.timezone("Asia/Kolkata")
            fetch_minutes = self._INTERVAL_MINUTES[fetch_interval]
            session = []
            for candle in candles:
                prices = candle[1:5]
                stamp = datetime.fromisoformat(str(candle[0]).replace(" ", "T"))
                market_open = stamp.replace(hour=9, minute=15, second=0, microsecond=0)
                # Leave out candles wholly inside the pre-open session
                if stamp + timedelta(minutes=fetch_minutes) <= market_open:
                    continue
                if prices[0] is None:
                    continue  # pre-open fragment: volume without an opening price
                volume = candle[5] if len(candle) > 5 else None
                session.append((stamp, *prices, volume))

            if interval in self._REBUCKETED:
                session = self._rebucket(session, self._INTERVAL_MINUTES[interval])
            for stamp, *ohlcv in session:
                rows.append([int(ist.localize(stamp).timestamp()), *ohlcv])

        if not rows:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame(rows, columns=columns)
        df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        # OpenAlgo's history format has a numeric volume, and the chart rejects
        # a candle whose volume is null. Groww sends none for indices and
        # leaves it empty on the odd stock candle, so that reads as 0, as the
        # reference broker reports index volume. Prices are never filled in.
        df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype("int64")
        return df.astype(object).where(df.notna(), None)

    def get_intervals(self) -> dict[str, dict[str, list[str]]]:
        """Intervals Groww's history provides, in OpenAlgo format."""
        return {
            "status": "success",
            "data": {
                "seconds": [],
                "minutes": ["1m", "2m", "3m", "5m", "10m", "15m", "30m"],
                "hours": ["1h", "4h"],
                "days": ["D"],
                "weeks": ["W"],
                "months": [],
            },
        }

    def get_quotes(self, symbol_list, exchange=None, timeout: int = 5) -> dict[str, Any]:
        """
        Get real-time quotes for a list of symbols using direct Groww API calls.

        This implementation directly calls Groww API endpoints instead of using the SDK.

        Args:
            symbol_list: A symbol string, dict {symbol, exchange}, or list thereof.
            exchange: Exchange code when ``symbol_list`` is a bare string.
                Accepted for compatibility with the ``(symbol, exchange)``
                calling convention used by the services layer.
            timeout: Timeout in seconds.

        Returns:
            Dict[str, Any]: Quote data in OpenAlgo format
        """
        # Back-compat: legacy callers passed timeout in the second positional slot.
        if isinstance(exchange, int) and not isinstance(exchange, bool):
            timeout = exchange
            exchange = None

        # Promote bare-string + explicit exchange to a dict so segment mapping
        # picks the right CASH/FNO segment (otherwise derivatives passed via
        # the services layer get routed to CASH and Groww 400s).
        if isinstance(symbol_list, str) and exchange:
            symbol_list = {"symbol": symbol_list, "exchange": exchange}

        logger.info(f"Getting quotes using direct API calls for: {symbol_list}")

        # Define exchange and segment constants
        EXCHANGE_NSE = "NSE"
        EXCHANGE_BSE = "BSE"
        SEGMENT_CASH = "CASH"
        SEGMENT_FNO = "FNO"

        # Standardize input to a list of dictionaries with exchange and symbol
        if isinstance(symbol_list, dict):
            try:
                # Extract symbol and exchange
                symbol = symbol_list.get("symbol") or symbol_list.get("SYMBOL")
                exchange = symbol_list.get("exchange") or symbol_list.get("EXCHANGE")

                if symbol and exchange:
                    logger.info(f"Processing single symbol request: {symbol} on {exchange}")
                    # Convert to a list with a single item
                    symbol_list = [{"symbol": symbol, "exchange": exchange}]
                else:
                    logger.error("Missing symbol or exchange in request")
                    return {
                        "status": "error",
                        "data": [],
                        "message": "Missing symbol or exchange in request",
                    }
            except Exception as e:
                logger.error(f"Error processing single symbol request: {str(e)}")
                return {
                    "status": "error",
                    "data": [],
                    "message": f"Error processing request: {str(e)}",
                }

        # Handle plain string (like just "RELIANCE")
        elif isinstance(symbol_list, str):
            symbol = symbol_list.strip()
            # Auto-detect if it's a derivative based on symbol format
            if symbol.endswith("FUT") or symbol.endswith("CE") or symbol.endswith("PE"):
                exchange = "NFO"  # It's a derivative
                logger.info(f"Auto-detected derivative symbol: {symbol}, using NFO exchange")
            else:
                exchange = "NSE"  # Default to NSE for equity
            logger.info(f"Processing string symbol: {symbol} on {exchange}")
            symbol_list = [{"symbol": symbol, "exchange": exchange}]

        # Process all symbols using direct API calls
        quote_data = []

        for sym in symbol_list:
            try:
                # Extract symbol and exchange
                if isinstance(sym, dict) and "symbol" in sym and "exchange" in sym:
                    symbol = sym["symbol"]
                    exchange = sym["exchange"]
                elif isinstance(sym, str):
                    symbol = sym
                    # Auto-detect if it's a derivative based on symbol format
                    if symbol.endswith("FUT") or symbol.endswith("CE") or symbol.endswith("PE"):
                        exchange = "NFO"  # It's a derivative
                    else:
                        exchange = "NSE"  # Default to NSE for equity
                else:
                    logger.warning(f"Invalid symbol format: {sym}")
                    continue

                # Get token for this symbol
                token = get_token(symbol, exchange)

                # Map OpenAlgo exchange to Groww exchange format
                # Indexes live in the CASH segment on Groww; without the *_INDEX
                # branches BSE_INDEX fell through to NSE and SENSEX quoted 0.
                if exchange in ("NSE", "NSE_INDEX"):
                    groww_exchange = EXCHANGE_NSE
                    segment = SEGMENT_CASH
                elif exchange in ("BSE", "BSE_INDEX"):
                    groww_exchange = EXCHANGE_BSE
                    segment = SEGMENT_CASH
                elif exchange == "NFO":
                    groww_exchange = EXCHANGE_NSE
                    segment = SEGMENT_FNO
                elif exchange == "BFO":
                    groww_exchange = EXCHANGE_BSE
                    segment = SEGMENT_FNO
                else:
                    raise ValueError(
                        f"Groww does not provide market data for the {exchange} exchange. "
                    "Supported: NSE, BSE, NFO, BFO, NSE_INDEX and BSE_INDEX."
                    )

                # Get broker-specific symbol. For FNO contracts, fall back to
                # format conversion when the master-contract lookup misses —
                # without this Groww may resolve loosely and return a partial
                # payload that's missing bid/ask/volume/OI for option strikes.
                br_symbol = get_br_symbol(symbol, exchange)
                if br_symbol:
                    trading_symbol = br_symbol
                elif exchange in ("NFO", "BFO"):
                    trading_symbol = self._convert_openalgo_to_groww_derivative_symbol(symbol)
                else:
                    trading_symbol = symbol

                logger.info(
                    f"Requesting quote for {trading_symbol} on {groww_exchange} (segment: {segment})"
                )
                # Make direct API call to Groww quotes endpoint
                start_time = time.time()

                # Safely convert values to float/int, handling None values
                def safe_float(value, default=0.0):
                    if value is None:
                        return default
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        return default

                def safe_int(value, default=0):
                    if value is None:
                        return default
                    try:
                        return int(value)
                    except (ValueError, TypeError):
                        return default

                try:
                    # Define API endpoint for quotes
                    quote_endpoint = "/v1/live-data/quote"

                    # Prepare parameters
                    params = {
                        "exchange": groww_exchange,
                        "segment": segment,
                        "trading_symbol": trading_symbol,
                    }

                    # Make the API call using the shared httpx client
                    response = get_api_response(
                        endpoint=quote_endpoint,
                        auth_token=self.auth_token,
                        method="GET",
                        params=params,
                        debug=True,
                    )

                    logger.info(f"Groww API response: {response}")
                    elapsed = time.time() - start_time
                    logger.info(f"Got response from Groww API in {elapsed:.2f}s")

                    if response and not response.get("error"):
                        logger.info(f"Successfully retrieved quote for {symbol} on {exchange}")
                        # Log a sample of the data structure
                        if isinstance(response, dict):
                            logger.info(f"Response keys: {list(response.keys())[:10]}")

                        # Extract payload which contains the actual quote data
                        if response.get("status") == "SUCCESS" and isinstance(
                            response.get("payload"), dict
                        ):
                            response = response.get("payload", {})
                            logger.info(f"response: {response}")
                            logger.info(
                                f"Extracted payload data with keys: {list(response.keys())[:10]}"
                            )

                            # Extract OHLC data from the nested structure
                            # OHLC might be a string in some responses
                            ohlc_data = response.get("ohlc", {})
                            logger.info(f"Raw OHLC data: {ohlc_data}")

                            # Handle case where ohlc is a string (from sample response)
                            ohlc = {}
                            if isinstance(ohlc_data, str):
                                # Try to parse the string into a dict
                                try:
                                    # Convert the string format "{open: 149.50,high: 150.50,low: 148.50,close: 149.50}" to a dict
                                    ohlc_str = ohlc_data.strip("{}")
                                    parts = ohlc_str.split(",")
                                    for part in parts:
                                        key_val = part.split(":")
                                        if len(key_val) == 2:
                                            key = key_val[0].strip()
                                            val = key_val[1].strip()
                                            ohlc[key] = float(val)
                                except Exception as e:
                                    logger.error(f"Error parsing OHLC string: {e}")
                            else:
                                # Use the object directly
                                ohlc = ohlc_data

                            logger.info(f"Processed OHLC data: {ohlc}")

                            # Create quote_item in OpenAlgo format
                            # Print each field being extracted for debugging
                            logger.info(f"last_price: {response.get('last_price')}")
                            logger.info(f"ohlc: {ohlc}")
                            logger.info(f"volume: {response.get('volume')}")

                            # CRITICAL: Build the quote item directly with values extracted from the response, using field names that OpenAlgo understands
                            # The quote_item should use the frontend-compatible field names
                            last_price = safe_float(response.get("last_price"))
                            logger.info(f"EXTRACTED last_price = {last_price}")

                            # Determine if this is a derivative instrument
                            is_derivative = exchange in ["NFO", "BFO"] or segment == SEGMENT_FNO

                            # Field aliases — Groww has been observed to use
                            # alternate keys for some segments. Probe each
                            # known name so FNO contracts populate bid/ask/
                            # volume/OI even when the canonical key is absent.
                            _depth = response.get("depth") or {}
                            _top_bid = (_depth.get("buy") or [{}])[0] or {}
                            _top_ask = (_depth.get("sell") or [{}])[0] or {}
                            _bid = (
                                response.get("bid_price")
                                or response.get("bid")
                                or response.get("best_bid_price")
                                or _top_bid.get("price")
                            )
                            _ask = (
                                response.get("offer_price")
                                or response.get("ask")
                                or response.get("best_offer_price")
                                or response.get("best_ask_price")
                                or _top_ask.get("price")
                            )
                            _bid_qty = (
                                response.get("bid_quantity")
                                or response.get("bid_size")
                                or response.get("best_bid_quantity")
                                or _top_bid.get("quantity")
                            )
                            _ask_qty = (
                                response.get("offer_quantity")
                                or response.get("ask_quantity")
                                or response.get("ask_size")
                                or response.get("offer_size")
                                or response.get("best_offer_quantity")
                                or _top_ask.get("quantity")
                            )
                            _vol = (
                                response.get("volume")
                                or response.get("total_volume")
                                or response.get("traded_volume")
                            )
                            _oi = response.get("open_interest") or response.get("oi") or 0

                            quote_item = {
                                "symbol": symbol,
                                "exchange": exchange,
                                "token": token,
                                # Use 'ltp' directly as that's what the frontend expects
                                "ltp": last_price,  # This is what the frontend looks for
                                "last_price": last_price,  # Keep original field too just in case
                                "open": safe_float(ohlc.get("open")),
                                "high": safe_float(ohlc.get("high")),
                                "low": safe_float(ohlc.get("low")),
                                "close": safe_float(ohlc.get("close")),
                                "prev_close": safe_float(
                                    ohlc.get("close")
                                ),  # Using previous day's close
                                "change": safe_float(response.get("day_change")),
                                "change_percent": safe_float(response.get("day_change_perc")),
                                "volume": safe_int(_vol),
                                # The frontend uses 'bid' and 'ask' without the _price suffix
                                "bid": safe_float(_bid),
                                "ask": safe_float(_ask),
                                # Also keep original fields
                                "bid_price": safe_float(_bid),
                                "bid_qty": safe_int(_bid_qty),
                                "ask_price": safe_float(_ask),
                                "ask_qty": safe_int(_ask_qty),
                                "total_buy_qty": safe_float(response.get("total_buy_quantity")),
                                "total_sell_qty": safe_float(response.get("total_sell_quantity")),
                                # Only show OI for derivatives, 0 for equity
                                "oi": safe_int(_oi) if is_derivative else 0,
                                "timestamp": response.get(
                                    "last_trade_time", int(datetime.now().timestamp() * 1000)
                                ),
                            }

                            # Add circuit limits
                            if "upper_circuit_limit" in response:
                                quote_item["upper_circuit"] = safe_float(
                                    response.get("upper_circuit_limit")
                                )
                            if "lower_circuit_limit" in response:
                                quote_item["lower_circuit"] = safe_float(
                                    response.get("lower_circuit_limit")
                                )

                            # Add market depth if available (check depth is not None)
                            if response.get("depth"):
                                depth_data = response["depth"]
                                buy_depth = depth_data.get("buy", [])
                                sell_depth = depth_data.get("sell", [])

                                depth = {"buy": [], "sell": []}

                                # Process buy side
                                for level in buy_depth:
                                    if (
                                        safe_float(level.get("price")) > 0
                                    ):  # Only include non-zero prices
                                        depth["buy"].append(
                                            {
                                                "price": safe_float(level.get("price")),
                                                "quantity": safe_int(level.get("quantity")),
                                                "orders": 0,  # Groww API doesn't provide order count
                                            }
                                        )

                                # Process sell side
                                for level in sell_depth:
                                    if (
                                        safe_float(level.get("price")) > 0
                                    ):  # Only include non-zero prices
                                        depth["sell"].append(
                                            {
                                                "price": safe_float(level.get("price")),
                                                "quantity": safe_int(level.get("quantity")),
                                                "orders": 0,  # Groww API doesn't provide order count
                                            }
                                        )

                                quote_item["depth"] = depth

                            # Add to quote data
                            quote_data.append(quote_item)
                            logger.info(f"Added quote_item: {quote_item}")
                        else:
                            logger.warning(f"Invalid response format for {symbol} on {exchange}")
                            quote_data.append(
                                {
                                    "symbol": symbol,
                                    "exchange": exchange,
                                    "error": f"Groww returned no quote for {symbol}",
                                }
                            )
                    else:
                        reason = _response_reason(response, "no response")
                        logger.warning(f"Groww refused quote for {symbol} on {exchange}: {reason}")
                        quote_data.append(
                            {
                                "symbol": symbol,
                                "exchange": exchange,
                                "error": f"Groww did not return a quote for {symbol}: {reason}",
                            }
                        )

                    # This section is now handled directly in the response processing code above to avoid duplicate processing
                    continue

                    # Add market depth if available
                    if "depth" in response:
                        depth_data = response["depth"]
                        buy_depth = depth_data.get("buy", [])
                        sell_depth = depth_data.get("sell", [])

                        depth = {"buy": [], "sell": []}

                        # Process buy side
                        for level in buy_depth:
                            depth["buy"].append(
                                {
                                    "price": safe_float(level.get("price")),
                                    "quantity": safe_int(level.get("quantity")),
                                    "orders": 0,  # Groww API doesn't provide order count
                                }
                            )

                        # Process sell side
                        for level in sell_depth:
                            depth["sell"].append(
                                {
                                    "price": safe_float(level.get("price")),
                                    "quantity": safe_int(level.get("quantity")),
                                    "orders": 0,  # Groww API doesn't provide order count
                                }
                            )

                        quote_item["depth"] = depth

                except Exception as api_error:
                    logger.error(f"Groww API error: {str(api_error)}")
                    error_msg = str(api_error)
                    # Add to quote data with error
                    quote_data.append(
                        {
                            "symbol": symbol,
                            "exchange": exchange,
                            "token": token,
                            "error": error_msg,
                            "ltp": 0,
                        }
                    )
            except Exception as e:
                logger.error(f"Error processing Groww API data for {sym}: {str(e)}")
                # Add empty quote data with error message
                quote_data.append(
                    {
                        "symbol": symbol if "symbol" in locals() else str(sym),
                        "exchange": exchange if "exchange" in locals() else "Unknown",
                        "error": str(e),
                        "ltp": 0,
                    }
                )

        # Debug output of the final quote_data
        logger.info(f"FINAL QUOTE DATA: {quote_data}")

        # No data case
        if not quote_data:
            raise ValueError("Groww returned no quote data for the requested symbols")

        # Single symbol case - return in simpler format for OpenAlgo frontend
        if isinstance(symbol_list, (str, dict)) or len(symbol_list) == 1:
            logger.info("Returning data for single symbol")

            # Log what is being passed to the formatter
            logger.debug(f"Quote data passed to formatter: {quote_data}")

            # For single symbols, just return the direct quote data
            # The REST API endpoint will wrap it with status/data
            return self._format_single_quote_response(quote_data)

        # Multiple quotes - return in standard format
        logger.info(f"Returning data for {len(quote_data)} symbols")
        return {"status": "success", "data": quote_data}

    def _format_single_quote_response(self, quote_data):
        """Helper method to convert from standard dict to the format expected by OpenAlgo frontend

        Returns only the data portion without status wrapper - status added by the caller
        """

        if not quote_data or not isinstance(quote_data, list) or len(quote_data) == 0:
            return {}

        quote = quote_data[0]
        if quote.get("error"):
            # A failed quote is an error, not a quote of zeros
            raise ValueError(quote["error"])

        logger.info(f"Formatting single quote: {quote}")

        result = {
            "ltp": quote.get("ltp", 0),
            "open": quote.get("open", 0),
            "high": quote.get("high", 0),
            "low": quote.get("low", 0),
            "prev_close": quote.get("prev_close", 0),
            "volume": quote.get("volume", 0),
            "bid": quote.get("bid_price", 0),
            "ask": quote.get("ask_price", 0),
            "bid_qty": quote.get("bid_qty", 0),
            "ask_qty": quote.get("ask_qty", 0),
            "oi": quote.get("oi", 0),  # Add Open Interest field
        }

        logger.debug(f"Final OpenAlgo quote format (data only): {result}")
        return result

        # Commented out alternate implementation

        # Legacy implementation - no longer used
        # The code below is from the previous implementation and is kept for reference
        #    logger.info("Empty quote_data received in _format_single_quote_response")
        #    return {
        #        "status": "success",
        #        "data": {}
        #    }
        #
        #    # Extract first (and only) item in single quote request
        #    quote = quote_data[0] if isinstance(quote_data, list) and len(quote_data) > 0 else {}

        logger.info(f"EXTRACTED QUOTE: {quote}")
        logger.info(f"Formatting single quote response for OpenAlgo frontend: {quote}")

        # Based on the sample response, OpenAlgo expects exactly these fields
        # Keep this extremely simple - just the required fields
        simple_data = {
            "ltp": 0,
            "open": 0,
            "high": 0,
            "low": 0,
            "prev_close": 0,
            "volume": 0,
            "bid": 0,
            "ask": 0,
            "status": "success",
        }

        # Now grab values from our quote data, using the field that matches best

        # LTP - preferred field name in OpenAlgo
        if "ltp" in quote and quote["ltp"] is not None:
            simple_data["ltp"] = float(quote["ltp"])
        elif "last_price" in quote and quote["last_price"] is not None:
            simple_data["ltp"] = float(quote["last_price"])

        # Open price
        if "open" in quote and quote["open"] is not None:
            simple_data["open"] = float(quote["open"])

        # High price
        if "high" in quote and quote["high"] is not None:
            simple_data["high"] = float(quote["high"])

        # Low price
        if "low" in quote and quote["low"] is not None:
            simple_data["low"] = float(quote["low"])

        # Previous close
        if "prev_close" in quote and quote["prev_close"] is not None:
            simple_data["prev_close"] = float(quote["prev_close"])
        elif "close" in quote and quote["close"] is not None:
            simple_data["prev_close"] = float(quote["close"])

        # Volume
        if "volume" in quote and quote["volume"] is not None:
            simple_data["volume"] = int(quote["volume"])

        # Bid price
        if "bid" in quote and quote["bid"] is not None:
            simple_data["bid"] = float(quote["bid"])
        elif "bid_price" in quote and quote["bid_price"] is not None:
            simple_data["bid"] = float(quote["bid_price"])

        # Ask price
        if "ask" in quote and quote["ask"] is not None:
            simple_data["ask"] = float(quote["ask"])
        elif "ask_price" in quote and quote["ask_price"] is not None:
            simple_data["ask"] = float(quote["ask_price"])
        elif "offer_price" in quote and quote["offer_price"] is not None:
            simple_data["ask"] = float(quote["offer_price"])

        # Debug output
        logger.info("FINAL SIMPLE FORMAT:")
        for key, value in simple_data.items():
            logger.info(f"{{key}}: {value}")

        # Return exact structure expected by OpenAlgo
        result = {"status": "success", "data": simple_data}

        logger.info(f"FINAL FORMATTED RESULT: {result}")
        logger.info(f"Formatted result for OpenAlgo frontend: {result}")

        return result

    def get_depth(self, symbol_list, exchange=None, timeout: int = 5) -> dict[str, Any]:
        """
        Get market depth for a symbol or list of symbols using Groww API.
        This leverages the direct API endpoint for quotes, which includes market depth information.

        Args:
            symbol_list: A symbol string, dict {symbol, exchange}, or list thereof.
            exchange: Exchange code (e.g. 'NSE', 'NFO') when ``symbol_list`` is a
                bare string. Accepted for compatibility with the
                ``(symbol, exchange)`` calling convention used by the rest of
                the broker adapters / services layer.
            timeout: Timeout in seconds.

        Returns:
            Dict[str, Any]: Market depth data in OpenAlgo format
        """
        # Back-compat: legacy callers passed timeout in the second positional
        # slot. If we got an int there, treat it as the timeout and ignore.
        if isinstance(exchange, int) and not isinstance(exchange, bool):
            timeout = exchange
            exchange = None

        # If a bare-string symbol came in along with an explicit exchange,
        # promote to a dict so the segment mapping below is correct. This is
        # the path the services layer (depth_service.get_depth) actually uses;
        # without it, derivatives like SBIN26MAY26FUT default to NSE/CASH and
        # Groww returns HTTP 400 GA001 "Bad Request".
        if isinstance(symbol_list, str) and exchange:
            symbol_list = {"symbol": symbol_list, "exchange": exchange}

        logger.info(f"Getting market depth using direct API calls for: {symbol_list}")

        # Make direct API call to get quote and depth data in a single request
        # Define exchange and segment constants
        EXCHANGE_NSE = "NSE"
        EXCHANGE_BSE = "BSE"
        SEGMENT_CASH = "CASH"
        SEGMENT_FNO = "FNO"

        # Bare-string symbols arrive without exchange info, so infer it
        # from the symbol suffix — derivatives (FUT/CE/PE) must go to NFO
        # so segment=FNO is sent to Groww. Defaulting to NSE/CASH for an
        # F&O contract triggers HTTP 400 GA001 "Bad Request".
        def _infer_exchange(sym_str: str) -> str:
            s = sym_str.strip().upper()
            if s.endswith("FUT") or s.endswith("CE") or s.endswith("PE"):
                return "NFO"
            return "NSE"

        # Standardize input to a list of dictionaries with exchange and symbol
        symbols_to_process = []
        if isinstance(symbol_list, dict):
            symbol = symbol_list.get("symbol") or symbol_list.get("SYMBOL")
            exchange = symbol_list.get("exchange") or symbol_list.get("EXCHANGE")
            if symbol and exchange:
                symbols_to_process.append({"symbol": symbol, "exchange": exchange})
        elif isinstance(symbol_list, str):
            symbols_to_process.append(
                {"symbol": symbol_list, "exchange": _infer_exchange(symbol_list)}
            )
        elif isinstance(symbol_list, list):
            for sym in symbol_list:
                if isinstance(sym, dict) and "symbol" in sym and "exchange" in sym:
                    symbols_to_process.append(sym)
                elif isinstance(sym, str):
                    symbols_to_process.append(
                        {"symbol": sym, "exchange": _infer_exchange(sym)}
                    )

        # No valid symbols to process
        if not symbols_to_process:
            logger.error("No valid symbols to process for market depth")
            return {}

        # Process the first symbol (for single symbol requests)
        sym_data = symbols_to_process[0]
        symbol = sym_data["symbol"]
        exchange = sym_data["exchange"]

        # Get token for this symbol
        token = get_token(symbol, exchange)

        # Map OpenAlgo exchange to Groww exchange format
        if exchange in ("NSE", "NSE_INDEX"):
            groww_exchange = EXCHANGE_NSE
            segment = SEGMENT_CASH
        elif exchange in ("BSE", "BSE_INDEX"):
            groww_exchange = EXCHANGE_BSE
            segment = SEGMENT_CASH
        elif exchange == "NFO":
            groww_exchange = EXCHANGE_NSE
            segment = SEGMENT_FNO
        elif exchange == "BFO":
            groww_exchange = EXCHANGE_BSE
            segment = SEGMENT_FNO
        else:
            raise ValueError(
                f"Groww does not provide market data for the {exchange} exchange. "
                "Supported: NSE, BSE, NFO, BFO, NSE_INDEX and BSE_INDEX."
            )

        # Convert symbol format for derivatives
        if exchange in ["NFO", "BFO"]:
            # First try to get from database
            br_symbol = get_br_symbol(symbol, exchange)
            if br_symbol:
                trading_symbol = br_symbol
                logger.debug(f"Found broker symbol in database: {trading_symbol}")
            else:
                # If not in database, convert format
                trading_symbol = self._convert_openalgo_to_groww_derivative_symbol(symbol)
                logger.debug(f"Converted derivative symbol: {symbol} -> {trading_symbol}")
        else:
            # For equity, use broker symbol if available
            trading_symbol = get_br_symbol(symbol, exchange) or symbol

        logger.info(
            f"Requesting quote with depth for {trading_symbol} on {groww_exchange} (segment: {segment})"
        )

        # Define API endpoint for quotes
        quote_endpoint = "/v1/live-data/quote"

        # Prepare parameters
        params = {"exchange": groww_exchange, "segment": segment, "trading_symbol": trading_symbol}

        # Make the API call using the shared httpx client
        try:
            response = get_api_response(
                endpoint=quote_endpoint,
                auth_token=self.auth_token,
                method="GET",
                params=params,
                debug=True,
            )

            logger.info(f"Groww /v1/live-data/quote raw response for {trading_symbol}: {response}")

            # Check if we got a valid response with depth data
            if not response or response.get("status") != "SUCCESS" or "payload" not in response:
                logger.error(f"No valid quote data received for {symbol}")
                return {}

            # Extract payload data
            payload = response["payload"]
            logger.info(f"Extracted payload with keys: {list(payload.keys())[:10]}")

            # Create a properly formatted response for OpenAlgo
            depth_response = {}

            # Safely convert values to float/int, handling None values
            def safe_float(value, default=0.0):
                if value is None:
                    return default
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return default

            def safe_int(value, default=0):
                if value is None:
                    return default
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return default

            # Extract OHLC data
            ohlc_data = payload.get("ohlc", "{}")
            ohlc = {}
            if isinstance(ohlc_data, str):
                # Parse string format like "{open: 149.50,high: 150.50,low: 148.50,close: 149.50}"
                try:
                    ohlc_str = ohlc_data.strip("{}")
                    parts = ohlc_str.split(",")
                    for part in parts:
                        key_val = part.split(":")
                        if len(key_val) == 2:
                            key = key_val[0].strip()
                            val = key_val[1].strip()
                            ohlc[key] = float(val)
                except Exception as e:
                    logger.error(f"Error parsing OHLC string: {e}")
            elif isinstance(ohlc_data, dict):
                ohlc = ohlc_data

            # Format bids/asks from market depth
            bids = []
            asks = []
            empty_price_level = {"price": 0, "quantity": 0}

            # Extract depth info
            depth_data = payload.get("depth", {})

            # Handle case where depth_data is None
            if depth_data is None:
                depth_data = {}

            # Process buy side (bids)
            for level in depth_data.get("buy", []):
                if len(bids) < 5:  # Limit to 5 levels
                    bids.append(
                        {
                            "price": safe_float(level.get("price", 0)),
                            "quantity": safe_int(level.get("quantity", 0)),
                        }
                    )

            # Process sell side (asks)
            for level in depth_data.get("sell", []):
                if len(asks) < 5:  # Limit to 5 levels
                    asks.append(
                        {
                            "price": safe_float(level.get("price", 0)),
                            "quantity": safe_int(level.get("quantity", 0)),
                        }
                    )

            # Ensure we have exactly 5 price levels
            while len(bids) < 5:
                bids.append(empty_price_level.copy())
            while len(asks) < 5:
                asks.append(empty_price_level.copy())

            # Last traded price and quantity
            ltp = safe_float(payload.get("last_price", 0))
            ltq = safe_int(payload.get("last_trade_quantity", 0))

            # Volume information
            volume = safe_int(payload.get("volume", 0))
            total_buy_qty = safe_int(payload.get("total_buy_quantity", 0))
            total_sell_qty = safe_int(payload.get("total_sell_quantity", 0))

            # Determine if this is a derivative instrument
            is_derivative = exchange in ["NFO", "BFO"] or segment == SEGMENT_FNO

            # Format the depth response according to OpenAlgo requirements
            depth_response = {
                "bids": bids,
                "asks": asks,
                "ltp": ltp,
                "ltq": ltq,
                "open": safe_float(ohlc.get("open", 0)),
                "high": safe_float(ohlc.get("high", 0)),
                "low": safe_float(ohlc.get("low", 0)),
                "prev_close": safe_float(ohlc.get("close", 0)),
                "volume": volume,
                "totalbuyqty": total_buy_qty,
                "totalsellqty": total_sell_qty,
                "oi": safe_int(payload.get("open_interest", 0))
                if is_derivative
                else 0,  # OI only for derivatives
            }

            logger.info(
                f"Formatted market depth response with {len(bids)} bids and {len(asks)} asks"
            )
            return depth_response

        except Exception as e:
            logger.exception(f"Error getting market depth: {str(e)}")
            return {}

    def get_market_depth(self, symbol_list, exchange=None, timeout: int = 5) -> dict[str, Any]:
        """Alias for get_depth. Maintains API compatibility.

        Accepts both ``(symbol, exchange)`` and the legacy
        ``(symbol_list, timeout)`` calling conventions.
        """
        return self.get_depth(symbol_list, exchange=exchange, timeout=timeout)

    def get_multiquotes(self, symbols: list) -> list:
        """
        Get real-time quotes for multiple symbols with automatic batching
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
                     Example: [{'symbol': 'SBIN', 'exchange': 'NSE'}, ...]
        Returns:
            list: List of quote data for each symbol with format:
                  [{'symbol': 'SBIN', 'exchange': 'NSE', 'data': {...}}, ...]
        """
        try:
            BATCH_SIZE = 50  # Groww API limit: up to 50 instruments per request

            # If symbols exceed batch size, process in batches
            if len(symbols) > BATCH_SIZE:
                logger.info(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
                all_results = []

                # Split symbols into batches
                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i : i + BATCH_SIZE]
                    logger.debug(
                        f"Processing batch {i // BATCH_SIZE + 1}: symbols {i + 1} to {min(i + BATCH_SIZE, len(symbols))}"
                    )

                    # Process this batch
                    batch_results = self._process_quotes_batch(batch)
                    all_results.extend(batch_results)


                logger.info(
                    f"Successfully processed {len(all_results)} quotes in {(len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE} batches"
                )
                return all_results
            else:
                # Single batch processing
                return self._process_quotes_batch(symbols)

        except Exception as e:
            logger.exception("Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _process_quotes_batch(self, symbols: list) -> list:
        """
        Process a single batch of symbols (internal method)
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys (max 50)
        Returns:
            list: List of quote data for the batch
        """
        # Build exchange_trading_symbols list and mapping
        # Group by segment (CASH vs FNO)
        cash_symbols = []
        fno_symbols = []
        symbol_map = {}  # {exchange_symbol -> {symbol, exchange}}
        skipped_symbols = []  # Track symbols that couldn't be resolved

        for item in symbols:
            symbol = item["symbol"]
            exchange = item["exchange"]

            try:
                # Get broker symbol from database. The brsymbol stored in
                # SymToken is already the format Groww expects (mirrors what
                # the CSV's trading_symbol provides). Re-running the OpenAlgo
                # → Groww regex on it would mangle valid Groww symbols whose
                # shape happens to match the OpenAlgo pattern (e.g. JUN26
                # contracts: "NIFTY26JUN22350PE" → "NIFTY22JUN350PE").
                # Only convert from OpenAlgo when DB lookup misses.
                if exchange not in ("NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"):
                    raise ValueError(
                        f"Groww does not provide market data for the {exchange} exchange"
                    )
                br_symbol = get_br_symbol(symbol, exchange)

                if not br_symbol:
                    if exchange in ["NFO", "BFO"]:
                        br_symbol = self._convert_openalgo_to_groww_derivative_symbol(symbol)
                    if not br_symbol:
                        logger.warning(
                            f"Skipping symbol {symbol} on {exchange}: could not resolve broker symbol"
                        )
                        skipped_symbols.append(
                            {
                                "symbol": symbol,
                                "exchange": exchange,
                                "error": "Could not resolve broker symbol",
                            }
                        )
                        continue

                # Determine Groww exchange prefix
                if exchange in ["NSE", "NFO", "NSE_INDEX"]:
                    groww_exchange = "NSE"
                elif exchange in ["BSE", "BFO", "BSE_INDEX"]:
                    groww_exchange = "BSE"
                else:
                    raise ValueError(
                        f"Groww does not provide market data for the {exchange} exchange"
                    )

                # Build exchange_trading_symbol format: EXCHANGE_SYMBOL
                exchange_symbol = f"{groww_exchange}_{br_symbol}"

                # Store mapping
                symbol_map[exchange_symbol] = {
                    "symbol": symbol,
                    "exchange": exchange,
                    "br_symbol": br_symbol,
                }

                # Group by segment
                if exchange in ["NFO", "BFO"]:
                    fno_symbols.append(exchange_symbol)
                else:
                    cash_symbols.append(exchange_symbol)

            except Exception as e:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: {str(e)}")
                skipped_symbols.append({"symbol": symbol, "exchange": exchange, "error": str(e)})
                continue

        # Return skipped symbols if no valid symbols
        if not cash_symbols and not fno_symbols:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        results = []

        # Fetch CASH segment quotes
        if cash_symbols:
            logger.info(f"Requesting OHLC for {len(cash_symbols)} CASH instruments")
            cash_results = self._fetch_ohlc_batch(cash_symbols, SEGMENT_CASH, symbol_map)
            results.extend(cash_results)

        # FNO segment: hybrid path.
        #   Step 1: OHLC batch (1 call) → fills LTP+OHLC for ALL strikes
        #           instantly. Bid/ask/qty/volume/OI default to 0.
        #   Step 2: best-effort per-symbol /v1/live-data/quote overlay
        #           layers in bid/ask/qty/volume/OI/depth where we can.
        # Groww has no multi-symbol full-snapshot endpoint and the per-
        # symbol quote endpoint trips a hard 429 lockout under load, so
        # this hybrid keeps the chain visible (LTP/OHLC always populated)
        # while enriching what we can.
        if fno_symbols:
            logger.info(f"Requesting OHLC for {len(fno_symbols)} FNO instruments (baseline)")
            fno_results = self._fetch_ohlc_batch(fno_symbols, SEGMENT_FNO, symbol_map)
            self._overlay_full_quotes(fno_results, fno_symbols, SEGMENT_FNO, symbol_map)
            results.extend(fno_results)

        # Include skipped symbols in results
        return skipped_symbols + results

    def _fetch_ohlc_batch(self, exchange_symbols: list, segment: str, symbol_map: dict) -> list:
        """
        Fetch OHLC data for a batch of symbols
        Args:
            exchange_symbols: List of exchange_trading_symbols (e.g., ['NSE_SBIN', 'NSE_TCS'])
            segment: CASH or FNO
            symbol_map: Mapping from exchange_symbol to original symbol/exchange
        Returns:
            list: List of quote data
        """
        results = []

        try:
            # Build comma-separated symbols for API
            symbols_param = ",".join(exchange_symbols)

            logger.info(
                f"Requesting OHLC with exchange_symbols: {symbols_param[:200]}..."
            )  # Log first 200 chars

            # Make API request to OHLC endpoint using GET
            response = get_api_response(
                endpoint="/v1/live-data/ohlc",
                auth_token=self.auth_token,
                method="GET",
                params={
                    "segment": segment,
                    "exchange_symbols": symbols_param,  # Comma-separated string
                },
                debug=True,
            )

            logger.info(
                f"Groww /v1/live-data/ohlc raw response (segment={segment}, "
                f"count={len(exchange_symbols)}): {response}"
            )

            # Check for valid response - handle invalid symbol errors with retry
            if not response or response.get("error"):
                error_details = response.get("details", "") if response else ""

                # Check if error is due to invalid symbol
                if "Invalid trading symbol" in str(error_details):
                    # Extract invalid symbol from error message
                    import re

                    match = re.search(r"Invalid trading symbol: (\w+)", str(error_details))
                    if match:
                        invalid_symbol = match.group(1)
                        logger.warning(
                            f"Invalid symbol detected: {invalid_symbol}, retrying without it"
                        )

                        # Find and remove the invalid symbol from the list
                        filtered_symbols = [s for s in exchange_symbols if invalid_symbol not in s]

                        if filtered_symbols and len(filtered_symbols) < len(exchange_symbols):
                            # Mark invalid symbol as error
                            for es in exchange_symbols:
                                if invalid_symbol in es:
                                    original = symbol_map.get(es, {})
                                    results.append(
                                        {
                                            "symbol": original.get("symbol", es),
                                            "exchange": original.get("exchange", "UNKNOWN"),
                                            "error": "Invalid trading symbol in Groww",
                                        }
                                    )

                            # Retry with filtered symbols (recursive call with max 5 retries)
                            if hasattr(self, "_retry_count"):
                                self._retry_count += 1
                            else:
                                self._retry_count = 1

                            if self._retry_count <= 5 and filtered_symbols:
                                retry_results = self._fetch_ohlc_batch(
                                    filtered_symbols, segment, symbol_map
                                )
                                results.extend(retry_results)
                                self._retry_count = 0
                                return results

                logger.error(f"API Error: {response.get('error', 'Unknown error')}")
                # Return error entries for all remaining symbols
                for exchange_symbol in exchange_symbols:
                    if not any(
                        r.get("symbol") == symbol_map.get(exchange_symbol, {}).get("symbol")
                        for r in results
                    ):
                        original = symbol_map.get(exchange_symbol, {})
                        results.append(
                            {
                                "symbol": original.get("symbol", exchange_symbol),
                                "exchange": original.get("exchange", "UNKNOWN"),
                                "error": response.get("error", "API Error")
                                if response
                                else "No response",
                            }
                        )
                return results

            # Extract payload data
            if response.get("status") == "SUCCESS":
                payload = response.get("payload", {})
            else:
                payload = response  # Direct response format

            # The OHLC snapshot's close is the previous session's close (it
            # equals the quote's ohlc.close, and day_change = LTP - close), so
            # the live price comes from the LTP endpoint (08-live-data
            # "Get LTP": 50 instruments, payload maps each symbol to its LTP).
            ltp_response = get_api_response(
                endpoint="/v1/live-data/ltp",
                auth_token=self.auth_token,
                method="GET",
                params={"segment": segment, "exchange_symbols": symbols_param},
            )
            ltp_payload = (
                ltp_response.get("payload")
                if isinstance(ltp_response, dict) and ltp_response.get("status") == "SUCCESS"
                else None
            )
            no_price = "Groww returned no live price for this symbol"
            if not isinstance(ltp_payload, dict):
                ltp_payload = {}
                no_price = (
                    "Groww did not return live prices: "
                    f"{_response_reason(ltp_response, 'no response')}"
                )
                logger.warning(f"Groww LTP batch failed for {segment}: {ltp_response}")

            # Process each symbol's data
            for exchange_symbol in exchange_symbols:
                original = symbol_map.get(exchange_symbol, {})
                ohlc_data = payload.get(exchange_symbol)

                if not ohlc_data:
                    logger.warning(f"No OHLC data found for {exchange_symbol}")
                    results.append(
                        {
                            "symbol": original.get("symbol", exchange_symbol),
                            "exchange": original.get("exchange", "UNKNOWN"),
                            "error": "No quote data available",
                        }
                    )
                    continue

                # Parse OHLC data. Groww's /v1/live-data/ohlc returns each
                # value as a non-JSON STRING like
                #   "{open: 149.50,high: 150.50,low: 148.50,close: 149.50}"
                # so we have to parse manually. Some responses also send a
                # dict directly, or (rarely) just the scalar LTP.
                ohlc_dict = None
                if isinstance(ohlc_data, dict):
                    ohlc_dict = ohlc_data
                elif isinstance(ohlc_data, str):
                    try:
                        parsed = {}
                        for part in ohlc_data.strip("{} ").split(","):
                            if ":" not in part:
                                continue
                            k, v = part.split(":", 1)
                            parsed[k.strip()] = float(v.strip())
                        if parsed:
                            ohlc_dict = parsed
                    except Exception as parse_err:
                        logger.warning(
                            f"Failed to parse OHLC string for {exchange_symbol}: "
                            f"{ohlc_data!r} ({parse_err})"
                        )

                ltp = ltp_payload.get(exchange_symbol)
                if ohlc_dict is None or ltp is None:
                    results.append(
                        {
                            "symbol": original.get("symbol", exchange_symbol),
                            "exchange": original.get("exchange", "UNKNOWN"),
                            "error": no_price,
                        }
                    )
                    continue
                ltp = float(ltp)
                open_price = float(ohlc_dict.get("open", 0) or 0)
                high_price = float(ohlc_dict.get("high", 0) or 0)
                low_price = float(ohlc_dict.get("low", 0) or 0)
                close_price = float(ohlc_dict.get("close", 0) or 0)

                result_item = {
                    "symbol": original.get("symbol", exchange_symbol),
                    "exchange": original.get("exchange", "UNKNOWN"),
                    "data": {
                        "bid": 0,  # OHLC endpoint doesn't provide bid/ask
                        "ask": 0,
                        "bid_qty": 0,
                        "ask_qty": 0,
                        "open": open_price,
                        "high": high_price,
                        "low": low_price,
                        "ltp": ltp,
                        "prev_close": close_price,  # ohlc.close is the previous close
                        "volume": 0,  # OHLC endpoint doesn't provide volume
                        "oi": 0,  # OHLC endpoint doesn't provide OI
                    },
                }
                results.append(result_item)

        except Exception as e:
            logger.error(f"Error fetching OHLC batch: {str(e)}")
            # Return error entries for all symbols
            for exchange_symbol in exchange_symbols:
                original = symbol_map.get(exchange_symbol, {})
                results.append(
                    {
                        "symbol": original.get("symbol", exchange_symbol),
                        "exchange": original.get("exchange", "UNKNOWN"),
                        "error": str(e),
                    }
                )

        return results

    def _overlay_full_quotes(
        self,
        existing_results: list,
        exchange_symbols: list,
        segment: str,
        symbol_map: dict,
    ) -> None:
        """
        Best-effort overlay of bid/ask/qty/volume/OI/depth onto results that
        already carry LTP/OHLC from the batch endpoint. Mutates
        ``existing_results`` in place.

        Per-symbol /v1/live-data/quote calls are issued sequentially and paced
        by broker.groww.api.rate_limiter (Live Data, 300/min), and the loop
        aborts after a run of consecutive failures so we never spin in a
        banned state. Symbols whose overlay fails simply keep their LTP/OHLC
        baseline.
        """
        # Stop overlaying after this many back-to-back 429s — Groww has put
        # us in cooldown and continuing only delays the user.
        MAX_CONSECUTIVE_429 = 4
        # Index existing results so we can merge by (symbol, exchange).
        result_index = {
            (r.get("symbol"), r.get("exchange")): r for r in existing_results
        }

        def _fetch_one(exchange_symbol: str) -> dict:
            original = symbol_map.get(exchange_symbol, {})
            # exchange_symbol is "NSE_<trading_symbol>" or "BSE_<trading_symbol>"
            try:
                groww_exchange, trading_symbol = exchange_symbol.split("_", 1)
            except ValueError:
                return {
                    "symbol": original.get("symbol", exchange_symbol),
                    "exchange": original.get("exchange", "UNKNOWN"),
                    "error": f"Malformed exchange_symbol: {exchange_symbol}",
                }

            try:
                response = get_api_response(
                    endpoint="/v1/live-data/quote",
                    auth_token=self.auth_token,
                    method="GET",
                    params={
                        "exchange": groww_exchange,
                        "segment": segment,
                        "trading_symbol": trading_symbol,
                    },
                    debug=False,
                )
            except Exception as fetch_err:
                logger.warning(
                    f"Quote fetch failed for {exchange_symbol}: {fetch_err}"
                )
                return {
                    "symbol": original.get("symbol", exchange_symbol),
                    "exchange": original.get("exchange", "UNKNOWN"),
                    "error": str(fetch_err),
                }

            if (
                not response
                or response.get("status") != "SUCCESS"
                or not isinstance(response.get("payload"), dict)
            ):
                err_msg = (response or {}).get("error") or "No quote data available"
                return {
                    "symbol": original.get("symbol", exchange_symbol),
                    "exchange": original.get("exchange", "UNKNOWN"),
                    "error": err_msg,
                }

            payload = response["payload"]

            def _safe_float(v, default=0.0):
                if v is None:
                    return default
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return default

            def _safe_int(v, default=0):
                if v is None:
                    return default
                try:
                    return int(v)
                except (TypeError, ValueError):
                    return default

            ohlc_raw = payload.get("ohlc")
            ohlc = {}
            if isinstance(ohlc_raw, dict):
                ohlc = ohlc_raw
            elif isinstance(ohlc_raw, str):
                try:
                    for part in ohlc_raw.strip("{} ").split(","):
                        if ":" in part:
                            k, v = part.split(":", 1)
                            ohlc[k.strip()] = float(v.strip())
                except Exception:
                    ohlc = {}

            depth_raw = payload.get("depth") or {}
            buy_levels = depth_raw.get("buy") or []
            sell_levels = depth_raw.get("sell") or []

            top_bid = buy_levels[0] if buy_levels else {}
            top_ask = sell_levels[0] if sell_levels else {}

            bid = (
                payload.get("bid_price")
                if payload.get("bid_price") is not None
                else top_bid.get("price")
            )
            ask = (
                payload.get("offer_price")
                if payload.get("offer_price") is not None
                else top_ask.get("price")
            )
            bid_qty = (
                payload.get("bid_quantity")
                if payload.get("bid_quantity") is not None
                else top_bid.get("quantity")
            )
            ask_qty = (
                payload.get("offer_quantity")
                if payload.get("offer_quantity") is not None
                else top_ask.get("quantity")
            )

            depth_normalized = {
                "buy": [
                    {
                        "price": _safe_float(level.get("price")),
                        "quantity": _safe_int(level.get("quantity")),
                        "orders": 0,
                    }
                    for level in buy_levels
                    if _safe_float(level.get("price")) > 0
                ],
                "sell": [
                    {
                        "price": _safe_float(level.get("price")),
                        "quantity": _safe_int(level.get("quantity")),
                        "orders": 0,
                    }
                    for level in sell_levels
                    if _safe_float(level.get("price")) > 0
                ],
            }

            data = {
                "ltp": _safe_float(payload.get("last_price")),
                "open": _safe_float(ohlc.get("open")),
                "high": _safe_float(ohlc.get("high")),
                "low": _safe_float(ohlc.get("low")),
                "close": _safe_float(ohlc.get("close")),
                "prev_close": _safe_float(ohlc.get("close")),
                "bid": _safe_float(bid),
                "ask": _safe_float(ask),
                "bid_qty": _safe_int(bid_qty),
                "ask_qty": _safe_int(ask_qty),
                "volume": _safe_int(payload.get("volume")),
                "oi": _safe_int(payload.get("open_interest")),
                "total_buy_qty": _safe_int(payload.get("total_buy_quantity")),
                "total_sell_qty": _safe_int(payload.get("total_sell_quantity")),
                "depth": depth_normalized,
            }

            return {
                "symbol": original.get("symbol", exchange_symbol),
                "exchange": original.get("exchange", "UNKNOWN"),
                "data": data,
            }

        consecutive_429 = 0
        overlaid = 0

        for idx, exchange_symbol in enumerate(exchange_symbols):
            quote_result = _fetch_one(exchange_symbol)
            err_str = str(quote_result.get("error", ""))

            if "429" in err_str or "Rate limit" in err_str:
                consecutive_429 += 1
                if consecutive_429 >= MAX_CONSECUTIVE_429:
                    logger.warning(
                        f"Aborting full-quote overlay after {consecutive_429} "
                        f"consecutive 429s; remaining {len(exchange_symbols) - idx - 1} "
                        f"strikes keep LTP/OHLC baseline only."
                    )
                    break
                continue
            consecutive_429 = 0

            if "error" in quote_result or "data" not in quote_result:
                continue

            original = symbol_map.get(exchange_symbol, {})
            target = result_index.get((original.get("symbol"), original.get("exchange")))
            if not target or "data" not in target:
                continue

            quote_data = quote_result["data"]
            # Merge enriched fields onto the OHLC baseline. Keep OHLC values
            # from the batch (they're the authoritative LTP/open/high/low) and
            # overlay the rest of OpenAlgo's multiquote fields: the documented
            # bid/ask/volume/oi plus bid_qty/ask_qty, as the reference broker
            # returns them for the option chain. Depth stays in the depth API.
            for key in (
                "bid",
                "ask",
                "bid_qty",
                "ask_qty",
                "volume",
                "oi",
            ):
                if key in quote_data:
                    target["data"][key] = quote_data[key]
            overlaid += 1

        logger.info(
            f"Full-quote overlay: {overlaid}/{len(exchange_symbols)} strikes enriched "
            f"with bid/ask/qty/volume/OI."
        )

