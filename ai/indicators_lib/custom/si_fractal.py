"""
INDICATOR: Williams Fractal
Library: stock-indicators-python (D:\test1\opensource_indicators\stock-indicators-python\)
Requires: .NET 8.0 runtime
Signal: bullish at swing low fractal (left_span=5), bearish at swing high fractal
"""
import sys
from pathlib import Path
from datetime import datetime
import numpy as np
import pandas as pd

_LIB_PATH = Path(r"D:\test1\opensource_indicators\stock-indicators-python")
sys.path.insert(0, str(_LIB_PATH))

DEFAULT_LEFT_SPAN = 5


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with bullish_si_fractal (1/0) and bearish_si_fractal (1/0).
    fractal_bull = non-None -> bullish (local swing low confirmed).
    fractal_bear = non-None -> bearish (local swing high confirmed).
    """
    from stock_indicators import indicators, Quote

    # Build Quote list. Dates must be datetime.datetime instances.
    if "datetime" in df.columns:
        raw_dates = pd.to_datetime(df["datetime"])
        if raw_dates.dt.tz is not None:
            # Convert IST (or any tz) to naive UTC
            dates_utc = raw_dates.dt.tz_convert("UTC").dt.tz_localize(None).tolist()
        else:
            dates_utc = raw_dates.tolist()
    else:
        dates_utc = [
            datetime(2020, 1, 1) + pd.Timedelta(minutes=15 * i)
            for i in range(len(df))
        ]

    quotes = [
        Quote(
            date=dates_utc[i],
            open=float(df["open"].iloc[i]),
            high=float(df["high"].iloc[i]),
            low=float(df["low"].iloc[i]),
            close=float(df["close"].iloc[i]),
            volume=float(df["volume"].iloc[i]) if "volume" in df.columns else 0.0,
        )
        for i in range(len(df))
    ]

    fractal_results = indicators.get_fractal(quotes, left_span=DEFAULT_LEFT_SPAN)

    n = len(df)
    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    # LOOKAHEAD FIX: Williams Fractal at bar i is only confirmed after DEFAULT_LEFT_SPAN
    # right-side bars (right_span = left_span by default). Place signal at i + left_span
    # (the bar when confirmation is FIRST knowable), not at the pivot bar i.
    for i, fr in enumerate(fractal_results):
        if i >= n:
            break
        target = min(i + DEFAULT_LEFT_SPAN, n - 1)
        if fr.fractal_bull is not None:  # non-None = fractal confirmed
            bullish[target] = 1
        if fr.fractal_bear is not None:
            bearish[target] = 1

    out = df.copy()
    out["bullish_si_fractal"] = bullish
    out["bearish_si_fractal"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_si_fractal"]
        bear = result["bearish_si_fractal"]
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
