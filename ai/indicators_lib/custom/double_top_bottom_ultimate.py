"""
# ============================================================
# INDICATOR: Double Top/Bottom - Ultimate (OS)
# Converted from Pine Script v4 | 2026-03-20
# Original Pine author: HeWhoMustNotBeNamed
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "Double Top/Bottom - Ultimate (OS)"
PINE_SHORT_NAME = "W/M - Ultimate(OS)"
PINE_AUTHOR = "HeWhoMustNotBeNamed"

DEFAULT_LENGTH = 10
DEFAULT_MAX_RISK_PER_REWARD = 30

MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\Double_TopBottom_Ultimate.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

NORMALIZED_OUTPUT_COLUMNS = (
    "double_top",
    "double_top_confirmation",
    "double_top_invalidation",
    "double_bottom",
    "double_bottom_confirmation",
    "double_bottom_invalidation",
)

EXCEL_OUTPUT_COLUMNS = (
    "Double_Top",
    "Double_Top_Confirmation",
    "Double_Top_Invalidation",
    "Double_Bottom",
    "Double_Bottom_Confirmation",
    "Double_Bottom_Invalidation",
)

VALIDATION_COLUMN_ALIASES = {
    "Double_Top": ("Double_Top",),
    "Double_Top_Confirmation": ("Double_Top_Confirmation",),
    "Double_Top_Invalidation": ("Double_Top_Invalidation",),
    "Double_Bottom": ("Double_Bottom",),
    "Double_Bottom_Confirmation": ("Double_Bottom_Confirmation",),
    "Double_Bottom_Invalidation": ("Double_Bottom_Invalidation",),
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


# -- CORE HELPERS -----------------------------------------------------------
def _current_is_strict_highest(high: np.ndarray, start: int, index: int) -> bool:
    """
    Mirror the sample's `highestbars(high, length) == 0` behavior.

    The current bar only counts as a pivot-high candidate when it is strictly
    greater than all earlier highs inside the lookback window.
    """
    if index == start:
        return True
    return bool(high[index] > np.max(high[start:index]))


def _current_is_strict_lowest(low: np.ndarray, start: int, index: int) -> bool:
    """
    Mirror the sample's `lowestbars(low, length) == 0` behavior.

    The current bar only counts as a pivot-low candidate when it is strictly
    lower than all earlier lows inside the lookback window.
    """
    if index == start:
        return True
    return bool(low[index] < np.min(low[start:index]))


def _add_to_zigzag_array(
    zigzag_values: list[float],
    zigzag_indexes: list[int],
    zigzag_dir: list[int],
    value: float,
    index: int,
    direction: int,
    max_array_size: int,
) -> None:
    """Replicate the Pine `add_to_array()` helper exactly."""
    if len(zigzag_values) < 2:
        mult = 1
    else:
        mult = 2 if direction * value > direction * zigzag_values[1] else 1

    zigzag_indexes.insert(0, index)
    zigzag_values.insert(0, value)
    zigzag_dir.insert(0, direction * mult)

    if len(zigzag_indexes) > max_array_size:
        zigzag_indexes.pop()
        zigzag_values.pop()
        zigzag_dir.pop()


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    length: int = DEFAULT_LENGTH,
    max_risk_per_reward: int = DEFAULT_MAX_RISK_PER_REWARD,
) -> pd.DataFrame:
    """
    Replicate the Pine Double Top/Bottom Ultimate state machine exactly enough
    to match the exported alert columns row-by-row.
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")
    if length < 5:
        raise ValueError("length must be >= 5 to match the Pine input constraints.")
    if not 5 <= max_risk_per_reward <= 100:
        raise ValueError("max_risk_per_reward must be between 5 and 100.")

    working = df.copy().sort_index()

    high = working["high"].to_numpy(dtype=float)
    low = working["low"].to_numpy(dtype=float)
    n_rows = len(working)

    zigzag_values: list[float] = []
    zigzag_indexes: list[int] = []
    zigzag_dir: list[int] = []
    max_array_size = 10

    double_pattern_values: list[float] = [np.nan, np.nan, np.nan]
    double_pattern_indexes: list[float] = [np.nan, np.nan, np.nan]
    double_pattern_dir: list[float] = [np.nan, np.nan, np.nan]

    double_top = np.zeros(n_rows, dtype=bool)
    double_bottom = np.zeros(n_rows, dtype=bool)
    double_top_confirmation = np.zeros(n_rows, dtype=bool)
    double_bottom_confirmation = np.zeros(n_rows, dtype=bool)
    double_top_invalidation = np.zeros(n_rows, dtype=bool)
    double_bottom_invalidation = np.zeros(n_rows, dtype=bool)

    pivot_high_candidate = np.full(n_rows, np.nan, dtype=float)
    pivot_low_candidate = np.full(n_rows, np.nan, dtype=float)
    dir_series = np.zeros(n_rows, dtype=int)
    latest_double_top_state = np.zeros(n_rows, dtype=bool)
    latest_double_bottom_state = np.zeros(n_rows, dtype=bool)
    active_lvalue = np.full(n_rows, np.nan, dtype=float)
    active_llvalue = np.full(n_rows, np.nan, dtype=float)

    prev_dir = 0
    prev_latest_double_top = False
    prev_latest_double_bottom = False
    prev_lvalue = np.nan
    prev_llvalue = np.nan

    for i in range(n_rows):
        start = max(0, i - length + 1)

        ph = high[i] if _current_is_strict_highest(high, start, i) else np.nan
        pl = low[i] if _current_is_strict_lowest(low, start, i) else np.nan
        pivot_high_candidate[i] = ph
        pivot_low_candidate[i] = pl

        current_dir = prev_dir
        ph_exists = not np.isnan(ph)
        pl_exists = not np.isnan(pl)
        if ph_exists and not pl_exists:
            current_dir = 1
        elif pl_exists and not ph_exists:
            current_dir = -1

        dir_series[i] = current_dir
        dir_changed = current_dir != prev_dir

        if ph_exists or pl_exists:
            value = ph if current_dir == 1 else pl
            if len(zigzag_values) == 0 or dir_changed:
                _add_to_zigzag_array(
                    zigzag_values,
                    zigzag_indexes,
                    zigzag_dir,
                    float(value),
                    i,
                    current_dir,
                    max_array_size,
                )
            elif (current_dir == 1 and value > zigzag_values[0]) or (
                current_dir == -1 and value < zigzag_values[0]
            ):
                zigzag_values.pop(0)
                zigzag_indexes.pop(0)
                zigzag_dir.pop(0)
                _add_to_zigzag_array(
                    zigzag_values,
                    zigzag_indexes,
                    zigzag_dir,
                    float(value),
                    i,
                    current_dir,
                    max_array_size,
                )

        current_double_top = False
        current_double_bottom = False
        if len(zigzag_values) >= 4:
            value = zigzag_values[1]
            high_low = zigzag_dir[1]

            lvalue = zigzag_values[2]
            lhigh_low = zigzag_dir[2]

            llvalue = zigzag_values[3]
            llhigh_low = zigzag_dir[3]

            risk = abs(value - llvalue)
            reward = abs(value - lvalue)
            risk_per_reward = (
                risk * 100.0 / (risk + reward) if (risk + reward) != 0 else np.inf
            )

            if (
                high_low == 1
                and llhigh_low == 2
                and lhigh_low < 0
                and risk_per_reward < max_risk_per_reward
            ):
                current_double_top = True
            if (
                high_low == -1
                and llhigh_low == -2
                and lhigh_low > 0
                and risk_per_reward < max_risk_per_reward
            ):
                current_double_bottom = True

            if current_double_top or current_double_bottom:
                double_pattern_values[0] = value
                double_pattern_values[1] = lvalue
                double_pattern_values[2] = llvalue

                double_pattern_indexes[0] = zigzag_indexes[1]
                double_pattern_indexes[1] = zigzag_indexes[2]
                double_pattern_indexes[2] = zigzag_indexes[3]

                double_pattern_dir[0] = high_low
                double_pattern_dir[1] = lhigh_low
                double_pattern_dir[2] = llhigh_low

        double_top[i] = current_double_top
        double_bottom[i] = current_double_bottom

        current_lvalue = double_pattern_values[1]
        current_llvalue = double_pattern_values[2]
        active_lvalue[i] = current_lvalue
        active_llvalue[i] = current_llvalue

        latest_double_top = (
            True
            if current_double_top
            else False if current_double_bottom else prev_latest_double_top
        )
        latest_double_bottom = (
            True
            if current_double_bottom
            else False if current_double_top else prev_latest_double_bottom
        )
        latest_double_top_state[i] = latest_double_top
        latest_double_bottom_state[i] = latest_double_bottom

        dt_confirmation_value = 0
        db_confirmation_value = 0

        if (
            latest_double_top
            and i > 0
            and not np.isnan(current_lvalue)
            and not np.isnan(current_llvalue)
            and not np.isnan(prev_lvalue)
            and not np.isnan(prev_llvalue)
        ):
            # Pine's current-bar crossover behavior on a side flip matches the
            # current pattern level rather than the previous stored level.
            prev_lvalue_for_cross = (
                current_lvalue
                if current_double_top and (not prev_latest_double_top and prev_latest_double_bottom)
                else prev_lvalue
            )
            prev_llvalue_for_cross = (
                current_llvalue
                if current_double_top and (not prev_latest_double_top and prev_latest_double_bottom)
                else prev_llvalue
            )

            if low[i] < current_lvalue and low[i - 1] >= prev_lvalue_for_cross:
                dt_confirmation_value = 1
            elif high[i] > current_llvalue and high[i - 1] <= prev_llvalue_for_cross:
                dt_confirmation_value = -1

        if (
            latest_double_bottom
            and i > 0
            and not np.isnan(current_lvalue)
            and not np.isnan(current_llvalue)
            and not np.isnan(prev_lvalue)
            and not np.isnan(prev_llvalue)
        ):
            prev_lvalue_for_cross = (
                current_lvalue
                if current_double_bottom and (not prev_latest_double_bottom and prev_latest_double_top)
                else prev_lvalue
            )
            prev_llvalue_for_cross = (
                current_llvalue
                if current_double_bottom and (not prev_latest_double_bottom and prev_latest_double_top)
                else prev_llvalue
            )

            if high[i] > current_lvalue and high[i - 1] <= prev_lvalue_for_cross:
                db_confirmation_value = 1
            elif low[i] < current_llvalue and low[i - 1] >= prev_llvalue_for_cross:
                db_confirmation_value = -1

        double_top_confirmation[i] = dt_confirmation_value > 0
        double_bottom_confirmation[i] = db_confirmation_value > 0
        double_top_invalidation[i] = dt_confirmation_value < 0
        double_bottom_invalidation[i] = db_confirmation_value < 0

        prev_dir = current_dir
        prev_latest_double_top = latest_double_top
        prev_latest_double_bottom = latest_double_bottom
        prev_lvalue = current_lvalue
        prev_llvalue = current_llvalue

    working = working.assign(
        pivot_high_candidate=pivot_high_candidate,
        pivot_low_candidate=pivot_low_candidate,
        dir_series=dir_series,
        latest_double_top_state=latest_double_top_state,
        latest_double_bottom_state=latest_double_bottom_state,
        active_lvalue=active_lvalue,
        active_llvalue=active_llvalue,
        double_top=double_top,
        double_top_confirmation=double_top_confirmation,
        double_top_invalidation=double_top_invalidation,
        double_bottom=double_bottom,
        double_bottom_confirmation=double_bottom_confirmation,
        double_bottom_invalidation=double_bottom_invalidation,
        Double_Top=double_top.astype(int),
        Double_Top_Confirmation=double_top_confirmation.astype(int),
        Double_Top_Invalidation=double_top_invalidation.astype(int),
        Double_Bottom=double_bottom.astype(int),
        Double_Bottom_Confirmation=double_bottom_confirmation.astype(int),
        Double_Bottom_Invalidation=double_bottom_invalidation.astype(int),
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
    """Compare exported Double Top/Bottom outputs against the sample CSV exactly."""
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

    print("Validation report:")
    for indicator, status in report_rows:
        print(f"  {indicator}: {status}")

    print("\nSignal counts:")
    for output_name in EXCEL_OUTPUT_COLUMNS:
        actual_count = int(aligned_df[output_name].sum())
        expected_count = int(aligned_sample[output_name].sum())
        print(f"  {output_name}: actual={actual_count} expected={expected_count}")

    if failures:
        lines = [f"{indicator}: {message}" for indicator, message in failures]
        raise AssertionError(
            "Double Top/Bottom validation failed:\n" + "\n".join(lines)
        )

    print("\nPASS: all exported Double Top/Bottom outputs match the sample exactly.")


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """
    Verify exact alias consistency and mutually exclusive confirmation outputs
    for the same pattern side.
    """
    required_columns = (
        "double_top",
        "double_top_confirmation",
        "double_top_invalidation",
        "double_bottom",
        "double_bottom_confirmation",
        "double_bottom_invalidation",
        "Double_Top",
        "Double_Top_Confirmation",
        "Double_Top_Invalidation",
        "Double_Bottom",
        "Double_Bottom_Confirmation",
        "Double_Bottom_Invalidation",
    )
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires calculated columns: " + ", ".join(missing)
        )

    alias_checks = (
        ("double_top", "Double_Top"),
        ("double_top_confirmation", "Double_Top_Confirmation"),
        ("double_top_invalidation", "Double_Top_Invalidation"),
        ("double_bottom", "Double_Bottom"),
        ("double_bottom_confirmation", "Double_Bottom_Confirmation"),
        ("double_bottom_invalidation", "Double_Bottom_Invalidation"),
    )
    for normalized, alias in alias_checks:
        if not np.array_equal(df[normalized].astype(int).to_numpy(), df[alias].to_numpy(dtype=int)):
            raise AssertionError(f"{alias} must equal {normalized}.astype(int) exactly.")

    if (df["double_top_confirmation"] & df["double_top_invalidation"]).any():
        raise AssertionError("Double Top confirmation and invalidation cannot both fire on the same bar.")
    if (df["double_bottom_confirmation"] & df["double_bottom_invalidation"]).any():
        raise AssertionError("Double Bottom confirmation and invalidation cannot both fire on the same bar.")

    print("Internal sanity checks: PASS")


# -- REPORTING --------------------------------------------------------------
def _build_signal_preview(df: pd.DataFrame, rows: int = 15) -> pd.DataFrame:
    """Return the first few rows where any exported signal is active."""
    signal_mask = (
        df["double_top"]
        | df["double_top_confirmation"]
        | df["double_top_invalidation"]
        | df["double_bottom"]
        | df["double_bottom_confirmation"]
        | df["double_bottom_invalidation"]
    )
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "Double_Bottom",
        "Double_Bottom_Confirmation",
        "Double_Bottom_Invalidation",
        "Double_Top",
        "Double_Top_Confirmation",
        "Double_Top_Invalidation",
    ]
    return df.loc[signal_mask, preview_columns].head(rows)


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
