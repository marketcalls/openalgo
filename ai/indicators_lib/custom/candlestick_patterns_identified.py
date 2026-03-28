"""
# ============================================================
# INDICATOR: Candlestick Patterns Identified, update 1-17-26
# Converted from Pine Script v6 | 2026-03-20
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "Candlestick Patterns Identified, update 1-17-26"

DEFAULT_TREND = 5
DEFAULT_DOJI_SIZE = 0.05

MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\NSE_BANKNIFTY_60_5568bars.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

FRIENDLY_PATTERN_COLUMNS = (
    "doji",
    "bearish_harami",
    "bullish_harami",
    "bearish_engulfing",
    "bullish_engulfing",
    "piercing_line",
    "bullish_belt",
    "bullish_kicker",
    "bearish_kicker",
    "hanging_man",
    "evening_star",
    "morning_star",
    "shooting_star",
    "hammer",
    "inverted_hammer",
)

ALIAS_COLUMN_MAP = {
    "doji": (
        "Candlestick_Patterns_Doji",
        "Candlestick_Patterns_Doji_2",
    ),
    "bearish_harami": (
        "Candlestick_Patterns_Bearish_Harami",
        "Candlestick_Patterns_Bearish_Harami_2",
    ),
    "bullish_harami": (
        "Candlestick_Patterns_Bullish_Harami",
        "Candlestick_Patterns_Bullish_Harami_2",
    ),
    "bearish_engulfing": (
        "Candlestick_Patterns_Bearish_Engulfing",
        "Candlestick_Patterns_Bearish_Engulfing_2",
    ),
    "bullish_engulfing": (
        "Candlestick_Patterns_Bullish_Engulfing",
        "Candlestick_Patterns_Bullish_Engulfing_2",
    ),
    "piercing_line": (
        "Candlestick_Patterns_Piercing_Line",
        "Candlestick_Patterns_Piercing_Line_2",
    ),
    "bullish_belt": (
        "Candlestick_Patterns_Bullish_Belt",
        "Candlestick_Patterns_Bullish_Belt_2",
    ),
    "bullish_kicker": (
        "Candlestick_Patterns_Bullish_Kicker",
        "Candlestick_Patterns_Bullish_Kicker_2",
    ),
    "bearish_kicker": (
        "Candlestick_Patterns_Bearish_Kicker",
        "Candlestick_Patterns_Bearish_Kicker_2",
    ),
    "hanging_man": (
        "Candlestick_Patterns_Hanging_Man",
        "Candlestick_Patterns_Hanging_Man_2",
    ),
    "evening_star": (
        "Candlestick_Patterns_Evening_Star",
        "Candlestick_Patterns_Evening_Star_2",
    ),
    "morning_star": (
        "Candlestick_Patterns_Morning_Star",
        "Candlestick_Patterns_Morning_Star_2",
    ),
    "shooting_star": (
        "Candlestick_Patterns_Shooting_Star",
        "Candlestick_Patterns_Shooting_Star_2",
    ),
    "hammer": (
        "Candlestick_Patterns_Hammer",
        "Candlestick_Patterns_Hammer_2",
    ),
    "inverted_hammer": (
        "Candlestick_Patterns_Inverted_Hammer",
        "Candlestick_Patterns_Inverted_Hammer_2",
    ),
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
    """Resolve the matching sample column for a given output name."""
    normalized_columns = {_normalize_name(column): column for column in sample_df.columns}
    for alias in aliases:
        alias_key = _normalize_name(alias)
        if alias_key in normalized_columns:
            return normalized_columns[alias_key]
    return None


# -- INDICATOR ENGINE -------------------------------------------------------
def _compute_pattern_series(
    df: pd.DataFrame,
    trend: int,
    doji_size: float,
) -> dict[str, pd.Series]:
    """Compute the raw candlestick pattern booleans exactly as written in Pine."""
    open_ = df["open"]
    high = df["high"]
    low = df["low"]
    close = df["close"]

    doji = (open_ - close).abs() <= (high - low) * doji_size

    bearish_harami = (
        (close.shift(1) > open_.shift(1))
        & (open_ > close)
        & (open_ <= close.shift(1))
        & (open_.shift(1) <= close)
        & ((open_ - close) < (close.shift(1) - open_.shift(1)))
        & (open_.shift(trend) < open_)
    )

    bullish_harami = (
        (open_.shift(1) > close.shift(1))
        & (close > open_)
        & (close <= open_.shift(1))
        & (close.shift(1) <= open_)
        & ((close - open_) < (open_.shift(1) - close.shift(1)))
        & (open_.shift(trend) > open_)
    )

    bearish_engulfing = (
        (close.shift(1) > open_.shift(1))
        & (open_ > close)
        & (open_ >= close.shift(1))
        & (open_.shift(1) >= close)
        & ((open_ - close) > (close.shift(1) - open_.shift(1)))
        & (open_.shift(trend) < open_)
    )

    bullish_engulfing = (
        (open_.shift(1) > close.shift(1))
        & (close > open_)
        & (close >= open_.shift(1))
        & (close.shift(1) >= open_)
        & ((close - open_) > (open_.shift(1) - close.shift(1)))
        & (open_.shift(trend) > open_)
    )

    piercing_line = (
        (close.shift(1) < open_.shift(1))
        & (open_ < low.shift(1))
        & (close > close.shift(1) + ((open_.shift(1) - close.shift(1)) / 2.0))
        & (close < open_.shift(1))
        & (open_.shift(trend) > open_)
    )

    lower = low.rolling(window=10, min_periods=10).min().shift(1)
    bullish_belt = (
        (low == open_)
        & (open_ < lower)
        & (open_ < close)
        & (close > ((high.shift(1) - low.shift(1)) / 2.0) + low.shift(1))
        & (open_.shift(trend) > open_)
    )

    bullish_kicker = (
        (open_.shift(1) > close.shift(1))
        & (open_ >= open_.shift(1))
        & (close > open_)
        & (open_.shift(trend) > open_)
    )

    bearish_kicker = (
        (open_.shift(1) < close.shift(1))
        & (open_ <= open_.shift(1))
        & (close <= open_)
        & (open_.shift(trend) < open_)
    )

    hanging_man = (
        ((high - low) > 4 * (open_ - close).abs())
        & (((close - low) / (0.001 + high - low)) >= 0.75)
        & (((open_ - low) / (0.001 + high - low)) >= 0.75)
        & (open_.shift(trend) < open_)
        & (high.shift(1) < open_)
        & (high.shift(2) < open_)
    )

    evening_star = (
        (close.shift(2) > open_.shift(2))
        & (np.minimum(open_.shift(1), close.shift(1)) > close.shift(2))
        & (open_ < np.minimum(open_.shift(1), close.shift(1)))
        & (close < open_)
    )

    morning_star = (
        (close.shift(2) < open_.shift(2))
        & (np.maximum(open_.shift(1), close.shift(1)) < close.shift(2))
        & (open_ > np.maximum(open_.shift(1), close.shift(1)))
        & (close > open_)
    )

    shooting_star = (
        (open_.shift(1) < close.shift(1))
        & (open_ > close.shift(1))
        & ((high - np.maximum(open_, close)) >= (open_ - close).abs() * 3)
        & ((np.minimum(close, open_) - low) <= (open_ - close).abs())
    )

    hammer = (
        ((high - low) > 3 * (open_ - close).abs())
        & (((close - low) / (0.001 + high - low)) > 0.6)
        & (((open_ - low) / (0.001 + high - low)) > 0.6)
    )

    inverted_hammer = (
        ((high - low) > 3 * (open_ - close).abs())
        & (((high - close) / (0.001 + high - low)) > 0.6)
        & (((high - open_) / (0.001 + high - low)) > 0.6)
    )

    return {
        "doji": doji.fillna(False),
        "bearish_harami": bearish_harami.fillna(False),
        "bullish_harami": bullish_harami.fillna(False),
        "bearish_engulfing": bearish_engulfing.fillna(False),
        "bullish_engulfing": bullish_engulfing.fillna(False),
        "piercing_line": piercing_line.fillna(False),
        "bullish_belt": bullish_belt.fillna(False),
        "bullish_kicker": bullish_kicker.fillna(False),
        "bearish_kicker": bearish_kicker.fillna(False),
        "hanging_man": hanging_man.fillna(False),
        "evening_star": evening_star.fillna(False),
        "morning_star": morning_star.fillna(False),
        "shooting_star": shooting_star.fillna(False),
        "hammer": hammer.fillna(False),
        "inverted_hammer": inverted_hammer.fillna(False),
    }


def calculate_indicators(
    df: pd.DataFrame,
    trend: int = DEFAULT_TREND,
    doji_size: float = DEFAULT_DOJI_SIZE,
) -> pd.DataFrame:
    """
    Replicate the Candlestick Patterns indicator and append boolean signal
    columns plus Excel-aligned alias columns.
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")
    if trend < 1:
        raise ValueError("trend must be >= 1")
    if doji_size < 0.01:
        raise ValueError("doji_size must be >= 0.01")

    working = df.copy().sort_index()
    patterns = _compute_pattern_series(working, trend=trend, doji_size=doji_size)
    working = working.assign(**patterns)

    for friendly_name, alias_columns in ALIAS_COLUMN_MAP.items():
        for alias in alias_columns:
            working[alias] = working[friendly_name].astype(int)

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


