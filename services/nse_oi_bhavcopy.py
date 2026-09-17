"""
Previous-session open interest for every NSE F&O contract, from one file.

"Change in OI" is today's open interest minus the previous session's close.
Today's arrives free with the option chain; the anchor used to cost one broker
history call per leg, so opening a chart on an underlying nobody had looked at
yet spent 30-90 seconds on ~80 calls before it could draw its change columns.

NSE publishes that anchor for the whole market after every close: the F&O
bhavcopy, one zipped CSV per trading day, ~1.1 MB, a row per contract carrying
its closing open interest. One download answers every underlying, every expiry
and every strike at once, so switching symbols stops touching the broker.

Verified against the figure `oi_profile_service._previous_session_oi` is pinned
to: NIFTY22SEP2623200PE read 7,467,135 in the 16-Sep-2026 file with a day's
change of 2,914,210, which is exactly the 4,552,925 close of 15-Sep that NSE
reported. Same units as the broker's feed - no lot-size conversion.

NSE only. BSE publishes its own file in a different format, and crypto has
none; both keep the per-leg fallback in `oi_profile_service`.
"""

from __future__ import annotations

import csv
import io
import re
import threading
import zipfile
from datetime import date, datetime, timedelta
from typing import NamedTuple

import pytz
from cachetools import TTLCache

from database.market_calendar_db import is_market_holiday
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

_URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{day}_F_0000.csv.zip"
# nsearchives serves the file to anything with a browser User-Agent; unlike
# www.nseindia.com it needs no warmed cookie (see services/nse_events_service).
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Referer": "https://www.nseindia.com/",
}
_TIMEOUT = 30.0

# How far back to look for the newest published file. Covers a long weekend
# plus consecutive holidays; past that, something is wrong and the per-leg
# fallback should take over rather than a walk down the calendar.
_MAX_LOOKBACK_DAYS = 10

# One parsed file is ~18,000 entries, a few MB. Keyed by the IST date it was
# resolved for, so the first request after midnight resolves again; two entries
# are enough to hold today's and last night's.
_CACHE_TTL = 12 * 60 * 60
_book_cache: TTLCache = TTLCache(maxsize=2, ttl=_CACHE_TTL)
_lock = threading.Lock()

# A failed resolve must not be retried on every miss - nor cached for the day,
# or an NSE hiccup at 09:15 would cost the whole session.
_RETRY_AFTER_SECONDS = 600
_failed_at: dict[date, float] = {}

_IST = pytz.timezone("Asia/Kolkata")

# The leading name of an OpenAlgo option symbol: everything before its DDMMMYY
# expiry. `NIFTY22SEP2623200PE` -> `NIFTY`, `TVSMOTOR29SEP263850CE` -> `TVSMOTOR`.
_UNDERLYING_RE = re.compile(r"^(.+?)\d{2}[A-Z]{3}\d{2}")


class Bhavcopy(NamedTuple):
    """One session's closing open interest, keyed by OpenAlgo option symbol."""

    trade_date: date
    oi: dict[str, float]
    # Underlyings the file carries. A contract missing from `oi` whose
    # underlying is here genuinely held no open interest that session; one
    # whose underlying is absent means the file cannot speak for it at all.
    underlyings: frozenset[str]


def _option_symbol(ticker: str, expiry: str, strike: str, option_type: str) -> str | None:
    """Build the OpenAlgo symbol for one bhavcopy row, or None if unreadable.

    `[Base][DDMMMYY][Strike][CE/PE]`, with the strike written the way the
    symbol master writes it: whole numbers bare, fractions kept (`292.5`).
    """
    try:
        expiry_part = datetime.strptime(expiry, "%Y-%m-%d").strftime("%d%b%y").upper()
        value = float(strike)
    except (TypeError, ValueError):
        return None
    strike_part = int(value) if value == int(value) else value
    return f"{ticker}{expiry_part}{strike_part}{option_type}"


