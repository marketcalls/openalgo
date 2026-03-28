"""
# ============================================================
# INDICATOR: Three Inside [TradingFinder] 3 Inside Up & Down Chart Patterns
# Converted from Pine Script v5 | 2026-03-20
# Original Pine author: TradingFinder
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "Three Inside [TradingFinder] 3 Inside Up & Down Chart Patterns"
DEFAULT_FILTER = "On"
MISSING_VALUE_SENTINEL = 1e100
BOUNDARY_EPSILON = 1e-12
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\Three_Inside_TradingFinder.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

# Observed TradingView export codes for the default "Filter = On" sample.
BULLISH_PLOTSHAPE_COLORER = 0
BEARISH_PLOTSHAPE_COLORER = 2
BULLISH_BARCOLOR_CODE = 4.0
BEARISH_BARCOLOR_CODE = 3.0

EXPORTED_COLUMNS = (
    "3_Insid_Bar_Bullish",
    "3_Insid_Bar_Bullish_colorer",
    "3_Insid_Bar_Bearish",
    "3_Insid_Bar_Bearish_colorer",
    "Bullish_Pin_Bar_Candle_Color",
    "Bearish_Pin_Bar_Candle_Color",
)

VALIDATION_COLUMN_ALIASES = {name: (name,) for name in EXPORTED_COLUMNS}


# -- LOADING ----------------------------------------------------------------
def _normalize_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """Replace TradingView-style sentinel values with NaN."""
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
    """Validate that the input contains the required OHLCV columns."""
    missing = [column for column in REQUIRED_PRICE_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(
            "Input data is missing required OHLCV columns: " + ", ".join(missing)
        )


def _normalize_name(value: str) -> str:
    """Lower-case alphanumeric-only normalization for column matching."""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _find_matching_sample_column(
    sample_df: pd.DataFrame,
    aliases: Iterable[str],
) -> Optional[str]:
    """Resolve the matching sample column for a calculated output."""
    normalized_columns = {_normalize_name(column): column for column in sample_df.columns}
    for alias in aliases:
        alias_key = _normalize_name(alias)
        if alias_key in normalized_columns:
            return normalized_columns[alias_key]
    return None


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    filter_mode: str = DEFAULT_FILTER,
) -> pd.DataFrame:
    """
    Replicate TradingFinder Three Inside signals and exported sample columns.

    The provided sample uses the default `Filter = 'On'`, so the exported
    bullish/bearish plotshape columns contain only strong patterns. The two
    bar-color columns still reflect both weak and strong detections.
    """
    _require_price_columns(df)
    if filter_mode not in {"On", "Off"}:
        raise ValueError("filter_mode must be either 'On' or 'Off'.")

    working = df.copy().sort_index()
    open_ = working["open"].astype(float)
    high = working["high"].astype(float)
    low = working["low"].astype(float)
    close = working["close"].astype(float)

    candle_range = high - low
    candle_body = close - open_
    cod_pos_candle = candle_body > 0
    cod_neg_candle = candle_body < 0

    cod_full_body = pd.Series(
        np.where(candle_range != 0, np.abs(candle_body / candle_range), np.nan),
        index=working.index,
        dtype=float,
    )

    weak_body = (cod_full_body >= (0.6 - BOUNDARY_EPSILON)) & (
        cod_full_body <= (0.8 + BOUNDARY_EPSILON)
    )
    strong_body = cod_full_body > (0.8 + BOUNDARY_EPSILON)

    prev2_mid = (low.shift(2) + high.shift(2)) / 2.0

    inside_bar_bull_w = (
        cod_neg_candle.shift(2, fill_value=False)
        & cod_pos_candle
        & weak_body
        & (close > high.shift(1))
        & (close > prev2_mid)
        & (high.shift(1) < high.shift(2))
        & (low.shift(2) > low.shift(1))
    )

    inside_bar_bull_s = (
        cod_neg_candle.shift(2, fill_value=False)
        & cod_pos_candle
        & strong_body
        & (close > high.shift(1))
        & (close > prev2_mid)
        & (high.shift(1) < high.shift(2))
        & (low.shift(2) > low.shift(1))
    )

    inside_bar_bear_w = (
        cod_neg_candle
        & cod_pos_candle.shift(2, fill_value=False)
        & weak_body
        & (close < low.shift(1))
        & (close < prev2_mid)
        & (high.shift(1) > high.shift(2))
        & (low.shift(2) < low.shift(1))
    )

    inside_bar_bear_s = (
        cod_neg_candle
        & cod_pos_candle.shift(2, fill_value=False)
        & strong_body
        & (close < low.shift(1))
        & (close < prev2_mid)
        & (high.shift(1) > high.shift(2))
        & (low.shift(2) < low.shift(1))
    )

    bullish_signal = (
        inside_bar_bull_s if filter_mode == "On" else (inside_bar_bull_s | inside_bar_bull_w)
    )
    bearish_signal = (
        inside_bar_bear_s if filter_mode == "On" else (inside_bar_bear_s | inside_bar_bear_w)
    )

    bullish_barcolor = inside_bar_bull_s | inside_bar_bull_w
    bearish_barcolor = inside_bar_bear_s | inside_bar_bear_w

    return working.assign(
        candle_range=candle_range,
        candle_body=candle_body,
        cod_pos_candle=cod_pos_candle,
        cod_neg_candle=cod_neg_candle,
        cod_full_body=cod_full_body,
        inside_bar_bull_w=inside_bar_bull_w,
        inside_bar_bull_s=inside_bar_bull_s,
        inside_bar_bear_w=inside_bar_bear_w,
        inside_bar_bear_s=inside_bar_bear_s,
        bullish_signal=bullish_signal,
        bearish_signal=bearish_signal,
        **{
            "3_Insid_Bar_Bullish": bullish_signal.astype(int),
            "3_Insid_Bar_Bullish_colorer": BULLISH_PLOTSHAPE_COLORER,
            "3_Insid_Bar_Bearish": bearish_signal.astype(int),
            "3_Insid_Bar_Bearish_colorer": BEARISH_PLOTSHAPE_COLORER,
            "Bullish_Pin_Bar_Candle_Color": np.where(
                bullish_barcolor, BULLISH_BARCOLOR_CODE, np.nan
            ),
            "Bearish_Pin_Bar_Candle_Color": np.where(
                bearish_barcolor, BEARISH_BARCOLOR_CODE, np.nan
            ),
        },
    )


# -- VALIDATION -------------------------------------------------------------
def _compare_numeric_series(
    actual: pd.Series,
    expected: pd.Series,
    atol: float = 1e-12,
) -> tuple[bool, Optional[pd.Timestamp], float, float, float]:
    """Compare numeric series with NaN support and small floating tolerance."""
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


def validate_against_sample(df: pd.DataFrame, sample_path: str | Path) -> None:
    """Compare all exported TradingFinder Three Inside columns against the sample CSV."""
    sample_df = load_csv_data(sample_path)
    common_index = df.index.intersection(sample_df.index)
    if common_index.empty:
        raise ValueError("No overlapping timestamps found between calculated data and sample file.")

    aligned_df = df.loc[common_index]
    aligned_sample = sample_df.loc[common_index]

    report_rows: list[tuple[str, str]] = []
    failures: list[tuple[str, str]] = []

    for output_name in EXPORTED_COLUMNS:
        sample_column = _find_matching_sample_column(
            aligned_sample,
            VALIDATION_COLUMN_ALIASES[output_name],
        )
        if sample_column is None:
            report_rows.append((output_name, "not available in sample"))
            failures.append((output_name, "missing sample column"))
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
            failures.append(
                (
                    output_name,
                    f"mismatch at {mismatch_idx}: actual={actual_value} expected={expected_value} diff={diff}",
                )
            )

    print("Validation report:")
    for output_name, status in report_rows:
        print(f"  {output_name}: {status}")

    if failures:
        lines = [f"{indicator}: {message}" for indicator, message in failures]
        raise AssertionError("Three Inside validation failed:\n" + "\n".join(lines))

    print("\nPASS: all exported Three Inside columns match the sample within floating tolerance.")


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """Verify internal relationships between strong, weak, and exported signals."""
    required_columns = (
        "inside_bar_bull_w",
        "inside_bar_bull_s",
        "inside_bar_bear_w",
        "inside_bar_bear_s",
        "bullish_signal",
        "bearish_signal",
        "3_Insid_Bar_Bullish",
        "3_Insid_Bar_Bearish",
        "Bullish_Pin_Bar_Candle_Color",
        "Bearish_Pin_Bar_Candle_Color",
    )
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires calculated columns: " + ", ".join(missing)
        )

    if not df["bullish_signal"].equals(df["inside_bar_bull_s"]):
        raise AssertionError("With default Filter='On', bullish_signal must equal inside_bar_bull_s.")

    if not df["bearish_signal"].equals(df["inside_bar_bear_s"]):
        raise AssertionError("With default Filter='On', bearish_signal must equal inside_bar_bear_s.")

    bullish_bar_mask = df["Bullish_Pin_Bar_Candle_Color"].eq(BULLISH_BARCOLOR_CODE)
    bearish_bar_mask = df["Bearish_Pin_Bar_Candle_Color"].eq(BEARISH_BARCOLOR_CODE)

    if not bullish_bar_mask.equals(df["inside_bar_bull_w"] | df["inside_bar_bull_s"]):
        raise AssertionError("Bullish bar-color column must reflect weak OR strong bullish patterns.")

    if not bearish_bar_mask.equals(df["inside_bar_bear_w"] | df["inside_bar_bear_s"]):
        raise AssertionError("Bearish bar-color column must reflect weak OR strong bearish patterns.")

    overlap_count = int((bullish_bar_mask & bearish_bar_mask).sum())
    print(f"Internal sanity checks: PASS (bull/bear barcolor overlap bars={overlap_count})")


# -- REPORTING --------------------------------------------------------------
def _build_preview(df: pd.DataFrame, rows: int = 8) -> pd.DataFrame:
    """Return a compact preview of exported signal columns."""
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "3_Insid_Bar_Bullish",
        "3_Insid_Bar_Bearish",
        "Bullish_Pin_Bar_Candle_Color",
        "Bearish_Pin_Bar_Candle_Color",
    ]
    return df.loc[:, preview_columns].head(rows)


def _build_signal_preview(df: pd.DataFrame, rows: int = 15) -> pd.DataFrame:
    """Return the first few rows where any pattern is detected."""
    mask = (
        df["inside_bar_bull_w"]
        | df["inside_bar_bull_s"]
        | df["inside_bar_bear_w"]
        | df["inside_bar_bear_s"]
    )
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "inside_bar_bull_w",
        "inside_bar_bull_s",
        "inside_bar_bear_w",
        "inside_bar_bear_s",
        "3_Insid_Bar_Bullish",
        "3_Insid_Bar_Bearish",
    ]
    return df.loc[mask, preview_columns].head(rows)


def main(sample_path: str | Path = DEFAULT_SAMPLE_PATH) -> int:
    """Load the sample, calculate the indicator, validate parity, and print previews."""
    df = load_csv_data(sample_path)
    calculated = calculate_indicators(df)
    run_internal_sanity_checks(calculated)
    validate_against_sample(calculated, sample_path)

    print("\nPattern counts:")
    print(f"  inside_bar_bull_w: {int(calculated['inside_bar_bull_w'].sum())}")
    print(f"  inside_bar_bull_s: {int(calculated['inside_bar_bull_s'].sum())}")
    print(f"  inside_bar_bear_w: {int(calculated['inside_bar_bear_w'].sum())}")
    print(f"  inside_bar_bear_s: {int(calculated['inside_bar_bear_s'].sum())}")
    print(f"  bullish signal (exported): {int(calculated['3_Insid_Bar_Bullish'].sum())}")
    print(f"  bearish signal (exported): {int(calculated['3_Insid_Bar_Bearish'].sum())}")

    print("\nExport preview:")
    print(_build_preview(calculated).to_string(index=False))

    print("\nSignal preview:")
    print(_build_signal_preview(calculated).to_string(index=False))
    return 0


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    raise SystemExit(main(input_path))
