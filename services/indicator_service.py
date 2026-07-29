# services/indicator_service.py
"""
Technical indicator computation for internal features (currently: Flow's
`indicator` node). Wraps the `openalgo.ta` Rust-backed indicator library
(pinned as the `openalgo` dependency in pyproject.toml) over OHLCV history.

This mirrors the input-resolution pattern already proven in
`mcp/mcpserver.py:calculate_indicator` (history -> auto-detect OHLC(V) inputs
-> call the ta function by name) but lives in services/ so internal callers
import it directly instead of going through the MCP tool layer. The MCP tool
is left untouched; this is a fresh, reusable implementation of the same idea.
"""

import inspect
import os
import threading
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from cachetools import TTLCache
from openalgo import ta

from utils.logging import get_logger

logger = get_logger(__name__)

# --- Shared history cache -------------------------------------------------
#
# Broker data APIs are rate limited far more tightly than a node-graph makes
# obvious: Dhan allows 5 req/s on history and only 1 req/s on quotes (error
# 805 on breach), Flattrade 10 req/s, some Zerodha paths 1 req/s, and
# services/history_service.py serializes every broker history call behind a
# process-wide ~350ms gate. A single strategy asking for RSI + SMA + ATR +
# previous-day levels on one symbol would otherwise issue four *identical*
# history requests per run, each waiting on that gate.
#
# Nodes therefore share one short-TTL cache keyed by the exact request. This
# collapses repeated fetches within a run (and across back-to-back runs)
# without hiding new bars: the default TTL is well under a one-minute candle.
# Bounded via maxsize so it cannot grow without limit in a long-lived worker
# (see the FD/memory hygiene rules in CLAUDE.md).
_HISTORY_CACHE_TTL = float(os.getenv("FLOW_HISTORY_CACHE_TTL", "30"))
_HISTORY_CACHE_MAXSIZE = int(os.getenv("FLOW_HISTORY_CACHE_MAXSIZE", "256"))
_history_cache: TTLCache = TTLCache(
    maxsize=max(_HISTORY_CACHE_MAXSIZE, 1), ttl=max(_HISTORY_CACHE_TTL, 0.001)
)
_history_cache_lock = threading.Lock()


def fetch_history_cached(
    client,
    symbol: str,
    exchange: str,
    interval: str,
    start_date: str,
    end_date: str,
    source: str = "api",
) -> dict[str, Any]:
    """Fetch OHLCV history through a short-TTL, process-wide cache.

    Only successful, non-empty responses are cached — an error or an empty
    range must stay retryable rather than being pinned for the whole TTL.
    Set FLOW_HISTORY_CACHE_TTL=0 to effectively disable caching.
    """
    key = (symbol, exchange, interval, start_date, end_date, source)

    if _HISTORY_CACHE_TTL > 0:
        with _history_cache_lock:
            hit = _history_cache.get(key)
        if hit is not None:
            logger.debug(f"History cache hit: {symbol} {interval} ({source})")
            return hit

    result = client.get_history(
        symbol=symbol,
        exchange=exchange,
        interval=interval,
        start_date=start_date,
        end_date=end_date,
        source=source,
    )

    if _HISTORY_CACHE_TTL > 0 and (result or {}).get("data"):
        with _history_cache_lock:
            _history_cache[key] = result
    return result


def clear_history_cache() -> None:
    """Drop all cached history (test/administrative helper)."""
    with _history_cache_lock:
        _history_cache.clear()


# Every ta function names its OHLCV-series parameters consistently
# (open_prices/open, high, low, close, data, volume) and always lists them
# before any scalar parameter (period, length, multiplier, ...). Introspecting
# the real signature and matching by parameter name is far more reliable than
# a hand-maintained "which indicators need H/L/C" table — it self-corrects
# whenever the pinned `openalgo` version changes an indicator's arg order.
_SERIES_PARAM_TO_COLUMN = {
    "open_prices": "open",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "data": "close",
    "volume": "volume",
}

