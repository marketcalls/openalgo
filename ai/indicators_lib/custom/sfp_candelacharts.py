"""
# ============================================================
# INDICATOR: CandelaCharts - Swing Failure Pattern (SFP)
# Converted from Pine Script v6 | 2026-03-20
# Original Pine author: CandelaCharts
# ============================================================
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "CandelaCharts - Swing Failure Pattern (SFP)"
PINE_SHORT_NAME = "CandelaCharts - Swing Failure Pattern (SFP)"
PINE_AUTHOR = "CandelaCharts"

DEFAULT_LENGTH = 7
DEFAULT_BULL_ENABLED = True
DEFAULT_BEAR_ENABLED = True
DEFAULT_BUFFER = 100
MAX_BARS_INVALIDATION = 500

EXCHANGE_TIMEZONE = "Asia/Kolkata"
MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\NSE_BANKNIFTY_60_5568bars.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
OUTPUT_COLUMNS = (
    "bullish_sfp",
    "bearish_sfp",
    "bull_active",
    "bull_confirmed",
    "bull_invalidated",
    "bull_swing_price",
    "bull_opposing_price",
    "bear_active",
    "bear_confirmed",
    "bear_invalidated",
    "bear_swing_price",
    "bear_opposing_price",
    "SFP_CandelaCharts_Bullish_SFP",
    "SFP_CandelaCharts_Bearish_SFP",
)
VALIDATION_COLUMN_ALIASES = {
    "bullish_sfp": ("SFP_CandelaCharts_Bullish_SFP",),
    "bearish_sfp": ("SFP_CandelaCharts_Bearish_SFP",),
    "SFP_CandelaCharts_Bullish_SFP": ("SFP_CandelaCharts_Bullish_SFP",),
    "SFP_CandelaCharts_Bearish_SFP": ("SFP_CandelaCharts_Bearish_SFP",),
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


# -- CORE HELPERS -----------------------------------------------------------
@dataclass
class _SfpState:
    swing_price: float
    swing_bar_index: int
    opposing_price: float
    opposing_bar_index: int
    active: bool = True
    confirmed: bool = False
    invalidated: bool = False
    alert_fired: bool = False


def _pivot_high_series(high: np.ndarray, left: int, right: int = 1) -> np.ndarray:
    """
    Pine-style pivot high aligned to the detection bar.

    With `right=1`, the pivot belongs to bar `i-1` and becomes known on bar `i`.
    Semantics used here match TradingView behavior for equality:
    - center >= all left bars
    - center > all right bars
    """
    out = np.full(high.shape[0], np.nan, dtype=float)
    for i in range(left + right, high.shape[0]):
        pivot_idx = i - right
        center = high[pivot_idx]
        left_slice = high[pivot_idx - left : pivot_idx]
        right_slice = high[pivot_idx + 1 : pivot_idx + right + 1]
        if np.isnan(center):
            continue
        if np.all(center >= left_slice) and np.all(center > right_slice):
            out[i] = center
    return out


def _pivot_low_series(low: np.ndarray, left: int, right: int = 1) -> np.ndarray:
    """
    Pine-style pivot low aligned to the detection bar.

    With `right=1`, the pivot belongs to bar `i-1` and becomes known on bar `i`.
    Semantics used here match TradingView behavior for equality:
    - center <= all left bars
    - center < all right bars
    """
    out = np.full(low.shape[0], np.nan, dtype=float)
    for i in range(left + right, low.shape[0]):
        pivot_idx = i - right
        center = low[pivot_idx]
        left_slice = low[pivot_idx - left : pivot_idx]
        right_slice = low[pivot_idx + 1 : pivot_idx + right + 1]
        if np.isnan(center):
            continue
        if np.all(center <= left_slice) and np.all(center < right_slice):
            out[i] = center
    return out


def _run_sfp_state_machine(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    sfp_ph: np.ndarray,
    sfp_pl: np.ndarray,
    bull_enabled: bool,
    bear_enabled: bool,
) -> dict[str, np.ndarray]:
    """Sequentially run the bullish/bearish SFP state machines."""
    n = close.shape[0]

    bullish_sfp = np.zeros(n, dtype=bool)
    bearish_sfp = np.zeros(n, dtype=bool)

    bull_active = np.zeros(n, dtype=bool)
    bull_confirmed = np.zeros(n, dtype=bool)
    bull_invalidated = np.zeros(n, dtype=bool)
    bull_swing_price = np.full(n, np.nan, dtype=float)
    bull_opposing_price = np.full(n, np.nan, dtype=float)

    bear_active = np.zeros(n, dtype=bool)
    bear_confirmed = np.zeros(n, dtype=bool)
    bear_invalidated = np.zeros(n, dtype=bool)
    bear_swing_price = np.full(n, np.nan, dtype=float)
    bear_opposing_price = np.full(n, np.nan, dtype=float)

    swing_h_price = np.nan
    swing_h_bar_index = -1
    swing_l_price = np.nan
    swing_l_bar_index = -1

    bear_state: Optional[_SfpState] = None
    bull_state: Optional[_SfpState] = None

    for i in range(n):
        if bear_enabled and not np.isnan(sfp_ph[i]):
            swing_h_bar_index = i - 1
            swing_h_price = sfp_ph[i]

        if bull_enabled and not np.isnan(sfp_pl[i]):
            swing_l_bar_index = i - 1
            swing_l_price = sfp_pl[i]

        if bear_enabled and not np.isnan(swing_h_price):
            if high[i] > swing_h_price and open_[i] < swing_h_price and close[i] < swing_h_price:
                opposing_price = swing_h_price
                opposing_bar_index = swing_h_bar_index
                for j in range(swing_h_bar_index + 1, i):
                    if low[j] < opposing_price:
                        opposing_price = low[j]
                        opposing_bar_index = j

                if bear_state is not None and not bear_state.confirmed:
                    bear_state.invalidated = True
                    bear_state.active = False

                bear_state = _SfpState(
                    swing_price=float(swing_h_price),
                    swing_bar_index=int(swing_h_bar_index),
                    opposing_price=float(opposing_price),
                    opposing_bar_index=int(opposing_bar_index),
                )

        if bull_enabled and not np.isnan(swing_l_price):
            if low[i] < swing_l_price and open_[i] > swing_l_price and close[i] > swing_l_price:
                opposing_price = swing_l_price
                opposing_bar_index = swing_l_bar_index
                for j in range(swing_l_bar_index + 1, i):
                    if high[j] > opposing_price:
                        opposing_price = high[j]
                        opposing_bar_index = j

                if bull_state is not None and not bull_state.confirmed:
                    bull_state.invalidated = True
                    bull_state.active = False

                bull_state = _SfpState(
                    swing_price=float(swing_l_price),
                    swing_bar_index=int(swing_l_bar_index),
                    opposing_price=float(opposing_price),
                    opposing_bar_index=int(opposing_bar_index),
                )

        if bear_enabled and bear_state is not None and bear_state.active and not bear_state.confirmed:
            if close[i] < bear_state.opposing_price:
                bear_state.confirmed = True
                bear_state.active = False
                if not bear_state.invalidated and not bear_state.alert_fired:
                    bearish_sfp[i] = True
                    bear_state.alert_fired = True

        if bull_enabled and bull_state is not None and bull_state.active and not bull_state.confirmed:
            if close[i] > bull_state.opposing_price:
                bull_state.confirmed = True
                bull_state.active = False
                if not bull_state.invalidated and not bull_state.alert_fired:
                    bullish_sfp[i] = True
                    bull_state.alert_fired = True

        if bear_enabled and bear_state is not None and bear_state.active and not bear_state.confirmed:
            in_range = close[i] > bear_state.swing_price
            bars_since_swing = i - bear_state.swing_bar_index
            if bars_since_swing > MAX_BARS_INVALIDATION or in_range:
                bear_state.active = False
                bear_state.invalidated = True

        if bull_enabled and bull_state is not None and bull_state.active and not bull_state.confirmed:
            in_range = close[i] < bull_state.swing_price
            bars_since_swing = i - bull_state.swing_bar_index
            if bars_since_swing > MAX_BARS_INVALIDATION or in_range:
                bull_state.active = False
                bull_state.invalidated = True

        if bear_state is not None:
            bear_active[i] = bear_state.active
            bear_confirmed[i] = bear_state.confirmed
            bear_invalidated[i] = bear_state.invalidated
            bear_swing_price[i] = bear_state.swing_price
            bear_opposing_price[i] = bear_state.opposing_price

        if bull_state is not None:
            bull_active[i] = bull_state.active
            bull_confirmed[i] = bull_state.confirmed
            bull_invalidated[i] = bull_state.invalidated
            bull_swing_price[i] = bull_state.swing_price
            bull_opposing_price[i] = bull_state.opposing_price

    return {
        "bullish_sfp": bullish_sfp,
        "bearish_sfp": bearish_sfp,
        "bull_active": bull_active,
        "bull_confirmed": bull_confirmed,
        "bull_invalidated": bull_invalidated,
        "bull_swing_price": bull_swing_price,
        "bull_opposing_price": bull_opposing_price,
        "bear_active": bear_active,
        "bear_confirmed": bear_confirmed,
        "bear_invalidated": bear_invalidated,
        "bear_swing_price": bear_swing_price,
        "bear_opposing_price": bear_opposing_price,
    }


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    length: int = DEFAULT_LENGTH,
    bull_enabled: bool = DEFAULT_BULL_ENABLED,
    bear_enabled: bool = DEFAULT_BEAR_ENABLED,
) -> pd.DataFrame:
    """
    Replicate the CandelaCharts SFP state machine and return parity-critical
    bullish/bearish signal columns plus compact internal state.
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")
    if length < 1:
        raise ValueError("length must be >= 1")

    working = df.copy().sort_index()
    open_ = working["open"].to_numpy(dtype=float)
    high = working["high"].to_numpy(dtype=float)
    low = working["low"].to_numpy(dtype=float)
    close = working["close"].to_numpy(dtype=float)

    sfp_ph = _pivot_high_series(high, left=length, right=1)
    sfp_pl = _pivot_low_series(low, left=length, right=1)
    outputs = _run_sfp_state_machine(
        open_=open_,
        high=high,
        low=low,
        close=close,
        sfp_ph=sfp_ph,
        sfp_pl=sfp_pl,
        bull_enabled=bull_enabled,
        bear_enabled=bear_enabled,
    )

    working = working.assign(**outputs)
    working["SFP_CandelaCharts_Bullish_SFP"] = working["bullish_sfp"].astype(int)
    working["SFP_CandelaCharts_Bearish_SFP"] = working["bearish_sfp"].astype(int)
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
    length: int = DEFAULT_LENGTH,
) -> None:
    """
    Verify pivot timing assumptions and core SFP state invariants.
    """
    missing = [column for column in OUTPUT_COLUMNS + REQUIRED_PRICE_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires these columns to exist: "
            + ", ".join(missing)
        )

    both_signals = df["bullish_sfp"] & df["bearish_sfp"]
    if both_signals.any():
        first_idx = both_signals[both_signals].index[0]
        raise AssertionError(f"Bullish and bearish SFP both fired on {first_idx}.")

    if (df["bull_active"] & df["bull_confirmed"]).any():
        raise AssertionError("A bullish SFP cannot be both active and confirmed.")

    if (df["bear_active"] & df["bear_confirmed"]).any():
        raise AssertionError("A bearish SFP cannot be both active and confirmed.")

    if (df["bullish_sfp"] & ~df["bull_confirmed"]).any():
        raise AssertionError("bullish_sfp can only fire on bars where the latest bullish state is confirmed.")

    if (df["bearish_sfp"] & ~df["bear_confirmed"]).any():
        raise AssertionError("bearish_sfp can only fire on bars where the latest bearish state is confirmed.")

    first_possible_detection = length + 1
    if df["bullish_sfp"].iloc[:first_possible_detection].any():
        raise AssertionError("Bullish SFP fired before a pivot-low could exist with right=1 timing.")
    if df["bearish_sfp"].iloc[:first_possible_detection].any():
        raise AssertionError("Bearish SFP fired before a pivot-high could exist with right=1 timing.")

    print("Internal sanity checks:")
    print("PASS bullish and bearish SFP never fire on the same bar")
    print("PASS active and confirmed flags are mutually exclusive")
    print("PASS right=1 pivot timing prevents signals before enough history exists")


