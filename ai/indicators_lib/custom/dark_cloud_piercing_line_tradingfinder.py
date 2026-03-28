"""
# ============================================================
# INDICATOR: Dark Cloud [TradingFinder] Piercing Line - Reversal chart Pattern
# Converted from Pine Script v5 | 2026-03-20
# Original Pine author: TradingFinder
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "Dark Cloud [TradingFinder] Piercing Line - Reversal chart Pattern"
PINE_VERSION = "v5"
PINE_AUTHOR = "TradingFinder"

DEFAULT_SHOW_DARK_CLOUD = True
DEFAULT_SHOW_PIERCING_LINE = True

MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\Dark_Cloud_TradingFinder.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

NORMALIZED_OUTPUT_COLUMNS = (
    "strong_dark_cloud",
    "weak_dark_cloud",
    "strong_piercing_line",
    "weak_piercing_line",
)

EXCEL_OUTPUT_COLUMNS = (
    "Strong_Dark_Cloud",
    "Weak_Dark_Cloud",
    "Strong_Piercing_Line",
    "Weak_Piercing_Line",
    "Bearish_Pin_Bar_Candle_Color",
    "Bearish_Pin_Bar_Candle_Color_2",
)

VALIDATION_COLUMN_ALIASES = {
    "Strong_Dark_Cloud": ("Strong_Dark_Cloud",),
    "Weak_Dark_Cloud": ("Weak_Dark_Cloud",),
    "Strong_Piercing_Line": ("Strong_Piercing_Line",),
    "Weak_Piercing_Line": ("Weak_Piercing_Line",),
    "Bearish_Pin_Bar_Candle_Color": ("Bearish_Pin_Bar_Candle_Color",),
    "Bearish_Pin_Bar_Candle_Color_2": ("Bearish_Pin_Bar_Candle_Color_2",),
}


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


# -- INDICATOR ENGINE -------------------------------------------------------
def _encode_tradingview_signal(signal: pd.Series, applicable: pd.Series) -> pd.Series:
    """
    Encode Pine-like output columns as:
    - 1.0 when signal is true
    - 0.0 when the bar is applicable but signal is false
    - NaN when the bar is not applicable
    """
    encoded = pd.Series(np.nan, index=signal.index, dtype=float)
    encoded.loc[applicable] = 0.0
    encoded.loc[signal] = 1.0
    return encoded


def calculate_indicators(
    df: pd.DataFrame,
    show_dark_cloud: bool = DEFAULT_SHOW_DARK_CLOUD,
    show_piercing_line: bool = DEFAULT_SHOW_PIERCING_LINE,
) -> pd.DataFrame:
    """
    Replicate the TradingFinder Dark Cloud / Piercing Line indicator exactly.

    Export-aligned numeric outputs follow the sample file semantics:
    - 1.0 when the pattern fires
    - 0.0 when the pattern family is applicable on that bar but the pattern is false
    - NaN when the pattern family is not applicable on that bar
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")

    working = df.copy().sort_index()

    open_ = working["open"]
    high = working["high"]
    low = working["low"]
    close = working["close"]

    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    candle_range = high - low
    candle_body = close - open_

    cod_pos_candle = candle_body > 0
    cod_neg_candle = candle_body < 0

    cod_full_body = pd.Series(False, index=working.index)
    nonzero_range = candle_range != 0
    cod_full_body.loc[nonzero_range] = (
        (candle_body.loc[nonzero_range] / candle_range.loc[nonzero_range]).abs() > 0.6
    )

    prev_mid = prev_low + (prev_high - prev_low) * 0.5

    # Dark Cloud
    cod_dc1 = open_ >= prev_close
    cod_dc2 = open_ >= prev_high
    cod_dc3 = high > prev_high
    first_check_dc = cod_pos_candle.shift(1, fill_value=False) & cod_neg_candle
    cod_semi_cloud = (close < prev_close) & (close > prev_mid)
    cod_full_cloud = close <= prev_mid

    dark_applicable = first_check_dc & bool(show_dark_cloud)

    weak_dark_cloud = dark_applicable & (
        (
            cod_dc1
            & cod_dc3
            & cod_full_body
            & cod_full_body.shift(1, fill_value=False)
            & cod_semi_cloud
        )
        | (
            cod_dc2
            & cod_dc3
            & cod_full_body
            & cod_full_body.shift(1, fill_value=False)
            & cod_semi_cloud
        )
        | (
            cod_dc1
            & cod_dc3
            & cod_full_body
            & cod_full_body.shift(1, fill_value=False)
            & cod_full_cloud
        )
    )

    strong_dark_cloud = dark_applicable & (
        cod_dc2
        & cod_dc3
        & cod_full_body
        & cod_full_body.shift(1, fill_value=False)
        & cod_full_cloud
    )

    weak_dark_cloud = weak_dark_cloud & ~strong_dark_cloud

    # Piercing Line
    cod_pl1 = open_ <= prev_close
    cod_pl2 = open_ <= prev_low
    cod_pl3 = low < prev_low
    first_check_pl = cod_pos_candle & cod_neg_candle.shift(1, fill_value=False)
    cod_semi_cloud_pl = (close > prev_close) & (close < prev_mid)
    cod_full_cloud_pl = close >= prev_mid

    piercing_applicable = first_check_pl & bool(show_piercing_line)

    weak_piercing_line = piercing_applicable & (
        (
            cod_pl1
            & cod_pl3
            & cod_full_body
            & cod_full_body.shift(1, fill_value=False)
            & cod_semi_cloud_pl
        )
        | (
            cod_pl2
            & cod_pl3
            & cod_full_body
            & cod_full_body.shift(1, fill_value=False)
            & cod_semi_cloud_pl
        )
        | (
            cod_pl1
            & cod_pl3
            & cod_full_body
            & cod_full_body.shift(1, fill_value=False)
            & cod_full_cloud_pl
        )
    )

    strong_piercing_line = piercing_applicable & (
        cod_pl2
        & cod_pl3
        & cod_full_body
        & cod_full_body.shift(1, fill_value=False)
        & cod_full_cloud_pl
    )

    weak_piercing_line = weak_piercing_line & ~strong_piercing_line

    bearish_color = pd.Series(np.nan, index=working.index, dtype=float)
    bearish_color.loc[strong_dark_cloud | weak_dark_cloud] = 0.0

    bullish_color = pd.Series(np.nan, index=working.index, dtype=float)
    bullish_color.loc[strong_piercing_line | weak_piercing_line] = 1.0

    working = working.assign(
        candle_range=candle_range,
        candle_body=candle_body,
        cod_pos_candle=cod_pos_candle,
        cod_neg_candle=cod_neg_candle,
        cod_full_body=cod_full_body,
        prev_mid=prev_mid,
        first_check_dc=first_check_dc,
        first_check_pl=first_check_pl,
        strong_dark_cloud=strong_dark_cloud.fillna(False),
        weak_dark_cloud=weak_dark_cloud.fillna(False),
        strong_piercing_line=strong_piercing_line.fillna(False),
        weak_piercing_line=weak_piercing_line.fillna(False),
        Strong_Dark_Cloud=_encode_tradingview_signal(strong_dark_cloud, dark_applicable),
        Weak_Dark_Cloud=_encode_tradingview_signal(weak_dark_cloud, dark_applicable),
        Strong_Piercing_Line=_encode_tradingview_signal(
            strong_piercing_line,
            piercing_applicable,
        ),
        Weak_Piercing_Line=_encode_tradingview_signal(
            weak_piercing_line,
            piercing_applicable,
        ),
        Bearish_Pin_Bar_Candle_Color=bearish_color,
        Bearish_Pin_Bar_Candle_Color_2=bullish_color,
    )
    return working


