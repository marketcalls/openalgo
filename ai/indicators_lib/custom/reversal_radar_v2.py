"""
# ============================================================
# INDICATOR: Reversal Radar v2
# Converted from Pine Script v6 | 2026-03-21
# Original Pine author: DashingBixby
# ============================================================
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Iterable, Optional
from urllib.parse import urlencode
from urllib.request import urlopen
import warnings

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "Reversal Radar v2"
MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\Reversal_Radar.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
DEFAULT_SESSION = "0915-1530"
DEFAULT_SYMBOL_TIMEZONE = "Asia/Kolkata"
DEFAULT_VIX_SYMBOL = "^INDIAVIX"
DEFAULT_SYMBOL = ""
DEFAULT_ENABLE_REVERSAL_DOTS = True
DEFAULT_ENABLE_SEL_REV_BASE = True
DEFAULT_ENABLE_BB_BREAK = True
DEFAULT_ENABLE_SNAP_BB = True
DEFAULT_ENABLE_ENG_BB = True
DEFAULT_ENABLE_VOL_CLIMAX = True
DEFAULT_ENABLE_FAILED_BREAK = True
DEFAULT_MIN_CONFLUENCE = 1
DEFAULT_NET_WIDTH = 1
DEFAULT_BLOCK_START = 15
DEFAULT_BLOCK_END = 10
DEFAULT_SHOW_BB = True


@dataclass
class ExternalData:
    """Container for India VIX intraday and daily-aligned inputs."""

    vix_now: pd.Series
    vix_daily_open_prev: pd.Series
    vix_daily_atr_prev: pd.Series


# -- LOADING ----------------------------------------------------------------
def _normalize_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """Replace TradingView-style numeric sentinels with NaN."""
    cleaned = df.copy()
    numeric_columns = cleaned.select_dtypes(include=[np.number]).columns
    if len(numeric_columns) > 0:
        cleaned.loc[:, numeric_columns] = cleaned.loc[:, numeric_columns].mask(
            cleaned.loc[:, numeric_columns] == MISSING_VALUE_SENTINEL,
            np.nan,
        )
    return cleaned


def _attach_timestamp_index(df: pd.DataFrame) -> pd.DataFrame:
    """Create a UTC timestamp index from `timestamp` or `datetime`."""
    indexed = df.copy()
    if isinstance(indexed.index, pd.DatetimeIndex):
        dt_index = indexed.index
    elif "timestamp" in indexed.columns:
        dt_index = pd.to_datetime(indexed["timestamp"], unit="s", utc=True)
    elif "datetime" in indexed.columns:
        dt_index = pd.to_datetime(indexed["datetime"], utc=True)
    else:
        raise ValueError(
            "Input data must provide a DatetimeIndex or a `timestamp`/`datetime` column."
        )

    indexed.index = dt_index
    indexed.index.name = "timestamp"
    return indexed.sort_index()


def load_csv_data(path: str | Path) -> pd.DataFrame:
    """Load CSV data, normalize sentinels, and attach a UTC timestamp index."""
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    raw = pd.read_csv(csv_path, low_memory=False)
    raw = _normalize_missing_values(raw)
    return _attach_timestamp_index(raw)


def _require_price_columns(df: pd.DataFrame) -> None:
    """Validate that the DataFrame contains the OHLCV columns required here."""
    missing = [column for column in REQUIRED_PRICE_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            "Input data is missing required OHLCV columns: " + ", ".join(missing)
        )


def _normalize_name(value: str) -> str:
    """Lower-case alphanumeric-only normalization for robust column matching."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _find_matching_sample_column(
    sample_df: pd.DataFrame,
    aliases: Iterable[str],
) -> Optional[str]:
    """Resolve the matching sample column for a given indicator output."""
    normalized_columns = {_normalize_name(column): column for column in sample_df.columns}
    for alias in aliases:
        alias_key = _normalize_name(alias)
        if alias_key in normalized_columns:
            return normalized_columns[alias_key]
    return None


# -- NUMERIC HELPERS --------------------------------------------------------
def _pine_sma(series: pd.Series, length: int) -> pd.Series:
    """Replicate Pine's ta.sma."""
    return series.rolling(length, min_periods=length).mean()


def _pine_stdev(series: pd.Series, length: int) -> pd.Series:
    """Replicate Pine's ta.stdev using population standard deviation."""
    return series.rolling(length, min_periods=length).std(ddof=0)


def _pine_rma(series: pd.Series, length: int) -> pd.Series:
    """Replicate Pine's Wilder RMA exactly."""
    out = pd.Series(np.nan, index=series.index, dtype=float)
    if len(series) < length:
        return out
    out.iloc[length - 1] = series.iloc[:length].mean()
    alpha = 1.0 / length
    for i in range(length, len(series)):
        prev = out.iloc[i - 1]
        out.iloc[i] = alpha * series.iloc[i] + (1.0 - alpha) * prev
    return out


