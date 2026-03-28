"""
# ============================================================
# STRATEGY: Central Pivot Range (Indicator Port)
# Converted from Pine Script v5 | 2026-03-20
# Original Pine author: ajithcpas
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Dict, Iterable, Optional

import numpy as np
import pandas as pd


# ── PARAMETERS (match Pine Script defaults used for this port) ─────────────
PINE_INDICATOR_NAME = "Central Pivot Range"
PINE_SHORT_NAME = "CPR"
PINE_VERSION = 5
PINE_AUTHOR = "ajithcpas"

PINE_KIND = "Traditional"  # kind
PINE_CPR_TIMEFRAME = "Daily"  # cpr_time_frame
PINE_LOOK_BACK = 2  # look_back
PINE_USE_DAILY_BASED_VALUES = True  # is_daily_based

EXCHANGE_TIMEZONE = "Asia/Kolkata"
MISSING_VALUE_SENTINEL = 1e100
VALIDATION_TOLERANCE_PCT = 0.01
ZERO_VALUE_ABSOLUTE_TOLERANCE = 1e-9

DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\NSE_BANKNIFTY_60_5568bars.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

INDICATOR_ORDER = [
    "prev_day_open",
    "prev_day_high",
    "prev_day_low",
    "prev_day_close",
    "p",
    "bp",
    "tp",
    "r0_5",
    "s0_5",
    "r1",
    "s1",
    "r1_5",
    "s1_5",
    "r2",
    "s2",
    "r2_5",
    "s2_5",
    "r3",
    "s3",
    "r3_5",
    "s3_5",
    "r4",
    "s4",
    "r4_5",
    "s4_5",
    "r5",
    "s5",
    "dev_p",
    "dev_bp",
    "dev_tp",
    "dev_r1",
    "dev_s1",
]

COMPLETED_SESSION_COLUMNS = {
    "prev_day_open",
    "prev_day_high",
    "prev_day_low",
    "prev_day_close",
    "p",
    "bp",
    "tp",
    "r0_5",
    "s0_5",
    "r1",
    "s1",
    "r1_5",
    "s1_5",
    "r2",
    "s2",
    "r2_5",
    "s2_5",
    "r3",
    "s3",
    "r3_5",
    "s3_5",
    "r4",
    "s4",
    "r4_5",
    "s4_5",
    "r5",
    "s5",
}

INDICATOR_METADATA: Dict[str, Dict[str, str]] = {
    "prev_day_open": {
        "pine_formula": "open[1] on the prior daily session",
        "python_impl": "previous daily OHLC frame shifted by one session",
    },
    "prev_day_high": {
        "pine_formula": "high[1] on the prior daily session",
        "python_impl": "previous daily OHLC frame shifted by one session",
    },
    "prev_day_low": {
        "pine_formula": "low[1] on the prior daily session",
        "python_impl": "previous daily OHLC frame shifted by one session",
    },
    "prev_day_close": {
        "pine_formula": "close[1] on the prior daily session",
        "python_impl": "previous daily OHLC frame shifted by one session",
    },
    "p": {
        "pine_formula": "(prev_high + prev_low + prev_close) / 3",
        "python_impl": "mapped previous-session OHLC onto each intraday row",
    },
    "bp": {
        "pine_formula": "(prev_high + prev_low) / 2",
        "python_impl": "previous-session BC, then min(bp, tp) after Pine swap",
    },
    "tp": {
        "pine_formula": "2 * p - bp",
        "python_impl": "previous-session TC, then max(bp, tp) after Pine swap",
    },
    "r0_5": {
        "pine_formula": "(p + r1) / 2",
        "python_impl": "midpoint between pivot and r1",
    },
    "s0_5": {
        "pine_formula": "(p + s1) / 2",
        "python_impl": "midpoint between pivot and s1",
    },
    "r1": {
        "pine_formula": "2 * p - prev_low",
        "python_impl": "Traditional CPR resistance 1",
    },
    "s1": {
        "pine_formula": "2 * p - prev_high",
        "python_impl": "Traditional CPR support 1",
    },
    "r1_5": {
        "pine_formula": "(r1 + r2) / 2",
        "python_impl": "midpoint between r1 and r2",
    },
    "s1_5": {
        "pine_formula": "(s1 + s2) / 2",
        "python_impl": "midpoint between s1 and s2",
    },
    "r2": {
        "pine_formula": "p + (prev_high - prev_low)",
        "python_impl": "Traditional CPR resistance 2",
    },
    "s2": {
        "pine_formula": "p - (prev_high - prev_low)",
        "python_impl": "Traditional CPR support 2",
    },
    "r2_5": {
        "pine_formula": "(r2 + r3) / 2",
        "python_impl": "midpoint between r2 and r3",
    },
    "s2_5": {
        "pine_formula": "(s2 + s3) / 2",
        "python_impl": "midpoint between s2 and s3",
    },
    "r3": {
        "pine_formula": "2 * p + (prev_high - 2 * prev_low)",
        "python_impl": "Traditional CPR resistance 3",
    },
    "s3": {
        "pine_formula": "2 * p - (2 * prev_high - prev_low)",
        "python_impl": "Traditional CPR support 3",
    },
    "r3_5": {
        "pine_formula": "(r3 + r4) / 2",
        "python_impl": "midpoint between r3 and r4",
    },
    "s3_5": {
        "pine_formula": "(s3 + s4) / 2",
        "python_impl": "midpoint between s3 and s4",
    },
    "r4": {
        "pine_formula": "3 * p + (prev_high - 3 * prev_low)",
        "python_impl": "Traditional CPR resistance 4",
    },
    "s4": {
        "pine_formula": "3 * p - (3 * prev_high - prev_low)",
        "python_impl": "Traditional CPR support 4",
    },
    "r4_5": {
        "pine_formula": "(r4 + r5) / 2",
        "python_impl": "midpoint between r4 and r5",
    },
    "s4_5": {
        "pine_formula": "(s4 + s5) / 2",
        "python_impl": "midpoint between s4 and s5",
    },
    "r5": {
        "pine_formula": "4 * p + (prev_high - 4 * prev_low)",
        "python_impl": "Traditional CPR resistance 5",
    },
    "s5": {
        "pine_formula": "4 * p - (4 * prev_high - prev_low)",
        "python_impl": "Traditional CPR support 5",
    },
    "dev_p": {
        "pine_formula": "(curr_high + curr_low + curr_close) / 3",
        "python_impl": "running session high/low with current close",
    },
    "dev_bp": {
        "pine_formula": "(curr_high + curr_low) / 2 then min(dbc, dtc)",
        "python_impl": "running session BC after Pine swap logic",
    },
    "dev_tp": {
        "pine_formula": "2 * dev_p - dev_bp_raw then max(dbc, dtc)",
        "python_impl": "running session TC after Pine swap logic",
    },
    "dev_r1": {
        "pine_formula": "2 * dev_p - curr_low",
        "python_impl": "Traditional developing R1 from running session OHLC",
    },
    "dev_s1": {
        "pine_formula": "2 * dev_p - curr_high",
        "python_impl": "Traditional developing S1 from running session OHLC",
    },
}

VALIDATION_COLUMN_ALIASES: Dict[str, Iterable[str]] = {
    "prev_day_open": ("prev_day_open",),
    "prev_day_high": ("CPR_Vedhaviyash4_prev_day_high", "prev_day_high"),
    "prev_day_low": ("CPR_Vedhaviyash4_prev_day_low", "prev_day_low"),
    "prev_day_close": ("prev_day_close",),
    "p": ("CPR_Vedhaviyash4_daily_pivot", "Central Pivot Range_CPR", "daily_pivot"),
    "bp": ("CPR_Vedhaviyash4_daily_bc", "Central Pivot Range_BC", "daily_bc"),
    "tp": ("CPR_Vedhaviyash4_daily_tc", "Central Pivot Range_TC", "daily_tc"),
    "r0_5": ("Central Pivot Range_R0.5", "r0_5"),
    "s0_5": ("Central Pivot Range_S0.5", "s0_5"),
    "r1": ("CPR_Vedhaviyash4_daily_r1", "Central Pivot Range_R1", "daily_r1", "r1"),
    "s1": ("CPR_Vedhaviyash4_daily_s1", "Central Pivot Range_S1", "daily_s1", "s1"),
    "r1_5": ("Central Pivot Range_R1.5", "r1_5"),
    "s1_5": ("Central Pivot Range_S1.5", "s1_5"),
    "r2": ("CPR_Vedhaviyash4_daily_r2", "Central Pivot Range_R2", "daily_r2", "r2"),
    "s2": ("CPR_Vedhaviyash4_daily_s2", "Central Pivot Range_S2", "daily_s2", "s2"),
    "r2_5": ("Central Pivot Range_R2.5", "r2_5"),
    "s2_5": ("Central Pivot Range_S2.5", "s2_5"),
    "r3": ("CPR_Vedhaviyash4_daily_r3", "Central Pivot Range_R3", "daily_r3", "r3"),
    "s3": ("CPR_Vedhaviyash4_daily_s3", "Central Pivot Range_S3", "daily_s3", "s3"),
    "r3_5": ("Central Pivot Range_R3.5", "r3_5"),
    "s3_5": ("Central Pivot Range_S3.5", "s3_5"),
    "r4": ("CPR_Vedhaviyash4_daily_r4", "Central Pivot Range_R4", "daily_r4", "r4"),
    "s4": ("CPR_Vedhaviyash4_daily_s4", "Central Pivot Range_S4", "daily_s4", "s4"),
    "r4_5": ("Central Pivot Range_R4.5", "r4_5"),
    "s4_5": ("Central Pivot Range_S4.5", "s4_5"),
    "r5": ("Central Pivot Range_R5", "r5"),
    "s5": ("Central Pivot Range_S5", "s5"),
    "dev_p": ("Central Pivot Range_Dev CPR", "dev_cpr", "dev_p"),
    "dev_bp": ("Central Pivot Range_Dev BC", "dev_bp"),
    "dev_tp": ("Central Pivot Range_Dev TC", "dev_tp"),
    "dev_r1": ("Central Pivot Range_Dev R1", "dev_r1"),
    "dev_s1": ("Central Pivot Range_Dev S1", "dev_s1"),
}


# ── IMPORT/LOAD HELPERS ────────────────────────────────────────────────────
def _normalize_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """Replace TradingView-style sentinel values with NaN on numeric columns only."""
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


def load_csv_data(csv_path: str | Path) -> pd.DataFrame:
    """
    Load raw market + indicator data from CSV.

    The loader keeps all original columns so validation can compare against
    whatever indicator columns are present in the sample export.
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV file not found: {path}")

    raw = pd.read_csv(path, low_memory=False)
    raw = _normalize_missing_values(raw)
    return _attach_timestamp_index(raw)


