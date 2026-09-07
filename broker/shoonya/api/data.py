import asyncio
import json
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd

from database.token_db import get_br_symbol, get_oa_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger


# Auto-detect eventlet environment (Docker/standalone uses gunicorn+eventlet)
# asyncio.run() cannot be called under eventlet's monkey-patched event loop
def _is_eventlet_patched():
    try:
        import eventlet.patcher

        return eventlet.patcher.is_monkey_patched("socket")
    except (ImportError, AttributeError):
        return False


USE_ASYNC = not _is_eventlet_patched()

logger = get_logger(__name__)


def _encode_jdata(data: dict) -> str:
    """
    Serialize a jData payload for Shoonya's form-urlencoded body.

    Shoonya splits the request body on "&" before parsing jData, so a literal
    ampersand inside the JSON (symbols like M&M-EQ) truncates the payload and
    the server replies "Invalid Input : jData is not valid json object".
    Percent-encoding does not help — the body is never URL-decoded, so "%26"
    reaches the backend verbatim and matches no symbol. Escaping it as the
    JSON unicode escape \\u0026 keeps the body free of "&" while the server's
    JSON parser still sees the real character.
    """
    return json.dumps(data).replace("&", "\\u0026")


# EODChartData resolves the `sym` argument against Shoonya's index names, which
# are neither the trading symbol ("NIFTY INDEX") nor always the master's Symbol
# column ("Nifty Fin Services"). Anything not listed here falls back to the
# broker symbol; BSE indices (SENSEX, BANKEX) have no EOD series at all.
EOD_INDEX_SYMBOLS = {
    ("NSE_INDEX", "NIFTY"): "Nifty 50",
    ("NSE_INDEX", "BANKNIFTY"): "Nifty Bank",
    ("NSE_INDEX", "FINNIFTY"): "Nifty Financial Services",
    ("NSE_INDEX", "MIDCPNIFTY"): "Nifty Midcap Select",
    ("NSE_INDEX", "NIFTYNXT50"): "Nifty Next 50",
    ("NSE_INDEX", "INDIAVIX"): "India VIX",
}


# A GetQuotes reply that describes a different instrument is retried rather
# than trusted. Measured 25-Aug-2026 against the live API, two NFO options
# polled round-robin at 2 req/sec for 13 minutes: 119 of 1318 replies came
# back wrong (9.03%), every one of them the NSE index. The failures are
# independent - for a given scrip P(wrong) was 8.19% and 9.86% while
# P(wrong | the previous reply for it was wrong) was 5.66% and 9.38% - so
# retrying is effective rather than hitting the same bad state again. At the
# measured rate three attempts leave roughly 0.07% unresolved, and those raise
# instead of returning a price. Retries cost nothing on the 91% that are
# right first time.
def _quote_attempts() -> int:
    """How many times a mismatched quote is re-requested before giving up.

    Configurable because the right number depends on the leak rate, which is
    Shoonya's to change and has already moved between 1.5% and 12% across
    sessions. Three suits what has been measured; a quieter endpoint needs
    fewer, and anything below 1 would disable the retry rather than the check,
    so the floor is 1.
    """
    try:
        return max(1, int(os.getenv("SHOONYA_QUOTE_ATTEMPTS", "3")))
    except ValueError:
        logger.warning("SHOONYA_QUOTE_ATTEMPTS is not an integer, using 3")
        return 3


QUOTE_ATTEMPTS = _quote_attempts()


# Shoonya reports every failure the same way - {"stat":"Not_Ok","emsg":"..."} -
# so the emsg text is the only thing separating "your login is dead" from "this
# scrip had no trades in that window". Matching is substring/lowercase because
# the wording carries varying prefixes ("Session Expired : Invalid Session Key").
SESSION_ERROR_MARKERS = (
    "session expired",
    "invalid session",
    "session key",
    "not logged in",
    "invalid input : uid",
)

NO_DATA_MARKERS = (
    "no data",
    "no data available",
)


def is_session_error(emsg) -> bool:
    """True when the broker's error message means the login is no longer valid.

    Session death is fatal for every subsequent request, so callers raise on it
    rather than treating it as a transient per-request hiccup.
    """
    text = str(emsg or "").lower()
    return any(marker in text for marker in SESSION_ERROR_MARKERS)


def is_no_data_error(emsg) -> bool:
    """True when the broker is saying the window is legitimately empty.

    Not a failure: illiquid contracts, ranges before a scrip was listed and
    holiday-only windows all answer this way, and an empty frame is the correct
    result for them.
    """
    text = str(emsg or "").lower()
    return any(marker in text for marker in NO_DATA_MARKERS)


