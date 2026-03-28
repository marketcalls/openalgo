"""
INDICATOR: Candlestick Engulfing Pattern
Library: pandas-ta-classic (D:\test1\opensource_indicators\pandas-ta-classic\)
Signal: bullish engulfing (+1) or bearish engulfing (-1) candle pattern
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_LIB_PATH = Path(r"D:\test1\opensource_indicators\pandas-ta-classic")
sys.path.insert(0, str(_LIB_PATH))


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with bullish_pandas_ta_cdl (1/0) and bearish_pandas_ta_cdl (1/0)."""
    import pandas_ta_classic  # registers .ta accessor on pd.DataFrame (lowercase columns)

    work = df[["open", "high", "low", "close"]].copy()
    result = work.ta.cdl_pattern(name="engulfing")
    cdl = result["CDL_ENGULFING"].fillna(0)

    out = df.copy()
    out["bullish_pandas_ta_cdl"] = (cdl > 0).astype(int)
    out["bearish_pandas_ta_cdl"] = (cdl < 0).astype(int)
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_pandas_ta_cdl"]
        bear = result["bearish_pandas_ta_cdl"]
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
