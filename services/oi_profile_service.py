"""
OI Profile Service
Combines futures candlestick data with options Open Interest profile.

Three panels:
  1. Futures OHLC candles (intraday, user-selected interval)
  2. Current OI butterfly (CE right, PE left per strike)
  3. Daily OI change butterfly (CE change right, PE change left)

Current OI is fetched efficiently via option chain (multiquotes).
OI change is computed from history (parallel execution) — either the
default daily delta (vs previous day's close), or, when an optional
window_start/window_end is given, the delta across that arbitrary
intraday window.
"""

import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import pytz
from cachetools import TTLCache

from database.market_calendar_db import is_market_open
from database.token_db_enhanced import fno_search_symbols
from services.history_service import get_history
from services.option_chain_service import get_option_chain
from services.strategy_chart_service import (
    _cap_last_n_trading_dates,
    _resolve_trading_window,
)
from utils.constants import CRYPTO_EXCHANGES, INSTRUMENT_PERPFUT
from utils.logging import get_logger

logger = get_logger(__name__)

# --- Shared profile cache -------------------------------------------------
#
# One OI Profile answer costs a multiquote over ~80 option legs (plus a
# futures history call, and one history call per leg when the OI change is
# asked for). Every chart tab, every browser and the /oiprofile page all ask
# for the same picture, and the exchange only republishes open interest every
# few minutes - so recomputing per request is pure broker load for numbers
# that cannot have moved. Answers are therefore shared for a short TTL,
# keyed by everything that defines the payload.
#
# Bounded via maxsize so it cannot grow without limit in a long-lived worker
# (see the FD/memory hygiene rules in CLAUDE.md).
_CACHE_TTL = float(os.getenv("OI_PROFILE_CACHE_TTL", "60"))
_CACHE_MAXSIZE = int(os.getenv("OI_PROFILE_CACHE_MAXSIZE", "64"))
_profile_cache: TTLCache = TTLCache(maxsize=max(_CACHE_MAXSIZE, 1), ttl=max(_CACHE_TTL, 0.001))
_profile_cache_lock = threading.Lock()

# Previous session's closing OI, per option symbol. It is settled history: it
# cannot change again until tomorrow, yet reading it costs one broker history
# call per leg behind a process-wide ~350ms gate, so an 80-leg chain spends
# most of a minute rediscovering yesterday. Cached for the session, which is
# what makes "Change in OI" usable at all.
_PREV_OI_TTL = float(os.getenv("OI_PROFILE_PREV_OI_TTL", "21600"))  # 6 hours
_PREV_OI_MAXSIZE = int(os.getenv("OI_PROFILE_PREV_OI_MAXSIZE", "4096"))
_prev_oi_cache: TTLCache = TTLCache(maxsize=max(_PREV_OI_MAXSIZE, 1), ttl=max(_PREV_OI_TTL, 0.001))
_prev_oi_cache_lock = threading.Lock()

# Index symbols that need special exchange for quotes
NSE_INDEX_SYMBOLS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
}

BSE_INDEX_SYMBOLS = {"SENSEX", "BANKEX", "SENSEX50"}


