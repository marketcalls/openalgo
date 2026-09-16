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

# Open interest each option carried into the current session, per symbol. The
# opening bar cannot change once the session has started, yet reading it costs
# one broker history call per leg behind a process-wide ~350ms gate, so an
# 80-leg chain spends most of a minute rediscovering the open. Cached for the
# session, which is what makes "Change in OI" usable at all.
#
# The TTL has to outlast a session: 09:15 to 15:30 is over six hours, so a
# six-hour TTL expired mid-afternoon and made the next request refetch all ~80
# legs for the same immutable number, stalling it for half a minute. Twelve is
# still well short of the next session, and `maxsize` is the real bound anyway.
_PREV_OI_TTL = float(os.getenv("OI_PROFILE_PREV_OI_TTL", "43200"))  # 12 hours
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


def _session_open_oi(candles: list[dict]) -> float:
    """
    Open interest carried into the latest session present in ``candles``.

    This is the anchor "Change in OI" is measured from, and it has to come
    from the intraday series rather than the daily one. A daily candle's OI
    is the last value the broker saw *during* that session; the exchange
    then settles and republishes, and the settled figure is what the next
    session opens on. Measured on NIFTY22SEP2623200PE: the daily candle for
    15-Sep closed at 4,552,925 while 16-Sep opened at 6,614,400, so a chart
    anchored on the daily row showed a phantom 2 million build on every
    strike from the first second of the session, before a single contract
    had traded.

    Anchoring on the opening bar keeps the anchor and the live chain OI in
    the same family, so the change is the session's own build and nothing
    else. It reads zero at the open, which is the correct answer.

    Returns 0.0 when the series carries no usable session.
    """
    session = _latest_session_rows(candles)
    if not session:
        return 0.0
    return float(session[0].get("oi", 0) or 0)


