"""
# ============================================================
# INDICATOR: Bollinger Band Breakout
# Converted from Pine Script v4 | 2026-03-20
# Original Pine author: Senthaamizh
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "Bollinger Band Breakout"
PINE_SHORT_NAME = "BB-BO"
PINE_AUTHOR = "Senthaamizh"

DEFAULT_LENGTH = 20
DEFAULT_MULT = 1.5
DEFAULT_EXIT_OPTION = 1

EXCHANGE_TIMEZONE = "Asia/Kolkata"
MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\NSE_BANKNIFTY_60_5568bars.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
OUTPUT_COLUMNS = (
    "basis",
    "upper",
    "lower",
    "long_entry_signal",
    "long_exit_lower_signal",
    "long_exit_basis_signal",
    "long_exit_signal",
)


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


# -- INDICATOR ENGINE -------------------------------------------------------
def _crossover(a: pd.Series, b: pd.Series) -> pd.Series:
    """Pine-style crossover: current a>b and previous a<=b."""
    return ((a > b) & (a.shift(1) <= b.shift(1))).fillna(False)


def _crossunder(a: pd.Series, b: pd.Series) -> pd.Series:
    """Pine-style crossunder: current a<b and previous a>=b."""
    return ((a < b) & (a.shift(1) >= b.shift(1))).fillna(False)


def calculate_indicators(
    df: pd.DataFrame,
    length: int = DEFAULT_LENGTH,
    mult: float = DEFAULT_MULT,
    exit_option: int = DEFAULT_EXIT_OPTION,
) -> pd.DataFrame:
    """
    Replicate the Bollinger Band Breakout script as indicator outputs.

    Returns Bollinger values plus Pine-style entry and exit signal booleans.
    No order simulation is performed here.
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")
    if length < 1:
        raise ValueError("length must be >= 1")
    if exit_option not in (1, 2):
        raise ValueError("exit_option must be either 1 or 2")

    working = df.copy().sort_index()
    source = working["close"]

    basis = source.rolling(window=length, min_periods=length).mean()
    dev = mult * source.rolling(window=length, min_periods=length).std(ddof=0)
    upper = basis + dev
    lower = basis - dev

    long_entry_signal = _crossover(source, upper)
    long_exit_lower_signal = _crossunder(source, lower)
    long_exit_basis_signal = _crossunder(source, basis)
    long_exit_signal = (
        long_exit_lower_signal if exit_option == 1 else long_exit_basis_signal
    )

    working = working.assign(
        basis=basis,
        upper=upper,
        lower=lower,
        long_entry_signal=long_entry_signal,
        long_exit_lower_signal=long_exit_lower_signal,
        long_exit_basis_signal=long_exit_basis_signal,
        long_exit_signal=long_exit_signal,
    )
    return working