def _parse(raw: bytes) -> tuple[dict[str, float], frozenset[str]]:
    """Read the zipped CSV into {symbol: closing OI} plus the names it covers."""
    oi: dict[str, float] = {}
    underlyings: set[str] = set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        name = next((n for n in archive.namelist() if n.lower().endswith(".csv")), None)
        if name is None:
            raise ValueError("bhavcopy archive holds no CSV")
        with archive.open(name) as handle:
            for row in csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8")):
                option_type = (row.get("OptnTp") or "").strip()
                if option_type not in ("CE", "PE"):
                    continue
                ticker = (row.get("TckrSymb") or "").strip()
                symbol = _option_symbol(
                    ticker, (row.get("XpryDt") or "").strip(), row.get("StrkPric"), option_type
                )
                if not symbol:
                    continue
                underlyings.add(ticker)
                try:
                    oi[symbol] = float(row.get("OpnIntrst") or 0)
                except (TypeError, ValueError):
                    continue
    return oi, frozenset(underlyings)


def _download(day: date) -> bytes | None:
    """The file for one date, or None if NSE published none for it."""
    url = _URL.format(day=day.strftime("%Y%m%d"))
    try:
        response = get_httpx_client().get(url, headers=_HEADERS, timeout=_TIMEOUT)
    except Exception:
        logger.warning(f"Could not reach NSE for the {day} bhavcopy", exc_info=True)
        return None
    if response.status_code == 404:
        return None  # not a trading day, or not published yet
    if response.status_code != 200:
        logger.warning(f"NSE refused the {day} bhavcopy")
        return None
    return response.content


def _newest_before(cutoff: date) -> Bhavcopy | None:
    """The newest published file strictly before `cutoff`."""
    for back in range(1, _MAX_LOOKBACK_DAYS + 1):
        day = cutoff - timedelta(days=back)
        raw = _download(day)
        if raw is None:
            continue
        try:
            oi, underlyings = _parse(raw)
        except Exception:
            logger.exception(f"Could not read the {day} bhavcopy")
            return None
        logger.info(f"Loaded NSE open interest for {day}: {len(oi)} option contracts")
        return Bhavcopy(day, oi, underlyings)
    return None


def _displayed_session(today: date) -> date:
    """The session the chart's *current* open interest belongs to.

    On a trading day that is today, whether or not the close has passed - the
    anchor stays the previous session all day, which is what the day's change
    is measured against. On a holiday or weekend it is the last session that
    traded, so a chart opened on a Saturday still shows Friday's build.
    """
    try:
        if not is_market_holiday(today, "NFO"):
            return today
    except Exception:
        # A calendar that will not answer is no reason to skip the anchor; a
        # weekday is the overwhelmingly common case and reads correctly.
        logger.warning("Could not read the market calendar; assuming today trades", exc_info=True)
        return today
    for back in range(1, _MAX_LOOKBACK_DAYS + 1):
        day = today - timedelta(days=back)
        try:
            if not is_market_holiday(day, "NFO"):
                return day
        except Exception:
            return today
    return today


def previous_session_oi(exchange: str) -> Bhavcopy | None:
    """
    Closing open interest for every NSE option, as of the session before the
    one on screen. Downloads once and serves the parsed file thereafter.

    Blocking - call it from the anchor worker, never from a request.

    Args:
        exchange: Options exchange. Anything but NFO returns None.

    Returns:
        The parsed file, or None when NSE cannot supply one.
    """
    if (exchange or "").upper() != "NFO":
        return None

    today = datetime.now(_IST).date()
    with _lock:
        cached = _book_cache.get(today)
        if cached is not None:
            return cached
        failed = _failed_at.get(today)
    if failed is not None and (datetime.now(_IST).timestamp() - failed) < _RETRY_AFTER_SECONDS:
        return None

    book = _newest_before(_displayed_session(today))

    with _lock:
        if book is None:
            _failed_at.clear()  # only today's attempt matters
            _failed_at[today] = datetime.now(_IST).timestamp()
            logger.warning("No NSE bhavcopy available; anchors fall back to per-leg history")
        else:
            _book_cache[today] = book
            _failed_at.pop(today, None)
    return book


def cached_previous_session_oi(exchange: str) -> Bhavcopy | None:
    """The parsed file if it is already in hand, without downloading one.

    Safe to call from a request: after the first underlying of the day has
    warmed it, every later symbol switch is answered from here with no network
    at all.
    """
    if (exchange or "").upper() != "NFO":
        return None
    with _lock:
        return _book_cache.get(datetime.now(_IST).date())


def underlying_of(symbol: str) -> str | None:
    """The underlying an OpenAlgo option symbol names, or None."""
    match = _UNDERLYING_RE.match(symbol or "")
    return match.group(1) if match else None
