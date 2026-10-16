#!/usr/bin/env python3
"""Dependency-light server for the yfinance demo.

Serves the package root statically and answers a JSON history endpoint, so
the browser demo and its data come from one origin and there is no CORS to
configure.

Usage:
    pip install -r requirements.txt
    python server.py                    # http://127.0.0.1:8000
    python server.py --port 8123        # another port (a bare 8123 works too)
    python server.py --fixture          # synthetic bars: no yfinance, no network
    python server.py --self-test        # run the built-in checks and exit

Then open:  http://127.0.0.1:8000/examples/yfinance/index.html

History endpoint:
    GET /api/history?symbol=AAPL&interval=1d&period=1y
    GET /api/history?symbol=AAPL&interval=5m&from=<utc_seconds>&to=<utc_seconds>
    GET /api/history?symbol=AAPL&interval=5m&period=5d&session=extended
`session` is `regular` (the default) or `extended`, which adds the pre and post
market bars. Extended hours are served only for intraday bars of a US listed
stock (a plain ticker such as AAPL or BRK-B), the one place the source has them.
A success is the Bar array the chart consumes directly:
    [{ "time": <utc_seconds>, "open", "high", "low", "close", "volume" }, ...]

Quote and news endpoints, for the watchlist and news panels (fixture mode only):
    GET /api/quotes?symbols=AAPL,RELIANCE.NS
        [{ "symbol", "exchange", "last", "previousClose", "bid", "ask", "volume", "time" }, ...]
        An instrument the source does not know is left out, never answered with zeros.
    GET /api/news?symbol=AAPL&limit=20&cursor=<from the previous page>
        { "items": [{ "id", "headline", "source", "time", "summary", "url"? }], "nextCursor": <string or null> }
Without --fixture both answer 501 not_available: this server has no live quote
or news source, and a quote is never made up from the last bar.

A failure is { "error": <message>, "code": <token> } with the matching status:
    400 bad_symbol, bad_interval, bad_period, bad_range, bad_session, bad_limit, bad_cursor
    400 unsupported_session (extended hours asked of an instrument or interval without them)
    404 no_data (the source has no bars for that ask), not_found (no such endpoint)
    429 rate_limited (the source is throttling; Retry-After says when to retry)
    501 not_available (quotes and news without --fixture)
    502 upstream_error (the source failed)
    503 not_installed (yfinance is missing and --fixture was not given)

Only the standard library and yfinance are used, and yfinance is imported on
the first real request, so static serving and --fixture work without it.
"""
from __future__ import annotations

import argparse
import functools
import gzip
import hashlib
import json
import math
import os
import re
import signal
import sys
import threading
import time
import traceback
import unittest
import zlib
from datetime import date, datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, NamedTuple
from urllib.parse import parse_qs, urlparse

# Package root (two levels up from examples/yfinance/), so /dist and /examples resolve.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# ── the contract ──────────────────────────────────────────────────────────
# A ticker as the source spells it: letters and digits, a venue suffix
# (RELIANCE.NS), a pair (BTC-USD), a future or a rate (GC=F, EURUSD=X), and an
# index (^NSEI). Nothing else, and never long enough to be a sentence: the
# symbol is echoed back in error messages and goes into a request URL.
SYMBOL_RE = re.compile(r"^\^?[A-Za-z0-9][A-Za-z0-9.\-=]{0,23}$")
SYMBOL_RULE = "a symbol is 1 to 24 letters, digits, '.', '-' or '=', with an optional leading '^'"

# The interval tokens the source accepts, with the longest a bar of each can
# last. The calendar ones are upper bounds on purpose: they only decide when
# a pinned range can no longer change, and a bound that is too generous just
# delays the immutable header, never serves a forming bar as closed.
INTERVALS = {
    "1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "90m": 5400,
    "1h": 3600, "1d": 86400, "5d": 5 * 86400, "1wk": 7 * 86400, "1mo": 31 * 86400, "3mo": 92 * 86400,
}
INTRADAY = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"}
SESSIONS = ("regular", "extended")
# A US listed stock as the source spells it: one to five letters, and an
# optional share class (BRK-B). The source has pre and post market bars for
# these and for nothing else it serves, so this is where extended hours exist.
# The reference host's feed declares the same rule (src/feed.js).
US_STOCK_RE = re.compile(r"^[A-Za-z]{1,5}(?:-[A-Za-z])?$")


def extended_session_available(symbol: str, interval: str) -> bool:
    """Whether the source serves pre and post market bars for this ask."""
    return interval in INTRADAY and bool(US_STOCK_RE.match(symbol))
# Period tokens and their length in days. `ytd` and `max` have no fixed
# length and are resolved against the end of the window when one is needed.
PERIOD_DAYS = {
    "1d": 1, "5d": 5, "1mo": 31, "3mo": 92, "6mo": 186, "1y": 366, "2y": 731,
    "5y": 1830, "10y": 3653, "ytd": None, "max": None,
}
# How far back the source will serve each intraday interval. The fixture
# clamps to the same limits so an offline run has the same shape as a live
# one, where an over-long ask comes back empty.
INTRADAY_MAX_DAYS = {"1m": 7, "2m": 60, "5m": 60, "15m": 60, "30m": 60, "60m": 730, "90m": 60, "1h": 730}
FIXTURE_MAX_DAYS = 20 * 366
# A timestamp past this is not a time anyone can chart, it is a typo or a
# millisecond value; refusing it early keeps the source from being asked for
# a window in the year 50000.
MAX_EPOCH = 4102444800  # 2100-01-01

# A range that ends in the past and whose last possible bar has closed cannot
# change, so the browser may keep it for as long as it likes. Everything
# else contains, or could grow, a forming bar, and a cache that serves a stale
# forming bar is worse than no cache at all: it gets a few seconds, enough to
# fold the double fetch a linked second chart makes into one.
LIVE_CACHE = "private, max-age=5"
CLOSED_CACHE = "public, max-age=31536000, immutable"
GZIP_MIN_BYTES = 512


class ApiError(Exception):
    """A failure the client is told about as JSON, with the status it deserves."""

    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


class HistoryRequest:
    """A validated /api/history ask. `start` and `end` are UTC seconds or None."""

    def __init__(self, symbol: str, interval: str, period: str, start: int | None, end: int | None,
                 session: str = "regular"):
        self.symbol = symbol
        self.interval = interval
        self.period = period
        self.start = start
        self.end = end
        self.session = session

    def describe(self) -> str:
        if self.start is not None or self.end is not None:
            return f"{self.interval} bars of {self.symbol} between {self.start or 'the start'} and {self.end or 'now'}"
        return f"{self.interval} bars of {self.symbol} over {self.period}"


def _first(q: dict, key: str) -> str | None:
    values = q.get(key)
    return values[0] if values else None


def _epoch_param(q: dict, key: str) -> int | None:
    raw = _first(q, key)
    if raw is None or raw == "":
        return None
    if not re.fullmatch(r"[0-9]{1,10}", raw):
        raise ApiError(400, "bad_range", f"{key} must be UTC seconds, got {raw!r}")
    value = int(raw)
    if value <= 0 or value >= MAX_EPOCH:
        raise ApiError(400, "bad_range", f"{key} must be UTC seconds before the year 2100, got {raw!r}")
    return value


def parse_history_query(q: dict) -> HistoryRequest:
    """Turn a parsed query string into a request, or raise a 400 that says why."""
    symbol = (_first(q, "symbol") or "").strip()
    if not symbol:
        raise ApiError(400, "bad_symbol", "symbol is required: " + SYMBOL_RULE)
    if not SYMBOL_RE.match(symbol):
        raise ApiError(400, "bad_symbol", f"symbol {symbol[:40]!r} is not valid: " + SYMBOL_RULE)
    interval = _first(q, "interval") or "1d"
    if interval not in INTERVALS:
        raise ApiError(400, "bad_interval", f"interval {interval[:20]!r} is not one of " + ", ".join(INTERVALS))
    period = _first(q, "period") or "1y"
    if period not in PERIOD_DAYS:
        raise ApiError(400, "bad_period", f"period {period[:20]!r} is not one of " + ", ".join(PERIOD_DAYS))
    start = _epoch_param(q, "from")
    end = _epoch_param(q, "to")
    if start is not None and end is not None and start >= end:
        raise ApiError(400, "bad_range", f"from ({start}) must be before to ({end})")
    session = _first(q, "session") or "regular"
    if session not in SESSIONS:
        raise ApiError(400, "bad_session", f"session {session[:20]!r} is not one of " + ", ".join(SESSIONS))
    # Refused rather than answered with regular hours: the chart would label
    # the regular series extended, and nothing on screen could tell.
    if session == "extended" and not extended_session_available(symbol, interval):
        raise ApiError(400, "unsupported_session",
                       f"extended hours are served only for intraday bars of US listed stocks, not {interval} bars of {symbol}")
    return HistoryRequest(symbol, interval, period, start, end, session)


