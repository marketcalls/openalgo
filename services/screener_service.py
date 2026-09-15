"""
Bar delivery for the indicator screener.

The screener runs one chart indicator across a few hundred symbols. The
indicator itself runs in the browser -- an ``openalgo-charts`` descriptor's
``calc`` is a pure function of ``(bars, settings)``, so the same code that draws
the study on ``/trading`` produces the screener's numbers, and a value in the
results table is the value on the chart by construction rather than by a second
implementation agreeing with the first.

That leaves this module with one job: hand the browser those bars, cheaply. It
does not evaluate indicators, filters or conditions.

Two sources, combined:

- **Historify DuckDB** for the history, read through
  ``database.historify_db.get_bulk_ohlcv`` in one query per exchange. The
  per-symbol ``get_history`` path is the wrong door here: it paces itself at
  350ms per call and materialises every bar as a dict, so 500 symbols is
  minutes of sleeping.
- **A batch quote** for the newest, still-forming candle, so an intraday scan
  reflects the current session instead of the last ingest.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from database.historify_db import (
    COMPUTED_INTERVALS,
    INTERVAL_MINUTES,
    IST_OFFSET_SECONDS,
    STORAGE_INTERVALS,
    _get_market_open_seconds,
    bucket_start,
    get_bulk_ohlcv,
)
from services.quotes_service import get_multiquotes
from utils.logging import get_logger

logger = get_logger(__name__)

# What the screener will scan. Deliberately narrower than what Historify can
# aggregate: W/M/Q/Y answer a question a screener is not asking, and every extra
# interval is another aggregation path to be right about.
SUPPORTED_INTERVALS = tuple(sorted(STORAGE_INTERVALS | COMPUTED_INTERVALS))

# A scan is one request, one response and one pass of the indicator over each
# symbol, so both ends are bounded rather than left to whatever list gets pasted
# in. 500 symbols x 300 bars is a few megabytes; an order of magnitude more is a
# request that times out rather than a scan that takes longer.
MAX_SYMBOLS = 500
MIN_BARS = 50
MAX_BARS = 1000
DEFAULT_BARS = 300

# The batch quote ceiling the rest of the platform uses (see
# restx_api/data_schemas.py). Chunks are fetched sequentially: production is a
# single eventlet worker, and every broker prices concurrency with a throttle.
QUOTE_CHUNK = 50

IST = timezone(timedelta(seconds=IST_OFFSET_SECONDS))


def scan_bars(
    pairs: list[tuple[str, str]],
    interval: str,
    bars: int = DEFAULT_BARS,
    live: bool = False,
    api_key: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Bars for a screener scan.

    Args:
        pairs: ``(symbol, exchange)`` tuples.
        interval: One of ``SUPPORTED_INTERVALS``.
        bars: Most recent candles per symbol.
        live: Stitch the forming candle on from a batch quote.
        api_key: Needed only when ``live`` is set. Without it the scan still
            runs on stored history and reports ``live: false``.

    Returns:
        ``(success, payload, http_status)``. The payload's ``data`` maps
        ``"EXCHANGE:SYMBOL"`` to columnar arrays; ``missing`` names the symbols
        Historify holds nothing for.
    """
    if interval not in SUPPORTED_INTERVALS:
        return (
            False,
            {
                "status": "error",
                "message": f"Unsupported interval '{interval}'. "
                f"Supported: {', '.join(SUPPORTED_INTERVALS)}",
            },
            400,
        )
    if not pairs:
        return False, {"status": "error", "message": "No symbols provided"}, 400
    if len(pairs) > MAX_SYMBOLS:
        return (
            False,
            {
                "status": "error",
                "message": f"{len(pairs)} symbols requested, limit is {MAX_SYMBOLS}",
            },
            400,
        )
    if not MIN_BARS <= bars <= MAX_BARS:
        return (
            False,
            {"status": "error", "message": f"bars must be {MIN_BARS}-{MAX_BARS}"},
            400,
        )

    data, missing = get_bulk_ohlcv(pairs, interval, bars)

    stitched = False
    if live and data:
        if api_key:
            stitched = _stitch_live(data, interval, api_key)
        else:
            logger.info("Screener scan asked for live bars with no API key; serving stored only")

    return (
        True,
        {
            "status": "success",
            "interval": interval,
            "bars": bars,
            "live": stitched,
            "data": data,
            "missing": [
                {"symbol": key.split(":", 1)[1], "exchange": key.split(":", 1)[0]}
                for key in missing
            ],
        },
        200,
    )


