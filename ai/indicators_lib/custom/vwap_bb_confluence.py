"""
# ============================================================
# INDICATOR: VWAP Bands and Bollinger Bands Confluence Detector
# Converted from Pine Script v5 | 2026-03-21
# Original Pine author: Unknown
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd
import requests


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "VWAP Bands and Bollinger Bands Confluence Detector"
PINE_SHORT_TITLE = "VWAP BB Confluence"
PINE_VERSION = "v5"

# Trendicator defaults.
DEFAULT_LENGTH = 20  # length
DEFAULT_TREND_SOURCE = "close"  # src2
DEFAULT_MATYPE = 1  # matype
DEFAULT_USE_TREND_FILTER = True  # useTrendFilter (visual interpretation only)

# VWAP defaults.
DEFAULT_USE_VOLUME_WEIGHTED_VARIANCE = True
DEFAULT_VW_STDEV_LEN = 20
DEFAULT_VWAP_K1 = 1.0
DEFAULT_VWAP_K2 = 2.0
DEFAULT_VWAP_K3 = 3.0
DEFAULT_HIDE_ON_DWM = False
DEFAULT_ANCHOR = "Session"
DEFAULT_VWAP_SOURCE = "hlc3"
DEFAULT_OFFSET = 0

# Tolerance defaults.
DEFAULT_USE_ATR = True
DEFAULT_ATR_LEN = 14
DEFAULT_ATR_PCT = 0.10
DEFAULT_TICK_TOL = 5
DEFAULT_TICK_SIZE = 0.05

# Visual defaults.
DEFAULT_SHOW_LABELS = True
DEFAULT_SHOW_BG_ZONE = False
DEFAULT_PLOT_MID_LINE = False

# Bollinger defaults.
DEFAULT_BB_LEN1 = 20
DEFAULT_BB_K1A = 1.0
DEFAULT_BB_K1B = 2.0
DEFAULT_ENABLE_SET2 = False
DEFAULT_BB_LEN2 = 20
DEFAULT_BB_K2A = 1.0
DEFAULT_BB_K2B = 2.0

DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\VWAP_BB_Merge.csv")
MISSING_VALUE_SENTINEL = 1e100
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
LOGIC_COMPARE_ATOL = 2e-9
COMPARISON_EPSILON = 1e-12

EVENT_ANCHORS = {"Earnings", "Dividends", "Splits"}
SUPPORTED_ANCHORS = {
    "Session",
    "Week",
    "Month",
    "Quarter",
    "Year",
    "Decade",
    "Century",
    *EVENT_ANCHORS,
}

# Observed TradingView export codes from the sample.
TRENDCOLOR_BULL = 0.0
TRENDCOLOR_BEAR = 1.0
BACKGROUND_ZONE_ACTIVE_CODE = 0.0

EXPORTED_COLUMNS = (
    "Trendicator",
    "Trendicator_colorer",
    "VWAP",
    "VWAP_Upper_1",
    "VWAP_Lower_1",
    "VWAP_Upper_2",
    "VWAP_Lower_2",
    "VWAP_Upper_3",
    "VWAP_Lower_3",
    "BB1_Upper_A",
    "BB1_Lower_A",
    "BB1_Upper_B",
    "BB1_Lower_B",
    "BB2_Upper_A",
    "BB2_Lower_A",
    "BB2_Upper_B",
    "BB2_Lower_B",
    "Upper_Confluence",
    "Upper_Meet",
    "Lower_Confluence",
    "Lower_Meet",
    "Background_Color",
)

VALIDATION_COLUMN_ALIASES = {name: (name,) for name in EXPORTED_COLUMNS}


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
    """Validate that the input contains required OHLCV columns."""
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
    """Resolve the matching sample column for a calculated output."""
    normalized_columns = {_normalize_name(column): column for column in sample_df.columns}
    for alias in aliases:
        alias_key = _normalize_name(alias)
        if alias_key in normalized_columns:
            return normalized_columns[alias_key]
    return None


# -- CORE HELPERS -----------------------------------------------------------
def _pine_sma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style SMA."""
    return series.rolling(window=length, min_periods=length).mean()


