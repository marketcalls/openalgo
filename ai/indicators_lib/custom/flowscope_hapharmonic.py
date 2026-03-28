"""
# ============================================================
# INDICATOR: FlowScope [Hapharmonic]
# Converted from Pine Script v6 | 2026-03-20
# Original Pine author: Hapharmonic
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "FlowScope [Hapharmonic]"
PINE_SHORT_NAME = "Hapharmonic - FlowScope"
PINE_AUTHOR = "Hapharmonic"

DEFAULT_GROUP_SIZE = 1
DEFAULT_MAX_PROFILE_BOXES = 50
DEFAULT_SHOW_CUSTOM_CANDLE = True

# TradingView exported `barcolor(color.new(color.black, 100))` as this integer
# in the provided sample. The chart's profile boxes/lines are not exported.
DEFAULT_BAR_COLOR_CODE = 4536886

MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\FlowScope_Hapharmonic.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

OUTPUT_COLUMNS = (
    "show_custom_candle",
    "bar_color_code",
    "Bar_Color",
)

VALIDATION_COLUMN_ALIASES = {
    "Bar_Color": ("Bar_Color",),
    "bar_color_code": ("Bar_Color",),
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
def calculate_indicators(
    df: pd.DataFrame,
    show_custom_candle: bool = DEFAULT_SHOW_CUSTOM_CANDLE,
    group_size: int = DEFAULT_GROUP_SIZE,
    max_profile_boxes: int = DEFAULT_MAX_PROFILE_BOXES,
    bar_color_code: int = DEFAULT_BAR_COLOR_CODE,
) -> pd.DataFrame:
    """
    Replicate the exported FlowScope output that is available in the CSV.

    Important limitation:
    The Pine script's core profile rendering depends on
    `request.security_lower_tf(..., "1", ...)` arrays and TradingView drawing
    objects (`box.new`, `line.new`). Those 1-minute arrays are not present in
    the provided CSV, and the drawings are not exported into tabular output.

    The only exported output column present in the sample is `Bar_Color`, which
    comes from:
        barcolor(showWickInput ? color.new(color.black, 100) : na)

    With the default `showWickInput=true`, the sample exports a constant
    `Bar_Color=4536886` on every row. This function reproduces that exact
    exported behavior.
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")
    if group_size < 1 or group_size > 10:
        raise ValueError("group_size must stay within the Pine input range [1, 10].")
    if max_profile_boxes < 5 or max_profile_boxes > 200:
        raise ValueError("max_profile_boxes must stay within the Pine input range [5, 200].")

    working = df.copy().sort_index()

    exported_bar_color = pd.Series(np.nan, index=working.index, dtype=float)
    if show_custom_candle:
        exported_bar_color.loc[:] = float(bar_color_code)

    working = working.assign(
        show_custom_candle=bool(show_custom_candle),
        bar_color_code=exported_bar_color,
        Bar_Color=exported_bar_color,
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
    """Compare exported FlowScope outputs against the sample CSV exactly."""
    sample_df = load_csv_data(sample_path)
    common_index = df.index.intersection(sample_df.index)
    if common_index.empty:
        raise ValueError("No overlapping timestamps found between calculated data and sample file.")

    aligned_df = df.loc[common_index]
    aligned_sample = sample_df.loc[common_index]

    report_rows: list[tuple[str, str]] = []
    failures: list[tuple[str, str]] = []

    for output_name in ("Bar_Color",):
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

    print("Validation report:")
    for indicator, status in report_rows:
        print(f"  {indicator}: {status}")

    actual_unique = sorted(aligned_df["Bar_Color"].dropna().unique().tolist())
    expected_unique = sorted(aligned_sample["Bar_Color"].dropna().unique().tolist())
    print("\nBar_Color uniques:")
    print(f"  actual={actual_unique}")
    print(f"  expected={expected_unique}")

    if failures:
        lines = [f"{indicator}: {message}" for indicator, message in failures]
        raise AssertionError("FlowScope validation failed:\n" + "\n".join(lines))

    print("\nPASS: exported FlowScope `Bar_Color` matches the sample exactly.")


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """
    Verify alias consistency and the expected constant-color behavior under the
    default sample settings.
    """
    required_columns = ("show_custom_candle", "bar_color_code", "Bar_Color")
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires calculated columns: " + ", ".join(missing)
        )

    if not df["show_custom_candle"].all():
        raise AssertionError("Default FlowScope export expects show_custom_candle=True on all rows.")

    if not np.array_equal(df["bar_color_code"].to_numpy(), df["Bar_Color"].to_numpy()):
        raise AssertionError("bar_color_code must equal Bar_Color exactly.")

    non_null_unique = pd.unique(df["Bar_Color"].dropna())
    if len(non_null_unique) != 1:
        raise AssertionError("Expected a single constant exported Bar_Color value in the sample.")

    print("Internal sanity checks: PASS")


# -- REPORTING --------------------------------------------------------------
def _build_preview(df: pd.DataFrame, rows: int = 12) -> pd.DataFrame:
    """Return a compact preview of exported data."""
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "Bar_Color",
    ]
    existing_columns = [column for column in preview_columns if column in df.columns]
    head_rows = df.loc[:, existing_columns].head(rows // 2)
    tail_rows = df.loc[:, existing_columns].tail(rows - len(head_rows))
    return pd.concat([head_rows, tail_rows])


def main(sample_path: str | Path = DEFAULT_SAMPLE_PATH) -> int:
    """Load the sample, calculate the exported output, validate parity, and print a preview."""
    df = load_csv_data(sample_path)
    calculated = calculate_indicators(df)
    run_internal_sanity_checks(calculated)
    validate_against_sample(calculated, sample_path)

    print("\nPreview rows:")
    print(_build_preview(calculated).to_string(index=False))
    return 0


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    raise SystemExit(main(input_path))