# A handful of required (no-default) scalar params that would otherwise raise
# TypeError if the caller's `params` doesn't set them. Applied only when the
# caller hasn't already supplied the key.
_REQUIRED_PARAM_DEFAULTS = {
    "sma": {"period": 14},
    "ema": {"period": 14},
    "wma": {"period": 14},
    "hma": {"period": 14},
    "dema": {"period": 14},
    "tema": {"period": 14},
    "zlema": {"period": 14},
    "vwma": {"period": 14},
    "highest": {"period": 14},
    "lowest": {"period": 14},
    "stdev": {"period": 14},
    "roc": {"length": 14},
    "rising": {"length": 1},
    "falling": {"length": 1},
}

# Indicators that need two independent series (a second symbol's data, or two
# already-computed signals) rather than one symbol's OHLCV — not
# representable by the single-symbol Indicator node. Kept here so callers get
# a clear error instead of a confusing stack trace.
TWO_SERIES_INDICATORS = {
    "correlation",
    "beta",
    "crossover",
    "crossunder",
    "cross",
    "exrem",
    "flip",
    "valuewhen",
}

# Indicators with a non-flat call shape (submodule access) that the generic
# getattr(ta, name)(...) dispatch below cannot call directly.
UNSUPPORTED_INDICATORS = {"median_bands"}

# Approx bars per trading day per interval (NSE ~6h15m session), used only to
# size the calendar window when fetching by bar-count.
_BARS_PER_DAY = {
    "1m": 375,
    "3m": 125,
    "5m": 75,
    "10m": 38,
    "15m": 25,
    "30m": 13,
    "1h": 7,
    "60m": 7,
    "2h": 4,
    "3h": 3,
    "4h": 2,
    "d": 1,
    "1d": 1,
    "day": 1,
    "w": 0.2,
    "week": 0.2,
    "m": 0.05,
    "month": 0.05,
    # Historify advertises quarterly/yearly aggregates. Without entries here
    # they fall back to the intraday default (75 bars/day) and the computed
    # window spans only days, yielding at most one bar - so every indicator
    # returns null.
    "q": 0.016,
    "quarter": 0.016,
    "y": 0.004,
    "year": 0.004,
}


def list_supported_indicators() -> list[str]:
    """Every `ta` function name usable by the generic single-symbol node."""
    names = [n for n in dir(ta) if not n.startswith("_")]
    excluded = TWO_SERIES_INDICATORS | UNSUPPORTED_INDICATORS
    return sorted(n for n in names if n not in excluded)


def is_single_series_indicator(name: str) -> bool:
    """True if the indicator's only series input is a single close-like
    series (param named `data`) — the only shape that can be nested on top
    of another indicator's output series."""
    fn = getattr(ta, name.strip().lower(), None)
    if fn is None:
        return False
    sig = inspect.signature(fn)
    series_params = [p for p in sig.parameters.values() if p.name in _SERIES_PARAM_TO_COLUMN]
    return len(series_params) == 1 and series_params[0].name == "data"


def resolve_indicator_inputs(
    df: pd.DataFrame, fn, inputs: list[str] | None = None
) -> tuple[list[str], list[pd.Series]]:
    """Pick the ordered input Series for an indicator from its real signature.

    Series-named parameters (open_prices/open/high/low/close/data/volume)
    always appear before any scalar parameter in every `ta` function, so
    walking the signature in order and stopping at the first non-series name
    reconstructs the correct positional call for every indicator without a
    hand-maintained per-name table.
    """
    if inputs:
        cols = [c.lower() for c in inputs]
        return cols, [df[c] for c in cols]

    cols = []
    for param in inspect.signature(fn).parameters.values():
        if param.name not in _SERIES_PARAM_TO_COLUMN:
            break
        cols.append(_SERIES_PARAM_TO_COLUMN[param.name])
    if not cols:
        cols = ["close"]
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"history data is missing required column(s): {missing}")
    return cols, [df[c] for c in cols]