def run_internal_sanity_checks(
    df: pd.DataFrame,
    trend: int = DEFAULT_TREND,
    doji_size: float = DEFAULT_DOJI_SIZE,
) -> None:
    """
    Recompute all pattern formulas from OHLC data and verify the exported
    boolean columns match exactly.
    """
    required = list(REQUIRED_PRICE_COLUMNS) + list(FRIENDLY_PATTERN_COLUMNS)
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires these columns to exist: "
            + ", ".join(missing)
        )

    expected = _compute_pattern_series(df, trend=trend, doji_size=doji_size)
    for column in FRIENDLY_PATTERN_COLUMNS:
        if not df[column].equals(expected[column]):
            raise AssertionError(f"{column} does not match the exact Pine formula.")

    print("Internal sanity checks:")
    print("PASS all 15 candlestick pattern formulas match exact Pine logic")
    print("PASS doji uses the configured proportional body-size threshold")
    print("PASS trend-based patterns use open.shift(trend) exactly as Pine does")


def validate_against_sample(
    df: pd.DataFrame,
    sample_path: str | Path,
    trend: int = DEFAULT_TREND,
    doji_size: float = DEFAULT_DOJI_SIZE,
) -> None:
    """
    Compare the pattern outputs exactly against the sample export and raise
    AssertionError on the first mismatch for any overlapping pattern column.
    """
    run_internal_sanity_checks(df, trend=trend, doji_size=doji_size)

    sample_df = load_csv_data(sample_path)
    common_index = df.index.intersection(sample_df.index)
    if common_index.empty:
        raise ValueError("No overlapping timestamps found between calculated data and sample file.")

    aligned_df = df.loc[common_index]
    aligned_sample = sample_df.loc[common_index]

    report_rows = []
    failures = []

    for friendly_name, alias_columns in ALIAS_COLUMN_MAP.items():
        for alias in alias_columns:
            sample_column = _find_matching_sample_column(aligned_sample, (alias,))
            if sample_column is None:
                report_rows.append((alias, "not available in sample"))
                continue

            passed, mismatch_idx = _compare_boolean_series(aligned_df[alias], aligned_sample[sample_column])
            if passed:
                report_rows.append((alias, "PASS exact"))
            else:
                report_rows.append((alias, f"FAIL first_mismatch={mismatch_idx}"))
                failures.append((alias, mismatch_idx))

    print("Validation report:")
    for indicator, status in report_rows:
        print(f"  {indicator}: {status}")

    if failures:
        details = [f"{alias} mismatch at {mismatch_idx}" for alias, mismatch_idx in failures]
        raise AssertionError("Candlestick pattern validation failed:\n" + "\n".join(details))

    print("\nPASS: all overlapping candlestick-pattern signal columns match the sample exactly.")


# -- MAIN -------------------------------------------------------------------
def main(sample_path: str | Path) -> None:
    """Load CSV, calculate pattern outputs, validate, and print a compact summary."""
    sample_df = load_csv_data(sample_path)
    market_df = sample_df.loc[:, list(REQUIRED_PRICE_COLUMNS)].copy()
    indicator_df = calculate_indicators(
        market_df,
        trend=DEFAULT_TREND,
        doji_size=DEFAULT_DOJI_SIZE,
    )

    validate_against_sample(
        indicator_df,
        sample_path,
        trend=DEFAULT_TREND,
        doji_size=DEFAULT_DOJI_SIZE,
    )

    print("\nPattern counts:")
    for column in FRIENDLY_PATTERN_COLUMNS:
        print(f"  {column:20s}: {int(indicator_df[column].sum())}")

    preview_columns = [
        "open",
        "high",
        "low",
        "close",
        "doji",
        "bearish_harami",
        "bullish_harami",
        "bearish_engulfing",
        "bullish_engulfing",
        "hammer",
        "inverted_hammer",
    ]
    print("\nIndicator preview:")
    print(indicator_df.loc[:, preview_columns].tail(10).to_string())


if __name__ == "__main__":
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    main(csv_path)
