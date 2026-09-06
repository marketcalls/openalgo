import json
import threading
import time
import urllib.parse
from datetime import timedelta

import httpx
import pandas as pd

from database.token_db import get_br_symbol, get_brexchange, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Neo serves historical data for these four segments only. cde_fo (CDS) and
# mcx_fo (MCX) are quote-only, even though the plugin trades them.
HISTORY_SEGMENTS = {"nse_cm", "nse_fo", "bse_cm", "bse_fo"}

# Widest span the backend accepts in one request, keyed by Neo interval. A wider
# request is rejected outright rather than truncated, so the fetch loop chunks
# to these and stitches the pieces back together.
HISTORY_CHUNK_DAYS = {
    "1min": 30,
    "3min": 30,
    "5min": 30,
    "10min": 60,
    "15min": 60,
    "30min": 90,
    "60min": 90,
    "D": 180,
    "W": 180,
}

# A Neo candle is a positional row already in the OpenAlgo column order.
HISTORY_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "oi"]

# Measured, not published. Neo documents no historical rate limit, but the
# endpoint starts returning HTTP 429 after roughly five requests in one second:
# probed 2026-09-06, 12 back-to-back requests got 5 successes then 429s, while a
# 0.5s gap sustained 10/10. Paced just under the observed ceiling for headroom.
# Two years of 1 minute data is ~25 sequential chunks, so this is the knob that
# decides whether a long pull completes or dies half way.
HISTORY_RATE_LIMIT_PER_SEC = 4
HISTORY_MIN_INTERVAL = 1.0 / HISTORY_RATE_LIMIT_PER_SEC

# Neo sends no Retry-After, so a 429 backs off exponentially: 1s, 2s, 4s, 8s.
HISTORY_MAX_RETRIES = 4
HISTORY_BASE_BACKOFF = 1.0

# Module level, never on BrokerData. Services build a fresh instance per request
# (see services/history_service.py), so pacing state held on the instance is
# reset away every call and throttles nothing across concurrent requests.
_history_rate_lock = threading.Lock()
_history_last_call = 0.0


def _history_pace():
    """Reserve the next historical request slot.

    Reserved inside the lock so concurrent callers cannot claim the same slot,
    slept outside it so waiters do not block one another.
    """
    global _history_last_call
    with _history_rate_lock:
        now = time.time()
        wait = max(0.0, _history_last_call + HISTORY_MIN_INTERVAL - now)
        _history_last_call = now + wait
    if wait > 0:
        time.sleep(wait)


# Neo reports a range holding no candles as a 400 fault rather than an empty
# success, so these have to be told apart from a real failure by their text. A
# pull whose last chunk lands on a weekend, a holiday, or today before the open
# is the ordinary case, not an error.
# Both observed live: "No data found" for a weekend, and the longer
# "Data not available ... Market has not yet opened" for today before the open.
# "Invalid neosymbol" is deliberately absent, being a real error.
_NO_DATA_MARKERS = (
    "no data found",
    "data not available",
    "no data is available",
    "market has not yet opened",
)


def _is_no_data_fault(message: str) -> bool:
    """True when Neo is saying the range is empty, not that the request is bad."""
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _NO_DATA_MARKERS)


def _history_retry_delay(headers, attempt: int) -> float:
    """Prefer the server's own guidance. Neo sends none, so back off."""
    value = headers.get("Retry-After") or headers.get("retry-after")
    if value:
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            pass
    return HISTORY_BASE_BACKOFF * (2**attempt)