def period_days(period: str, at: int) -> int | None:
    """Days a period covers ending at `at`; None when the source decides (max)."""
    if period == "ytd":
        jan1 = datetime(datetime.fromtimestamp(at, tz=timezone.utc).year, 1, 1, tzinfo=timezone.utc)
        return max(1, math.ceil((at - jan1.timestamp()) / 86400))
    return PERIOD_DAYS[period]


def cache_control_for(req: HistoryRequest, now: int) -> str:
    """The rule from the top of the file: immutable only for a pinned, closed range."""
    if req.end is not None and now >= req.end + INTERVALS[req.interval]:
        return CLOSED_CACHE
    return LIVE_CACHE


# ── the live source ───────────────────────────────────────────────────────

def upstream_error(exc: Exception) -> ApiError:
    """Map whatever the source threw onto a status, without the traceback."""
    name = type(exc).__name__
    text = str(exc).replace("\n", " ").strip()
    if "RateLimit" in name or "Too Many Requests" in text or " 429" in text:
        return ApiError(429, "rate_limited", "the data source is rate limiting this address; try again in a minute",
                        {"Retry-After": "60"})
    return ApiError(502, "upstream_error", f"{name}: {text[:300]}" if text else name)


def yfinance_bars(req: HistoryRequest, now: int) -> list:
    """Fetch OHLCV from yfinance and map it to the chart's Bar shape (UTC seconds)."""
    try:
        import yfinance as yf  # imported lazily so static serving works without it
    except ModuleNotFoundError:
        raise ApiError(503, "not_installed",
                       "yfinance is not installed: pip install -r requirements.txt, or start with --fixture") from None
    try:
        ticker = yf.Ticker(req.symbol)
        # The source's own pre and post market bars; nothing is derived here.
        prepost = req.session == "extended"
        # Prices as they traded. The source's default rewrites every past bar
        # for later dividends, so an old candle stops matching the exchange's
        # record (RELIANCE.NS closed 1165.03 on 2021-09-27; the adjusted series
        # says 1143.37). Unadjusted bars keep the source's split adjustment,
        # which is what an exchange-price chart shows.
        adjust = False
        if req.start is None and req.end is None:
            df = ticker.history(period=req.period, interval=req.interval, prepost=prepost, auto_adjust=adjust)
        else:
            # A pinned window. The source ignores `end` when a period is given,
            # so the period is turned into a start here; `max` leaves the start
            # to the source's own default.
            end = req.end if req.end is not None else now
            start = req.start
            if start is None:
                days = period_days(req.period, end)
                start = None if days is None else end - days * 86400
            df = ticker.history(
                start=None if start is None else datetime.fromtimestamp(start, tz=timezone.utc),
                end=datetime.fromtimestamp(end, tz=timezone.utc),
                interval=req.interval,
                prepost=prepost,
                auto_adjust=adjust,
            )
    except Exception as exc:  # noqa: BLE001 (the source's failures all become one status)
        raise upstream_error(exc) from None
    return frame_to_bars(df)


def frame_to_bars(df) -> list:
    bars = []
    for idx, row in df.iterrows():
        # idx is a (tz-aware) Timestamp; .timestamp() yields UTC epoch seconds.
        # A row with no price is not a bar. yfinance emits them for suspensions
        # and some holidays (RELIANCE.NS over a year has four), and json.dumps
        # writes a bare NaN, which is not valid JSON: the browser then fails to
        # parse the whole response and the symbol looks broken rather than
        # gappy. Volume was already guarded here; OHLC was not.
        if any(_isnan(row[c]) for c in ("Open", "High", "Low", "Close")):
            continue
        bars.append(
            {
                "time": int(idx.timestamp()),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row["Volume"]) if not _isnan(row["Volume"]) else 0,
            }
        )
    return bars


def _isnan(v) -> bool:
    try:
        return v != v
    except Exception:
        return False


# ── the fixture source ────────────────────────────────────────────────────
# Deterministic synthetic bars for any symbol, so the demo runs with no
# network and no yfinance, and a test can assert on what it sees. Every value
# is a pure function of (symbol, bar time): the same URL answers with the same
# bytes from any machine on any day, as long as the window is pinned with
# `to`. Three symbols are reserved so the error paths can be exercised too.
FIXTURE_SENTINELS = {
    "FAIL": ApiError(502, "upstream_error", "fixture: FAIL always fails upstream"),
    "EMPTY": ApiError(404, "no_data", "fixture: EMPTY has no bars"),
    "BUSY": ApiError(429, "rate_limited", "fixture: BUSY is always rate limited", {"Retry-After": "30"}),
}
# One symbol is an instrument with a price-dependent tick, so the reference
# host has one to show: it trades around 100, on a 0.01 grid below 100 and a
# 0.05 grid from 100. The host hands the same rules to the library as its own
# metadata (src/ticks.js). Synthetic, not any venue's schedule.
BANDED = "BANDED"
BANDED_BOUNDARY = 100.0


def banded_price(v: float) -> float:
    """v on BANDED's grid, halves rounding up. Monotonic, so high and low stay outside open and close."""
    tick = 0.05 if v >= BANDED_BOUNDARY else 0.01
    return round(math.floor(v / tick + 0.5) * tick, 2)


# ── venues ────────────────────────────────────────────────────────────────
# Each symbol trades in its own venue's hours, by the rule the reference host
# reads its session calendar and its status line from (src/status.js, exchangeOf
# and SESSIONS; src/ticks.js for BANDED). A chart of fixture bars then agrees
# with its own calendar, as a chart of live bars does: a US stock's regular bars
# sit in New York's regular session, where the session shading leaves them
# alone, and its staleness is judged against the hours it actually trades.
DAY = 86400
EPOCH_ORDINAL = date(1970, 1, 1).toordinal()


@functools.lru_cache(maxsize=256)
def _new_york_daylight(year: int) -> tuple:
    """The local days (since 1970) daylight time starts and ends in New York in `year`.

    Spelled out rather than read from the zone database: some systems give
    Python none without the tzdata package, and the fixture promises the same
    bytes on every machine. The self-test holds the rule to the zone database
    where one is installed.
    """
    def sunday(month: int, n: int) -> int:
        if n > 0:
            first = date(year, month, 1)
            return first.toordinal() + (6 - first.weekday()) % 7 + 7 * (n - 1)
        last = date(year, month + 1, 1).toordinal() - 1
        return last - (date.fromordinal(last).weekday() + 1) % 7
    start, end = (sunday(3, 2), sunday(11, 1)) if year >= 2007 else (sunday(4, 1), sunday(10, -1))
    return start - EPOCH_ORDINAL, end - EPOCH_ORDINAL


def _new_york_offset(day: int) -> int:
    # The clocks change at 02:00 on a Sunday, so for every trading hour the
    # local date alone says which offset is in force.
    start, end = _new_york_daylight(date.fromordinal(day + EPOCH_ORDINAL).year)
    return -4 * 3600 if start <= day < end else -5 * 3600


class Venue(NamedTuple):
    """A venue's trading hours, in seconds after local midnight."""
    offset: Callable[[int], int]  # the UTC offset on a local day
    open: int
    close: int
    # The walk runs from `pre` to `post` on each trading day, and extended hours
    # are served there where the source has them.
    pre: int
    post: int
    week: int   # trading days a week: 5, Monday to Friday, or 7
    depth: int  # levels of the walk's tree: enough trading minutes to reach the year 2100


# Mumbai walks two hours either side of its session although the source serves
# no extended hours there: the NSE prices stay the ones every earlier run drew.
MUMBAI = Venue(lambda day: 19800, 9 * 3600 + 15 * 60, 15 * 3600 + 30 * 60, 7 * 3600 + 15 * 60, 17 * 3600 + 30 * 60, 5, 25)
NEW_YORK = Venue(_new_york_offset, 9 * 3600 + 30 * 60, 16 * 3600, 4 * 3600, 20 * 3600, 5, 25)
AROUND_THE_CLOCK = Venue(lambda day: 0, 0, DAY, 0, DAY, 7, 27)
INDIA_INDICES = {"^NSEI", "^NSEBANK", "^BSESN"}
US_INDICES = {"^GSPC", "^DJI", "^IXIC", "^RUT", "^VIX"}


