"""
# ============================================================
# STRATEGY: N Bar Reversal Detector [LuxAlgo]
# Converted from Pine Script v5 | 2026-03-21
# Original Pine author: LuxAlgo
# ============================================================
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Optional

import numpy as np
import pandas as pd

import n_bar_reversal_luxalgo as indicator_base


# -- PARAMETERS -------------------------------------------------------------
PINE_STRATEGY_NAME = indicator_base.PINE_INDICATOR_NAME
PINE_SHORT_NAME = indicator_base.PINE_SHORT_NAME
PINE_VERSION = "v5"
PINE_AUTHOR = indicator_base.PINE_AUTHOR

# Pine indicator defaults.
DEFAULT_BRP_TYPE = indicator_base.DEFAULT_BRP_TYPE
DEFAULT_NUM_BARS = indicator_base.DEFAULT_NUM_BARS
DEFAULT_MIN_BARS = indicator_base.DEFAULT_MIN_BARS
DEFAULT_BRP_SR = indicator_base.DEFAULT_BRP_SR
DEFAULT_TREND_TYPE = indicator_base.DEFAULT_TREND_TYPE
DEFAULT_TREND_FILTER = indicator_base.DEFAULT_TREND_FILTER
DEFAULT_MA_TYPE = indicator_base.DEFAULT_MA_TYPE
DEFAULT_MA_FAST_LENGTH = indicator_base.DEFAULT_MA_FAST_LENGTH
DEFAULT_MA_SLOW_LENGTH = indicator_base.DEFAULT_MA_SLOW_LENGTH
DEFAULT_ATR_PERIOD = indicator_base.DEFAULT_ATR_PERIOD
DEFAULT_FACTOR = indicator_base.DEFAULT_FACTOR
DEFAULT_DONCHIAN_LENGTH = indicator_base.DEFAULT_DONCHIAN_LENGTH

# Derived strategy defaults.
DEFAULT_ATR_STOP_MULT = 1.0
DEFAULT_ATR_TARGET_MULT = 2.0
DEFAULT_INITIAL_CAPITAL = 100_000.0
DEFAULT_COMMISSION_PCT = 0.0
DEFAULT_SLIPPAGE_TICKS = 0
DEFAULT_TICK_SIZE = 0.05
DEFAULT_PYRAMIDING = 0

DEFAULT_SAMPLE_PATH = Path(r"D:\TV_proj\output\individual\N_Bar_Reversal_LuxAlgo.csv")

SIGNAL_TYPE_NONE = 0
SIGNAL_TYPE_BULLISH_CONFIRMED = 1
SIGNAL_TYPE_BEARISH_CONFIRMED = -1
EXIT_REASON_TARGET = 1
EXIT_REASON_STOP = 2


# -- LOADING ----------------------------------------------------------------
def load_csv_data(path: str | Path) -> pd.DataFrame:
    """Load the sample CSV through the validated indicator module."""
    return indicator_base.load_csv_data(path)


# -- INDICATOR ENGINE -------------------------------------------------------
def calculate_indicators(
    df: pd.DataFrame,
    brp_type: str = DEFAULT_BRP_TYPE,
    num_bars: int = DEFAULT_NUM_BARS,
    min_bars: float = DEFAULT_MIN_BARS,
    brp_sr: str = DEFAULT_BRP_SR,
    trend_type: str = DEFAULT_TREND_TYPE,
    trend_filter: str = DEFAULT_TREND_FILTER,
    ma_type: str = DEFAULT_MA_TYPE,
    ma_fast_length: int = DEFAULT_MA_FAST_LENGTH,
    ma_slow_length: int = DEFAULT_MA_SLOW_LENGTH,
    atr_period: int = DEFAULT_ATR_PERIOD,
    factor: float = DEFAULT_FACTOR,
    donchian_length: int = DEFAULT_DONCHIAN_LENGTH,
) -> pd.DataFrame:
    """
    Calculate the full LuxAlgo indicator plus derived strategy context.

    The indicator engine is delegated to the validated local port, then
    augmented with:
    - trend bias
    - confirmation/failure process state
    - ATR risk series
    - pattern levels needed by the strategy layer
    """
    working = indicator_base.calculate_indicators(
        df,
        brp_type=brp_type,
        num_bars=num_bars,
        min_bars=min_bars,
        brp_sr=brp_sr,
        trend_type=trend_type,
        trend_filter=trend_filter,
        ma_type=ma_type,
        ma_fast_length=ma_fast_length,
        ma_slow_length=ma_slow_length,
        atr_period=atr_period,
        factor=factor,
        donchian_length=donchian_length,
    ).copy()

    open_ = working["open"].astype(float)
    high = working["high"].astype(float)
    low = working["low"].astype(float)
    close = working["close"].astype(float)
    volume = working["volume"].astype(float)

    ma_fast_raw = indicator_base._moving_average(close, volume, ma_fast_length, ma_type)
    ma_slow_raw = indicator_base._moving_average(close, volume, ma_slow_length, ma_type)
    supertrend, direction = indicator_base._supertrend(high, low, close, factor, atr_period)

    upper = close.rolling(window=donchian_length, min_periods=donchian_length).max()
    lower = close.rolling(window=donchian_length, min_periods=donchian_length).min()
    os = pd.Series(0, index=working.index, dtype=int)
    for i in range(1, len(working)):
        os.iloc[i] = (
            1
            if upper.iloc[i] > upper.iloc[i - 1]
            else 0 if lower.iloc[i] < lower.iloc[i - 1] else os.iloc[i - 1]
        )

    true_range = pd.concat(
        [
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_risk = indicator_base._rma(true_range, atr_period)

    trend_bias = pd.Series(0.0, index=working.index, dtype=float)
    c_up_trend = pd.Series(True, index=working.index, dtype=bool)
    c_down_trend = pd.Series(True, index=working.index, dtype=bool)

    if trend_type == "Moving Average Cloud":
        trend_bias = pd.Series(
            np.where(ma_fast_raw > ma_slow_raw, 1.0, -1.0),
            index=working.index,
            dtype=float,
        ).where(ma_fast_raw.notna() & ma_slow_raw.notna(), 0.0)
        if trend_filter == "Aligned":
            c_down_trend = (close < ma_fast_raw) & (ma_fast_raw < ma_slow_raw)
            c_up_trend = (close > ma_fast_raw) & (ma_fast_raw > ma_slow_raw)
        elif trend_filter == "Opposite":
            c_down_trend = (close > ma_fast_raw) & (ma_fast_raw > ma_slow_raw)
            c_up_trend = (close < ma_fast_raw) & (ma_fast_raw < ma_slow_raw)
    elif trend_type == "Supertrend":
        trend_bias = pd.Series(
            np.where(direction < 0, 1.0, -1.0),
            index=working.index,
            dtype=float,
        ).where(direction.notna(), 0.0)
        if trend_filter == "Aligned":
            c_down_trend = direction > 0
            c_up_trend = direction < 0
        elif trend_filter == "Opposite":
            c_down_trend = direction < 0
            c_up_trend = direction > 0
    elif trend_type == "Donchian Channels":
        trend_bias = pd.Series(
            np.where(os == 1, 1.0, -1.0),
            index=working.index,
            dtype=float,
        )
        if trend_filter == "Aligned":
            c_down_trend = os == 0
            c_up_trend = os == 1
        elif trend_filter == "Opposite":
            c_down_trend = os == 1
            c_up_trend = os == 0

    enhanced_bull = close > high.shift(num_bars)
    normal_bull = close < high.shift(num_bars)
    enhanced_bear = close < low.shift(num_bars)
    normal_bear = close > low.shift(num_bars)

    bullish_pattern_upper = high.shift(num_bars)
    bullish_pattern_lower = working["bull_low"].astype(float)
    bearish_pattern_upper = working["bear_high"].astype(float)
    bearish_pattern_lower = low.shift(num_bars)

    bullish_confirmed = pd.Series(False, index=working.index, dtype=bool)
    bearish_confirmed = pd.Series(False, index=working.index, dtype=bool)
    bullish_failed = pd.Series(False, index=working.index, dtype=bool)
    bearish_failed = pd.Series(False, index=working.index, dtype=bool)
    bull_process_state = pd.Series(False, index=working.index, dtype=bool)
    bear_process_state = pd.Series(False, index=working.index, dtype=bool)
    bullish_pattern_level = pd.Series(np.nan, index=working.index, dtype=float)
    bearish_pattern_level = pd.Series(np.nan, index=working.index, dtype=float)
    bullish_pattern_origin = pd.Series(np.nan, index=working.index, dtype=float)
    bearish_pattern_origin = pd.Series(np.nan, index=working.index, dtype=float)

    bull_process = False
    bear_process = False
    bull_upper_level = np.nan
    bull_lower_level = np.nan
    bear_upper_level = np.nan
    bear_lower_level = np.nan
    bull_origin = np.nan
    bear_origin = np.nan

    bullish_pattern_start = working["bullish_pattern_start"].fillna(False).astype(bool)
    bearish_pattern_start = working["bearish_pattern_start"].fillna(False).astype(bool)
    bullish_reversal = working["bullish_reversal"].fillna(False).astype(bool)
    bearish_reversal = working["bearish_reversal"].fillna(False).astype(bool)

    for i in range(len(working)):
        if bullish_pattern_start.iloc[i]:
            bull_process = True
            bull_upper_level = bullish_pattern_upper.iloc[i]
            bull_lower_level = bullish_pattern_lower.iloc[i]
            bull_origin = float(i)

        if bull_process:
            bull_process_state.iloc[i] = True
            if i > 0 and not np.isnan(bull_upper_level) and close.iloc[i - 1] > bull_upper_level:
                bullish_confirmed.iloc[i] = True
                bullish_pattern_level.iloc[i] = bull_upper_level
                bullish_pattern_origin.iloc[i] = bull_origin
                bull_process = False
            elif i > 0 and (
                (not np.isnan(bull_lower_level) and close.iloc[i - 1] < bull_lower_level)
                or bearish_reversal.iloc[i]
            ):
                bullish_failed.iloc[i] = True
                bull_process = False

        if bearish_pattern_start.iloc[i]:
            bear_process = True
            bear_upper_level = bearish_pattern_upper.iloc[i]
            bear_lower_level = bearish_pattern_lower.iloc[i]
            bear_origin = float(i)

        if bear_process:
            bear_process_state.iloc[i] = True
            if i > 0 and (
                (not np.isnan(bear_upper_level) and close.iloc[i - 1] > bear_upper_level)
                or bullish_reversal.iloc[i]
            ):
                bearish_failed.iloc[i] = True
                bear_process = False
            elif i > 0 and not np.isnan(bear_lower_level) and close.iloc[i - 1] < bear_lower_level:
                bearish_confirmed.iloc[i] = True
                bearish_pattern_level.iloc[i] = bear_lower_level
                bearish_pattern_origin.iloc[i] = bear_origin
                bear_process = False

    return working.assign(
        atr_risk=atr_risk,
        trend_bias=trend_bias,
        c_up_trend=c_up_trend.astype(bool),
        c_down_trend=c_down_trend.astype(bool),
        ma_fast_raw=ma_fast_raw,
        ma_slow_raw=ma_slow_raw,
        supertrend_raw=supertrend,
        supertrend_direction=direction,
        donchian_upper=upper,
        donchian_lower=lower,
        donchian_os=os.astype(float),
        enhanced_bull=enhanced_bull.astype(bool),
        normal_bull=normal_bull.astype(bool),
        enhanced_bear=enhanced_bear.astype(bool),
        normal_bear=normal_bear.astype(bool),
        bullish_pattern_upper=bullish_pattern_upper,
        bullish_pattern_lower=bullish_pattern_lower,
        bearish_pattern_upper=bearish_pattern_upper,
        bearish_pattern_lower=bearish_pattern_lower,
        bull_process_state=bull_process_state,
        bear_process_state=bear_process_state,
        bullish_confirmed=bullish_confirmed,
        bearish_confirmed=bearish_confirmed,
        bullish_failed=bullish_failed,
        bearish_failed=bearish_failed,
        bullish_pattern_level=bullish_pattern_level,
        bearish_pattern_level=bearish_pattern_level,
        bullish_pattern_origin=bullish_pattern_origin,
        bearish_pattern_origin=bearish_pattern_origin,
    )


def _simulate_trade_events(
    df: pd.DataFrame,
    atr_stop_mult: float,
    atr_target_mult: float,
    warmup_bars: int,
) -> dict[str, np.ndarray]:
    """Simulate confirmed-pattern entries and ATR TP/SL exits bar by bar."""
    n = len(df)
    open_v = df["open"].astype(float).to_numpy()
    high_v = df["high"].astype(float).to_numpy()
    low_v = df["low"].astype(float).to_numpy()
    close_v = df["close"].astype(float).to_numpy()
    atr_v = df["atr_risk"].astype(float).to_numpy()
    bull_confirmed = df["bullish_confirmed"].fillna(False).to_numpy(dtype=bool)
    bear_confirmed = df["bearish_confirmed"].fillna(False).to_numpy(dtype=bool)
    bull_level = df["bullish_pattern_level"].astype(float).to_numpy()
    bear_level = df["bearish_pattern_level"].astype(float).to_numpy()
    trend_bias = df["trend_bias"].astype(float).to_numpy()

    long_entry = np.zeros(n, dtype=bool)
    short_entry = np.zeros(n, dtype=bool)
    long_exit = np.zeros(n, dtype=bool)
    short_exit = np.zeros(n, dtype=bool)
    entry_price = np.full(n, np.nan, dtype=float)
    stop_price = np.full(n, np.nan, dtype=float)
    target_price = np.full(n, np.nan, dtype=float)
    exit_price = np.full(n, np.nan, dtype=float)
    signal_type = np.full(n, SIGNAL_TYPE_NONE, dtype=float)
    pattern_level = np.full(n, np.nan, dtype=float)
    exit_reason = np.full(n, np.nan, dtype=float)

    position = 0
    active_stop = np.nan
    active_target = np.nan
    pending_side = 0
    pending_fill_index = -1
    pending_fill_price = np.nan
    pending_atr = np.nan
    pending_signal_type = SIGNAL_TYPE_NONE
    pending_pattern_level = np.nan
    skip_same_bar_exit = False

    for i in range(n):
        if pending_side != 0 and i == pending_fill_index:
            entry_px = pending_fill_price
            stop_px = entry_px - atr_stop_mult * pending_atr if pending_side == 1 else entry_px + atr_stop_mult * pending_atr
            target_px = entry_px + atr_target_mult * pending_atr if pending_side == 1 else entry_px - atr_target_mult * pending_atr

            if pending_side == 1:
                long_entry[i] = True
            else:
                short_entry[i] = True
            entry_price[i] = entry_px
            stop_price[i] = stop_px
            target_price[i] = target_px
            signal_type[i] = pending_signal_type
            pattern_level[i] = pending_pattern_level

            position = pending_side
            active_stop = stop_px
            active_target = target_px
            skip_same_bar_exit = pending_fill_index == n - 1 and np.isclose(entry_px, close_v[i], atol=1e-12, rtol=0.0)

            pending_side = 0
            pending_fill_index = -1
            pending_fill_price = np.nan
            pending_atr = np.nan
            pending_signal_type = SIGNAL_TYPE_NONE
            pending_pattern_level = np.nan

        if position != 0 and not skip_same_bar_exit:
            if position == 1:
                hit_stop = low_v[i] <= active_stop
                hit_target = high_v[i] >= active_target
                if hit_stop or hit_target:
                    long_exit[i] = True
                    exit_reason[i] = EXIT_REASON_STOP if hit_stop else EXIT_REASON_TARGET
                    exit_price[i] = active_stop if hit_stop else active_target
                    position = 0
                    active_stop = np.nan
                    active_target = np.nan
            else:
                hit_stop = high_v[i] >= active_stop
                hit_target = low_v[i] <= active_target
                if hit_stop or hit_target:
                    short_exit[i] = True
                    exit_reason[i] = EXIT_REASON_STOP if hit_stop else EXIT_REASON_TARGET
                    exit_price[i] = active_stop if hit_stop else active_target
                    position = 0
                    active_stop = np.nan
                    active_target = np.nan

        skip_same_bar_exit = False

        if i < warmup_bars or position != 0 or pending_side != 0:
            continue

        bull_signal = bool(bull_confirmed[i])
        bear_signal = bool(bear_confirmed[i])
        if bull_signal == bear_signal:
            continue

        atr_value = atr_v[i]
        if np.isnan(atr_value) or atr_value <= 0:
            continue

        fill_index = i + 1 if i + 1 < n else i
        fill_price = open_v[fill_index] if fill_index > i else close_v[i]

        if bull_signal:
            pending_side = 1
            pending_fill_index = fill_index
            pending_fill_price = fill_price
            pending_atr = atr_value
            pending_signal_type = SIGNAL_TYPE_BULLISH_CONFIRMED
            pending_pattern_level = bull_level[i]
        elif bear_signal:
            pending_side = -1
            pending_fill_index = fill_index
            pending_fill_price = fill_price
            pending_atr = atr_value
            pending_signal_type = SIGNAL_TYPE_BEARISH_CONFIRMED
            pending_pattern_level = bear_level[i]

    return {
        "long_entry": long_entry,
        "short_entry": short_entry,
        "long_exit": long_exit,
        "short_exit": short_exit,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "exit_price": exit_price,
        "signal_type": signal_type,
        "pattern_level": pattern_level,
        "trend_bias_out": trend_bias,
        "exit_reason": exit_reason,
    }


# -- SIGNAL ENGINE ----------------------------------------------------------
def generate_signals(
    df: pd.DataFrame,
    num_bars: int = DEFAULT_NUM_BARS,
    ma_slow_length: int = DEFAULT_MA_SLOW_LENGTH,
    atr_period: int = DEFAULT_ATR_PERIOD,
    donchian_length: int = DEFAULT_DONCHIAN_LENGTH,
    atr_stop_mult: float = DEFAULT_ATR_STOP_MULT,
    atr_target_mult: float = DEFAULT_ATR_TARGET_MULT,
) -> pd.DataFrame:
    """
    Generate derived strategy entries/exits from confirmed LuxAlgo patterns.

    Entries are placed on the execution bar:
    - next bar open after a confirmation signal
    - current close if the confirmation occurs on the final available bar
    """
    required = {
        "open",
        "high",
        "low",
        "close",
        "atr_risk",
        "bullish_confirmed",
        "bearish_confirmed",
        "bullish_pattern_level",
        "bearish_pattern_level",
        "trend_bias",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(
            "generate_signals requires calculate_indicators output. Missing columns: "
            + ", ".join(missing)
        )

    warmup_bars = max(num_bars + 1, ma_slow_length, atr_period, donchian_length)
    events = _simulate_trade_events(
        df,
        atr_stop_mult=atr_stop_mult,
        atr_target_mult=atr_target_mult,
        warmup_bars=warmup_bars,
    )

    out = df.copy()
    out["long_entry"] = events["long_entry"]
    out["short_entry"] = events["short_entry"]
    out["long_exit"] = events["long_exit"]
    out["short_exit"] = events["short_exit"]
    out["entry_price"] = events["entry_price"]
    out["stop_price"] = events["stop_price"]
    out["target_price"] = events["target_price"]
    out["exit_price"] = events["exit_price"]
    out["signal_type"] = events["signal_type"]
    out["pattern_level"] = events["pattern_level"]
    out["trend_bias"] = events["trend_bias_out"]
    out["exit_reason"] = events["exit_reason"]
    return out


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
    Backtest the derived LuxAlgo reversal strategy.

    Strategy policy:
    - one open position at a time
    - entry on bars flagged by `long_entry` / `short_entry`
    - exit on ATR target/stop bars flagged by `long_exit` / `short_exit`
    - opposite signals are ignored while a trade is open
    """
    del pyramiding  # This derived strategy is single-position only.

    required = {
        "close",
        "long_entry",
        "short_entry",
        "long_exit",
        "short_exit",
        "entry_price",
        "exit_price",
    }
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(
            "backtest requires generate_signals output. Missing columns: "
            + ", ".join(missing)
        )

    working = df.copy()
    closes = working["close"].astype(float).to_numpy()
    long_entry = working["long_entry"].fillna(False).to_numpy(dtype=bool)
    short_entry = working["short_entry"].fillna(False).to_numpy(dtype=bool)
    long_exit = working["long_exit"].fillna(False).to_numpy(dtype=bool)
    short_exit = working["short_exit"].fillna(False).to_numpy(dtype=bool)
    raw_entry = working["entry_price"].astype(float).to_numpy()
    raw_exit = working["exit_price"].astype(float).to_numpy()

    commission_rate = commission_pct / 100.0
    slip = slippage_ticks * tick_size

    equity = initial_capital
    equity_curve = np.full(len(working), np.nan, dtype=float)
    position = 0
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
        if position == 0:
            if long_entry[i]:
                if np.isnan(raw_entry[i]):
                    raise ValueError(f"Missing entry_price on long entry at {working.index[i]}")
                entry_equity_before_commission = equity
                equity *= (1.0 - commission_rate)
                entry_equity = equity
                entry_price = raw_entry[i] + slip
                position = 1
                entry_bar = i
            elif short_entry[i]:
                if np.isnan(raw_entry[i]):
                    raise ValueError(f"Missing entry_price on short entry at {working.index[i]}")
                entry_equity_before_commission = equity
                equity *= (1.0 - commission_rate)
                entry_equity = equity
                entry_price = raw_entry[i] - slip
                position = -1
                entry_bar = i

        if position == 1 and long_exit[i]:
            if np.isnan(raw_exit[i]):
                raise ValueError(f"Missing exit_price on long exit at {working.index[i]}")
            exit_price = raw_exit[i] - slip
            realized_equity = entry_equity * (1.0 + ((exit_price - entry_price) / entry_price))
            realized_equity *= (1.0 - commission_rate)
            trade_pnls.append(realized_equity - entry_equity_before_commission)
            bars_in_trade.append(i - entry_bar + 1)
            equity = realized_equity
            position = 0
            entry_price = np.nan
            entry_equity = np.nan
            entry_equity_before_commission = np.nan
            entry_bar = -1
        elif position == -1 and short_exit[i]:
            if np.isnan(raw_exit[i]):
                raise ValueError(f"Missing exit_price on short exit at {working.index[i]}")
            exit_price = raw_exit[i] + slip
            realized_equity = entry_equity * (1.0 - ((exit_price - entry_price) / entry_price))
            realized_equity *= (1.0 - commission_rate)
            trade_pnls.append(realized_equity - entry_equity_before_commission)
            bars_in_trade.append(i - entry_bar + 1)
            equity = realized_equity
            position = 0
            entry_price = np.nan
            entry_equity = np.nan
            entry_equity_before_commission = np.nan
            entry_bar = -1

        equity_curve[i] = mark_to_market(closes[i])

    if position != 0:
        final_close = closes[-1]
        if position == 1:
            final_exit = final_close - slip
            realized_equity = entry_equity * (1.0 + ((final_exit - entry_price) / entry_price))
        else:
            final_exit = final_close + slip
            realized_equity = entry_equity * (1.0 - ((final_exit - entry_price) / entry_price))
        realized_equity *= (1.0 - commission_rate)
        trade_pnls.append(realized_equity - entry_equity_before_commission)
        bars_in_trade.append(len(working) - entry_bar)
        equity = realized_equity
        equity_curve[-1] = equity

    equity_series = pd.Series(equity_curve, index=working.index, name="equity_curve").ffill()
    returns = equity_series.pct_change().fillna(0.0)
    negative_returns = returns.where(returns < 0.0, 0.0)

    years = max(
        (working.index[-1] - working.index[0]).total_seconds() / (365.25 * 24 * 3600),
        1e-9,
    )
    total_return_pct = (equity_series.iloc[-1] / initial_capital - 1.0) * 100.0
    cagr_pct = ((equity_series.iloc[-1] / initial_capital) ** (1.0 / years) - 1.0) * 100.0

    bars_per_year = float(max(len(working) / years, 1.0))
    sharpe_ratio = 0.0
    if returns.std(ddof=0) > 0:
        sharpe_ratio = float((returns.mean() / returns.std(ddof=0)) * np.sqrt(bars_per_year))

    sortino_ratio = 0.0
    downside_std = negative_returns.std(ddof=0)
    if downside_std > 0:
        sortino_ratio = float((returns.mean() / downside_std) * np.sqrt(bars_per_year))

    running_max = equity_series.cummax()
    drawdown = equity_series / running_max - 1.0
    max_drawdown_pct = float(drawdown.min() * 100.0)

    total_trades = len(trade_pnls)
    win_rate_pct = (
        float(sum(pnl > 0 for pnl in trade_pnls) / total_trades * 100.0)
        if total_trades
        else 0.0
    )
    gross_profit = float(sum(pnl for pnl in trade_pnls if pnl > 0))
    gross_loss = float(-sum(pnl for pnl in trade_pnls if pnl < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    avg_bars_in_trade = float(np.mean(bars_in_trade)) if bars_in_trade else 0.0

    return {
        "total_return_pct": float(total_return_pct),
        "cagr_pct": float(cagr_pct),
        "sharpe_ratio": float(sharpe_ratio),
        "sortino_ratio": float(sortino_ratio),
        "max_drawdown_pct": float(max_drawdown_pct),
        "win_rate_pct": float(win_rate_pct),
        "profit_factor": float(profit_factor),
        "total_trades": int(total_trades),
        "avg_bars_in_trade": float(avg_bars_in_trade),
        "equity_curve": equity_series,
    }


# -- VALIDATION -------------------------------------------------------------
def validate_against_sample(df: pd.DataFrame, sample_path: str | Path) -> None:
    """Validate indicator parity and note that strategy outputs are derived."""
    indicator_base.validate_against_sample(df, sample_path)
    print("\nNote: strategy signals/TP/SL are derived and not directly exported by TradingView.")


# -- INTERNAL TESTS ---------------------------------------------------------
def run_internal_sanity_checks(df: pd.DataFrame, signals: pd.DataFrame) -> None:
    """Verify internal consistency for derived confirmation and strategy series."""
    required_indicator_columns = (
        "bullish_reversal",
        "bearish_reversal",
        "bullish_pattern_start",
        "bearish_pattern_start",
        "bullish_confirmed",
        "bearish_confirmed",
        "atr_risk",
    )
    missing_indicator = [column for column in required_indicator_columns if column not in df.columns]
    if missing_indicator:
        raise ValueError(
            "run_internal_sanity_checks requires calculated columns: " + ", ".join(missing_indicator)
        )

    required_signal_columns = (
        "long_entry",
        "short_entry",
        "long_exit",
        "short_exit",
        "entry_price",
        "stop_price",
        "target_price",
    )
    missing_signal = [column for column in required_signal_columns if column not in signals.columns]
    if missing_signal:
        raise ValueError(
            "run_internal_sanity_checks requires generated signal columns: " + ", ".join(missing_signal)
        )

    if (signals["long_entry"] & signals["short_entry"]).any():
        raise AssertionError("A bar cannot contain both long_entry and short_entry.")
    if (signals["long_exit"] & signals["short_exit"]).any():
        raise AssertionError("A bar cannot contain both long_exit and short_exit.")

    long_rows = signals["long_entry"].fillna(False)
    short_rows = signals["short_entry"].fillna(False)
    if not ((signals.loc[long_rows, "target_price"] > signals.loc[long_rows, "entry_price"]).all()):
        raise AssertionError("Long target_price must exceed long entry_price.")
    if not ((signals.loc[long_rows, "stop_price"] < signals.loc[long_rows, "entry_price"]).all()):
        raise AssertionError("Long stop_price must be below long entry_price.")
    if not ((signals.loc[short_rows, "target_price"] < signals.loc[short_rows, "entry_price"]).all()):
        raise AssertionError("Short target_price must be below short entry_price.")
    if not ((signals.loc[short_rows, "stop_price"] > signals.loc[short_rows, "entry_price"]).all()):
        raise AssertionError("Short stop_price must be above short entry_price.")

    print(
        "Internal sanity checks: PASS "
        f"(bullish_confirmed={int(df['bullish_confirmed'].sum())}, "
        f"bearish_confirmed={int(df['bearish_confirmed'].sum())}, "
        f"long_entries={int(signals['long_entry'].sum())}, "
        f"short_entries={int(signals['short_entry'].sum())})"
    )


# -- MAIN -------------------------------------------------------------------
def main(sample_path: str | Path = DEFAULT_SAMPLE_PATH) -> int:
    """Load the sample, calculate indicators, validate parity, and run the strategy."""
    df = load_csv_data(sample_path)
    calculated = calculate_indicators(df)
    signals = generate_signals(calculated)
    run_internal_sanity_checks(calculated, signals)
    validate_against_sample(calculated, sample_path)
    stats = backtest(signals)

    print("\nDerived strategy counts:")
    print(f"  bullish_confirmed: {int(calculated['bullish_confirmed'].sum())}")
    print(f"  bearish_confirmed: {int(calculated['bearish_confirmed'].sum())}")
    print(f"  long_entry: {int(signals['long_entry'].sum())}")
    print(f"  short_entry: {int(signals['short_entry'].sum())}")
    print(f"  long_exit: {int(signals['long_exit'].sum())}")
    print(f"  short_exit: {int(signals['short_exit'].sum())}")

    print("\nBacktest:")
    print(f"  total_return_pct={stats['total_return_pct']:.6f}")
    print(f"  cagr_pct={stats['cagr_pct']:.6f}")
    print(f"  sharpe_ratio={stats['sharpe_ratio']:.6f}")
    print(f"  sortino_ratio={stats['sortino_ratio']:.6f}")
    print(f"  max_drawdown_pct={stats['max_drawdown_pct']:.6f}")
    print(f"  win_rate_pct={stats['win_rate_pct']:.6f}")
    print(f"  profit_factor={stats['profit_factor']:.6f}")
    print(f"  total_trades={stats['total_trades']}")
    print(f"  avg_bars_in_trade={stats['avg_bars_in_trade']:.6f}")
    return 0


if __name__ == "__main__":
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PATH
    raise SystemExit(main(input_path))