def quote_matches_request(response: dict, exch: str, token: str) -> bool:
    """Check that a GetQuotes reply describes the instrument that was asked for.

    Shoonya's quote backend intermittently answers with a snapshot of a
    different instrument requested elsewhere on the same login. It is not a
    transport or concurrency artefact: it reproduces on strictly sequential
    calls over a single connection, and a process that never asks for the index
    still receives it - a 13-minute run that requested only two NFO options was
    answered with the NSE index 119 times.

    The payload is complete and carries stat=Ok, so the only way to detect it
    is to compare the echoed exch/token against the request. Nothing about the
    price itself gives it away: a leaked index quote is internally consistent,
    its LTP sits inside its own OHLC, which is why the stale-quote check in
    sandbox/execution_engine.py cannot catch it. Unchecked, the foreign price
    reaches order fills - a sandbox MARKET buy on NIFTY18AUG2624600CE filled at
    24391.25, the NIFTY spot, instead of ~39.85.

    The same session's WebSocket touchline feed carried 1719 ticks over that
    window with zero wrong instruments, so this is specific to the REST
    endpoint. Prefer the feed where one is available; this guard is for the
    paths that have no feed to fall back on.

    A reply with no token echo is accepted: there is nothing to check it
    against, and every observed Ok response carries one.
    """
    got_token = str(response.get("token", "") or "")
    if not got_token:
        return True
    if got_token != str(token):
        return False
    got_exch = str(response.get("exch", "") or "")
    return not got_exch or got_exch == exch


def log_wrong_instrument_response(
    context: str, exch: str, token: str, response: dict, attempt: int
) -> None:
    """Record a wrong-instrument reply in full, so the behaviour stays visible.

    Currently silent. Shoonya gets this wrong on roughly 9-12% of option quote
    requests, so at any real polling rate the full-payload line below floods
    log/errors.jsonl and buries everything else in it. The reply is still
    detected and discarded either way - this only controls whether it is
    reported. Uncomment to gather evidence for a broker ticket.

    test/shoonya_guard_live_test.py does not depend on this: it captures raw
    replies beneath the broker module rather than reading them out of the log.
    """
    # logger.error(
    #     f"WRONG INSTRUMENT Shoonya was asked for {exch}|{token}{context} and "
    #     f"answered with {response.get('exch')}|{response.get('token')} "
    #     f"({response.get('tsym')}) lp={response.get('lp')} "
    #     f"stat={response.get('stat')} - discarding "
    #     f"(attempt {attempt}/{QUOTE_ATTEMPTS}). Full response: {json.dumps(response)}"
    # )


def get_quotes_response(auth_token, exch: str, token: str, context: str = "") -> dict:
    """Call GetQuotes, verifying the reply belongs to the instrument requested.

    Retries a mismatch up to QUOTE_ATTEMPTS times, then raises rather than
    handing back another instrument's prices. See quote_matches_request() for
    why this is necessary and why the check is an identity comparison rather
    than anything to do with the price.

    A broker error (stat != Ok) is returned untouched on the first attempt -
    that is Shoonya answering the question, and the caller reports its emsg.
    """
    for attempt in range(1, QUOTE_ATTEMPTS + 1):
        response = get_api_response(
            "/NorenWClientAPI/GetQuotes",
            auth_token,
            payload={"exch": exch, "token": token},
        )

        if response.get("stat") != "Ok":
            return response  # caller reports the broker's own error message

        if quote_matches_request(response, exch, token):
            return response

        log_wrong_instrument_response(context, exch, token, response, attempt)

    raise Exception(
        f"Shoonya returned a quote for a different instrument "
        f"({response.get('exch')}|{response.get('token')} {response.get('tsym')}) "
        f"when asked for {exch}|{token}{context} on all {QUOTE_ATTEMPTS} attempts"
    )


def get_api_response(endpoint, auth, method="POST", payload=None):
    """
    Common function to make API calls to Shoonya using httpx with connection pooling
    """
    AUTH_TOKEN = auth
    # BROKER_API_KEY format: userid:::client_id
    full_api_key = os.getenv("BROKER_API_KEY")
    if not full_api_key:
        raise RuntimeError("BROKER_API_KEY is not configured")
    api_key = full_api_key.split(":::")[0]  # Trading user ID

    if payload is None:
        data = {"uid": api_key}
    else:
        data = payload
        data["uid"] = api_key

    payload_str = "jData=" + _encode_jdata(data)

    # Get the shared httpx client
    client = get_httpx_client()

    headers = {
        "Content-Type": "text/plain",
        "Authorization": f"Bearer {AUTH_TOKEN}",
    }
    url = f"https://api.shoonya.com{endpoint}"

    response = client.request(method, url, content=payload_str, headers=headers)
    data = response.text

    # Log response status and raw data for debugging
    logger.info(f"API Response [{endpoint}] status={response.status_code} body={data[:500]}")

    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON: {e}")
        logger.debug(f"Response data: {data}")
        raise

    return parsed


