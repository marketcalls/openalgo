"""
INDICATOR: MACD Signal Line Cross
Library: ta-library (D:\test1\opensource_indicators\ta-library\)
Signal: bullish when MACD line crosses above signal line, bearish when crosses below
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_LIB_PATH = Path(r"D:\test1\opensource_indicators\ta-library")
sys.path.insert(0, str(_LIB_PATH))

DEFAULT_FAST   = 12
DEFAULT_SLOW   = 26
DEFAULT_SIGNAL = 9


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with bullish_ta_macd (1/0) and bearish_ta_macd (1/0)."""
    import ta

    close = df["close"]
    macd_obj    = ta.trend.MACD(
        close,
        window_fast=DEFAULT_FAST,
        window_slow=DEFAULT_SLOW,
        window_sign=DEFAULT_SIGNAL,
    )
    macd_line   = macd_obj.macd().values
    signal_line = macd_obj.macd_signal().values

    n = len(df)
    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    for i in range(1, n):
        if any(np.isnan(v) for v in [macd_line[i], signal_line[i],
                                      macd_line[i-1], signal_line[i-1]]):
            continue
        if macd_line[i] > signal_line[i] and macd_line[i-1] <= signal_line[i-1]:
            bullish[i] = 1
        elif macd_line[i] < signal_line[i] and macd_line[i-1] >= signal_line[i-1]:
            bearish[i] = 1

    out = df.copy()
    out["bullish_ta_macd"] = bullish
    out["bearish_ta_macd"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_ta_macd"]
        bear = result["bearish_ta_macd"]
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
