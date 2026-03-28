"""
INDICATOR: Chandelier Exit Crossover
Library: finta (D:\test1\opensource_indicators\finta\)
Signal: bullish when close crosses above Chandelier Long stop, bearish when crosses below Short stop
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_LIB_PATH = Path(r"D:\test1\opensource_indicators\finta")
sys.path.insert(0, str(_LIB_PATH))


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with bullish_finta_chandelier (1/0) and bearish_finta_chandelier (1/0)."""
    from finta import TA

    # finta requires capitalized column names
    work = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })

    chandelier = TA.CHANDELIER(work)
    # Output columns: "Long." (long stop) and "Short." (short stop)
    long_arr  = chandelier["Long."].values
    short_arr = chandelier["Short."].values
    close     = df["close"].values

    n = len(df)
    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    for i in range(1, n):
        if np.isnan(long_arr[i]) or np.isnan(long_arr[i - 1]):
            continue
        if np.isnan(short_arr[i]) or np.isnan(short_arr[i - 1]):
            continue
        # Bullish: close crosses above Long stop
        if close[i] > long_arr[i] and close[i - 1] <= long_arr[i - 1]:
            bullish[i] = 1
        # Bearish: close crosses below Short stop (only if not also bullish)
        if close[i] < short_arr[i] and close[i - 1] >= short_arr[i - 1]:
            if not bullish[i]:  # tiebreak: prefer bull
                bearish[i] = 1

    out = df.copy()
    out["bullish_finta_chandelier"] = bullish
    out["bearish_finta_chandelier"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_finta_chandelier"]
        bear = result["bearish_finta_chandelier"]
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