def get_chart_api_response(endpoint, auth, method="POST", payload=None):
    """
    Chart data endpoints (EODChartData, TPSeries) take jKey embedded in the
    form-urlencoded body (same pattern as Flattrade/Finvasia chart APIs). The
    legacy /NorenWClientTP/ path is decommissioned post-OAuth and answers 502
    Bad Gateway, so callers must use the /NorenWClientAPI/ path.
    """
    AUTH_TOKEN = auth
    full_api_key = os.getenv("BROKER_API_KEY")
    if not full_api_key:
        raise RuntimeError("BROKER_API_KEY is not configured")
    api_key = full_api_key.split(":::")[0]

    if payload is None:
        data = {"uid": api_key}
    else:
        data = payload
        data["uid"] = api_key

    # Chart endpoints want jData=<json>&jKey=<token> form-urlencoded, NOT a
    # Bearer header. This mirrors broker/flattrade/api/data.py:get_api_response.
    payload_str = "jData=" + _encode_jdata(data) + "&jKey=" + AUTH_TOKEN

    client = get_httpx_client()

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    url = f"https://api.shoonya.com{endpoint}"

    response = client.request(method, url, content=payload_str, headers=headers)
    data = response.text

    logger.info(f"Chart API Response [{endpoint}] status={response.status_code} body={data[:500]}")

    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding chart JSON: {e}")
        logger.debug(f"Chart response data: {data}")
        raise


