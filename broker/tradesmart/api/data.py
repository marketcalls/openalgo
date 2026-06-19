import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pandas as pd

from broker.tradesmart.api.baseurl import post, resolve_uid
from database.token_db import get_br_symbol, get_token
from utils.logging import get_logger

logger = get_logger(__name__)

# Global rate limiter — TradeSmart (Noren) caps data APIs at 120 requests/min
# per user (it returns "... exceeds Limit 120 for user" past that). 0.55s/req
# ≈ 109/min keeps the whole app — quotes, option chain, OI tracker, scalping,
# history — under the ceiling through this single shared gate.
_last_api_call_time = 0.0
_rate_limit_lock = threading.Lock()
TRADESMART_MIN_REQUEST_INTERVAL = 0.55  # ~109 req/min, under the 120/min cap


def _apply_rate_limit():
    """Serialize API calls across threads; reserve the slot, sleep outside the lock."""
    global _last_api_call_time
    sleep_time = 0.0
    with _rate_limit_lock:
        current_time = time.time()
        elapsed = current_time - _last_api_call_time
        if elapsed < TRADESMART_MIN_REQUEST_INTERVAL:
            sleep_time = TRADESMART_MIN_REQUEST_INTERVAL - elapsed
        _last_api_call_time = current_time + sleep_time
    if sleep_time > 0:
        time.sleep(sleep_time)


def _normalize_data_exchange(exchange):
    """Map OpenAlgo index pseudo-exchanges to their parent cash exchange for data."""
    if exchange == "NSE_INDEX":
        return "NSE"
    if exchange == "BSE_INDEX":
        return "BSE"
    return exchange


def _is_rate_limit_error(response) -> bool:
    """Return True when TradeSmart reports a per-minute rate-limit hit.

    Noren returns ``stat=Not_Ok`` with an emsg like "Invalid Input :  Order
    Recieved 141 in a current minute exceeds Limit 120 for user" once the
    minute's data-API budget is exhausted.
    """
    if not isinstance(response, dict):
        return False
    if response.get("stat") != "Not_Ok":
        return False
    emsg = response.get("emsg", "")
    return "exceeds Limit" in emsg or "exceeds limit" in emsg


def _get_api_response(endpoint, auth, payload, retry_count=0):
    """Rate-limited POST returning parsed JSON (dict or list).

    Retries with exponential backoff when TradeSmart reports a per-minute
    rate-limit hit, so a burst of quote requests (e.g. a 90+ symbol option
    chain or the OI tracker) degrades to slower-but-successful instead of
    failing the whole batch.
    """
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0  # base seconds for exponential backoff

    _apply_rate_limit()
    payload.setdefault("uid", resolve_uid(auth))
    response = post(endpoint, payload, auth)
    parsed = json.loads(response.text)

    if _is_rate_limit_error(parsed) and retry_count < MAX_RETRIES:
        retry_delay = RETRY_DELAY * (2**retry_count)
        logger.warning(
            f"TradeSmart rate limit hit ({parsed.get('emsg')}). "
            f"Retrying in {retry_delay}s (attempt {retry_count + 1}/{MAX_RETRIES})"
        )
        time.sleep(retry_delay)
        return _get_api_response(endpoint, auth, payload, retry_count + 1)

    return parsed


