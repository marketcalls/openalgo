"""
INDICATOR: Parabolic SAR Flip
Library: ta-py (D:\test1\opensource_indicators\ta-py\)
Signal: bullish when SAR flips from above to below close, bearish when below to above
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_LIB_PATH = Path(r"D:\test1\opensource_indicators\ta-py")
sys.path.insert(0, str(_LIB_PATH))

DEFAULT_STEP     = 0.02
DEFAULT_MAX_STEP = 0.2


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with bullish_tapy_psar (1/0) and bearish_tapy_psar (1/0)."""
    import ta_py as tap

    # Vectorized array construction (faster than iterrows)
    high_arr = df["high"].to_numpy(dtype=float)
    low_arr  = df["low"].to_numpy(dtype=float)
    hl_pairs = [[high_arr[i], low_arr[i]] for i in range(len(df))]
    sar_vals  = tap.psar(hl_pairs, step=DEFAULT_STEP, maxi=DEFAULT_MAX_STEP)

    close = df["close"].to_numpy(dtype=float)
    n     = len(df)
    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    for i in range(1, n):
        sv, sv_prev = sar_vals[i], sar_vals[i - 1]
        if sv is None or sv_prev is None:
            continue
        s, s_prev = float(sv), float(sv_prev)
        c, c_prev = close[i], close[i - 1]
        # NaN guard on close values
        if np.isnan(c) or np.isnan(c_prev):
            continue
        # Bullish flip: SAR was above price, now below
        if s < c and s_prev >= c_prev:
            bullish[i] = 1
        # Bearish flip: SAR was below price, now above
        elif s > c and s_prev <= c_prev:
            bearish[i] = 1

    out = df.copy()
    out["bullish_tapy_psar"] = bullish
    out["bearish_tapy_psar"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_tapy_psar"]
        bear = result["bearish_tapy_psar"]
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
