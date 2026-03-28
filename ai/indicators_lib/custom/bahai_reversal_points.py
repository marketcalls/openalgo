"""
# ============================================================
# INDICATOR: Baha'i Reversal Points [CC]
# Converted from Pine Script v5 source | 2026-03-21
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "Baha'i Reversal Points [CC]"
DEFAULT_LENGTH = 19
DEFAULT_LOOKBACK_LENGTH = 9
DEFAULT_THRESHOLD_LEVEL = 1.0  # Declared in Pine, but unused in calculations.
DEFAULT_ALLOW_REPAINTING = False
DEFAULT_ALLOW_BAR_COLOR_CHANGE = True
MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\Bahai_Reversal_Points.csv")
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
def _pine_nz(series: pd.Series, replacement: float = 0.0) -> pd.Series:
    """Replicate Pine's nz() for numeric series."""
    return series.fillna(replacement)


def _pine_crossover(series: pd.Series, level: float) -> pd.Series:
    """Replicate ta.crossover(series, level)."""
    previous = series.shift(1)
    return (series > level) & (previous <= level)


def _pine_crossunder(series: pd.Series, level: float) -> pd.Series:
    """Replicate ta.crossunder(series, level)."""
    previous = series.shift(1)
    return (series < level) & (previous >= level)


