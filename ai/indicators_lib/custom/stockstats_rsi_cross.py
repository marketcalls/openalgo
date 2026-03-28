"""
INDICATOR: RSI 30/70 Cross
Library: stockstats (D:\test1\opensource_indicators\stockstats\)
Signal: bullish when RSI(14) rises through 30, bearish when falls through 70
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_LIB_PATH = Path(r"D:\test1\opensource_indicators\stockstats")
sys.path.insert(0, str(_LIB_PATH))

DEFAULT_RSI_PERIOD  = 14
DEFAULT_OVERSOLD    = 30
DEFAULT_OVERBOUGHT  = 70


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with bullish_stockstats_rsi (1/0) and bearish_stockstats_rsi (1/0)."""
    from stockstats import StockDataFrame

    work = df[["open", "high", "low", "close", "volume"]].copy()
    sdf  = StockDataFrame.retype(work)
    rsi  = sdf[f"rsi_{DEFAULT_RSI_PERIOD}"].values

    n = len(df)
    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    for i in range(1, n):
        if np.isnan(rsi[i]) or np.isnan(rsi[i - 1]):
            continue
        # Bullish: RSI rises through 30 (oversold exit)
        if rsi[i] > DEFAULT_OVERSOLD and rsi[i - 1] <= DEFAULT_OVERSOLD:
            bullish[i] = 1
        # Bearish: RSI falls through 70 (overbought exit)
        elif rsi[i] < DEFAULT_OVERBOUGHT and rsi[i - 1] >= DEFAULT_OVERBOUGHT:
            bearish[i] = 1

    out = df.copy()
    out["bullish_stockstats_rsi"] = bullish
    out["bearish_stockstats_rsi"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_stockstats_rsi"]
        bear = result["bearish_stockstats_rsi"]
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