def history_window(
    lookback_bars: int = 100,
    lookback_days: int | None = None,
    interval: str = "D",
    end_date: str | None = None,
) -> tuple[str, str]:
    """Compute a (start_date, end_date) pair covering the requested lookback.

    No caller-supplied dates required — this is what lets the Flow `indicator`
    node avoid Flow JSON's lack of relative-date arithmetic (see
    docs/prompt/flow-import-format.md limitation notes).
    """
    end = end_date or date.today().isoformat()
    if lookback_days:
        start = (date.fromisoformat(end) - timedelta(days=int(lookback_days))).isoformat()
        return start, end
    bars_per_day = _BARS_PER_DAY.get(interval.lower(), 75)
    calendar_days = int((lookback_bars / bars_per_day) * 1.6) + 5
    start = (date.fromisoformat(end) - timedelta(days=calendar_days)).isoformat()
    return start, end


def _resolve_params(name: str, params: dict[str, Any] | None) -> dict[str, Any]:
    resolved = dict(params or {})
    for key, value in _REQUIRED_PARAM_DEFAULTS.get(name, {}).items():
        resolved.setdefault(key, value)
    return resolved


def _parse_timestamp(value: Any) -> datetime:
    """Normalize a history record's `timestamp` field to a naive local
    datetime. Broker adapters (confirmed for Zerodha; likely universal since
    `services/history_service.py` passes broker DataFrames straight through
    `to_dict(orient="records")`) return this as **epoch seconds**, not an
    ISO string - `datetime.fromtimestamp` converts using the server's local
    tz, which is IST in this deployment, matching `datetime.now()` elsewhere
    in this module. Falls back to ISO-string parsing for any adapter that
    does emit strings.
    """
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    text = str(value)
    try:
        return datetime.fromtimestamp(float(text))
    except (TypeError, ValueError):
        pass
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        # Convert to server-local wall time and drop tzinfo. Callers subtract
        # these from a naive datetime.now() (see _drop_forming_bar), which
        # raises TypeError on an aware operand.
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _timestamp_series(df: pd.DataFrame) -> pd.Series:
    """Like _parse_timestamp but vectorized for a DataFrame's timestamp
    column. Epoch seconds are converted UTC -> server local tz (IST in this
    deployment) to match `_parse_timestamp` and `datetime.now()`."""
    col = df["timestamp"]
    if pd.api.types.is_numeric_dtype(col):
        local_tz = datetime.now().astimezone().tzinfo
        return pd.to_datetime(col, unit="s", utc=True).dt.tz_convert(local_tz).dt.tz_localize(None)
    return pd.to_datetime(col)


# Approx minutes per bar for common interval spellings, used only to decide
# whether the most recent returned bar is still forming (see bar_at_offset).
_INTERVAL_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "10m": 10,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "60m": 60,
    "2h": 120,
    "3h": 180,
    "4h": 240,
}


