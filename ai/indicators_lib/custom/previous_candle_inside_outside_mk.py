"""
# ============================================================
# INDICATOR: Previous Candle + Inside/Outside [MK]
# Converted from Pine Script v5 | 2026-03-20
# Original Pine author: MK
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "Previous Candle + Inside/Outside [MK]"
PINE_VERSION = 5
PINE_AUTHOR = "MK"

I_MINTF3 = 720
SHOW_DAILY_HL = True
SHOW_INSIDE_BARS = True
SHOW_OUTSIDE_BARS = True
SHOW_PREVIOUS_HL_LABELS = True
SHOW_BULL_BEAR_LABELS = False

EXCHANGE_TIMEZONE = "Asia/Kolkata"
MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\NSE_BANKNIFTY_60_5568bars.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

LEVEL_COLUMNS = ("prev_high", "prev_low", "prev_mid")
RAW_COLUMNS = (
    "inside_bar_raw",
    "outside_bull_raw",
    "outside_bear_raw",
    "prev_high_break_raw",
    "prev_low_break_raw",
    "above_mid_raw",
    "below_mid_raw",
)
VISIBLE_COLUMNS = (
    "disp3_active",
    "inside_bar_visible",
    "outside_bull_visible",
    "outside_bear_visible",
    "ph_label_visible",
    "pl_label_visible",
    "bull_label_visible",
    "bear_label_visible",
)
OUTPUT_COLUMNS = LEVEL_COLUMNS + RAW_COLUMNS + VISIBLE_COLUMNS


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


def _find_matching_sample_column(sample_df: pd.DataFrame, aliases: Iterable[str]) -> Optional[str]:
    """Resolve the best sample column match for a given output name."""
    normalized_columns = {_normalize_name(column): column for column in sample_df.columns}
    for alias in aliases:
        alias_key = _normalize_name(alias)
        if alias_key in normalized_columns:
            return normalized_columns[alias_key]
    return None


def _infer_timeframe_minutes(df: pd.DataFrame) -> int:
    """
    Infer chart timeframe minutes from timestamp spacing.

    This is used only for the Pine `disp3` gate approximation.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("_infer_timeframe_minutes expects a DatetimeIndex.")

    diffs = df.index.to_series().diff().dropna().dt.total_seconds().div(60)
    positive_diffs = diffs[diffs > 0]
    if positive_diffs.empty:
        raise ValueError("Unable to infer timeframe minutes from fewer than 2 timestamps.")
    return int(round(float(positive_diffs.mode().iloc[0])))


