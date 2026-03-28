"""
# ============================================================
# INDICATOR: N Bar Reversal Detector [LuxAlgo]
# Converted from Pine Script v5 | 2026-03-20
# Original Pine author: LuxAlgo
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "N Bar Reversal Detector [LuxAlgo]"
PINE_SHORT_NAME = "LuxAlgo - N Bar Reversal Detector"
PINE_AUTHOR = "LuxAlgo"

DEFAULT_BRP_TYPE = "All"
DEFAULT_NUM_BARS = 7
DEFAULT_MIN_BARS = 0.50
DEFAULT_BRP_SR = "Level"
DEFAULT_TREND_TYPE = "None"
DEFAULT_TREND_FILTER = "Aligned"
DEFAULT_MA_TYPE = "HMA"
DEFAULT_MA_FAST_LENGTH = 50
DEFAULT_MA_SLOW_LENGTH = 200
DEFAULT_ATR_PERIOD = 10
DEFAULT_FACTOR = 3.0
DEFAULT_DONCHIAN_LENGTH = 13

MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\N_Bar_Reversal_LuxAlgo.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

EXPORTED_COLUMNS = (
    "ma_fast",
    "ma_fast_colorer",
    "ma_slow",
    "ma_slow_colorer",
    "fill_0_data",
    "plot_5",
    "fill_0_colorer",
    "plot_7",
    "Up_Trend",
    "Up_Trend_colorer",
    "Down_Trend",
    "Down_Trend_colorer",
    "Body_Middle",
    "fill_1_data",
    "plot_14",
    "fill_1_colorer",
    "plot_16",
    "fill_2_data",
    "plot_18",
    "fill_2_colorer",
    "plot_20",
    "Plot",
    "Plot_colorer",
    "Plot_2",
    "Plot_2_colorer",
    "fill_3_data",
    "plot_26",
    "fill_3_colorer",
    "plot_28",
)

VALIDATION_COLUMN_ALIASES = {name: (name,) for name in EXPORTED_COLUMNS}


# TradingView export color codes observed in the sample for the default colors.
COLOR_MA_FAST_BULL = 805306377
COLOR_MA_FAST_BEAR = 805306378
COLOR_MA_SLOW_BULL = 1157627913
COLOR_MA_SLOW_BEAR = 1157627914
COLOR_FILL0_TOP_BULL = 50331657
COLOR_FILL0_TOP_BEAR = 805306378
COLOR_FILL0_BOTTOM_BULL = 805306377
COLOR_FILL0_BOTTOM_BEAR = 50331658
COLOR_SUPERTREND_UP = 1157627913
COLOR_SUPERTREND_DOWN = 1157627914
COLOR_FILL1_TOP = 805306377
COLOR_FILL1_BOTTOM = 17
COLOR_FILL2_TOP = 17
COLOR_FILL2_BOTTOM = 805306378
COLOR_DONCHIAN_UPPER_BULL = 50331657
COLOR_DONCHIAN_UPPER_BEAR = 1157627914
COLOR_DONCHIAN_LOWER_BULL = 1157627913
COLOR_DONCHIAN_LOWER_BEAR = 50331658
COLOR_FILL3_TOP_BULL = 17
COLOR_FILL3_TOP_BEAR = 805306378
COLOR_FILL3_BOTTOM_BULL = 805306377
COLOR_FILL3_BOTTOM_BEAR = 17


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
    """Create a UTC timestamp index from `timestamp` or `datetime` columns."""
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


# -- CORE HELPERS -----------------------------------------------------------
def _sma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style SMA."""
    return series.rolling(window=length, min_periods=length).mean()


