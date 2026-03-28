"""
# ============================================================
# INDICATOR: Trend Signals with TP & SL [UAlgo]
# Converted from Pine Script v5 | 2026-03-21
# Original Pine author: UAlgo
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_INDICATOR_NAME = "Trend Signals with TP & SL [UAlgo]"
DEFAULT_MULTIPLIER = 2.0
DEFAULT_ATR_PERIOD = 14
DEFAULT_ATR_METHOD = "Method 1"
DEFAULT_CLOUD_VAL = 10
DEFAULT_STOP_LOSS_PCT = 2.0
DEFAULT_SHOW_BUY_SELL = True
DEFAULT_SHOW_CLOUD = True
MISSING_VALUE_SENTINEL = 1e100
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\Trend_Signals_TP_SL_UAlgo.csv")
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

# Observed TradingView export codes for the sample's fill color channels.
POSITIVE_CLOUD_COLOR_CODE = 5.0
NEGATIVE_CLOUD_COLOR_CODE = 6.0

EXPORTED_COLUMNS = (
    "Plot",
    "Plot_colorer",
    "Plot_2",
    "Plot_2_colorer",
    "UpTrend_Begins",
    "Buy",
    "DownTrend_Begins",
    "Sell",
    "fill_0_colorer",
    "fill_1_colorer",
    "fill_2_colorer",
    "fill_3_colorer",
    "plot_12",
    "Trend_Direction_Change_",
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
def _pine_sma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style SMA."""
    return series.rolling(window=length, min_periods=length).mean()


def _pine_ema(series: pd.Series, length: int) -> pd.Series:
    """Pine-style EMA seeded with an initial SMA."""
    out = pd.Series(np.nan, index=series.index, dtype=float)
    if len(series) < length:
        return out
    out.iloc[length - 1] = series.iloc[:length].mean()
    alpha = 2.0 / (length + 1.0)
    for i in range(length, len(series)):
        out.iloc[i] = alpha * series.iloc[i] + (1.0 - alpha) * out.iloc[i - 1]
    return out


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


