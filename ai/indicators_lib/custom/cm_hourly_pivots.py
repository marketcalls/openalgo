"""
# ============================================================
# INDICATOR: CM_Hourly_Pivots
# Converted from Pine Script | 2026-03-20
# Original Pine author: ChrisMoody
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "CM_Hourly_Pivots"
PINE_SHORT_NAME = "CM_Hourly_Pivots"
PINE_AUTHOR = "ChrisMoody"

SHOW_HOURLY_PIVOTS = True  # sh, plotting only
SHOW_R3_S3 = False  # sh3

EXCHANGE_TIMEZONE = "Asia/Kolkata"
MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\NSE_BANKNIFTY_60_5568bars.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
OUTPUT_COLUMNS = (
    "hourly_pivot",
    "hourly_r1",
    "hourly_s1",
    "hourly_r2",
    "hourly_s2",
    "hourly_r3",
    "hourly_s3",
)


# -- LOADERS ----------------------------------------------------------------
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


def _normalize_index_timezone(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Assume naive timestamps are UTC, then convert them to exchange time."""
    if index.tz is None:
        return index.tz_localize("UTC").tz_convert(EXCHANGE_TIMEZONE)
    return index.tz_convert(EXCHANGE_TIMEZONE)


def _require_price_columns(df: pd.DataFrame) -> None:
    """Validate that the DataFrame contains the OHLCV columns required here."""
    missing = [column for column in REQUIRED_PRICE_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            "Input data is missing required OHLCV columns: " + ", ".join(missing)
        )