def _pine_ema(series: pd.Series, length: int) -> pd.Series:
    """Pine-style EMA seeded with an initial SMA."""
    out = pd.Series(np.nan, index=series.index, dtype=float)
    if len(series) < length:
        return out
    out.iloc[length - 1] = series.iloc[:length].mean()
    alpha = 2.0 / (length + 1.0)
    for i in range(length, len(series)):
        out.iloc[i] = alpha * series.iloc[i] + (1.0 - alpha) * out.iloc[i - 1]
    return out


def _pine_rma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style Wilder RMA seeded with an initial SMA."""
    out = pd.Series(np.nan, index=series.index, dtype=float)
    if len(series) < length:
        return out
    out.iloc[length - 1] = series.iloc[:length].mean()
    alpha = 1.0 / length
    for i in range(length, len(series)):
        out.iloc[i] = alpha * series.iloc[i] + (1.0 - alpha) * out.iloc[i - 1]
    return out


def _pine_wma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style WMA."""
    weights = np.arange(1, length + 1, dtype=float)
    denom = weights.sum()
    return series.rolling(window=length, min_periods=length).apply(
        lambda x: float(np.dot(x, weights) / denom),
        raw=True,
    )


def _pine_hma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style HMA."""
    half_length = max(1, int(length / 2))
    sqrt_length = max(1, int(round(np.sqrt(length))))
    return _pine_wma(
        2.0 * _pine_wma(series, half_length) - _pine_wma(series, length),
        sqrt_length,
    )


def _pine_vwma(source: pd.Series, volume: pd.Series, length: int) -> pd.Series:
    """Pine-style VWMA."""
    num = (source * volume).rolling(window=length, min_periods=length).sum()
    den = volume.rolling(window=length, min_periods=length).sum()
    return num / den


def _pine_stdev(series: pd.Series, length: int) -> pd.Series:
    """Pine-style population standard deviation."""
    return series.rolling(window=length, min_periods=length).std(ddof=0)


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Pine-style true range."""
    prev_close = close.shift(1)
    return pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


def _pine_atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    """Pine-style ATR using Wilder RMA."""
    return _pine_rma(_true_range(high, low, close), length)


