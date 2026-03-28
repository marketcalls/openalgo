"""
INDICATOR: Keltner Channel Cross (edge-triggered)
Library: pyti (D:\test1\opensource_indicators\pyti\)
Signal: bullish when close TRANSITIONS from <= upper band to > upper band (crossing bar only)
        bearish when close TRANSITIONS from >= lower band to < lower band (crossing bar only)
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_LIB_PATH = Path(r"D:\test1\opensource_indicators\pyti")
sys.path.insert(0, str(_LIB_PATH))

DEFAULT_PERIOD = 20


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with bullish_pyti_keltner (1/0) and bearish_pyti_keltner (1/0).
    EDGE-TRIGGER: only the crossing bar gets 1, not every bar already above/below."""
    from pyti.keltner_bands import upper_band, lower_band

    close_l = df["close"].tolist()
    high_l  = df["high"].tolist()
    low_l   = df["low"].tolist()

    ub = upper_band(close_l, high_l, low_l, DEFAULT_PERIOD)
    lb = lower_band(close_l, high_l, low_l, DEFAULT_PERIOD)

    close_arr = np.array(close_l)
    n = len(df)
    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    for i in range(1, n):
        u, u_prev = ub[i], ub[i - 1]
        l, l_prev = lb[i], lb[i - 1]
        c, c_prev = close_arr[i], close_arr[i - 1]
        if np.isnan(u) or np.isnan(u_prev) or np.isnan(l) or np.isnan(l_prev):
            continue
        # Bullish: close was <= upper band, now > upper band (first crossing bar)
        if c > u and c_prev <= u_prev:
            bullish[i] = 1
        # Bearish: close was >= lower band, now < lower band (first crossing bar)
        if c < l and c_prev >= l_prev:
            bearish[i] = 1

    out = df.copy()
    out["bullish_pyti_keltner"] = bullish
    out["bearish_pyti_keltner"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_pyti_keltner"]
        bear = result["bearish_pyti_keltner"]
        assert not (bull & bear).any(), "simultaneous bull+bear signal"
        assert set(bull.unique()).issubset({0, 1}), "bull non-0/1"
        assert set(bear.unique()).issubset({0, 1}), "bear non-0/1"
        assert bull.isna().sum() == 0 and bear.isna().sum() == 0, "NaN in output"
        n = int((bull | bear).sum())
        assert n > 0, "zero signals"
        rate = n / len(df)
        assert rate < 0.30, f"rate {rate:.1%} too high — check edge-trigger logic"
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