def _normalize_index_timezone(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Assume naive timestamps are UTC, then convert them to exchange time."""
    if index.tz is None:
        return index.tz_localize("UTC").tz_convert(EXCHANGE_TIMEZONE)
    return index.tz_convert(EXCHANGE_TIMEZONE)


def _normalize_name(value: str) -> str:
    """Lower-case alphanumeric-only normalization for robust column matching."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _find_matching_sample_column(sample_df: pd.DataFrame, aliases: Iterable[str]) -> Optional[str]:
    """Resolve the best sample column match for a given internal indicator column."""
    normalized_columns = {_normalize_name(column): column for column in sample_df.columns}

    for alias in aliases:
        alias_key = _normalize_name(alias)
        if alias_key in normalized_columns:
            return normalized_columns[alias_key]

    for alias in aliases:
        alias_key = _normalize_name(alias)
        if len(alias_key) < 6:
            continue
        matches = [
            original
            for normalized, original in normalized_columns.items()
            if normalized.endswith(alias_key)
        ]
        if len(matches) == 1:
            return matches[0]

    return None


def _require_price_columns(df: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_PRICE_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            "Input data is missing required OHLCV columns: "
            + ", ".join(missing)
        )


# ── INDICATOR ENGINE ──────────────────────────────────────────────────────
def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replicate the Pine Central Pivot Range indicator for the locked plan:
    Traditional CPR, Daily timeframe, Use Daily-based Values = true.

    Input df must have: timestamp (index), open, high, low, close, volume.
    Returns df with indicator columns appended.
    No lookahead is used for completed CPR levels: they are derived strictly
    from the previous completed daily session and then mapped onto each
    intraday bar of the current session. Developing CPR uses current-session
    running high/low with the current bar close, which mirrors Pine's
    `request.security(..., lookahead_on)` daily behavior on intraday charts.
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")

    working = df.copy().sort_index()
    local_index = _normalize_index_timezone(working.index)
    session_key = local_index.normalize()
    working["_session_key"] = session_key

    daily = (
        working.groupby("_session_key", sort=True)
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
        )
        .rename(
            columns={
                "open": "session_open",
                "high": "session_high",
                "low": "session_low",
                "close": "session_close",
                "volume": "session_volume",
            }
        )
    )

    previous_daily = daily.shift(1).rename(
        columns={
            "session_open": "prev_day_open",
            "session_high": "prev_day_high",
            "session_low": "prev_day_low",
            "session_close": "prev_day_close",
            "session_volume": "prev_day_volume",
        }
    )
    previous_daily_aligned = previous_daily.reindex(working["_session_key"]).set_axis(
        working.index
    )

    prev_day_open = previous_daily_aligned["prev_day_open"]
    prev_day_high = previous_daily_aligned["prev_day_high"]
    prev_day_low = previous_daily_aligned["prev_day_low"]
    prev_day_close = previous_daily_aligned["prev_day_close"]

    p = (prev_day_high + prev_day_low + prev_day_close) / 3.0
    bp_raw = (prev_day_high + prev_day_low) / 2.0
    tp_raw = (p * 2.0) - bp_raw
    bp = np.minimum(bp_raw, tp_raw)
    tp = np.maximum(bp_raw, tp_raw)

    session_range = prev_day_high - prev_day_low

    r1 = p * 2.0 - prev_day_low
    s1 = p * 2.0 - prev_day_high
    r2 = p + session_range
    s2 = p - session_range
    r3 = p * 2.0 + (prev_day_high - 2.0 * prev_day_low)
    s3 = p * 2.0 - (2.0 * prev_day_high - prev_day_low)
    r4 = p * 3.0 + (prev_day_high - 3.0 * prev_day_low)
    s4 = p * 3.0 - (3.0 * prev_day_high - prev_day_low)
    r5 = p * 4.0 + (prev_day_high - 4.0 * prev_day_low)
    s5 = p * 4.0 - (4.0 * prev_day_high - prev_day_low)

    grouped_high = working.groupby("_session_key")["high"]
    grouped_low = working.groupby("_session_key")["low"]
    running_high = grouped_high.cummax()
    running_low = grouped_low.cummin()
    current_close = working["close"]

    dev_p = (running_high + running_low + current_close) / 3.0
    dev_bp_raw = (running_high + running_low) / 2.0
    dev_tp_raw = (dev_p * 2.0) - dev_bp_raw
    dev_bp = np.minimum(dev_bp_raw, dev_tp_raw)
    dev_tp = np.maximum(dev_bp_raw, dev_tp_raw)
    dev_r1 = dev_p * 2.0 - running_low
    dev_s1 = dev_p * 2.0 - running_high

    working = working.assign(
        prev_day_open=prev_day_open,
        prev_day_high=prev_day_high,
        prev_day_low=prev_day_low,
        prev_day_close=prev_day_close,
        p=p,
        bp=bp,
        tp=tp,
        r0_5=(p + r1) / 2.0,
        s0_5=(p + s1) / 2.0,
        r1=r1,
        s1=s1,
        r1_5=(r1 + r2) / 2.0,
        s1_5=(s1 + s2) / 2.0,
        r2=r2,
        s2=s2,
        r2_5=(r2 + r3) / 2.0,
        s2_5=(s2 + s3) / 2.0,
        r3=r3,
        s3=s3,
        r3_5=(r3 + r4) / 2.0,
        s3_5=(s3 + s4) / 2.0,
        r4=r4,
        s4=s4,
        r4_5=(r4 + r5) / 2.0,
        s4_5=(s4 + s5) / 2.0,
        r5=r5,
        s5=s5,
        dev_p=dev_p,
        dev_bp=dev_bp,
        dev_tp=dev_tp,
        dev_r1=dev_r1,
        dev_s1=dev_s1,
    )

    return working.drop(columns=["_session_key"])