def _build_hour_bucket_start(index: pd.DatetimeIndex) -> pd.Series:
    """
    Build session-anchored 60-minute bucket starts in exchange time.

    This matches NSE-style hourly bars such as 09:15, 10:15, 11:15, etc,
    instead of wall-clock top-of-hour buckets.
    """
    local_index = _normalize_index_timezone(index)
    local_series = pd.Series(local_index, index=index)
    session_key = local_index.normalize()
    session_start = local_series.groupby(session_key).transform("min")
    elapsed_minutes = ((local_series - session_start).dt.total_seconds() // 60).astype(int)
    bucket_number = elapsed_minutes // 60
    bucket_start = session_start + pd.to_timedelta(bucket_number * 60, unit="m")
    return bucket_start


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    show_r3_s3: bool = SHOW_R3_S3,
) -> pd.DataFrame:
    """
    Replicate the Pine hourly pivot indicator.

    Pine logic:
    - Compute pivot, r1, s1, r2, s2, r3, s3 on 60-minute bars
    - Use security(..., "60", level[1]) to project the previous completed
      60-minute bucket's levels onto the current chart bars

    This implementation supports both 60-minute input and lower intraday input.
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")

    working = df.copy().sort_index()
    working["_hour_bucket_start"] = _build_hour_bucket_start(working.index)

    hourly = (
        working.groupby("_hour_bucket_start", sort=True)
        .agg(
            hour_open=("open", "first"),
            hour_high=("high", "max"),
            hour_low=("low", "min"),
            hour_close=("close", "last"),
            hour_volume=("volume", "sum"),
            bar_count=("close", "size"),
        )
    )

    pivot = (hourly["hour_high"] + hourly["hour_low"] + hourly["hour_close"]) / 3.0
    hour_range = hourly["hour_high"] - hourly["hour_low"]
    r1 = pivot + (pivot - hourly["hour_low"])
    s1 = pivot - (hourly["hour_high"] - pivot)
    r2 = pivot + hour_range
    s2 = pivot - hour_range

    if show_r3_s3:
        r3 = r1 + hour_range
        s3 = s1 - hour_range
    else:
        r3 = pd.Series(np.nan, index=hourly.index, dtype=float)
        s3 = pd.Series(np.nan, index=hourly.index, dtype=float)

    projected = pd.DataFrame(
        {
            "hourly_pivot": pivot.shift(1),
            "hourly_r1": r1.shift(1),
            "hourly_s1": s1.shift(1),
            "hourly_r2": r2.shift(1),
            "hourly_s2": s2.shift(1),
            "hourly_r3": r3.shift(1),
            "hourly_s3": s3.shift(1),
        }
    )

    projected_aligned = projected.reindex(working["_hour_bucket_start"]).set_axis(working.index)
    working = working.assign(**projected_aligned.to_dict("series"))
    return working.drop(columns=["_hour_bucket_start"])


# -- VALIDATION -------------------------------------------------------------
def run_internal_sanity_checks(
    df: pd.DataFrame,
    show_r3_s3: bool = SHOW_R3_S3,
) -> None:
    """
    Verify no-lookahead mapping for the projected hourly pivot ladder.
    """
    required_columns = list(REQUIRED_PRICE_COLUMNS) + list(OUTPUT_COLUMNS)
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires these columns to exist: "
            + ", ".join(missing)
        )

    bucket_start = _build_hour_bucket_start(df.index)
    first_bucket = bucket_start.iloc[0]
    first_bucket_rows = bucket_start == first_bucket
    if not df.loc[first_bucket_rows, OUTPUT_COLUMNS].isna().all().all():
        raise AssertionError(
            "First available 60-minute bucket must remain NaN because no prior bucket exists."
        )

    for column in OUTPUT_COLUMNS:
        unique_counts = df[column].groupby(bucket_start).nunique(dropna=True)
        if not (unique_counts <= 1).all():
            raise AssertionError(f"Column `{column}` is not constant within a 60-minute bucket.")

    hourly = (
        df.assign(_hour_bucket_start=bucket_start)
        .groupby("_hour_bucket_start", sort=True)
        .agg(
            hour_high=("high", "max"),
            hour_low=("low", "min"),
            hour_close=("close", "last"),
            bar_count=("close", "size"),
        )
    )
    pivot = (hourly["hour_high"] + hourly["hour_low"] + hourly["hour_close"]) / 3.0
    hour_range = hourly["hour_high"] - hourly["hour_low"]
    expected = pd.DataFrame(
        {
            "hourly_pivot": pivot.shift(1),
            "hourly_r1": (pivot + (pivot - hourly["hour_low"])).shift(1),
            "hourly_s1": (pivot - (hourly["hour_high"] - pivot)).shift(1),
            "hourly_r2": (pivot + hour_range).shift(1),
            "hourly_s2": (pivot - hour_range).shift(1),
            "hourly_r3": ((pivot + (pivot - hourly["hour_low"])) + hour_range).shift(1)
            if show_r3_s3
            else pd.Series(np.nan, index=hourly.index, dtype=float),
            "hourly_s3": ((pivot - (hourly["hour_high"] - pivot)) - hour_range).shift(1)
            if show_r3_s3
            else pd.Series(np.nan, index=hourly.index, dtype=float),
        }
    )

    first_rows = df.loc[~bucket_start.duplicated(), OUTPUT_COLUMNS].copy()
    first_rows.index = bucket_start[~bucket_start.duplicated()]
    if not first_rows.index.equals(expected.index):
        raise AssertionError("Projected buckets do not align with expected hourly bucket index.")

    for column in OUTPUT_COLUMNS:
        if not np.allclose(first_rows[column], expected[column], equal_nan=True):
            raise AssertionError(
                f"Column `{column}` does not match the previous completed 60-minute bucket."
            )

    if (hourly["bar_count"] == 1).all():
        direct_pivot = (df["high"] + df["low"] + df["close"]) / 3.0
        direct_range = df["high"] - df["low"]
        direct_expected = pd.DataFrame(
            {
                "hourly_pivot": direct_pivot.shift(1),
                "hourly_r1": (direct_pivot + (direct_pivot - df["low"])).shift(1),
                "hourly_s1": (direct_pivot - (df["high"] - direct_pivot)).shift(1),
                "hourly_r2": (direct_pivot + direct_range).shift(1),
                "hourly_s2": (direct_pivot - direct_range).shift(1),
                "hourly_r3": ((direct_pivot + (direct_pivot - df["low"])) + direct_range).shift(1)
                if show_r3_s3
                else pd.Series(np.nan, index=df.index, dtype=float),
                "hourly_s3": ((direct_pivot - (df["high"] - direct_pivot)) - direct_range).shift(1)
                if show_r3_s3
                else pd.Series(np.nan, index=df.index, dtype=float),
            }
        )
        for column in OUTPUT_COLUMNS:
            if not np.allclose(df[column], direct_expected[column], equal_nan=True):
                raise AssertionError(
                    f"Column `{column}` does not match direct previous-row formulas on 60-minute input."
                )
        print("PASS sample is already 60-minute data, so projected values match previous-row formulas")

    print("Internal sanity checks:")
    print("PASS first projected bucket remains NaN")
    print("PASS projected levels remain constant within each 60-minute bucket")
    print("PASS each bucket uses the previous completed 60-minute bucket")
    print("PASS session-anchored hourly grouping handles 09:15-style NSE bars")


# -- MANUAL REVIEW ----------------------------------------------------------
def _format_price(value: float) -> str:
    """Format prices for compact output."""
    if pd.isna(value):
        return "NaN"
    return f"{value:,.2f}"


def _resolve_target_index(
    df: pd.DataFrame,
    timestamp: Optional[str | pd.Timestamp] = None,
) -> pd.Timestamp:
    """Resolve the target bar to inspect; defaults to the latest available row."""
    if timestamp is None:
        return df.index[-1]

    target = pd.Timestamp(timestamp)
    if target.tzinfo is None:
        target = target.tz_localize(EXCHANGE_TIMEZONE).tz_convert("UTC")
    else:
        target = target.tz_convert("UTC")

    eligible = df.index[df.index <= target]
    if len(eligible) == 0:
        raise ValueError(f"No rows found at or before {target}.")
    return eligible[-1]


def print_hour_bucket_levels(
    df: pd.DataFrame,
    timestamp: Optional[str | pd.Timestamp] = None,
) -> None:
    """
    Print the projected hourly pivot ladder for a chosen bar so it can be
    compared manually against a TradingView screenshot.
    """
    missing = [column for column in OUTPUT_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            "print_hour_bucket_levels requires these columns to exist: "
            + ", ".join(missing)
        )

    target_index = _resolve_target_index(df, timestamp)
    row = df.loc[target_index]
    local_target = target_index.tz_convert(EXCHANGE_TIMEZONE)
    bucket_start = _build_hour_bucket_start(df.index)
    target_bucket = bucket_start.loc[target_index]
    previous_bucket = bucket_start[bucket_start < target_bucket]
    previous_bucket_start = previous_bucket.iloc[-1] if len(previous_bucket) > 0 else pd.NaT

    print("\nProjected hourly pivot ladder:")
    print(f"  target_bar_utc     : {target_index}")
    print(f"  target_bar_local   : {local_target}")
    print(f"  current_bucket     : {target_bucket}")
    print(f"  previous_bucket    : {previous_bucket_start if pd.notna(previous_bucket_start) else 'None'}")
    print(f"  hourly_pivot       : {_format_price(row['hourly_pivot'])}")
    print(f"  hourly_r1          : {_format_price(row['hourly_r1'])}")
    print(f"  hourly_s1          : {_format_price(row['hourly_s1'])}")
    print(f"  hourly_r2          : {_format_price(row['hourly_r2'])}")
    print(f"  hourly_s2          : {_format_price(row['hourly_s2'])}")
    print(f"  hourly_r3          : {_format_price(row['hourly_r3'])}")
    print(f"  hourly_s3          : {_format_price(row['hourly_s3'])}")

    print("\nManual screenshot review:")
    print("  1. Open the same symbol and chart timeframe in TradingView.")
    print(f"  2. Navigate to the local bar time {local_target}.")
    print("  3. Compare pivot, R1/S1, and R2/S2 first.")
    print("  4. R3/S3 are expected to be hidden by default because sh3=false in Pine.")


# -- MAIN -------------------------------------------------------------------
def main(sample_path: str | Path) -> None:
    """Load CSV, calculate hourly pivots, run checks, and print the latest ladder."""
    sample_df = load_csv_data(sample_path)
    market_df = sample_df.loc[:, list(REQUIRED_PRICE_COLUMNS)].copy()
    indicator_df = calculate_indicators(market_df, show_r3_s3=SHOW_R3_S3)

    run_internal_sanity_checks(indicator_df, show_r3_s3=SHOW_R3_S3)
    print_hour_bucket_levels(indicator_df)

    preview_columns = [
        "open",
        "high",
        "low",
        "close",
        "hourly_pivot",
        "hourly_r1",
        "hourly_s1",
        "hourly_r2",
        "hourly_s2",
    ]
    print("\nIndicator preview:")
    print(indicator_df.loc[:, preview_columns].tail(5).to_string())


if __name__ == "__main__":
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    main(csv_path)