class BrokerData:
    def __init__(self, auth_token):
        # Updated for Neo API v2: session_token:::session_sid:::base_url:::access_token
        self.session_token, self.session_sid, self.base_url, self.access_token = auth_token.split(
            ":::"
        )

        # baseUrl is mandatory; it comes from MPIN validation. Raise if missing.
        if not self.base_url or not self.base_url.startswith("http"):
            raise ValueError(
                "Kotak auth token missing baseUrl. Please re-login (TOTP + MPIN) to refresh credentials."
            )

        self.base_url = self.base_url.rstrip("/")
        self.quotes_base_url = self.base_url  # Use broker-provided baseUrl for quotes
        self.last_quote_error = None
        logger.info(f"Using quotes baseUrl: {self.quotes_base_url}")

        # OpenAlgo interval -> Neo interval. "60m" is an accepted alias for "1h":
        # intervals_service drops it from what it advertises because it is not a
        # canonical interval, but it keeps working as input.
        self.timeframe_map = {
            # Minutes
            "1m": "1min",
            "3m": "3min",
            "5m": "5min",
            "10m": "10min",
            "15m": "15min",
            "30m": "30min",
            # Hours
            "1h": "60min",
            "60m": "60min",
            # Daily and weekly
            "D": "D",
            "W": "W",
        }

    def _get_kotak_exchange(self, exchange):
        """Map OpenAlgo exchange to Kotak exchange segment"""
        exchange_map = {
            "NSE": "nse_cm",
            "BSE": "bse_cm",
            "NFO": "nse_fo",
            "BFO": "bse_fo",
            "CDS": "cde_fo",
            "MCX": "mcx_fo",
            "NSE_INDEX": "nse_cm",
            "BSE_INDEX": "bse_cm",
        }
        return exchange_map.get(exchange)

    def _get_index_symbol_candidates(self, symbol):
        """Return candidate Neo API neoSymbol names for an OpenAlgo index symbol.

        Kotak Neo's /quotes/neosymbol endpoint expects an exact name match. The
        canonical name differs per index and is not always derivable from the
        master contract (which often stores just the short ticker). We try
        descriptive variants in priority order and stop at the first hit.
        """
        index_map = {
            "NIFTY": ["Nifty 50"],
            "NIFTY50": ["Nifty 50"],
            "BANKNIFTY": ["Nifty Bank"],
            "FINNIFTY": ["Nifty Fin Service"],
            "MIDCPNIFTY": [
                "Nifty Mid Select",
                "Nifty Midcap Sel",
                "Nifty Midcap Select",
                "NIFTY MID SELECT",
            ],
            "NIFTYNXT50": ["Nifty Next 50"],
            "INDIAVIX": ["India VIX"],
            "SENSEX": ["SENSEX"],
            "BANKEX": ["BANKEX"],
        }
        key = symbol.upper()
        return index_map.get(key, [symbol])

    def _make_quotes_request(self, query, filter_name="all"):
        """Make HTTP request to Neo API v2 quotes endpoint using httpx connection pooling"""
        client = get_httpx_client()

        # URL encode spaces but keep pipe/comma characters
        encoded_query = urllib.parse.quote(query, safe="|,")
        endpoint = f"/script-details/1.0/quotes/neosymbol/{encoded_query}/{filter_name}"

        headers = {"Authorization": self.access_token, "Content-Type": "application/json"}

        url = f"{self.quotes_base_url}{endpoint}"
        last_error = None

        try:
            logger.info(f"QUOTES API - Making request to: {url}")
            logger.debug(f"QUOTES API - Using access_token: {self.access_token[:10]}...")

            response = client.get(url, headers=headers)
            logger.info(f"QUOTES API - Response status: {response.status_code} for {url}")

            if response.status_code == 200:
                response_data = json.loads(response.text)
                logger.debug(
                    f"QUOTES API - Raw response: {response.text[:200]}..."
                )  # Log first 200 chars

                # Kotak Neo returns 200 with {"stat":"Not_Ok","emsg":...,"stCode":1009}
                # when the instrument/code is invalid. Surface that as an error.
                if isinstance(response_data, dict) and response_data.get("stat") == "Not_Ok":
                    self.last_quote_error = {
                        "stat": "Not_Ok",
                        "emsg": response_data.get("emsg"),
                        "stCode": response_data.get("stCode"),
                        "url": url,
                    }
                    logger.warning(
                        f"QUOTES API - Neo error: {response_data.get('emsg')} (stCode={response_data.get('stCode')})"
                    )
                    return None

                # Log the complete structure for debugging (only for depth requests)
                if (
                    "depth" in endpoint
                    and response_data
                    and isinstance(response_data, list)
                    and len(response_data) > 0
                ):
                    logger.debug(
                        f"DEPTH API - Complete raw response structure: {json.dumps(response_data[0], indent=2)}"
                    )

                self.last_quote_error = None
                return response_data

            last_error = {"status": response.status_code, "body": response.text[:500], "url": url}
            logger.warning(f"QUOTES API - HTTP {response.status_code}: {response.text[:200]}...")

        except httpx.HTTPError as e:
            last_error = {"error": str(e), "url": url}
            logger.error(f"HTTP error in _make_quotes_request ({url}): {e}")
        except Exception as e:
            last_error = {"error": str(e), "url": url}
            logger.error(f"Error in _make_quotes_request ({url}): {e}")

        self.last_quote_error = last_error
        return None

    def _query_index_with_candidates(self, kotak_exchange, candidates, filter_name="all"):
        """Try each candidate index name until one returns data.

        Kotak Neo's neoSymbol endpoint requires exact case-sensitive names that
        aren't always present in the scrip master, so we probe known variants.
        Returns (response, query_used) or (None, last_query_tried).
        """
        last_query = None
        for cand in candidates:
            query = f"{kotak_exchange}|{cand}"
            last_query = query
            response = self._make_quotes_request(query, filter_name)
            if response and isinstance(response, list) and len(response) > 0:
                return response, query
        return None, last_query

    def get_quotes(self, symbol, exchange):
        """Get live quotes using Neo API v2 quotes endpoint with pSymbol-based queries"""
        try:
            logger.info(f"QUOTES API - Symbol: {symbol}, Exchange: {exchange}")

            # Check if this is an index - use symbol name instead of pSymbol
            if "INDEX" in exchange.upper():
                # For indices, map to correct Neo API format and use static exchange mapping
                kotak_exchange = self._get_kotak_exchange(exchange)
                candidates = self._get_index_symbol_candidates(symbol)
                logger.info(
                    f"QUOTES API - Index candidates for {symbol}: {candidates}"
                )
                response, query = self._query_index_with_candidates(
                    kotak_exchange, candidates, "all"
                )
                if response is None:
                    logger.error(
                        f"QUOTES API - All index candidates failed for {symbol}; last query: {query}"
                    )
                    return None
                logger.info(f"QUOTES API - Index resolved via: {query}")
            else:
                # For regular stocks/F&O, get both pSymbol and brexchange from database
                # In Kotak DB: token = pSymbol, brexchange = nse_cm/nse_fo/bse_cm etc.
                psymbol = get_token(symbol, exchange)
                brexchange = get_brexchange(symbol, exchange)
                logger.info(f"QUOTES API - pSymbol: {psymbol}, brexchange: {brexchange}")

                if not psymbol or not brexchange:
                    logger.error(f"pSymbol or brexchange not found for {symbol} on {exchange}")
                    return self._get_default_quote()

                # Map brexchange to correct Kotak format if needed
                if brexchange in ["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"]:
                    kotak_exchange = self._get_kotak_exchange(brexchange)
                    logger.info(f"QUOTES API - Mapped {brexchange} to {kotak_exchange}")
                else:
                    kotak_exchange = brexchange  # Already in correct format

                # Build query using mapped exchange: kotak_exchange|pSymbol
                query = f"{kotak_exchange}|{psymbol}"
                logger.info(f"QUOTES API - Query: {query}")

                # Make API request (index branch already fetched response above)
                response = self._make_quotes_request(query, "all")

            if response and isinstance(response, list) and len(response) > 0:
                quote_data = response[0]
                logger.info(
                    f"QUOTES API - Query successful for: {quote_data.get('display_symbol')}"
                )
            else:
                logger.error(
                    f"QUOTES API - Query failed for {symbol}; last_error={self.last_quote_error}"
                )
                return None

            if response and isinstance(response, list) and len(response) > 0:
                quote_data = response[0]

                # Parse Neo API v2 response format (based on actual API response)
                ohlc_data = quote_data.get("ohlc", {})
                ltp_parsed = float(quote_data.get("ltp", 0))

                # Get depth data for actual bid/ask prices
                depth_data = quote_data.get("depth", {})
                buy_orders = depth_data.get("buy", [])
                sell_orders = depth_data.get("sell", [])

                # Extract best bid and ask prices from depth
                bid_price = float(buy_orders[0].get("price", 0)) if buy_orders else ltp_parsed
                ask_price = float(sell_orders[0].get("price", 0)) if sell_orders else ltp_parsed

                # Get total quantities (for reference)
                total_buy_qty = quote_data.get("total_buy", 0)
                total_sell_qty = quote_data.get("total_sell", 0)

                logger.debug(
                    f"QUOTES API - Parsing for {quote_data.get('display_symbol', 'unknown')}:"
                )
                logger.debug(f"  - ltp: {ltp_parsed}")
                logger.debug(f"  - total_buy_qty: {total_buy_qty} (quantity, not price)")
                logger.debug(f"  - total_sell_qty: {total_sell_qty} (quantity, not price)")
                logger.debug(f"  - best_bid_price: {bid_price}")
                logger.debug(f"  - best_ask_price: {ask_price}")

                return {
                    "bid": bid_price,
                    "ask": ask_price,
                    "open": float(ohlc_data.get("open", 0)),
                    "high": float(ohlc_data.get("high", 0)),
                    "low": float(ohlc_data.get("low", 0)),
                    "ltp": ltp_parsed,
                    "prev_close": float(ohlc_data.get("close", 0)),
                    "volume": float(quote_data.get("last_volume", 0)),
                    "oi": int(quote_data.get("open_int", 0)),  # Available in response
                }
            elif response is not None:
                # API returned 200 but empty response - this is normal for some symbols
                logger.info(f"Empty response received for {symbol} - API returned 200 but no data")
                return self._get_default_quote()
            else:
                logger.warning(f"No quote data received for {symbol}")
                return self._get_default_quote()

        except Exception as e:
            logger.error(f"Error in get_quotes: {e}")
            return self._get_default_quote()

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Get market depth using Neo API v2 quotes endpoint with depth filter"""
        try:
            logger.info(f"DEPTH API - Symbol: {symbol}, Exchange: {exchange}")

            # Check if this is an index - use symbol name instead of pSymbol
            if "INDEX" in exchange.upper():
                # For indices, map to correct Neo API format and use static exchange mapping
                kotak_exchange = self._get_kotak_exchange(exchange)
                candidates = self._get_index_symbol_candidates(symbol)
                logger.debug(
                    f"DEPTH API - Index candidates for {symbol}: {candidates}"
                )
                response, query = self._query_index_with_candidates(
                    kotak_exchange, candidates, "depth"
                )
                if response is None:
                    logger.warning(
                        f"DEPTH API - All index candidates failed for {symbol}; last query: {query}"
                    )
                    return self._get_default_depth()
                logger.debug(f"DEPTH API - Index resolved via: {query}")
            else:
                # For regular stocks/F&O, get both pSymbol and brexchange from database
                # In Kotak DB: token = pSymbol, brexchange = nse_cm/nse_fo/bse_cm etc.
                psymbol = get_token(symbol, exchange)
                brexchange = get_brexchange(symbol, exchange)
                logger.info(f"DEPTH API - pSymbol: {psymbol}, brexchange: {brexchange}")

                if not psymbol or brexchange is None:
                    logger.error(f"pSymbol or brexchange not found for {symbol} on {exchange}")
                    return self._get_default_depth()

                # Map brexchange to correct Kotak format if needed
                if brexchange in ["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"]:
                    kotak_exchange = self._get_kotak_exchange(brexchange)
                    logger.info(f"DEPTH API - Mapped {brexchange} to {kotak_exchange}")
                else:
                    kotak_exchange = brexchange  # Already in correct format

                # Build query using mapped exchange: kotak_exchange|pSymbol
                query = f"{kotak_exchange}|{psymbol}"
                logger.debug(f"DEPTH API - Query: {query}")

                # Make API request with depth filter (index branch already fetched response)
                response = self._make_quotes_request(query, "depth")

            if response and isinstance(response, list) and len(response) > 0:
                target_quote = response[0]
                depth_data = target_quote.get("depth", {})

                logger.debug(f"DEPTH API - Raw depth data: {depth_data}")

                # Parse Neo API v2 depth format (based on actual API response)
                bids = []
                asks = []

                # Process buy orders (bids) - handle both array and object formats
                buy_data = depth_data.get("buy", [])
                logger.debug(f"DEPTH API - Buy data: {buy_data}")

                if isinstance(buy_data, list):
                    for i, bid in enumerate(buy_data[:5]):  # Top 5 bids
                        logger.debug(f"DEPTH API - Processing bid {i}: {bid}")
                        bids.append(
                            {
                                "price": float(bid.get("price", 0)),
                                "quantity": int(bid.get("quantity", 0)),
                            }
                        )

                # Process sell orders (asks) - handle both array and object formats
                sell_data = depth_data.get("sell", [])
                logger.debug(f"DEPTH API - Sell data: {sell_data}")

                if isinstance(sell_data, list):
                    for i, ask in enumerate(sell_data[:5]):  # Top 5 asks
                        logger.debug(f"DEPTH API - Processing ask {i}: {ask}")
                        asks.append(
                            {
                                "price": float(ask.get("price", 0)),
                                "quantity": int(ask.get("quantity", 0)),
                            }
                        )

                logger.debug(f"DEPTH API - Parsed bids: {bids}")
                logger.debug(f"DEPTH API - Parsed asks: {asks}")

                # Ensure we have 5 levels
                while len(bids) < 5:
                    bids.append({"price": 0, "quantity": 0})
                while len(asks) < 5:
                    asks.append({"price": 0, "quantity": 0})

                total_buy_qty = sum(bid["quantity"] for bid in bids if bid["quantity"] > 0)
                total_sell_qty = sum(ask["quantity"] for ask in asks if ask["quantity"] > 0)

                result = {
                    "bids": bids,
                    "asks": asks,
                    "totalbuyqty": total_buy_qty,
                    "totalsellqty": total_sell_qty,
                }

                logger.debug(f"DEPTH API - Final result: {result}")
                return result
            else:
                logger.warning(f"No depth data received for {symbol}")
                return self._get_default_depth()

        except Exception as e:
            logger.error(f"Error in get_depth: {e}")
            return self._get_default_depth()

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
            # Kotak Neo's quotes endpoint rejects a request carrying 50 symbols with
            # HTTP 400 "Please set the Neo symbol max value to 50.", so the effective
            # server-side cap is below 50 even though the docs state no limit at all.
            # Observed against the live endpoint: 42 symbols returns 200, 50 returns
            # 400, so the cap sits somewhere in 42-49. 25 keeps a wide margin; URL
            # length is not the constraint (25 entries is roughly 350 characters).
            BATCH_SIZE = 25
            RATE_LIMIT_DELAY = 0.2  # 5 requests/sec = 125 symbols/sec (under 500 limit)

            # If symbols exceed batch size, process in batches
            if len(symbols) > BATCH_SIZE:
                total_batches = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE
                logger.info(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
                all_results = []
                failed_batches = 0

                # Split symbols into batches
                for i in range(0, len(symbols), BATCH_SIZE):
                    batch = symbols[i : i + BATCH_SIZE]
                    logger.debug(
                        f"Processing batch {i // BATCH_SIZE + 1}: symbols {i + 1} to {min(i + BATCH_SIZE, len(symbols))}"
                    )

                    # Process this batch. A sub-batch that fails must not discard the
                    # batches that already succeeded - callers such as the option chain
                    # can still work from a partial set, and every symbol in the failed
                    # batch is reported with an error entry.
                    try:
                        batch_results = self._process_quotes_batch(batch)
                        all_results.extend(batch_results)
                    except Exception as e:
                        failed_batches += 1
                        logger.warning(f"Batch {i // BATCH_SIZE + 1}/{total_batches} failed: {e}")
                        all_results.extend(
                            {
                                "symbol": item["symbol"],
                                "exchange": item["exchange"],
                                "error": str(e),
                            }
                            for item in batch
                        )

                    # Rate limit delay between batches
                    if i + BATCH_SIZE < len(symbols):
                        time.sleep(RATE_LIMIT_DELAY)

                # Only a total wipe-out is worth failing the whole call for
                if failed_batches == total_batches:
                    raise Exception(f"All {total_batches} quote batches failed")

                if failed_batches:
                    logger.warning(
                        f"Processed {len(all_results)} quotes in {total_batches} batches "
                        f"({failed_batches} failed)"
                    )
                else:
                    logger.info(
                        f"Successfully processed {len(all_results)} quotes in {total_batches} batches"
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
            symbols: List of dicts with 'symbol' and 'exchange' keys (max 25)
        Returns:
            list: List of quote data for the batch
        """
        # Build comma-separated queries and mapping
        queries = []
        query_map = {}  # {query -> {symbol, exchange}}
        skipped_symbols = []  # Track symbols that couldn't be resolved

        for item in symbols:
            symbol = item["symbol"]
            exchange = item["exchange"]

            try:
                # Check if this is an index
                if "INDEX" in exchange.upper():
                    kotak_exchange = self._get_kotak_exchange(exchange)
                    # Batch path uses the first candidate; single-symbol path
                    # (get_quotes/get_depth) iterates all candidates.
                    candidates = self._get_index_symbol_candidates(symbol)
                    neo_symbol = candidates[0]
                    query = f"{kotak_exchange}|{neo_symbol}"
                else:
                    # For regular stocks/F&O, get pSymbol and brexchange
                    psymbol = get_token(symbol, exchange)
                    brexchange = get_brexchange(symbol, exchange)

                    if not psymbol or not brexchange:
                        logger.warning(
                            f"Skipping symbol {symbol} on {exchange}: could not resolve pSymbol or brexchange"
                        )
                        skipped_symbols.append(
                            {
                                "symbol": symbol,
                                "exchange": exchange,
                                "error": "Could not resolve pSymbol or brexchange",
                            }
                        )
                        continue

                    # Map brexchange to Kotak format if needed
                    if brexchange in ["NSE", "BSE", "NFO", "BFO", "CDS", "MCX"]:
                        kotak_exchange = self._get_kotak_exchange(brexchange)
                    else:
                        kotak_exchange = brexchange

                    query = f"{kotak_exchange}|{psymbol}"

                queries.append(query)
                query_map[query] = {"symbol": symbol, "exchange": exchange}

            except Exception as e:
                logger.warning(f"Skipping symbol {symbol} on {exchange}: {str(e)}")
                skipped_symbols.append({"symbol": symbol, "exchange": exchange, "error": str(e)})
                continue

        # Return skipped symbols if no valid queries
        if not queries:
            logger.warning("No valid queries to fetch quotes for")
            return skipped_symbols

        # Build comma-separated query string
        combined_query = ",".join(queries)

        logger.info(f"Requesting quotes for {len(queries)} instruments")
        logger.debug(
            f"Combined query: {combined_query[:200]}..."
            if len(combined_query) > 200
            else f"Combined query: {combined_query}"
        )

        # Make API request using existing method (handles URL encoding)
        response_data = self._make_quotes_request(combined_query, "all")
        if response_data is None:
            logger.error(f"API Error: {self.last_quote_error}")
            raise Exception(f"API Error: {self.last_quote_error}")

        # Parse response and build results
        results = []

        if not response_data or not isinstance(response_data, list):
            logger.warning("Empty or invalid response from API")
            return results

        # Build lookup by query for response matching
        # Response items have 'exchange' and 'exchange_token' or 'display_symbol'
        response_lookup = {}
        for quote in response_data:
            # Build possible keys to match
            exch = quote.get("exchange", "")
            token = quote.get("exchange_token", "")
            display = quote.get("display_symbol", "")

            # Try to match with original query format
            key1 = f"{exch}|{token}"
            key2 = f"{exch}|{display.replace('-EQ', '').replace('-IN', '')}" if display else None

            response_lookup[key1] = quote
            if key2:
                response_lookup[key2] = quote

        # Build results from query_map
        for query, original in query_map.items():
            # Try to find matching quote in response
            quote_data = response_lookup.get(query)

            # If not found, try variations
            if not quote_data:
                for resp_key, resp_quote in response_lookup.items():
                    if query.lower() == resp_key.lower():
                        quote_data = resp_quote
                        break

            if not quote_data:
                logger.warning(f"No quote data found for {original['symbol']} ({query})")
                results.append(
                    {
                        "symbol": original["symbol"],
                        "exchange": original["exchange"],
                        "error": "No quote data available",
                    }
                )
                continue

            # Parse and format quote data
            ohlc_data = quote_data.get("ohlc", {})
            depth_data = quote_data.get("depth") or {}  # Guard against null depth
            buy_orders = depth_data.get("buy", [])
            sell_orders = depth_data.get("sell", [])

            ltp = float(quote_data.get("ltp", 0))
            bid_price = float(buy_orders[0].get("price", 0)) if buy_orders else ltp
            ask_price = float(sell_orders[0].get("price", 0)) if sell_orders else ltp

            result_item = {
                "symbol": original["symbol"],
                "exchange": original["exchange"],
                "data": {
                    "bid": bid_price,
                    "ask": ask_price,
                    "open": float(ohlc_data.get("open", 0)),
                    "high": float(ohlc_data.get("high", 0)),
                    "low": float(ohlc_data.get("low", 0)),
                    "ltp": ltp,
                    "prev_close": float(ohlc_data.get("close", 0)),
                    "volume": float(quote_data.get("last_volume", 0)),
                    "oi": int(quote_data.get("open_int", 0)),
                },
            }
            results.append(result_item)

        # Include skipped symbols in results
        return skipped_symbols + results

    def _get_default_quote(self):
        """Return default quote structure"""
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

    def _get_default_depth(self):
        """Return default depth structure"""
        return {
            "bids": [{"price": 0, "quantity": 0} for _ in range(5)],
            "asks": [{"price": 0, "quantity": 0} for _ in range(5)],
            "totalbuyqty": 0,
            "totalsellqty": 0,
        }

    def _history_segment(self, symbol: str, exchange: str) -> str:
        """Resolve the Neo exchange segment the historical endpoint expects.

        The master contract is not consistent about brexchange: cash rows store
        an OpenAlgo code ("NSE"), F&O rows store pExchSeg, which is already in
        Neo form ("nse_fo"). Both shapes reach here, so map what maps and take
        the rest as given.
        """
        brexchange = get_brexchange(symbol, exchange)
        segment = None
        if brexchange:
            segment = self._get_kotak_exchange(brexchange) or brexchange
        if not segment:
            segment = self._get_kotak_exchange(exchange)
        if not segment:
            raise Exception(f"Unsupported exchange for historical data: {exchange}")

        if segment not in HISTORY_SEGMENTS:
            raise Exception(
                f"Kotak Neo serves historical data for NSE, BSE, NFO, BFO, NSE_INDEX and "
                f"BSE_INDEX only. {exchange} (segment {segment}) is quote-only."
            )
        return segment

    def _history_neosymbols(self, symbol: str, exchange: str, segment: str) -> list:
        """Candidate neosymbol keys for the historical endpoint, best first.

        The endpoint documents `<segment>|<instrument_token>`, and the master
        contract carries a pSymbol for index rows as well as tradable ones, so
        the token is always tried first. An index additionally falls back to the
        descriptive Neo names `get_quotes` relies on, because the index name is
        the one key the scrip master has been seen to disagree with the feed on.
        """
        candidates = []

        token = get_token(symbol, exchange)
        if token:
            candidates.append(f"{segment}|{token}")

        if "INDEX" in exchange.upper():
            for name in self._get_index_symbol_candidates(symbol):
                # The historical endpoint matches names case-sensitively and does
                # not always agree with the quotes endpoint: INDIAVIX answers to
                # "India VIX" for quotes but only to "INDIA VIX" here. Trying the
                # upper-case form as well costs nothing when the first one hits.
                for variant in (name, name.upper()):
                    key = f"{segment}|{variant}"
                    if key not in candidates:
                        candidates.append(key)

        if not candidates:
            raise Exception(f"Could not find instrument token for {exchange}:{symbol}")
        return candidates

    def _fetch_history_chunk(self, neosymbol, resolution, chunk_start, chunk_end) -> list:
        """One historical request. Returns the candle rows, or raises."""
        client = get_httpx_client()

        params = {
            "neosymbol": neosymbol,
            "fromdate": chunk_start.strftime("%Y-%m-%d"),
            "todate": chunk_end.strftime("%Y-%m-%d"),
            "interval": resolution,
        }
        # Neo takes the pipe literally, and leaving it unescaped keeps the URL
        # readable in the logs and identical to the documented example.
        url = (
            f"{self.base_url}/market-data/1.0/historical/details"
            f"?{urllib.parse.urlencode(params, safe='|')}"
        )
        headers = {"Authorization": self.access_token, "Content-Type": "application/json"}

        logger.debug(
            f"HISTORY API - Requesting {neosymbol} {resolution} "
            f"{params['fromdate']} to {params['todate']}"
        )

        # A 429 retries this same request. Letting it fall through to the next
        # neosymbol candidate would spend another slot on the very quota that is
        # already exhausted, and would blame the symbol for a pacing problem.
        for attempt in range(HISTORY_MAX_RETRIES + 1):
            _history_pace()
            response = client.get(url, headers=headers, timeout=60)
            if response.status_code != 429:
                break
            if attempt == HISTORY_MAX_RETRIES:
                raise Exception(
                    f"Rate limited by Neo for {neosymbol} after "
                    f"{HISTORY_MAX_RETRIES} retries: {response.text[:200]}"
                )
            delay = _history_retry_delay(response.headers, attempt)
            logger.warning(
                f"HISTORY API - 429 for {neosymbol}, retry "
                f"{attempt + 1}/{HISTORY_MAX_RETRIES} in {delay:.1f}s"
            )
            time.sleep(delay)

        try:
            payload = json.loads(response.text)
        except ValueError as exc:
            raise Exception(
                f"HTTP {response.status_code} for {neosymbol}, non-JSON body: {response.text[:300]}"
            ) from exc
        if not isinstance(payload, dict):
            raise Exception(f"Unexpected payload for {neosymbol}: {response.text[:300]}")

        fault = payload.get("fault") or {}
        message = str(fault.get("message") or payload.get("emsg") or "")

        # An empty range arrives as a 400 fault. Reported as an error it would
        # abort a whole multi-chunk pull whose last chunk merely landed on a
        # Sunday, so it is answered with no candles instead.
        if _is_no_data_fault(message):
            logger.info(
                f"HISTORY API - No data for {neosymbol} "
                f"{params['fromdate']}..{params['todate']}: {message[:120]}"
            )
            return []

        if response.status_code != 200:
            raise Exception(
                f"HTTP {response.status_code} for {neosymbol}: {message or response.text[:300]}"
            )
        if str(payload.get("status", "")).lower() != "success":
            raise Exception(f"Neo error for {neosymbol}: {message or response.text[:300]}")

        return (payload.get("data") or {}).get("candles") or []

    @staticmethod
    def _normalize_candles(candles: list) -> list:
        """Pad each positional row out to the full seven column contract.

        Neo documents `[timestamp, open, high, low, close, volume, oi]` but does
        not populate oi in phase one, so a row can arrive short. Padding here
        keeps the frame rectangular instead of letting pandas invent NaN columns.
        """
        rows = []
        for candle in candles:
            if not isinstance(candle, (list, tuple)) or len(candle) < 5:
                logger.warning(f"HISTORY API - Skipping malformed candle row: {candle}")
                continue
            row = list(candle[:7])
            row.extend([0] * (7 - len(row)))
            rows.append(row)
        return rows

    def get_history(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """Historical OHLCV candles from the Neo market-data API.

        Args:
            symbol: OpenAlgo trading symbol
            exchange: OpenAlgo exchange (NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX)
            interval: OpenAlgo interval, a key of self.timeframe_map
            start_date: Start date, YYYY-MM-DD
            end_date: End date, YYYY-MM-DD

        Returns:
            pd.DataFrame of [timestamp, open, high, low, close, volume, oi] with
            timestamp in epoch seconds.
        """
        try:
            resolution = self.timeframe_map.get(interval)
            if not resolution:
                supported = ", ".join(sorted(self.timeframe_map))
                raise Exception(f"Unsupported timeframe: {interval}. Supported: {supported}")

            segment = self._history_segment(symbol, exchange)
            candidates = self._history_neosymbols(symbol, exchange, segment)

            start = pd.to_datetime(start_date)
            end = pd.to_datetime(end_date)
            if start > end:
                raise Exception(f"start_date {start_date} is after end_date {end_date}")

            chunk_days = HISTORY_CHUNK_DAYS[resolution]
            resolved = None
            dfs = []
            current_start = start

            while current_start <= end:
                current_end = min(current_start + timedelta(days=chunk_days - 1), end)

                # Once a candidate has actually produced candles, stay on it.
                attempts = [resolved] if resolved else candidates
                candles = None
                errors = []
                for neosymbol in attempts:
                    try:
                        result = self._fetch_history_chunk(
                            neosymbol, resolution, current_start, current_end
                        )
                    except Exception as exc:
                        errors.append(f"{neosymbol}: {exc}")
                        continue
                    candles = result
                    if result:
                        resolved = neosymbol
                        break

                if candles is None:
                    # Every candidate failed. Skipping the chunk would leave a
                    # hole that reads as a market holiday rather than an error,
                    # so surface it instead of returning a short series.
                    raise Exception(
                        f"Historical request failed for {exchange}:{symbol} "
                        f"{current_start.date()} to {current_end.date()} - " + "; ".join(errors)
                    )

                rows = self._normalize_candles(candles)
                if rows:
                    dfs.append(pd.DataFrame(rows, columns=HISTORY_COLUMNS))

                current_start = current_end + timedelta(days=1)

            if not dfs:
                logger.info(f"HISTORY API - No candles for {exchange}:{symbol} {interval}")
                return pd.DataFrame(columns=HISTORY_COLUMNS)

            final_df = pd.concat(dfs, ignore_index=True)

            # Neo stamps every candle ISO 8601 carrying the +0530 offset, so
            # parsing as UTC already yields the true epoch, which is what an
            # intraday bar wants. A daily or weekly candle is a date rather than
            # an instant, and the platform expects those on IST midnight, which
            # is the +5:30 shift Zerodha applies for the same reason.
            final_df["timestamp"] = pd.to_datetime(
                final_df["timestamp"], format="ISO8601", utc=True
            )
            if resolution in ("D", "W"):
                final_df["timestamp"] = final_df["timestamp"] + pd.Timedelta(hours=5, minutes=30)
            final_df["timestamp"] = final_df["timestamp"].astype("int64") // 10**9

            for column in ("open", "high", "low", "close"):
                final_df[column] = pd.to_numeric(final_df[column], errors="coerce")
            # oi is unpopulated in phase one, so it lands as 0 rather than NaN.
            for column in ("volume", "oi"):
                final_df[column] = (
                    pd.to_numeric(final_df[column], errors="coerce").fillna(0).astype("int64")
                )

            # Chunks can overlap at the seams and can arrive out of order.
            final_df = (
                final_df.sort_values("timestamp")
                .drop_duplicates(subset=["timestamp"], keep="first")
                .reset_index(drop=True)
            )

            return final_df[HISTORY_COLUMNS]

        except Exception as e:
            logger.exception(f"Error fetching historical data for {exchange}:{symbol}: {e}")
            raise

    def get_supported_intervals(self) -> dict:
        """Return supported intervals matching the format expected by intervals.py"""
        offered = list(self.timeframe_map.keys())
        return {
            "seconds": [k for k in offered if k.endswith("s")],
            "minutes": [k for k in offered if k.endswith("m")],
            "hours": [k for k in offered if k.endswith("h")],
            "days": [k for k in offered if k == "D"],
            "weeks": [k for k in offered if k == "W"],
            "months": [k for k in offered if k == "M"],
        }