def _find_futures_symbol(
    underlying: str, exchange: str, expiry_date: str, api_key: str
) -> dict | None:
    """
    Find the futures contract matching the underlying and expiry.

    Returns dict with 'symbol' and 'exchange' keys, or None.
    """
    try:
        # Convert DDMMMYY to DD-MMM-YY for database lookup
        expiry_formatted = f"{expiry_date[:2]}-{expiry_date[2:5]}-{expiry_date[5:]}".upper()

        # Search for futures contract matching this expiry
        # For crypto exchanges, perpetuals (PERPFUT) serve as the underlying
        if exchange.upper() in CRYPTO_EXCHANGES:
            _perp = fno_search_symbols(
                query=f"{underlying}USDFUT",
                exchange=exchange,
                instrumenttype=INSTRUMENT_PERPFUT,
                limit=1,
            )
            if not _perp:
                return None
            futures = [{"symbol": _perp[0]["symbol"], "exchange": _perp[0]["exchange"]}]
        else:
            futures = fno_search_symbols(
                underlying=underlying,
                exchange=exchange,
                instrumenttype="FUT",
                expiry=expiry_formatted,
                limit=1,
            )

        if not futures:
            # Try without expiry filter to get nearest futures
            if exchange.upper() in CRYPTO_EXCHANGES:
                logger.warning(f"No perpetual contracts found for {underlying} on {exchange}")
                return None
            futures = fno_search_symbols(
                underlying=underlying,
                exchange=exchange,
                instrumenttype="FUT",
                limit=10,
            )
            if not futures:
                logger.warning(f"No futures contracts found for {underlying} on {exchange}")
                return None

            # Sort by expiry to get nearest
            def parse_expiry(exp_str: str) -> datetime:
                try:
                    return datetime.strptime(exp_str, "%d-%b-%y")
                except (ValueError, TypeError):
                    return datetime.max

            futures.sort(key=lambda f: parse_expiry(f.get("expiry", "")))

        return {"symbol": futures[0]["symbol"], "exchange": futures[0]["exchange"]}
    except Exception as e:
        logger.warning(f"Error finding futures symbol: {e}")
        return None


def _previous_session_oi(candles: list[dict]) -> float:
    """
    OI at the close of the session before the latest one that traded.

    Not simply ``candles[-2]``. Outside market hours the broker appends a
    candle for the new calendar date carrying the last quote, so the newest two
    rows are an exact copy of each other; taking the second-to-last then
    compares a session against itself and reports every strike as unchanged.
    A trader opening the chart in the evening wants the day's build, not a
    screen of zeros, so an identical trailing row is dropped first.
    """
    if not candles:
        return 0.0

    rows = list(candles)
    last = rows[-1]
    while len(rows) >= 2 and _same_session_row(rows[-2], last):
        rows.pop()

    if len(rows) < 2:
        return 0.0
    return float(rows[-2].get("oi", 0) or 0)


def _same_session_row(a: dict, b: dict) -> bool:
    """Whether two daily candles carry the same session's numbers."""
    return all(a.get(k) == b.get(k) for k in ("open", "high", "low", "close", "volume", "oi"))


def _fetch_daily_oi_changes(
    option_symbols: list[dict], options_exchange: str, api_key: str
) -> dict[str, float]:
    """
    Fetch daily history for options and return previous day's OI.

    Yesterday's close is settled, so each symbol is fetched once per session
    and then served from a cache. Whatever is left uses sequential batch
    processing with rate-limit handling to avoid broker 429 errors: batches
    with delays between them, and retries with exponential backoff.

    Args:
        option_symbols: List of dicts with 'symbol' key
        options_exchange: Exchange for options (NFO, BFO)
        api_key: OpenAlgo API key

    Returns:
        Dict mapping symbol -> previous_day_oi
    """
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

    results = {}

    # Only fetch for symbols with non-zero current OI, and only those whose
    # previous close is not already known for this session.
    symbols_to_fetch = []
    with _prev_oi_cache_lock:
        for s in option_symbols:
            symbol = s["symbol"]
            if s.get("oi", 0) <= 0:
                continue
            cached = _prev_oi_cache.get((symbol, options_exchange))
            if cached is None:
                symbols_to_fetch.append(symbol)
            else:
                results[symbol] = cached

    if not symbols_to_fetch:
        return results

    BATCH_SIZE = 5
    BATCH_DELAY = 0.5  # seconds between batches
    MAX_RETRIES = 2
    RETRY_BASE_DELAY = 1.0  # seconds, doubles each retry

    def fetch_one_with_retry(symbol: str) -> tuple[str, float]:
        for attempt in range(MAX_RETRIES + 1):
            try:
                success, resp, status_code = get_history(
                    symbol=symbol,
                    exchange=options_exchange,
                    interval="D",
                    start_date=start,
                    end_date=end,
                    api_key=api_key,
                )
                if success and resp.get("data"):
                    return symbol, _previous_session_oi(resp["data"])

                # Rate limited - retry with backoff
                if status_code == 429 and attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"Rate limited fetching {symbol}, retry {attempt + 1} after {delay}s"
                    )
                    time.sleep(delay)
                    continue

                return symbol, 0.0
            except Exception as e:
                if attempt < MAX_RETRIES and "429" in str(e):
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"Rate limited fetching {symbol}, retry {attempt + 1} after {delay}s"
                    )
                    time.sleep(delay)
                    continue
                return symbol, 0.0
        return symbol, 0.0

    # Process in batches to respect rate limits
    for i in range(0, len(symbols_to_fetch), BATCH_SIZE):
        batch = symbols_to_fetch[i : i + BATCH_SIZE]
        for symbol in batch:
            sym, prev_oi = fetch_one_with_retry(symbol)
            results[sym] = prev_oi
            # A zero is "the broker had nothing to say", not a settled close,
            # so it is not worth remembering for the rest of the day.
            if prev_oi > 0:
                with _prev_oi_cache_lock:
                    _prev_oi_cache[(sym, options_exchange)] = prev_oi

        # Delay between batches (skip after last batch)
        if i + BATCH_SIZE < len(symbols_to_fetch):
            time.sleep(BATCH_DELAY)

    return results


