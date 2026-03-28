"""
INDICATOR: ZigZag Swing Pivot Confirm
Library: ZigZag (D:\test1\opensource_indicators\ZigZag\) -- core.pyx Cython only
Implementation: Pure Python reimplementation of peak_valley_pivots from core.pyx
Signal: bullish when VALLEY pivot CONFIRMED (3%+ rise from the low is observed)
        bearish when PEAK pivot CONFIRMED (3%+ fall from the high is observed)
MAPPING: VALLEY confirmation -> bullish (+1 buy)
         PEAK   confirmation -> bearish (-1 sell)

LOOKAHEAD-FREE DESIGN:
  Signal fires at bar t (confirmation bar), NOT at the pivot bar itself.
  A valley at bar last_pivot_t is only KNOWABLE at bar t when price rises 3% from it.
  Placing the signal at the pivot bar would be lookahead bias in backtesting.
  Signal fires the bar you could actually trade it (when 3% reversal is confirmed).
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

DEFAULT_UP_PCT   = 0.03   # 3% rise from low to confirm valley
DEFAULT_DOWN_PCT = 0.03   # 3% fall from high to confirm peak


def _identify_initial_pivot(X: np.ndarray, up_thresh: float, down_thresh: float) -> int:
    """Find whether the first pivot is a PEAK (+1) or VALLEY (-1). Translation of core.pyx."""
    x_0 = X[0]
    max_x, min_x = x_0, x_0
    max_t, min_t = 0, 0
    up   = up_thresh + 1
    down = down_thresh + 1

    for t in range(1, len(X)):
        x_t = X[t]
        if x_t / min_x >= up:
            return -1 if min_t == 0 else 1
        if x_t / max_x <= down:
            return 1 if max_t == 0 else -1
        if x_t > max_x:
            max_x, max_t = x_t, t
        if x_t < min_x:
            min_x, min_t = x_t, t

    return -1 if X[0] < X[-1] else 1


def _peak_valley_pivots_confirmed(X: np.ndarray, up_pct: float, down_pct: float) -> np.ndarray:
    """
    Signals fire at bar t (CONFIRMATION bar), NOT at the pivot bar.
    This eliminates lookahead bias: a valley at bar last_pivot_t is only
    knowable at bar t when price has risen >= up_pct% from it.

    Returns int array:
      -1 at bar t = VALLEY confirmed at bar t (price just rose 3% -> bullish)
      +1 at bar t = PEAK confirmed at bar t (price just fell 3% -> bearish)
       0 = neither
    """
    down_thresh = -abs(down_pct)
    up_thresh   =  abs(up_pct)

    X = np.asarray(X, dtype=np.float64)
    t_n = len(X)
    confirmed = np.zeros(t_n, dtype=int)  # signal at CONFIRMATION bar, not pivot bar

    initial_pivot = _identify_initial_pivot(X, up_thresh, down_thresh)
    trend         = -initial_pivot
    last_pivot_x  = X[0]
    last_pivot_t  = 0

    up   = up_thresh + 1
    down = down_thresh + 1

    for t in range(1, t_n):
        x = X[t]
        r = x / last_pivot_x

        if trend == -1:              # waiting to confirm a VALLEY
            if r >= up:              # price rose enough -> VALLEY confirmed
                confirmed[t] = -1   # signal fires at bar t (when we KNOW it was a valley)
                trend        = 1
                last_pivot_x = x
                last_pivot_t = t
            elif x < last_pivot_x:  # new lower low -> update pivot candidate
                last_pivot_x = x
                last_pivot_t = t
        else:                        # trend == 1: waiting to confirm a PEAK
            if r <= down:            # price fell enough -> PEAK confirmed
                confirmed[t] = 1    # signal fires at bar t (when we KNOW it was a peak)
                trend        = -1
                last_pivot_x = x
                last_pivot_t = t
            elif x > last_pivot_x:  # new higher high -> update pivot candidate
                last_pivot_x = x
                last_pivot_t = t

    return confirmed


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with bullish_zigzag (1/0) and bearish_zigzag (1/0).
    Signals fire at the CONFIRMATION bar (no lookahead).
    VALLEY confirmed -> bullish; PEAK confirmed -> bearish.
    Last signal excluded (may be at a boundary with no following confirmation).
    """
    close     = df["close"].values.astype(np.float64)
    confirmed = _peak_valley_pivots_confirmed(close, DEFAULT_UP_PCT, DEFAULT_DOWN_PCT)

    # Find all confirmation bars
    conf_idxs = np.where(confirmed != 0)[0]

    # Exclude the last confirmation (boundary: no subsequent reversal yet confirmed)
    if len(conf_idxs) > 1:
        conf_idxs = conf_idxs[:-1]

    n = len(df)
    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    for idx in conf_idxs:
        if confirmed[idx] == -1:   # VALLEY confirmed -> bullish
            bullish[idx] = 1
        elif confirmed[idx] == 1:  # PEAK confirmed -> bearish
            bearish[idx] = 1

    out = df.copy()
    out["bullish_zigzag"] = bullish
    out["bearish_zigzag"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_zigzag"]
        bear = result["bearish_zigzag"]
        assert not (bull & bear).any(), "simultaneous bull+bear signal"
        assert set(bull.unique()).issubset({0, 1}), "bull non-0/1"
        assert set(bear.unique()).issubset({0, 1}), "bear non-0/1"
        assert bull.isna().sum() == 0 and bear.isna().sum() == 0, "NaN in output"
        n = int((bull | bear).sum())
        assert n > 0, "zero signals"
        rate = n / len(df)
        assert rate < 0.30, f"rate {rate:.1%} too high (state indicator?)"
        return {"status": "PASS", "n": n, "rate": rate, "msg": ""}
    except AssertionError as e:
        return {"status": "FAIL", "n": 0, "rate": 0.0, "msg": str(e)}
    except Exception as e:
        return {"status": "FAIL", "n": 0, "rate": 0.0, "msg": f"{type(e).__name__}: {e}"}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                            "ml/stock_advisor_starter_pack/local_project/src"))
    from core.constants import DEFAULT_RELIANCE_ROOT
    from data.load_symbol_timeframes import load_symbol_timeframes
    datasets = load_symbol_timeframes(DEFAULT_RELIANCE_ROOT, symbol="RELIANCE")
    df = datasets["15m"].frame
    print(_verify(df))