def _stitch_live(data: dict[str, dict[str, list]], interval: str, api_key: str) -> bool:
    """
    Bring each series up to the current quote.

    Best effort throughout: a scan on slightly stale bars is useful, a scan that
    fails because the broker is busy is not. Any chunk that errors leaves its
    symbols on their stored history.

    ponytail: the forming candle's high and low are approximated from the LTP,
    which is exact for its close and a lower bound for its range. Exact needs
    the 1m ingest to be current, which is the same thing that makes the
    approximation small.

    Returns:
        True if at least one series was updated.
    """
    keys = list(data)
    quotes: dict[str, dict[str, Any]] = {}

    for start in range(0, len(keys), QUOTE_CHUNK):
        chunk = keys[start : start + QUOTE_CHUNK]
        request = [
            {"symbol": key.split(":", 1)[1], "exchange": key.split(":", 1)[0]} for key in chunk
        ]
        try:
            ok, response, _ = get_multiquotes(request, api_key=api_key)
        except Exception:
            logger.exception("Screener live quote chunk failed")
            continue
        if not ok:
            logger.info(f"Screener live quote chunk refused: {response.get('message')}")
            continue
        for item in response.get("results") or []:
            quote = item.get("data")
            if not quote:
                continue
            quotes[f"{item.get('exchange')}:{item.get('symbol')}"] = quote

    if not quotes:
        return False

    now = int(datetime.now(UTC).timestamp())
    updated = False
    for key, columns in data.items():
        quote = quotes.get(key)
        if not quote:
            continue
        try:
            ltp = float(quote.get("ltp") or 0)
        except (TypeError, ValueError):
            continue
        if ltp <= 0 or not columns.get("t"):
            continue
        if _apply_quote(columns, key.split(":", 1)[0], interval, ltp, now):
            updated = True
    return updated


def _apply_quote(
    columns: dict[str, list], exchange: str, interval: str, ltp: float, now: int
) -> bool:
    """
    Extend or amend one series with a live price.

    Three cases, and a fourth that is deliberately a no-op:

    - the quote falls in the last stored candle: amend it in place;
    - it falls in the very next candle: append one bar;
    - it is older than the last stored candle: leave it alone;
    - it is further ahead than one candle: also leave it alone.

    That last case is what keeps the series honest. Outside market hours the
    quote is the day's close and "now" is many candles past the last bar, so
    appending would invent a flat candle at a time the market was shut. A store
    that is days stale has a hole no single price can fill. In both, the right
    answer is to change nothing and let the newest bar's timestamp show the user
    how old the data is.
    """
    last_t = int(columns["t"][-1])
    step = _interval_seconds(interval)
    if step is None:
        return False

    if interval == "D":
        # Daily timestamps carry whatever time-of-day convention the ingest
        # wrote, so the next bar is derived by shifting the last one rather than
        # by constructing a timestamp from scratch.
        days = (_ist_date(now) - _ist_date(last_t)).days
        if days < 0 or days > 1:
            return False
        bucket = last_t + 86400 * days
    else:
        bucket = bucket_start(now, step, _get_market_open_seconds(exchange))
        if bucket < last_t or bucket - last_t > step:
            return False

    if bucket == last_t:
        columns["c"][-1] = ltp
        columns["h"][-1] = max(float(columns["h"][-1]), ltp)
        columns["l"][-1] = min(float(columns["l"][-1]), ltp)
        return True

    columns["t"].append(bucket)
    columns["o"].append(ltp)
    columns["h"].append(ltp)
    columns["l"].append(ltp)
    columns["c"].append(ltp)
    # Every column must stay the same length as every other -- a ragged column
    # is exactly what an indicator's calc cannot survive.
    if "v" in columns:
        columns["v"].append(0)
    return True


def _interval_seconds(interval: str) -> int | None:
    if interval == "D":
        return 86400
    minutes = INTERVAL_MINUTES.get(interval)
    return minutes * 60 if minutes else None


def _ist_date(ts: int):
    return datetime.fromtimestamp(ts, IST).date()
