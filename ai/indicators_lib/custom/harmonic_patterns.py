"""
harmonic_patterns.py
====================
ZigZag-based harmonic pattern detection (Gartley, Bat, Butterfly, Crab, Shark, Cypher, ABCD).

Detects XABCD swing sequences and checks Fibonacci ratio constraints to identify
known harmonic patterns. Returns per-bar directional signals.

Signal output columns (picked up by signal_adapter.py):
  harmonic_bullish  (+1 at D point of bullish pattern)
  harmonic_bearish  (+1 at D point of bearish pattern → mapped to -1 by adapter)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_PRICE_COLUMNS = ("open", "high", "low", "close", "volume")

# Fibonacci ratio ranges per pattern (XB, AC, BD, XD)
HARMONIC_RATIOS = {
    'Gartley':   {'XB': (0.618, 0.618), 'AC': (0.382, 0.886), 'BD': (1.272, 1.618), 'XD': (0.786, 0.786)},
    'Bat':       {'XB': (0.382, 0.500), 'AC': (0.382, 0.886), 'BD': (1.618, 2.618), 'XD': (0.886, 0.886)},
    'Butterfly': {'XB': (0.786, 0.786), 'AC': (0.382, 0.886), 'BD': (1.618, 2.618), 'XD': (1.272, 1.618)},
    'Crab':      {'XB': (0.382, 0.618), 'AC': (0.382, 0.886), 'BD': (2.240, 3.618), 'XD': (1.618, 1.618)},
    'Shark':     {'XB': (0.382, 0.618), 'AC': (1.130, 1.618), 'BD': (1.618, 2.236), 'XD': (0.886, 1.130)},
    'Cypher':    {'XB': (0.382, 0.618), 'AC': (1.130, 1.414), 'BD': (1.272, 2.000), 'XD': (0.786, 0.786)},
    'ABCD':      {'XB': (0.000, 1.000), 'AC': (0.618, 0.786), 'BD': (1.272, 1.618), 'XD': (0.000, 2.000)},
}
TOLERANCE = 0.08


def _ratio_ok(actual: float, lo: float, hi: float) -> bool:
    return lo * (1 - TOLERANCE) <= actual <= hi * (1 + TOLERANCE)


def _zigzag_pivots(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> list[tuple[int, float, str]]:
    """Extract swing pivots using adaptive ZigZag."""
    n = len(h)
    price_range = (h.max() - l.min()) / l.min() if l.min() > 0 else 0.03
    pct = max(0.015, min(0.05, price_range / 50))

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
    Run ZigZag harmonic scan on OHLCV DataFrame.

    Returns df with added columns:
      harmonic_bullish  -- 1 at bars where a bullish harmonic D point completed
      harmonic_bearish  -- 1 at bars where a bearish harmonic D point completed
    """
    result = df.copy()
    n = len(df)
    bull = np.zeros(n, dtype=int)
    bear = np.zeros(n, dtype=int)

    if n < 20:
        result["harmonic_bullish"] = bull
        result["harmonic_bearish"] = bear
        return result

    h = df["high"].values
    l = df["low"].values
    c = df["close"].values

    pivots = _zigzag_pivots(h, l, c)

    for i in range(4, len(pivots)):
        _, Xp, _ = pivots[i - 4]
        _, Ap, _ = pivots[i - 3]
        _, Bp, _ = pivots[i - 2]
        _, Cp, _ = pivots[i - 1]
        Di, Dp, Dt = pivots[i]

        if Di >= n:
            continue

        XA = abs(Ap - Xp)
        if XA == 0:
            continue
        AB = abs(Bp - Ap)
        BC = abs(Cp - Bp)
        CD = abs(Dp - Cp)

        xb = AB / XA
        ac = BC / AB if AB > 0 else 0.0
        bd = CD / BC if BC > 0 else 0.0
        xd = abs(Dp - Xp) / XA

        for ratios in HARMONIC_RATIOS.values():
            if (_ratio_ok(xb, *ratios['XB']) and _ratio_ok(ac, *ratios['AC']) and
                    _ratio_ok(bd, *ratios['BD']) and _ratio_ok(xd, *ratios['XD'])):
                if Dt == 'L':   # bullish: D is a swing low — price expected to rise
                    bull[Di] = 1
                else:           # bearish: D is a swing high — price expected to fall
                    bear[Di] = 1
                break           # one pattern match per D point is enough

    result["harmonic_bullish"] = bull
    result["harmonic_bearish"] = bear
    return result


def run_strategy(frame: pd.DataFrame) -> pd.DataFrame:
    """Bridge for the Trading Strategy Comparator / combo optimizer."""
    df = frame.copy()
    ts_col = None
    if "timestamp" in df.columns:
        ts_col = df["timestamp"].copy()
        df = df.set_index(pd.to_datetime(df["datetime"]) if "datetime" in df.columns
                          else pd.to_datetime(df["timestamp"], unit="s", utc=True))
        df.index.name = "timestamp"

    result = calculate_indicators(df)

    if ts_col is not None and not isinstance(result.index, pd.RangeIndex):
        result = result.reset_index(drop=True)
    return result
