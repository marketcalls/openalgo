import json
import os
import threading
import time
from datetime import datetime, timedelta

import httpx
import pandas as pd

from broker.indmoney.api.baseurl import get_url
from database.token_db import get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# --- Poison scrip-code cache ---------------------------------------------
# IndStocks' /market/quotes/full 400-rejects the ENTIRE comma-separated batch
# if any single scrip code is unquotable (e.g. a deep-ITM option strike the
# server won't price). We isolate the offending code(s) via bisection and cache
# them here so subsequent quote calls skip them and stay a single fast batch.
# Cached codes are re-tested after a TTL in case they become quotable again.
_BAD_SCRIP_CODES = {}          # scrip_code -> monotonic() time it was marked bad
_BAD_SCRIP_TTL = 300.0         # seconds before a bad code is retried
_bad_scrip_lock = threading.Lock()


def _is_known_bad(scrip_code):
    """True if scrip_code is currently cached as unquotable (within TTL)."""
    with _bad_scrip_lock:
        ts = _BAD_SCRIP_CODES.get(scrip_code)
        if ts is None:
            return False
        if time.monotonic() - ts > _BAD_SCRIP_TTL:
            _BAD_SCRIP_CODES.pop(scrip_code, None)
            return False
        return True


def _mark_bad(scrip_code):
    """Cache scrip_code as unquotable so future batches skip it."""
    with _bad_scrip_lock:
        now = time.monotonic()
        _BAD_SCRIP_CODES[scrip_code] = now
        # Prune expired entries so the cache stays bounded on a long-running
        # worker that sees many one-off unquotable strikes over the day.
        for code, ts in list(_BAD_SCRIP_CODES.items()):
            if now - ts > _BAD_SCRIP_TTL:
                _BAD_SCRIP_CODES.pop(code, None)

# 429 (rate-limit) retry configuration. IndStocks enforces per-category rate
# limits (Data/Quote 5/s) and returns 429 on breach (docs 03-conventions /
# 14-errors), so requests retry with backoff.
_MAX_RETRIES = 3
_RATE_LIMIT_BASE_DELAY = 1.0  # seconds; doubled each attempt (1s, 2s, 4s)


def request_with_retry(client, method, url, **kwargs):
    """
    Perform an httpx request, retrying HTTP 429 with exponential backoff
    (honouring Retry-After when present). Sets ``.status`` for compatibility
    with the existing codebase.
    """
    response = None
    for attempt in range(_MAX_RETRIES):
        response = client.request(method.upper(), url, **kwargs)
        if response.status_code == 429 and attempt < _MAX_RETRIES - 1:
            retry_after = response.headers.get("Retry-After")
            try:
                delay = (
                    min(float(retry_after), 30.0)
                    if retry_after
                    else _RATE_LIMIT_BASE_DELAY * (2 ** attempt)
                )
            except (TypeError, ValueError):
                delay = _RATE_LIMIT_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"Rate limit hit (429) on {url}, retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{_MAX_RETRIES})"
            )
            time.sleep(delay)
            continue
        break
    if response is not None:
        response.status = response.status_code
    return response