def venue_of(symbol: str) -> Venue:
    """The venue a symbol trades on: the host's rule, and BANDED's own metadata."""
    s = symbol.upper()
    if s == BANDED or s.endswith((".NS", ".BO")) or s in INDIA_INDICES:
        return MUMBAI
    if s.endswith("-USD"):
        return AROUND_THE_CLOCK
    if s in US_INDICES or not s.startswith("^"):
        return NEW_YORK
    # An index the host has no hours for keeps the session the fixture always used.
    return MUMBAI


def _weekday(day: int) -> int:
    # 1970-01-01 was a Thursday; Monday is 0 to match datetime.weekday().
    return (day + 3) % 7


def _trading_day(venue: Venue, day: int) -> bool:
    return venue.week == 7 or _weekday(day) < 5


def _at(venue: Venue, day: int, seconds: int) -> int:
    """UTC seconds of a wall-clock time on a local day at the venue."""
    return day * DAY + seconds - venue.offset(day)


def _local(venue: Venue, t: int) -> tuple:
    """The local day of `t` at the venue, and the seconds into it."""
    day = (t + venue.offset(t // DAY)) // DAY
    return day, t + venue.offset(day) - day * DAY


def fixture_grid(interval: str, start: int, end: int, extended: bool = False, venue: Venue = MUMBAI) -> list:
    """Ascending bar start times in [start, end) on the interval's calendar, in the venue's hours."""
    out = []
    # Local days, with one either side: an offset moves a day by less than that.
    days = range(start // DAY - 1, end // DAY + 2)
    if interval in INTRADAY:
        step = INTERVALS[interval]
        opens, closes = (venue.pre, venue.post) if extended else (venue.open, venue.close)
        for day in days:
            if _trading_day(venue, day):
                t, stop = _at(venue, day, opens), _at(venue, day, closes)
                while t < stop and t < end:
                    if t >= start:
                        out.append(t)
                    t += step
    elif interval in ("1d", "5d", "1wk"):
        # Daily bars at the session open, weekly ones on Mondays.
        for day in days:
            t = _at(venue, day, venue.open)
            if start <= t < end and _trading_day(venue, day) and (interval == "1d" or _weekday(day) == 0):
                out.append(t)
    else:
        months = 1 if interval == "1mo" else 3
        d = date.fromordinal(_local(venue, start)[0] + EPOCH_ORDINAL)
        year, month = d.year, ((d.month - 1) // months) * months + 1
        while True:
            t = _at(venue, date(year, month, 1).toordinal() - EPOCH_ORDINAL, venue.open)
            if t >= end:
                break
            if t >= start:
                out.append(t)
            month += months
            if month > 12:
                month -= 12
                year += 1
    return out


def _noise(symbol: str, t: int, salt: str) -> float:
    """A stable number in [0, 1) for one bar of one symbol. crc32, not hash(): hash() is salted per process."""
    return (zlib.crc32(f"{symbol}|{t}|{salt}".encode()) & 0xFFFFFFFF) / 2 ** 32


# The fixture's price is a seeded random walk, so a chart of it reads like a
# traded stock. It walks in trading time: each trading day adds the minutes
# from its venue's pre-open to its post-close, and a night or a closed day adds
# none, so the open follows on from the last close the way a quiet night's does.
# Every value is still a pure function of (symbol, bar time): the walk is laid
# out as a Brownian bridge over a binary tree of minute spans, each split drawn
# from a digest of the symbol and the span, so the level at any minute costs one
# descent of the tree rather than a sum of every step since 1970.
# A symbol trades at its base price at the start of 2025 and walks from there.
WALK_ANCHOR = 1_735_689_600
# BANDED's walk comes back to 100 about every 53 trading days, so its tick
# boundary stays on screen at any date instead of drifting off it.
BANDED_SPAN = 1 << 15


def _trading_minute(t: int, venue: Venue = MUMBAI) -> int:
    """Minutes of the venue's walked hours from 1970 to t; a night or a closed day holds the last one."""
    day, into = _local(venue, t)
    length = venue.post - venue.pre
    if venue.week == 7:
        before = day
    else:
        weeks, rest = divmod(day, 7)
        before = weeks * 5 + sum(1 for i in range(rest) if _weekday(i) < 5)
        if _weekday(day) >= 5:
            return before * length // 60
    return (before * length + min(max(into - venue.pre, 0), length)) // 60


@functools.lru_cache(maxsize=1 << 16)
def _gauss(symbol: str, lo: int, size: int) -> float:
    """A standard normal draw for one span of one symbol's walk. A digest, not crc32: neighbouring spans must not correlate."""
    digest = hashlib.blake2b(f"{symbol}|walk|{lo}|{size}".encode(), digest_size=8).digest()
    u = (int.from_bytes(digest[:4], "big") + 0.5) / 2 ** 32
    v = int.from_bytes(digest[4:], "big") / 2 ** 32
    return math.sqrt(-2.0 * math.log(u)) * math.cos(2 * math.pi * v)


def _walk(symbol: str, n: int, pin: int = 0, depth: int = 25) -> float:
    """The sum of the first n unit steps of the symbol's walk; with `pin`, less the line through each pin-long span's ends."""
    lo, size = 0, 1 << depth
    total = _gauss(symbol, -1, size) * math.sqrt(size)
    acc = 0.0
    block = None
    while True:
        if size == pin:
            block = (lo, acc, total)
        if n <= lo:
            s = acc
            break
        if n >= lo + size:
            s = acc + total
            break
        half = size >> 1
        # Brownian bridge: given a span's total, its first half is half of it
        # plus a draw whose spread is half the span's root length.
        left = total / 2 + _gauss(symbol, lo, size) * math.sqrt(size) / 2
        if n >= lo + half:
            acc += left
            lo += half
            total -= left
        else:
            total = left
        size = half
    if not pin:
        return s
    if block is None:
        return 0.0
    start, before, span_total = block
    return s - before - (n - start) / pin * span_total


@functools.lru_cache(maxsize=256)
def _walk_anchor(symbol: str) -> float:
    venue = venue_of(symbol)
    return _walk(symbol, _trading_minute(WALK_ANCHOR, venue), depth=venue.depth)


def fixture_level(symbol: str, t: int) -> float:
    """The synthetic close at time t: the symbol's random walk from its base, with a drift and a volatility it picks."""
    seed = zlib.crc32(symbol.encode()) & 0xFFFFFFFF
    venue = venue_of(symbol)
    n = _trading_minute(t, venue)
    if symbol == BANDED:
        return 100 * math.exp(0.0004 * _walk(symbol, n, BANDED_SPAN))
    base = 20 + seed % 2000
    # A day's move is 1.2 to 2.3 percent, and a year drifts -9 to +9 percent.
    minutes = (venue.post - venue.pre) // 60
    vol = (0.012 + ((seed >> 8) % 12) / 1000) / math.sqrt(minutes)
    drift = (seed % 7 - 3) * 0.03 / ((261 if venue.week == 5 else 365) * minutes)
    ref = _trading_minute(WALK_ANCHOR, venue)
    return base * math.exp(vol * (_walk(symbol, n, depth=venue.depth) - _walk_anchor(symbol)) + drift * (n - ref))


def fixture_bars(req: HistoryRequest, now: int) -> list:
    symbol = req.symbol.upper()
    if symbol in FIXTURE_SENTINELS:
        raise FIXTURE_SENTINELS[symbol]
    end = min(req.end, now) if req.end is not None else now
    start = req.start
    if start is None:
        days = period_days(req.period, end)
        start = end - (FIXTURE_MAX_DAYS if days is None else days) * DAY
    if req.interval in INTRADAY:
        start = max(start, end - INTRADAY_MAX_DAYS[req.interval] * DAY)
    # One bar before the window, so the first bar's open is the close of the
    # bar before it rather than a number the chart never saw.
    lead = INTERVALS[req.interval] * (10 if req.interval in INTRADAY else 2)
    grid = fixture_grid(req.interval, start - lead, end + 1, getattr(req, "session", "regular") == "extended", venue_of(symbol))
    bars = []
    prev_close = None
    for t in grid:
        close = fixture_level(symbol, t)
        if t < start or t > end:
            prev_close = close
            continue
        open_ = prev_close if prev_close is not None else close
        span = abs(close - open_)
        high = max(open_, close) + _noise(symbol, t, "h") * 0.004 * close
        low = min(open_, close) - _noise(symbol, t, "l") * 0.004 * close
        volume = int(1000 + _noise(symbol, t, "v") * 100000 * (1 + 30 * span / close))
        price = banded_price if symbol == BANDED else (lambda v: round(v, 2))
        bars.append({
            "time": t,
            "open": price(open_),
            "high": price(high),
            "low": price(low),
            "close": price(close),
            "volume": volume,
        })
        prev_close = close
    return bars


# ── fixture quotes and news ───────────────────────────────────────────────
# Quotes move on a two-second step and news arrives on a per-symbol schedule,
# both pure functions of (symbol, time) like the bars, so a pinned clock gives
# the same bytes anywhere. A quote is the fixture level at its own time, not
# the close of the last bar: the chart may show a daily candle that closed
# hours before the quote was taken.
QUOTE_STEP = 2
MAX_QUOTE_SYMBOLS = 50
NEWS_PERIOD = 5400
NEWS_DEPTH = 60
NEWS_MAX_LIMIT = 50
NEWS_CURSOR_RE = re.compile(r"^[0-9]{1,9}:[0-9]{1,9}$")
NEWS_SOURCES = ("Fixture Wire", "Sample Markets Desk", "Demo Newsroom")
# One headline carries markup on purpose: a reader must show it as text.
NEWS_HEADLINES = (
    "{symbol} moves with its sector peers",
    "{symbol} sets a date for quarterly results",
    "Analysts revise estimates for {symbol}",
    "{symbol} to present at an investor conference",
    "Options activity rises in {symbol}",
    "{symbol} files an exchange disclosure",
    "Filing mentions <b>guidance</b> & outlook for {symbol}",
)


def parse_quotes_query(q: dict) -> list:
    raw = (_first(q, "symbols") or "").strip()
    symbols = [part.strip() for part in raw.split(",") if part.strip()]
    if not symbols:
        raise ApiError(400, "bad_symbol", "symbols is required: a comma-separated list, " + SYMBOL_RULE)
    if len(symbols) > MAX_QUOTE_SYMBOLS:
        raise ApiError(400, "bad_symbol", f"at most {MAX_QUOTE_SYMBOLS} symbols per request")
    for symbol in symbols:
        if not SYMBOL_RE.match(symbol):
            raise ApiError(400, "bad_symbol", f"symbol {symbol[:40]!r} is not valid: " + SYMBOL_RULE)
    return list(dict.fromkeys(symbols))


def parse_news_query(q: dict) -> dict:
    symbol = (_first(q, "symbol") or "").strip()
    if not symbol or not SYMBOL_RE.match(symbol):
        raise ApiError(400, "bad_symbol", f"symbol {symbol[:40]!r} is not valid: " + SYMBOL_RULE)
    raw_limit = _first(q, "limit") or "20"
    if not re.fullmatch(r"[0-9]{1,3}", raw_limit) or not 1 <= int(raw_limit) <= NEWS_MAX_LIMIT:
        raise ApiError(400, "bad_limit", f"limit must be 1 to {NEWS_MAX_LIMIT}, got {raw_limit[:10]!r}")
    cursor = _first(q, "cursor")
    if cursor is not None and cursor != "" and not NEWS_CURSOR_RE.match(cursor):
        raise ApiError(400, "bad_cursor", "cursor must be the nextCursor of a previous page")
    return {"symbol": symbol, "limit": int(raw_limit), "cursor": cursor or None}


def fixture_quotes(symbols: list, now: int) -> list:
    """One quote per known symbol; the sentinels are unknown and left out."""
    t = now - now % QUOTE_STEP
    out = []
    for symbol in symbols:
        key = symbol.upper()
        if key in FIXTURE_SENTINELS:
            continue
        last = fixture_level(key, t) * (1 + (_noise(key, t, "q") - 0.5) * 0.002)
        # The previous trading day's close at the symbol's venue, whatever day it is there now.
        venue = venue_of(key)
        day = _local(venue, t)[0] - 1
        while not _trading_day(venue, day):
            day -= 1
        previous = fixture_level(key, _at(venue, day, venue.close) - 60)
        spread = max(0.01, round(last * 0.0004, 2))
        out.append({
            "symbol": symbol, "exchange": "", "last": round(last, 2), "previousClose": round(previous, 2),
            "bid": round(last - spread, 2), "ask": round(last + spread, 2),
            "volume": int(50000 + _noise(key, t // 3600, "qv") * 2000000), "time": t,
        })
    return out


def _news_draw(symbol: str, slot: int, salt: str) -> float:
    """A stable number in [0, 1) per story slot. The bars' crc32 noise is correlated across
    consecutive integers, which would give runs of one headline, so stories use a real digest."""
    digest = hashlib.blake2b(f"{symbol}|{slot}|{salt}".encode(), digest_size=4).digest()
    return int.from_bytes(digest, "big") / 2 ** 32


def fixture_news(req: dict, now: int) -> dict:
    """A page of news on a per-symbol schedule. The cursor is `slot:floor`, so later pages ignore the clock."""
    symbol = req["symbol"].upper()
    if symbol == "EMPTY":
        return {"items": [], "nextCursor": None}
    if symbol in FIXTURE_SENTINELS:
        raise FIXTURE_SENTINELS[symbol]
    seed = zlib.crc32(symbol.encode()) & 0xFFFFFFFF
    phase = seed % NEWS_PERIOD
    if req["cursor"] is None:
        start = (now - phase) // NEWS_PERIOD
        floor = start - NEWS_DEPTH
    else:
        start, floor = (int(part) for part in req["cursor"].split(":"))
        start -= 1
    items, slot = [], start
    while slot > floor and len(items) < req["limit"]:
        # Roughly three slots in five carry a story, so the gaps are irregular.
        if _news_draw(symbol, slot, "has") < 0.6:
            pick = int(_news_draw(symbol, slot, "h") * len(NEWS_HEADLINES))
            headline = NEWS_HEADLINES[pick].format(symbol=req["symbol"])
            item = {
                "id": f"{symbol}-{slot}",
                "headline": headline,
                "source": NEWS_SOURCES[int(_news_draw(symbol, slot, "s") * len(NEWS_SOURCES))],
                "time": slot * NEWS_PERIOD + phase + int(_news_draw(symbol, slot, "t") * 600),
                "summary": f"Fixture story {slot} about {req['symbol']}. Synthetic text for the reference host; it is not market news.",
            }
            # The markup headline also carries a script link, which a reader must refuse to open.
            if "<b>" in headline:
                item["url"] = "javascript:alert(document.domain)"
            elif _news_draw(symbol, slot, "u") >= 0.15:
                item["url"] = f"https://example.com/news/{req['symbol']}/{slot}"
            items.append(item)
        slot -= 1
    more = any(_news_draw(symbol, j, "has") < 0.6 for j in range(slot, floor, -1))
    return {"items": items, "nextCursor": f"{slot + 1}:{floor}" if more and items else None}


def unavailable(what: str):
    def source(*args):
        raise ApiError(501, "not_available", f"{what} are served only with --fixture: this server has no live source for them")
    return source


# ── the server ────────────────────────────────────────────────────────────

def accepts_gzip(header: str | None) -> bool:
    """True when Accept-Encoding lists gzip with a non-zero quality."""
    for part in (header or "").split(","):
        token, _, params = part.strip().partition(";")
        if token.strip().lower() != "gzip":
            continue
        quality = 1.0
        for param in params.split(";"):
            key, _, value = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(value)
                except ValueError:
                    quality = 0.0
        return quality > 0
    return False


def pick_port(flag: int | None, legacy: int | None) -> int:
    """--port wins, then the bare positional the 1.x README taught, then 8000."""
    if flag is not None:
        return flag
    if legacy is not None:
        return legacy
    return 8000


def format_log_line(client: str, method: str, path: str, status, size, ms: float) -> str:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{stamp} {client} {method} {path} {status if status is not None else '-'} {size if size is not None else '-'} {ms:.0f}ms"


class Handler(SimpleHTTPRequestHandler):
    server_version = "openalgo-charts-demo/2.0"
    # Serve ES modules with a JS MIME type: browsers reject `text/plain` modules
    # under strict MIME checking, which would block `import ... from '.mjs'`.
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".mjs": "application/javascript",
        ".js": "application/javascript",
    }

    def __init__(self, *args, **kwargs):
        self._status = None
        self._size = None
        self._cache_set = False
        super().__init__(*args, directory=ROOT, **kwargs)

    # -- bookkeeping for the log line ---------------------------------------
    def send_response(self, code, message=None):  # noqa: N802 (stdlib naming)
        self._status = code
        super().send_response(code, message)

    def send_header(self, keyword, value):  # noqa: N802 (stdlib naming)
        if keyword.lower() == "content-length":
            self._size = value
        super().send_header(keyword, value)

    def end_headers(self):  # noqa: N802 (stdlib naming)
        # A dev server for a library you are actively rebuilding must not cache
        # its files. The browser keeps ES modules in its own module map, so a
        # reload does not re-fetch /dist: you edit the source, rebuild, reload,
        # and still run the previous bundle with no sign anything is stale. The
        # history endpoint sets its own policy and is left alone here.
        if not self._cache_set:
            self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_request(self, code="-", size="-"):
        # Replaced by the one line per call written at the end of do_GET,
        # which also knows how long the call took.
        pass

    def log_message(self, fmt, *args):
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write(fmt % args + "\n")
        sys.stderr.flush()

    # -- routing --------------------------------------------------------------
    def do_GET(self):  # noqa: N802 (stdlib naming)
        t0 = time.monotonic()
        self._status = None
        self._size = None
        self._cache_set = False
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/"):
                self._api(parsed)
            else:
                super().do_GET()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self._status = "client-gone"
        finally:
            self.log_message("%s", format_log_line(
                self.client_address[0], self.command, self.path, self._status, self._size,
                (time.monotonic() - t0) * 1000,
            ))

    def _api(self, parsed):
        now = int(time.time())
        try:
            query = parse_qs(parsed.query, keep_blank_values=True)
            # Quotes and news are live answers: never cached, by the browser or anyone else.
            if parsed.path == "/api/quotes":
                self._json(200, self.server.quotes(parse_quotes_query(query), now))
                return
            if parsed.path == "/api/news":
                self._json(200, self.server.news(parse_news_query(query), now))
                return
            if parsed.path != "/api/history":
                raise ApiError(404, "not_found", f"no endpoint at {parsed.path[:80]}")
            req = parse_history_query(query)
            bars = self.server.source(req, now)
            if not bars:
                raise ApiError(404, "no_data", "no " + req.describe())
            self._json(200, bars, cache=cache_control_for(req, now))
        except ApiError as e:
            self._json(e.status, {"error": e.message, "code": e.code}, headers=e.headers)
        except Exception as e:  # noqa: BLE001 (a bug here must not take the connection down)
            # The traceback is for the terminal. The browser gets a sentence.
            self.log_message("unhandled %s in %s", type(e).__name__, self.path)
            if not getattr(self.server, "quiet", False):
                traceback.print_exc()
            self._json(500, {"error": "internal error, see the server log", "code": "internal_error"})

    def _json(self, code, payload, headers=None, cache="no-store"):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        encoding = None
        if len(body) >= GZIP_MIN_BYTES and accepts_gzip(self.headers.get("Accept-Encoding")):
            body = gzip.compress(body, compresslevel=6)
            encoding = "gzip"
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", cache)
        self._cache_set = True
        self.send_header("Vary", "Accept-Encoding")
        if encoding:
            self.send_header("Content-Encoding", encoding)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DemoServer(ThreadingHTTPServer):
    # A thread per request, so a slow upstream fetch never blocks the static
    # files the page is loading alongside it; daemon threads, so a fetch that
    # hangs cannot hold the process open after Ctrl+C.
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, source, quiet=False, quotes=None, news=None):
        self.source = source
        self.quiet = quiet
        self.quotes = quotes or unavailable("quotes")
        self.news = news or unavailable("news items")
        super().__init__(address, Handler)


def make_server(host: str, port: int, fixture: bool = False, quiet: bool = False, source=None) -> DemoServer:
    return DemoServer((host, port), source or (fixture_bars if fixture else yfinance_bars), quiet=quiet,
                      quotes=fixture_quotes if fixture else None, news=fixture_news if fixture else None)


def serve(server: DemoServer) -> None:
    """Run until Ctrl+C or SIGTERM, then close the socket and return."""
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if not server.quiet:
            print("\nstopped", flush=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="openalgo-charts yfinance demo server")
    p.add_argument("legacy_port", nargs="?", type=int, help=argparse.SUPPRESS)
    p.add_argument("--port", type=int, default=None, help="port to listen on (default 8000; 0 picks a free one)")
    p.add_argument("--host", default="127.0.0.1", help="address to bind (default 127.0.0.1)")
    p.add_argument("--fixture", action="store_true", help="serve deterministic synthetic bars; no yfinance, no network")
    p.add_argument("--quiet", action="store_true", help="no request log")
    p.add_argument("--self-test", action="store_true", help="run the built-in checks against the fixture and exit")
    args = p.parse_args(argv)
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(SelfTest)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    server = make_server(args.host, pick_port(args.port, args.legacy_port), fixture=args.fixture, quiet=args.quiet)
    bound = server.server_address[1]
    print(f"openalgo-charts yfinance demo -> http://{args.host}:{bound}/examples/yfinance/index.html")
    print(f"serving package root: {ROOT}")
    print("bars: " + ("synthetic fixture, no network" if args.fixture else "yfinance"), flush=True)
    print("quotes and news: " + ("synthetic fixture" if args.fixture else "not available (start with --fixture)"), flush=True)
    serve(server)
    return 0


# ── self-test ─────────────────────────────────────────────────────────────
# `python server.py --self-test`. Runs against an in-process fixture server on
# a free port, so it needs neither yfinance nor a network, and is the check a
# change to this file is held to.

def _get(base: str, path: str, headers: dict | None = None):
    import urllib.error
    import urllib.request
    request = urllib.request.Request(base + path, headers=headers or {})
    # The headers come back as the case-insensitive message object: the
    # static route spells Content-type the stdlib way, the JSON route ours.
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _start(source=None, fixture=True):
    server = make_server("127.0.0.1", 0, fixture=fixture, quiet=True, source=source)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread, "http://127.0.0.1:%d" % server.server_address[1]


class SelfTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.thread, cls.base = _start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, headers=None):
        return _get(self.base, path, headers)

    def json(self, path, headers=None):
        status, hdrs, body = self.get(path, headers)
        if hdrs.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return status, hdrs, json.loads(body)

    # -- bars ------------------------------------------------------------------
    def test_history_returns_bars_in_the_chart_shape(self):
        status, hdrs, bars = self.json("/api/history?symbol=AAPL&interval=1d&period=1y")
        self.assertEqual(status, 200)
        self.assertTrue(hdrs["Content-Type"].startswith("application/json"))
        self.assertGreater(len(bars), 200)
        for b in bars:
            self.assertEqual(set(b), {"time", "open", "high", "low", "close", "volume"})
            self.assertLessEqual(b["low"], min(b["open"], b["close"]))
            self.assertGreaterEqual(b["high"], max(b["open"], b["close"]))
            self.assertGreater(b["volume"], 0)
        times = [b["time"] for b in bars]
        self.assertEqual(times, sorted(times))
        self.assertEqual(len(set(times)), len(times))
        self.assertLessEqual(times[-1], int(time.time()))

    def test_fixture_is_deterministic_and_differs_by_symbol(self):
        pinned = "&from=1700000000&to=1710000000"
        a1 = self.get("/api/history?symbol=INFY.NS&interval=1d" + pinned)[2]
        a2 = self.get("/api/history?symbol=INFY.NS&interval=1d" + pinned)[2]
        b = self.get("/api/history?symbol=TCS.NS&interval=1d" + pinned)[2]
        self.assertEqual(a1, a2)
        self.assertNotEqual(a1, b)
        # A second server instance answers with the same bytes: nothing about
        # the values depends on process state.
        other, thread, base = _start()
        try:
            self.assertEqual(_get(base, "/api/history?symbol=INFY.NS&interval=1d" + pinned)[2], a1)
        finally:
            other.shutdown()
            other.server_close()

    def test_bars_connect_open_to_previous_close(self):
        _, _, bars = self.json("/api/history?symbol=AAPL&interval=1d&from=1700000000&to=1710000000")
        for prev, cur in zip(bars, bars[1:]):
            self.assertEqual(cur["open"], prev["close"])

    def test_the_price_is_a_random_walk_not_a_wave(self):
        # A random walk's variance over q days is q times its one-day
        # variance, so the ratio of the two sits near 1. Waves that repeat
        # within a quarter hold the 125-day change to their amplitude, and the
        # ratio falls towards 0: the sine fixture this replaced measured 0.18.
        # One symbol's ratio is noisy, so it is pooled over several.
        q, days = 125, 1300
        ratios = []
        for symbol in ("AAPL", "RELIANCE.NS", "INFY.NS", "MSFT", "^NSEI", "TCS.NS", "GOOG", "SBIN.NS", "BTC-USD"):
            venue, closes, day = venue_of(symbol), [], 1_700_000_000 // DAY
            while len(closes) < days:
                if _trading_day(venue, day):
                    closes.append(math.log(fixture_level(symbol, _at(venue, day, venue.close) - 60)))
                day += 1

            def variance(xs):
                mean = sum(xs) / len(xs)
                return sum((x - mean) ** 2 for x in xs) / len(xs)
            one = variance([b - a for a, b in zip(closes, closes[1:])])
            ratios.append(variance([closes[i + q] - closes[i] for i in range(days - q)]) / (q * one))
        self.assertGreater(sum(ratios) / len(ratios), 0.5)
        self.assertLess(sum(ratios) / len(ratios), 1.6)

    def test_intraday_grid_sits_in_the_venue_session_on_weekdays(self):
        # New York across the March 2024 clock change, and Mumbai, each in its own hours.
        for symbol, venue, window, count in (("AAPL", NEW_YORK, "&from=1709800000&to=1710600000", 400),
                                             ("RELIANCE.NS", MUMBAI, "&from=1700000000&to=1700600000", 300)):
            _, _, bars = self.json(f"/api/history?symbol={symbol}&interval=5m" + window)
            self.assertGreater(len(bars), count, symbol)
            for b in bars:
                day, into = _local(venue, b["time"])
                self.assertGreaterEqual(into, venue.open, symbol)
                self.assertLess(into, venue.close, symbol)
                self.assertLess(_weekday(day), 5, symbol)
                self.assertEqual((into - venue.open) % 300, 0, symbol)
            # Consecutive bars inside a day are one interval apart.
            gaps = {cur["time"] - prev["time"] for prev, cur in zip(bars, bars[1:])
                    if _local(venue, cur["time"])[0] == _local(venue, prev["time"])[0]}
            self.assertEqual(gaps, {300}, symbol)

    def test_new_york_clock_changes_match_the_zone_database(self):
        try:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo("America/New_York")
        except Exception:
            self.skipTest("no zone database on this machine")
        for year in range(2000, 2036):
            for ordinal in range(date(year, 1, 1).toordinal(), date(year + 1, 1, 1).toordinal()):
                d = date.fromordinal(ordinal)
                noon = datetime(d.year, d.month, d.day, 12, tzinfo=zone)
                self.assertEqual(_new_york_offset(ordinal - EPOCH_ORDINAL), noon.utcoffset().total_seconds(), noon)

    def test_a_pair_trades_around_the_clock(self):
        # 2024-03-08 is a Friday: the weekend has bars, every hour of every day.
        _, _, bars = self.json("/api/history?symbol=BTC-USD&interval=1h&from=1709856000&to=1710111600")
        self.assertEqual([b["time"] for b in bars], list(range(1709856000, 1710111600 + 1, 3600)))
        _, _, daily = self.json("/api/history?symbol=BTC-USD&interval=1d&from=1709856000&to=1710374400")
        self.assertEqual([b["time"] for b in daily], list(range(1709856000, 1710374400 + 1, DAY)))

    def test_calendar_intervals_land_on_their_boundaries(self):
        for symbol, venue in (("AAPL", NEW_YORK), ("RELIANCE.NS", MUMBAI)):
            local = [_local(venue, b["time"]) for b in self.json(f"/api/history?symbol={symbol}&interval=1d&from=1690000000&to=1710000000")[2]]
            self.assertTrue(all(into == venue.open and _weekday(day) < 5 for day, into in local), symbol)
            self.assertGreater(len(local), 150)
            weekly = self.json(f"/api/history?symbol={symbol}&interval=1wk&from=1690000000&to=1710000000")[2]
            self.assertTrue(all(_weekday(_local(venue, b["time"])[0]) == 0 for b in weekly), symbol)
            self.assertGreater(len(weekly), 25)
            dates = [date.fromordinal(_local(venue, b["time"])[0] + EPOCH_ORDINAL)
                     for b in self.json(f"/api/history?symbol={symbol}&interval=1mo&from=1600000000&to=1710000000")[2]]
            self.assertTrue(all(d.day == 1 for d in dates), symbol)
            self.assertGreater(len(dates), 40)
            dates = [date.fromordinal(_local(venue, b["time"])[0] + EPOCH_ORDINAL)
                     for b in self.json(f"/api/history?symbol={symbol}&interval=3mo&from=1600000000&to=1710000000")[2]]
            self.assertTrue(all(d.day == 1 and d.month in (1, 4, 7, 10) for d in dates), symbol)

    def test_intraday_period_is_clamped_like_the_source(self):
        _, _, bars = self.json("/api/history?symbol=AAPL&interval=1m&period=1y")
        self.assertGreaterEqual(bars[0]["time"], int(time.time()) - 8 * DAY)
        self.assertLess(len(bars), 3000)

    def test_period_days_resolves_ytd(self):
        mid_feb = int(datetime(2024, 2, 15, tzinfo=timezone.utc).timestamp())
        self.assertEqual(period_days("ytd", mid_feb), 45)
        self.assertIsNone(period_days("max", mid_feb))
        self.assertEqual(period_days("1y", mid_feb), 366)

    # -- sessions --------------------------------------------------------------
    def test_extended_session_adds_bars_around_the_same_regular_closes(self):
        window = "&from=1700000000&to=1700600000"
        _, _, regular = self.json("/api/history?symbol=AAPL&interval=5m" + window)
        _, _, extended = self.json("/api/history?symbol=AAPL&interval=5m&session=extended" + window)
        self.assertGreater(len(extended), len(regular))
        closes = {b["time"]: b["close"] for b in extended}
        # The regular hours are the same observations in both series; extended
        # hours add bars before the open and after the close, nothing else.
        for b in regular:
            self.assertEqual(closes[b["time"]], b["close"])
        extra = [_local(NEW_YORK, b["time"]) for b in extended if b["time"] not in {r["time"] for r in regular}]
        # New York's own pre and post market, 04:00 to 09:30 and 16:00 to 20:00.
        self.assertTrue(any(into < NEW_YORK.open for _, into in extra))
        self.assertTrue(any(into >= NEW_YORK.close for _, into in extra))
        for day, into in extra:
            self.assertGreaterEqual(into, NEW_YORK.pre)
            self.assertLess(into, NEW_YORK.post)
            self.assertLess(_weekday(day), 5)
        again = self.get("/api/history?symbol=AAPL&interval=5m&session=extended" + window)[2]
        self.assertEqual(json.loads(again), extended)

    def test_an_explicit_regular_session_is_the_default_series(self):
        window = "&from=1700000000&to=1700600000"
        self.assertEqual(self.get("/api/history?symbol=AAPL&interval=5m&session=regular" + window)[2],
                         self.get("/api/history?symbol=AAPL&interval=5m" + window)[2])

    def test_session_is_validated_and_served_only_where_the_source_has_it(self):
        status, _, body = self.json("/api/history?symbol=AAPL&interval=5m&session=overnight")
        self.assertEqual((status, body["code"]), (400, "bad_session"))
        for q in ("symbol=RELIANCE.NS&interval=5m", "symbol=AAPL&interval=1d", "symbol=%5EGSPC&interval=5m", "symbol=BTC-USD&interval=5m"):
            status, _, body = self.json("/api/history?" + q + "&session=extended")
            self.assertEqual((status, body["code"]), (400, "unsupported_session"), q)
        self.assertTrue(extended_session_available("BRK-B", "15m"))
        self.assertFalse(extended_session_available("BRK-B", "1wk"))

    def test_the_session_reaches_the_source(self):
        seen = []
        server, thread, base = _start(source=lambda req, now: seen.append(req.session) or [{"time": 1700000000, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])
        try:
            _get(base, "/api/history?symbol=AAPL&interval=5m&session=extended&from=1700000000&to=1700600000")
            _get(base, "/api/history?symbol=AAPL&interval=5m&from=1700000000&to=1700600000")
            self.assertEqual(seen, ["extended", "regular"])
        finally:
            server.shutdown()
            server.server_close()

    # -- validation ------------------------------------------------------------
    def test_symbol_is_validated(self):
        for path in ("/api/history", "/api/history?symbol=", "/api/history?symbol=AA%20PL",
                     "/api/history?symbol=" + "A" * 25, "/api/history?symbol=.AAPL", "/api/history?symbol=%3Cb%3E"):
            status, _, body = self.json(path)
            self.assertEqual(status, 400, path)
            self.assertEqual(body["code"], "bad_symbol", path)
            self.assertIn("symbol", body["error"])
        for ok in ("AAPL", "RELIANCE.NS", "%5ENSEI", "BTC-USD", "GC%3DF", "BRK-B", "EURUSD%3DX"):
            self.assertEqual(self.get("/api/history?symbol=" + ok + "&from=1700000000&to=1701000000")[0], 200, ok)

    def test_interval_and_period_are_allowlisted(self):
        status, _, body = self.json("/api/history?symbol=AAPL&interval=7m")
        self.assertEqual((status, body["code"]), (400, "bad_interval"))
        status, _, body = self.json("/api/history?symbol=AAPL&period=3y")
        self.assertEqual((status, body["code"]), (400, "bad_period"))
        status, _, body = self.json("/api/history?symbol=AAPL&interval=1d&period=1y")
        self.assertEqual(status, 200)

    def test_range_is_validated(self):
        for q in ("to=abc", "from=-5", "to=1.5", "from=99999999999", "from=1700000000&to=1700000000",
                  "from=1700000001&to=1700000000"):
            status, _, body = self.json("/api/history?symbol=AAPL&" + q)
            self.assertEqual((status, body["code"]), (400, "bad_range"), q)

    def test_unknown_endpoint_is_json_404(self):
        status, hdrs, body = self.json("/api/quote?symbol=AAPL")
        self.assertEqual((status, body["code"]), (404, "not_found"))
        self.assertTrue(hdrs["Content-Type"].startswith("application/json"))

    # -- quotes and news -------------------------------------------------------
    def test_quotes_answer_known_symbols_and_leave_unknown_ones_out(self):
        status, hdrs, quotes = self.json("/api/quotes?symbols=AAPL,RELIANCE.NS,FAIL,AAPL")
        self.assertEqual(status, 200)
        self.assertEqual(hdrs["Cache-Control"], "no-store")
        self.assertEqual([q["symbol"] for q in quotes], ["AAPL", "RELIANCE.NS"])
        for q in quotes:
            self.assertEqual(set(q), {"symbol", "exchange", "last", "previousClose", "bid", "ask", "volume", "time"})
            self.assertEqual(q["exchange"], "")
            self.assertLess(q["bid"], q["last"])
            self.assertGreater(q["ask"], q["last"])
            self.assertEqual(q["time"] % QUOTE_STEP, 0)
            self.assertGreater(q["previousClose"], 0)

    def test_quotes_are_a_pure_function_of_symbol_and_step(self):
        pinned = 1_758_800_001
        self.assertEqual(fixture_quotes(["INFY.NS"], pinned), fixture_quotes(["INFY.NS"], pinned - 1))
        self.assertNotEqual(fixture_quotes(["INFY.NS"], pinned)[0]["last"], fixture_quotes(["INFY.NS"], pinned + 600)[0]["last"])
        # The quote is taken at its own time: it is not the last daily bar's close.
        bar = fixture_bars(HistoryRequest("INFY.NS", "1d", "1mo", None, pinned), pinned)[-1]
        self.assertNotEqual(fixture_quotes(["INFY.NS"], pinned)[0]["last"], bar["close"])

    def test_quote_requests_are_validated(self):
        for path in ("/api/quotes", "/api/quotes?symbols=", "/api/quotes?symbols=AA%20PL",
                     "/api/quotes?symbols=" + ",".join(f"S{i}" for i in range(MAX_QUOTE_SYMBOLS + 1))):
            status, _, body = self.json(path)
            self.assertEqual((status, body["code"]), (400, "bad_symbol"), path)

    def test_news_pages_follow_the_cursor_to_the_end_without_repeats(self):
        pinned = 1_758_800_000
        first = fixture_news({"symbol": "AAPL", "limit": 20, "cursor": None}, pinned)
        self.assertEqual(len(first["items"]), 20)
        seen, page, pages = [], first, 1
        while True:
            times = [item["time"] for item in page["items"]]
            self.assertEqual(times, sorted(times, reverse=True))
            seen.extend(item["id"] for item in page["items"])
            if page["nextCursor"] is None:
                break
            # Later pages depend on the cursor alone, not on the clock.
            page = fixture_news({"symbol": "AAPL", "limit": 20, "cursor": page["nextCursor"]}, pinned + 99999)
            pages += 1
        self.assertGreater(pages, 1)
        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(first, fixture_news({"symbol": "AAPL", "limit": 20, "cursor": None}, pinned))
        status, hdrs, body = self.json("/api/news?symbol=AAPL&limit=5")
        self.assertEqual((status, len(body["items"])), (200, 5))
        self.assertEqual(hdrs["Cache-Control"], "no-store")
        status, _, older = self.json("/api/news?symbol=AAPL&limit=5&cursor=" + body["nextCursor"])
        self.assertEqual(status, 200)
        self.assertLess(older["items"][0]["time"], body["items"][-1]["time"])

    def test_news_headlines_vary_from_story_to_story(self):
        page = fixture_news({"symbol": "AAPL", "limit": 20, "cursor": None}, 1_758_800_000)
        headlines = [item["headline"] for item in page["items"]]
        longest = run = 1
        for previous, current in zip(headlines, headlines[1:]):
            run = run + 1 if current == previous else 1
            longest = max(longest, run)
        self.assertLessEqual(longest, 3)
        self.assertGreaterEqual(len(set(headlines)), 5)

    def test_news_markup_headlines_carry_an_unsafe_link_for_the_reader_to_refuse(self):
        found = []
        for symbol in ("AAPL", "MSFT", "INFY.NS", "RELIANCE.NS", "TCS.NS"):
            page = fixture_news({"symbol": symbol, "limit": 50, "cursor": None}, 1_758_800_000)
            found += [item for item in page["items"] if "<b>" in item["headline"]]
        self.assertTrue(found)
        for item in found:
            self.assertTrue(item["url"].startswith("javascript:"))

    def test_news_sentinels_and_validation(self):
        self.assertEqual(self.json("/api/news?symbol=EMPTY")[2], {"items": [], "nextCursor": None})
        status, _, body = self.json("/api/news?symbol=FAIL")
        self.assertEqual((status, body["code"]), (502, "upstream_error"))
        for query, code in (("symbol=%3Cb%3E", "bad_symbol"), ("symbol=AAPL&limit=0", "bad_limit"),
                            ("symbol=AAPL&limit=500", "bad_limit"), ("symbol=AAPL&cursor=abc", "bad_cursor")):
            status, _, body = self.json("/api/news?" + query)
            self.assertEqual((status, body["code"]), (400, code), query)

    def test_quotes_and_news_are_not_made_up_without_the_fixture(self):
        server, thread, base = _start(fixture=False)
        try:
            for path in ("/api/quotes?symbols=AAPL", "/api/news?symbol=AAPL"):
                status, _, body = _get(base, path)
                self.assertEqual((status, json.loads(body)["code"]), (501, "not_available"), path)
        finally:
            server.shutdown()
            server.server_close()

    # -- error states ----------------------------------------------------------
    def test_sentinel_symbols_exercise_the_error_paths(self):
        status, _, body = self.json("/api/history?symbol=FAIL")
        self.assertEqual((status, body["code"]), (502, "upstream_error"))
        status, _, body = self.json("/api/history?symbol=fail")
        self.assertEqual(status, 502)
        status, _, body = self.json("/api/history?symbol=EMPTY")
        self.assertEqual((status, body["code"]), (404, "no_data"))
        status, hdrs, body = self.json("/api/history?symbol=BUSY")
        self.assertEqual((status, body["code"]), (429, "rate_limited"))
        self.assertEqual(hdrs["Retry-After"], "30")

    def test_banded_symbol_trades_on_its_tick_schedule_across_the_boundary(self):
        _, _, bars = self.json("/api/history?symbol=banded&interval=1d&from=1700000000&to=1730000000")
        prices = [b[k] for b in bars for k in ("open", "high", "low", "close")]
        self.assertTrue(any(p < BANDED_BOUNDARY for p in prices) and any(p >= BANDED_BOUNDARY for p in prices))
        for p in prices:
            cents = round(p * 100)
            self.assertAlmostEqual(p * 100, cents, places=6)
            if p >= BANDED_BOUNDARY:
                self.assertEqual(cents % 5, 0, p)
        for b in bars:
            self.assertLessEqual(b["low"], min(b["open"], b["close"]))
            self.assertGreaterEqual(b["high"], max(b["open"], b["close"]))
        self.assertEqual(banded_price(99.996), 100.0)
        self.assertEqual(banded_price(100.024), 100.0)
        self.assertEqual(banded_price(100.025), 100.05)

    def test_upstream_errors_map_to_429_or_502_without_a_traceback(self):
        class YFRateLimitError(Exception):
            pass
        e = upstream_error(YFRateLimitError("Too Many Requests. Rate limited."))
        self.assertEqual((e.status, e.code, e.headers.get("Retry-After")), (429, "rate_limited", "60"))
        e = upstream_error(ConnectionError("name resolution failed\nsecond line"))
        self.assertEqual((e.status, e.code), (502, "upstream_error"))
        self.assertEqual(e.message, "ConnectionError: name resolution failed second line")
        e = upstream_error(RuntimeError("x" * 1000))
        self.assertLess(len(e.message), 400)

    def test_a_source_with_no_bars_is_a_404(self):
        server, thread, base = _start(source=lambda req, now: [])
        try:
            status, hdrs, body = _get(base, "/api/history?symbol=AAPL&interval=5m&period=1mo")
            self.assertEqual((status, json.loads(body)["code"]), (404, "no_data"))
            self.assertIn("5m bars of AAPL over 1mo", json.loads(body)["error"])
            self.assertEqual(hdrs["Cache-Control"], "no-store")
        finally:
            server.shutdown()
            server.server_close()

    def test_a_bug_in_the_source_is_a_500_that_leaks_nothing(self):
        def broken(req, now):
            raise RuntimeError("boom in C:\\private\\path\\server.py")
        server, thread, base = _start(source=broken)
        try:
            status, hdrs, body = _get(base, "/api/history?symbol=AAPL")
            self.assertEqual(status, 500)
            text = body.decode()
            self.assertEqual(json.loads(text)["code"], "internal_error")
            self.assertNotIn("Traceback", text)
            self.assertNotIn("private", text)
            self.assertNotIn("boom", text)
            self.assertEqual(hdrs["Cache-Control"], "no-store")
        finally:
            server.shutdown()
            server.server_close()

    def test_missing_yfinance_is_a_503(self):
        real = sys.modules.get("yfinance")
        sys.modules["yfinance"] = None  # makes `import yfinance` raise ModuleNotFoundError
        try:
            server, thread, base = _start(fixture=False)
            try:
                status, _, body = _get(base, "/api/history?symbol=AAPL")
                self.assertEqual((status, json.loads(body)["code"]), (503, "not_installed"))
            finally:
                server.shutdown()
                server.server_close()
        finally:
            if real is None:
                del sys.modules["yfinance"]
            else:
                sys.modules["yfinance"] = real

    # -- headers ---------------------------------------------------------------
    def test_cache_control_is_short_for_live_and_immutable_for_closed_ranges(self):
        _, hdrs, _ = self.get("/api/history?symbol=AAPL&interval=1d&period=1mo")
        self.assertEqual(hdrs["Cache-Control"], LIVE_CACHE)
        _, hdrs, _ = self.get("/api/history?symbol=AAPL&interval=1d&from=1700000000&to=1701000000")
        self.assertEqual(hdrs["Cache-Control"], CLOSED_CACHE)
        # A window that ends now still holds a forming bar.
        now = int(time.time())
        _, hdrs, _ = self.get(f"/api/history?symbol=AAPL&interval=1d&period=1mo&to={now}")
        self.assertEqual(hdrs["Cache-Control"], LIVE_CACHE)
        # And so does one that ended a minute ago on a daily interval, whose
        # last bar can still be open; the same minute on 1m bars has closed.
        _, hdrs, _ = self.get(f"/api/history?symbol=AAPL&interval=1d&period=1mo&to={now - 60}")
        self.assertEqual(hdrs["Cache-Control"], LIVE_CACHE)
        _, hdrs, _ = self.get(f"/api/history?symbol=AAPL&interval=1m&period=5d&to={now - 120}")
        self.assertEqual(hdrs["Cache-Control"], CLOSED_CACHE)
        # Errors are never cached.
        _, hdrs, _ = self.get("/api/history?symbol=FAIL&from=1700000000&to=1701000000")
        self.assertEqual(hdrs["Cache-Control"], "no-store")

    def test_gzip_only_when_the_client_accepts_it(self):
        path = "/api/history?symbol=AAPL&interval=1d&from=1700000000&to=1710000000"
        status, plain_hdrs, plain = self.get(path)
        self.assertEqual(status, 200)
        self.assertNotIn("Content-Encoding", plain_hdrs)
        status, gz_hdrs, gz = self.get(path, {"Accept-Encoding": "gzip, deflate, br"})
        self.assertEqual(gz_hdrs["Content-Encoding"], "gzip")
        self.assertEqual(gz_hdrs["Vary"], "Accept-Encoding")
        self.assertEqual(int(gz_hdrs["Content-Length"]), len(gz))
        self.assertLess(len(gz), len(plain))
        self.assertEqual(gzip.decompress(gz), plain)
        _, hdrs, _ = self.get(path, {"Accept-Encoding": "gzip;q=0, identity"})
        self.assertNotIn("Content-Encoding", hdrs)
        # A short error body is not worth the header.
        _, hdrs, _ = self.get("/api/history?symbol=FAIL", {"Accept-Encoding": "gzip"})
        self.assertNotIn("Content-Encoding", hdrs)

    def test_static_files_are_served_uncached(self):
        status, hdrs, body = self.get("/examples/yfinance/server.py")
        self.assertEqual(status, 200)
        self.assertEqual(hdrs["Cache-Control"], "no-store, must-revalidate")
        self.assertIn(b"openalgo-charts", body)
        status, hdrs, _ = self.get("/examples/yfinance/src/main.js")
        self.assertEqual(status, 200)
        self.assertTrue(hdrs["Content-Type"].startswith("application/javascript"))
        self.assertEqual(self.get("/examples/yfinance/no-such-file")[0], 404)

    # -- operations ------------------------------------------------------------
    def test_log_line_carries_method_path_status_size_and_duration(self):
        line = format_log_line("127.0.0.1", "GET", "/api/history?symbol=AAPL", 200, "1234", 12.4)
        self.assertRegex(line, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d 127\.0\.0\.1 GET /api/history\?symbol=AAPL 200 1234 12ms$")
        self.assertTrue(format_log_line("::1", "GET", "/", None, None, 0).endswith(" GET / - - 0ms"))

    def test_shutdown_is_prompt_and_frees_the_port(self):
        server, thread, base = _start()
        port = server.server_address[1]
        self.assertEqual(_get(base, "/api/history?symbol=AAPL&period=5d")[0], 200)
        t0 = time.monotonic()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertLess(time.monotonic() - t0, 2)
        again = make_server("127.0.0.1", port, fixture=True, quiet=True)
        again.server_close()

    def test_serve_returns_on_ctrl_c(self):
        import _thread
        server = make_server("127.0.0.1", 0, fixture=True, quiet=True)
        # Ctrl+C is a KeyboardInterrupt in the main thread; this is that, on a timer.
        threading.Timer(0.2, _thread.interrupt_main).start()
        t0 = time.monotonic()
        serve(server)
        self.assertLess(time.monotonic() - t0, 3)
        with self.assertRaises(OSError):
            server.socket.getsockname()  # closed: the socket is gone

    def test_cli_port_forms(self):
        self.assertEqual(pick_port(None, None), 8000)
        self.assertEqual(pick_port(None, 8123), 8123)
        self.assertEqual(pick_port(9000, 8123), 9000)
        self.assertEqual(pick_port(0, None), 0)

    def test_gzip_negotiation(self):
        self.assertTrue(accepts_gzip("gzip"))
        self.assertTrue(accepts_gzip("gzip, deflate, br"))
        self.assertTrue(accepts_gzip("GZIP;q=0.5"))
        self.assertFalse(accepts_gzip("gzip;q=0"))
        self.assertFalse(accepts_gzip("identity"))
        self.assertFalse(accepts_gzip(None))


if __name__ == "__main__":
    sys.exit(main())