# ── VALIDATION ────────────────────────────────────────────────────────────
def _compare_indicator_series(
    actual: pd.Series,
    expected: pd.Series,
) -> tuple[bool, float, Optional[pd.Timestamp], Optional[float], Optional[float]]:
    """Compare two series using the configured percentage tolerance."""
    actual_aligned, expected_aligned = actual.align(expected, join="inner")
    if actual_aligned.empty:
        return False, np.inf, None, None, None

    both_nan = actual_aligned.isna() & expected_aligned.isna()
    nan_mismatch = actual_aligned.isna() ^ expected_aligned.isna()

    valid_mask = ~(both_nan | nan_mismatch)
    if valid_mask.any():
        diff_abs = (actual_aligned[valid_mask] - expected_aligned[valid_mask]).abs()
        denom = expected_aligned[valid_mask].abs()
        diff_pct = np.where(
            denom > ZERO_VALUE_ABSOLUTE_TOLERANCE,
            (diff_abs / denom) * 100.0,
            np.where(diff_abs <= ZERO_VALUE_ABSOLUTE_TOLERANCE, 0.0, np.inf),
        )
        max_diff_pct = float(np.max(diff_pct))
    else:
        diff_pct = np.array([], dtype=float)
        max_diff_pct = 0.0

    passed = (not nan_mismatch.any()) and (max_diff_pct <= VALIDATION_TOLERANCE_PCT)
    if passed:
        return True, max_diff_pct, None, None, None

    mismatch_index = nan_mismatch[nan_mismatch].index
    if len(mismatch_index) > 0:
        first_idx = mismatch_index[0]
        return (
            False,
            np.inf,
            first_idx,
            actual_aligned.loc[first_idx],
            expected_aligned.loc[first_idx],
        )

    failing_positions = np.where(diff_pct > VALIDATION_TOLERANCE_PCT)[0]
    if len(failing_positions) == 0:
        first_idx = actual_aligned[valid_mask].index[0]
    else:
        first_idx = actual_aligned[valid_mask].index[failing_positions[0]]

    return (
        False,
        max_diff_pct,
        first_idx,
        actual_aligned.loc[first_idx],
        expected_aligned.loc[first_idx],
    )


