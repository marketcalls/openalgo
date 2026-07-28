import asyncio
import json
import os
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

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

    payload_str = "jData=" + json.dumps(data)

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
        return json.loads(data)
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON: {e}")
        logger.debug(f"Response data: {data}")
        raise


def get_chart_api_response(endpoint, auth, method="POST", payload=None):
    """
    Chart data endpoints (EODChartData, TPSeries) use the legacy NorenWClientTP
    path with jKey embedded in the form-urlencoded body (same pattern as
    Flattrade/Finvasia chart APIs). They do not accept Authorization: Bearer
    headers, which is why the previous implementation returned an empty body
    and caused JSONDecodeError at line 1 col 1.
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
    payload_str = "jData=" + json.dumps(data) + "&jKey=" + AUTH_TOKEN

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

            payload = {"exch": exchange, "token": token}

            response = get_api_response(
                "/NorenWClientAPI/GetQuotes", self.auth_token, payload=payload
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

            payload_str = "jData=" + json.dumps(data)
            headers = {
                "Content-Type": "text/plain",
                "Authorization": f"Bearer {self.auth_token}",
            }
            url = "https://api.shoonya.com/NorenWClientAPI/GetQuotes"

            # Use httpx.post for sync requests
            http_response = httpx.post(url, content=payload_str, headers=headers, timeout=10.0)
            response = http_response.json()

            if response.get("stat") != "Ok":
                return {
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": response.get("emsg", "Unknown error"),
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

            payload_str = "jData=" + json.dumps(data)
            headers = {
                "Content-Type": "text/plain",
                "Authorization": f"Bearer {self.auth_token}",
            }
            url = "https://api.shoonya.com/NorenWClientAPI/GetQuotes"

            http_response = await client.post(url, content=payload_str, headers=headers)
            response = http_response.json()

            if response.get("stat") != "Ok":
                return {
                    "symbol": symbol,
                    "exchange": exchange,
                    "error": response.get("emsg", "Unknown error"),
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

            payload = {"exch": exchange, "token": token}

            response = get_api_response(
                "/NorenWClientAPI/GetQuotes", self.auth_token, payload=payload
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
        Per-request window size for TPSeries, in seconds. Shoonya returns
        504 Server Timeout when the range produces too many candles in a
        single call. These values keep each request under roughly a few
        thousand candles (empirically safe).
        """
        # 1m bars: ~375 per trading day -> cap at ~5 days
        # 5m bars: ~75 per day -> ~30 days
        # daily bars: 1 per day -> ~2 years
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

            # Use TPSeries for all intervals (including daily via intrv="D").
            # Post-OAuth, Shoonya's /NorenWClientAPI/EODChartData returns 405
            # Method Not Allowed — the endpoint was removed. TPSeries with
            # intrv="D" covers daily bars, so we route everything through it.
            # Chart endpoints require jKey in the form-urlencoded body (Bearer
            # header alone returns an empty body).
            #
            # TPSeries times out (504 Server Timeout) on long ranges. Chunk
            # the [start_ts, end_ts] window so each request stays within the
            # broker's per-request budget. Chunk size is interval-dependent:
            # minute/hour intervals have many more bars per day than daily.
            chunk_seconds = self._get_history_chunk_seconds(interval)

            response_candles = []
            chunk_start = start_ts
            while chunk_start <= end_ts:
                chunk_end = min(chunk_start + chunk_seconds, end_ts)
                payload = {
                    "exch": exchange,
                    "token": token,
                    "st": str(chunk_start),
                    "et": str(chunk_end),
                    "intrv": self.timeframe_map[interval],
                }
                logger.debug(f"TPSeries Payload: {payload}")

                try:
                    chunk_response = get_chart_api_response(
                        "/NorenWClientAPI/TPSeries", self.auth_token, payload=payload
                    )
                except Exception as e:
                    logger.error(f"TPSeries chunk request failed ({chunk_start}-{chunk_end}): {e}")
                    chunk_start = chunk_end + 1
                    continue

                # TPSeries normally returns a LIST of candles. On error it
                # returns a DICT like {"stat":"Not_Ok","emsg":"..."} — detect
                # that before iterating (the old code iterated dict keys and
                # crashed trying to json.loads("stat")).
                if isinstance(chunk_response, dict):
                    emsg = chunk_response.get("emsg") or chunk_response.get("message") or "unknown"
                    logger.warning(
                        f"TPSeries returned error for chunk {chunk_start}-{chunk_end}: "
                        f"stat={chunk_response.get('stat')} emsg={emsg}"
                    )
                    chunk_start = chunk_end + 1
                    continue

                if not isinstance(chunk_response, list):
                    logger.warning(
                        f"Unexpected TPSeries response type {type(chunk_response).__name__}: "
                        f"{str(chunk_response)[:200]}"
                    )
                    chunk_start = chunk_end + 1
                    continue

                response_candles.extend(chunk_response)
                chunk_start = chunk_end + 1

            # Convert candles to rows. TPSeries returns both `ssboe` (epoch)
            # and `time` (DD-MM-YYYY HH:MM:SS); prefer ssboe — it's already
            # an integer and avoids timezone quirks.
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
                        timestamp = int(
                            datetime.strptime(candle["time"], "%d-%m-%Y %H:%M:%S").timestamp()
                        )

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
                today_ts = int(
                    datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
                )

                # Only get today's data if it's within the requested range
                if today_ts >= start_ts and today_ts <= end_ts:
                    if df.empty or df["timestamp"].max() < today_ts:
                        try:
                            # Get today's data from quotes
                            payload = {"exch": exchange, "token": token}
                            quotes_response = get_api_response(
                                "/NorenWClientAPI/GetQuotes", self.auth_token, payload=payload
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
                                # Append today's data
                                df = pd.concat([df, pd.DataFrame([today_data])], ignore_index=True)
                                logger.debug("Added today's data from quotes")
                        except Exception as e:
                            logger.info(f"Error fetching today's data from quotes: {e}")
                else:
                    logger.info(
                        f"Today ({{today_ts}}) is outside requested range ({{start_ts}} to {end_ts})"
                    )

            # Sort by timestamp
            df = df.sort_values("timestamp")
            return df

        except Exception as e:
            logger.error(f"Error in get_history: {e}")  # Add debug logging
            raise Exception(f"Error fetching historical data: {str(e)}")