def _request_security_current_timeframe_non_repainting(
    df: pd.DataFrame,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Replicate the script's requestSecurity() behavior for the default inputs.

    With:
    - `res = ""` (current chart timeframe)
    - `rep = false`
    - historical data

    the wrapper resolves to the previous completed bar values on the current
    timeframe. That is exactly what the sample export uses.
    """
    h = df["high"].shift(1)
    l = df["low"].shift(1)
    o = df["open"].shift(1)
    c = df["close"].shift(1)
    return h, l, o, c


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    length: int = DEFAULT_LENGTH,
    lookback_length: int = DEFAULT_LOOKBACK_LENGTH,
    threshold_level: float = DEFAULT_THRESHOLD_LEVEL,
    allow_repainting: bool = DEFAULT_ALLOW_REPAINTING,
    allow_bar_color_change: bool = DEFAULT_ALLOW_BAR_COLOR_CHANGE,
) -> pd.DataFrame:
    """
    Replicate the pasted Baha'i Reversal Points script using the default sample settings.

    Note:
    - `threshold_level` is declared in the Pine source but not used in the logic.
    - `allow_repainting` only affects the `request.security()` wrapper. The sample
      export uses the default non-repainting behavior.
    """
    del threshold_level
    _require_price_columns(df)
    working = df.copy().sort_index()

    if allow_repainting:
        h = working["high"].astype(float).copy()
        l = working["low"].astype(float).copy()
        o = working["open"].astype(float).copy()
        c = working["close"].astype(float).copy()
    else:
        h, l, o, c = _request_security_current_timeframe_non_repainting(working)

    lp_sum = (l < _pine_nz(l.shift(lookback_length), 0.0)).astype(float).rolling(
        length, min_periods=length
    ).sum()
    hp_sum = (h > _pine_nz(h.shift(lookback_length), 0.0)).astype(float).rolling(
        length, min_periods=length
    ).sum()

    slo = pd.Series(
        np.where(lp_sum >= length, 1.0, np.where(hp_sum >= length, -1.0, 0.0)),
        index=working.index,
        dtype=float,
    )

    prev_slo = _pine_nz(slo.shift(1), 0.0)
    sig = pd.Series(
        np.where(
            slo > 0.0,
            np.where(slo > prev_slo, 2.0, 1.0),
            np.where(slo < 0.0, np.where(slo < prev_slo, -2.0, -1.0), 0.0),
        ),
        index=working.index,
        dtype=float,
    )

    strong_buy_signal = _pine_crossover(sig, 1.0).astype(int)
    strong_sell_signal = _pine_crossunder(sig, -1.0).astype(int)
    buy_signal = _pine_crossover(sig, 0.0).astype(int)
    sell_signal = _pine_crossunder(sig, 0.0).astype(int)
    all_buy_signals = (strong_buy_signal.eq(1) | buy_signal.eq(1)).astype(int)
    all_sell_signals = (strong_sell_signal.eq(1) | sell_signal.eq(1)).astype(int)
    buy = _pine_crossover(slo, 0.0).astype(int)
    sell = _pine_crossunder(slo, 0.0).astype(int)

    bar_color = pd.Series(np.nan, index=working.index, dtype=float)
    if allow_bar_color_change:
        bar_color = sig.map({2.0: 0.0, 1.0: 1.0, -2.0: 2.0, -1.0: 3.0})

    return working.assign(
        requested_high=h,
        requested_low=l,
        requested_open=o,
        requested_close=c,
        lp_sum=lp_sum,
        hp_sum=hp_sum,
        slo=slo,
        sig=sig,
        Strong_Buy_Signal=strong_buy_signal,
        Strong_Sell_Signal=strong_sell_signal,
        Buy_Signal=buy_signal,
        Sell_Signal=sell_signal,
        All_Buy_Signals=all_buy_signals,
        All_Sell_Signals=all_sell_signals,
        Bar_Color=bar_color,
        Buy=buy,
        Sell=sell,
    )


# -- VALIDATION -------------------------------------------------------------
def validate_against_sample(df: pd.DataFrame, sample_path: str | Path) -> list[str]:
    """Compare all exported output columns against the sample CSV exactly."""
    sample_df = load_csv_data(sample_path)
    messages: list[str] = []
    alias_map = {
        "Strong_Buy_Signal": ("Strong_Buy_Signal",),
        "Strong_Sell_Signal": ("Strong_Sell_Signal",),
        "Buy_Signal": ("Buy_Signal",),
        "Sell_Signal": ("Sell_Signal",),
        "All_Buy_Signals": ("All_Buy_Signals",),
        "All_Sell_Signals": ("All_Sell_Signals",),
        "Bar_Color": ("Bar_Color",),
        "Buy": ("Buy",),
        "Sell": ("Sell",),
    }

    common_index = df.index.intersection(sample_df.index)
    if len(common_index) != len(df):
        messages.append(
            f"Index overlap warning: calculated rows={len(df)}, overlapping sample rows={len(common_index)}."
        )

    for output_column, aliases in alias_map.items():
        sample_column = _find_matching_sample_column(sample_df, aliases)
        if sample_column is None:
            messages.append(f"{output_column}: sample column missing")
            continue

        actual = df.loc[common_index, output_column].astype(float).to_numpy()
        expected = sample_df.loc[common_index, sample_column].astype(float).to_numpy()
        passed = np.isclose(actual, expected, atol=1e-9, rtol=0.0, equal_nan=True)

        if passed.all():
            messages.append(f"{output_column}: PASS")
            continue

        first_idx = int(np.flatnonzero(~passed)[0])
        mismatch_time = common_index[first_idx]
        messages.append(
            f"{output_column}: FAIL at {mismatch_time} actual={actual[first_idx]!r} expected={expected[first_idx]!r}"
        )

    return messages


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """Verify internal consistency for the calculated reversal series."""
    required_columns = (
        "lp_sum",
        "hp_sum",
        "slo",
        "sig",
        "Strong_Buy_Signal",
        "Strong_Sell_Signal",
        "Buy_Signal",
        "Sell_Signal",
        "Buy",
        "Sell",
    )
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires calculated columns: " + ", ".join(missing)
        )

    expected_buy = _pine_crossover(df["slo"], 0.0).astype(int)
    expected_sell = _pine_crossunder(df["slo"], 0.0).astype(int)
    if not expected_buy.equals(df["Buy"].astype(int)):
        raise AssertionError("Buy must equal ta.crossover(slo, 0).")
    if not expected_sell.equals(df["Sell"].astype(int)):
        raise AssertionError("Sell must equal ta.crossunder(slo, 0).")

    expected_strong_buy = _pine_crossover(df["sig"], 1.0).astype(int)
    expected_strong_sell = _pine_crossunder(df["sig"], -1.0).astype(int)
    if not expected_strong_buy.equals(df["Strong_Buy_Signal"].astype(int)):
        raise AssertionError("Strong_Buy_Signal must equal ta.crossover(sig, 1).")
    if not expected_strong_sell.equals(df["Strong_Sell_Signal"].astype(int)):
        raise AssertionError("Strong_Sell_Signal must equal ta.crossunder(sig, -1).")

    if not df["All_Buy_Signals"].astype(int).equals(
        (df["Strong_Buy_Signal"].eq(1) | df["Buy_Signal"].eq(1)).astype(int)
    ):
        raise AssertionError("All_Buy_Signals must be the OR of strong and regular buy signals.")
    if not df["All_Sell_Signals"].astype(int).equals(
        (df["Strong_Sell_Signal"].eq(1) | df["Sell_Signal"].eq(1)).astype(int)
    ):
        raise AssertionError("All_Sell_Signals must be the OR of strong and regular sell signals.")

    print("Internal sanity checks: PASS")


# -- REPORTING --------------------------------------------------------------
def _build_sample_preview(sample_df: pd.DataFrame, rows: int = 8) -> pd.DataFrame:
    """Return a compact preview of the exported CSV structure."""
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "Strong_Buy_Signal",
        "Strong_Sell_Signal",
        "Buy_Signal",
        "Sell_Signal",
        "All_Buy_Signals",
        "All_Sell_Signals",
        "Bar_Color",
        "Buy",
        "Sell",
    ]
    return sample_df.loc[:, preview_columns].head(rows)


def _build_python_preview(df: pd.DataFrame, rows: int = 8) -> pd.DataFrame:
    """Return the first few calculated rows in export-like form."""
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "Strong_Buy_Signal",
        "Strong_Sell_Signal",
        "Buy_Signal",
        "Sell_Signal",
        "All_Buy_Signals",
        "All_Sell_Signals",
        "Bar_Color",
        "Buy",
        "Sell",
    ]
    return df.loc[:, preview_columns].head(rows)


def _build_signal_preview(df: pd.DataFrame, rows: int = 12) -> pd.DataFrame:
    """Return the first few rows where any exported signal fires."""
    mask = (
        df["Strong_Buy_Signal"].eq(1)
        | df["Strong_Sell_Signal"].eq(1)
        | df["Buy"].eq(1)
        | df["Sell"].eq(1)
    )
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "Strong_Buy_Signal",
        "Strong_Sell_Signal",
        "Buy_Signal",
        "Sell_Signal",
        "All_Buy_Signals",
        "All_Sell_Signals",
        "Bar_Color",
        "Buy",
        "Sell",
    ]
    return df.loc[mask, preview_columns].head(rows)


def main(sample_path: str | Path = DEFAULT_SAMPLE_PATH) -> int:
    """Load the sample, calculate the indicator, and print a verification report."""
    sample_df = load_csv_data(sample_path)
    calculated = calculate_indicators(sample_df)
    run_internal_sanity_checks(calculated)
    messages = validate_against_sample(calculated, sample_path)

    print("Indicator:", PINE_INDICATOR_NAME)
    print("Rows:", len(calculated))
    print("\nValidation report:")
    for message in messages:
        print(f"  {message}")

    print("\nSignal counts:")
    for column in (
        "Strong_Buy_Signal",
        "Strong_Sell_Signal",
        "Buy_Signal",
        "Sell_Signal",
        "All_Buy_Signals",
        "All_Sell_Signals",
        "Buy",
        "Sell",
    ):
        print(f"  {column}: {int(calculated[column].sum())}")

    print("\nSample preview:")
    print(_build_sample_preview(sample_df).to_string(index=False))

    print("\nPython result preview:")
    print(_build_python_preview(calculated).to_string(index=False))

    print("\nPython signal preview:")
    print(_build_signal_preview(calculated).to_string(index=False))

    return 0


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    raise SystemExit(main(input_path))