def _drop_forming_bar(
    records: list[dict[str, Any]], interval: str, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Drop the last record if it looks like a still-forming (not yet
    closed) bar, so offset/index 0 reliably means "last CLOSED bar".

    Daily-and-above intervals: drop if the last bar's date is today.
    Intraday intervals: drop if the last bar started less than one full
    bar-duration ago. Unknown interval spellings are left alone (no drop) -
    better to risk including a partial bar than to wrongly discard a valid
    closed one.
    """
    if not records:
        return records
    now = now or datetime.now()
    last_ts = _parse_timestamp(records[-1].get("timestamp"))
    key = interval.strip().lower()
    if key in ("d", "1d", "day", "w", "week", "m", "month"):
        if last_ts.date() == now.date():
            return records[:-1]
        return records
    minutes = _INTERVAL_MINUTES.get(key)
    if minutes is not None and (now - last_ts) < timedelta(minutes=minutes):
        return records[:-1]
    return records


def bar_at_offset(
    records: list[dict[str, Any]],
    offset_bars: int,
    interval: str = "D",
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return the OHLCV record `offset_bars` closed bars back from the most
    recent one (0 = most recent CLOSED bar, 1 = one bar before that, ...).

    `records` must be ascending by timestamp, as returned by
    `services.history_service.get_history`.
    """
    if offset_bars < 0:
        return None
    closed = _drop_forming_bar(records, interval, now)
    if not closed:
        return None
    index = len(closed) - 1 - offset_bars
    if index < 0:
        return None
    return closed[index]


_PERIOD_TO_PANDAS_FREQ = {"previous_week": "W", "previous_month": "M"}


def prior_period_ohlc(
    records: list[dict[str, Any]], period: str, now: date | None = None
) -> dict[str, Any]:
    """Aggregate OHLCV records into the previous full hour/day/week/month.

    - `previous_day`: last daily bar whose date is before today.
    - `previous_hour`: last hourly bar whose hour bucket is before the
      current one.
    - `previous_week` / `previous_month`: aggregates every daily bar that
      falls in the most recently COMPLETED calendar week/month (high = max
      high, low = min low, close = last close, open = first open) — needed
      because "previous week's high/low" isn't a single stored bar.
    """
    if not records:
        raise ValueError("no historical data available for this symbol/date range")
    now_dt = datetime.combine(now, datetime.min.time()) if now else datetime.now()

    if period == "previous_hour":
        current_bucket = now_dt.strftime("%Y-%m-%d %H")
        closed = [
            r
            for r in records
            if _parse_timestamp(r.get("timestamp")).strftime("%Y-%m-%d %H") != current_bucket
        ]
        if not closed:
            # Falling back to records[-1] here would hand back the current,
            # still-forming candle as "previous hour" - wrong PDH/PDL/PDC.
            raise ValueError("not enough history to determine previous_hour")
        row = closed[-1]
        return {
            "period": period,
            "date": _parse_timestamp(row.get("timestamp")).strftime("%Y-%m-%d %H:%M"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "volume": row.get("volume"),
        }

    if period == "previous_day":
        today_str = now_dt.strftime("%Y-%m-%d")
        closed = [
            r
            for r in records
            if _parse_timestamp(r.get("timestamp")).strftime("%Y-%m-%d") != today_str
        ]
        if not closed:
            # Same reasoning as previous_hour: never pass today's in-progress
            # candle off as the previous day's settled OHLC.
            raise ValueError("not enough history to determine previous_day")
        row = closed[-1]
        return {
            "period": period,
            "date": _parse_timestamp(row.get("timestamp")).strftime("%Y-%m-%d"),
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "volume": row.get("volume"),
        }

    if period in _PERIOD_TO_PANDAS_FREQ:
        df = pd.DataFrame(records)
        df["ts"] = _timestamp_series(df)
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        freq = _PERIOD_TO_PANDAS_FREQ[period]
        current_bucket = pd.Timestamp(now_dt).to_period(freq)
        df["bucket"] = df["ts"].dt.to_period(freq)
        prior = df[df["bucket"] < current_bucket]
        if prior.empty:
            raise ValueError(f"not enough history to determine {period}")
        last_bucket = prior["bucket"].max()
        rows = prior[prior["bucket"] == last_bucket].sort_values("ts")
        return {
            "period": period,
            "date": str(last_bucket),
            "open": float(rows.iloc[0]["open"]),
            "high": float(rows["high"].max()),
            "low": float(rows["low"].min()),
            "close": float(rows.iloc[-1]["close"]),
            "volume": float(rows["volume"].sum()) if "volume" in rows.columns else None,
        }

    raise ValueError(
        f"unknown period '{period}' — expected previous_hour/previous_day/previous_week/previous_month"
    )


def compute_indicator(
    records: list[dict[str, Any]] | None,
    indicator_name: str,
    params: dict[str, Any] | None = None,
    inputs: list[str] | None = None,
    lookback_bars: int = 100,
    tail_bars: int = 5,
    source_series: list[float] | None = None,
) -> dict[str, Any]:
    """Compute one `ta` indicator over OHLCV records (as returned by
    `services.history_service.get_history`'s `data` field) — or, in nested
    mode, over an already-computed series from another Indicator node.

    Args:
        records: OHLCV records. Ignored (may be None/empty) when
            `source_series` is given.
        source_series: when set, run the indicator on this single numeric
            series instead of fetching OHLC(V) columns — this is what lets
            one Indicator node feed another (e.g. SMA(RSI(14), 9)). Only
            single-series indicators (the ones whose only series parameter
            is named `data`) support nesting; anything needing high/low/
            close/volume independently cannot be reconstructed from one
            already-collapsed output series.
        tail_bars: length of the returned `series` array. Fixed length is
            deliberate — Flow JSON string interpolation only supports
            positive array indices (see flow-import-format.md), so a
            caller-known-fixed-length array lets `{{ind.series[N]}}`
            address a specific historical bar deterministically.

    Returns the latest value(s), the previous bar's value(s), and a fixed-
    length recent-history tail rather than the full series, keeping the
    payload small.
    """
    name = indicator_name.strip().lower()
    if name in TWO_SERIES_INDICATORS:
        raise ValueError(
            f"'{name}' needs two independent series (a second symbol or two "
            "already-computed signals) and cannot run from a single symbol's "
            "history. Use two Indicator nodes plus a Math Expression/Var "
            "Condition node instead."
        )
    if name in UNSUPPORTED_INDICATORS:
        raise ValueError(f"'{name}' has a non-standard call shape and is not supported here.")
    fn = getattr(ta, name, None)
    if fn is None:
        raise ValueError(f"unknown indicator '{indicator_name}'")

    resolved_params = _resolve_params(name, params)

    if source_series is not None:
        if not is_single_series_indicator(name):
            raise ValueError(
                f"'{name}' takes more than one independent input series (e.g. "
                "high/low/close), so it cannot be nested on top of another "
                "indicator's single output series. Nest only single-series "
                "indicators (SMA, EMA, RSI, WMA, stdev, highest/lowest, ...)."
            )
        if len(source_series) < 2:
            raise ValueError("nested indicator needs at least 2 upstream values")
        index = pd.RangeIndex(len(source_series))
        series = pd.Series(source_series, index=index, dtype="float64")
        cols = ["data (nested)"]
        args = [series]
        df_index = index
    else:
        if not records:
            raise ValueError("no historical data available for this symbol/date range")
        df = pd.DataFrame(records)
        if "timestamp" in df.columns:
            df = df.set_index(pd.to_datetime(df["timestamp"]))
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.tail(max(int(lookback_bars), 5) + 50)
        cols, args = resolve_indicator_inputs(df, fn, inputs)
        df_index = df.index

    result = fn(*args, **resolved_params)

    out = pd.DataFrame(index=df_index)
    if isinstance(result, tuple):
        for i, series in enumerate(result):
            out[f"out{i}"] = pd.Series(list(series), index=df_index)
    else:
        out["value"] = pd.Series(list(result), index=df_index)

    def _at(offset: int) -> dict[str, float | None]:
        row: dict[str, float | None] = {}
        for col in out.columns:
            series = out[col].dropna()
            try:
                row[col] = round(float(series.iloc[offset]), 6)
            except (IndexError, ValueError, TypeError):
                row[col] = None
        return row

    n = max(int(tail_bars), 1)
    tail_series = [_at(offset) for offset in range(-n, 0)]

    return {
        "status": "success",
        "indicator": name,
        "nested": source_series is not None,
        "inputs": cols,
        "params": resolved_params,
        "outputs": list(out.columns),
        "latest": _at(-1),
        "previous": _at(-2),
        "series": tail_series,
        "bars_used": len(df_index),
    }
