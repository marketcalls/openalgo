"""
INDICATOR: Ichimoku TK Cross
Library: trading-technical-indicators (D:\test1\opensource_indicators\trading-technical-indicators\)
Signal: bullish when Tenkan-sen crosses above Kijun-sen, bearish when crosses below
Note: tti ParabolicSAR has read-only NumPy bug -- Ichimoku used instead.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_LIB_PATH = Path(r"D:\test1\opensource_indicators\trading-technical-indicators")
sys.path.insert(0, str(_LIB_PATH))


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with bullish_tti_ichimoku (1/0) and bearish_tti_ichimoku (1/0)."""
    import tti.indicators as ti

    # tti requires capitalized column names and DatetimeIndex
    work = df[["open", "high", "low", "close", "volume"]].copy()
    work.columns = ["Open", "High", "Low", "Close", "Volume"]

    if "datetime" in df.columns:
        work.index = pd.to_datetime(df["datetime"].values)
    else:
        work.index = pd.date_range("2020-01-01", periods=len(df), freq="15min")

    cloud   = ti.IchimokuCloud(work)
    ti_data = cloud.getTiData()  # DataFrame indexed by same DatetimeIndex

    # Align output to input by reindexing (handles warmup NaN rows)
    tenkan = ti_data["tenkan_sen"].reindex(work.index).values
    kijun  = ti_data["kijun_sen"].reindex(work.index).values

    n = len(df)
    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    for i in range(1, n):
        t, t_prev = tenkan[i], tenkan[i - 1]
        k, k_prev = kijun[i],  kijun[i - 1]
        if any(np.isnan(v) for v in [t, t_prev, k, k_prev]):
            continue
        if t > k and t_prev <= k_prev:   # Tenkan crosses above Kijun
            bullish[i] = 1
        elif t < k and t_prev >= k_prev: # Tenkan crosses below Kijun
            bearish[i] = 1

    out = df.copy()
    out["bullish_tti_ichimoku"] = bullish
    out["bearish_tti_ichimoku"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_tti_ichimoku"]
        bear = result["bearish_tti_ichimoku"]
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