# -- VALIDATION -------------------------------------------------------------
def run_internal_sanity_checks(
    df: pd.DataFrame,
    length: int = DEFAULT_LENGTH,
    mult: float = DEFAULT_MULT,
    exit_option: int = DEFAULT_EXIT_OPTION,
) -> None:
    """
    Verify Bollinger math and Pine-style crossover/crossunder logic directly
    from the OHLCV data.
    """
    missing = [column for column in OUTPUT_COLUMNS + REQUIRED_PRICE_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires these columns to exist: "
            + ", ".join(missing)
        )

    source = df["close"]
    expected_basis = source.rolling(window=length, min_periods=length).mean()
    expected_dev = mult * source.rolling(window=length, min_periods=length).std(ddof=0)
    expected_upper = expected_basis + expected_dev
    expected_lower = expected_basis - expected_dev

    if not df["basis"].equals(expected_basis):
        raise AssertionError("basis does not match rolling SMA(close, length).")
    if not df["upper"].equals(expected_upper):
        raise AssertionError("upper does not match basis + mult * rolling std(ddof=0).")
    if not df["lower"].equals(expected_lower):
        raise AssertionError("lower does not match basis - mult * rolling std(ddof=0).")

    expected_entry = _crossover(source, expected_upper)
    expected_exit_lower = _crossunder(source, expected_lower)
    expected_exit_basis = _crossunder(source, expected_basis)
    expected_exit = expected_exit_lower if exit_option == 1 else expected_exit_basis

    if not df["long_entry_signal"].equals(expected_entry):
        raise AssertionError("long_entry_signal does not match Pine crossover(close, upper).")
    if not df["long_exit_lower_signal"].equals(expected_exit_lower):
        raise AssertionError("long_exit_lower_signal does not match Pine crossunder(close, lower).")
    if not df["long_exit_basis_signal"].equals(expected_exit_basis):
        raise AssertionError("long_exit_basis_signal does not match Pine crossunder(close, basis).")
    if not df["long_exit_signal"].equals(expected_exit):
        raise AssertionError("long_exit_signal does not match the selected Pine exit option.")

    if df["basis"].iloc[: max(length - 1, 0)].notna().any():
        raise AssertionError("Warmup rows before `length` should not have complete Bollinger values.")

    print("Internal sanity checks:")
    print("PASS basis matches rolling SMA(close, length)")
    print("PASS upper/lower match Bollinger math with population std (ddof=0)")
    print("PASS long_entry_signal matches Pine crossover(close, upper)")
    print("PASS long_exit_lower_signal and long_exit_basis_signal match Pine crossunder logic")
    print("PASS long_exit_signal respects the selected exit option")


def validate_against_sample(
    df: pd.DataFrame,
    sample_path: str | Path,
    length: int = DEFAULT_LENGTH,
    mult: float = DEFAULT_MULT,
    exit_option: int = DEFAULT_EXIT_OPTION,
) -> None:
    """
    Perform formula-based validation and report whether any obvious sample
    columns from this exact strategy are present.
    """
    run_internal_sanity_checks(df, length=length, mult=mult, exit_option=exit_option)

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
            "  No obvious named output columns from this exact Bollinger Band Breakout strategy "
            "were found in the current CSV. Validation falls back to internal formula checks."
        )
        return

    print("  Matching sample columns were found and can be compared in a later revision:")
    for output_name, sample_column in overlaps:
        print(f"  {output_name} -> {sample_column}")


# -- MAIN -------------------------------------------------------------------
def main(sample_path: str | Path) -> None:
    """Load CSV, calculate Bollinger breakout outputs, validate, and print a summary."""
    sample_df = load_csv_data(sample_path)
    market_df = sample_df.loc[:, list(REQUIRED_PRICE_COLUMNS)].copy()
    indicator_df = calculate_indicators(
        market_df,
        length=DEFAULT_LENGTH,
        mult=DEFAULT_MULT,
        exit_option=DEFAULT_EXIT_OPTION,
    )

    validate_against_sample(
        indicator_df,
        sample_path,
        length=DEFAULT_LENGTH,
        mult=DEFAULT_MULT,
        exit_option=DEFAULT_EXIT_OPTION,
    )

    print("\nSignal counts:")
    print(f"  long_entry_signal      : {int(indicator_df['long_entry_signal'].sum())}")
    print(f"  long_exit_lower_signal : {int(indicator_df['long_exit_lower_signal'].sum())}")
    print(f"  long_exit_basis_signal : {int(indicator_df['long_exit_basis_signal'].sum())}")
    print(f"  long_exit_signal       : {int(indicator_df['long_exit_signal'].sum())}")

    preview_columns = [
        "close",
        "basis",
        "upper",
        "lower",
        "long_entry_signal",
        "long_exit_lower_signal",
        "long_exit_basis_signal",
        "long_exit_signal",
    ]
    print("\nIndicator preview:")
    print(indicator_df.loc[:, preview_columns].tail(10).to_string())


if __name__ == "__main__":
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    main(csv_path)
