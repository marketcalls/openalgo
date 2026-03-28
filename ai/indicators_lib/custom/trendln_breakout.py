"""
INDICATOR: Trend Line Breakout
Library: trendln (D:\test1\opensource_indicators\trendln\)
Signal: bullish when close crosses above rolling resistance trend line,
        bearish when crosses below rolling support trend line
Logic: rolling 125-bar window, accuracy=2 (must be even per findiff API)
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_LIB_PATH = Path(r"D:\test1\opensource_indicators\trendln")
sys.path.insert(0, str(_LIB_PATH))

DEFAULT_WINDOW   = 125
DEFAULT_ACCURACY = 2   # must be even integer (findiff requirement)


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with bullish_trendln (1/0) and bearish_trendln (1/0).

    For bar i, window = close[i-125:i] (bars i-125 to i-1, 125 bars).
    Support/resistance line value = slope*(W-1) + intercept (last bar of window).
    Edge-triggered: only the bar where close first crosses the line fires.
    """
    import trendln

    close = df["close"].values
    n = len(df)
    W = DEFAULT_WINDOW

    support_vals  = []  # support level per bar, starting from bar W
    resist_vals   = []  # resistance level per bar, starting from bar W

    for i in range(W, n):
        window = close[i - W: i].tolist()
        try:
            (_, pmin, _, _), (_, pmax, _, _) = trendln.calc_support_resistance(
                window, accuracy=DEFAULT_ACCURACY
            )
            sup = pmin[0] * (W - 1) + pmin[1] if not np.isnan(pmin[0]) else np.nan
            res = pmax[0] * (W - 1) + pmax[1] if not np.isnan(pmax[0]) else np.nan
        except Exception:
            sup, res = np.nan, np.nan
        support_vals.append(sup)
        resist_vals.append(res)

    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    for j in range(1, len(support_vals)):
        i     = j + W          # bar index in df
        c     = close[i]
        c_prev = close[i - 1]
        s, s_prev = support_vals[j], support_vals[j - 1]
        r, r_prev = resist_vals[j], resist_vals[j - 1]
        # Bullish: close crosses above resistance line
        if not np.isnan(r) and not np.isnan(r_prev):
            if c > r and c_prev <= r_prev:
                bullish[i] = 1
        # Bearish: close crosses below support line (elif prevents simultaneous bull+bear)
        elif not np.isnan(s) and not np.isnan(s_prev):
            if c < s and c_prev >= s_prev:
                bearish[i] = 1

    out = df.copy()
    out["bullish_trendln"] = bullish
    out["bearish_trendln"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_trendln"]
        bear = result["bearish_trendln"]
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
    df = datasets["15m"].frame.iloc[:500]   # use 500-bar subset (slow on full set)
    print(_verify(df))