def _pine_true_range(df: pd.DataFrame) -> pd.Series:
    """Replicate ta.tr."""
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close_prev = df["close"].astype(float).shift(1)
    return pd.concat(
        [
            high - low,
            (high - close_prev).abs(),
            (low - close_prev).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _pine_atr(df: pd.DataFrame, length: int) -> pd.Series:
    """Replicate ta.atr via Wilder RMA of true range."""
    return _pine_rma(_pine_true_range(df), length)


def _pine_rsi(source: pd.Series, length: int) -> pd.Series:
    """Replicate ta.rsi via Wilder RMA."""
    delta = source.diff()
    up = _pine_rma(delta.clip(lower=0.0), length)
    down = _pine_rma((-delta.clip(upper=0.0)), length)
    out = pd.Series(np.nan, index=source.index, dtype=float)
    out[(down == 0) & down.notna()] = 100.0
    out[(up == 0) & down.notna()] = 0.0
    mask = (up != 0) & (down != 0)
    out.loc[mask] = 100.0 - (100.0 / (1.0 + up.loc[mask] / down.loc[mask]))
    return out


def _pine_crossover(a: pd.Series, b: pd.Series | float) -> pd.Series:
    """Replicate ta.crossover."""
    if isinstance(b, pd.Series):
        return (a > b) & (a.shift(1) <= b.shift(1))
    return (a > b) & (a.shift(1) <= b)


def _pine_crossunder(a: pd.Series, b: pd.Series | float) -> pd.Series:
    """Replicate ta.crossunder."""
    if isinstance(b, pd.Series):
        return (a < b) & (a.shift(1) >= b.shift(1))
    return (a < b) & (a.shift(1) >= b)


def _highestbars_negative(series: pd.Series, length: int) -> pd.Series:
    """
    Replicate ta.highestbars(series, length) returning 0 or a negative bars-back offset.

    Ties resolve to the most recent occurrence.
    """
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    for i in range(length - 1, len(values)):
        window = values[i - length + 1 : i + 1]
        if np.isnan(window).all():
            continue
        max_value = np.nanmax(window)
        latest_idx = np.where(window == max_value)[0][-1]
        bars_back = (length - 1) - latest_idx
        out[i] = -float(bars_back)
    return pd.Series(out, index=series.index, dtype=float)


def _lowestbars_negative(series: pd.Series, length: int) -> pd.Series:
    """Replicate ta.lowestbars(series, length) returning 0 or a negative bars-back offset."""
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    for i in range(length - 1, len(values)):
        window = values[i - length + 1 : i + 1]
        if np.isnan(window).all():
            continue
        min_value = np.nanmin(window)
        latest_idx = np.where(window == min_value)[0][-1]
        bars_back = (length - 1) - latest_idx
        out[i] = -float(bars_back)
    return pd.Series(out, index=series.index, dtype=float)


def _pine_pivothigh(series: pd.Series, left: int, right: int) -> pd.Series:
    """Replicate ta.pivothigh(series, left, right) on confirmation bars."""
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    for i in range(left + right, len(values)):
        pivot_idx = i - right
        window = values[pivot_idx - left : pivot_idx + right + 1]
        if np.isnan(window).any():
            continue
        pivot_value = values[pivot_idx]
        if pivot_value == np.max(window):
            right_window = values[pivot_idx + 1 : pivot_idx + right + 1]
            if np.all(right_window < pivot_value) or right == 0:
                out[i] = pivot_value
    return pd.Series(out, index=series.index, dtype=float)


def _pine_pivotlow(series: pd.Series, left: int, right: int) -> pd.Series:
    """Replicate ta.pivotlow(series, left, right) on confirmation bars."""
    values = series.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    for i in range(left + right, len(values)):
        pivot_idx = i - right
        window = values[pivot_idx - left : pivot_idx + right + 1]
        if np.isnan(window).any():
            continue
        pivot_value = values[pivot_idx]
        if pivot_value == np.min(window):
            right_window = values[pivot_idx + 1 : pivot_idx + right + 1]
            if np.all(right_window > pivot_value) or right == 0:
                out[i] = pivot_value
    return pd.Series(out, index=series.index, dtype=float)


def _rolling_signal_window(signal: pd.Series, window: int) -> pd.Series:
    """Return True when the signal is true on the current bar or within `window` bars back."""
    out = signal.astype(bool).copy()
    for i in range(1, window + 1):
        out = out | signal.shift(i, fill_value=False).astype(bool)
    return out


def _parse_session_string(session_str: str) -> tuple[int, int, int, int]:
    """Parse TradingView-style HHMM-HHMM session strings."""
    if len(session_str) != 9 or "-" not in session_str:
        raise ValueError(f"Unsupported session string: {session_str!r}")
    start_h = int(session_str[0:2])
    start_m = int(session_str[2:4])
    end_h = int(session_str[5:7])
    end_m = int(session_str[7:9])
    return start_h, start_m, end_h, end_m


def _infer_timeframe_minutes(index: pd.DatetimeIndex) -> int:
    """Infer the dominant timeframe in minutes from the timestamp index."""
    if len(index) < 2:
        return 60
    diffs = index.to_series().diff().dropna()
    if diffs.empty:
        return 60
    minutes = int(round(diffs.dt.total_seconds().median() / 60.0))
    return max(minutes, 1)


def _yahoo_interval_from_minutes(minutes: int) -> str:
    """Map a minute timeframe to a Yahoo chart interval."""
    mapping = {
        1: "1m",
        2: "2m",
        5: "5m",
        15: "15m",
        30: "30m",
        60: "60m",
        90: "90m",
        120: "60m",
        240: "60m",
        1440: "1d",
    }
    if minutes in mapping:
        return mapping[minutes]
    if minutes < 5:
        return "1m"
    if minutes < 15:
        return "5m"
    if minutes < 30:
        return "15m"
    if minutes < 60:
        return "30m"
    if minutes < 1440:
        return "60m"
    return "1d"


def _fetch_yahoo_chart(symbol: str, interval: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Fetch OHLCV data from Yahoo's chart endpoint."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware UTC timestamps.")
    params = {
        "period1": int(start.timestamp()),
        "period2": int(end.timestamp()),
        "interval": interval,
        "includePrePost": "true",
        "events": "div,splits",
    }
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + symbol + "?" + urlencode(params)
    with urlopen(url, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))

    result = payload["chart"]["result"][0]
    timestamps = result.get("timestamp", []) or []
    quote = result["indicators"]["quote"][0]
    frame = pd.DataFrame(
        {
            "open": quote.get("open", []),
            "high": quote.get("high", []),
            "low": quote.get("low", []),
            "close": quote.get("close", []),
            "volume": quote.get("volume", []),
        },
        index=pd.to_datetime(timestamps, unit="s", utc=True),
    )
    frame.index.name = "timestamp"
    return frame.sort_index()


def _align_daily_prev_series(
    daily_series: pd.Series,
    base_index: pd.DatetimeIndex,
    daily_timezone: str,
) -> pd.Series:
    """Map prior-completed daily values onto intraday bars using local daily boundaries."""
    base_local_dates = base_index.tz_convert(daily_timezone).normalize()
    aligned = pd.Series(np.nan, index=base_index, dtype=float)
    daily_index_dates = daily_series.index.tz_convert(daily_timezone).normalize()
    mapper = pd.Series(daily_series.to_numpy(dtype=float), index=daily_index_dates)
    prev_dates = pd.Series(base_local_dates, index=base_index).map(
        lambda ts: ts - pd.Timedelta(days=1)
    )
    aligned.loc[:] = prev_dates.map(mapper).to_numpy()
    return aligned


def _compute_daily_prev_atr_and_close(
    df: pd.DataFrame,
    exchange_tz: str,
) -> tuple[pd.Series, pd.Series]:
    """Compute previous completed daily ATR(14) and close for the base symbol."""
    local = df.tz_convert(exchange_tz)
    daily_ohlcv = pd.DataFrame(
        {
            "open": local["open"].resample("1D").first(),
            "high": local["high"].resample("1D").max(),
            "low": local["low"].resample("1D").min(),
            "close": local["close"].resample("1D").last(),
            "volume": local["volume"].resample("1D").sum(),
        }
    ).dropna(subset=["open", "high", "low", "close"])
    daily_ohlcv.index = daily_ohlcv.index.tz_convert("UTC")
    daily_atr = _pine_atr(daily_ohlcv, 14)
    daily_close = daily_ohlcv["close"].astype(float)
    daily_atr_prev = _align_daily_prev_series(daily_atr, df.index, exchange_tz)
    daily_close_prev = _align_daily_prev_series(daily_close, df.index, exchange_tz)
    return daily_atr_prev, daily_close_prev


def load_external_data(
    base_df: pd.DataFrame,
    vix_symbol: str = DEFAULT_VIX_SYMBOL,
    exchange_tz: str = DEFAULT_SYMBOL_TIMEZONE,
) -> ExternalData:
    """
    Fetch India VIX intraday and daily data aligned to the base DataFrame.

    If fetches fail, this raises an exception. Callers that want a softer fallback
    should catch exceptions and substitute NaN series.
    """
    base_index = base_df.index
    timeframe_minutes = _infer_timeframe_minutes(base_index)
    intraday_interval = _yahoo_interval_from_minutes(timeframe_minutes)
    start = (base_index.min() - pd.Timedelta(days=40)).tz_convert("UTC")
    end = (base_index.max() + pd.Timedelta(days=5)).tz_convert("UTC")

    vix_intraday = _fetch_yahoo_chart(vix_symbol, intraday_interval, start, end)
    vix_daily = _fetch_yahoo_chart(vix_symbol, "1d", start - pd.Timedelta(days=120), end)

    vix_now = vix_intraday["close"].astype(float).reindex(base_index).ffill()
    vix_daily_open_prev = _align_daily_prev_series(
        vix_daily["open"].astype(float), base_index, exchange_tz
    )
    vix_daily_atr_prev = _align_daily_prev_series(
        _pine_atr(vix_daily, 14), base_index, exchange_tz
    )
    return ExternalData(
        vix_now=vix_now,
        vix_daily_open_prev=vix_daily_open_prev,
        vix_daily_atr_prev=vix_daily_atr_prev,
    )


def _empty_external_data(index: pd.DatetimeIndex) -> ExternalData:
    """Return NaN-filled external data placeholders."""
    empty = pd.Series(np.nan, index=index, dtype=float)
    return ExternalData(vix_now=empty.copy(), vix_daily_open_prev=empty.copy(), vix_daily_atr_prev=empty.copy())


def _detect_is_index(symbol: str) -> bool:
    """Replicate the Pine index-symbol detection logic approximately."""
    normalized = symbol.upper()
    if normalized in {"SPX", "NDX", "RUT", "DJX", "VIX"}:
        return True
    return any(tag in normalized for tag in (":SPX", ":NDX", ":RUT", ":DJX"))


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    external_data: Optional[ExternalData] = None,
    symbol: str = DEFAULT_SYMBOL,
    exchange_tz: str = DEFAULT_SYMBOL_TIMEZONE,
    sess_str: str = DEFAULT_SESSION,
    enable_reversal_dots: bool = DEFAULT_ENABLE_REVERSAL_DOTS,
    enable_sel_rev_base: bool = DEFAULT_ENABLE_SEL_REV_BASE,
    enable_bb_break: bool = DEFAULT_ENABLE_BB_BREAK,
    enable_snap_bb: bool = DEFAULT_ENABLE_SNAP_BB,
    enable_eng_bb: bool = DEFAULT_ENABLE_ENG_BB,
    enable_vol_climax: bool = DEFAULT_ENABLE_VOL_CLIMAX,
    enable_failed_break: bool = DEFAULT_ENABLE_FAILED_BREAK,
    min_confluence: int = DEFAULT_MIN_CONFLUENCE,
    net_width: int = DEFAULT_NET_WIDTH,
    block_start: int = DEFAULT_BLOCK_START,
    block_end: int = DEFAULT_BLOCK_END,
    show_bb: bool = DEFAULT_SHOW_BB,
    allow_external_fetch: bool = True,
) -> pd.DataFrame:
    """
    Replicate the Reversal Radar v2 indicator.

    This is an indicator-only port. It preserves NSE session gating and India VIX-
    based filters. All visual constructs are reduced to numeric export columns.
    """
    del show_bb
    _require_price_columns(df)
    working = df.copy().sort_index()

    open_ = working["open"].astype(float)
    high = working["high"].astype(float)
    low = working["low"].astype(float)
    close = working["close"].astype(float)
    volume = working["volume"].astype(float)

    start_h, start_m, end_h, end_m = _parse_session_string(sess_str)
    local_index = working.index.tz_convert(exchange_tz)
    local_hour = pd.Series(local_index.hour, index=working.index)
    local_minute = pd.Series(local_index.minute, index=working.index)
    curr_mins = local_hour * 60 + local_minute
    in_session = (
        (curr_mins >= (start_h * 60 + start_m))
        & (curr_mins < (end_h * 60 + end_m))
    )
    limit_start_mins = (start_h * 60 + start_m) + block_start
    limit_end_mins = (end_h * 60 + end_m) - block_end
    time_ok = in_session & (curr_mins >= limit_start_mins) & (curr_mins < limit_end_mins)

    base_local_dates = working.index.tz_convert(exchange_tz).normalize()
    new_day = pd.Series(base_local_dates, index=working.index).ne(
        pd.Series(base_local_dates, index=working.index).shift(1)
    )
    new_day.iloc[0] = True

    atr14 = _pine_atr(working, 14)
    bb_basis = _pine_sma(close, 20)
    bb_dev = _pine_stdev(close, 20) * 2.0
    bb_upper = bb_basis + bb_dev
    bb_lower = bb_basis - bb_dev

    if external_data is None:
        if bool(in_session.any()) and allow_external_fetch:
            try:
                external_data = load_external_data(working, exchange_tz=exchange_tz)
            except Exception as exc:  # pragma: no cover
                warnings.warn(
                    f"External India VIX fetch failed ({exc}). Continuing with NaN external series; "
                    "India VIX-dependent detectors will remain inactive."
                )
                external_data = _empty_external_data(working.index)
        else:
            external_data = _empty_external_data(working.index)

    vix_daily_open = external_data.vix_daily_open_prev.reindex(working.index)
    vix_daily_atr = external_data.vix_daily_atr_prev.reindex(working.index)
    vix_now = external_data.vix_now.reindex(working.index)
    daily_atr, daily_close = _compute_daily_prev_atr_and_close(working, exchange_tz)
    is_index = _detect_is_index(symbol)

    rd_pivot_left = 5 if net_width == 1 else 4 if net_width == 2 else 3
    rd_pivot_right = 3 if net_width == 1 else 2
    rd_wick_ratio = 0.43 if net_width == 1 else 0.35 if net_width == 2 else 0.28
    rd_trap_bars = 6 if net_width == 1 else 5 if net_width == 2 else 4
    rd_cooldown_bars = 5 if net_width == 1 else 4 if net_width == 2 else 3
    rd_candle_range = high - low
    rd_upper_wick = high - np.maximum(open_, close)
    rd_lower_wick = np.minimum(open_, close) - low
    rd_ph = _pine_pivothigh(high, rd_pivot_left, rd_pivot_right)
    rd_pl = _pine_pivotlow(low, rd_pivot_left, rd_pivot_right)
    rd_is_bear_wick = (rd_upper_wick / rd_candle_range.replace(0.0, np.nan)) >= rd_wick_ratio
    rd_is_bull_wick = (rd_lower_wick / rd_candle_range.replace(0.0, np.nan)) >= rd_wick_ratio
    rd_prev_greens = (close > open_).astype(int).rolling(rd_trap_bars, min_periods=rd_trap_bars).sum()
    rd_prev_reds = (close < open_).astype(int).rolling(rd_trap_bars, min_periods=rd_trap_bars).sum()
    rd_trap_bear = rd_prev_greens.shift(1) == rd_trap_bars
    rd_trap_bull = rd_prev_reds.shift(1) == rd_trap_bars
    rd_bear_color = close < open_
    rd_bull_color = close > open_
    rd_prev_was_high = high.shift(1) == high.rolling(rd_pivot_left, min_periods=rd_pivot_left).max().shift(1)
    rd_prev_was_low = low.shift(1) == low.rolling(rd_pivot_left, min_periods=rd_pivot_left).min().shift(1)
    rd_follow_bear = rd_prev_was_high & rd_bear_color & rd_is_bear_wick & rd_trap_bear
    rd_follow_bull = rd_prev_was_low & rd_bull_color & rd_is_bull_wick & rd_trap_bull
    rd_valid_bear_pivot = rd_ph.notna() & rd_is_bear_wick.shift(rd_pivot_right, fill_value=False) & rd_bear_color.shift(rd_pivot_right, fill_value=False)
    rd_valid_bull_pivot = rd_pl.notna() & rd_is_bull_wick.shift(rd_pivot_right, fill_value=False) & rd_bull_color.shift(rd_pivot_right, fill_value=False)

    srb_pivot_left = 3 if net_width == 1 else 2
    srb_pivot_right = 2 if net_width == 1 else 1
    srb_structure_lookback = 60 if net_width == 1 else 50 if net_width == 2 else 40
    srb_cooldown_bars = 5 if net_width == 1 else 4 if net_width == 2 else 3
    srb_band_touch_buffer = 1.0 if net_width == 1 else 1.001 if net_width == 2 else 1.002
    srb_rsi = _pine_rsi(close, 14)
    srb_pivot_high = _pine_pivothigh(high, srb_pivot_left, srb_pivot_right)
    srb_pivot_low = _pine_pivotlow(low, srb_pivot_left, srb_pivot_right)
    srb_pivot_high_found = srb_pivot_high.notna()
    srb_pivot_low_found = srb_pivot_low.notna()
    srb_bod_filter = max(block_start, 10)
    srb_eod_filter = max(block_end, 5)
    srb_limit_start_mins = (start_h * 60 + start_m) + srb_bod_filter
    srb_limit_end_mins = (end_h * 60 + end_m) - srb_eod_filter
    srb_time_ok = in_session & (curr_mins >= srb_limit_start_mins) & (curr_mins < srb_limit_end_mins)

    bb_cooldown_bars = 5 if net_width == 1 else 4 if net_width == 2 else 3
    bb_min_band_width_pct = 0.3 if net_width == 1 else 0.24 if net_width == 2 else 0.19
    bb_slope_threshold = 45.0 if net_width == 1 else 54.0 if net_width == 2 else 65.0
    bb_min_wick_percent = 75.0 if net_width == 1 else 60.0 if net_width == 2 else 48.0
    bb_band_width = bb_upper - bb_lower
    bb_band_width_percent = (bb_band_width / close) * 100.0
    bb_band_width_ok = bb_band_width_percent >= bb_min_band_width_pct
    bb_upper_slope = (bb_upper - bb_upper.shift(3)) / 3.0
    bb_lower_slope = (bb_lower - bb_lower.shift(3)) / 3.0
    bb_upper_slope_degrees = np.degrees(np.arctan(bb_upper_slope / atr14))
    bb_lower_slope_degrees = np.degrees(np.arctan(bb_lower_slope / atr14))
    bb_bearish_slope_ok = bb_upper_slope_degrees < bb_slope_threshold
    bb_bullish_slope_ok = bb_lower_slope_degrees > -bb_slope_threshold
    bb_body_high = np.maximum(open_, close)
    bb_body_low = np.minimum(open_, close)
    bb_top_wick_ratio = np.where(rd_candle_range > 0, ((high - bb_body_high) / rd_candle_range) * 100.0, 0.0)
    bb_bot_wick_ratio = np.where(rd_candle_range > 0, ((bb_body_low - low) / rd_candle_range) * 100.0, 0.0)
    bb_short_signal_raw = (open_ > bb_upper) & (close > bb_upper) & (bb_top_wick_ratio >= bb_min_wick_percent) & bb_bearish_slope_ok & bb_band_width_ok
    bb_long_signal_raw = (open_ < bb_lower) & (close < bb_lower) & (bb_bot_wick_ratio >= bb_min_wick_percent) & bb_bullish_slope_ok & bb_band_width_ok

    snap_vix_fib_level = 0.618 if net_width == 1 else 0.5 if net_width == 2 else 0.4
    snap_snap_min_bars = 4 if net_width == 1 else 3 if net_width == 2 else 2
    snap_snap_body_ratio = 0.65 if net_width == 1 else 0.52 if net_width == 2 else 0.42
    snap_max_recovery_atr = 1.0 if net_width == 1 else 1.2 if net_width == 2 else 1.44
    snap_cooldown_bars = 10 if net_width == 1 else 8 if net_width == 2 else 6
    snap_vix_threshold = vix_daily_open + (vix_daily_atr * snap_vix_fib_level)
    snap_in_vix_zone = vix_now >= snap_vix_threshold
    snap_lower_low_count = pd.Series(0, index=working.index, dtype=int)
    for offset in range(1, 6):
        snap_lower_low_count = snap_lower_low_count + (low.shift(offset) < low.shift(offset + 1)).astype(int)
    snap_prior_bars_downtrend = snap_lower_low_count >= snap_snap_min_bars
    snap_current_body_ratio = np.where((high - low) > 0, (close - open_).abs() / (high - low), 0.0)
    snap_five_bar_snap_bull = (close > open_) & (snap_current_body_ratio >= snap_snap_body_ratio) & snap_prior_bars_downtrend
    snap_bb_touch_in_window = _rolling_signal_window((low <= bb_lower).fillna(False), 1)
    session_start_mins = start_h * 60 + start_m
    session_end_mins = end_h * 60 + end_m
    snap_mins_since_open = curr_mins - session_start_mins
    snap_mins_until_close = session_end_mins - curr_mins
    snap_time_ok = in_session & ~(((snap_mins_since_open >= 0) & (snap_mins_since_open < 0))) & ~(((snap_mins_until_close >= 0) & (snap_mins_until_close < 31)))

    eng_vix_fib_level = 1.0 if net_width == 1 else 0.8 if net_width == 2 else 0.64
    eng_bb_pen_min_pct = 50.0 if net_width == 1 else 40.0 if net_width == 2 else 32.0
    eng_bb_slope_atr_mult = 0.02 if net_width == 1 else 0.016 if net_width == 2 else 0.013
    eng_cooldown_bars = 10 if net_width == 1 else 8 if net_width == 2 else 6
    eng_vix_threshold = vix_daily_open + (vix_daily_atr * eng_vix_fib_level)
    eng_in_vix_zone = vix_now >= eng_vix_threshold
    eng_bb_touch_in_window = _rolling_signal_window((low <= bb_lower).fillna(False), 4)
    eng_bb_slope_raw = (bb_lower - bb_lower.shift(5)) / 5.0
    eng_slope_threshold = -(atr14 * eng_bb_slope_atr_mult)
    eng_bb_slope_in_window = _rolling_signal_window((eng_bb_slope_raw <= eng_slope_threshold).fillna(False), 4)
    eng_prior_body_high = np.maximum(open_.shift(1), close.shift(1))
    eng_prior_body_low = np.minimum(open_.shift(1), close.shift(1))
    eng_bullish_engulfing = (close > open_) & (close.shift(1) < open_.shift(1)) & (close >= eng_prior_body_high) & (open_ <= eng_prior_body_low)
    eng_mins_since_open = curr_mins - session_start_mins
    eng_mins_until_close = session_end_mins - curr_mins
    eng_time_ok = in_session & ~(eng_mins_since_open.between(0, 19)) & ~(eng_mins_until_close.between(0, 19))

    vc_vol_spike_mult = 2.4 if net_width == 1 else 1.9 if net_width == 2 else 1.5
    vc_min_candle_atr = 1.0 if net_width == 1 else 0.8 if net_width == 2 else 0.64
    vc_cooldown_bars = 3 if net_width == 1 else 2
    vc_block_end = 25 if net_width == 1 else 20 if net_width == 2 else 16
    vc_vol_ma = _pine_sma(volume, 16)
    vc_time_ok = in_session & (curr_mins >= limit_start_mins) & ((session_end_mins - curr_mins) >= vc_block_end)
    vc_prev_vol_spike = volume.shift(1) >= (vc_vol_ma.shift(1) * vc_vol_spike_mult)
    vc_prev_big_candle = (high.shift(1) - low.shift(1)) >= (atr14.shift(1) * vc_min_candle_atr)
    vc_bearish_climax = (close.shift(1) < open_.shift(1)) & vc_prev_vol_spike & vc_prev_big_candle
    vc_bullish_climax = (close.shift(1) > open_.shift(1)) & vc_prev_vol_spike & vc_prev_big_candle

    fb_max_bars_confirm = 3 if net_width == 1 else 4 if net_width == 2 else 5
    fb_cooldown_bars = 5 if net_width == 1 else 4 if net_width == 2 else 3
    fb_track_pmhl = not is_index
    fb_preopen_start_mins = max(0, session_start_mins - 15)
    fb_is_preopen = (curr_mins >= fb_preopen_start_mins) & (curr_mins < session_start_mins)
    fb_is_rth = in_session
    fb_rth_just_opened = fb_is_rth & ~fb_is_rth.shift(1, fill_value=False)
    fb_minutes_since_open = (curr_mins - session_start_mins).clip(lower=0)

    n = len(working)
    rd_bear_signal = np.zeros(n, dtype=bool)
    rd_bull_signal = np.zeros(n, dtype=bool)
    srb_short_signal = np.zeros(n, dtype=bool)
    srb_long_signal = np.zeros(n, dtype=bool)
    bb_short_signal = np.zeros(n, dtype=bool)
    bb_long_signal = np.zeros(n, dtype=bool)
    snap_long_signal = np.zeros(n, dtype=bool)
    eng_long_signal = np.zeros(n, dtype=bool)
    vc_long_signal = np.zeros(n, dtype=bool)
    vc_short_signal = np.zeros(n, dtype=bool)
    fb_long_signal = np.zeros(n, dtype=bool)
    fb_short_signal = np.zeros(n, dtype=bool)

    snap_session_low = np.nan
    rd_last_bear_bar = 0
    rd_last_bull_bar = 0
    srb_last_short_bar = 0
    srb_last_long_bar = 0
    bb_last_short_bar = 0
    bb_last_long_bar = 0
    snap_last_long_bar = 0
    eng_last_long_bar = 0
    vc_last_signal_bar = -999
    fb_break_level_id = -1
    fb_break_direction = 0
    fb_break_bar = 0
    fb_break_level_value = np.nan
    fb_last_signal_bar = -999
    fb_pdh = np.nan
    fb_pdl = np.nan
    fb_prev_day_high = np.nan
    fb_prev_day_low = np.nan
    fb_curr_day_high = np.nan
    fb_curr_day_low = np.nan
    fb_pmh = np.nan
    fb_pml = np.nan
    fb_pmh_building = np.nan
    fb_pml_building = np.nan
    fb_hod = np.nan
    fb_lod = np.nan
    fb_vwap_sum = 0.0
    fb_vwap_vol_sum = 0.0
    fb_vwap_value = np.nan
    fb_or_high = np.nan
    fb_or_low = np.nan
    fb_or_complete = False
    srb_major_high_price = np.full(n, np.nan, dtype=float)
    srb_major_low_price = np.full(n, np.nan, dtype=float)

    for i in range(n):
        if bool(new_day.iloc[i]):
            snap_session_low = float(low.iloc[i])
        else:
            snap_session_low = min(snap_session_low, float(low.iloc[i])) if not np.isnan(snap_session_low) else float(low.iloc[i])

        if enable_reversal_dots and bool(time_ok.iloc[i]) and (i - rd_last_bear_bar) >= rd_cooldown_bars and bool((rd_valid_bear_pivot | rd_follow_bear).iloc[i]):
            rd_bear_signal[i] = True
            rd_last_bear_bar = i
        if enable_reversal_dots and bool(time_ok.iloc[i]) and (i - rd_last_bull_bar) >= rd_cooldown_bars and bool((rd_valid_bull_pivot | rd_follow_bull).iloc[i]):
            rd_bull_signal[i] = True
            rd_last_bull_bar = i

        if srb_pivot_high_found.iloc[i]:
            pivot_idx = i - srb_pivot_right
            end_idx = i - (srb_pivot_right + 1)
            start_idx = end_idx - srb_structure_lookback + 1
            if start_idx >= 0 and pivot_idx >= 0 and end_idx >= start_idx:
                segment = high.iloc[start_idx : end_idx + 1].to_numpy(dtype=float)
                if not np.isnan(segment).all():
                    max_value = np.nanmax(segment)
                    chosen = start_idx + int(np.where(segment == max_value)[0][-1])
                    srb_major_high_price[i] = float(high.iloc[chosen])
                    current_pivot_high = float(high.iloc[pivot_idx])
                    band_touch_short = not np.isnan(bb_upper.iloc[pivot_idx]) and current_pivot_high >= float(bb_upper.iloc[pivot_idx]) * (2.0 - srb_band_touch_buffer)
                    srb_short_raw = current_pivot_high >= max_value and band_touch_short
                    if enable_sel_rev_base and bool(srb_time_ok.iloc[i]) and srb_short_raw and (i - srb_last_short_bar) >= srb_cooldown_bars:
                        srb_short_signal[i] = True
                        srb_last_short_bar = i

        if srb_pivot_low_found.iloc[i]:
            pivot_idx = i - srb_pivot_right
            end_idx = i - (srb_pivot_right + 1)
            start_idx = end_idx - srb_structure_lookback + 1
            if start_idx >= 0 and pivot_idx >= 0 and end_idx >= start_idx:
                segment = low.iloc[start_idx : end_idx + 1].to_numpy(dtype=float)
                if not np.isnan(segment).all():
                    min_value = np.nanmin(segment)
                    chosen = start_idx + int(np.where(segment == min_value)[0][-1])
                    srb_major_low_price[i] = float(low.iloc[chosen])
                    current_pivot_low = float(low.iloc[pivot_idx])
                    band_touch_long = not np.isnan(bb_lower.iloc[pivot_idx]) and current_pivot_low <= float(bb_lower.iloc[pivot_idx]) * srb_band_touch_buffer
                    srb_long_raw = current_pivot_low <= min_value and band_touch_long
                    if enable_sel_rev_base and bool(srb_time_ok.iloc[i]) and srb_long_raw and (i - srb_last_long_bar) >= srb_cooldown_bars:
                        srb_long_signal[i] = True
                        srb_last_long_bar = i

        if enable_bb_break and bool(time_ok.iloc[i]) and (i - bb_last_short_bar) >= bb_cooldown_bars and bool(bb_short_signal_raw.iloc[i]):
            bb_short_signal[i] = True
            bb_last_short_bar = i
        if enable_bb_break and bool(time_ok.iloc[i]) and (i - bb_last_long_bar) >= bb_cooldown_bars and bool(bb_long_signal_raw.iloc[i]):
            bb_long_signal[i] = True
            bb_last_long_bar = i

        recovery_from_low = 0.0
        if not np.isnan(daily_atr.iloc[i]) and daily_atr.iloc[i] > 0 and not np.isnan(snap_session_low):
            recovery_from_low = (float(close.iloc[i]) - snap_session_low) / float(daily_atr.iloc[i])
        snap_long_raw = bool(
            snap_bb_touch_in_window.iloc[i]
            and snap_in_vix_zone.iloc[i]
            and snap_five_bar_snap_bull.iloc[i]
            and recovery_from_low <= snap_max_recovery_atr
        )
        if enable_snap_bb and bool(snap_time_ok.iloc[i]) and snap_long_raw and (i - snap_last_long_bar) >= snap_cooldown_bars:
            snap_long_signal[i] = True
            snap_last_long_bar = i

        def _eng_body_penetration(row_idx: int) -> float:
            if row_idx < 0 or np.isnan(bb_lower.iloc[row_idx]):
                return 0.0
            body_high = max(float(open_.iloc[row_idx]), float(close.iloc[row_idx]))
            body_low = min(float(open_.iloc[row_idx]), float(close.iloc[row_idx]))
            body_size = body_high - body_low
            if body_size <= 0:
                return 0.0
            bb_val = float(bb_lower.iloc[row_idx])
            if body_high <= bb_val:
                return 100.0
            if body_low >= bb_val:
                return 0.0
            return ((bb_val - body_low) / body_size) * 100.0

        eng_penetrations = [_eng_body_penetration(i - off) for off in range(5)]
        eng_long_raw = bool(
            eng_bb_touch_in_window.iloc[i]
            and any(pen >= eng_bb_pen_min_pct for pen in eng_penetrations)
            and eng_bb_slope_in_window.iloc[i]
            and eng_in_vix_zone.iloc[i]
            and eng_bullish_engulfing.iloc[i]
        )
        if enable_eng_bb and bool(eng_time_ok.iloc[i]) and eng_long_raw and (i - eng_last_long_bar) >= eng_cooldown_bars:
            eng_long_signal[i] = True
            eng_last_long_bar = i

        if enable_vol_climax and bool(vc_time_ok.iloc[i]) and (i - vc_last_signal_bar) >= vc_cooldown_bars:
            if bool(vc_bearish_climax.iloc[i]) and bool((close > open_).iloc[i]):
                vc_long_signal[i] = True
                vc_last_signal_bar = i
            if bool(vc_bullish_climax.iloc[i]) and bool((close < open_).iloc[i]):
                vc_short_signal[i] = True
                vc_last_signal_bar = i

        if bool(new_day.iloc[i]):
            fb_prev_day_high = fb_curr_day_high
            fb_prev_day_low = fb_curr_day_low
            fb_curr_day_high = float(high.iloc[i])
            fb_curr_day_low = float(low.iloc[i])
            fb_pdh = fb_prev_day_high
            fb_pdl = fb_prev_day_low
            fb_pmh_building = np.nan
            fb_pml_building = np.nan
            fb_pmh = np.nan
            fb_pml = np.nan
            fb_vwap_sum = 0.0
            fb_vwap_vol_sum = 0.0
        else:
            fb_curr_day_high = max(fb_curr_day_high if not np.isnan(fb_curr_day_high) else float(high.iloc[i]), float(high.iloc[i]))
            fb_curr_day_low = min(fb_curr_day_low if not np.isnan(fb_curr_day_low) else float(low.iloc[i]), float(low.iloc[i]))

        if fb_track_pmhl:
            if bool(fb_is_preopen.iloc[i]):
                fb_pmh_building = float(high.iloc[i]) if np.isnan(fb_pmh_building) else max(fb_pmh_building, float(high.iloc[i]))
                fb_pml_building = float(low.iloc[i]) if np.isnan(fb_pml_building) else min(fb_pml_building, float(low.iloc[i]))
            if bool(fb_rth_just_opened.iloc[i]):
                fb_pmh = fb_pmh_building
                fb_pml = fb_pml_building

        if bool(fb_rth_just_opened.iloc[i]):
            fb_hod = float(high.iloc[i])
            fb_lod = float(low.iloc[i])
        elif bool(fb_is_rth.iloc[i]):
            fb_hod = float(high.iloc[i]) if np.isnan(fb_hod) else max(fb_hod, float(high.iloc[i]))
            fb_lod = float(low.iloc[i]) if np.isnan(fb_lod) else min(fb_lod, float(low.iloc[i]))

        if bool(fb_rth_just_opened.iloc[i]) or bool(new_day.iloc[i]):
            fb_vwap_sum = 0.0
            fb_vwap_vol_sum = 0.0
            fb_vwap_value = np.nan
        if bool(fb_is_rth.iloc[i]):
            typical_price = (float(high.iloc[i]) + float(low.iloc[i]) + float(close.iloc[i])) / 3.0
            fb_vwap_sum += typical_price * float(volume.iloc[i])
            fb_vwap_vol_sum += float(volume.iloc[i])
            fb_vwap_value = fb_vwap_sum / fb_vwap_vol_sum if fb_vwap_vol_sum > 0 else np.nan

        if bool(fb_rth_just_opened.iloc[i]):
            fb_or_high = float(high.iloc[i])
            fb_or_low = float(low.iloc[i])
            fb_or_complete = False
        elif bool(fb_is_rth.iloc[i]) and not fb_or_complete:
            if float(fb_minutes_since_open.iloc[i]) < 15:
                fb_or_high = float(high.iloc[i]) if np.isnan(fb_or_high) else max(fb_or_high, float(high.iloc[i]))
                fb_or_low = float(low.iloc[i]) if np.isnan(fb_or_low) else min(fb_or_low, float(low.iloc[i]))
            else:
                fb_or_complete = True

        if (i - fb_break_bar) > fb_max_bars_confirm:
            fb_break_level_id = -1
            fb_break_direction = 0
        fb_detect_new_break = fb_break_level_id == -1 or (i - fb_break_bar) > fb_max_bars_confirm
        if fb_detect_new_break and bool(time_ok.iloc[i]) and i > 0:
            prior_close = float(close.iloc[i - 1])

            def _break_above(level: float) -> bool:
                return (not np.isnan(level)) and (float(close.iloc[i]) > level) and (prior_close <= level)

            def _break_below(level: float) -> bool:
                return (not np.isnan(level)) and (float(close.iloc[i]) < level) and (prior_close >= level)

            if (not np.isnan(fb_pdh)) and _break_above(fb_pdh):
                fb_break_level_id, fb_break_direction, fb_break_bar, fb_break_level_value = 0, 1, i, fb_pdh
            elif (not np.isnan(fb_pdl)) and _break_below(fb_pdl):
                fb_break_level_id, fb_break_direction, fb_break_bar, fb_break_level_value = 1, -1, i, fb_pdl
            elif fb_track_pmhl and (not np.isnan(fb_pmh)) and _break_above(fb_pmh):
                fb_break_level_id, fb_break_direction, fb_break_bar, fb_break_level_value = 2, 1, i, fb_pmh
            elif fb_track_pmhl and (not np.isnan(fb_pml)) and _break_below(fb_pml):
                fb_break_level_id, fb_break_direction, fb_break_bar, fb_break_level_value = 3, -1, i, fb_pml
            elif (not np.isnan(fb_hod)) and _break_above(fb_hod):
                fb_break_level_id, fb_break_direction, fb_break_bar, fb_break_level_value = 4, 1, i, fb_hod
            elif (not np.isnan(fb_lod)) and _break_below(fb_lod):
                fb_break_level_id, fb_break_direction, fb_break_bar, fb_break_level_value = 5, -1, i, fb_lod
            elif (not np.isnan(fb_vwap_value)) and _break_above(fb_vwap_value):
                fb_break_level_id, fb_break_direction, fb_break_bar, fb_break_level_value = 6, 1, i, fb_vwap_value
            elif (not np.isnan(fb_vwap_value)) and _break_below(fb_vwap_value):
                fb_break_level_id, fb_break_direction, fb_break_bar, fb_break_level_value = 6, -1, i, fb_vwap_value
            elif fb_or_complete and (not np.isnan(fb_or_high)) and _break_above(fb_or_high):
                fb_break_level_id, fb_break_direction, fb_break_bar, fb_break_level_value = 9, 1, i, fb_or_high
            elif fb_or_complete and (not np.isnan(fb_or_low)) and _break_below(fb_or_low):
                fb_break_level_id, fb_break_direction, fb_break_bar, fb_break_level_value = 10, -1, i, fb_or_low

        if (
            enable_failed_break
            and fb_break_level_id != -1
            and i > fb_break_bar
            and (i - fb_break_bar) <= fb_max_bars_confirm
            and (i - fb_last_signal_bar) >= fb_cooldown_bars
            and bool(time_ok.iloc[i])
        ):
            if fb_break_direction == 1 and float(close.iloc[i]) < fb_break_level_value:
                fb_short_signal[i] = True
                fb_last_signal_bar = i
                fb_break_level_id = -1
                fb_break_direction = 0
            elif fb_break_direction == -1 and float(close.iloc[i]) > fb_break_level_value:
                fb_long_signal[i] = True
                fb_last_signal_bar = i
                fb_break_level_id = -1
                fb_break_direction = 0

    any_long_signal = rd_bull_signal | srb_long_signal | bb_long_signal | snap_long_signal | eng_long_signal | vc_long_signal | fb_long_signal
    any_short_signal = rd_bear_signal | srb_short_signal | bb_short_signal | vc_short_signal | fb_short_signal
    long_count = (
        rd_bull_signal.astype(int)
        + srb_long_signal.astype(int)
        + bb_long_signal.astype(int)
        + snap_long_signal.astype(int)
        + eng_long_signal.astype(int)
        + vc_long_signal.astype(int)
        + fb_long_signal.astype(int)
    )
    short_count = (
        rd_bear_signal.astype(int)
        + srb_short_signal.astype(int)
        + bb_short_signal.astype(int)
        + vc_short_signal.astype(int)
        + fb_short_signal.astype(int)
    )
    show_long_diamonds = any_long_signal & (long_count >= min_confluence)
    show_short_diamonds = any_short_signal & (short_count >= min_confluence)
    long_entry = any_long_signal.astype(int)
    short_entry = any_short_signal.astype(int)
    strong_long_entry = (long_count >= 2).astype(int)
    strong_short_entry = (short_count >= 2).astype(int)
    very_strong_long_entry = (long_count >= 3).astype(int)
    stack_unit = atr14 * 0.3
    detector_colorers = {name: 1 for name in (
        "L1_Liquidity_Trap_colorer",
        "L2_Structural_Divergence_colorer",
        "L3_Band_Rejection_colorer",
        "L4_Panic_Snap_colorer",
        "L5_Capitulation_Engulf_colorer",
        "L6_Volume_Climax_colorer",
        "L7_Failed_Breakout_colorer",
        "S1_Band_Rejection_colorer",
        "S2_Structural_Divergence_colorer",
        "S3_Liquidity_Trap_colorer",
        "S4_Volume_Climax_colorer",
        "S5_Failed_Breakout_colorer",
    )}

    return working.assign(
        atr14=atr14,
        bb_upper=bb_upper,
        bb_basis=bb_basis,
        bb_lower=bb_lower,
        vix_now=vix_now,
        vix_daily_open=vix_daily_open,
        vix_daily_atr=vix_daily_atr,
        daily_atr=daily_atr,
        daily_close=daily_close,
        india_vix_now=vix_now,
        india_vix_daily_open=vix_daily_open,
        india_vix_daily_atr=vix_daily_atr,
        in_session=in_session.astype(int),
        time_ok=time_ok.astype(int),
        preopen_session=fb_is_preopen.astype(int),
        rd_bull_signal=rd_bull_signal.astype(int),
        rd_bear_signal=rd_bear_signal.astype(int),
        srb_long_signal=srb_long_signal.astype(int),
        srb_short_signal=srb_short_signal.astype(int),
        bb_long_signal=bb_long_signal.astype(int),
        bb_short_signal=bb_short_signal.astype(int),
        snap_long_signal=snap_long_signal.astype(int),
        eng_long_signal=eng_long_signal.astype(int),
        vc_long_signal=vc_long_signal.astype(int),
        vc_short_signal=vc_short_signal.astype(int),
        fb_long_signal=fb_long_signal.astype(int),
        fb_short_signal=fb_short_signal.astype(int),
        long_count=long_count,
        short_count=short_count,
        show_long_diamonds=show_long_diamonds.astype(int),
        show_short_diamonds=show_short_diamonds.astype(int),
        BB_Upper=bb_upper,
        BB_Basis=bb_basis,
        BB_Lower=bb_lower,
        L1_Liquidity_Trap=np.where(show_long_diamonds, low - stack_unit * 1, np.nan),
        L2_Structural_Divergence=np.where(show_long_diamonds, low - stack_unit * 2, np.nan),
        L3_Band_Rejection=np.where(show_long_diamonds, low - stack_unit * 3, np.nan),
        L4_Panic_Snap=np.where(show_long_diamonds, low - stack_unit * 4, np.nan),
        L5_Capitulation_Engulf=np.where(show_long_diamonds, low - stack_unit * 5, np.nan),
        L6_Volume_Climax=np.where(show_long_diamonds, low - stack_unit * 6, np.nan),
        L7_Failed_Breakout=np.where(show_long_diamonds, low - stack_unit * 7, np.nan),
        S1_Band_Rejection=np.where(show_short_diamonds, high + stack_unit * 1, np.nan),
        S2_Structural_Divergence=np.where(show_short_diamonds, high + stack_unit * 2, np.nan),
        S3_Liquidity_Trap=np.where(show_short_diamonds, high + stack_unit * 3, np.nan),
        S4_Volume_Climax=np.where(show_short_diamonds, high + stack_unit * 4, np.nan),
        S5_Failed_Breakout=np.where(show_short_diamonds, high + stack_unit * 5, np.nan),
        Any_Long_Signal=any_long_signal.astype(int),
        Any_Short_Signal=any_short_signal.astype(int),
        Strong_Long_2=(long_count >= 2).astype(int),
        Strong_Short_2=(short_count >= 2).astype(int),
        Very_Strong_Long_3=(long_count >= 3).astype(int),
        long_entry=long_entry,
        short_entry=short_entry,
        strong_long_entry=strong_long_entry,
        strong_short_entry=strong_short_entry,
        very_strong_long_entry=very_strong_long_entry,
        EngBB_Signal=eng_long_signal.astype(int),
        SnapBB_Signal=snap_long_signal.astype(int),
        Volume_Climax_Signal=(vc_long_signal | vc_short_signal).astype(int),
        Failed_Breakout_Signal=(fb_long_signal | fb_short_signal).astype(int),
        **detector_colorers,
    )


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return the indicator's actionable boolean outputs without backtesting.

    This keeps the first-pass deliverable indicator-only, while exposing the
    aggregated long/short conditions and detector contributions.
    """
    required = [
        "Any_Long_Signal",
        "Any_Short_Signal",
        "long_count",
        "short_count",
        "long_entry",
        "short_entry",
        "strong_long_entry",
        "strong_short_entry",
        "very_strong_long_entry",
        "rd_bull_signal",
        "rd_bear_signal",
        "srb_long_signal",
        "srb_short_signal",
        "bb_long_signal",
        "bb_short_signal",
        "snap_long_signal",
        "eng_long_signal",
        "vc_long_signal",
        "vc_short_signal",
        "fb_long_signal",
        "fb_short_signal",
    ]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(
            "generate_signals requires calculated columns: " + ", ".join(missing)
        )
    return df.loc[:, required].copy()


# -- VALIDATION -------------------------------------------------------------
def validate_against_sample(df: pd.DataFrame, sample_path: str | Path) -> list[str]:
    """Compare exported indicator columns against the sample CSV."""
    sample_df = load_csv_data(sample_path)
    messages: list[str] = []
    alias_map = {
        "BB_Upper": ("BB_Upper",),
        "BB_Basis": ("BB_Basis",),
        "BB_Lower": ("BB_Lower",),
        "L1_Liquidity_Trap": ("L1_Liquidity_Trap",),
        "L1_Liquidity_Trap_colorer": ("L1_Liquidity_Trap_colorer",),
        "L2_Structural_Divergence": ("L2_Structural_Divergence",),
        "L2_Structural_Divergence_colorer": ("L2_Structural_Divergence_colorer",),
        "L3_Band_Rejection": ("L3_Band_Rejection",),
        "L3_Band_Rejection_colorer": ("L3_Band_Rejection_colorer",),
        "L4_Panic_Snap": ("L4_Panic_Snap",),
        "L4_Panic_Snap_colorer": ("L4_Panic_Snap_colorer",),
        "L5_Capitulation_Engulf": ("L5_Capitulation_Engulf",),
        "L5_Capitulation_Engulf_colorer": ("L5_Capitulation_Engulf_colorer",),
        "L6_Volume_Climax": ("L6_Volume_Climax",),
        "L6_Volume_Climax_colorer": ("L6_Volume_Climax_colorer",),
        "L7_Failed_Breakout": ("L7_Failed_Breakout",),
        "L7_Failed_Breakout_colorer": ("L7_Failed_Breakout_colorer",),
        "S1_Band_Rejection": ("S1_Band_Rejection",),
        "S1_Band_Rejection_colorer": ("S1_Band_Rejection_colorer",),
        "S2_Structural_Divergence": ("S2_Structural_Divergence",),
        "S2_Structural_Divergence_colorer": ("S2_Structural_Divergence_colorer",),
        "S3_Liquidity_Trap": ("S3_Liquidity_Trap",),
        "S3_Liquidity_Trap_colorer": ("S3_Liquidity_Trap_colorer",),
        "S4_Volume_Climax": ("S4_Volume_Climax",),
        "S4_Volume_Climax_colorer": ("S4_Volume_Climax_colorer",),
        "S5_Failed_Breakout": ("S5_Failed_Breakout",),
        "S5_Failed_Breakout_colorer": ("S5_Failed_Breakout_colorer",),
        "Any_Long_Signal": ("Any_Long_Signal",),
        "Any_Short_Signal": ("Any_Short_Signal",),
        "Strong_Long_2": ("Strong_Long_2",),
        "Strong_Short_2": ("Strong_Short_2",),
        "Very_Strong_Long_3": ("Very_Strong_Long_3",),
        "EngBB_Signal": ("EngBB_Signal",),
        "SnapBB_Signal": ("SnapBB_Signal",),
        "Volume_Climax_Signal": ("Volume_Climax_Signal",),
        "Failed_Breakout_Signal": ("Failed_Breakout_Signal",),
    }
    common_index = df.index.intersection(sample_df.index)

    for output_column, aliases in alias_map.items():
        sample_column = _find_matching_sample_column(sample_df, aliases)
        if sample_column is None:
            messages.append(f"{output_column}: sample column missing")
            continue

        actual = pd.to_numeric(df.loc[common_index, output_column], errors="coerce").to_numpy(dtype=float)
        expected = pd.to_numeric(sample_df.loc[common_index, sample_column], errors="coerce").to_numpy(dtype=float)
        passed = np.isclose(actual, expected, atol=1e-8, rtol=0.0, equal_nan=True)
        if passed.all():
            messages.append(f"{output_column}: PASS")
        else:
            mismatch_idx = int(np.flatnonzero(~passed)[0])
            mismatch_time = common_index[mismatch_idx]
            messages.append(
                f"{output_column}: FAIL at {mismatch_time} actual={actual[mismatch_idx]!r} expected={expected[mismatch_idx]!r}"
            )
    return messages


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """Verify internal consistency for the calculated indicator outputs."""
    required = ["Any_Long_Signal", "Any_Short_Signal", "long_count", "short_count", "BB_Upper", "BB_Basis", "BB_Lower"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires calculated columns: " + ", ".join(missing)
        )

    expected_any_long = (
        df["rd_bull_signal"].eq(1)
        | df["srb_long_signal"].eq(1)
        | df["bb_long_signal"].eq(1)
        | df["snap_long_signal"].eq(1)
        | df["eng_long_signal"].eq(1)
        | df["vc_long_signal"].eq(1)
        | df["fb_long_signal"].eq(1)
    ).astype(int)
    expected_any_short = (
        df["rd_bear_signal"].eq(1)
        | df["srb_short_signal"].eq(1)
        | df["bb_short_signal"].eq(1)
        | df["vc_short_signal"].eq(1)
        | df["fb_short_signal"].eq(1)
    ).astype(int)

    if not expected_any_long.equals(df["Any_Long_Signal"].astype(int)):
        raise AssertionError("Any_Long_Signal must be the OR of all long detectors.")
    if not expected_any_short.equals(df["Any_Short_Signal"].astype(int)):
        raise AssertionError("Any_Short_Signal must be the OR of all short detectors.")

    if not df["long_entry"].astype(int).equals(df["Any_Long_Signal"].astype(int)):
        raise AssertionError("long_entry must equal Any_Long_Signal.")
    if not df["short_entry"].astype(int).equals(df["Any_Short_Signal"].astype(int)):
        raise AssertionError("short_entry must equal Any_Short_Signal.")
    if not df["strong_long_entry"].astype(int).equals(df["Strong_Long_2"].astype(int)):
        raise AssertionError("strong_long_entry must equal Strong_Long_2.")
    if not df["strong_short_entry"].astype(int).equals(df["Strong_Short_2"].astype(int)):
        raise AssertionError("strong_short_entry must equal Strong_Short_2.")
    if not df["very_strong_long_entry"].astype(int).equals(df["Very_Strong_Long_3"].astype(int)):
        raise AssertionError("very_strong_long_entry must equal Very_Strong_Long_3.")

    print("Internal sanity checks: PASS")


# -- REPORTING --------------------------------------------------------------
def _build_sample_preview(sample_df: pd.DataFrame, rows: int = 6) -> pd.DataFrame:
    """Return a compact sample preview."""
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "BB_Upper",
        "BB_Basis",
        "BB_Lower",
        "Any_Long_Signal",
        "Any_Short_Signal",
    ]
    return sample_df.loc[:, preview_columns].head(rows)


def _build_python_preview(df: pd.DataFrame, rows: int = 6) -> pd.DataFrame:
    """Return a compact Python output preview."""
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "BB_Upper",
        "BB_Basis",
        "BB_Lower",
        "Any_Long_Signal",
        "Any_Short_Signal",
    ]
    return df.loc[:, preview_columns].head(rows)


def _build_signal_preview(df: pd.DataFrame, rows: int = 10) -> pd.DataFrame:
    """Return a compact preview of active signals, if any."""
    mask = df["Any_Long_Signal"].eq(1) | df["Any_Short_Signal"].eq(1)
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "rd_bull_signal",
        "rd_bear_signal",
        "srb_long_signal",
        "srb_short_signal",
        "bb_long_signal",
        "bb_short_signal",
        "snap_long_signal",
        "eng_long_signal",
        "vc_long_signal",
        "vc_short_signal",
        "fb_long_signal",
        "fb_short_signal",
        "Any_Long_Signal",
        "Any_Short_Signal",
        "long_count",
        "short_count",
    ]
    return df.loc[mask, preview_columns].head(rows)


def main(sample_path: str | Path = DEFAULT_SAMPLE_PATH) -> int:
    """Load the sample, calculate the indicator, validate, and print a compact report."""
    sample_df = load_csv_data(sample_path)
    calculated = calculate_indicators(sample_df, allow_external_fetch=False)
    run_internal_sanity_checks(calculated)
    messages = validate_against_sample(calculated, sample_path)

    print("Indicator:", PINE_INDICATOR_NAME)
    print("Rows:", len(calculated))
    print("\nValidation report:")
    for message in messages:
        print(f"  {message}")

    print("\nSignal counts:")
    for column in (
        "Any_Long_Signal",
        "Any_Short_Signal",
        "Strong_Long_2",
        "Strong_Short_2",
        "Very_Strong_Long_3",
        "EngBB_Signal",
        "SnapBB_Signal",
        "Volume_Climax_Signal",
        "Failed_Breakout_Signal",
    ):
        print(f"  {column}: {int(pd.to_numeric(calculated[column], errors='coerce').fillna(0).sum())}")

    print("\nSample preview:")
    print(_build_sample_preview(sample_df).to_string(index=False))

    print("\nPython result preview:")
    print(_build_python_preview(calculated).to_string(index=False))

    signal_preview = _build_signal_preview(calculated)
    if not signal_preview.empty:
        print("\nPython signal preview:")
        print(signal_preview.to_string(index=False))
    else:
        print("\nPython signal preview: no active signals in the current sample.")

    return 0


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    raise SystemExit(main(input_path))