def get_api_response(endpoint, auth, method="GET", params=None):
    AUTH_TOKEN = auth

    if not AUTH_TOKEN:
        raise Exception("Authentication token is required")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Log token info for debugging (mask the actual token)
    token_preview = (
        AUTH_TOKEN[:20] + "..." + AUTH_TOKEN[-10:] if len(AUTH_TOKEN) > 30 else AUTH_TOKEN
    )
    logger.debug(f"Using auth token: {token_preview}")

    headers = {
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    url = get_url(endpoint)

    logger.debug(f"Making request to {url}")
    logger.debug(f"Method: {method}")
    logger.debug(f"Headers: {headers}")
    logger.debug(f"Params: {params}")
    # Build query string for debugging
    if params:
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        logger.debug(f"Full URL with params: {url}?{query_string}")
    else:
        logger.debug(f"Full URL: {url}")

    try:
        # request_with_retry handles HTTP 429 with backoff and sets .status
        if method == "GET":
            res = request_with_retry(client, "GET", url, headers=headers, params=params)
        elif method == "POST":
            res = request_with_retry(client, "POST", url, headers=headers, json=params)
        else:
            res = request_with_retry(client, method, url, headers=headers, params=params)

        logger.debug(f"Request completed. Status code: {res.status_code}")
        logger.info(f"Actual request URL: {res.url}")

    except Exception as req_error:
        logger.error(f"Request failed: {str(req_error)}")
        raise Exception(f"Failed to make request to Indmoney API: {str(req_error)}")

    logger.debug(f"Response status: {res.status}")
    logger.debug(f"Raw response text: {res.text}")

    # Check if response is successful
    if res.status_code != 200:
        logger.error(f"HTTP Error {res.status_code}: {res.text}")
        raise Exception(f"Indmoney API HTTP Error {res.status_code}: {res.text}")

    # Try to parse JSON response
    try:
        response = json.loads(res.text)
        logger.debug(f"Parsed JSON response keys: {list(response.keys())}")
        logger.debug(f"Response status field: '{response.get('status')}'")
        logger.debug(f"Status field type: {type(response.get('status'))}")
        logger.debug(f"Status field length: {len(str(response.get('status')))}")
        logger.debug(f"Status field repr: {repr(response.get('status'))}")

        # Check if this is a successful data response even without explicit status
        has_valid_data = False

        if "data" in response:
            data = response["data"]
            # Check for direct array (alternative format)
            if isinstance(data, list) and len(data) > 0:
                has_valid_data = True
                logger.debug("Response contains direct data array, treating as successful")
            # Check for nested structure with 'candles' (documented format for historical API)
            elif (
                isinstance(data, dict)
                and "candles" in data
                and isinstance(data["candles"], list)
                and len(data["candles"]) > 0
            ):
                has_valid_data = True
                logger.info("Response contains nested candles array, treating as successful")

        if has_valid_data:
            # For historical data responses that don't have explicit status, add it
            if "status" not in response:
                response["status"] = "success"
                logger.debug("Added missing status field to successful data response")

        # Log full response only for smaller responses to avoid spam
        if len(res.text) < 5000:
            logger.debug(f"Full JSON response: {json.dumps(response, indent=2)}")
        else:
            logger.debug(f"Large response received ({len(res.text)} chars), logging summary only")
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        logger.error(f"Response text that failed to parse: {res.text}")
        raise Exception(f"Indmoney API returned invalid JSON: {str(e)}")

    # Handle Indmoney API error responses
    response_status = response.get("status")
    response_success = response.get("success")

    # Check if this is a successful data response - return early
    has_valid_data = False

    if "data" in response:
        data = response["data"]
        # Check for direct array (alternative format)
        if isinstance(data, list) and len(data) > 0:
            has_valid_data = True
            logger.debug("Response contains valid direct data array")
        # Check for nested structure with 'candles' (documented format: data.candles)
        elif (
            isinstance(data, dict)
            and "candles" in data
            and isinstance(data["candles"], list)
            and len(data["candles"]) > 0
        ):
            has_valid_data = True
            logger.debug("Response contains valid nested candles array")
        # Check for scrip-code nested structure (actual format: data[scrip_code].candles)
        elif isinstance(data, dict):
            for key, value in data.items():
                if (
                    isinstance(value, dict)
                    and "candles" in value
                    and isinstance(value["candles"], list)
                    and len(value["candles"]) > 0
                ):
                    has_valid_data = True
                    logger.info(
                        f"Response contains valid scrip-nested candles array under key: {key}"
                    )
                    break

    # Also check for success field (actual API uses this instead of status)
    if response_success is True:
        logger.debug("Response has success=true field")
        return response

    if has_valid_data:
        # For data responses that don't have explicit status, add it
        if "status" not in response or response_status != "success":
            response["status"] = "success"
            logger.debug("Added/corrected status field to successful data response")
        return response

    # Only check status if there's no valid data
    if response_status != "success" and response_success is not True:
        error_message = response.get("message", response.get("error", "Unknown error"))
        error_code = response.get("code", "unknown")
        logger.error(
            f"API Error - Status: '{response_status}' (code: {error_code}): {error_message}"
        )
        logger.error(f"Full error response: {json.dumps(response, indent=2)}")
        raise Exception(f"Indmoney API Error ({error_code}): {error_message}")
    else:
        logger.debug(
            f"API response successful with status: '{response_status}' or success: {response_success}"
        )

    return response


class BrokerData:
    def __init__(self, auth_token):
        """Initialize Indmoney data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Indmoney intervals
        self.timeframe_map = {
            # Seconds (max 1 day range)
            "1s": "1second",
            "5s": "5second",
            "10s": "10second",
            "15s": "15second",
            # Minutes (max 7 days range for 1-30m)
            "1m": "1minute",
            "2m": "2minute",
            "3m": "3minute",
            "4m": "4minute",
            "5m": "5minute",
            "10m": "10minute",
            "15m": "15minute",
            "30m": "30minute",
            # Hours (max 14 days range)
            "1h": "60minute",
            "2h": "120minute",
            "3h": "180minute",
            "4h": "240minute",
            # Daily (max 1 year range)
            "D": "1day",
            "W": "1week",
            "M": "1month",
        }

    def _get_scrip_code(self, symbol, exchange):
        """Convert symbol and exchange to Indmoney scrip code format"""
        # Get security ID/token for the symbol
        security_id = get_token(symbol, exchange)
        if not security_id:
            raise Exception(f"Could not find security ID for {symbol} on {exchange}")

        # Map exchange to Indmoney segment
        # Note: Index segments use NIDX/BIDX for API calls, not NSE/BSE
        exchange_segment_map = {
            "NSE": "NSE",
            "BSE": "BSE",
            "NFO": "NFO",
            "BFO": "BFO",
            "MCX": "MCX",
            "CDS": "CDS",
            "BCD": "BCD",
            "NSE_INDEX": "NIDX",  # NSE Index segment
            "BSE_INDEX": "BIDX",  # BSE Index segment
        }

        segment = exchange_segment_map.get(exchange)
        if not segment:
            raise Exception(f"Unsupported exchange: {exchange}")

        # Format: SEGMENT_INSTRUMENTTOKEN
        scrip_code = f"{segment}_{security_id}"
        logger.debug(
            f"Generated scrip code: {scrip_code} for symbol: {symbol}, exchange: {exchange}"
        )

        return scrip_code

    def _clean_number(self, value, default=0):
        """Clean comma-separated number strings and convert to appropriate type"""
        if value is None:
            return default

        # Convert to string and remove commas
        clean_value = str(value).replace(",", "").strip()

        # Handle empty or invalid values
        if not clean_value or clean_value == "":
            return default

        try:
            # Try to convert to float first, then to int if it's a whole number
            float_val = float(clean_value)
            if float_val.is_integer():
                return int(float_val)
            return float_val
        except (ValueError, AttributeError):
            return default

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Quote data with required fields
        """
        try:
            scrip_code = self._get_scrip_code(symbol, exchange)

            logger.info(f"Getting quotes for symbol: {symbol}, exchange: {exchange}")
            logger.debug(f"Using scrip code: {scrip_code}")

            params = {"scrip-codes": scrip_code}

            try:
                # Try the /full endpoint first for comprehensive quote data
                full_response = get_api_response(
                    "/market/quotes/full", self.auth_token, "GET", params
                )
                logger.debug(f"Full quotes response: {full_response}")
                full_data = full_response.get("data", {}).get(scrip_code, {})

                if full_data and any(
                    key in full_data for key in ["ltp", "live_price", "open", "high", "low"]
                ):
                    # Extract data from full quotes response
                    result = {
                        "ltp": self._clean_number(
                            full_data.get("live_price", full_data.get("ltp", 0))
                        ),
                        "open": self._clean_number(full_data.get("day_open", 0)),
                        "high": self._clean_number(full_data.get("day_high", 0)),
                        "low": self._clean_number(full_data.get("day_low", 0)),
                        "volume": self._clean_number(full_data.get("volume", 0)),
                        "prev_close": self._clean_number(
                            full_data.get("prev_close", full_data.get("close", 0))
                        ),
                        "oi": self._clean_number(
                            full_data.get("oi", full_data.get("open_interest", 0))
                        ),
                        "bid": 0,  # Will try to get from market depth if available
                        "ask": 0,  # Will try to get from market depth if available
                    }

                    # Try to extract bid/ask from market depth if available in full response
                    market_depth_container = full_data.get("market_depth", {})
                    market_depth = market_depth_container.get(scrip_code, {})
                    depth_levels = market_depth.get("depth", [])

                    if depth_levels and len(depth_levels) > 0:
                        first_level = depth_levels[0]
                        if "buy" in first_level:
                            result["bid"] = self._clean_number(first_level["buy"].get("price", 0))
                        if "sell" in first_level:
                            result["ask"] = self._clean_number(first_level["sell"].get("price", 0))

                    logger.debug(f"Successfully fetched full quotes: {result}")
                    return result

            except Exception as full_error:
                logger.warning(
                    f"Full quotes endpoint failed, falling back to separate calls: {str(full_error)}"
                )

            # Fallback to separate LTP and market depth calls
            ltp_data = {}
            bid_price = 0
            ask_price = 0

            # Get LTP data
            try:
                ltp_response = get_api_response(
                    "/market/quotes/ltp", self.auth_token, "GET", params
                )
                logger.debug(f"LTP Response: {ltp_response}")
                ltp_data = ltp_response.get("data", {}).get(scrip_code, {})
            except Exception as ltp_error:
                logger.warning(f"Could not fetch LTP data: {str(ltp_error)}")

            # Get market depth for bid/ask
            try:
                depth_response = get_api_response(
                    "/market/quotes/mkt", self.auth_token, "GET", params
                )
                depth_raw = depth_response.get("data", {}).get(scrip_code, {})

                # Handle the extra nesting level in market depth
                market_depth_container = depth_raw.get("market_depth", {})
                market_depth = market_depth_container.get(scrip_code, {})
                depth_levels = market_depth.get("depth", [])

                if depth_levels and len(depth_levels) > 0:
                    first_level = depth_levels[0]
                    if "buy" in first_level and "price" in first_level["buy"]:
                        bid_price = self._clean_number(first_level["buy"]["price"])
                    if "sell" in first_level and "price" in first_level["sell"]:
                        ask_price = self._clean_number(first_level["sell"]["price"])

                logger.debug(f"Extracted bid: {bid_price}, ask: {ask_price}")

            except Exception as depth_error:
                logger.warning(f"Could not fetch depth data for quotes: {str(depth_error)}")

            # Build the final result
            result = {
                "ltp": self._clean_number(ltp_data.get("live_price", 0)) if ltp_data else 0,
                "open": 0,  # OHLC data not available from LTP endpoint
                "high": 0,
                "low": 0,
                "volume": 0,  # Volume not available from LTP endpoint
                "oi": 0,  # Open interest not available
                "bid": bid_price,
                "ask": ask_price,
                "prev_close": 0,  # Previous close not available from LTP endpoint
            }

            logger.debug(f"Final quotes result: {result}")
            return result

        except Exception as e:
            logger.error(f"Error in get_quotes: {str(e)}", exc_info=True)
            # Return default structure with error info
            return {
                "ltp": 0,
                "open": 0,
                "high": 0,
                "low": 0,
                "volume": 0,
                "bid": 0,
                "ask": 0,
                "prev_close": 0,
                "oi": 0,
                "error": str(e),
            }

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
            BATCH_SIZE = 500  # Indmoney API batch size limit
            RATE_LIMIT_DELAY = 0.3  # Delay in seconds between batch API calls

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
                    batch_results = self._process_multiquotes_batch(batch)
                    all_results.extend(batch_results)

                    # Rate limit delay between batches
                    if i + BATCH_SIZE < len(symbols):
                        time.sleep(RATE_LIMIT_DELAY)

                logger.info(
                    f"Successfully processed {len(all_results)} quotes in {(len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE} batches"
                )
                return all_results
            else:
                # Single batch processing
                return self._process_multiquotes_batch(symbols)

        except Exception as e:
            logger.exception("Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _fetch_full_quotes_map(self, scrip_codes):
        """
        Fetch /market/quotes/full for a list of scrip codes, tolerating
        'poison' codes. IndStocks 400-rejects the whole batch if ANY single
        code is unquotable, so on a 400 we bisect to isolate and drop the bad
        code(s); valid codes still return data. Bad codes are cached (with TTL)
        so later calls skip them and stay a single fast request.

        Returns: {scrip_code: raw_quote_dict} for the codes that returned data.
        """
        if not scrip_codes:
            return {}

        # Skip codes already known to poison the batch (re-tested after TTL)
        codes = [c for c in scrip_codes if not _is_known_bad(c)]
        if not codes:
            return {}

        try:
            params = {"scrip-codes": ",".join(codes)}
            response = get_api_response("/market/quotes/full", self.auth_token, "GET", params)
            return response.get("data", {}) or {}
        except Exception as e:
            msg = str(e)
            # A 400 carrying the server's "Invalid scrip codes or mode" text
            # means at least one code in this batch is unquotable — only those
            # are worth bisecting. Match the phrase specifically (not any "400")
            # so an unrelated 400 (bad param, etc.) doesn't blacklist valid
            # codes for the whole TTL.
            bad_batch = "Invalid scrip" in msg

            if len(codes) == 1:
                if bad_batch:
                    logger.warning(f"Marking unquotable scrip code as bad: {codes[0]}")
                    _mark_bad(codes[0])
                else:
                    logger.error(f"Quote fetch failed for {codes[0]}: {e}")
                return {}

            if not bad_batch:
                # Network/auth/other error - don't hammer the API by bisecting
                logger.error(f"Quote fetch failed for {len(codes)} codes: {e}")
                return {}

            # Bisect to isolate the poison code(s)
            mid = len(codes) // 2
            left = self._fetch_full_quotes_map(codes[:mid])
            right = self._fetch_full_quotes_map(codes[mid:])
            left.update(right)
            return left

    def _process_multiquotes_batch(self, symbols: list) -> list:
        """
        Process a single batch of symbols (internal method)
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys
        Returns:
            list: List of quote data for the batch
        """
        results = []
        skipped_symbols = []
        scrip_codes = []
        symbol_map = {}  # Map scrip_code back to original symbol/exchange

        for item in symbols:
            symbol = item.get("symbol")
            exchange = item.get("exchange")

            if not symbol or not exchange:
                logger.warning(f"Skipping entry due to missing symbol/exchange: {item}")
                skipped_symbols.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "error": "Missing required symbol or exchange",
                    }
                )
                continue

            try:
                scrip_code = self._get_scrip_code(symbol, exchange)
                scrip_codes.append(scrip_code)
                symbol_map[scrip_code] = {"symbol": symbol, "exchange": exchange}
            except Exception as e:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: {str(e)}")
                skipped_symbols.append(
                    {"symbol": symbol, "exchange": exchange, "error": str(e)}
                )

        # Return skipped symbols if no valid symbols
        if not scrip_codes:
            logger.warning("No valid symbols to fetch quotes for")
            return skipped_symbols

        # Fetch quotes, tolerating poison codes that would otherwise 400 the
        # whole batch. Returns {scrip_code: raw_quote} for codes with data.
        quotes_data = self._fetch_full_quotes_map(scrip_codes)
        logger.debug(f"Multiquotes returned data for {len(quotes_data)} of {len(scrip_codes)} codes")

        succeeded = 0
        for scrip_code, original in symbol_map.items():
            quote = quotes_data.get(scrip_code, {})

            if quote and any(
                key in quote for key in ["ltp", "live_price", "day_open", "day_high", "day_low"]
            ):
                succeeded += 1
                results.append(
                    {
                        "symbol": original["symbol"],
                        "exchange": original["exchange"],
                        "data": {
                            "bid": 0,  # Will be 0 unless we fetch depth
                            "ask": 0,
                            "open": self._clean_number(quote.get("day_open", 0)),
                            "high": self._clean_number(quote.get("day_high", 0)),
                            "low": self._clean_number(quote.get("day_low", 0)),
                            "ltp": self._clean_number(
                                quote.get("live_price", quote.get("ltp", 0))
                            ),
                            "prev_close": self._clean_number(
                                quote.get("prev_close", quote.get("close", 0))
                            ),
                            "volume": self._clean_number(quote.get("volume", 0)),
                            "oi": self._clean_number(quote.get("oi", quote.get("open_interest", 0))),
                        },
                    }
                )
            else:
                # No quote for this symbol (e.g. an unquotable strike). Omit the
                # "data" key (and include "error") so downstream consumers treat
                # it as missing and default to {} rather than hitting a None.
                results.append(
                    {
                        "symbol": original["symbol"],
                        "exchange": original["exchange"],
                        "error": "No data received",
                    }
                )

        logger.info(f"Retrieved quotes for {succeeded} / {len(symbols)} symbols")
        return skipped_symbols + results

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data with bids and asks
        """
        try:
            scrip_code = self._get_scrip_code(symbol, exchange)

            logger.info(f"Getting depth for symbol: {symbol}, exchange: {exchange}")
            logger.debug(f"Using scrip code: {scrip_code}")

            params = {"scrip-codes": scrip_code}

            # For index symbols or to get OHLC data, try full quotes first
            full_quotes_data = {}
            try:
                full_response = get_api_response(
                    "/market/quotes/full", self.auth_token, "GET", params
                )
                full_quotes_data = full_response.get("data", {}).get(scrip_code, {})
                logger.debug(f"Full quotes data retrieved for OHLC: {bool(full_quotes_data)}")
            except Exception as full_error:
                logger.warning(f"Could not fetch full quotes for OHLC: {str(full_error)}")

            try:
                # Get market depth from Indmoney API
                depth_response = get_api_response(
                    "/market/quotes/mkt", self.auth_token, "GET", params
                )
                depth_data = depth_response.get("data", {}).get(scrip_code, {})

                # Try to get LTP data as fallback
                quotes_data = {}
                try:
                    ltp_response = get_api_response(
                        "/market/quotes/ltp", self.auth_token, "GET", params
                    )
                    quotes_data = ltp_response.get("data", {}).get(scrip_code, {})
                except Exception as ltp_error:
                    logger.warning(f"Could not fetch LTP data: {str(ltp_error)}")

                if not depth_data:
                    # No depth data available (common for indices)
                    # But we may have OHLC data from full quotes
                    ltp = 0
                    open_p = 0
                    high = 0
                    low = 0
                    prev_close_p = 0
                    vol = 0
                    oi_val = 0

                    if full_quotes_data:
                        ltp = self._clean_number(
                            full_quotes_data.get("live_price", full_quotes_data.get("ltp", 0))
                        )
                        open_p = self._clean_number(full_quotes_data.get("day_open", 0))
                        high = self._clean_number(full_quotes_data.get("day_high", 0))
                        low = self._clean_number(full_quotes_data.get("day_low", 0))
                        prev_close_p = self._clean_number(
                            full_quotes_data.get("prev_close", full_quotes_data.get("close", 0))
                        )
                        vol = self._clean_number(full_quotes_data.get("volume", 0))
                        oi_val = self._clean_number(
                            full_quotes_data.get("oi", full_quotes_data.get("open_interest", 0))
                        )
                    elif quotes_data and "live_price" in quotes_data:
                        ltp = self._clean_number(quotes_data.get("live_price", 0))

                    return {
                        "bids": [{"price": 0, "quantity": 0} for _ in range(5)],
                        "asks": [{"price": 0, "quantity": 0} for _ in range(5)],
                        "ltp": ltp,
                        "ltq": 0,
                        "volume": vol,
                        "open": open_p,
                        "high": high,
                        "low": low,
                        "prev_close": prev_close_p,
                        "oi": oi_val,
                        "totalbuyqty": 0,
                        "totalsellqty": 0,
                    }

                # Process market depth - handle the extra nesting level
                market_depth_container = depth_data.get("market_depth", {})
                # Indmoney has an extra nesting level with the scrip code
                market_depth = market_depth_container.get(scrip_code, {})
                depth_levels = market_depth.get("depth", [])
                aggregate = market_depth.get("aggregate", {})

                # Prepare bids and asks arrays
                bids = []
                asks = []

                # Process depth levels (up to 5 levels)
                for i in range(5):
                    if i < len(depth_levels):
                        level = depth_levels[i]
                        buy_data = level.get("buy", {})
                        sell_data = level.get("sell", {})

                        # Use _clean_number to handle comma-separated values
                        bids.append(
                            {
                                "price": self._clean_number(buy_data.get("price", 0)),
                                "quantity": self._clean_number(buy_data.get("quantity", 0)),
                            }
                        )

                        asks.append(
                            {
                                "price": self._clean_number(sell_data.get("price", 0)),
                                "quantity": self._clean_number(sell_data.get("quantity", 0)),
                            }
                        )
                    else:
                        bids.append({"price": 0, "quantity": 0})
                        asks.append({"price": 0, "quantity": 0})

                # Calculate total buy/sell quantities
                # Try to get from aggregate data first, then calculate from depth
                try:
                    total_buy = aggregate.get("total_buy", "0")
                    total_sell = aggregate.get("total_sell", "0")

                    # Use _clean_number to handle comma-separated values
                    totalbuyqty = (
                        self._clean_number(total_buy)
                        if total_buy
                        else sum(bid["quantity"] for bid in bids)
                    )
                    totalsellqty = (
                        self._clean_number(total_sell)
                        if total_sell
                        else sum(ask["quantity"] for ask in asks)
                    )
                except Exception:
                    # Fallback to calculation from depth
                    totalbuyqty = sum(bid["quantity"] for bid in bids)
                    totalsellqty = sum(ask["quantity"] for ask in asks)

                # Build final result - prioritize full quotes for OHLC, then LTP data
                ltp_price = 0
                open_price = 0
                high_price = 0
                low_price = 0
                prev_close = 0
                volume = 0
                oi = 0

                # Try to get data from full quotes first (has OHLC)
                if full_quotes_data:
                    ltp_price = self._clean_number(
                        full_quotes_data.get("live_price", full_quotes_data.get("ltp", 0))
                    )
                    open_price = self._clean_number(full_quotes_data.get("day_open", 0))
                    high_price = self._clean_number(full_quotes_data.get("day_high", 0))
                    low_price = self._clean_number(full_quotes_data.get("day_low", 0))
                    prev_close = self._clean_number(
                        full_quotes_data.get("prev_close", full_quotes_data.get("close", 0))
                    )
                    volume = self._clean_number(full_quotes_data.get("volume", 0))
                    oi = self._clean_number(
                        full_quotes_data.get("oi", full_quotes_data.get("open_interest", 0))
                    )
                # Fallback to LTP data if full quotes not available
                elif quotes_data and "live_price" in quotes_data:
                    ltp_price = self._clean_number(quotes_data.get("live_price", 0))
                # Last resort: use best bid price as approximation
                elif bids and bids[0]["price"] > 0:
                    ltp_price = bids[0]["price"]

                result = {
                    "bids": bids,
                    "asks": asks,
                    "ltp": ltp_price,
                    "ltq": 0,  # Last traded quantity not available in Indmoney API
                    "volume": volume,
                    "open": open_price,
                    "high": high_price,
                    "low": low_price,
                    "prev_close": prev_close,
                    "oi": oi,
                    "totalbuyqty": totalbuyqty,
                    "totalsellqty": totalsellqty,
                }

                return result

            except Exception as api_error:
                logger.error(f"API error in get_depth: {str(api_error)}")
                return {
                    "bids": [{"price": 0, "quantity": 0} for _ in range(5)],
                    "asks": [{"price": 0, "quantity": 0} for _ in range(5)],
                    "ltp": 0,
                    "ltq": 0,
                    "volume": 0,
                    "open": 0,
                    "high": 0,
                    "low": 0,
                    "prev_close": 0,
                    "oi": 0,
                    "totalbuyqty": 0,
                    "totalsellqty": 0,
                    "error": str(api_error),
                }

        except Exception as e:
            logger.error(f"Error in get_depth: {str(e)}", exc_info=True)
            raise Exception(f"Error fetching market depth: {str(e)}")

    def get_history(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Candle interval in common format:
                     Minutes: 1m, 5m, 15m, 30m
                     Hours: 1h, 2h, 3h, 4h
                     Days: D
            start_date: Start date (YYYY-MM-DD) in IST
            end_date: End date (YYYY-MM-DD) in IST
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume, oi]
        """
        try:
            # Convert date objects to strings if needed
            if not isinstance(start_date, str):
                start_date = start_date.strftime("%Y-%m-%d")
            if not isinstance(end_date, str):
                end_date = end_date.strftime("%Y-%m-%d")

            # Map OpenAlgo intervals to Indmoney intervals using timeframe_map
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(
                    f"Unsupported interval '{interval}'. Supported intervals are: {', '.join(supported)}"
                )

            indmoney_interval = self.timeframe_map[interval]
            scrip_code = self._get_scrip_code(symbol, exchange)

            logger.info(f"Getting history for symbol: {symbol}, exchange: {exchange}")
            logger.debug(f"Interval: {interval} -> {indmoney_interval}")
            logger.debug(f"Date range: {start_date} to {end_date}")
            logger.debug(f"Using scrip code: {scrip_code}")

            # Convert dates to Unix timestamps (milliseconds) in IST
            start_timestamp = self._date_to_timestamp_ms(start_date)
            end_timestamp = self._date_to_timestamp_ms(end_date, end_of_day=True)

            logger.debug(f"Timestamp range: {start_timestamp} to {end_timestamp}")

            # Check if date range exceeds Indmoney limits
            max_ranges = {
                "1second": 1,
                "5second": 1,
                "10second": 1,
                "15second": 1,  # 1 day
                "1minute": 7,
                "2minute": 7,
                "3minute": 7,
                "4minute": 7,
                "5minute": 7,  # 7 days
                "10minute": 7,
                "15minute": 7,
                "30minute": 7,  # 7 days
                "60minute": 14,
                "120minute": 14,
                "180minute": 14,
                "240minute": 14,  # 14 days
                "1day": 365,
                "1week": 365,
                "1month": 365,  # 1 year
            }

            max_days = max_ranges.get(indmoney_interval, 7)
            date_chunks = self._split_date_range(start_date, end_date, max_days)

            logger.debug(f"Split into {len(date_chunks)} chunks: {date_chunks}")

            all_candles = []

            for chunk_start, chunk_end in date_chunks:
                try:
                    chunk_start_ts = self._date_to_timestamp_ms(chunk_start)
                    chunk_end_ts = self._date_to_timestamp_ms(chunk_end, end_of_day=True)

                    params = {
                        "scrip-codes": scrip_code,
                        "start_time": str(chunk_start_ts),
                        "end_time": str(chunk_end_ts),
                    }

                    endpoint = f"/market/historical/{indmoney_interval}"
                    logger.debug(f"Fetching chunk {chunk_start} to {chunk_end}")
                    logger.info(f"Request params: {params}")

                    response = get_api_response(endpoint, self.auth_token, "GET", params)

                    # Extract candles from response - handle actual Indmoney format
                    # Actual format: {"data": {"NSE_1594": {"candles": [...]}}}
                    data_obj = response.get("data", {})
                    candles_data = []

                    # Try scrip-code nested structure first (actual format)
                    if isinstance(data_obj, dict) and scrip_code in data_obj:
                        scrip_data = data_obj[scrip_code]
                        if isinstance(scrip_data, dict) and "candles" in scrip_data:
                            candles_data = scrip_data["candles"] or []  # Handle None/null
                            logger.debug(
                                f"Extracted candles from scrip-nested structure: {scrip_code}"
                            )
                    # Try direct nested structure (documented format: data.candles)
                    elif isinstance(data_obj, dict) and "candles" in data_obj:
                        candles_data = data_obj.get("candles") or []  # Handle None/null
                        logger.debug("Extracted candles from direct nested structure")
                    # Fallback to direct array (alternative format)
                    elif isinstance(data_obj, list):
                        candles_data = data_obj
                        logger.debug("Extracted candles from direct array")

                    # Ensure candles_data is always a list (handle None/null from API)
                    if candles_data is None:
                        candles_data = []

                    logger.debug(f"Received {len(candles_data)} candles for chunk")

                    # Transform Indmoney candle format to OpenAlgo format
                    chunk_candles = []
                    for candle in candles_data:
                        try:
                            # Handle the actual format: {"ts": timestamp, "o": open, "h": high, "l": low, "c": close, "v": volume}
                            if isinstance(candle, dict) and "ts" in candle:
                                # Note: API doc says milliseconds, but actual data is in seconds
                                timestamp_seconds = int(candle.get("ts", 0))

                                chunk_candles.append(
                                    {
                                        "timestamp": timestamp_seconds,
                                        "open": float(candle.get("o", 0)),
                                        "high": float(candle.get("h", 0)),
                                        "low": float(candle.get("l", 0)),
                                        "close": float(candle.get("c", 0)),
                                        "volume": int(candle.get("v", 0)),
                                        "oi": 0,  # Open interest not available in Indmoney historical data
                                    }
                                )
                            # Also handle documented format as fallback
                            elif isinstance(candle, list) and len(candle) >= 6:
                                # Convert timestamp from milliseconds to seconds
                                timestamp_seconds = int(candle[0] / 1000)

                                chunk_candles.append(
                                    {
                                        "timestamp": timestamp_seconds,
                                        "open": float(candle[1]),
                                        "high": float(candle[2]),
                                        "low": float(candle[3]),
                                        "close": float(candle[4]),
                                        "volume": int(candle[5]) if candle[5] else 0,
                                        "oi": 0,  # Open interest not available in Indmoney historical data
                                    }
                                )
                        except Exception as candle_error:
                            logger.error(
                                f"Error processing individual candle {candle}: {str(candle_error)}"
                            )
                            continue

                    logger.debug(f"Successfully processed {len(chunk_candles)} candles from chunk")
                    all_candles.extend(chunk_candles)

                except Exception as chunk_error:
                    logger.error(
                        f"Error fetching chunk {chunk_start} to {chunk_end}: {str(chunk_error)}"
                    )
                    logger.error(f"Chunk error type: {type(chunk_error).__name__}")
                    logger.error(f"Chunk error details: {repr(chunk_error)}")
                    logger.exception("Full traceback for chunk error")
                    continue

            logger.info(f"Total candles collected from all chunks: {len(all_candles)}")

            # Create DataFrame from all candles
            if all_candles:
                df = pd.DataFrame(all_candles)
                # Sort by timestamp and remove duplicates
                df = (
                    df.sort_values("timestamp")
                    .drop_duplicates(subset=["timestamp"])
                    .reset_index(drop=True)
                )
                logger.debug(f"Successfully fetched {len(df)} candles after deduplication")
                logger.debug(
                    f"Sample data: {df.head(3).to_dict('records') if len(df) > 0 else 'No data'}"
                )
            else:
                df = pd.DataFrame(
                    columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
                )
                logger.warning("No historical data received from any chunks")

            return df

        except Exception as e:
            logger.error(f"Error fetching historical data: {str(e)}")
            raise Exception(f"Error fetching historical data: {str(e)}")

    def _date_to_timestamp_ms(self, date_str: str, end_of_day: bool = False) -> int:
        """Convert date string to Unix timestamp in milliseconds (IST)"""

        if end_of_day:
            # For end date, use end of day (23:59:59)
            dt = datetime.strptime(f"{date_str} 23:59:59", "%Y-%m-%d %H:%M:%S")
        else:
            # For start date, use start of day (00:00:00)
            dt = datetime.strptime(f"{date_str} 00:00:00", "%Y-%m-%d %H:%M:%S")

        # Convert to Unix timestamp and then to milliseconds
        timestamp_ms = int(dt.timestamp() * 1000)
        return timestamp_ms

    def _split_date_range(self, start_date: str, end_date: str, max_days: int) -> list:
        """Split date range into chunks based on Indmoney API limits"""

        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        chunks = []

        current = start
        while current < end:
            chunk_end = min(current + timedelta(days=max_days - 1), end)
            chunks.append((current.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")))
            current = chunk_end + timedelta(days=1)

        return chunks

    def get_intervals(self) -> list:
        """
        Get list of supported timeframes/intervals for historical data.

        Returns:
            list: List of supported interval strings like ['1s', '5s', '1m', '5m', '15m', '1h', 'D', etc.]
        """
        return list(self.timeframe_map.keys())