def _is_dwm_timeframe(timeframe_minutes: int) -> bool:
    """Approximate Pine's timeframe.isdwm using minute granularity."""
    return timeframe_minutes >= 1440


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    timeframe_minutes: Optional[int] = None,
) -> pd.DataFrame:
    """
    Replicate the previous-candle levels and inside/outside logic from the MK indicator.

    `res = ''` is treated literally as the current chart timeframe, so all
    request.security(..., res, series[1]) values reduce to previous-bar values
    on the current input timeframe.
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")

    working = df.copy().sort_index()
    tf_minutes = timeframe_minutes if timeframe_minutes is not None else _infer_timeframe_minutes(working)
    is_intraday = tf_minutes < 1440
    is_dwm = _is_dwm_timeframe(tf_minutes)
    disp3_active_scalar = (is_intraday and tf_minutes >= I_MINTF3) or is_dwm

    prev_high = working["high"].shift(1) if SHOW_DAILY_HL else pd.Series(np.nan, index=working.index)
    prev_low = working["low"].shift(1) if SHOW_DAILY_HL else pd.Series(np.nan, index=working.index)
    prev_mid = (prev_high + prev_low) / 2.0

    prev_high_break_raw = (working["high"] > working["high"].shift(1)).fillna(False)
    prev_low_break_raw = (working["low"] < working["low"].shift(1)).fillna(False)

    inside_bar_raw = ((working["high"] <= prev_high) & (working["low"] >= prev_low)).fillna(False)
    outside_bear_raw = ((working["high"] > working["high"].shift(1)) & (working["close"] < prev_mid)).fillna(False)
    outside_bull_raw = ((working["low"] < working["low"].shift(1)) & (working["close"] > prev_mid)).fillna(False)
    above_mid_raw = (working["close"] > prev_mid).fillna(False)
    below_mid_raw = (working["close"] < prev_mid).fillna(False)

    is_last_bar = pd.Series(False, index=working.index)
    is_last_bar.iloc[-1] = True

    disp3_active = pd.Series(disp3_active_scalar, index=working.index, dtype=bool)
    inside_bar_visible = inside_bar_raw & disp3_active & SHOW_INSIDE_BARS
    outside_bull_visible = outside_bull_raw & disp3_active & SHOW_OUTSIDE_BARS & is_last_bar & (working["open"] < working["close"])
    outside_bear_visible = outside_bear_raw & disp3_active & SHOW_OUTSIDE_BARS & is_last_bar & (working["open"] > working["close"])
    ph_label_visible = prev_high_break_raw & disp3_active & SHOW_PREVIOUS_HL_LABELS
    pl_label_visible = prev_low_break_raw & disp3_active & SHOW_PREVIOUS_HL_LABELS
    bull_label_visible = above_mid_raw & disp3_active & SHOW_BULL_BEAR_LABELS
    bear_label_visible = below_mid_raw & disp3_active & SHOW_BULL_BEAR_LABELS

    working = working.assign(
        prev_high=prev_high,
        prev_low=prev_low,
        prev_mid=prev_mid,
        inside_bar_raw=inside_bar_raw,
        outside_bull_raw=outside_bull_raw,
        outside_bear_raw=outside_bear_raw,
        prev_high_break_raw=prev_high_break_raw,
        prev_low_break_raw=prev_low_break_raw,
        above_mid_raw=above_mid_raw,
        below_mid_raw=below_mid_raw,
        disp3_active=disp3_active,
        inside_bar_visible=inside_bar_visible,
        outside_bull_visible=outside_bull_visible,
        outside_bear_visible=outside_bear_visible,
        ph_label_visible=ph_label_visible,
        pl_label_visible=pl_label_visible,
        bull_label_visible=bull_label_visible,
        bear_label_visible=bear_label_visible,
    )
    return working


# -- VALIDATION -------------------------------------------------------------
def run_internal_sanity_checks(
    df: pd.DataFrame,
    timeframe_minutes: Optional[int] = None,
) -> None:
    """
    Validate previous-bar levels, raw-condition formulas, and literal default gate behavior.
    """
    missing = [column for column in OUTPUT_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires these output columns: " + ", ".join(missing)
        )

    tf_minutes = timeframe_minutes if timeframe_minutes is not None else _infer_timeframe_minutes(df)
    first_row = df.iloc[0]
    if pd.notna(first_row["prev_high"]) or pd.notna(first_row["prev_low"]) or pd.notna(first_row["prev_mid"]):
        raise AssertionError("First row previous-candle levels must be NaN because Pine references [1].")

    for column in RAW_COLUMNS + VISIBLE_COLUMNS:
        if bool(first_row[column]):
            raise AssertionError(f"First row `{column}` must be False because Pine references [1].")

    if not df["prev_high"].equals(df["high"].shift(1)):
        raise AssertionError("prev_high does not match high.shift(1).")

    if not df["prev_low"].equals(df["low"].shift(1)):
        raise AssertionError("prev_low does not match low.shift(1).")

    expected_mid = (df["high"].shift(1) + df["low"].shift(1)) / 2.0
    if not df["prev_mid"].equals(expected_mid):
        raise AssertionError("prev_mid does not match (high.shift(1) + low.shift(1)) / 2.")

    expected_inside = ((df["high"] <= df["prev_high"]) & (df["low"] >= df["prev_low"])).fillna(False)
    expected_outside_bull = ((df["low"] < df["low"].shift(1)) & (df["close"] > df["prev_mid"])).fillna(False)
    expected_outside_bear = ((df["high"] > df["high"].shift(1)) & (df["close"] < df["prev_mid"])).fillna(False)
    expected_prev_high_break = (df["high"] > df["high"].shift(1)).fillna(False)
    expected_prev_low_break = (df["low"] < df["low"].shift(1)).fillna(False)
    expected_above_mid = (df["close"] > df["prev_mid"]).fillna(False)
    expected_below_mid = (df["close"] < df["prev_mid"]).fillna(False)

    checks = {
        "inside_bar_raw": expected_inside,
        "outside_bull_raw": expected_outside_bull,
        "outside_bear_raw": expected_outside_bear,
        "prev_high_break_raw": expected_prev_high_break,
        "prev_low_break_raw": expected_prev_low_break,
        "above_mid_raw": expected_above_mid,
        "below_mid_raw": expected_below_mid,
    }
    for column, expected in checks.items():
        if not df[column].equals(expected):
            raise AssertionError(f"{column} does not match the exact Pine formula.")

    expected_disp3 = pd.Series(
        ((tf_minutes < 1440) and (tf_minutes >= I_MINTF3)) or _is_dwm_timeframe(tf_minutes),
        index=df.index,
        dtype=bool,
    )
    if not df["disp3_active"].equals(expected_disp3):
        raise AssertionError("disp3_active does not match the expected Pine timeframe gate.")

    expected_is_last = pd.Series(False, index=df.index)
    expected_is_last.iloc[-1] = True
    expected_inside_visible = expected_inside & expected_disp3 & SHOW_INSIDE_BARS
    expected_outside_bull_visible = expected_outside_bull & expected_disp3 & SHOW_OUTSIDE_BARS & expected_is_last & (df["open"] < df["close"])
    expected_outside_bear_visible = expected_outside_bear & expected_disp3 & SHOW_OUTSIDE_BARS & expected_is_last & (df["open"] > df["close"])
    expected_ph_label = expected_prev_high_break & expected_disp3 & SHOW_PREVIOUS_HL_LABELS
    expected_pl_label = expected_prev_low_break & expected_disp3 & SHOW_PREVIOUS_HL_LABELS
    expected_bull_label = expected_above_mid & expected_disp3 & SHOW_BULL_BEAR_LABELS
    expected_bear_label = expected_below_mid & expected_disp3 & SHOW_BULL_BEAR_LABELS

    visible_checks = {
        "inside_bar_visible": expected_inside_visible,
        "outside_bull_visible": expected_outside_bull_visible,
        "outside_bear_visible": expected_outside_bear_visible,
        "ph_label_visible": expected_ph_label,
        "pl_label_visible": expected_pl_label,
        "bull_label_visible": expected_bull_label,
        "bear_label_visible": expected_bear_label,
    }
    for column, expected in visible_checks.items():
        if not df[column].equals(expected):
            raise AssertionError(f"{column} does not match the literal Pine gate behavior.")

    if tf_minutes == 60:
        if df["disp3_active"].any():
            raise AssertionError("disp3_active should be False on the 60-minute sample with default settings.")
        for column in VISIBLE_COLUMNS[1:]:
            if df[column].any():
                raise AssertionError(f"{column} should remain False on the 60-minute sample.")

    print("Internal sanity checks:")
    print("PASS first row previous-candle levels stay NaN and booleans stay False")
    print("PASS prev_high, prev_low, and prev_mid match exact previous-bar formulas")
    print("PASS inside/outside/prev-break/mid raw conditions match exact Pine logic")
    print("PASS literal Pine visibility gates match default disp3 and bullbear behavior")


def validate_against_sample(
    df: pd.DataFrame,
    sample_path: str | Path,
    timeframe_minutes: Optional[int] = None,
) -> None:
    """
    Perform formula/internal validation and optionally report overlapping sample
    columns if matching aliases ever become available.
    """
    run_internal_sanity_checks(df, timeframe_minutes=timeframe_minutes)

    sample_df = load_csv_data(sample_path)
    common_index = df.index.intersection(sample_df.index)
    if common_index.empty:
        raise ValueError("No overlapping timestamps found between calculated data and sample file.")

    alias_map = {column: (column,) for column in OUTPUT_COLUMNS}
    overlaps = []
    for output_name, aliases in alias_map.items():
        sample_column = _find_matching_sample_column(sample_df, aliases)
        if sample_column is not None:
            overlaps.append((output_name, sample_column))

    print("\nSample validation:")
    if not overlaps:
        print(
            "  No matching exported columns for this exact indicator were found in the current CSV. "
            "Validation falls back to internal formula checks."
        )
        return

    print("  Matching sample columns were found and can be compared in a later revision:")
    for output_name, sample_column in overlaps:
        print(f"  {output_name} -> {sample_column}")


# -- MAIN -------------------------------------------------------------------
def main(sample_path: str | Path) -> None:
    """Load CSV, calculate outputs, run validation, and print a compact summary."""
    sample_df = load_csv_data(sample_path)
    market_df = sample_df.loc[:, list(REQUIRED_PRICE_COLUMNS)].copy()
    timeframe_minutes = _infer_timeframe_minutes(market_df)
    indicator_df = calculate_indicators(market_df, timeframe_minutes=timeframe_minutes)

    validate_against_sample(
        indicator_df,
        sample_path,
        timeframe_minutes=timeframe_minutes,
    )

    print("\nCounts:")
    print(f"  timeframe_minutes    : {timeframe_minutes}")
    print(f"  inside_bar_raw       : {int(indicator_df['inside_bar_raw'].sum())}")
    print(f"  outside_bull_raw     : {int(indicator_df['outside_bull_raw'].sum())}")
    print(f"  outside_bear_raw     : {int(indicator_df['outside_bear_raw'].sum())}")
    print(f"  prev_high_break_raw  : {int(indicator_df['prev_high_break_raw'].sum())}")
    print(f"  prev_low_break_raw   : {int(indicator_df['prev_low_break_raw'].sum())}")
    print(f"  inside_bar_visible   : {int(indicator_df['inside_bar_visible'].sum())}")
    print(f"  outside_bull_visible : {int(indicator_df['outside_bull_visible'].sum())}")
    print(f"  outside_bear_visible : {int(indicator_df['outside_bear_visible'].sum())}")

    preview_columns = [
        "open",
        "high",
        "low",
        "close",
        "prev_high",
        "prev_low",
        "prev_mid",
        "inside_bar_raw",
        "outside_bull_raw",
        "outside_bear_raw",
        "disp3_active",
    ]
    print("\nIndicator preview:")
    print(indicator_df.loc[:, preview_columns].tail(10).to_string())


if __name__ == "__main__":
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    main(csv_path)
