"""
# ============================================================
# INDICATOR: Cpr sakthi (Vedhaviyash4 Daily CPR Port)
# Converted from Pine Script v4 | 2026-03-20
# Original Pine author: vedhaviyash4
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "Cpr sakthi"
PINE_SHORT_NAME = "CPR"
PINE_VERSION = 4
PINE_AUTHOR = "vedhaviyash4"

EXCHANGE_TIMEZONE = "Asia/Kolkata"
MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\NSE_BANKNIFTY_60_5568bars.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
OUTPUT_COLUMNS = (
    "daily_pivot",
    "daily_bc",
    "daily_tc",
    "prev_day_high",
    "prev_day_low",
    "daily_r1",
    "daily_r2",
    "daily_r3",
    "daily_r4",
    "daily_s1",
    "daily_s2",
    "daily_s3",
    "daily_s4",
)
LEGACY_SAMPLE_COLUMNS = (
    "CPR_Vedhaviyash4_daily_pivot",
    "CPR_Vedhaviyash4_daily_bc",
    "CPR_Vedhaviyash4_daily_tc",
    "CPR_Vedhaviyash4_prev_day_high",
    "CPR_Vedhaviyash4_prev_day_low",
    "CPR_Vedhaviyash4_daily_r1",
    "CPR_Vedhaviyash4_daily_r2",
    "CPR_Vedhaviyash4_daily_r3",
    "CPR_Vedhaviyash4_daily_r4",
    "CPR_Vedhaviyash4_daily_s1",
    "CPR_Vedhaviyash4_daily_s2",
    "CPR_Vedhaviyash4_daily_s3",
    "CPR_Vedhaviyash4_daily_s4",
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


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replicate the intended corrected daily CPR behavior for the Vedhaviyash4
    script by using the previous completed trading day's OHLC on intraday bars.

    Input df must have: timestamp (index), open, high, low, close, volume.
    Returns df with the plotted CPR columns appended.
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
            session_open=("open", "first"),
            session_high=("high", "max"),
            session_low=("low", "min"),
            session_close=("close", "last"),
            session_volume=("volume", "sum"),
        )
    )

    prev_daily = daily.shift(1)
    prev_daily_aligned = prev_daily.reindex(working["_session_key"]).set_axis(working.index)

    prev_day_high = prev_daily_aligned["session_high"]
    prev_day_low = prev_daily_aligned["session_low"]
    prev_day_close = prev_daily_aligned["session_close"]

    daily_pivot = (prev_day_high + prev_day_low + prev_day_close) / 3.0
    daily_bc = (prev_day_high + prev_day_low) / 2.0
    daily_tc = (2.0 * daily_pivot) - daily_bc
    range_size = prev_day_high - prev_day_low

    daily_r1 = (2.0 * daily_pivot) - prev_day_low
    daily_r2 = daily_pivot + range_size
    daily_r3 = daily_r1 + range_size
    daily_r4 = daily_r3 + daily_r2 - daily_r1

    daily_s1 = (2.0 * daily_pivot) - prev_day_high
    daily_s2 = daily_pivot - prev_day_high + prev_day_low
    daily_s3 = daily_s1 - prev_day_high + prev_day_low
    daily_s4 = daily_s3 + daily_s2 - daily_s1

    working = working.assign(
        daily_pivot=daily_pivot,
        daily_bc=daily_bc,
        daily_tc=daily_tc,
        prev_day_high=prev_day_high,
        prev_day_low=prev_day_low,
        daily_r1=daily_r1,
        daily_r2=daily_r2,
        daily_r3=daily_r3,
        daily_r4=daily_r4,
        daily_s1=daily_s1,
        daily_s2=daily_s2,
        daily_s3=daily_s3,
        daily_s4=daily_s4,
    )

    return working.drop(columns=["_session_key"])


# -- VALIDATION -------------------------------------------------------------
def _series_is_session_constant(series: pd.Series) -> bool:
    """Return True when a series has at most one non-NaN value per local session."""
    local_index = _normalize_index_timezone(series.index)
    session_key = local_index.normalize()
    unique_counts = series.groupby(session_key).nunique(dropna=True)
    return bool((unique_counts <= 1).all())


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """
    Verify the corrected daily CPR has no lookahead and stays constant within
    each session after the initial warmup day.
    """
    required_columns = list(REQUIRED_PRICE_COLUMNS) + list(OUTPUT_COLUMNS)
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires these columns to exist: "
            + ", ".join(missing)
        )

    local_index = _normalize_index_timezone(df.index)
    session_key = local_index.normalize()
    first_bar_mask = ~session_key.duplicated()

    first_session = session_key[first_bar_mask][0]
    first_session_rows = session_key == first_session
    if not df.loc[first_session_rows, OUTPUT_COLUMNS].isna().all().all():
        raise AssertionError(
            "First available session must remain NaN because no prior daily session exists."
        )

    for column in OUTPUT_COLUMNS:
        unique_counts = df[column].groupby(session_key).nunique(dropna=True)
        if not (unique_counts.iloc[1:] <= 1).all():
            raise AssertionError(f"Column `{column}` is not constant within a trading session.")

    daily = (
        df.groupby(session_key, sort=True)
        .agg(
            session_high=("high", "max"),
            session_low=("low", "min"),
            session_close=("close", "last"),
        )
    )
    prev_daily = daily.shift(1)

    expected = pd.DataFrame(index=prev_daily.index)
    expected["prev_day_high"] = prev_daily["session_high"]
    expected["prev_day_low"] = prev_daily["session_low"]
    expected["daily_pivot"] = (
        prev_daily["session_high"] + prev_daily["session_low"] + prev_daily["session_close"]
    ) / 3.0
    expected["daily_bc"] = (prev_daily["session_high"] + prev_daily["session_low"]) / 2.0
    expected["daily_tc"] = (2.0 * expected["daily_pivot"]) - expected["daily_bc"]
    range_size = prev_daily["session_high"] - prev_daily["session_low"]
    expected["daily_r1"] = (2.0 * expected["daily_pivot"]) - prev_daily["session_low"]
    expected["daily_r2"] = expected["daily_pivot"] + range_size
    expected["daily_r3"] = expected["daily_r1"] + range_size
    expected["daily_r4"] = expected["daily_r3"] + expected["daily_r2"] - expected["daily_r1"]
    expected["daily_s1"] = (2.0 * expected["daily_pivot"]) - prev_daily["session_high"]
    expected["daily_s2"] = expected["daily_pivot"] - prev_daily["session_high"] + prev_daily["session_low"]
    expected["daily_s3"] = expected["daily_s1"] - prev_daily["session_high"] + prev_daily["session_low"]
    expected["daily_s4"] = expected["daily_s3"] + expected["daily_s2"] - expected["daily_s1"]

    first_bar_rows = df.loc[first_bar_mask, list(OUTPUT_COLUMNS)].copy()
    first_bar_rows.index = session_key[first_bar_mask]

    comparable_sessions = expected.index[1:]
    for column in OUTPUT_COLUMNS:
        if not np.allclose(
            first_bar_rows.loc[comparable_sessions, column],
            expected.loc[comparable_sessions, column],
            equal_nan=True,
        ):
            raise AssertionError(
                f"Column `{column}` does not match previous-session daily mapping on session boundaries."
            )

    print("Internal sanity checks:")
    print("PASS first-session CPR remains NaN")
    print("PASS all CPR levels stay constant within each trading day")
    print("PASS session boundaries use the previous completed trading day")
    print("PASS weekend and holiday gaps are handled by trading-session order")


def warn_about_legacy_sample_columns(sample_df: pd.DataFrame) -> None:
    """
    Warn when the sample contains the legacy Vedhaviyash4 export columns that
    reflect the obsolete 60-minute logic instead of corrected daily CPR logic.
    """
    present_columns = [column for column in LEGACY_SAMPLE_COLUMNS if column in sample_df.columns]
    if not present_columns:
        print("No legacy `CPR_Vedhaviyash4_*` sample columns detected.")
        return

    varying_columns = [
        column for column in present_columns if not _series_is_session_constant(sample_df[column])
    ]

    print("\nLegacy sample warning:")
    print(
        "Detected `CPR_Vedhaviyash4_*` columns in the CSV. These are not used as parity targets "
        "for this corrected daily CPR port."
    )
    if varying_columns:
        shown = ", ".join(varying_columns[:4])
        print(
            "They change within the same trading day, which indicates the older intraday/60-minute "
            f"logic. Example varying columns: {shown}"
        )
    else:
        shown = ", ".join(present_columns[:4])
        print(
            "They are present in the file, but screenshot-only validation means this module still "
            f"treats them as informational only. Example columns: {shown}"
        )


# -- MANUAL REVIEW ----------------------------------------------------------
def _resolve_target_session(
    df: pd.DataFrame,
    timestamp: Optional[str | pd.Timestamp] = None,
) -> pd.Timestamp:
    """Resolve a target local session date from an optional timestamp or date-like string."""
    local_index = _normalize_index_timezone(df.index)
    session_key = local_index.normalize()

    if timestamp is None:
        return session_key[-1]

    target = pd.Timestamp(timestamp)
    if target.tzinfo is None:
        if target.hour == 0 and target.minute == 0 and target.second == 0 and target.nanosecond == 0:
            return target.tz_localize(EXCHANGE_TIMEZONE).normalize()
        return target.tz_localize(EXCHANGE_TIMEZONE).normalize()

    return target.tz_convert(EXCHANGE_TIMEZONE).normalize()


def _format_price(value: float) -> str:
    """Format a price value for compact manual review output."""
    if pd.isna(value):
        return "NaN"
    return f"{value:,.2f}"


def print_session_levels(df: pd.DataFrame, timestamp: Optional[str | pd.Timestamp] = None) -> None:
    """
    Print the CPR ladder for a single trading session so it can be compared
    manually against a TradingView screenshot.
    """
    required_columns = list(OUTPUT_COLUMNS)
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "print_session_levels requires these indicator columns to exist: "
            + ", ".join(missing)
        )

    local_index = _normalize_index_timezone(df.index)
    session_key = local_index.normalize()
    target_session = _resolve_target_session(df, timestamp)
    session_rows = df.loc[session_key == target_session]
    if session_rows.empty:
        raise ValueError(f"No rows found for local trading session {target_session.date()}.")

    row = session_rows.iloc[0]
    first_bar_index = session_rows.index[0]
    session_dates = pd.Index(session_key.unique()).sort_values()
    session_position = session_dates.get_loc(target_session)
    previous_session = session_dates[session_position - 1] if session_position > 0 else pd.NaT

    cpr_top = max(row["daily_bc"], row["daily_tc"]) if pd.notna(row["daily_bc"]) and pd.notna(row["daily_tc"]) else np.nan
    cpr_bottom = min(row["daily_bc"], row["daily_tc"]) if pd.notna(row["daily_bc"]) and pd.notna(row["daily_tc"]) else np.nan

    print("\nSession CPR ladder:")
    print(f"  session_date    : {target_session.date()}")
    print(f"  first_bar_utc   : {first_bar_index}")
    print(f"  previous_session: {previous_session.date() if pd.notna(previous_session) else 'None'}")
    print(f"  prev_day_high   : {_format_price(row['prev_day_high'])}")
    print(f"  prev_day_low    : {_format_price(row['prev_day_low'])}")
    print(f"  daily_pivot     : {_format_price(row['daily_pivot'])}")
    print(f"  daily_bc        : {_format_price(row['daily_bc'])}")
    print(f"  daily_tc        : {_format_price(row['daily_tc'])}")
    print(f"  cpr_top         : {_format_price(cpr_top)}")
    print(f"  cpr_bottom      : {_format_price(cpr_bottom)}")
    print(f"  daily_r1        : {_format_price(row['daily_r1'])}")
    print(f"  daily_r2        : {_format_price(row['daily_r2'])}")
    print(f"  daily_r3        : {_format_price(row['daily_r3'])}")
    print(f"  daily_r4        : {_format_price(row['daily_r4'])}")
    print(f"  daily_s1        : {_format_price(row['daily_s1'])}")
    print(f"  daily_s2        : {_format_price(row['daily_s2'])}")
    print(f"  daily_s3        : {_format_price(row['daily_s3'])}")
    print(f"  daily_s4        : {_format_price(row['daily_s4'])}")

    print("\nManual screenshot review:")
    print("  1. Open the same symbol and intraday timeframe in TradingView.")
    print(f"  2. Navigate to the local session date {target_session.date()} in {EXCHANGE_TIMEZONE}.")
    print("  3. Compare pivot, BC/TC, R1/R2, and S1/S2 first.")
    print("  4. Treat the screenshot as qualitative confirmation only, not exact numeric parity.")


# -- MAIN -------------------------------------------------------------------
def main(sample_path: str | Path) -> None:
    """Load CSV, compute corrected daily CPR, run checks, and print a session ladder."""
    sample_df = load_csv_data(sample_path)
    market_df = sample_df.loc[:, list(REQUIRED_PRICE_COLUMNS)].copy()
    indicator_df = calculate_indicators(market_df)

    run_internal_sanity_checks(indicator_df)
    warn_about_legacy_sample_columns(sample_df)
    print_session_levels(indicator_df)

    preview_columns = [
        "open",
        "high",
        "low",
        "close",
        "daily_pivot",
        "daily_bc",
        "daily_tc",
        "daily_r1",
        "daily_s1",
    ]
    print("\nIndicator preview:")
    print(indicator_df.loc[:, preview_columns].tail(5).to_string())


if __name__ == "__main__":
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    main(csv_path)