class BrokerData:
    def __init__(self, auth_token):
        """Initialize Shoonya data handler with authentication token"""
        self.auth_token = auth_token
        # Map common timeframe format to Shoonya resolutions
        # Note: Weekly and Monthly intervals are not supported
        self.timeframe_map = {
            # Minutes
            "1m": "1",  # 1 minute
            "3m": "3",  # 3 minutes
            "5m": "5",  # 5 minutes
            "10m": "10",  # 10 minutes
            "15m": "15",  # 15 minutes
            "30m": "30",  # 30 minutes
            # Hours
            "1h": "60",  # 1 hour (60 minutes)
            "2h": "120",  # 2 hours (120 minutes)
            "4h": "240",  # 4 hours (240 minutes)
            # Daily
            "D": "D",  # Daily data
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Simplified quote data with required fields
        """
        try:
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)

            if exchange == "NSE_INDEX":
                exchange = "NSE"
            elif exchange == "BSE_INDEX":
                exchange = "BSE"

            response = get_quotes_response(
                self.auth_token, exchange, token, context=f" for {symbol}"
            )

            if response.get("stat") != "Ok":
                raise Exception(f"Error from Shoonya API: {response.get('emsg', 'Unknown error')}")

            # Return simplified quote data
            return {
                "bid": float(response.get("bp1", 0)),
                "ask": float(response.get("sp1", 0)),
                "open": float(response.get("o", 0)),
                "high": float(response.get("h", 0)),
                "low": float(response.get("l", 0)),
                "ltp": float(response.get("lp", 0)),
                "prev_close": float(response.get("c", 0)) if "c" in response else 0,
                "volume": int(response.get("v", 0)),
                "oi": int(response.get("oi", 0)),
                "tick_size": float(response.get("ti", 0)) if response.get("ti") else None,
            }

        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}")

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
            # Shoonya API uses NorenAPI (similar to Flattrade)
            # Rate limits: ~20 requests/second (conservative estimate)
            BATCH_SIZE = 20  # Process 40 symbols per batch
            RATE_LIMIT_DELAY = 1.0  # 1 second delay between batches

            if len(symbols) > BATCH_SIZE:
                logger.info(f"Processing {len(symbols)} symbols in batches of {BATCH_SIZE}")
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

                logger.info(
                    f"Successfully processed {len(all_results)} quotes in {(len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE} batches"
                )
                return all_results
            else:
                return self._process_quotes_batch(symbols)

        except Exception as e:
            logger.exception("Error fetching multiquotes")
            raise Exception(f"Error fetching multiquotes: {e}")

    def _fetch_single_quote_sync(
        self, symbol: str, exchange: str, api_exchange: str, token: str, api_key: str
    ) -> dict:
        """
        Fetch quote for a single symbol synchronously (for ThreadPoolExecutor)
        """
        try:
            data = {"uid": api_key, "exch": api_exchange, "token": token}

            payload_str = "jData=" + _encode_jdata(data)
            headers = {
                "Content-Type": "text/plain",
                "Authorization": f"Bearer {self.auth_token}",
            }
            url = "https://api.shoonya.com/NorenWClientAPI/GetQuotes"

            # This path does not go through get_quotes_response because it does
            # not go through get_api_response either, but the rule is the same:
            # never return a reply that describes another instrument. A row
            # that cannot be resolved carries an error instead of a price, so
            # one bad symbol does not fail the whole batch.
            for attempt in range(1, QUOTE_ATTEMPTS + 1):
                # Use httpx.post for sync requests
                http_response = httpx.post(url, content=payload_str, headers=headers, timeout=10.0)
                response = http_response.json()

                if response.get("stat") != "Ok":
                    return {
                        "symbol": symbol,
                        "exchange": exchange,
                        "error": response.get("emsg", "Unknown error"),
                    }

                if quote_matches_request(response, api_exchange, token):
                    break

                log_wrong_instrument_response(
                    f" for {symbol}", api_exchange, token, response, attempt
                )
            else:
                return {
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": (
                        f"Broker returned a quote for a different instrument "
                        f"({response.get('exch')}|{response.get('token')} "
                        f"{response.get('tsym')}) on all {QUOTE_ATTEMPTS} attempts"
                    ),
                }

            return {
                "symbol": symbol,
                "exchange": exchange,
                "data": {
                    "bid": float(response.get("bp1", 0)),
                    "ask": float(response.get("sp1", 0)),
                    "open": float(response.get("o", 0)),
                    "high": float(response.get("h", 0)),
                    "low": float(response.get("l", 0)),
                    "ltp": float(response.get("lp", 0)),
                    "prev_close": float(response.get("c", 0)) if "c" in response else 0,
                    "volume": int(response.get("v", 0)),
                    "oi": int(response.get("oi", 0)),
                },
            }

        except Exception as e:
            return {"symbol": symbol, "exchange": exchange, "error": str(e)}

    async def _fetch_single_quote_async(
        self,
        client: httpx.AsyncClient,
        symbol: str,
        exchange: str,
        api_exchange: str,
        token: str,
        api_key: str,
    ) -> dict:
        """
        Fetch quote for a single symbol asynchronously
        """
        try:
            data = {"uid": api_key, "exch": api_exchange, "token": token}

            payload_str = "jData=" + _encode_jdata(data)
            headers = {
                "Content-Type": "text/plain",
                "Authorization": f"Bearer {self.auth_token}",
            }
            url = "https://api.shoonya.com/NorenWClientAPI/GetQuotes"

            # Same rule as the sync path above - see _fetch_single_quote_sync.
            for attempt in range(1, QUOTE_ATTEMPTS + 1):
                http_response = await client.post(url, content=payload_str, headers=headers)
                response = http_response.json()

                if response.get("stat") != "Ok":
                    return {
                        "symbol": symbol,
                        "exchange": exchange,
                        "error": response.get("emsg", "Unknown error"),
                    }

                if quote_matches_request(response, api_exchange, token):
                    break

                log_wrong_instrument_response(
                    f" for {symbol}", api_exchange, token, response, attempt
                )
            else:
                return {
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": (
                        f"Broker returned a quote for a different instrument "
                        f"({response.get('exch')}|{response.get('token')} "
                        f"{response.get('tsym')}) on all {QUOTE_ATTEMPTS} attempts"
                    ),
                }

            return {
                "symbol": symbol,
                "exchange": exchange,
                "data": {
                    "bid": float(response.get("bp1", 0)),
                    "ask": float(response.get("sp1", 0)),
                    "open": float(response.get("o", 0)),
                    "high": float(response.get("h", 0)),
                    "low": float(response.get("l", 0)),
                    "ltp": float(response.get("lp", 0)),
                    "prev_close": float(response.get("c", 0)) if "c" in response else 0,
                    "volume": int(response.get("v", 0)),
                    "oi": int(response.get("oi", 0)),
                },
            }

        except Exception as e:
            return {"symbol": symbol, "exchange": exchange, "error": str(e)}

    async def _process_quotes_batch_async(self, symbols: list, api_key: str) -> list:
        """
        Process a batch of symbols using async httpx
        """
        results = []

        # High connection limits for maximum concurrency
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=100)
        async with httpx.AsyncClient(timeout=10.0, limits=limits) as client:
            tasks = [
                self._fetch_single_quote_async(
                    client,
                    item["symbol"],
                    item["exchange"],
                    item["api_exchange"],
                    item["token"],
                    api_key,
                )
                for item in symbols
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error dicts
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    {
                        "symbol": symbols[i]["symbol"],
                        "exchange": symbols[i]["exchange"],
                        "error": str(result),
                    }
                )
            else:
                final_results.append(result)

        return final_results

    def _process_quotes_batch(self, symbols: list) -> list:
        """
        Process a single batch of symbols using concurrent API calls
        Args:
            symbols: List of dicts with 'symbol' and 'exchange' keys (max 40)
        Returns:
            list: List of quote data for the batch
        """
        skipped_symbols = []
        prepared_symbols = []

        # Pre-fetch API key (userid part)
        full_api_key = os.getenv("BROKER_API_KEY")
        api_key = full_api_key.split(":::")[0]  # Trading user ID

        # Step 1: Pre-resolve all tokens sequentially (database access)
        for item in symbols:
            symbol = item["symbol"]
            exchange = item["exchange"]

            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)

            if not br_symbol or not token:
                logger.warning(
                    f"Skipping symbol {symbol} on {exchange}: could not resolve broker symbol or token"
                )
                skipped_symbols.append(
                    {
                        "symbol": symbol,
                        "exchange": exchange,
                        "error": "Could not resolve broker symbol or token",
                    }
                )
                continue

            # Normalize exchange for indices
            api_exchange = exchange
            if exchange == "NSE_INDEX":
                api_exchange = "NSE"
            elif exchange == "BSE_INDEX":
                api_exchange = "BSE"

            prepared_symbols.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "api_exchange": api_exchange,
                    "token": token,
                }
            )

        if not prepared_symbols:
            return skipped_symbols

        # Step 2: Make concurrent API calls
        start_time = time.time()

        # Runtime check: even if USE_ASYNC is True, asyncio.run() will crash
        # if called from within an already-running event loop
        use_async = USE_ASYNC
        if use_async:
            try:
                asyncio.get_running_loop()
                use_async = False
            except RuntimeError:
                pass

        if use_async:
            # Async approach with httpx.AsyncClient
            results = asyncio.run(self._process_quotes_batch_async(prepared_symbols, api_key))
        else:
            # ThreadPoolExecutor approach
            results = []
            with ThreadPoolExecutor(max_workers=20) as executor:
                future_to_symbol = {
                    executor.submit(
                        self._fetch_single_quote_sync,
                        item["symbol"],
                        item["exchange"],
                        item["api_exchange"],
                        item["token"],
                        api_key,
                    ): item
                    for item in prepared_symbols
                }

                for future in as_completed(future_to_symbol):
                    try:
                        result = future.result()
                        results.append(result)
                    except Exception as e:
                        item = future_to_symbol[future]
                        results.append(
                            {
                                "symbol": item["symbol"],
                                "exchange": item["exchange"],
                                "error": str(e),
                            }
                        )

        elapsed = time.time() - start_time
        logger.debug(
            f"Batch of {len(prepared_symbols)} symbols completed in {elapsed:.2f}s ({len(prepared_symbols) / max(elapsed, 0.001):.1f} symbols/sec)"
        )

        return skipped_symbols + results

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """
        Get market depth for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
        Returns:
            dict: Market depth data with bids, asks and other details
        """
        try:
            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)

            if exchange == "NSE_INDEX":
                exchange = "NSE"
            elif exchange == "BSE_INDEX":
                exchange = "BSE"

            response = get_quotes_response(
                self.auth_token, exchange, token, context=f" for {symbol} depth"
            )

            if response.get("stat") != "Ok":
                raise Exception(f"Error from Shoonya API: {response.get('emsg', 'Unknown error')}")

            # Format bids and asks data
            bids = []
            asks = []

            # Process top 5 bids and asks
            for i in range(1, 6):
                bids.append(
                    {
                        "price": float(response.get(f"bp{i}", 0)),
                        "quantity": int(response.get(f"bq{i}", 0)),
                    }
                )
                asks.append(
                    {
                        "price": float(response.get(f"sp{i}", 0)),
                        "quantity": int(response.get(f"sq{i}", 0)),
                    }
                )

            # Return depth data
            return {
                "bids": bids,
                "asks": asks,
                "totalbuyqty": sum(bid["quantity"] for bid in bids),
                "totalsellqty": sum(ask["quantity"] for ask in asks),
                "high": float(response.get("h", 0)),
                "low": float(response.get("l", 0)),
                "ltp": float(response.get("lp", 0)),
                "ltq": int(response.get("ltq", 0)),  # Last Traded Quantity
                "open": float(response.get("o", 0)),
                "prev_close": float(response.get("c", 0)) if "c" in response else 0,
                "volume": int(response.get("v", 0)),
                "oi": 0,  # Shoonya doesn't provide OI in quotes response
            }

        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}")

    def _get_history_chunk_seconds(self, interval: str) -> int:
        """
        Per-request window size for the chart endpoints, in seconds. TPSeries
        returns 504 Server Timeout when the range produces too many candles in
        a single call, and EODChartData silently truncates to the newest 1201
        rows. These values keep each request under both limits.
        """
        # 1m bars: ~375 per trading day -> cap at ~5 days
        # 5m bars: ~75 per day -> ~30 days
        # daily bars: 1 per day (~250/yr) -> ~2 years, well under the 1201 cap
        minute_windows = {
            "1m": 5 * 24 * 3600,
            "3m": 10 * 24 * 3600,
            "5m": 20 * 24 * 3600,
            "10m": 40 * 24 * 3600,
            "15m": 60 * 24 * 3600,
            "30m": 90 * 24 * 3600,
            "1h": 180 * 24 * 3600,
            "2h": 180 * 24 * 3600,
            "4h": 365 * 24 * 3600,
            "D": 2 * 365 * 24 * 3600,
        }
        return minute_windows.get(interval, 30 * 24 * 3600)

    def get_history(
        self, symbol: str, exchange: str, interval: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        Get historical data for given symbol
        Args:
            symbol: Trading symbol
            exchange: Exchange (e.g., NSE, BSE)
            interval: Candle interval in common format:
                     Minutes: 1m, 3m, 5m, 10m, 15m, 30m
                     Hours: 1h, 2h, 4h
                     Days: D
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        Returns:
            pd.DataFrame: Historical data with columns [timestamp, open, high, low, close, volume]
        """
        try:
            # Check if interval is supported
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(
                    f"Unsupported interval '{interval}'. Supported intervals are: {', '.join(supported)}"
                )

            # Convert symbol to broker format and get token
            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)

            # EODChartData resolves indices by display name, so keep the
            # OpenAlgo exchange around after normalising it for the API.
            oa_exchange = exchange
            if exchange == "NSE_INDEX":
                exchange = "NSE"
            elif exchange == "BSE_INDEX":
                exchange = "BSE"

            # Convert dates to epoch timestamps
            # Handle both string and datetime.date inputs
            if isinstance(start_date, datetime):
                start_date_str = start_date.strftime("%Y-%m-%d")
            elif hasattr(start_date, "strftime"):  # datetime.date object
                start_date_str = start_date.strftime("%Y-%m-%d")
            else:
                start_date_str = str(start_date)

            if isinstance(end_date, datetime):
                end_date_str = end_date.strftime("%Y-%m-%d")
            elif hasattr(end_date, "strftime"):  # datetime.date object
                end_date_str = end_date.strftime("%Y-%m-%d")
            else:
                end_date_str = str(end_date)

            start_ts = int(
                datetime.strptime(start_date_str + " 00:00:00", "%Y-%m-%d %H:%M:%S").timestamp()
            )
            end_ts = int(
                datetime.strptime(end_date_str + " 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp()
            )

            # Daily bars come from EODChartData, intraday from TPSeries. Both
            # live under /NorenWClientAPI/ post-OAuth (the legacy
            # /NorenWClientTP/ path answers 502) and both want jKey in the
            # form-urlencoded body rather than a Bearer header.
            #
            # TPSeries does NOT accept intrv="D" — the request hangs until the
            # gateway times it out (504 Server Timeout), which is why daily
            # history returned nothing but the live quote appended below.
            #
            # Both endpoints are bounded per request: TPSeries times out on
            # long ranges and EODChartData truncates to the newest 1201 rows.
            # Chunk [start_ts, end_ts] so each request stays inside those
            # limits; chunk size is interval-dependent.
            if interval == "D":
                endpoint = "/NorenWClientAPI/EODChartData"
                eod_symbol = EOD_INDEX_SYMBOLS.get((oa_exchange, symbol), br_symbol)
            else:
                endpoint = "/NorenWClientAPI/TPSeries"
                eod_symbol = None

            chunk_seconds = self._get_history_chunk_seconds(interval)

            response_candles = []
            chunk_start = start_ts
            attempted_chunks = 0
            failed_chunks = 0
            while chunk_start <= end_ts:
                chunk_end = min(chunk_start + chunk_seconds, end_ts)
                attempted_chunks += 1
                if interval == "D":
                    payload = {
                        "sym": f"{exchange}:{eod_symbol}",
                        "from": str(chunk_start),
                        "to": str(chunk_end),
                    }
                else:
                    payload = {
                        "exch": exchange,
                        "token": token,
                        "st": str(chunk_start),
                        "et": str(chunk_end),
                        "intrv": self.timeframe_map[interval],
                    }
                logger.debug(f"{endpoint} Payload: {payload}")

                try:
                    chunk_response = get_chart_api_response(
                        endpoint, self.auth_token, payload=payload
                    )
                except Exception as e:
                    logger.error(
                        f"{endpoint} chunk request failed ({chunk_start}-{chunk_end}): {e}"
                    )
                    failed_chunks += 1
                    chunk_start = chunk_end + 1
                    continue

                # Both endpoints normally return a LIST of candles. On error
                # they return a DICT like {"stat":"Not_Ok","emsg":"..."} —
                # detect that before iterating (the old code iterated dict keys
                # and crashed trying to json.loads("stat")).
                if isinstance(chunk_response, dict):
                    emsg = chunk_response.get("emsg") or chunk_response.get("message") or "unknown"
                    # A dead session fails every chunk identically, so tolerating
                    # it per chunk drains the loop to zero candles and the API
                    # layer reports {"status":"success","data":[]} - a fake gap
                    # indistinguishable from a quiet window (#1944). Raise on it
                    # the way get_quotes() does.
                    if is_session_error(emsg):
                        raise Exception(f"Error from Shoonya API: {emsg}")
                    # "no data" is Shoonya answering, not failing: illiquid
                    # contracts, pre-listing ranges and holiday-only windows all
                    # come back this way. Count it as an empty success so the
                    # all-chunks-failed guard below does not turn it into a 500.
                    if is_no_data_error(emsg):
                        logger.debug(
                            f"{endpoint} reported no data for chunk {chunk_start}-{chunk_end}"
                        )
                        chunk_start = chunk_end + 1
                        continue
                    logger.warning(
                        f"{endpoint} returned error for chunk {chunk_start}-{chunk_end}: "
                        f"stat={chunk_response.get('stat')} emsg={emsg}"
                    )
                    failed_chunks += 1
                    chunk_start = chunk_end + 1
                    continue

                if not isinstance(chunk_response, list):
                    logger.warning(
                        f"Unexpected {endpoint} response type {type(chunk_response).__name__}: "
                        f"{str(chunk_response)[:200]}"
                    )
                    failed_chunks += 1
                    chunk_start = chunk_end + 1
                    continue

                response_candles.extend(chunk_response)
                chunk_start = chunk_end + 1

            # A single bad chunk inside a long range stays tolerated - the rest
            # of the series is still worth returning. Every chunk failing is a
            # different animal: there is no series at all, so surface it as an
            # error instead of an empty success (#1944).
            if attempted_chunks and failed_chunks == attempted_chunks:
                raise Exception(
                    f"All {attempted_chunks} {endpoint} chunk request(s) failed for "
                    f"{symbol}/{oa_exchange} between {start_date_str} and {end_date_str}"
                )

            if interval == "D" and not response_candles:
                # An unknown index name resolves to an empty list rather than
                # an error, so say which symbol Shoonya did not recognise.
                logger.warning(
                    f"EODChartData returned no daily candles for {exchange}:{eod_symbol} "
                    f"({symbol}/{oa_exchange}) between {start_ts} and {end_ts}"
                )

            # Convert candles to rows. Both endpoints carry `ssboe` (epoch)
            # alongside `time` — DD-MM-YYYY HH:MM:SS for TPSeries, DD-MON-YYYY
            # for EODChartData. Prefer ssboe: it is already an integer and
            # avoids both the format split and timezone quirks. EODChartData
            # rows arrive as JSON strings and carry no `oi`.
            data = []
            for candle in response_candles:
                if isinstance(candle, str):
                    try:
                        candle = json.loads(candle)
                    except json.JSONDecodeError:
                        logger.error(f"Non-JSON candle entry, skipping: {candle[:200]}")
                        continue

                if not isinstance(candle, dict):
                    continue

                try:
                    # Skip candles with all zero OHLC (stale ticks)
                    if (
                        float(candle.get("into", 0)) == 0
                        and float(candle.get("inth", 0)) == 0
                        and float(candle.get("intl", 0)) == 0
                        and float(candle.get("intc", 0)) == 0
                    ):
                        continue

                    ssboe = candle.get("ssboe")
                    if ssboe is not None:
                        timestamp = int(ssboe)
                    else:
                        # TPSeries `time` is IST wall-clock, so a naive parse
                        # against the host clock reproduces its ssboe. The
                        # date-only EODChartData form has no clock at all and
                        # must be pinned to 00:00 UTC — the convention every
                        # other daily bar here uses — or it would land 5.5
                        # hours early and miss the timestamp dedupe.
                        timestamp = None
                        for time_format, as_utc in (
                            ("%d-%m-%Y %H:%M:%S", False),
                            ("%d-%b-%Y", True),
                        ):
                            try:
                                parsed = datetime.strptime(candle["time"], time_format)
                            except ValueError:
                                continue
                            if as_utc:
                                parsed = parsed.replace(tzinfo=UTC)
                            timestamp = int(parsed.timestamp())
                            break
                        if timestamp is None:
                            logger.error(f"Unparseable candle time, skipping: {candle}")
                            continue

                    data.append(
                        {
                            "timestamp": timestamp,
                            "open": float(candle.get("into", 0)),
                            "high": float(candle.get("inth", 0)),
                            "low": float(candle.get("intl", 0)),
                            "close": float(candle.get("intc", 0)),
                            "volume": float(candle.get("intv", 0)),
                            "oi": float(candle.get("oi", 0)),
                        }
                    )
                except (KeyError, ValueError) as e:
                    logger.error(f"Error parsing candle data: {e}, Candle: {candle}")
                    continue

            df = pd.DataFrame(data)
            if df.empty:
                df = pd.DataFrame(
                    columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
                )

            # For daily data, append today's data from quotes if it's missing
            if interval == "D":
                # EODChartData stamps each daily bar at 00:00:00 UTC of the
                # trade date, so today's synthetic bar has to use the same
                # convention or it lands 5.5 hours before the previous close.
                # Matches flattrade/tradesmart/zebu.
                utc_today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                today_ts = int((utc_today + timedelta(hours=5, minutes=30)).timestamp())

                # Only get today's data if it's within the requested range
                if today_ts >= start_ts and today_ts <= end_ts:
                    if df.empty or df["timestamp"].max() < today_ts:
                        try:
                            # Get today's data from quotes. A wrong-instrument
                            # reply raises here and is caught below, so today's
                            # candle is left out rather than filled with
                            # another instrument's open/high/low/close.
                            quotes_response = get_quotes_response(
                                self.auth_token,
                                exchange,
                                token,
                                context=f" for {symbol} today-candle",
                            )
                            logger.debug(f"Quotes Response: {quotes_response}")  # Debug print

                            if quotes_response and quotes_response.get("stat") == "Ok":
                                today_data = {
                                    "timestamp": today_ts,
                                    "open": float(quotes_response.get("o", 0)),
                                    "high": float(quotes_response.get("h", 0)),
                                    "low": float(quotes_response.get("l", 0)),
                                    "close": float(
                                        quotes_response.get("lp", 0)
                                    ),  # Use LTP as close
                                    "volume": float(quotes_response.get("v", 0)),
                                    "oi": float(quotes_response.get("oi", 0)),
                                }
                                logger.debug(f"Today's quote data: {today_data}")
                                # Append today's data. Concatenating onto the
                                # all-NA placeholder frame raises a pandas
                                # FutureWarning, so replace it outright when
                                # the broker returned no candles at all.
                                today_df = pd.DataFrame([today_data])
                                df = (
                                    today_df
                                    if df.empty
                                    else pd.concat([df, today_df], ignore_index=True)
                                )
                                logger.debug("Added today's data from quotes")
                        except Exception as e:
                            logger.info(f"Error fetching today's data from quotes: {e}")
                else:
                    logger.info(
                        f"Today ({today_ts}) is outside requested range ({start_ts} to {end_ts})"
                    )

            # Sort by timestamp. Adjacent chunks are half-open, but a candle
            # landing exactly on a boundary would otherwise appear twice.
            df = df.sort_values("timestamp").drop_duplicates(subset="timestamp", keep="last")
            return df.reset_index(drop=True)

        except Exception as e:
            logger.error(f"Error in get_history: {e}")  # Add debug logging
            raise Exception(f"Error fetching historical data: {str(e)}")