class BrokerData:
    def __init__(self, auth_token):
        """Initialize TradeSmart data handler with an access token."""
        self.auth_token = auth_token
        # OpenAlgo interval -> TradeSmart TPSeries interval (minutes). 'D' -> EOD.
        self.timeframe_map = {
            "1m": "1",
            "3m": "3",
            "5m": "5",
            "10m": "10",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "2h": "120",
            "D": "D",
        }

    def _quote_dict(self, response):
        """Build the OpenAlgo quote dict from a GetQuotes response."""
        return {
            "bid": float(response.get("bp1", 0)),
            "ask": float(response.get("sp1", 0)),
            "open": float(response.get("o", 0)),
            "high": float(response.get("h", 0)),
            "low": float(response.get("l", 0)),
            "ltp": float(response.get("lp", 0)),
            "prev_close": float(response.get("c", 0)) if "c" in response else 0,
            "volume": int(float(response.get("v", 0))),
            "oi": int(float(response.get("oi", 0))),
            "tick_size": float(response.get("ti", 0)) if response.get("ti") else None,
        }

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """Get a quote snapshot for a single symbol."""
        try:
            token = get_token(symbol, exchange)
            api_exchange = _normalize_data_exchange(exchange)

            payload = {"exch": api_exchange, "token": token}
            response = _get_api_response("/GetQuotes", self.auth_token, payload)

            if response.get("stat") != "Ok":
                raise Exception(
                    f"Error from TradeSmart API: {response.get('emsg', 'Unknown error')}"
                )
            return self._quote_dict(response)
        except Exception as e:
            raise Exception(f"Error fetching quotes: {str(e)}") from e

    def get_multiquotes(self, symbols: list) -> list:
        """Get quotes for many symbols.

        TradeSmart has no batch-quote endpoint, so fan out concurrent GetQuotes
        calls (the shared rate limiter keeps them under the request ceiling).
        Returns ``[{'symbol','exchange','data'|'error'}, ...]``.
        """
        if not symbols:
            return []

        prepared = []
        results = []
        for item in symbols:
            symbol = item["symbol"]
            exchange = item["exchange"]
            token = get_token(symbol, exchange)
            if not token:
                results.append(
                    {"symbol": symbol, "exchange": exchange, "error": "Token not resolved"}
                )
                continue
            prepared.append(
                {
                    "symbol": symbol,
                    "exchange": exchange,
                    "api_exchange": _normalize_data_exchange(exchange),
                    "token": token,
                }
            )

        if not prepared:
            return results

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_map = {
                executor.submit(self._fetch_single_quote, item): item for item in prepared
            }
            for future in as_completed(future_map):
                item = future_map[future]
                try:
                    results.append(future.result())
                except Exception as e:
                    results.append(
                        {"symbol": item["symbol"], "exchange": item["exchange"], "error": str(e)}
                    )

        return results

    def _fetch_single_quote(self, item: dict) -> dict:
        """Fetch one quote (used by the multiquotes thread pool)."""
        try:
            payload = {"exch": item["api_exchange"], "token": item["token"]}
            response = _get_api_response("/GetQuotes", self.auth_token, payload)
            if response.get("stat") != "Ok":
                return {
                    "symbol": item["symbol"],
                    "exchange": item["exchange"],
                    "error": response.get("emsg", "Unknown error"),
                }
            return {
                "symbol": item["symbol"],
                "exchange": item["exchange"],
                "data": self._quote_dict(response),
            }
        except Exception as e:
            return {"symbol": item["symbol"], "exchange": item["exchange"], "error": str(e)}

    def get_depth(self, symbol: str, exchange: str) -> dict:
        """Get 5-level market depth for a single symbol."""
        try:
            token = get_token(symbol, exchange)
            api_exchange = _normalize_data_exchange(exchange)

            payload = {"exch": api_exchange, "token": token}
            response = _get_api_response("/GetQuotes", self.auth_token, payload)

            if response.get("stat") != "Ok":
                raise Exception(
                    f"Error from TradeSmart API: {response.get('emsg', 'Unknown error')}"
                )

            bids = []
            asks = []
            for i in range(1, 6):
                bids.append(
                    {
                        "price": float(response.get(f"bp{i}", 0)),
                        "quantity": int(float(response.get(f"bq{i}", 0))),
                        "orders": int(float(response.get(f"bo{i}", 0))),
                    }
                )
                asks.append(
                    {
                        "price": float(response.get(f"sp{i}", 0)),
                        "quantity": int(float(response.get(f"sq{i}", 0))),
                        "orders": int(float(response.get(f"so{i}", 0))),
                    }
                )

            return {
                "bids": bids,
                "asks": asks,
                "totalbuyqty": sum(bid["quantity"] for bid in bids),
                "totalsellqty": sum(ask["quantity"] for ask in asks),
                "high": float(response.get("h", 0)),
                "low": float(response.get("l", 0)),
                "ltp": float(response.get("lp", 0)),
                "ltq": int(float(response.get("ltq", 0))),
                "open": float(response.get("o", 0)),
                "prev_close": float(response.get("c", 0)) if "c" in response else 0,
                "volume": int(float(response.get("v", 0))),
                "oi": int(float(response.get("oi", 0))),
            }
        except Exception as e:
            raise Exception(f"Error fetching market depth: {str(e)}") from e

    # Alias required by some services
    get_market_depth = get_depth

    def get_history(
        self, symbol: str, exchange: str, interval: str, start_date, end_date
    ) -> pd.DataFrame:
        """Get historical candles.

        Daily uses /EODChartData (sym = EXCH:BRSYMBOL); intraday uses /TPSeries.
        Returns a DataFrame [timestamp, open, high, low, close, volume, oi] with
        ``timestamp`` in epoch seconds.
        """
        try:
            if interval not in self.timeframe_map:
                supported = list(self.timeframe_map.keys())
                raise Exception(
                    f"Unsupported interval '{interval}'. Supported: {', '.join(supported)}"
                )

            br_symbol = get_br_symbol(symbol, exchange)
            token = get_token(symbol, exchange)
            api_exchange = _normalize_data_exchange(exchange)

            start_date_str = (
                start_date.strftime("%Y-%m-%d")
                if hasattr(start_date, "strftime")
                else str(start_date)
            )
            end_date_str = (
                end_date.strftime("%Y-%m-%d") if hasattr(end_date, "strftime") else str(end_date)
            )

            start_ts = int(
                datetime.strptime(start_date_str + " 00:00:00", "%Y-%m-%d %H:%M:%S").timestamp()
            )
            end_ts = int(
                datetime.strptime(end_date_str + " 23:59:59", "%Y-%m-%d %H:%M:%S").timestamp()
            )

            if interval == "D":
                payload = {
                    "sym": f"{api_exchange}:{br_symbol}",
                    "from": str(start_ts),
                    "to": str(end_ts),
                }
                _apply_rate_limit()
                try:
                    response = json.loads(post("/EODChartData", payload, self.auth_token).text)
                except Exception as e:
                    logger.error(f"EOD request error: {e}")
                    response = []
            else:
                payload = {
                    "uid": resolve_uid(self.auth_token),
                    "exch": api_exchange,
                    "token": token,
                    "st": str(start_ts),
                    "et": str(end_ts),
                    "intrv": self.timeframe_map[interval],
                }
                _apply_rate_limit()
                response = json.loads(post("/TPSeries", payload, self.auth_token).text)

            if isinstance(response, dict):
                if response.get("stat") == "Not_Ok":
                    emsg = response.get("emsg", "Unknown error")
                    # "no data" is a benign empty result, not an error. TradeSmart's
                    # Noren backend serves no historical series for the CDS currency
                    # segment, and illiquid contracts can have no trades in the window.
                    # Return an empty frame so the caller renders an empty/live chart
                    # instead of surfacing a 500 and logging a traceback every cycle.
                    if "no data" in emsg.lower():
                        return pd.DataFrame(
                            columns=["close", "high", "low", "open", "timestamp", "volume", "oi"]
                        )
                    raise Exception(f"Error from TradeSmart API: {emsg}")
            elif not isinstance(response, list):
                raise Exception("Invalid response format from TradeSmart API")

            data = []
            for candle in response:
                if isinstance(candle, str):
                    candle = json.loads(candle)
                try:
                    if interval == "D":
                        timestamp = int(candle.get("ssboe", 0))
                    else:
                        try:
                            timestamp = int(
                                datetime.strptime(candle["time"], "%d-%m-%Y %H:%M:%S").timestamp()
                            )
                        except (ValueError, KeyError):
                            # Fall back to the epoch field if present
                            if candle.get("ssboe"):
                                timestamp = int(candle["ssboe"])
                            else:
                                continue
                        if (
                            float(candle.get("into", 0)) == 0
                            and float(candle.get("inth", 0)) == 0
                            and float(candle.get("intl", 0)) == 0
                            and float(candle.get("intc", 0)) == 0
                        ):
                            continue

                    data.append(
                        {
                            "timestamp": timestamp,
                            "open": float(candle.get("into", 0)),
                            "high": float(candle.get("inth", 0)),
                            "low": float(candle.get("intl", 0)),
                            "close": float(candle.get("intc", 0)),
                            "volume": int(float(candle.get("intv", 0))),
                            "oi": int(float(candle.get("oi", 0))),
                        }
                    )
                except (KeyError, ValueError) as e:
                    logger.error(f"Error parsing candle: {e}, Candle: {candle}")
                    continue

            df = pd.DataFrame(data)
            if df.empty:
                df = pd.DataFrame(
                    columns=["timestamp", "open", "high", "low", "close", "volume", "oi"]
                )

            # For daily data, append today's candle from quotes if missing. Use an
            # IST-midnight epoch (+5:30) to match the cross-broker daily convention.
            if interval == "D":
                utc_today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                ist_today = utc_today + timedelta(hours=5, minutes=30)
                today_ts = int(ist_today.timestamp())

                if start_ts <= today_ts <= end_ts and (
                    df.empty or df["timestamp"].max() < today_ts
                ):
                    try:
                        quotes = self.get_quotes(symbol, exchange)
                        if quotes:
                            today_data = {
                                "timestamp": today_ts,
                                "open": float(quotes.get("open", 0)),
                                "high": float(quotes.get("high", 0)),
                                "low": float(quotes.get("low", 0)),
                                "close": float(quotes.get("ltp", 0)),
                                "volume": int(float(quotes.get("volume", 0))),
                                "oi": 0,
                            }
                            df = pd.concat([df, pd.DataFrame([today_data])], ignore_index=True)
                    except Exception as e:
                        logger.info(f"Error fetching today's candle from quotes: {e}")

            df = df.sort_values("timestamp")
            df = df[["close", "high", "low", "open", "timestamp", "volume", "oi"]]
            return df

        except Exception as e:
            raise Exception(f"Error fetching historical data: {str(e)}") from e

    def get_intervals(self) -> list:
        """Return supported interval keys."""
        return list(self.timeframe_map.keys())