# -- VALIDATION -------------------------------------------------------------
def _compare_numeric_series(
    actual: pd.Series,
    expected: pd.Series,
) -> tuple[bool, Optional[pd.Timestamp], Optional[float], Optional[float]]:
    """Compare numeric series exactly, treating NaN as equal to NaN."""
    actual_aligned, expected_aligned = actual.align(expected, join="inner")
    both_nan = actual_aligned.isna() & expected_aligned.isna()
    mismatch = ~both_nan & (
        actual_aligned.fillna(np.inf) != expected_aligned.fillna(np.inf)
    )
    if mismatch.any():
        first_idx = mismatch[mismatch].index[0]
        return False, first_idx, actual_aligned.loc[first_idx], expected_aligned.loc[first_idx]
    return True, None, None, None


def validate_against_sample(df: pd.DataFrame, sample_path: str | Path) -> None:
    """Compare exported Dark Cloud / Piercing outputs against the sample CSV exactly."""
    sample_df = load_csv_data(sample_path)
    common_index = df.index.intersection(sample_df.index)
    if common_index.empty:
        raise ValueError("No overlapping timestamps found between calculated data and sample file.")

    aligned_df = df.loc[common_index]
    aligned_sample = sample_df.loc[common_index]

    report_rows: list[tuple[str, str]] = []
    failures: list[tuple[str, str]] = []

    for output_name in EXCEL_OUTPUT_COLUMNS:
        sample_column = _find_matching_sample_column(
            aligned_sample,
            VALIDATION_COLUMN_ALIASES[output_name],
        )
        if sample_column is None:
            report_rows.append((output_name, "not available in sample"))
            failures.append((output_name, "missing sample column"))
            continue

        passed, mismatch_idx, actual_value, expected_value = _compare_numeric_series(
            aligned_df[output_name],
            aligned_sample[sample_column],
        )
        if passed:
            report_rows.append((output_name, "PASS exact"))
        else:
            report_rows.append(
                (
                    output_name,
                    f"FAIL first_mismatch={mismatch_idx} actual={actual_value} expected={expected_value}",
                )
            )
            failures.append(
                (
                    output_name,
                    f"numeric mismatch at {mismatch_idx}: actual={actual_value} expected={expected_value}",
                )
            )

    expected_counts = {
        "Strong_Dark_Cloud": int(aligned_sample["Strong_Dark_Cloud"].eq(1).sum()),
        "Weak_Dark_Cloud": int(aligned_sample["Weak_Dark_Cloud"].eq(1).sum()),
        "Strong_Piercing_Line": int(aligned_sample["Strong_Piercing_Line"].eq(1).sum()),
        "Weak_Piercing_Line": int(aligned_sample["Weak_Piercing_Line"].eq(1).sum()),
    }
    actual_counts = {
        "Strong_Dark_Cloud": int(aligned_df["Strong_Dark_Cloud"].eq(1).sum()),
        "Weak_Dark_Cloud": int(aligned_df["Weak_Dark_Cloud"].eq(1).sum()),
        "Strong_Piercing_Line": int(aligned_df["Strong_Piercing_Line"].eq(1).sum()),
        "Weak_Piercing_Line": int(aligned_df["Weak_Piercing_Line"].eq(1).sum()),
    }

    print("Validation report:")
    for indicator, status in report_rows:
        print(f"  {indicator}: {status}")

    print("\nSignal counts:")
    for key in expected_counts:
        print(f"  {key}: actual={actual_counts[key]} expected={expected_counts[key]}")

    if failures:
        lines = [f"{indicator}: {message}" for indicator, message in failures]
        raise AssertionError(
            "Dark Cloud / Piercing Line validation failed:\n" + "\n".join(lines)
        )

    print(
        "\nPASS: all exported Dark Cloud / Piercing Line outputs match the sample exactly."
    )


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """
    Verify first-bar behavior, strong-overrides-weak rules, zero-range safety,
    and non-overlap between bearish and bullish final signals.
    """
    required_columns = (
        "candle_range",
        "cod_full_body",
        "strong_dark_cloud",
        "weak_dark_cloud",
        "strong_piercing_line",
        "weak_piercing_line",
        "Strong_Dark_Cloud",
        "Weak_Dark_Cloud",
        "Strong_Piercing_Line",
        "Weak_Piercing_Line",
        "Bearish_Pin_Bar_Candle_Color",
        "Bearish_Pin_Bar_Candle_Color_2",
    )
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires calculated columns: " + ", ".join(missing)
        )

    first_row = df.iloc[0]
    if not pd.isna(first_row["Strong_Dark_Cloud"]):
        raise AssertionError("First row Strong_Dark_Cloud must be NaN because Pine uses [1].")
    if not pd.isna(first_row["Weak_Dark_Cloud"]):
        raise AssertionError("First row Weak_Dark_Cloud must be NaN because Pine uses [1].")
    if not pd.isna(first_row["Strong_Piercing_Line"]):
        raise AssertionError("First row Strong_Piercing_Line must be NaN because Pine uses [1].")
    if not pd.isna(first_row["Weak_Piercing_Line"]):
        raise AssertionError("First row Weak_Piercing_Line must be NaN because Pine uses [1].")

    zero_range_mask = df["candle_range"] == 0
    if zero_range_mask.any():
        if df.loc[zero_range_mask, "cod_full_body"].any():
            raise AssertionError("Zero-range candles must not be marked as full-body.")

    if (df["strong_dark_cloud"] & df["weak_dark_cloud"]).any():
        raise AssertionError("Strong Dark Cloud must override weak Dark Cloud on the same bar.")
    if (df["strong_piercing_line"] & df["weak_piercing_line"]).any():
        raise AssertionError(
            "Strong Piercing Line must override weak Piercing Line on the same bar."
        )

    bearish_any = df["strong_dark_cloud"] | df["weak_dark_cloud"]
    bullish_any = df["strong_piercing_line"] | df["weak_piercing_line"]
    if (bearish_any & bullish_any).any():
        raise AssertionError("Bearish and bullish final signals must not overlap on the same bar.")

    bearish_color_mismatch = df["Bearish_Pin_Bar_Candle_Color"].eq(0.0) != bearish_any
    if bearish_color_mismatch.any():
        mismatch_idx = bearish_color_mismatch[bearish_color_mismatch].index[0]
        raise AssertionError(
            f"Bearish color column mismatch at {mismatch_idx}: color must mark any Dark Cloud bar."
        )

    bullish_color_mismatch = df["Bearish_Pin_Bar_Candle_Color_2"].eq(1.0) != bullish_any
    if bullish_color_mismatch.any():
        mismatch_idx = bullish_color_mismatch[bullish_color_mismatch].index[0]
        raise AssertionError(
            f"Bullish color column mismatch at {mismatch_idx}: color must mark any Piercing Line bar."
        )

    print("Internal sanity checks: PASS")