def validate_against_sample(
    df: pd.DataFrame,
    sample_path: str | Path,
    length: int = DEFAULT_LENGTH,
) -> None:
    """
    Compare bullish/bearish SFP signals exactly against the sample export and
    raise AssertionError on the first mismatch.
    """
    run_internal_sanity_checks(df, length=length)

    sample_df = load_csv_data(sample_path)
    common_index = df.index.intersection(sample_df.index)
    if common_index.empty:
        raise ValueError("No overlapping timestamps found between calculated data and sample file.")

    aligned_df = df.loc[common_index]
    aligned_sample = sample_df.loc[common_index]

    report_rows = []
    failures = []
    for output_name in (
        "bullish_sfp",
        "bearish_sfp",
        "SFP_CandelaCharts_Bullish_SFP",
        "SFP_CandelaCharts_Bearish_SFP",
    ):
        sample_column = _find_matching_sample_column(
            aligned_sample,
            VALIDATION_COLUMN_ALIASES[output_name],
        )
        if sample_column is None:
            report_rows.append((output_name, "not available in sample"))
            continue

        passed, mismatch_idx = _compare_boolean_series(aligned_df[output_name], aligned_sample[sample_column])
        if passed:
            report_rows.append((output_name, "PASS exact"))
        else:
            report_rows.append((output_name, f"FAIL first_mismatch={mismatch_idx}"))
            failures.append((output_name, mismatch_idx))

    print("Validation report:")
    for indicator, status in report_rows:
        print(f"  {indicator}: {status}")

    if failures:
        details = [f"{indicator} mismatch at {mismatch_idx}" for indicator, mismatch_idx in failures]
        raise AssertionError("SFP validation failed:\n" + "\n".join(details))

    bull_count = int(aligned_df["bullish_sfp"].sum())
    bear_count = int(aligned_df["bearish_sfp"].sum())
    print(f"\nSignal counts: bullish={bull_count}, bearish={bear_count}")
    print("PASS: bullish and bearish SFP outputs match the sample exactly.")


# -- MAIN -------------------------------------------------------------------
def main(sample_path: str | Path) -> None:
    """Load CSV, calculate SFP outputs, validate, and print a compact summary."""
    sample_df = load_csv_data(sample_path)
    market_df = sample_df.loc[:, list(REQUIRED_PRICE_COLUMNS)].copy()
    indicator_df = calculate_indicators(
        market_df,
        length=DEFAULT_LENGTH,
        bull_enabled=DEFAULT_BULL_ENABLED,
        bear_enabled=DEFAULT_BEAR_ENABLED,
    )

    validate_against_sample(indicator_df, sample_path, length=DEFAULT_LENGTH)

    preview_columns = [
        "open",
        "high",
        "low",
        "close",
        "bullish_sfp",
        "bearish_sfp",
        "bull_active",
        "bull_confirmed",
        "bull_invalidated",
        "bear_active",
        "bear_confirmed",
        "bear_invalidated",
    ]
    print("\nIndicator preview:")
    print(indicator_df.loc[:, preview_columns].tail(15).to_string())


if __name__ == "__main__":
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    main(csv_path)