def _ema(series: pd.Series, length: int) -> pd.Series:
    """Pine-style EMA."""
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def _rma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style Wilder RMA with SMA seeding."""
    out = pd.Series(np.nan, index=series.index, dtype=float)
    if len(series) < length:
        return out
    out.iloc[length - 1] = series.iloc[:length].mean()
    alpha = 1.0 / length
    for i in range(length, len(series)):
        out.iloc[i] = alpha * series.iloc[i] + (1.0 - alpha) * out.iloc[i - 1]
    return out


def _wma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style WMA."""
    weights = np.arange(1, length + 1, dtype=float)
    weight_sum = weights.sum()
    return series.rolling(window=length, min_periods=length).apply(
        lambda x: float(np.dot(x, weights) / weight_sum),
        raw=True,
    )


def _hma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style HMA."""
    half_length = max(1, length // 2)
    sqrt_length = max(1, int(np.sqrt(length)))
    return _wma(2.0 * _wma(series, half_length) - _wma(series, length), sqrt_length)


def _vwma(source: pd.Series, volume: pd.Series, length: int) -> pd.Series:
    """Pine-style VWMA."""
    numerator = (source * volume).rolling(window=length, min_periods=length).sum()
    denominator = volume.rolling(window=length, min_periods=length).sum()
    return numerator / denominator


def _moving_average(source: pd.Series, volume: pd.Series, length: int, ma_type: str) -> pd.Series:
    """Dispatch Pine moving-average types."""
    if ma_type == "SMA":
        return _sma(source, length)
    if ma_type == "EMA":
        return _ema(source, length)
    if ma_type == "HMA":
        return _hma(source, length)
    if ma_type == "RMA":
        return _rma(source, length)
    if ma_type == "WMA":
        return _wma(source, length)
    if ma_type == "VWMA":
        return _vwma(source, volume, length)
    raise ValueError(f"Unsupported ma_type: {ma_type}")


def _supertrend(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    factor: float,
    atr_period: int,
) -> tuple[pd.Series, pd.Series]:
    """Replicate Pine ta.supertrend() closely enough for sample parity."""
    prev_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = _rma(true_range, atr_period)
    hl2 = (high + low) / 2.0

    upperband = hl2 + factor * atr
    lowerband = hl2 - factor * atr

    final_upper = pd.Series(np.nan, index=close.index, dtype=float)
    final_lower = pd.Series(np.nan, index=close.index, dtype=float)
    supertrend = pd.Series(np.nan, index=close.index, dtype=float)
    direction = pd.Series(np.nan, index=close.index, dtype=float)

    for i in range(len(close)):
        if np.isnan(atr.iloc[i]):
            continue

        if i == 0 or np.isnan(atr.iloc[i - 1]):
            final_upper.iloc[i] = upperband.iloc[i]
            final_lower.iloc[i] = lowerband.iloc[i]
            supertrend.iloc[i] = upperband.iloc[i]
            direction.iloc[i] = 1.0
            continue

        final_upper.iloc[i] = (
            upperband.iloc[i]
            if upperband.iloc[i] < final_upper.iloc[i - 1]
            or close.iloc[i - 1] > final_upper.iloc[i - 1]
            else final_upper.iloc[i - 1]
        )
        final_lower.iloc[i] = (
            lowerband.iloc[i]
            if lowerband.iloc[i] > final_lower.iloc[i - 1]
            or close.iloc[i - 1] < final_lower.iloc[i - 1]
            else final_lower.iloc[i - 1]
        )

        if supertrend.iloc[i - 1] == final_upper.iloc[i - 1]:
            if close.iloc[i] <= final_upper.iloc[i]:
                supertrend.iloc[i] = final_upper.iloc[i]
                direction.iloc[i] = 1.0
            else:
                supertrend.iloc[i] = final_lower.iloc[i]
                direction.iloc[i] = -1.0
        else:
            if close.iloc[i] >= final_lower.iloc[i]:
                supertrend.iloc[i] = final_lower.iloc[i]
                direction.iloc[i] = -1.0
            else:
                supertrend.iloc[i] = final_upper.iloc[i]
                direction.iloc[i] = 1.0

    if len(supertrend) > 0:
        supertrend.iloc[0] = np.nan

    return supertrend, direction


def _compute_reversal_patterns(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    num_bars: int,
    min_bars_fraction: float,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Replicate LuxAlgo's internal bullish/bearish reversal functions exactly.

    These signals are not exported in the provided CSV, but they are part of
    the indicator's core pattern logic and are returned for inspection.
    """
    n = len(close)
    bull_low = pd.Series(np.nan, index=close.index, dtype=float)
    bear_high = pd.Series(np.nan, index=close.index, dtype=float)
    bullish = pd.Series(False, index=close.index, dtype=bool)
    bearish = pd.Series(False, index=close.index, dtype=bool)

    open_v = open_.to_numpy(dtype=float)
    high_v = high.to_numpy(dtype=float)
    low_v = low.to_numpy(dtype=float)
    close_v = close.to_numpy(dtype=float)

    for t in range(n):
        if t < num_bars:
            continue

        # Bullish reversal
        current_bull_low = low_v[t - num_bars]
        bear_count = 0
        bull_reversal = np.nan
        for j in range(1, num_bars):
            i = t - j
            if high_v[i] > high_v[t - num_bars]:
                bull_reversal = False
                break
            bull_reversal = True
            current_bull_low = min(current_bull_low, low_v[i])
            if open_v[i] > close_v[i]:
                bear_count += 1
        bull_reversal = (bear_count / (num_bars - 1)) >= min_bars_fraction
        bull_low.iloc[t] = min(current_bull_low, low_v[t])
        bullish.iloc[t] = bool(bull_reversal and high_v[t] > high_v[t - num_bars])

        # Bearish reversal
        current_bear_high = high_v[t - num_bars]
        bull_count = 0
        bear_reversal = np.nan
        for j in range(1, num_bars):
            i = t - j
            if low_v[i] < low_v[t - num_bars]:
                bear_reversal = False
                break
            bear_reversal = True
            current_bear_high = max(current_bear_high, high_v[i])
            if open_v[i] < close_v[i]:
                bull_count += 1
        bear_reversal = (bull_count / (num_bars - 1)) >= min_bars_fraction
        bear_high.iloc[t] = max(current_bear_high, high_v[t])
        bearish.iloc[t] = bool(bear_reversal and low_v[t] < low_v[t - num_bars])

    return bull_low, bullish, bear_high, bearish


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    brp_type: str = DEFAULT_BRP_TYPE,
    num_bars: int = DEFAULT_NUM_BARS,
    min_bars: float = DEFAULT_MIN_BARS,
    brp_sr: str = DEFAULT_BRP_SR,
    trend_type: str = DEFAULT_TREND_TYPE,
    trend_filter: str = DEFAULT_TREND_FILTER,
    ma_type: str = DEFAULT_MA_TYPE,
    ma_fast_length: int = DEFAULT_MA_FAST_LENGTH,
    ma_slow_length: int = DEFAULT_MA_SLOW_LENGTH,
    atr_period: int = DEFAULT_ATR_PERIOD,
    factor: float = DEFAULT_FACTOR,
    donchian_length: int = DEFAULT_DONCHIAN_LENGTH,
) -> pd.DataFrame:
    """
    Replicate the exported LuxAlgo N-Bar Reversal columns exactly.

    The provided CSV exports trend-overlay plots/fills and color channels, but
    it does not export the bullish/bearish reversal label or line objects. This
    function reproduces the exported plot/fill columns exactly and also returns
    the internal bullish/bearish reversal booleans for inspection.
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")

    working = df.copy().sort_index()

    open_ = working["open"]
    high = working["high"]
    low = working["low"]
    close = working["close"]
    volume = working["volume"]

    ma_fast = _moving_average(close, volume, ma_fast_length, ma_type)
    ma_slow = _moving_average(close, volume, ma_slow_length, ma_type)
    ma_bullish = ma_fast > ma_slow

    supertrend, direction = _supertrend(high, low, close, factor, atr_period)

    upper = close.rolling(window=donchian_length, min_periods=donchian_length).max()
    lower = close.rolling(window=donchian_length, min_periods=donchian_length).min()
    os = pd.Series(0, index=working.index, dtype=int)
    for i in range(1, len(working)):
        os.iloc[i] = (
            1
            if upper.iloc[i] > upper.iloc[i - 1]
            else 0 if lower.iloc[i] < lower.iloc[i - 1] else os.iloc[i - 1]
        )

    body_middle = (open_ + close) / 2.0

    bull_low, bullish_reversal, bear_high, bearish_reversal = _compute_reversal_patterns(
        open_,
        high,
        low,
        close,
        num_bars,
        min_bars,
    )

    if trend_type == "Moving Average Cloud":
        c_down_trend = (
            (close < ma_fast) & (ma_fast < ma_slow)
            if trend_filter == "Aligned"
            else (close > ma_fast) & (ma_fast > ma_slow)
            if trend_filter == "Opposite"
            else pd.Series(True, index=working.index)
        )
        c_up_trend = (
            (close > ma_fast) & (ma_fast > ma_slow)
            if trend_filter == "Aligned"
            else (close < ma_fast) & (ma_fast < ma_slow)
            if trend_filter == "Opposite"
            else pd.Series(True, index=working.index)
        )
    elif trend_type == "Supertrend":
        c_down_trend = (
            direction > 0
            if trend_filter == "Aligned"
            else direction < 0
            if trend_filter == "Opposite"
            else pd.Series(True, index=working.index)
        )
        c_up_trend = (
            direction < 0
            if trend_filter == "Aligned"
            else direction > 0
            if trend_filter == "Opposite"
            else pd.Series(True, index=working.index)
        )
    elif trend_type == "Donchian Channels":
        c_down_trend = (
            os == 0
            if trend_filter == "Aligned"
            else os == 1
            if trend_filter == "Opposite"
            else pd.Series(True, index=working.index)
        )
        c_up_trend = (
            os == 1
            if trend_filter == "Aligned"
            else os == 0
            if trend_filter == "Opposite"
            else pd.Series(True, index=working.index)
        )
    else:
        c_down_trend = pd.Series(True, index=working.index)
        c_up_trend = pd.Series(True, index=working.index)

    bullish_reversal = bullish_reversal & c_up_trend
    bearish_reversal = bearish_reversal & c_down_trend

    enhanced_bull = close > high.shift(num_bars)
    normal_bull = close < high.shift(num_bars)
    enhanced_bear = close < low.shift(num_bars)
    normal_bear = close > low.shift(num_bars)

    bullish_pattern_start = bullish_reversal & ~bullish_reversal.shift(1, fill_value=False)
    bearish_pattern_start = bearish_reversal & ~bearish_reversal.shift(1, fill_value=False)

    if brp_type == "Enhanced":
        bullish_pattern_start &= enhanced_bull
        bearish_pattern_start &= enhanced_bear
    elif brp_type == "Normal":
        bullish_pattern_start &= normal_bull
        bearish_pattern_start &= normal_bear

    exported = working.assign(
        # Internal pattern outputs not available in the sample export.
        bull_low=bull_low,
        bear_high=bear_high,
        bullish_reversal=bullish_reversal,
        bearish_reversal=bearish_reversal,
        bullish_pattern_start=bullish_pattern_start,
        bearish_pattern_start=bearish_pattern_start,
        # Exported plot/fill data.
        ma_fast=np.nan if trend_type != "Moving Average Cloud" else ma_fast,
        ma_fast_colorer=np.where(ma_bullish, COLOR_MA_FAST_BULL, COLOR_MA_FAST_BEAR),
        ma_slow=np.nan if trend_type != "Moving Average Cloud" else ma_slow,
        ma_slow_colorer=np.where(ma_bullish, COLOR_MA_SLOW_BULL, COLOR_MA_SLOW_BEAR),
        fill_0_data=np.maximum(ma_fast, ma_slow),
        plot_5=np.minimum(ma_fast, ma_slow),
        fill_0_colorer=np.where(ma_bullish, COLOR_FILL0_TOP_BULL, COLOR_FILL0_TOP_BEAR),
        plot_7=np.where(ma_bullish, COLOR_FILL0_BOTTOM_BULL, COLOR_FILL0_BOTTOM_BEAR),
        Up_Trend=np.where((direction < 0) & (trend_type == "Supertrend"), supertrend, np.nan),
        Up_Trend_colorer=COLOR_SUPERTREND_UP,
        Down_Trend=np.where((direction >= 0) & (trend_type == "Supertrend"), supertrend, np.nan),
        Down_Trend_colorer=COLOR_SUPERTREND_DOWN,
        Body_Middle=np.where(trend_type == "Supertrend", body_middle, np.nan),
        fill_1_data=supertrend,
        plot_14=body_middle,
        fill_1_colorer=COLOR_FILL1_TOP,
        plot_16=COLOR_FILL1_BOTTOM,
        fill_2_data=body_middle,
        plot_18=supertrend,
        fill_2_colorer=COLOR_FILL2_TOP,
        plot_20=COLOR_FILL2_BOTTOM,
        Plot=np.where(trend_type == "Donchian Channels", upper, np.nan),
        Plot_colorer=np.where(os == 1, COLOR_DONCHIAN_UPPER_BULL, COLOR_DONCHIAN_UPPER_BEAR),
        Plot_2=np.where(trend_type == "Donchian Channels", lower, np.nan),
        Plot_2_colorer=np.where(os == 1, COLOR_DONCHIAN_LOWER_BULL, COLOR_DONCHIAN_LOWER_BEAR),
        fill_3_data=upper,
        plot_26=lower,
        fill_3_colorer=np.where(os == 1, COLOR_FILL3_TOP_BULL, COLOR_FILL3_TOP_BEAR),
        plot_28=np.where(os == 1, COLOR_FILL3_BOTTOM_BULL, COLOR_FILL3_BOTTOM_BEAR),
    )

    return exported


# -- VALIDATION -------------------------------------------------------------
def _compare_numeric_series(
    actual: pd.Series,
    expected: pd.Series,
    atol: float = 1e-9,
) -> tuple[bool, Optional[pd.Timestamp], Optional[float], Optional[float], Optional[float]]:
    """Compare numeric series with a small float tolerance, treating NaN as equal."""
    actual_aligned, expected_aligned = actual.align(expected, join="inner")
    both_nan = actual_aligned.isna() & expected_aligned.isna()

    actual_filled = actual_aligned.astype(float).fillna(np.inf)
    expected_filled = expected_aligned.astype(float).fillna(np.inf)
    mismatch = ~both_nan & ~np.isclose(actual_filled, expected_filled, atol=atol, rtol=0.0)

    if mismatch.any():
        first_idx = mismatch[mismatch].index[0]
        diff = abs(actual_aligned.loc[first_idx] - expected_aligned.loc[first_idx])
        return (
            False,
            first_idx,
            actual_aligned.loc[first_idx],
            expected_aligned.loc[first_idx],
            diff,
        )
    return True, None, None, None, None


def validate_against_sample(df: pd.DataFrame, sample_path: str | Path) -> None:
    """Compare exported LuxAlgo columns against the sample CSV."""
    sample_df = load_csv_data(sample_path)
    common_index = df.index.intersection(sample_df.index)
    if common_index.empty:
        raise ValueError("No overlapping timestamps found between calculated data and sample file.")

    aligned_df = df.loc[common_index]
    aligned_sample = sample_df.loc[common_index]

    report_rows: list[tuple[str, str]] = []
    failures: list[tuple[str, str]] = []

    for output_name in EXPORTED_COLUMNS:
        sample_column = _find_matching_sample_column(
            aligned_sample,
            VALIDATION_COLUMN_ALIASES[output_name],
        )
        if sample_column is None:
            report_rows.append((output_name, "not available in sample"))
            failures.append((output_name, "missing sample column"))
            continue

        passed, mismatch_idx, actual_value, expected_value, diff = _compare_numeric_series(
            aligned_df[output_name],
            aligned_sample[sample_column],
        )
        if passed:
            report_rows.append((output_name, "PASS"))
        else:
            report_rows.append(
                (
                    output_name,
                    f"FAIL first_mismatch={mismatch_idx} actual={actual_value} expected={expected_value} diff={diff}",
                )
            )
            failures.append(
                (
                    output_name,
                    f"mismatch at {mismatch_idx}: actual={actual_value} expected={expected_value} diff={diff}",
                )
            )

    print("Validation report:")
    for indicator, status in report_rows:
        print(f"  {indicator}: {status}")

    if failures:
        lines = [f"{indicator}: {message}" for indicator, message in failures]
        raise AssertionError("N Bar Reversal validation failed:\n" + "\n".join(lines))

    print("\nPASS: all exported LuxAlgo columns match the sample within floating tolerance.")


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """Verify internal consistency for key exported and derived series."""
    required_columns = (
        "fill_0_data",
        "plot_5",
        "fill_1_data",
        "plot_14",
        "fill_2_data",
        "plot_18",
        "fill_3_data",
        "plot_26",
        "bullish_reversal",
        "bearish_reversal",
    )
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires calculated columns: " + ", ".join(missing)
        )

    if not np.allclose(
        df["fill_1_data"].fillna(np.inf),
        df["plot_18"].fillna(np.inf),
        atol=1e-9,
        rtol=0.0,
    ):
        raise AssertionError("fill_1_data and plot_18 must both equal the hidden supertrend series.")

    if not np.allclose(
        df["plot_14"].fillna(np.inf),
        df["fill_2_data"].fillna(np.inf),
        atol=1e-9,
        rtol=0.0,
    ):
        raise AssertionError("plot_14 and fill_2_data must both equal the body midpoint.")

    overlap_count = int((df["bullish_reversal"] & df["bearish_reversal"]).sum())
    print(f"Internal sanity checks: PASS (bull/bear overlap bars={overlap_count})")


# -- REPORTING --------------------------------------------------------------
def _build_export_preview(df: pd.DataFrame, rows: int = 8) -> pd.DataFrame:
    """Return a compact preview of the exported columns."""
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "ma_fast",
        "ma_slow",
        "fill_0_data",
        "plot_5",
        "fill_1_data",
        "plot_14",
        "fill_3_data",
        "plot_26",
        "Bar_Color" if "Bar_Color" in df.columns else "plot_28",
    ]
    existing = [column for column in preview_columns if column in df.columns]
    return df.loc[:, existing].head(rows)


def _build_pattern_preview(df: pd.DataFrame, rows: int = 15) -> pd.DataFrame:
    """Return the first few internally detected bullish/bearish reversal rows."""
    mask = df["bullish_reversal"] | df["bearish_reversal"]
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "bullish_reversal",
        "bearish_reversal",
        "bullish_pattern_start",
        "bearish_pattern_start",
    ]
    return df.loc[mask, preview_columns].head(rows)


def main(sample_path: str | Path = DEFAULT_SAMPLE_PATH) -> int:
    """Load the sample, calculate the indicator, validate parity, and print previews."""
    df = load_csv_data(sample_path)
    calculated = calculate_indicators(df)
    run_internal_sanity_checks(calculated)
    validate_against_sample(calculated, sample_path)

    print("\nInternal reversal counts (not exported by sample):")
    print(f"  bullish_reversal: {int(calculated['bullish_reversal'].sum())}")
    print(f"  bearish_reversal: {int(calculated['bearish_reversal'].sum())}")
    print(f"  bullish_pattern_start: {int(calculated['bullish_pattern_start'].sum())}")
    print(f"  bearish_pattern_start: {int(calculated['bearish_pattern_start'].sum())}")

    print("\nExport preview:")
    print(_build_export_preview(calculated).to_string(index=False))

    print("\nInternal pattern preview:")
    print(_build_pattern_preview(calculated).to_string(index=False))
    return 0


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    raise SystemExit(main(input_path))
