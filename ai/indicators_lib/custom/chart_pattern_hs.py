"""
INDICATOR: Head and Shoulders / Inverse Head and Shoulders
Library: tradingpatterns (pip install tradingpattern, imports as tradingpatterns)
Signal: Inverse H&S -> bullish reversal (bottom pattern)
        H&S -> bearish reversal (top pattern)

Lookahead fix: the library's detect_head_shoulder() uses shift(-1) for confirmation.
We shift the output signal by +1 bar so it only fires AFTER the next bar confirms,
making it suitable for live use (signal fires on bar i+1, based on pattern at bar i).

Pattern uses rolling window=3 over High/Low to find the head (highest/lowest point).
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns df with bullish_chart_hs (1/0) and bearish_chart_hs (1/0).
    Signal shifted by 1 bar to remove lookahead from detect_head_shoulder().
    """
    from tradingpatterns.tradingpatterns import detect_head_shoulder

    # tradingpatterns requires capitalized High, Low, Close columns
    work = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    }).copy()

    work = detect_head_shoulder(work, window=3)

    # The library output uses strings -- convert to int signals
    # 'Inverse Head and Shoulder' -> bullish reversal (bottom)
    # 'Head and Shoulder' -> bearish reversal (top)
    hs_col = work["head_shoulder_pattern"]
    raw_bull = (hs_col == "Inverse Head and Shoulder").astype(int)
    raw_bear = (hs_col == "Head and Shoulder").astype(int)

    # Shift by 1 bar to avoid lookahead (library uses shift(-1) for confirmation)
    bull_shifted = raw_bull.shift(1).fillna(0).astype(int)
    bear_shifted = raw_bear.shift(1).fillna(0).astype(int)

    # Where both fire simultaneously, prefer bull
    bear_shifted = bear_shifted & ~bull_shifted

    out = df.copy()
    out["bullish_chart_hs"] = bull_shifted.values
    out["bearish_chart_hs"] = bear_shifted.values
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_chart_hs"]
        bear = result["bearish_chart_hs"]
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
    result = calculate_indicators(df)
    bull = result["bullish_chart_hs"].sum()
    bear = result["bearish_chart_hs"].sum()
    print(f"bullish_chart_hs: {bull}  bearish_chart_hs: {bear}  total_bars: {len(df)}")