def _series_is_session_constant(series: pd.Series) -> bool:
    """Return True when a series has at most one non-NaN value per local session."""
    local_index = _normalize_index_timezone(series.index)
    session_key = local_index.normalize()
    unique_counts = series.groupby(session_key).nunique(dropna=True)
    return bool((unique_counts <= 1).all())


def _build_validation_report(indicator_df: pd.DataFrame, sample_df: pd.DataFrame) -> pd.DataFrame:
    """Create a TradingView-style validation report for all overlapping CPR columns."""
    report_rows = []

    for indicator_name in INDICATOR_ORDER:
        aliases = VALIDATION_COLUMN_ALIASES.get(indicator_name, ())
        sample_column = _find_matching_sample_column(sample_df, aliases)
        metadata = INDICATOR_METADATA[indicator_name]

        if sample_column is None:
            report_rows.append(
                {
                    "Indicator": indicator_name,
                    "Pine Formula": metadata["pine_formula"],
                    "Python Implementation": metadata["python_impl"],
                    "Smoothing Match": "N/A",
                    "Sample Data Match": "not available in sample",
                }
            )
            continue

        if indicator_name in COMPLETED_SESSION_COLUMNS and not _series_is_session_constant(
            sample_df[sample_column]
        ):
            report_rows.append(
                {
                    "Indicator": indicator_name,
                    "Pine Formula": metadata["pine_formula"],
                    "Python Implementation": metadata["python_impl"],
                    "Smoothing Match": "N/A",
                    "Sample Data Match": "present but incompatible with completed-session CPR semantics",
                }
            )
            continue

        passed, max_diff_pct, first_idx, actual_value, expected_value = _compare_indicator_series(
            indicator_df[indicator_name],
            sample_df[sample_column],
        )
        status = f"PASS max_err={max_diff_pct:.6f}%"
        if not passed:
            status = (
                f"FAIL max_err={max_diff_pct:.6f}% first_mismatch={first_idx} "
                f"actual={actual_value} expected={expected_value}"
            )

        report_rows.append(
            {
                "Indicator": indicator_name,
                "Pine Formula": metadata["pine_formula"],
                "Python Implementation": metadata["python_impl"],
                "Smoothing Match": "N/A",
                "Sample Data Match": status,
            }
        )

    return pd.DataFrame(report_rows)


