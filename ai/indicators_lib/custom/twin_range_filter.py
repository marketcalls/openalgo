"""
# ============================================================
# INDICATOR: Twin Range Filter
# Converted from Pine Script v4 | 2026-03-21
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "Twin Range Filter"
DEFAULT_SOURCE = "close"
DEFAULT_PER1 = 27
DEFAULT_MULT1 = 1.6
DEFAULT_PER2 = 55
DEFAULT_MULT2 = 2.0
MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\Twin_Range_Filter.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

EXPORTED_COLUMNS = (
    "Long",
    "Short",
    "Long_2",
    "Short_2",
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
def _ema_min_periods(series: pd.Series, length: int) -> pd.Series:
    """
    EMA variant that matched the sample most closely.

    This uses `adjust=False` with `min_periods=length`, which reproduced the
    exported long signals exactly and missed only two short rows in the sample.
    """
    return series.ewm(span=length, adjust=False, min_periods=length).mean()


def _compare_numeric_series(
    actual: pd.Series,
    expected: pd.Series,
    atol: float = 1e-9,
) -> tuple[bool, Optional[pd.Timestamp], float, float, float]:
    """Compare numeric series with NaN support and floating tolerance."""
    actual_values = actual.astype(float).to_numpy()
    expected_values = expected.astype(float).to_numpy()
    comparison = np.isclose(actual_values, expected_values, atol=atol, rtol=0.0, equal_nan=True)
    if comparison.all():
        return True, None, np.nan, np.nan, 0.0

    mismatch_pos = int(np.flatnonzero(~comparison)[0])
    mismatch_idx = actual.index[mismatch_pos]
    actual_value = actual_values[mismatch_pos]
    expected_value = expected_values[mismatch_pos]
    diff = np.nan if np.isnan(actual_value) or np.isnan(expected_value) else abs(actual_value - expected_value)
    return False, mismatch_idx, actual_value, expected_value, diff


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    source_column: str = DEFAULT_SOURCE,
    per1: int = DEFAULT_PER1,
    mult1: float = DEFAULT_MULT1,
    per2: int = DEFAULT_PER2,
    mult2: float = DEFAULT_MULT2,
) -> pd.DataFrame:
    """
    Replicate Twin Range Filter long/short outputs.

    The sample CSV only exports the final Long/Short markers, with duplicate
    `Long_2` and `Short_2` columns. This function also returns the intermediate
    smooth ranges, filter, direction counts, and raw conditions for inspection.
    """
    _require_price_columns(df)
    if source_column not in df.columns:
        raise ValueError(f"Source column not found in input data: {source_column}")

    working = df.copy().sort_index()
    source = working[source_column].astype(float)

    abs_delta = (source - source.shift(1)).abs()
    wper1 = per1 * 2 - 1
    wper2 = per2 * 2 - 1

    smrng1 = _ema_min_periods(_ema_min_periods(abs_delta, per1), wper1) * mult1
    smrng2 = _ema_min_periods(_ema_min_periods(abs_delta, per2), wper2) * mult2
    smrng = (smrng1 + smrng2) / 2.0

    filt = pd.Series(np.nan, index=working.index, dtype=float)
    upward = pd.Series(np.nan, index=working.index, dtype=float)
    downward = pd.Series(np.nan, index=working.index, dtype=float)
    long_cond = pd.Series(False, index=working.index, dtype=bool)
    short_cond = pd.Series(False, index=working.index, dtype=bool)
    cond_ini = pd.Series(np.nan, index=working.index, dtype=float)
    long_signal = pd.Series(False, index=working.index, dtype=bool)
    short_signal = pd.Series(False, index=working.index, dtype=bool)

    for i in range(len(working)):
        x = source.iloc[i]
        r = smrng.iloc[i]
        prev_filt = 0.0 if i == 0 or np.isnan(filt.iloc[i - 1]) else filt.iloc[i - 1]

        if x > prev_filt:
            filt.iloc[i] = prev_filt if x - r < prev_filt else x - r
        else:
            filt.iloc[i] = prev_filt if x + r > prev_filt else x + r

        prev_up = 0.0 if i == 0 or np.isnan(upward.iloc[i - 1]) else upward.iloc[i - 1]
        prev_down = 0.0 if i == 0 or np.isnan(downward.iloc[i - 1]) else downward.iloc[i - 1]
        prev_filter_value = np.nan if i == 0 else filt.iloc[i - 1]

        upward.iloc[i] = (
            prev_up + 1
            if filt.iloc[i] > prev_filter_value
            else 0.0
            if filt.iloc[i] < prev_filter_value
            else prev_up
        )

        downward.iloc[i] = (
            prev_down + 1
            if filt.iloc[i] < prev_filter_value
            else 0.0
            if filt.iloc[i] > prev_filter_value
            else prev_down
        )

        if i == 0:
            previous_source = np.nan
            previous_cond_ini = np.nan
        else:
            previous_source = source.iloc[i - 1]
            previous_cond_ini = cond_ini.iloc[i - 1]

        long_cond.iloc[i] = bool(
            i > 0
            and (
                (x > filt.iloc[i] and x > previous_source and upward.iloc[i] > 0)
                or (x > filt.iloc[i] and x < previous_source and upward.iloc[i] > 0)
            )
        )

        short_cond.iloc[i] = bool(
            i > 0
            and (
                (x < filt.iloc[i] and x < previous_source and downward.iloc[i] > 0)
                or (x < filt.iloc[i] and x > previous_source and downward.iloc[i] > 0)
            )
        )

        cond_ini.iloc[i] = (
            1.0
            if long_cond.iloc[i]
            else -1.0
            if short_cond.iloc[i]
            else previous_cond_ini
        )

        long_signal.iloc[i] = bool(long_cond.iloc[i] and previous_cond_ini == -1)
        short_signal.iloc[i] = bool(short_cond.iloc[i] and previous_cond_ini == 1)

    return working.assign(
        smrng1=smrng1,
        smrng2=smrng2,
        smrng=smrng,
        filt=filt,
        upward=upward,
        downward=downward,
        long_cond=long_cond,
        short_cond=short_cond,
        cond_ini=cond_ini,
        Long=long_signal.astype(int),
        Short=short_signal.astype(int),
        Long_2=long_signal.astype(int),
        Short_2=short_signal.astype(int),
    )


# -- VALIDATION -------------------------------------------------------------
def validate_against_sample(df: pd.DataFrame, sample_path: str | Path) -> list[tuple[str, str]]:
    """Compare exported Twin Range columns against the sample CSV."""
    sample_df = load_csv_data(sample_path)
    common_index = df.index.intersection(sample_df.index)
    if common_index.empty:
        raise ValueError("No overlapping timestamps found between calculated data and sample file.")

    aligned_df = df.loc[common_index]
    aligned_sample = sample_df.loc[common_index]

    report_rows: list[tuple[str, str]] = []

    for output_name in EXPORTED_COLUMNS:
        sample_column = _find_matching_sample_column(
            aligned_sample,
            VALIDATION_COLUMN_ALIASES[output_name],
        )
        if sample_column is None:
            report_rows.append((output_name, "missing sample column"))
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
    return report_rows


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """Verify internal consistency for the calculated outputs."""
    required_columns = (
        "Long",
        "Short",
        "Long_2",
        "Short_2",
        "long_cond",
        "short_cond",
    )
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires calculated columns: " + ", ".join(missing)
        )

    if not (df["Long"] == df["Long_2"]).all():
        raise AssertionError("Long and Long_2 must be identical.")
    if not (df["Short"] == df["Short_2"]).all():
        raise AssertionError("Short and Short_2 must be identical.")
    if int(((df["Long"] == 1) & (df["Short"] == 1)).sum()) != 0:
        raise AssertionError("Long and Short must not overlap on the same bar.")

    print("Internal sanity checks: PASS")


# -- REPORTING --------------------------------------------------------------
def _build_export_preview(df: pd.DataFrame, rows: int = 8) -> pd.DataFrame:
    """Return a compact preview of the exported columns."""
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "Long",
        "Short",
        "Long_2",
        "Short_2",
    ]
    return df.loc[:, preview_columns].head(rows)


def _build_signal_preview(df: pd.DataFrame, rows: int = 15) -> pd.DataFrame:
    """Return the first few signal rows."""
    mask = (df["Long"] == 1) | (df["Short"] == 1)
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "Long",
        "Short",
        "Long_2",
        "Short_2",
    ]
    return df.loc[mask, preview_columns].head(rows)


def _build_mismatch_preview(
    calculated: pd.DataFrame,
    sample_path: str | Path,
    rows: int = 10,
) -> pd.DataFrame:
    """Return the first few sample-vs-python mismatch rows for Long/Short."""
    sample_df = load_csv_data(sample_path)
    common_index = calculated.index.intersection(sample_df.index)
    aligned_calc = calculated.loc[common_index]
    aligned_sample = sample_df.loc[common_index]
    mask = (aligned_calc["Long"] != aligned_sample["Long"]) | (aligned_calc["Short"] != aligned_sample["Short"])
    return pd.DataFrame(
        {
            "datetime": aligned_calc.loc[mask, "datetime"],
            "close": aligned_calc.loc[mask, "close"],
            "sample_Long": aligned_sample.loc[mask, "Long"],
            "python_Long": aligned_calc.loc[mask, "Long"],
            "sample_Short": aligned_sample.loc[mask, "Short"],
            "python_Short": aligned_calc.loc[mask, "Short"],
        }
    ).head(rows)


def main(sample_path: str | Path = DEFAULT_SAMPLE_PATH) -> int:
    """Load the sample, calculate the indicator, validate parity, and print previews."""
    df = load_csv_data(sample_path)
    calculated = calculate_indicators(df)
    run_internal_sanity_checks(calculated)
    report_rows = validate_against_sample(calculated, sample_path)

    print("Validation report:")
    for output_name, status in report_rows:
        print(f"  {output_name}: {status}")

    print("\nSignal counts:")
    print(f"  Long: {int(calculated['Long'].sum())}")
    print(f"  Short: {int(calculated['Short'].sum())}")

    print("\nExport preview:")
    print(_build_export_preview(calculated).to_string(index=False))

    print("\nSignal preview:")
    print(_build_signal_preview(calculated).to_string(index=False))

    mismatch_preview = _build_mismatch_preview(calculated, sample_path)
    if not mismatch_preview.empty:
        print("\nMismatch preview:")
        print(mismatch_preview.to_string(index=False))
    else:
        print("\nMismatch preview:\n  none")

    return 0


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    raise SystemExit(main(input_path))
