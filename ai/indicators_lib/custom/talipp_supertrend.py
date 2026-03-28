"""
INDICATOR: SuperTrend Direction Flip
Library: talipp (D:\test1\opensource_indicators\talipp\)
Signal: bullish when SuperTrend flips DOWN->UP, bearish when UP->DOWN
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_LIB_PATH = Path(r"D:\test1\opensource_indicators\talipp")
sys.path.insert(0, str(_LIB_PATH))

DEFAULT_MULT       = 3.0
DEFAULT_ATR_PERIOD = 7


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with bullish_talipp_supertrend (1/0) and bearish_talipp_supertrend (1/0)."""
    from talipp.indicators import SuperTrend
    from talipp.ohlcv import OHLCV
    from talipp.indicators.SuperTrend import Trend

    ohlcv_list = [
        OHLCV(
            open=float(df["open"].iloc[i]),
            high=float(df["high"].iloc[i]),
            low=float(df["low"].iloc[i]),
            close=float(df["close"].iloc[i]),
        )
        for i in range(len(df))
    ]

    st = SuperTrend(
        atr_period=DEFAULT_ATR_PERIOD,
        mult=DEFAULT_MULT,
        input_values=ohlcv_list,
    )

    trends = []
    for r in st:
        if r is None:
            trends.append(None)
        else:
            trends.append(r.trend)  # Trend.UP (bullish) or Trend.DOWN (bearish)

    n = len(df)
    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    from talipp.indicators.SuperTrend import Trend as _Trend
    for i in range(1, n):
        prev, curr = trends[i - 1], trends[i]
        if prev is None or curr is None:
            continue
        if curr == _Trend.UP and prev == _Trend.DOWN:    # DOWN -> UP flip
            bullish[i] = 1
        elif curr == _Trend.DOWN and prev == _Trend.UP:  # UP -> DOWN flip
            bearish[i] = 1

    out = df.copy()
    out["bullish_talipp_supertrend"] = bullish
    out["bearish_talipp_supertrend"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_talipp_supertrend"]
        bear = result["bearish_talipp_supertrend"]
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