def validate_against_sample(df: pd.DataFrame, sample_path: str | Path) -> None:
    """
    Load a CSV sample, compare overlapping CPR columns value-by-value, and
    raise AssertionError if any matched indicator exceeds 0.01% tolerance.

    Because the supplied sample is not a full export from this exact line-based
    Pine indicator, validation is performed against the overlapping CPR fields
    that are actually present in the sample. The same function can validate a
    richer future export without code changes.
    """
    sample_df = load_csv_data(sample_path)
    common_index = df.index.intersection(sample_df.index)
    if common_index.empty:
        raise ValueError("No overlapping timestamps found between calculated data and sample file.")

    aligned_indicator_df = df.loc[common_index]
    aligned_sample_df = sample_df.loc[common_index]
    report = _build_validation_report(aligned_indicator_df, aligned_sample_df)

    print("Validation report:")
    print(report.to_string(index=False))

    compared = report["Sample Data Match"].str.startswith(("PASS", "FAIL"))
    if not compared.any():
        print(
            "\nNOTE: no semantically compatible external CPR columns were found in the sample. "
            "Strict parity still requires an export from the exact CPR script."
        )
        return

    failed = report["Sample Data Match"].str.startswith("FAIL")
    if failed.any():
        failures = report.loc[failed, ["Indicator", "Sample Data Match"]]
        raise AssertionError(
            "One or more CPR indicators failed sample validation:\n"
            + failures.to_string(index=False)
        )

    print("\nPASS: all overlapping CPR columns are within tolerance.")


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """
    Run internal no-lookahead and session-consistency checks against the
    calculated indicator frame.
    """
    local_index = _normalize_index_timezone(df.index)
    session_key = local_index.normalize()
    first_bar_mask = ~session_key.duplicated()

    completed_columns = ["p", "bp", "tp", "r1", "s1", "r2", "s2", "r3", "s3", "r4", "s4"]
    first_session = session_key[first_bar_mask][0]
    first_session_rows = session_key == first_session
    if not df.loc[first_session_rows, completed_columns].isna().all().all():
        raise AssertionError("First available session must remain NaN for completed CPR levels.")

    for column in completed_columns:
        unique_counts = df[column].groupby(session_key).nunique(dropna=True)
        later_sessions = unique_counts.iloc[1:]
        if not (later_sessions <= 1).all():
            raise AssertionError(f"Completed CPR column `{column}` is not constant within a session.")

    first_bar_rows = df.loc[first_bar_mask].copy()
    first_bar_rows["expected_p"] = (
        first_bar_rows["prev_day_high"]
        + first_bar_rows["prev_day_low"]
        + first_bar_rows["prev_day_close"]
    ) / 3.0
    comparable_first_bars = first_bar_rows.iloc[1:]
    if not np.allclose(
        comparable_first_bars["p"],
        comparable_first_bars["expected_p"],
        equal_nan=True,
    ):
        raise AssertionError("Completed pivot values do not match previous-session HLC on day boundaries.")

    if df["dev_p"].nunique(dropna=True) <= 1:
        raise AssertionError("Developing CPR did not evolve intraday; expected changing dev_p values.")

    print("Internal sanity checks:")
    print("PASS first-session completed CPR stays NaN")
    print("PASS completed CPR remains session-constant after warmup")
    print("PASS day-boundary pivot matches previous-session HLC")
    print("PASS developing CPR changes intraday")


# ── MAIN ──────────────────────────────────────────────────────────────────
def main(sample_path: str | Path) -> None:
    """Load CSV, calculate CPR values, validate, and print a compact summary."""
    sample_df = load_csv_data(sample_path)
    market_df = sample_df.loc[:, list(REQUIRED_PRICE_COLUMNS)].copy()
    indicator_df = calculate_indicators(market_df)

    run_internal_sanity_checks(indicator_df)
    validate_against_sample(indicator_df, sample_path)

    preview_columns = [
        "open",
        "high",
        "low",
        "close",
        "p",
        "bp",
        "tp",
        "r1",
        "s1",
        "dev_p",
        "dev_r1",
        "dev_s1",
    ]
    print("\nIndicator preview:")
    print(indicator_df.loc[:, preview_columns].tail(5).to_string())


if __name__ == "__main__":
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    main(csv_path)
