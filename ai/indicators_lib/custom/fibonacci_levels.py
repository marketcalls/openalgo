"""
fibonacci_levels.py
===================
Fibonacci retracement signal generator.

Detects recent swing high / swing low using ZigZag and computes standard
Fibonacci retracement levels (23.6%, 38.2%, 50%, 61.8%, 78.6%).

A signal fires when the current close is within TOUCH_PCT of a Fib level:
  - fib_long  = +1  (price at Fib support inside a downswing → potential bounce up)
  - fib_short = +1  (price at Fib resistance inside an upswing → potential reversal down)

The signal_adapter.py picks up:
  "long"  → direction +1   (fib_long)
  "short" → direction -1   (fib_short)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

FIB_RATIOS = [0.236, 0.382, 0.500, 0.618, 0.786]
TOUCH_PCT   = 0.005    # price within 0.5% of a Fib level counts as a touch
SWING_PCT   = 0.02     # minimum ZigZag swing size (2%)
MIN_LOOKBACK = 10      # bars to wait before signalling again (cooldown)


def _zigzag_pivots(h: np.ndarray, l: np.ndarray, c: np.ndarray,
                   pct: float = SWING_PCT) -> list[tuple[int, float, str]]:
    """Return list of (bar_index, price, 'H'|'L') swing pivots."""
    n = len(h)
    pivots: list[tuple[int, float, str]] = []
    last_type: str | None = None
    last_price = c[0]

    for i in range(1, n):
        if h[i] >= last_price * (1 + pct) and last_type != 'H':
            pivots.append((i, h[i], 'H'))
            last_type, last_price = 'H', h[i]
        elif l[i] <= last_price * (1 - pct) and last_type != 'L':
            pivots.append((i, l[i], 'L'))
            last_type, last_price = 'L', l[i]
        else:
            if last_type == 'H' and h[i] > last_price:
                pivots[-1] = (i, h[i], 'H')
                last_price = h[i]
            elif last_type == 'L' and l[i] < last_price:
                pivots[-1] = (i, l[i], 'L')
                last_price = l[i]

    return pivots


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute Fibonacci retracement signals on OHLCV DataFrame.

    Returns df with added columns:
      fib_long   -- 1 when price is at a bullish Fib support (downswing retracement)
      fib_short  -- 1 when price is at a bearish Fib resistance (upswing retracement)
    """
    result = df.copy()
    n = len(df)
    fib_long  = np.zeros(n, dtype=int)
    fib_short = np.zeros(n, dtype=int)

    if n < 20:
        result["fib_long"]  = fib_long
        result["fib_short"] = fib_short
        return result

    h = df["high"].values
    l = df["low"].values
    c = df["close"].values

    pivots = _zigzag_pivots(h, l, c)
    if len(pivots) < 2:
        result["fib_long"]  = fib_long
        result["fib_short"] = fib_short
        return result

    # For each bar, find the most recent completed swing (H-L or L-H pair)
    # and check if current price is near a Fib retracement of that swing.
    last_signal_bar = -MIN_LOOKBACK

    for bar_i in range(1, n):
        price = c[bar_i]

        # Find the two most recent pivots before this bar
        recent = [(pi, pp, pt) for (pi, pp, pt) in pivots if pi < bar_i]
        if len(recent) < 2:
            continue

        p1 = recent[-1]   # most recent pivot
        p2 = recent[-2]   # second most recent pivot

        _, p1_price, p1_type = p1
        _, p2_price, p2_type = p2

        if p1_type == 'L' and p2_type == 'H':
            # Downswing: H → L; Fib levels measure how far price has retraced up from L
            # Bullish signal: price near 38.2%–78.6% retracement (support bounce zone)
            swing = p2_price - p1_price
            if swing <= 0:
                continue
            for ratio in FIB_RATIOS[1:4]:   # 38.2, 50, 61.8 — core support zone
                level = p1_price + swing * ratio
                if abs(price - level) / level <= TOUCH_PCT:
                    if (bar_i - last_signal_bar) >= MIN_LOOKBACK:
                        fib_long[bar_i] = 1
                        last_signal_bar = bar_i
                    break

        elif p1_type == 'H' and p2_type == 'L':
            # Upswing: L → H; Fib levels measure how far price has pulled back from H
            # Bearish signal: price near 38.2%–78.6% retracement (resistance zone)
            swing = p1_price - p2_price
            if swing <= 0:
                continue
            for ratio in FIB_RATIOS[1:4]:   # 38.2, 50, 61.8 — core resistance zone
                level = p1_price - swing * ratio
                if abs(price - level) / level <= TOUCH_PCT:
                    if (bar_i - last_signal_bar) >= MIN_LOOKBACK:
                        fib_short[bar_i] = 1
                        last_signal_bar = bar_i
                    break

    result["fib_long"]  = fib_long
    result["fib_short"] = fib_short
    return result


def run_strategy(frame: pd.DataFrame) -> pd.DataFrame:
    """Bridge for the Trading Strategy Comparator / combo optimizer."""
    df = frame.copy()

    if "timestamp" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index(pd.to_datetime(df["datetime"]) if "datetime" in df.columns
                          else pd.to_datetime(df["timestamp"], unit="s", utc=True))
        df.index.name = "timestamp"

    result = calculate_indicators(df)

    if not isinstance(result.index, pd.RangeIndex):
        result = result.reset_index(drop=True)
    return result