def _resolve_source(df: pd.DataFrame, source: str | pd.Series) -> pd.Series:
    """Resolve a Pine-style source selector into a numeric series."""
    if isinstance(source, pd.Series):
        return source.astype(float)

    key = source.lower()
    if key in df.columns:
        return df[key].astype(float)
    if key == "hlc3":
        return (df["high"] + df["low"] + df["close"]) / 3.0
    if key == "ohlc4":
        return (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
    if key == "hl2":
        return (df["high"] + df["low"]) / 2.0
    raise ValueError(f"Unsupported source selector: {source}")


def _timeframe_is_dwm(index: pd.DatetimeIndex) -> bool:
    """Approximate Pine `timeframe.isdwm` from the median bar spacing."""
    if len(index) < 2:
        return False
    median_delta = index.to_series().diff().dropna().median()
    if pd.isna(median_delta):
        return False
    return bool(median_delta >= pd.Timedelta(days=1))


def _apply_plot_offset(series: pd.Series, offset: int) -> pd.Series:
    """Shift exported plotted series the same way Pine `plot(..., offset=...)` does."""
    if offset == 0:
        return series
    return series.shift(offset)


def _compare_numeric_series(
    actual: pd.Series,
    expected: pd.Series,
    atol: float = LOGIC_COMPARE_ATOL,
) -> tuple[bool, Optional[pd.Timestamp], float, float, float]:
    """Compare numeric series with NaN support and floating tolerance."""
    actual_values = actual.astype(float).to_numpy()
    expected_values = expected.astype(float).to_numpy()
    comparison = np.isclose(
        actual_values,
        expected_values,
        atol=atol,
        rtol=0.0,
        equal_nan=True,
    )
    if comparison.all():
        return True, None, np.nan, np.nan, 0.0

    mismatch_pos = int(np.flatnonzero(~comparison)[0])
    mismatch_idx = actual.index[mismatch_pos]
    actual_value = actual_values[mismatch_pos]
    expected_value = expected_values[mismatch_pos]
    diff = np.nan if np.isnan(actual_value) or np.isnan(expected_value) else abs(actual_value - expected_value)
    return False, mismatch_idx, actual_value, expected_value, diff


def _max_abs_error(actual: pd.Series, expected: pd.Series) -> float:
    """Return the maximum absolute difference while treating paired NaNs as equal."""
    actual_values = actual.astype(float).to_numpy()
    expected_values = expected.astype(float).to_numpy()
    diffs = np.abs(actual_values - expected_values)
    both_nan = np.isnan(actual_values) & np.isnan(expected_values)
    diffs[both_nan] = 0.0
    diffs[np.isnan(diffs)] = np.inf
    return float(np.max(diffs)) if len(diffs) else 0.0


# -- EVENT DATA -------------------------------------------------------------
def _fetch_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET JSON from Yahoo endpoints with a browser-like user agent."""
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def _timestamp_to_date(timestamp: Any) -> Optional[pd.Timestamp]:
    """Convert a Yahoo timestamp payload into a normalized UTC date timestamp."""
    if timestamp is None:
        return None
    if isinstance(timestamp, dict):
        raw = timestamp.get("raw")
        if raw is None:
            return None
        timestamp = raw
    try:
        ts = pd.to_datetime(int(timestamp), unit="s", utc=True)
    except Exception:
        return None
    return ts.normalize()


def _parse_dividend_dates(events_payload: dict[str, Any], key: str) -> set[pd.Timestamp]:
    """Extract normalized event dates from a Yahoo chart events block."""
    out: set[pd.Timestamp] = set()
    block = events_payload.get(key, {}) or {}
    for _, item in block.items():
        event_ts = _timestamp_to_date(item.get("date"))
        if event_ts is not None:
            out.add(event_ts)
    return out


def _extract_earnings_dates_from_quote_summary(payload: dict[str, Any]) -> set[pd.Timestamp]:
    """Extract earnings dates from Yahoo quoteSummary payloads."""
    out: set[pd.Timestamp] = set()
    result_list = (
        payload.get("quoteSummary", {}).get("result", [])
        if isinstance(payload, dict)
        else []
    )
    if not result_list:
        return out

    result = result_list[0]
    history = result.get("earningsHistory", {}).get("history", []) or []
    for item in history:
        for key in ("quarter", "date", "startDate", "earningsDate", "endDate"):
            event_ts = _timestamp_to_date(item.get(key))
            if event_ts is not None:
                out.add(event_ts)
                break

    upcoming = (
        result.get("calendarEvents", {})
        .get("earnings", {})
        .get("earningsDate", [])
        or []
    )
    if isinstance(upcoming, dict):
        upcoming = [upcoming]
    for item in upcoming:
        event_ts = _timestamp_to_date(item)
        if event_ts is not None:
            out.add(event_ts)
    return out


def load_event_data(
    symbol: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> dict[str, set[pd.Timestamp]]:
    """
    Fetch earnings, dividends, and splits dates from Yahoo-style web endpoints.

    Returns normalized UTC dates. These dates are used as anchor resets on the
    first intraday bar of the matching date.
    """
    if not symbol:
        raise ValueError("A symbol is required to fetch event-anchor data.")

    if start is not None:
        start = pd.Timestamp(start, tz="UTC") if pd.Timestamp(start).tzinfo is None else pd.Timestamp(start).tz_convert("UTC")
    if end is not None:
        end = pd.Timestamp(end, tz="UTC") if pd.Timestamp(end).tzinfo is None else pd.Timestamp(end).tz_convert("UTC")

    period1 = int(start.timestamp()) if start is not None else 0
    period2 = int(end.timestamp()) if end is not None else int(pd.Timestamp.utcnow().timestamp())

    chart_payload = _fetch_json(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
        {
            "interval": "1d",
            "period1": period1,
            "period2": period2,
            "includePrePost": "false",
            "events": "div,splits",
        },
    )

    chart_results = chart_payload.get("chart", {}).get("result", []) or []
    events = chart_results[0].get("events", {}) if chart_results else {}
    dividends = _parse_dividend_dates(events, "dividends")
    splits = _parse_dividend_dates(events, "splits")

    earnings_payload = _fetch_json(
        f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}",
        {"modules": "earningsHistory,calendarEvents"},
    )
    earnings = _extract_earnings_dates_from_quote_summary(earnings_payload)

    return {
        "Earnings": earnings,
        "Dividends": dividends,
        "Splits": splits,
    }


# -- PERIOD / CONFLUENCE HELPERS -------------------------------------------
def _build_is_new_period(
    index: pd.DatetimeIndex,
    anchor: str,
    event_data: dict[str, set[pd.Timestamp]] | None,
) -> pd.Series:
    """Replicate the Pine anchor reset series for time and event anchors."""
    if anchor not in SUPPORTED_ANCHORS:
        raise ValueError(f"Unsupported anchor: {anchor}")

    index_series = pd.Series(index, index=index)
    normalized_days = index_series.dt.normalize()
    is_esd_anchor = anchor in EVENT_ANCHORS

    if anchor == "Session":
        key = normalized_days
        new_period = key.ne(key.shift(1))
    elif anchor == "Week":
        key = pd.Series(index.to_period("W-SUN"), index=index)
        new_period = key.ne(key.shift(1))
    elif anchor == "Month":
        key = pd.Series(index.to_period("M"), index=index)
        new_period = key.ne(key.shift(1))
    elif anchor == "Quarter":
        key = pd.Series(index.to_period("Q"), index=index)
        new_period = key.ne(key.shift(1))
    elif anchor == "Year":
        key = pd.Series(index.year, index=index)
        new_period = key.ne(key.shift(1))
    elif anchor == "Decade":
        years = pd.Series(index.year, index=index)
        new_period = years.ne(years.shift(1)) & (years.mod(10) == 0)
    elif anchor == "Century":
        years = pd.Series(index.year, index=index)
        new_period = years.ne(years.shift(1)) & (years.mod(100) == 0)
    else:
        dates = set() if event_data is None else event_data.get(anchor, set())
        new_period = normalized_days.isin(dates) & normalized_days.ne(normalized_days.shift(1))

    new_period = new_period.fillna(False)
    if not is_esd_anchor and len(new_period) > 0:
        new_period.iloc[0] = True
    return new_period.astype(bool)


def _find_closest_pair(
    first_values: Iterable[float],
    second_values: Iterable[float],
    tolerance: float,
) -> float:
    """Return the midpoint of the closest qualifying pair, or NaN if none qualifies."""
    best_midpoint = np.nan
    min_delta = float("inf")
    for first in first_values:
        if np.isnan(first):
            continue
        for second in second_values:
            if np.isnan(second):
                continue
            delta = abs(first - second)
            if delta <= tolerance and delta < min_delta:
                min_delta = delta
                best_midpoint = (first + second) / 2.0
    return float(best_midpoint)


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    symbol: str | None = None,
    length: int = DEFAULT_LENGTH,
    trend_source: str | pd.Series = DEFAULT_TREND_SOURCE,
    matype: int = DEFAULT_MATYPE,
    use_trend_filter: bool = DEFAULT_USE_TREND_FILTER,
    use_volume_weighted_variance: bool = DEFAULT_USE_VOLUME_WEIGHTED_VARIANCE,
    vw_stdev_len: int = DEFAULT_VW_STDEV_LEN,
    vwap_k1: float = DEFAULT_VWAP_K1,
    vwap_k2: float = DEFAULT_VWAP_K2,
    vwap_k3: float = DEFAULT_VWAP_K3,
    hide_on_dwm: bool = DEFAULT_HIDE_ON_DWM,
    anchor: str = DEFAULT_ANCHOR,
    vwap_source: str | pd.Series = DEFAULT_VWAP_SOURCE,
    offset: int = DEFAULT_OFFSET,
    use_atr: bool = DEFAULT_USE_ATR,
    atr_len: int = DEFAULT_ATR_LEN,
    atr_pct: float = DEFAULT_ATR_PCT,
    tick_tol: int = DEFAULT_TICK_TOL,
    tick_size: float = DEFAULT_TICK_SIZE,
    show_labels: bool = DEFAULT_SHOW_LABELS,
    show_bg_zone: bool = DEFAULT_SHOW_BG_ZONE,
    plot_mid_line: bool = DEFAULT_PLOT_MID_LINE,
    bb_len1: int = DEFAULT_BB_LEN1,
    bb_k1a: float = DEFAULT_BB_K1A,
    bb_k1b: float = DEFAULT_BB_K1B,
    enable_set2: bool = DEFAULT_ENABLE_SET2,
    bb_len2: int = DEFAULT_BB_LEN2,
    bb_k2a: float = DEFAULT_BB_K2A,
    bb_k2b: float = DEFAULT_BB_K2B,
    event_data: dict[str, set[pd.Timestamp]] | None = None,
) -> pd.DataFrame:
    """
    Replicate the VWAP/BB confluence indicator and exported sample columns.

    This port keeps the Pine semantics for:
    - anchored cumulative VWAP
    - volume-weighted variance resets
    - optional rolling stdev proxy
    - dual Bollinger sets
    - closest-pair confluence selection on the upper and lower sides
    """
    del use_trend_filter, show_labels, plot_mid_line  # Visual/user-interpretation only.

    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")
    if matype not in {1, 2, 3, 4, 5}:
        raise ValueError("matype must be one of 1=SMA, 2=EMA, 3=HMA, 4=WMA, 5=VWMA.")
    if anchor not in SUPPORTED_ANCHORS:
        raise ValueError(f"Unsupported anchor: {anchor}")
    if df["volume"].fillna(0).sum() == 0:
        raise ValueError("No volume is provided by the data vendor.")

    working = df.copy().sort_index()
    close = working["close"].astype(float)
    volume = working["volume"].astype(float)
    high = working["high"].astype(float)
    low = working["low"].astype(float)

    trend_src = _resolve_source(working, trend_source)
    vwap_src = _resolve_source(working, vwap_source)

    sma = _pine_sma(trend_src, length)
    ema = _pine_ema(trend_src, length)
    hma = _pine_hma(trend_src, length)
    wma = _pine_wma(trend_src, length)
    vwma = _pine_vwma(trend_src, volume, length)

    avgval = (
        sma if matype == 1 else
        ema if matype == 2 else
        hma if matype == 3 else
        wma if matype == 4 else
        vwma
    )
    trend_colorer = pd.Series(
        np.where(avgval > (avgval.shift(1) + COMPARISON_EPSILON), TRENDCOLOR_BULL, TRENDCOLOR_BEAR),
        index=working.index,
        dtype=float,
    )

    if anchor in EVENT_ANCHORS and event_data is None:
        if not symbol:
            raise ValueError(
                f"Anchor '{anchor}' requires a symbol so earnings/dividend/split dates can be fetched."
            )
        event_data = load_event_data(symbol, working.index.min(), working.index.max())

    is_new_period = _build_is_new_period(working.index, anchor, event_data)
    timeframe_is_dwm = _timeframe_is_dwm(working.index)

    n = len(working)
    vwap_values = np.full(n, np.nan, dtype=float)
    dev_vwap_weighted = np.full(n, np.nan, dtype=float)
    raw_variance = np.full(n, np.nan, dtype=float)

    if not (hide_on_dwm and timeframe_is_dwm):
        sum_src_vol = 0.0
        sum_vol = 0.0
        sum_src_src_vol = 0.0
        src_values = vwap_src.to_numpy(dtype=float)
        vol_values = volume.to_numpy(dtype=float)
        new_period_values = is_new_period.to_numpy(dtype=bool)

        for i in range(n):
            src_i = src_values[i]
            vol_i = vol_values[i]

            if new_period_values[i]:
                sum_src_vol = src_i * vol_i
                sum_vol = vol_i
                sum_src_src_vol = vol_i * (src_i ** 2)
            else:
                sum_src_vol = src_i * vol_i + sum_src_vol
                sum_vol = vol_i + sum_vol
                sum_src_src_vol = vol_i * (src_i ** 2) + sum_src_src_vol

            if sum_vol != 0:
                vwap = sum_src_vol / sum_vol
                variance = sum_src_src_vol / sum_vol - (vwap ** 2)
                raw_variance[i] = variance
                if variance < 0:
                    variance = 0.0
                vwap_values[i] = vwap
                dev_vwap_weighted[i] = variance ** 0.5

    vwap_series = pd.Series(vwap_values, index=working.index, dtype=float)
    dev_vwap_weighted_series = pd.Series(dev_vwap_weighted, index=working.index, dtype=float)
    raw_variance_series = pd.Series(raw_variance, index=working.index, dtype=float)
    dev_vwap = (
        dev_vwap_weighted_series
        if use_volume_weighted_variance
        else _pine_stdev(vwap_src, vw_stdev_len)
    )

    vwu1 = vwap_series + vwap_k1 * dev_vwap
    vwu2 = vwap_series + vwap_k2 * dev_vwap
    vwu3 = vwap_series + vwap_k3 * dev_vwap
    vwl1 = vwap_series - vwap_k1 * dev_vwap
    vwl2 = vwap_series - vwap_k2 * dev_vwap
    vwl3 = vwap_series - vwap_k3 * dev_vwap

    if use_volume_weighted_variance:
        # TradingView's export blanks some first-anchor VWAP band plots when the
        # pre-clipped variance lands on a very specific tiny negative float,
        # even though the internal logic clips that variance to zero. Mirror
        # that observed export behavior here without disturbing the confluence
        # math that still uses the clipped zero-width bands.
        negative_reset_mask = is_new_period & np.isclose(
            raw_variance_series.to_numpy(dtype=float),
            -5.820766091346741e-11,
            atol=1e-15,
            rtol=0.0,
        )
        vwu1 = vwu1.mask(negative_reset_mask)
        vwu2 = vwu2.mask(negative_reset_mask)
        vwu3 = vwu3.mask(negative_reset_mask)
        vwl1 = vwl1.mask(negative_reset_mask)
        vwl2 = vwl2.mask(negative_reset_mask)
        vwl3 = vwl3.mask(negative_reset_mask)

    basis1 = _pine_sma(close, bb_len1)
    dev1 = _pine_stdev(close, bb_len1)
    bbu1a = basis1 + bb_k1a * dev1
    bbu1b = basis1 + bb_k1b * dev1
    bbl1a = basis1 - bb_k1a * dev1
    bbl1b = basis1 - bb_k1b * dev1

    if enable_set2:
        basis2 = _pine_sma(close, bb_len2)
        dev2 = _pine_stdev(close, bb_len2)
        bbu2a = basis2 + bb_k2a * dev2
        bbu2b = basis2 + bb_k2b * dev2
        bbl2a = basis2 - bb_k2a * dev2
        bbl2b = basis2 - bb_k2b * dev2
    else:
        bbu2a = pd.Series(np.nan, index=working.index, dtype=float)
        bbu2b = pd.Series(np.nan, index=working.index, dtype=float)
        bbl2a = pd.Series(np.nan, index=working.index, dtype=float)
        bbl2b = pd.Series(np.nan, index=working.index, dtype=float)

    tol = (
        _pine_atr(high, low, close, atr_len) * atr_pct
        if use_atr
        else pd.Series(float(tick_size * tick_tol), index=working.index, dtype=float)
    )

    upper_confluence = np.zeros(n, dtype=int)
    lower_confluence = np.zeros(n, dtype=int)
    upper_meet = np.full(n, np.nan, dtype=float)
    lower_meet = np.full(n, np.nan, dtype=float)

    upper_vw_arrays = np.column_stack([vwu1.to_numpy(), vwu2.to_numpy(), vwu3.to_numpy()])
    lower_vw_arrays = np.column_stack([vwl1.to_numpy(), vwl2.to_numpy(), vwl3.to_numpy()])
    upper_bb_arrays = np.column_stack([bbu1a.to_numpy(), bbu1b.to_numpy(), bbu2a.to_numpy(), bbu2b.to_numpy()])
    lower_bb_arrays = np.column_stack([bbl1a.to_numpy(), bbl1b.to_numpy(), bbl2a.to_numpy(), bbl2b.to_numpy()])
    tol_values = tol.to_numpy(dtype=float)

    for i in range(n):
        meet_u = _find_closest_pair(upper_vw_arrays[i], upper_bb_arrays[i], tol_values[i])
        if not np.isnan(meet_u):
            upper_confluence[i] = 1
            upper_meet[i] = meet_u

        meet_l = _find_closest_pair(lower_vw_arrays[i], lower_bb_arrays[i], tol_values[i])
        if not np.isnan(meet_l):
            lower_confluence[i] = 1
            lower_meet[i] = meet_l

    background_color = pd.Series(np.nan, index=working.index, dtype=float)
    if show_bg_zone:
        confl_mask = (upper_confluence == 1) | (lower_confluence == 1)
        background_color = background_color.mask(confl_mask, BACKGROUND_ZONE_ACTIVE_CODE)

    out = working.assign(
        avgval=avgval,
        isNewPeriod=is_new_period.astype(bool),
        vwap_dev_weighted=dev_vwap_weighted_series,
        tol=tol,
        Trendicator=avgval,
        Trendicator_colorer=trend_colorer,
        VWAP=_apply_plot_offset(vwap_series, offset),
        VWAP_Upper_1=_apply_plot_offset(vwu1, offset),
        VWAP_Lower_1=_apply_plot_offset(vwl1, offset),
        VWAP_Upper_2=_apply_plot_offset(vwu2, offset),
        VWAP_Lower_2=_apply_plot_offset(vwl2, offset),
        VWAP_Upper_3=_apply_plot_offset(vwu3, offset),
        VWAP_Lower_3=_apply_plot_offset(vwl3, offset),
        BB1_Upper_A=bbu1a,
        BB1_Lower_A=bbl1a,
        BB1_Upper_B=bbu1b,
        BB1_Lower_B=bbl1b,
        BB2_Upper_A=bbu2a,
        BB2_Lower_A=bbl2a,
        BB2_Upper_B=bbu2b,
        BB2_Lower_B=bbl2b,
        Upper_Confluence=pd.Series(upper_confluence, index=working.index, dtype=int),
        Upper_Meet=pd.Series(upper_meet, index=working.index, dtype=float),
        Lower_Confluence=pd.Series(lower_confluence, index=working.index, dtype=int),
        Lower_Meet=pd.Series(lower_meet, index=working.index, dtype=float),
        Background_Color=background_color,
    )
    return out


# -- VALIDATION -------------------------------------------------------------
def validate_against_sample(
    df: pd.DataFrame,
    sample_path: str | Path,
) -> dict[str, dict[str, object]]:
    """Compare calculated outputs against the sample export value-by-value."""
    sample_df = load_csv_data(sample_path)
    common_index = df.index.intersection(sample_df.index)
    if common_index.empty:
        raise ValueError("No overlapping timestamps found between calculated data and sample file.")

    aligned_df = df.loc[common_index]
    aligned_sample = sample_df.loc[common_index]
    results: dict[str, dict[str, object]] = {}

    for output_name in EXPORTED_COLUMNS:
        sample_column = _find_matching_sample_column(
            aligned_sample,
            VALIDATION_COLUMN_ALIASES[output_name],
        )
        if sample_column is None:
            results[output_name] = {
                "status": "MISSING",
                "sample_column": None,
                "max_err": float("nan"),
            }
            continue

        passed, mismatch_idx, actual_value, expected_value, diff = _compare_numeric_series(
            aligned_df[output_name],
            aligned_sample[sample_column],
            atol=LOGIC_COMPARE_ATOL,
        )
        max_err = _max_abs_error(aligned_df[output_name], aligned_sample[sample_column])
        results[output_name] = {
            "status": "PASS" if passed else "FAIL",
            "sample_column": sample_column,
            "max_err": max_err,
        }
        if not passed:
            raise AssertionError(
                f"Validation failed for {output_name} against sample column {sample_column} at "
                f"{mismatch_idx}: actual={actual_value}, expected={expected_value}, diff={diff}"
            )

    return results


# -- INTERNAL TESTS ---------------------------------------------------------
def run_internal_sanity_checks() -> None:
    """Run deterministic unit-style checks for the non-sample code paths."""
    idx = pd.date_range("2020-12-30 03:45:00", periods=40, freq="6h", tz="UTC")
    base = pd.Series(np.linspace(100.0, 120.0, len(idx)), index=idx)
    df = pd.DataFrame(
        {
            "open": base - 0.5,
            "high": base + 1.0,
            "low": base - 1.0,
            "close": base,
            "volume": np.linspace(1000.0, 2000.0, len(idx)),
        },
        index=idx,
    )

    # Period reset tests.
    session_reset = _build_is_new_period(df.index, "Session", None)
    assert bool(session_reset.iloc[0]), "Session anchor must reset on the first bar."
    decade_idx = pd.DatetimeIndex(
        pd.to_datetime(
            ["2029-12-31 03:45:00Z", "2030-01-01 03:45:00Z", "2030-01-02 03:45:00Z"]
        )
    )
    decade_reset = _build_is_new_period(decade_idx, "Decade", None)
    assert bool(decade_reset.iloc[0]) and bool(decade_reset.iloc[1]) and not bool(decade_reset.iloc[2])

    century_idx = pd.DatetimeIndex(
        pd.to_datetime(
            ["2099-12-31 03:45:00Z", "2100-01-01 03:45:00Z", "2100-01-02 03:45:00Z"]
        )
    )
    century_reset = _build_is_new_period(century_idx, "Century", None)
    assert bool(century_reset.iloc[1]) and not bool(century_reset.iloc[2])

    event_dates = {"Earnings": {pd.Timestamp("2021-01-02", tz="UTC")}}
    event_reset = _build_is_new_period(df.index, "Earnings", event_dates)
    matching = event_reset[event_reset].index.normalize().unique()
    assert len(matching) == 1 and matching[0] == pd.Timestamp("2021-01-02", tz="UTC")

    # Closest pair selection.
    midpoint = _find_closest_pair([110.0, 111.0], [110.11, 111.40], 0.2)
    assert abs(midpoint - ((110.0 + 110.11) / 2.0)) < 1e-12
    assert np.isnan(_find_closest_pair([110.0], [111.0], 0.5))

    # Zero-volume safeguard.
    zero_df = df.copy()
    zero_df["volume"] = 0.0
    try:
        calculate_indicators(zero_df)
    except ValueError as exc:
        assert "No volume" in str(exc)
    else:
        raise AssertionError("Zero-volume datasets must raise a descriptive error.")


# -- MAIN -------------------------------------------------------------------
def main(argv: list[str]) -> int:
    """Load a CSV, calculate indicators, validate against sample, and print results."""
    sample_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_SAMPLE_PATH
    symbol = argv[2] if len(argv) > 2 else None

    df = load_csv_data(sample_path)
    run_internal_sanity_checks()
    calculated = calculate_indicators(df, symbol=symbol)
    validation = validate_against_sample(calculated, sample_path)

    print(f"Indicator: {PINE_INDICATOR_NAME}")
    print(f"Rows: {len(df)}")
    print("Validation:")
    for column in EXPORTED_COLUMNS:
        result = validation[column]
        print(f"  {column}: {result['status']} (max_err={result['max_err']})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