def _candle_time(candle: dict) -> int | None:
    """Unix seconds for a candle, from either the `time` or `timestamp` key."""
    t = candle.get("time")
    if t is None:
        t = candle.get("timestamp")
    if t is None:
        return None
    try:
        t = float(t)
    except (TypeError, ValueError):
        return None
    return int(t // 1000) if t > 1e12 else int(t)


def _latest_session_rows(candles: list[dict]) -> list[dict]:
    """Rows belonging to the most recent IST calendar date in the series."""
    ist = pytz.timezone("Asia/Kolkata")
    dated = []
    for c in candles:
        t = _candle_time(c)
        if t is None:
            continue
        dated.append((datetime.fromtimestamp(t, ist).date(), t, c))
    if not dated:
        return []
    last_date = max(d for d, _, _ in dated)
    rows = sorted((t, c) for d, t, c in dated if d == last_date)
    return [c for _, c in rows]


# Broker rate-limit shape for the per-leg history calls below: small batches
# with a pause between them, and exponential backoff on a 429.
BATCH_SIZE = 5
BATCH_DELAY = 0.5  # seconds between batches
MAX_RETRIES = 2
RETRY_BASE_DELAY = 1.0  # seconds, doubles each retry


def _history_rows(
    symbol: str, exchange: str, interval: str, start: str, end: str, api_key: str
) -> list[dict] | None:
    """One history call with 429 backoff. Returns the rows, or None."""
    for attempt in range(MAX_RETRIES + 1):
        try:
            success, resp, status_code = get_history(
                symbol=symbol,
                exchange=exchange,
                interval=interval,
                start_date=start,
                end_date=end,
                api_key=api_key,
            )
            if success and resp.get("data"):
                return resp["data"]
            if status_code != 429 or attempt >= MAX_RETRIES:
                return None
        except Exception as e:
            if attempt >= MAX_RETRIES or "429" not in str(e):
                logger.warning(f"Could not read history for {symbol}: {e}")
                return None
        delay = RETRY_BASE_DELAY * (2**attempt)
        logger.warning(f"Rate limited fetching {symbol}, retry {attempt + 1} after {delay}s")
        time.sleep(delay)
    return None


def _in_batches(symbols: list[str], fetch_one) -> dict[str, float]:
    """
    Run fetch_one over symbols in rate-limit-friendly batches.

    A symbol fetch_one answers None for is left out of the result rather than
    recorded as zero. The difference matters: a caller subtracting a zero
    anchor from a live number reports the leg's whole open interest as though
    every contract of it had been written today, so one broker hiccup paints a
    strike as a huge fresh build. Absent means unknown, and unknown draws
    nothing.
    """
    results = {}
    for i in range(0, len(symbols), BATCH_SIZE):
        for symbol in symbols[i : i + BATCH_SIZE]:
            value = fetch_one(symbol)
            if value is not None:
                results[symbol] = value
        if i + BATCH_SIZE < len(symbols):
            time.sleep(BATCH_DELAY)
    return results


def _anchor_intervals(interval: str) -> list[str]:
    """
    Bar sizes to try for an OI anchor, tightest first.

    The anchor's granularity is its error: a bar's ``oi`` is its closing
    value, so a five-minute anchor silently swallows the first five minutes
    of whatever it is measuring. One minute is the tightest the brokers
    serve; the chart's own interval is the fallback for one that does not.
    """
    return ["1m"] if interval == "1m" else ["1m", interval]


def _fetch_session_open_oi(
    option_symbols: list[dict], options_exchange: str, api_key: str, interval: str = "5m"
) -> dict[str, float]:
    """
    Fetch the open interest each option carried into the current session.

    The opening bar cannot change once the session has started, so each
    symbol is fetched once per session and then served from a cache.

    Args:
        option_symbols: List of dicts with 'symbol' key
        options_exchange: Exchange for options (NFO, BFO)
        api_key: OpenAlgo API key
        interval: Fallback bar size, for a broker that does not serve 1m.

    Returns:
        Dict mapping symbol -> open interest at the session's open
    """
    ist = pytz.timezone("Asia/Kolkata")
    today = datetime.now(ist).strftime("%Y-%m-%d")
    # A week back is the fallback range: it always contains a trading day, so
    # a chart opened on a holiday or over a long weekend still anchors on the
    # last session that actually traded.
    fallback_start = (datetime.now(ist) - timedelta(days=7)).strftime("%Y-%m-%d")

    results = {}

    # Only fetch for symbols with non-zero current OI, and only those whose
    # opening OI is not already known for this session.
    symbols_to_fetch = []
    with _prev_oi_cache_lock:
        for s in option_symbols:
            symbol = s["symbol"]
            if s.get("oi", 0) <= 0:
                continue
            cached = _prev_oi_cache.get((symbol, options_exchange, today))
            if cached is None:
                symbols_to_fetch.append(symbol)
            else:
                results[symbol] = cached

    if not symbols_to_fetch:
        return results

    def fetch_one(symbol: str) -> float | None:
        # Today is asked for first, because that is the small answer and the
        # common case. Only an empty reply widens the range, so a holiday
        # costs the wide call and a trading day does not.
        for bar in _anchor_intervals(interval):
            for start, end in ((today, today), (fallback_start, today)):
                rows = _history_rows(symbol, options_exchange, bar, start, end, api_key)
                if rows:
                    open_oi = _session_open_oi(rows)
                    if open_oi > 0:
                        return open_oi
        logger.warning(f"No opening OI for {symbol}; its change is reported as unknown")
        return None

    fetched = _in_batches(symbols_to_fetch, fetch_one)
    with _prev_oi_cache_lock:
        for sym, open_oi in fetched.items():
            _prev_oi_cache[(sym, options_exchange, today)] = open_oi
    results.update(fetched)
    return results


def _oi_entering(candles: list[dict], target_time: int) -> float:
    """
    Open interest carried *into* the bar that starts at ``target_time``.

    A bar's ``oi`` is its closing value, so the bar starting at target_time
    already contains the build the window is meant to measure; anchoring on it
    silently drops the window's first bar. Measured live on 16-Sep-2026: a
    09:15-09:25 window on NIFTY22SEP2623200PE reported 450,125 where the true
    build was 1,892,020, because the anchor was already five minutes in.

    The last bar strictly before target_time carries the right value, but only
    within the same session - reaching back across a session boundary picks up
    the settlement gap that :func:`_session_open_oi` exists to avoid. A window
    starting on the session's own first bar therefore falls back to that bar's
    close, which is the closest the intraday series can get.
    """
    ist = pytz.timezone("Asia/Kolkata")
    target_date = datetime.fromtimestamp(target_time, ist).date()
    best = None
    for c in candles:
        t = _candle_time(c)
        if t is None or t >= target_time:
            continue
        if datetime.fromtimestamp(t, ist).date() != target_date:
            continue
        if best is None or t > best[0]:
            best = (t, c.get("oi", 0) or 0)
    if best is not None:
        return float(best[1])
    return _oi_at_or_before(candles, target_time)


def _oi_at_or_before(candles: list[dict], target_time: int) -> float:
    """Last candle's OI at or before target_time (unix seconds), else 0.0."""
    best = None
    for c in candles:
        t = _candle_time(c)
        if t is None:
            continue
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
    arbitrary [window_start, window_end] range (unix seconds).

    Read at the tightest bar size the broker serves rather than the chart's,
    because the anchor's granularity is the measurement's error - see
    :func:`_anchor_intervals`.

    Returns:
        Dict mapping symbol -> (oi_at_window_end - oi_entering_window_start)
    """
    ist = pytz.timezone("Asia/Kolkata")
    start = datetime.fromtimestamp(window_start, ist).strftime("%Y-%m-%d")
    end = datetime.fromtimestamp(window_end, ist).strftime("%Y-%m-%d")

    symbols_to_fetch = [s["symbol"] for s in option_symbols if s.get("oi", 0) > 0]
    if not symbols_to_fetch:
        return {}

    def fetch_one(symbol: str) -> float:
        for bar in _anchor_intervals(interval):
            rows = _history_rows(symbol, options_exchange, bar, start, end, api_key)
            if rows:
                return _oi_at_or_before(rows, window_end) - _oi_entering(rows, window_start)
        return 0.0

    return _in_batches(symbols_to_fetch, fetch_one)


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
                prev_oi_map = _fetch_session_open_oi(
                    option_symbols_for_history, options_exchange, api_key, interval
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
