"""IST timestamp utilities for the Strategy v2 engine and any other module that
needs to render Indian-time strings while keeping UTC as the storage truth.

Storage rule:    DB columns store UTC (TIMESTAMP, datetime.now(timezone.utc) defaults).
Display rule:    APIs and Socket.IO payloads return IST display strings matching the
                 existing /orderbook ('DD-MMM-YYYY HH:MM:SS') and /tradebook ('HH:MM:SS')
                 formats produced by broker responses.
Engine rule:     Internal math uses UTC epoch ms (matches market_data_service ticks).

India has no DST, so IST is constantly UTC+5:30. No edge cases around DST.

This module deliberately lives in utils/ (not services/) so it can be imported
by services, blueprints, subscribers, and event handlers without circular-import
risk.
"""

from datetime import datetime, timezone, timedelta
from typing import Union

IST = timezone(timedelta(hours=5, minutes=30))

# Match existing /orderbook timestamp format: "08-May-2026 14:30:45"
ORDERBOOK_FMT = "%d-%b-%Y %H:%M:%S"

# Match existing /tradebook timestamp format: "14:30:45"
TRADEBOOK_FMT = "%H:%M:%S"

# Used when we need an unambiguous machine-parseable IST string (logs, telemetry).
ISO_IST_FMT = "%Y-%m-%dT%H:%M:%S+05:30"

TimestampLike = Union[int, float, datetime]


def now_utc() -> datetime:
    """Engine's source of truth for 'now' — always timezone-aware UTC."""
    return datetime.now(timezone.utc)


def to_ist(ts: TimestampLike) -> datetime:
    """Convert epoch seconds, epoch milliseconds, or a datetime to a timezone-aware IST datetime.

    Naive datetimes are assumed to be UTC (matches our DB default). Timestamps
    larger than 1e12 are treated as milliseconds.
    """
    if isinstance(ts, (int, float)):
        # Epoch — auto-detect ms vs s.
        seconds = ts / 1000.0 if ts > 1e12 else float(ts)
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    elif isinstance(ts, datetime):
        dt = ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
    else:
        raise TypeError(f"Unsupported timestamp type: {type(ts).__name__}")
    return dt.astimezone(IST)


def fmt_orderbook(ts: TimestampLike) -> str:
    """Format a timestamp as 'DD-MMM-YYYY HH:MM:SS' in IST (matches /orderbook responses)."""
    return to_ist(ts).strftime(ORDERBOOK_FMT)


def fmt_tradebook(ts: TimestampLike) -> str:
    """Format a timestamp as 'HH:MM:SS' in IST (matches /tradebook responses)."""
    return to_ist(ts).strftime(TRADEBOOK_FMT)


def fmt_iso_ist(ts: TimestampLike) -> str:
    """Format a timestamp as ISO-8601 with explicit +05:30 offset (logs, telemetry)."""
    return to_ist(ts).strftime(ISO_IST_FMT)


def parse_broker_ist(s: str) -> datetime:
    """Parse a broker-supplied IST string ('DD-MMM-YYYY HH:MM:SS' or 'HH:MM:SS')
    into a timezone-aware UTC datetime suitable for storing in a TIMESTAMP column.

    For HH:MM:SS only (tradebook-style), the date is assumed to be today's IST date.
    Returns the equivalent UTC datetime.
    """
    s = s.strip()
    if not s:
        raise ValueError("Empty timestamp string")

    fmts = (ORDERBOOK_FMT, TRADEBOOK_FMT)
    for fmt in fmts:
        try:
            naive = datetime.strptime(s, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"Cannot parse broker timestamp: {s!r}")

    if fmt == TRADEBOOK_FMT:
        today_ist = datetime.now(IST).date()
        naive = naive.replace(year=today_ist.year, month=today_ist.month, day=today_ist.day)

    aware_ist = naive.replace(tzinfo=IST)
    return aware_ist.astimezone(timezone.utc)


def to_epoch_ms(ts: TimestampLike) -> int:
    """Return UTC epoch milliseconds — engine-internal time format used in
    Socket.IO payloads alongside the IST display string."""
    if isinstance(ts, (int, float)):
        return int(ts if ts > 1e12 else ts * 1000)
    if isinstance(ts, datetime):
        dt = ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    raise TypeError(f"Unsupported timestamp type: {type(ts).__name__}")