def _pine_wma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style WMA."""
    weights = np.arange(1, length + 1, dtype=float)
    weight_sum = weights.sum()
    return series.rolling(window=length, min_periods=length).apply(
        lambda x: float(np.dot(x, weights) / weight_sum),
        raw=True,
    )


def _pine_hma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style HMA."""
    half_length = max(1, length // 2)
    sqrt_length = max(1, int(np.sqrt(length)))
    return _pine_wma(
        2.0 * _pine_wma(series, half_length) - _pine_wma(series, length),
        sqrt_length,
    )


def _pine_rsi(source: pd.Series, length: int) -> pd.Series:
    """Pine-style RSI using Wilder RMA internals."""
    delta = source.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = _pine_rma(gain, length)
    avg_loss = _pine_rma(loss, length)
    rs = avg_gain / avg_loss
    out = 100.0 - (100.0 / (1.0 + rs))
    out[(avg_loss == 0) & avg_gain.notna()] = 100.0
    out[(avg_gain == 0) & avg_loss.notna()] = 0.0
    return out


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Pine-style true range."""
    prev_close = close.shift(1)
    return pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)


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
    multiplier: float = DEFAULT_MULTIPLIER,
    atr_period: int = DEFAULT_ATR_PERIOD,
    atr_calc_method: str = DEFAULT_ATR_METHOD,
    cloud_val: int = DEFAULT_CLOUD_VAL,
    stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
    show_buy_sell_signals: bool = DEFAULT_SHOW_BUY_SELL,
    show_moving_average_cloud: bool = DEFAULT_SHOW_CLOUD,
) -> pd.DataFrame:
    """
    Replicate the exported Trend Signals with TP & SL [UAlgo] columns exactly.

    The provided sample exports the cloud EMA plots, buy/sell markers, cloud fill
    color channels, the hidden ohlc4 circles plot, and the trend-change alert
    condition. The TP/SL lines and labels are visual-only and not exported.
    """
    _require_price_columns(df)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("calculate_indicators expects a DataFrame indexed by timestamps.")
    if atr_calc_method not in {"Method 1", "Method 2"}:
        raise ValueError("atr_calc_method must be either 'Method 1' or 'Method 2'.")

    working = df.copy().sort_index()
    open_ = working["open"].astype(float)
    high = working["high"].astype(float)
    low = working["low"].astype(float)
    close = working["close"].astype(float)
    volume = working["volume"].astype(float)

    src = (high + low) / 2.0
    ohlc4 = (open_ + high + low + close) / 4.0

    # Auxiliary calculations present in the Pine source. These do not affect the
    # exported sample columns, but keeping them available helps with inspection.
    src1 = _pine_hma(open_, 5).shift(1)
    src2 = _pine_hma(close, 12)
    momm1 = src1.diff()
    momm2 = src2.diff()
    m1 = np.where(momm1 >= momm2, momm1, 0.0)
    m2 = np.where(momm1 >= momm2, 0.0, -momm1)
    sm1 = pd.Series(m1, index=working.index, dtype=float)
    sm2 = pd.Series(m2, index=working.index, dtype=float)
    cmo_calc = 100.0 * (sm1 - sm2) / (sm1 + sm2)
    rsi_calc = _pine_rsi(close, 9)

    tr = _true_range(high, low, close)
    atr_alt = _pine_sma(tr, atr_period)
    atr = _pine_rma(tr, atr_period) if atr_calc_method == "Method 1" else atr_alt

    up_raw = src - (multiplier * atr)
    dn_raw = src + (multiplier * atr)

    up = pd.Series(np.nan, index=working.index, dtype=float)
    dn = pd.Series(np.nan, index=working.index, dtype=float)
    trend = pd.Series(np.nan, index=working.index, dtype=float)
    buy_signal = pd.Series(False, index=working.index, dtype=bool)
    sell_signal = pd.Series(False, index=working.index, dtype=bool)
    pos = pd.Series(np.nan, index=working.index, dtype=float)
    long_cond = pd.Series(False, index=working.index, dtype=bool)
    short_cond = pd.Series(False, index=working.index, dtype=bool)
    entry_long = pd.Series(np.nan, index=working.index, dtype=float)
    entry_short = pd.Series(np.nan, index=working.index, dtype=float)

    for i in range(len(working)):
        current_up = up_raw.iloc[i]
        current_dn = dn_raw.iloc[i]
        up1 = up.iloc[i - 1] if i > 0 and not np.isnan(up.iloc[i - 1]) else current_up
        dn1 = dn.iloc[i - 1] if i > 0 and not np.isnan(dn.iloc[i - 1]) else current_dn

        up.iloc[i] = (
            max(current_up, up1)
            if i > 0 and close.iloc[i - 1] > up1
            else current_up
        )
        dn.iloc[i] = (
            min(current_dn, dn1)
            if i > 0 and close.iloc[i - 1] < dn1
            else current_dn
        )

        previous_trend = trend.iloc[i - 1] if i > 0 and not np.isnan(trend.iloc[i - 1]) else 1.0
        previous_trend_series = trend.iloc[i - 1] if i > 0 else np.nan

        trend.iloc[i] = (
            1.0
            if previous_trend == -1 and close.iloc[i] > dn1
            else -1.0
            if previous_trend == 1 and close.iloc[i] < up1
            else previous_trend
        )

        buy_signal.iloc[i] = bool(trend.iloc[i] == 1 and previous_trend_series == -1)
        sell_signal.iloc[i] = bool(trend.iloc[i] == -1 and previous_trend_series == 1)

        previous_pos = pos.iloc[i - 1] if i > 0 else np.nan
        long_cond.iloc[i] = bool(
            buy_signal.iloc[i] and not np.isnan(previous_pos) and previous_pos != 1
        )
        short_cond.iloc[i] = bool(
            sell_signal.iloc[i] and not np.isnan(previous_pos) and previous_pos != -1
        )

        current_pos = 1.0 if buy_signal.iloc[i] else -1.0 if sell_signal.iloc[i] else previous_pos

        long_entries = np.flatnonzero(long_cond.iloc[: i + 1].to_numpy())
        short_entries = np.flatnonzero(short_cond.iloc[: i + 1].to_numpy())

        entry_long.iloc[i] = close.iloc[long_entries[-1]] if len(long_entries) else np.nan
        entry_short.iloc[i] = close.iloc[short_entries[-1]] if len(short_entries) else np.nan

        sl_fraction = stop_loss_pct / 100.0 if stop_loss_pct > 0 else 99999.0
        stop_loss_long = entry_long.iloc[i] * (1.0 - sl_fraction) if not np.isnan(entry_long.iloc[i]) else np.nan
        stop_loss_short = entry_short.iloc[i] * (1.0 + sl_fraction) if not np.isnan(entry_short.iloc[i]) else np.nan
        take_profit_long_3r = entry_long.iloc[i] * (1.0 + sl_fraction * 3.0) if not np.isnan(entry_long.iloc[i]) else np.nan
        take_profit_short_3r = entry_short.iloc[i] * (1.0 - sl_fraction * 3.0) if not np.isnan(entry_short.iloc[i]) else np.nan

        long_sl = bool(
            not np.isnan(stop_loss_long)
            and not np.isnan(previous_pos)
            and previous_pos == 1
            and low.iloc[i] < stop_loss_long
        )
        short_sl = bool(
            not np.isnan(stop_loss_short)
            and not np.isnan(previous_pos)
            and previous_pos == -1
            and high.iloc[i] > stop_loss_short
        )
        take_profit_long_final = bool(
            not np.isnan(take_profit_long_3r)
            and not np.isnan(previous_pos)
            and previous_pos == 1
            and high.iloc[i] > take_profit_long_3r
        )
        take_profit_short_final = bool(
            not np.isnan(take_profit_short_3r)
            and not np.isnan(previous_pos)
            and previous_pos == -1
            and low.iloc[i] < take_profit_short_3r
        )

        if long_sl or short_sl or take_profit_long_final or take_profit_short_final:
            current_pos = 0.0

        pos.iloc[i] = current_pos

    sma_src_high = _pine_ema(high, cloud_val)
    sma_src_low = _pine_ema(low, cloud_val)
    macd_line = _pine_ema(close, 12) - _pine_ema(close, 26)
    macd_prev = macd_line.shift(1)

    fill_0_mask = (macd_line > 0) & (macd_line > macd_prev)
    fill_1_mask = (macd_line > 0) & (macd_line < macd_prev)
    fill_2_mask = (macd_line < 0) & (macd_line < macd_prev)
    fill_3_mask = (macd_line < 0) & (macd_line > macd_prev)

    change_cond = (trend != trend.shift(1)).fillna(False)
    if len(change_cond) > 0:
        change_cond.iloc[0] = False

    plot = sma_src_high if show_moving_average_cloud else pd.Series(np.nan, index=working.index, dtype=float)
    plot_2 = sma_src_low if show_moving_average_cloud else pd.Series(np.nan, index=working.index, dtype=float)

    uptrend_begins = up.where(long_cond)
    buy = up.where(long_cond) if show_buy_sell_signals else pd.Series(np.nan, index=working.index, dtype=float)
    downtrend_begins = dn.where(short_cond)
    sell = dn.where(short_cond) if show_buy_sell_signals else pd.Series(np.nan, index=working.index, dtype=float)

    return working.assign(
        src=src,
        ohlc4=ohlc4,
        src1=src1,
        src2=src2,
        cmo_calc=cmo_calc,
        rsi_calc=rsi_calc,
        atr=atr,
        up=up,
        dn=dn,
        trend=trend,
        buy_signal=buy_signal,
        sell_signal=sell_signal,
        pos=pos,
        long_cond=long_cond,
        short_cond=short_cond,
        entry_of_long_position=entry_long,
        entry_of_short_position=entry_short,
        Plot=plot,
        Plot_colorer=np.nan,
        Plot_2=plot_2,
        Plot_2_colorer=np.nan,
        UpTrend_Begins=uptrend_begins,
        Buy=buy,
        DownTrend_Begins=downtrend_begins,
        Sell=sell,
        fill_0_colorer=np.where(fill_0_mask, POSITIVE_CLOUD_COLOR_CODE, np.nan),
        fill_1_colorer=np.where(fill_1_mask, POSITIVE_CLOUD_COLOR_CODE, np.nan),
        fill_2_colorer=np.where(fill_2_mask, NEGATIVE_CLOUD_COLOR_CODE, np.nan),
        fill_3_colorer=np.where(fill_3_mask, NEGATIVE_CLOUD_COLOR_CODE, np.nan),
        plot_12=ohlc4,
        Trend_Direction_Change_=change_cond.astype(int),
    )


# -- VALIDATION -------------------------------------------------------------
def validate_against_sample(df: pd.DataFrame, sample_path: str | Path) -> None:
    """Compare exported UAlgo columns against the sample CSV."""
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
        raise AssertionError("Trend Signals validation failed:\n" + "\n".join(lines))

    print("\nPASS: all exported UAlgo columns match the sample within floating tolerance.")


def run_internal_sanity_checks(df: pd.DataFrame) -> None:
    """Verify internal consistency for the key exported and derived series."""
    required_columns = (
        "Plot",
        "Plot_2",
        "Buy",
        "Sell",
        "UpTrend_Begins",
        "DownTrend_Begins",
        "long_cond",
        "short_cond",
        "plot_12",
        "Trend_Direction_Change_",
        "ohlc4",
    )
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        raise ValueError(
            "run_internal_sanity_checks requires calculated columns: " + ", ".join(missing)
        )

    if not np.isclose(
        df["plot_12"].to_numpy(dtype=float),
        df["ohlc4"].to_numpy(dtype=float),
        atol=1e-9,
        rtol=0.0,
        equal_nan=True,
    ).all():
        raise AssertionError("plot_12 must equal ohlc4 exactly.")

    if not np.isclose(
        df["Buy"].to_numpy(dtype=float),
        df["UpTrend_Begins"].to_numpy(dtype=float),
        atol=1e-9,
        rtol=0.0,
        equal_nan=True,
    ).all():
        raise AssertionError("Buy must match UpTrend_Begins when showBuySellSignals is enabled.")

    if not np.isclose(
        df["Sell"].to_numpy(dtype=float),
        df["DownTrend_Begins"].to_numpy(dtype=float),
        atol=1e-9,
        rtol=0.0,
        equal_nan=True,
    ).all():
        raise AssertionError("Sell must match DownTrend_Begins when showBuySellSignals is enabled.")

    trend_change_count = int(df["Trend_Direction_Change_"].sum())
    print(f"Internal sanity checks: PASS (trend_change_count={trend_change_count})")


# -- REPORTING --------------------------------------------------------------
def _build_export_preview(df: pd.DataFrame, rows: int = 8) -> pd.DataFrame:
    """Return a compact preview of the exported columns."""
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "Plot",
        "Plot_2",
        "UpTrend_Begins",
        "DownTrend_Begins",
        "plot_12",
        "Trend_Direction_Change_",
    ]
    return df.loc[:, preview_columns].head(rows)


def _build_signal_preview(df: pd.DataFrame, rows: int = 15) -> pd.DataFrame:
    """Return the first few buy/sell signal rows."""
    mask = df["long_cond"] | df["short_cond"]
    preview_columns = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "UpTrend_Begins",
        "DownTrend_Begins",
        "Buy",
        "Sell",
        "Trend_Direction_Change_",
    ]
    return df.loc[mask, preview_columns].head(rows)


def main(sample_path: str | Path = DEFAULT_SAMPLE_PATH) -> int:
    """Load the sample, calculate the indicator, validate parity, and print previews."""
    df = load_csv_data(sample_path)
    calculated = calculate_indicators(df)
    run_internal_sanity_checks(calculated)
    validate_against_sample(calculated, sample_path)

    print("\nSignal counts:")
    print(f"  UpTrend_Begins: {int(calculated['UpTrend_Begins'].notna().sum())}")
    print(f"  DownTrend_Begins: {int(calculated['DownTrend_Begins'].notna().sum())}")
    print(f"  Buy: {int(calculated['Buy'].notna().sum())}")
    print(f"  Sell: {int(calculated['Sell'].notna().sum())}")
    print(f"  Trend_Direction_Change_: {int(calculated['Trend_Direction_Change_'].sum())}")

    print("\nExport preview:")
    print(_build_export_preview(calculated).to_string(index=False))

    print("\nSignal preview:")
    print(_build_signal_preview(calculated).to_string(index=False))
    return 0


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    raise SystemExit(main(input_path))