def _oi_at_or_before(candles: list[dict], target_time: int) -> float:
    """Last candle's OI at or before target_time (unix seconds), else 0.0."""
    best = None
    for c in candles:
        t = c.get("time")
        if t is None:
            ts = c.get("timestamp")
            if ts is None:
                continue
            t = int(ts // 1000) if ts > 1e12 else int(ts)
        if t <= target_time and (best is None or t > best[0]):
            best = (t, c.get("oi", 0) or 0)
    return float(best[1]) if best else 0.0


def _fetch_windowed_oi_changes(
    option_symbols: list[dict],
    options_exchange: str,
    interval: str,
    window_start: int,
    window_end: int,
    api_key: str,
) -> dict[str, float]:
    """
    Fetch intraday history for options and return OI change over an
    arbitrary [window_start, window_end] range (unix seconds), at the same
    interval used for the futures candles.

    Mirrors _fetch_daily_oi_changes's batching/retry shape exactly, only the
    interval/date-range and the OI(end) - OI(start) computation differ.

    Returns:
        Dict mapping symbol -> (oi_at_window_end - oi_at_window_start)
    """
    ist = pytz.timezone("Asia/Kolkata")
    start = datetime.fromtimestamp(window_start, ist).strftime("%Y-%m-%d")
    end = datetime.fromtimestamp(window_end, ist).strftime("%Y-%m-%d")

    results = {}

    symbols_to_fetch = [s["symbol"] for s in option_symbols if s.get("oi", 0) > 0]

    if not symbols_to_fetch:
        return results

    BATCH_SIZE = 5
    BATCH_DELAY = 0.5  # seconds between batches
    MAX_RETRIES = 2
    RETRY_BASE_DELAY = 1.0  # seconds, doubles each retry

    def fetch_one_with_retry(symbol: str) -> tuple[str, float]:
        for attempt in range(MAX_RETRIES + 1):
            try:
                success, resp, status_code = get_history(
                    symbol=symbol,
                    exchange=options_exchange,
                    interval=interval,
                    start_date=start,
                    end_date=end,
                    api_key=api_key,
                )
                if success and resp.get("data"):
                    data = resp["data"]
                    oi_start = _oi_at_or_before(data, window_start)
                    oi_end = _oi_at_or_before(data, window_end)
                    return symbol, oi_end - oi_start

                if status_code == 429 and attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"Rate limited fetching {symbol}, retry {attempt + 1} after {delay}s"
                    )
                    time.sleep(delay)
                    continue

                return symbol, 0.0
            except Exception as e:
                if attempt < MAX_RETRIES and "429" in str(e):
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"Rate limited fetching {symbol}, retry {attempt + 1} after {delay}s"
                    )
                    time.sleep(delay)
                    continue
                return symbol, 0.0
        return symbol, 0.0

    for i in range(0, len(symbols_to_fetch), BATCH_SIZE):
        batch = symbols_to_fetch[i : i + BATCH_SIZE]
        for symbol in batch:
            sym, oi_change = fetch_one_with_retry(symbol)
            results[sym] = oi_change

        if i + BATCH_SIZE < len(symbols_to_fetch):
            time.sleep(BATCH_DELAY)

    return results


