"""
# ============================================================
# INDICATOR: RSI Divergence
# Converted from Pine Script v4-style source | 2026-03-21
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "RSI Divergence"
DEFAULT_FAST_LENGTH = 5
DEFAULT_SLOW_LENGTH = 14
MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\RSI_Divergence.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")


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


def _pine_rsi(source: pd.Series, length: int) -> pd.Series:
    """Replicate the script's manual RSI formula exactly."""
    change = source.diff()
    up = _pine_rma(change.clip(lower=0.0), length)
    down = _pine_rma((-change.clip(upper=0.0)), length)
    out = pd.Series(np.nan, index=source.index, dtype=float)
    out[(down == 0) & down.notna()] = 100.0
    out[(up == 0) & down.notna()] = 0.0
    mask = (up != 0) & (down != 0)
    out[mask] = 100.0 - (100.0 / (1.0 + up[mask] / down[mask]))
    return out


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    fast_length: int = DEFAULT_FAST_LENGTH,
    slow_length: int = DEFAULT_SLOW_LENGTH,
) -> pd.DataFrame:
    """
    Replicate the pasted RSI Divergence script.

    The pasted Pine computes only:
    - fast RSI
    - slow RSI
    - divergence = fast RSI - slow RSI
    - horizontal zero line

    It does not define Buy/Sell signals. Those sample columns appear to come from
    a different script or a later modified version.
    """
    _require_price_columns(df)
    working = df.copy().sort_index()
    close = working["close"].astype(float)

    rsi_fast = _pine_rsi(close, fast_length)
    rsi_slow = _pine_rsi(close, slow_length)
    divergence = rsi_fast - rsi_slow

    return working.assign(
        rsi_fast=rsi_fast,
        rsi_slow=rsi_slow,
        divergence=divergence,
        band_zero=0.0,
    )


# -- VALIDATION -------------------------------------------------------------
def validate_against_sample(df: pd.DataFrame, sample_path: str | Path) -> list[str]:
    """
    Inspect the sample and explain whether it can validate the pasted Pine script.

    The provided sample has `Buy_Signal` and `Sell_Signal`, but the pasted source
    has no such outputs. We therefore report the mismatch explicitly instead of
    pretending the sample is a parity source for this script.
    """
    sample_df = load_csv_data(sample_path)
    messages: list[str] = []

    divergence_column = _find_matching_sample_column(sample_df, ("divergence", "plotdiv", "RSI_Divergence"))
    if divergence_column is None:
        messages.append(
            "Sample does not contain a divergence series column, so it cannot directly validate the pasted RSI Divergence script."
        )
    else:
        common_index = df.index.intersection(sample_df.index)
        actual = df.loc[common_index, "divergence"].astype(float).to_numpy()
        expected = sample_df.loc[common_index, divergence_column].astype(float).to_numpy()
        passed = np.isclose(actual, expected, atol=1e-9, rtol=0.0, equal_nan=True).all()
        messages.append(f"Divergence column parity: {'PASS' if passed else 'FAIL'}")

    if "Buy_Signal" in sample_df.columns and "Sell_Signal" in sample_df.columns:
        messages.append(
            "Sample includes Buy_Signal/Sell_Signal, but those are not defined in the pasted Pine. "
            "This confirms the sample came from a different RSI-divergence logic than the pasted script."
        )

    return messages


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """Verify internal consistency for the calculated divergence series."""
    required_columns = ("rsi_fast", "rsi_slow", "divergence", "band_zero")
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires calculated columns: " + ", ".join(missing)
        )

    if not np.isclose(
        df["divergence"].to_numpy(dtype=float),
        (df["rsi_fast"] - df["rsi_slow"]).to_numpy(dtype=float),
        atol=1e-9,
        rtol=0.0,
        equal_nan=True,
    ).all():
        raise AssertionError("divergence must equal rsi_fast - rsi_slow exactly.")

    print("Internal sanity checks: PASS")


# -- REPORTING --------------------------------------------------------------
def _build_export_preview(df: pd.DataFrame, rows: int = 8) -> pd.DataFrame:
    """Return a compact preview of the pasted indicator outputs."""
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "rsi_fast",
        "rsi_slow",
        "divergence",
        "band_zero",
    ]
    return df.loc[:, preview_columns].head(rows)


def _build_sample_signal_preview(sample_df: pd.DataFrame, rows: int = 15) -> pd.DataFrame:
    """Return the first few sample buy/sell rows for inspection."""
    if "Buy_Signal" not in sample_df.columns or "Sell_Signal" not in sample_df.columns:
        return pd.DataFrame()
    mask = (sample_df["Buy_Signal"] == 1) | (sample_df["Sell_Signal"] == 1)
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "Buy_Signal",
        "Sell_Signal",
    ]
    return sample_df.loc[mask, preview_columns].head(rows)


def main(sample_path: str | Path = DEFAULT_SAMPLE_PATH) -> int:
    """Load the sample, calculate the indicator, and print a verification report."""
    sample_df = load_csv_data(sample_path)
    calculated = calculate_indicators(sample_df)
    run_internal_sanity_checks(calculated)
    messages = validate_against_sample(calculated, sample_path)

    print("Validation report:")
    for message in messages:
        print(f"  {message}")

    print("\nPasted indicator preview:")
    print(_build_export_preview(calculated).to_string(index=False))

    sample_signal_preview = _build_sample_signal_preview(sample_df)
    if not sample_signal_preview.empty:
        print("\nSample signal preview:")
        print(sample_signal_preview.to_string(index=False))

    return 0


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    raise SystemExit(main(input_path))
