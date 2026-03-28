"""
# ============================================================
# STRATEGY: Impulse Trend Levels [BOSWaves]
# Converted from Pine Script v6 | 2026-03-21
# Original Pine author: BOSWaves
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import math
import sys
from typing import Iterable, Optional

import numpy as np
import pandas as pd


# -- PARAMETERS -------------------------------------------------------------
PINE_STRATEGY_NAME = "Impulse Trend Levels [BOSWaves]"
PINE_VERSION = "v6"
PINE_AUTHOR = "BOSWaves"

# Pine input defaults.
DEFAULT_LEN = 19  # len
DEFAULT_IMPULSE_LEN = 5  # impulseLen
DEFAULT_DECAY_RATE = 0.99  # decayRate
DEFAULT_MAD_LEN = 20  # madLen
DEFAULT_BAND_MIN = 1.5  # bandMin
DEFAULT_BAND_MAX = 1.9  # bandMax
DEFAULT_SHOW_BANDS = True  # showBands (unused by source logic)
DEFAULT_SHOW_CLOUD = True  # showCloud
DEFAULT_PAINT_BARS = True  # paintBars
DEFAULT_SHOW_SIGNALS = True  # showSignals (visual only)
DEFAULT_RT_W = 6  # rtW (visual only)
DEFAULT_SIGNAL_BUFFER = 10  # signalBuffer

# Derived strategy defaults because the source is an indicator, not a strategy.
DEFAULT_INITIAL_CAPITAL = 100_000.0
DEFAULT_COMMISSION_PCT = 0.0
DEFAULT_SLIPPAGE_TICKS = 0
DEFAULT_TICK_SIZE = 0.01
DEFAULT_PYRAMIDING = 0

# Export / validation settings.
DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\Impulse_Trend_BOSWaves.csv")
MISSING_VALUE_SENTINEL = 1e100
REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
LOGIC_COMPARE_ATOL = 1e-9

# Observed TradingView export codes from the default sample.
BULL_COLOR_CODE = 11.0
BEAR_COLOR_CODE = 12.0
BULL_INNER_COLOR_CODE = 1291845643.0
BEAR_INNER_COLOR_CODE = 1291845644.0
BULL_FILL_COLOR_CODE = 3003121675.0
BEAR_FILL_COLOR_CODE = 855638028.0
BULL_PLOT14_COLOR_CODE = 855638027.0
BEAR_PLOT14_COLOR_CODE = 3003121676.0

LOGIC_COLUMNS = (
    "Band_Outer",
    "Band_Inner",
    "Bull_Retest",
    "Bear_Retest",
    "Impulse_Long",
    "Impulse_Short",
    "Impulse_Retest",
    "Impulse_Fading",
)

STRUCTURAL_COLUMNS = (
    "plotcandle_0_ohlc_open",
    "plotcandle_0_ohlc_high",
    "plotcandle_0_ohlc_low",
    "plotcandle_0_ohlc_close",
    "plotcandle_0_ohlc_colorer",
    "plotcandle_0_wick_colorer",
    "plotcandle_0_border_colorer",
    "Band_Outer_colorer",
    "Band_Inner_colorer",
    "fill_0_data",
    "plot_12",
    "fill_0_colorer",
    "plot_14",
    "Bull_Retest_colorer",
    "Bear_Retest_colorer",
)

VALIDATION_COLUMN_ALIASES = {name: (name,) for name in (*LOGIC_COLUMNS, *STRUCTURAL_COLUMNS)}


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
    """Validate that the input contains the required OHLCV columns."""
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
    """Resolve the matching sample column for a calculated output."""
    normalized_columns = {_normalize_name(column): column for column in sample_df.columns}
    for alias in aliases:
        alias_key = _normalize_name(alias)
        if alias_key in normalized_columns:
            return normalized_columns[alias_key]
    return None


# -- CORE HELPERS -----------------------------------------------------------
def _pine_sma(series: pd.Series, length: int) -> pd.Series:
    """Pine-style SMA with full-length warmup."""
    return series.rolling(window=length, min_periods=length).mean()


def _pine_ema(series: pd.Series, length: int) -> pd.Series:
    """Pine-style EMA seeded with an initial SMA."""
    out = pd.Series(np.nan, index=series.index, dtype=float)
    if length <= 0:
        raise ValueError("EMA length must be positive.")
    if len(series) < length:
        return out

    out.iloc[length - 1] = series.iloc[:length].mean()
    alpha = 2.0 / (length + 1.0)
    for i in range(length, len(series)):
        out.iloc[i] = alpha * series.iloc[i] + (1.0 - alpha) * out.iloc[i - 1]
    return out


def _crossover(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pine-style crossover using current and previous bar values."""
    out = np.zeros(len(a), dtype=bool)
    for i in range(1, len(a)):
        if (
            np.isnan(a[i])
            or np.isnan(b[i])
            or np.isnan(a[i - 1])
            or np.isnan(b[i - 1])
        ):
            continue
        out[i] = (a[i] > b[i]) and (a[i - 1] <= b[i - 1])
    return out