def _market_open(exchange: str) -> bool:
    """Whether the exchange is in session right now, False if unknown."""
    try:
        return bool(is_market_open(exchange))
    except Exception:
        logger.warning(f"Could not read market status for {exchange}", exc_info=True)
        return False


def get_oi_profile_data(
    underlying: str,
    exchange: str,
    expiry_date: str,
    interval: str,
    days: int,
    api_key: str,
    window_start: int | None = None,
    window_end: int | None = None,
    expiry_dates: list[str] | None = None,
    include_change: bool = True,
    include_candles: bool = True,
    strike_count: int = 20,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get OI Profile data: futures candles + OI butterfly + OI change.

    Args:
        underlying: Underlying symbol (e.g., NIFTY, BANKNIFTY)
        exchange: Exchange (NFO, BFO)
        expiry_date: Expiry in DDMMMYY format
        interval: Candle interval (1m, 5m, 15m)
        days: Number of days for futures candles
        api_key: OpenAlgo API key
        window_start: Optional unix seconds. When both window_start and
            window_end are given, OI change is computed for that arbitrary
            window instead of the default "vs previous day's close".
        window_end: Optional unix seconds, paired with window_start.
        expiry_dates: Optional list of expiries (DDMMMYY) to sum OI across.
            When given, it replaces expiry_date; the first entry drives the
            spot/ATM/futures context and the rest only add OI per strike.
        include_change: When False, skip the OI-change pass (which costs one
            history call per option leg) and report every change as zero.
        include_candles: When False, skip the futures lookup and its history
            call. The chart overlay draws on bars it already has.
        strike_count: Strikes either side of ATM. Every strike is two option
            legs to quote, and one history call each when the change is asked
            for, so a narrower window is a faster answer.

    Returns:
        Tuple of (success, response_data, status_code)
    """
    cache_key = (
        underlying.upper(),
        exchange.upper(),
        tuple(expiry_dates or [expiry_date]),
        interval,
        days,
        window_start,
        window_end,
        include_change,
        include_candles,
        strike_count,
    )
    with _profile_cache_lock:
        cached = _profile_cache.get(cache_key)
    if cached is not None:
        return True, cached, 200

    try:
        # Determine options exchange
        options_exchange = exchange.upper()
        if options_exchange in ("NSE_INDEX", "NSE"):
            options_exchange = "NFO"
        elif options_exchange in ("BSE_INDEX", "BSE"):
            options_exchange = "BFO"

        # Step 1: Get option chain per expiry (current OI via multiquotes).
        # Multiple expiries are summed per strike, the way Sensibull's OI
        # Profile shows cumulative OI across the expiries you tick.
        expiries = [e for e in (expiry_dates or [expiry_date]) if e]
        if not expiries:
            return False, {"status": "error", "message": "Select at least one expiry"}, 400

        chain_response = None
        strike_map: dict[float, dict] = {}
        option_symbols_for_history: list[dict] = []
        lot_size = None

        for expiry in expiries:
            success, resp, status_code = get_option_chain(
                underlying=underlying,
                exchange=exchange,
                expiry_date=expiry,
                strike_count=strike_count,
                api_key=api_key,
            )

            if not success:
                if chain_response is None:
                    # Nothing usable at all - surface the broker's answer.
                    return False, resp, status_code
                logger.warning(f"OI Profile: no option chain for {underlying} {expiry}, skipped")
                continue

            # The first expiry that answers sets spot, ATM and the futures leg.
            if chain_response is None:
                chain_response = resp

            for item in resp.get("chain", []):
                strike = item["strike"]
                row = strike_map.setdefault(
                    strike,
                    {
                        "strike": strike,
                        "ce_oi": 0,
                        "pe_oi": 0,
                        "ce_legs": [],
                        "pe_legs": [],
                        "ce_oi_change": 0,
                        "pe_oi_change": 0,
                    },
                )

                for side in ("ce", "pe"):
                    leg = item.get(side)
                    if not leg:
                        continue
                    oi = leg.get("oi", 0) or 0
                    symbol = leg.get("symbol")
                    row[f"{side}_oi"] += oi
                    if lot_size is None and leg.get("lotsize"):
                        lot_size = leg["lotsize"]
                    if symbol and oi > 0:
                        row[f"{side}_legs"].append((symbol, oi))
                        option_symbols_for_history.append(
                            {
                                "symbol": symbol,
                                "type": side.upper(),
                                "strike": strike,
                                "oi": oi,
                            }
                        )

        if chain_response is None:
            return False, {"status": "error", "message": "No option chain data available"}, 502

        oi_chain = [strike_map[k] for k in sorted(strike_map)]
        atm_strike = chain_response.get("atm_strike")
        spot_price = chain_response.get("underlying_ltp")

        # Step 2: Find futures symbol and fetch candles
        candles = []
        futures_symbol = None
        futures_info = (
            _find_futures_symbol(underlying, options_exchange, expiries[0], api_key)
            if include_candles
            else None
        )

        if futures_info:
            futures_symbol = futures_info["symbol"]
            fut_exchange = futures_info["exchange"]

            ist = pytz.timezone("Asia/Kolkata")
            # Generous calendar window; post-filter the returned candles to
            # the last N distinct trading dates with data so "3 days" stays
            # 3 days even when queried before market open / on holidays.
            start_date, end_date = _resolve_trading_window(days, ist)

            success_h, hist_response, _ = get_history(
                symbol=futures_symbol,
                exchange=fut_exchange,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
                api_key=api_key,
            )

            if success_h and hist_response.get("data"):
                candles = hist_response["data"]
                # Normalize each candle's timestamp key so the helper can
                # read it — get_history returns `timestamp` in seconds/ms.
                # The helper expects a `time` key (Unix seconds) so tag that
                # from the existing `timestamp` column if needed.
                for c in candles:
                    if "time" not in c and "timestamp" in c:
                        try:
                            ts_val = c["timestamp"]
                            # Heuristic: ms if > 10^12, else seconds.
                            c["time"] = int(ts_val // 1000) if ts_val > 1e12 else int(ts_val)
                        except (TypeError, ValueError):
                            pass
                candles = _cap_last_n_trading_dates(candles, days, ist)

        # Step 3: Fetch OI changes — either an arbitrary window, or the
        # default "vs previous day's close".
        windowed = window_start is not None and window_end is not None
        oi_change_map = {}
        prev_oi_map = {}
        if include_change:
            if windowed:
                oi_change_map = _fetch_windowed_oi_changes(
                    option_symbols_for_history,
                    options_exchange,
                    interval,
                    window_start,
                    window_end,
                    api_key,
                )
            else:
                prev_oi_map = _fetch_daily_oi_changes(
                    option_symbols_for_history, options_exchange, api_key
                )

        # Step 4: Compute OI changes, summed over every selected expiry
        for item in oi_chain:
            for side in ("ce", "pe"):
                change = 0.0
                for symbol, current_oi in item[f"{side}_legs"]:
                    if windowed:
                        change += oi_change_map.get(symbol, 0.0)
                    elif symbol in prev_oi_map:
                        change += current_oi - prev_oi_map[symbol]
                item[f"{side}_oi_change"] = change
            # Internal bookkeeping, not part of the response
            item.pop("ce_legs", None)
            item.pop("pe_legs", None)

        payload = {
            "status": "success",
            "underlying": chain_response.get("underlying", underlying),
            "spot_price": spot_price,
            "atm_strike": atm_strike,
            "lot_size": lot_size or 1,
            "expiry_date": expiries[0],
            "strike_count": strike_count,
            "expiry_dates": expiries,
            "futures_symbol": futures_symbol,
            "interval": interval,
            "candles": candles,
            "oi_chain": oi_chain,
            "window_start": window_start,
            "window_end": window_end,
            # Lets a live overlay stop asking once the exchange has closed,
            # instead of polling a number that cannot move until tomorrow.
            "market_open": _market_open(options_exchange),
        }

        with _profile_cache_lock:
            _profile_cache[cache_key] = payload

        return True, payload, 200

    except Exception as e:
        logger.exception(f"Error in get_oi_profile_data: {e}")
        return (
            False,
            {"status": "error", "message": "Error fetching OI Profile data"},
            500,
        )
