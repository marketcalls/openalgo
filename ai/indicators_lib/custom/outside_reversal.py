"""
# ============================================================
# INDICATOR: OutsideReversal
# Converted from Pine Script | 2026-03-20
# Original Pine author: Cristian.D
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "OutsideReversal"
PINE_SHORT_NAME = "OReversal"
PINE_AUTHOR = "Cristian.D"

EXCHANGE_TIMEZONE = "Asia/Kolkata"
MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\NSE_BANKNIFTY_60_5568bars.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

OUTPUT_COLUMNS = (
    "reversal_long",
    "reversal_short",
    "background_color_code",
    "Outside_Reversal_ReversalLong",
    "Outside_Reversal_ReversalShort",
    "Outside_Reversal_Background_Color",
)

VALIDATION_COLUMN_ALIASES = {
    "reversal_long": ("Outside_Reversal_ReversalLong",),
    "reversal_short": ("Outside_Reversal_ReversalShort",),
    "background_color_code": ("Outside_Reversal_Background_Color",),
    "Outside_Reversal_ReversalLong": ("Outside_Reversal_ReversalLong",),
    "Outside_Reversal_ReversalShort": ("Outside_Reversal_ReversalShort",),
    "Outside_Reversal_Background_Color": ("Outside_Reversal_Background_Color",),
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


def _find_matching_sample_column(sample_df: pd.DataFrame, aliases: Iterable[str]) -> Optional[str]:
    """Resolve the matching sample column for a given indicator output."""
    normalized_columns = {_normalize_name(column): column for column in sample_df.columns}

    for alias in aliases:
        alias_key = _normalize_name(alias)
        if alias_key in normalized_columns:
            return normalized_columns[alias_key]

    return None


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replicate the Pine Outside Reversal indicator.

    Pine formulas:
    - ReversalLong  = low < low[1] and close > high[1] and open < close[1]
    - ReversalShort = high > high[1] and close < low[1] and open > open[1]

    The background color is encoded numerically for Excel parity:
    - 0.0 when ReversalLong is true
    - 1.0 when ReversalShort is true
    - NaN otherwise
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")

    working = df.copy().sort_index()

    reversal_long = (
        (working["low"] < working["low"].shift(1))
        & (working["close"] > working["high"].shift(1))
        & (working["open"] < working["close"].shift(1))
    ).fillna(False)

    reversal_short = (
        (working["high"] > working["high"].shift(1))
        & (working["close"] < working["low"].shift(1))
        & (working["open"] > working["open"].shift(1))
    ).fillna(False)

    background_color_code = pd.Series(np.nan, index=working.index, dtype=float)
    background_color_code = background_color_code.mask(reversal_long, 0.0)
    background_color_code = background_color_code.mask(reversal_short, 1.0)

    working = working.assign(
        reversal_long=reversal_long,
        reversal_short=reversal_short,
        background_color_code=background_color_code,
        Outside_Reversal_ReversalLong=reversal_long.astype(int),
        Outside_Reversal_ReversalShort=reversal_short.astype(int),
        Outside_Reversal_Background_Color=background_color_code,
    )
    return working


# -- VALIDATION -------------------------------------------------------------
def _compare_boolean_series(actual: pd.Series, expected: pd.Series) -> tuple[bool, Optional[pd.Timestamp]]:
    """Compare two boolean-like series exactly."""
    actual_bool = actual.fillna(False).astype(bool)
    expected_bool = expected.fillna(0).astype(float) != 0
    mismatch = actual_bool != expected_bool
    if mismatch.any():
        return False, mismatch[mismatch].index[0]
    return True, None


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
    """
    Compare Outside Reversal outputs against the sample CSV value-by-value and
    raise AssertionError on the first mismatch for any overlapping column.
    """
    sample_df = load_csv_data(sample_path)
    common_index = df.index.intersection(sample_df.index)
    if common_index.empty:
        raise ValueError("No overlapping timestamps found between calculated data and sample file.")

    aligned_df = df.loc[common_index]
    aligned_sample = sample_df.loc[common_index]

    report_rows = []
    failures = []

    for output_name in OUTPUT_COLUMNS:
        sample_column = _find_matching_sample_column(
            aligned_sample,
            VALIDATION_COLUMN_ALIASES[output_name],
        )
        if sample_column is None:
            report_rows.append((output_name, "not available in sample"))
            continue

        if output_name in ("reversal_long", "reversal_short", "Outside_Reversal_ReversalLong", "Outside_Reversal_ReversalShort"):
            passed, mismatch_idx = _compare_boolean_series(aligned_df[output_name], aligned_sample[sample_column])
            if passed:
                report_rows.append((output_name, "PASS exact"))
            else:
                report_rows.append((output_name, f"FAIL first_mismatch={mismatch_idx}"))
                failures.append((output_name, f"boolean mismatch at {mismatch_idx}"))
        else:
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

    print("Validation report:")
    for indicator, status in report_rows:
        print(f"  {indicator}: {status}")

    if failures:
        lines = [f"{indicator}: {message}" for indicator, message in failures]
        raise AssertionError("Outside Reversal validation failed:\n" + "\n".join(lines))

    print("\nPASS: all overlapping Outside Reversal outputs match the sample exactly.")


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """
    Verify first-bar behavior and confirm that long and short do not both fire
    on the same row in the current sample logic.
    """
    required_columns = (
        "reversal_long",
        "reversal_short",
        "background_color_code",
        "Outside_Reversal_ReversalLong",
        "Outside_Reversal_ReversalShort",
        "Outside_Reversal_Background_Color",
    )
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires these columns to exist: "
            + ", ".join(missing)
        )

    first_row = df.iloc[0]
    if bool(first_row["reversal_long"]) or bool(first_row["reversal_short"]):
        raise AssertionError("First row must be False for both signals because Pine uses [1].")

    if pd.notna(first_row["background_color_code"]):
        raise AssertionError("First row background_color_code must be NaN because Pine uses [1].")

    both_signals = df["reversal_long"] & df["reversal_short"]
    if both_signals.any():
        first_idx = both_signals[both_signals].index[0]
        raise AssertionError(
            f"Long and short both triggered on the same row at {first_idx}. "
            "If this occurs, Pine's ternary gives long precedence in bgcolor()."
        )

    expected_background = pd.Series(np.nan, index=df.index, dtype=float)
    expected_background = expected_background.mask(df["reversal_long"], 0.0)
    expected_background = expected_background.mask(df["reversal_short"], 1.0)
    if not _compare_numeric_series(df["background_color_code"], expected_background)[0]:
        raise AssertionError("background_color_code does not match the expected long/short encoding.")

    print("Internal sanity checks:")
    print("PASS first row stays False/NaN because the indicator references [1]")
    print("PASS no rows trigger both reversal_long and reversal_short in the sample")
    print("PASS background_color_code matches the Pine ternary encoding")


# -- MAIN -------------------------------------------------------------------
def main(sample_path: str | Path) -> None:
    """Load CSV, calculate Outside Reversal, validate, and print a compact summary."""
    sample_df = load_csv_data(sample_path)
    market_df = sample_df.loc[:, list(REQUIRED_PRICE_COLUMNS)].copy()
    indicator_df = calculate_indicators(market_df)

    run_internal_sanity_checks(indicator_df)
    validate_against_sample(indicator_df, sample_path)

    print("\nSignal counts:")
    print(f"  reversal_long : {int(indicator_df['reversal_long'].sum())}")
    print(f"  reversal_short: {int(indicator_df['reversal_short'].sum())}")

    preview_columns = [
        "open",
        "high",
        "low",
        "close",
        "reversal_long",
        "reversal_short",
        "background_color_code",
    ]
    print("\nIndicator preview:")
    print(indicator_df.loc[:, preview_columns].tail(10).to_string())


if __name__ == "__main__":
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    main(csv_path)