def _crossunder(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pine-style crossunder using current and previous bar values."""
    out = np.zeros(len(a), dtype=bool)
    for i in range(1, len(a)):
        if (
            np.isnan(a[i])
            or np.isnan(b[i])
            or np.isnan(a[i - 1])
            or np.isnan(b[i - 1])
        ):
            continue
        out[i] = (a[i] < b[i]) and (a[i - 1] >= b[i - 1])
    return out


def _compare_numeric_series(
    actual: pd.Series,
    expected: pd.Series,
    atol: float = LOGIC_COMPARE_ATOL,
) -> tuple[bool, Optional[pd.Timestamp], float, float, float]:
    """Compare numeric series with NaN support and absolute tolerance."""
    actual_values = actual.astype(float).to_numpy()
    expected_values = expected.astype(float).to_numpy()
    comparison = np.isclose(
        actual_values,
        expected_values,
        atol=atol,
        rtol=0.0,
        equal_nan=True,
    )
    if comparison.all():
        return True, None, np.nan, np.nan, 0.0

    mismatch_pos = int(np.flatnonzero(~comparison)[0])
    mismatch_idx = actual.index[mismatch_pos]
    actual_value = actual_values[mismatch_pos]
    expected_value = expected_values[mismatch_pos]
    diff = np.nan if np.isnan(actual_value) or np.isnan(expected_value) else abs(actual_value - expected_value)
    return False, mismatch_idx, actual_value, expected_value, diff


def _max_abs_error(actual: pd.Series, expected: pd.Series) -> float:
    """Return the maximum absolute difference while treating paired NaNs as equal."""
    actual_values = actual.astype(float).to_numpy()
    expected_values = expected.astype(float).to_numpy()
    diffs = np.abs(actual_values - expected_values)
    both_nan = np.isnan(actual_values) & np.isnan(expected_values)
    diffs[both_nan] = 0.0
    diffs[np.isnan(diffs)] = np.inf
    return float(np.max(diffs)) if len(diffs) else 0.0


def _bars_per_year(index: pd.DatetimeIndex) -> float:
    """Estimate annual bars from the median bar spacing."""
    if len(index) < 2:
        return 0.0
    deltas = index.to_series().diff().dropna()
    if deltas.empty:
        return 0.0
    median_delta = deltas.median()
    if pd.isna(median_delta) or median_delta <= pd.Timedelta(0):
        return 0.0
    return float(pd.Timedelta(days=365) / median_delta)


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    len_: int = DEFAULT_LEN,
    impulse_len: int = DEFAULT_IMPULSE_LEN,
    decay_rate: float = DEFAULT_DECAY_RATE,
    mad_len: int = DEFAULT_MAD_LEN,
    band_min: float = DEFAULT_BAND_MIN,
    band_max: float = DEFAULT_BAND_MAX,
    show_bands: bool = DEFAULT_SHOW_BANDS,
    show_cloud: bool = DEFAULT_SHOW_CLOUD,
    paint_bars: bool = DEFAULT_PAINT_BARS,
    show_signals: bool = DEFAULT_SHOW_SIGNALS,
    rt_w: int = DEFAULT_RT_W,
    signal_buffer: int = DEFAULT_SIGNAL_BUFFER,
) -> pd.DataFrame:
    """
    Replicate the BOSWaves Impulse Trend indicator and exported sample columns.

    This port keeps the Pine stateful semantics intact:
    - `impulse` and `impulseDir` persist bar-to-bar.
    - `lastSignal` persists until replaced by a new crossover/crossunder.
    - retest dots enforce both the post-signal buffer and the 55-bar cooldown.
    """
    del show_bands, show_signals, rt_w  # Unused by the executable core.

    _require_price_columns(df)

    working = df.copy().sort_index()
    open_ = working["open"].astype(float)
    high = working["high"].astype(float)
    low = working["low"].astype(float)
    close = working["close"].astype(float)

    basis_o = _pine_ema(open_, len_)
    basis_c = _pine_ema(close, len_)
    basis = basis_c

    mean = _pine_sma(close, mad_len)
    mad = _pine_sma((close - mean).abs(), mad_len)

    raw_impulse = pd.Series(
        np.where(
            mad.gt(0).fillna(False).to_numpy(),
            ((close - close.shift(impulse_len)) / mad).to_numpy(),
            0.0,
        ),
        index=working.index,
        dtype=float,
    )

    n = len(working)
    impulse_arr = np.zeros(n, dtype=float)
    impulse_dir_arr = np.zeros(n, dtype=int)
    freshness_arr = np.zeros(n, dtype=float)
    band_mult_arr = np.full(n, np.nan, dtype=float)
    upper_arr = np.full(n, np.nan, dtype=float)
    lower_arr = np.full(n, np.nan, dtype=float)

    impulse_value = 0.0
    impulse_dir = 0

    basis_values = basis.to_numpy(dtype=float)
    mad_values = mad.to_numpy(dtype=float)
    raw_impulse_values = raw_impulse.to_numpy(dtype=float)

    for i in range(n):
        abs_raw = abs(raw_impulse_values[i])
        if abs_raw > 1.0:
            impulse_value = abs_raw
            impulse_dir = 1 if raw_impulse_values[i] > 0 else -1
        else:
            impulse_value *= decay_rate

        freshness = min(impulse_value / 2.0, 1.0)
        band_mult = band_max - (band_max - band_min) * freshness

        impulse_arr[i] = impulse_value
        impulse_dir_arr[i] = impulse_dir
        freshness_arr[i] = freshness
        band_mult_arr[i] = band_mult

        if not np.isnan(basis_values[i]) and not np.isnan(mad_values[i]):
            upper_arr[i] = basis_values[i] + mad_values[i] * band_mult
            lower_arr[i] = basis_values[i] - mad_values[i] * band_mult

    long_cond_arr = _crossover(close.to_numpy(dtype=float), upper_arr)
    short_cond_arr = _crossunder(close.to_numpy(dtype=float), lower_arr)

    prev_signal_arr = np.zeros(n, dtype=int)
    last_signal_arr = np.zeros(n, dtype=int)
    switch_up_arr = np.zeros(n, dtype=bool)
    switch_down_arr = np.zeros(n, dtype=bool)
    band_outer_arr = np.full(n, np.nan, dtype=float)
    band_inner_arr = np.full(n, np.nan, dtype=float)
    trend_color_code_arr = np.full(n, BEAR_COLOR_CODE, dtype=float)
    inner_color_code_arr = np.full(n, BEAR_INNER_COLOR_CODE, dtype=float)
    fill_color_code_arr = np.full(n, BEAR_FILL_COLOR_CODE, dtype=float)
    plot14_color_code_arr = np.full(n, BEAR_PLOT14_COLOR_CODE, dtype=float)
    bull_retest_price_arr = np.full(n, np.nan, dtype=float)
    bear_retest_price_arr = np.full(n, np.nan, dtype=float)
    bull_retest_ok_arr = np.zeros(n, dtype=bool)
    bear_retest_ok_arr = np.zeros(n, dtype=bool)
    impulse_retest_arr = np.zeros(n, dtype=bool)
    last_signal_bar_arr = np.zeros(n, dtype=int)

    last_signal = 0
    last_signal_bar = 0
    last_bull_dot: Optional[int] = None
    last_bear_dot: Optional[int] = None

    high_values = high.to_numpy(dtype=float)
    low_values = low.to_numpy(dtype=float)
    mad_thickness_arr = mad_values * 0.5

    for i in range(n):
        prev_signal = last_signal
        if long_cond_arr[i]:
            last_signal = 1
        elif short_cond_arr[i]:
            last_signal = -1

        switch_up = (last_signal == 1) and (prev_signal == -1)
        switch_down = (last_signal == -1) and (prev_signal == 1)

        if last_signal == 1:
            trend_color_code_arr[i] = BULL_COLOR_CODE
            inner_color_code_arr[i] = BULL_INNER_COLOR_CODE
            fill_color_code_arr[i] = BULL_FILL_COLOR_CODE
            plot14_color_code_arr[i] = BULL_PLOT14_COLOR_CODE
        else:
            trend_color_code_arr[i] = BEAR_COLOR_CODE
            inner_color_code_arr[i] = BEAR_INNER_COLOR_CODE
            fill_color_code_arr[i] = BEAR_FILL_COLOR_CODE
            plot14_color_code_arr[i] = BEAR_PLOT14_COLOR_CODE

        if last_signal == 1:
            band_outer_arr[i] = lower_arr[i]
            band_inner_arr[i] = (
                lower_arr[i] + mad_thickness_arr[i]
                if not np.isnan(lower_arr[i]) and not np.isnan(mad_thickness_arr[i])
                else np.nan
            )
        else:
            band_outer_arr[i] = upper_arr[i]
            band_inner_arr[i] = (
                upper_arr[i] - mad_thickness_arr[i]
                if not np.isnan(upper_arr[i]) and not np.isnan(mad_thickness_arr[i])
                else np.nan
            )

        if switch_up or switch_down:
            last_signal_bar = i

        far_enough_from_signal = (i - last_signal_bar) >= signal_buffer
        bull_retest = (
            last_signal == 1
            and not np.isnan(band_inner_arr[i])
            and low_values[i] < band_inner_arr[i]
            and far_enough_from_signal
        )
        bear_retest = (
            last_signal == -1
            and not np.isnan(band_inner_arr[i])
            and high_values[i] > band_inner_arr[i]
            and far_enough_from_signal
        )

        bull_dot_ok = bull_retest and (
            last_bull_dot is None or (i - last_bull_dot) >= 55
        )
        bear_dot_ok = bear_retest and (
            last_bear_dot is None or (i - last_bear_dot) >= 55
        )

        if bull_dot_ok:
            last_bull_dot = i
            bull_retest_price_arr[i] = low_values[i]
        if bear_dot_ok:
            last_bear_dot = i
            bear_retest_price_arr[i] = high_values[i]

        prev_signal_arr[i] = prev_signal
        last_signal_arr[i] = last_signal
        switch_up_arr[i] = switch_up
        switch_down_arr[i] = switch_down
        bull_retest_ok_arr[i] = bull_dot_ok
        bear_retest_ok_arr[i] = bear_dot_ok
        impulse_retest_arr[i] = bull_dot_ok or bear_dot_ok
        last_signal_bar_arr[i] = last_signal_bar

    freshness_series = pd.Series(freshness_arr, index=working.index, dtype=float)
    impulse_fading = (freshness_series.shift(1) > 0.5) & (freshness_series <= 0.5)

    band_outer_series = pd.Series(
        band_outer_arr if show_cloud else np.full(n, np.nan, dtype=float),
        index=working.index,
        dtype=float,
    )
    band_inner_series = pd.Series(
        band_inner_arr if show_cloud else np.full(n, np.nan, dtype=float),
        index=working.index,
        dtype=float,
    )

    return working.assign(
        basisO=basis_o,
        basisC=basis_c,
        basis=basis,
        mean=mean,
        mad=mad,
        rawImpulse=raw_impulse,
        impulse=pd.Series(impulse_arr, index=working.index, dtype=float),
        impulseDir=pd.Series(impulse_dir_arr, index=working.index, dtype=int),
        freshness=freshness_series,
        bandMult=pd.Series(band_mult_arr, index=working.index, dtype=float),
        upper=pd.Series(upper_arr, index=working.index, dtype=float),
        lower=pd.Series(lower_arr, index=working.index, dtype=float),
        longCond=pd.Series(long_cond_arr, index=working.index, dtype=bool),
        shortCond=pd.Series(short_cond_arr, index=working.index, dtype=bool),
        prevSignal=pd.Series(prev_signal_arr, index=working.index, dtype=int),
        lastSignal=pd.Series(last_signal_arr, index=working.index, dtype=int),
        switchUp=pd.Series(switch_up_arr, index=working.index, dtype=bool),
        switchDown=pd.Series(switch_down_arr, index=working.index, dtype=bool),
        lastSignalBar=pd.Series(last_signal_bar_arr, index=working.index, dtype=int),
        bullDotOk=pd.Series(bull_retest_ok_arr, index=working.index, dtype=bool),
        bearDotOk=pd.Series(bear_retest_ok_arr, index=working.index, dtype=bool),
        Band_Outer=band_outer_series,
        Band_Inner=band_inner_series,
        Bull_Retest=pd.Series(bull_retest_price_arr, index=working.index, dtype=float),
        Bear_Retest=pd.Series(bear_retest_price_arr, index=working.index, dtype=float),
        Impulse_Long=pd.Series(switch_up_arr, index=working.index, dtype=int),
        Impulse_Short=pd.Series(switch_down_arr, index=working.index, dtype=int),
        Impulse_Retest=pd.Series(impulse_retest_arr, index=working.index, dtype=int),
        Impulse_Fading=impulse_fading.astype(int),
        plotcandle_0_ohlc_open=open_ if paint_bars else np.nan,
        plotcandle_0_ohlc_high=high if paint_bars else np.nan,
        plotcandle_0_ohlc_low=low if paint_bars else np.nan,
        plotcandle_0_ohlc_close=close if paint_bars else np.nan,
        plotcandle_0_ohlc_colorer=pd.Series(
            trend_color_code_arr if paint_bars else np.full(n, np.nan, dtype=float),
            index=working.index,
            dtype=float,
        ),
        plotcandle_0_wick_colorer=pd.Series(
            trend_color_code_arr if paint_bars else np.full(n, np.nan, dtype=float),
            index=working.index,
            dtype=float,
        ),
        plotcandle_0_border_colorer=pd.Series(
            trend_color_code_arr if paint_bars else np.full(n, np.nan, dtype=float),
            index=working.index,
            dtype=float,
        ),
        Band_Outer_colorer=pd.Series(trend_color_code_arr, index=working.index, dtype=float),
        Band_Inner_colorer=pd.Series(inner_color_code_arr, index=working.index, dtype=float),
        fill_0_data=band_outer_series,
        plot_12=band_inner_series,
        fill_0_colorer=pd.Series(fill_color_code_arr, index=working.index, dtype=float),
        plot_14=pd.Series(plot14_color_code_arr, index=working.index, dtype=float),
        Bull_Retest_colorer=BULL_COLOR_CODE,
        Bear_Retest_colorer=BEAR_COLOR_CODE,
    )


# -- SIGNAL ENGINE ----------------------------------------------------------
def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build the derived long/short strategy signals from the indicator outputs.

    Strategy policy:
    - Long entry on `Impulse_Long`
    - Short entry on `Impulse_Short`
    - Long exits on the next bearish switch
    - Short exits on the next bullish switch
    - Retest events remain informational only
    """
    required = {"Impulse_Long", "Impulse_Short", "Impulse_Retest"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(
            "generate_signals() requires indicator columns: " + ", ".join(missing)
        )

    working = df.copy()
    long_entry = working["Impulse_Long"].fillna(0).astype(int) == 1
    short_entry = working["Impulse_Short"].fillna(0).astype(int) == 1
    long_exit = short_entry
    short_exit = long_entry

    return working.assign(
        long_entry=long_entry,
        short_entry=short_entry,
        long_exit=long_exit,
        short_exit=short_exit,
    )


# -- BACKTEST ENGINE --------------------------------------------------------
def backtest(
    df: pd.DataFrame,
    initial_capital: float = DEFAULT_INITIAL_CAPITAL,
    commission_pct: float = DEFAULT_COMMISSION_PCT,
    slippage_ticks: int = DEFAULT_SLIPPAGE_TICKS,
    tick_size: float = DEFAULT_TICK_SIZE,
    pyramiding: int = DEFAULT_PYRAMIDING,
) -> dict:
    """
    Backtest the derived BOSWaves strategy using next-bar-open execution.

    Because the source is an indicator rather than a Pine strategy, this engine
    uses a fixed derived policy:
    - fully invested long or short
    - opposite signals close and reverse
    - no pyramiding, stop loss, or take profit
    - fills occur at the next bar open, adjusted for slippage
    """
    del pyramiding  # The derived strategy is single-position only.

    required = {"open", "close", "long_entry", "short_entry", "long_exit", "short_exit"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError("backtest() requires columns: " + ", ".join(missing))

    working = df.copy().sort_index()
    opens = working["open"].astype(float).to_numpy()
    closes = working["close"].astype(float).to_numpy()
    long_entry = working["long_entry"].astype(bool).to_numpy()
    short_entry = working["short_entry"].astype(bool).to_numpy()
    long_exit = working["long_exit"].astype(bool).to_numpy()
    short_exit = working["short_exit"].astype(bool).to_numpy()

    equity_curve = np.full(len(working), np.nan, dtype=float)
    commission_rate = commission_pct / 100.0
    slip = slippage_ticks * tick_size

    # Warm up until the nested SMA-based MAD and bands are available.
    warmup_bars = max(DEFAULT_LEN, DEFAULT_MAD_LEN * 2 - 1, DEFAULT_IMPULSE_LEN + 1)

    equity = float(initial_capital)
    position = 0  # 1 for long, -1 for short
    entry_price = np.nan
    entry_equity = np.nan
    entry_equity_before_commission = np.nan
    entry_bar = -1
    trade_pnls: list[float] = []
    bars_in_trade: list[int] = []

    def mark_to_market(close_price: float) -> float:
        if position == 0 or np.isnan(entry_price) or np.isnan(entry_equity):
            return equity
        return entry_equity * (1.0 + position * ((close_price - entry_price) / entry_price))

    for i in range(len(working)):
        if i > 0:
            prev_i = i - 1

            if position == 1 and long_exit[prev_i]:
                exit_price = opens[i] - slip
                realized_equity = entry_equity * (
                    1.0 + ((exit_price - entry_price) / entry_price)
                )
                realized_equity *= (1.0 - commission_rate)
                trade_pnls.append(realized_equity - entry_equity_before_commission)
                bars_in_trade.append(i - entry_bar)
                equity = realized_equity
                position = 0
                entry_price = np.nan
                entry_equity = np.nan
                entry_equity_before_commission = np.nan
                entry_bar = -1
            elif position == -1 and short_exit[prev_i]:
                exit_price = opens[i] + slip
                realized_equity = entry_equity * (
                    1.0 - ((exit_price - entry_price) / entry_price)
                )
                realized_equity *= (1.0 - commission_rate)
                trade_pnls.append(realized_equity - entry_equity_before_commission)
                bars_in_trade.append(i - entry_bar)
                equity = realized_equity
                position = 0
                entry_price = np.nan
                entry_equity = np.nan
                entry_equity_before_commission = np.nan
                entry_bar = -1

            if i >= warmup_bars and position == 0:
                if long_entry[prev_i]:
                    entry_equity_before_commission = equity
                    equity *= (1.0 - commission_rate)
                    entry_equity = equity
                    entry_price = opens[i] + slip
                    position = 1
                    entry_bar = i
                elif short_entry[prev_i]:
                    entry_equity_before_commission = equity
                    equity *= (1.0 - commission_rate)
                    entry_equity = equity
                    entry_price = opens[i] - slip
                    position = -1
                    entry_bar = i

        equity_curve[i] = mark_to_market(closes[i])

    if position != 0 and len(working) > 0:
        final_close = closes[-1]
        if position == 1:
            exit_price = final_close - slip
            realized_equity = entry_equity * (
                1.0 + ((exit_price - entry_price) / entry_price)
            )
        else:
            exit_price = final_close + slip
            realized_equity = entry_equity * (
                1.0 - ((exit_price - entry_price) / entry_price)
            )
        realized_equity *= (1.0 - commission_rate)
        trade_pnls.append(realized_equity - entry_equity_before_commission)
        bars_in_trade.append(len(working) - 1 - entry_bar + 1)
        equity = realized_equity
        equity_curve[-1] = equity

    equity_series = pd.Series(equity_curve, index=working.index, name="equity_curve")
    equity_returns = equity_series.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)

    total_return_pct = ((equity / initial_capital) - 1.0) * 100.0
    elapsed_years = max(
        (working.index[-1] - working.index[0]).total_seconds() / (365.25 * 24 * 3600),
        1e-12,
    )
    cagr_pct = (((equity / initial_capital) ** (1.0 / elapsed_years)) - 1.0) * 100.0

    bars_per_year = _bars_per_year(working.index)
    if equity_returns.std(ddof=0) > 0 and bars_per_year > 0:
        sharpe_ratio = float(
            equity_returns.mean() / equity_returns.std(ddof=0) * math.sqrt(bars_per_year)
        )
    else:
        sharpe_ratio = float("nan")

    downside = equity_returns[equity_returns < 0]
    if downside.std(ddof=0) > 0 and bars_per_year > 0:
        sortino_ratio = float(
            equity_returns.mean() / downside.std(ddof=0) * math.sqrt(bars_per_year)
        )
    else:
        sortino_ratio = float("nan")

    rolling_peak = equity_series.cummax()
    drawdown = (equity_series / rolling_peak) - 1.0
    max_drawdown_pct = abs(float(drawdown.min() * 100.0)) if len(drawdown) else 0.0

    total_trades = len(trade_pnls)
    gross_profit = float(sum(pnl for pnl in trade_pnls if pnl > 0))
    gross_loss = abs(float(sum(pnl for pnl in trade_pnls if pnl < 0)))
    win_rate_pct = (
        (sum(1 for pnl in trade_pnls if pnl > 0) / total_trades) * 100.0
        if total_trades > 0
        else 0.0
    )
    profit_factor = (
        gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    )
    avg_bars_in_trade = float(np.mean(bars_in_trade)) if bars_in_trade else 0.0

    return {
        "total_return_pct": total_return_pct,
        "cagr_pct": cagr_pct,
        "sharpe_ratio": sharpe_ratio,
        "sortino_ratio": sortino_ratio,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate_pct": win_rate_pct,
        "profit_factor": profit_factor,
        "total_trades": total_trades,
        "avg_bars_in_trade": avg_bars_in_trade,
        "equity_curve": equity_series,
        "warmup_bars": warmup_bars,
    }


# -- VALIDATION -------------------------------------------------------------
def validate_against_sample(
    df: pd.DataFrame,
    sample_path: str | Path,
) -> dict[str, dict[str, object]]:
    """
    Compare calculated outputs to the TradingView sample export.

    Logic columns are validated value-by-value and raise on any mismatch.
    Structural/export-artifact columns are reported as informational checks.
    """
    sample_df = load_csv_data(sample_path)
    if len(sample_df) != len(df):
        raise AssertionError(
            f"Row count mismatch. Actual={len(df)} Expected={len(sample_df)}"
        )

    results: dict[str, dict[str, object]] = {}

    for column in (*LOGIC_COLUMNS, *STRUCTURAL_COLUMNS):
        sample_column = _find_matching_sample_column(
            sample_df,
            VALIDATION_COLUMN_ALIASES[column],
        )
        if sample_column is None:
            results[column] = {
                "status": "MISSING",
                "sample_column": None,
                "max_err": float("nan"),
            }
            continue

        actual = df[column]
        expected = sample_df[sample_column]
        passed, mismatch_idx, actual_value, expected_value, diff = _compare_numeric_series(
            actual,
            expected,
            atol=LOGIC_COMPARE_ATOL,
        )
        max_err = _max_abs_error(actual, expected)
        results[column] = {
            "status": "PASS" if passed else "FAIL",
            "sample_column": sample_column,
            "max_err": max_err,
        }

        if not passed and column in LOGIC_COLUMNS:
            raise AssertionError(
                f"Validation failed for {column} against sample column {sample_column} at "
                f"{mismatch_idx}: actual={actual_value}, expected={expected_value}, diff={diff}"
            )

    return results


# -- INTERNAL TESTS ---------------------------------------------------------
def run_internal_sanity_checks() -> None:
    """Run deterministic checks around the stateful Pine translation."""
    test_index = pd.date_range("2025-01-01", periods=80, freq="h", tz="UTC")
    close = pd.Series(
        np.concatenate(
            [
                np.linspace(100.0, 120.0, 30),
                np.linspace(120.0, 101.0, 20),
                np.linspace(101.0, 125.0, 30),
            ]
        ),
        index=test_index,
    )
    open_ = close.shift(1).fillna(close.iloc[0])
    high = np.maximum(open_, close) + 1.0
    low = np.minimum(open_, close) - 1.0
    volume = pd.Series(1_000.0, index=test_index)

    test_df = pd.DataFrame(
        {
            "open": open_.astype(float),
            "high": high.astype(float),
            "low": low.astype(float),
            "close": close.astype(float),
            "volume": volume.astype(float),
        },
        index=test_index,
    )

    out = calculate_indicators(test_df, signal_buffer=3)
    sig = generate_signals(out)

    assert out["mad"].iloc[:38].isna().all(), "MAD should warm up over the nested SMA window."
    assert (out["freshness"] >= 0).all() and (out["freshness"] <= 1).all(), "Freshness must stay in [0, 1]."
    assert not (sig["long_entry"] & sig["short_entry"]).any(), "Entries must be mutually exclusive."
    assert (
        out["Impulse_Retest"]
        == ((out["Bull_Retest"].notna()) | (out["Bear_Retest"].notna())).astype(int)
    ).all()
    fading_crosses = ((out["freshness"].shift(1) > 0.5) & (out["freshness"] <= 0.5)).astype(int)
    assert (out["Impulse_Fading"] == fading_crosses).all(), "Impulse fading must only fire on downward 50% crosses."


# -- MAIN -------------------------------------------------------------------
def main(argv: list[str]) -> int:
    """Run validation and the derived backtest from a CSV sample."""
    sample_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_SAMPLE_PATH

    df = load_csv_data(sample_path)
    run_internal_sanity_checks()
    calculated = calculate_indicators(df)
    validation = validate_against_sample(calculated, sample_path)
    signals = generate_signals(calculated)
    metrics = backtest(signals)

    print(f"Indicator: {PINE_STRATEGY_NAME}")
    print(f"Rows: {len(df)}")
    print("Validation:")
    for column in LOGIC_COLUMNS:
        result = validation[column]
        print(f"  {column}: {result['status']} (max_err={result['max_err']})")

    print("Strategy:")
    print(f"  long_entry_count: {int(signals['long_entry'].sum())}")
    print(f"  short_entry_count: {int(signals['short_entry'].sum())}")
    print(f"  total_trades: {metrics['total_trades']}")
    print(f"  total_return_pct: {metrics['total_return_pct']:.6f}")
    print(f"  cagr_pct: {metrics['cagr_pct']:.6f}")
    print(f"  sharpe_ratio: {metrics['sharpe_ratio']:.6f}")
    print(f"  sortino_ratio: {metrics['sortino_ratio']:.6f}")
    print(f"  max_drawdown_pct: {metrics['max_drawdown_pct']:.6f}")
    print(f"  win_rate_pct: {metrics['win_rate_pct']:.6f}")
    print(f"  profit_factor: {metrics['profit_factor']:.6f}")
    print(f"  avg_bars_in_trade: {metrics['avg_bars_in_trade']:.6f}")
    print(f"  warmup_bars: {metrics['warmup_bars']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