# -- REPORTING --------------------------------------------------------------
def _build_signal_preview(df: pd.DataFrame, rows: int = 12) -> pd.DataFrame:
    """Return the first few rows where any final signal is present."""
    signal_mask = (
        df["strong_dark_cloud"]
        | df["weak_dark_cloud"]
        | df["strong_piercing_line"]
        | df["weak_piercing_line"]
    )
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "Strong_Dark_Cloud",
        "Weak_Dark_Cloud",
        "Strong_Piercing_Line",
        "Weak_Piercing_Line",
        "Bearish_Pin_Bar_Candle_Color",
        "Bearish_Pin_Bar_Candle_Color_2",
    ]
    existing_columns = [column for column in preview_columns if column in df.columns]
    return df.loc[signal_mask, existing_columns].head(rows)


def main(sample_path: str | Path = DEFAULT_SAMPLE_PATH) -> int:
    """Load the sample, calculate the indicator, validate parity, and print a preview."""
    df = load_csv_data(sample_path)
    calculated = calculate_indicators(df)
    run_internal_sanity_checks(calculated)
    validate_against_sample(calculated, sample_path)

    print("\nNormalized signal counts:")
    for column in NORMALIZED_OUTPUT_COLUMNS:
        print(f"  {column}: {int(calculated[column].sum())}")

    print("\nFirst signal rows:")
    print(_build_signal_preview(calculated).to_string(index=False))
    return 0


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    raise SystemExit(main(input_path))
