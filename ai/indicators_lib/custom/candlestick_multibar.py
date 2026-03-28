"""
INDICATOR: Multi-Bar Candlestick Reversal Patterns
Library: Candlestick (pip install candlestick, imports as Pattern)
Patterns: Bullish Engulfing, Bullish Harami (bottom reversal)
          Bearish Engulfing, Bearish Harami (top reversal)

Multi-bar patterns are stronger reversal signals than single-bar patterns.
Signal fires on the confirmation bar (the 2nd bar of the pattern).
Capitalized column names required: Open, High, Low, Close.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns df with bullish_cdl_multibar (1/0) and bearish_cdl_multibar (1/0).
    Combines Engulfing + Harami patterns for multi-bar reversal signals.
    """
    import Pattern

    # Pattern module requires capitalized columns
    work = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    }).copy()

    # Apply 2-bar patterns
    Pattern.Engulfing(work)  # adds SBullEngulf, SBearEngulf
    Pattern.Harami(work)     # adds BullHarami, BearHarami

    bull_mask = work["SBullEngulf"] | work["BullHarami"]
    bear_mask = work["SBearEngulf"] | work["BearHarami"]

    # Where both fire simultaneously (edge case), prefer bull (arbitrary tiebreak)
    bear_mask = bear_mask & ~bull_mask

    out = df.copy()
    out["bullish_cdl_multibar"] = bull_mask.astype(int)
    out["bearish_cdl_multibar"] = bear_mask.astype(int)
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_cdl_multibar"]
        bear = result["bearish_cdl_multibar"]
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
    bull = result["bullish_cdl_multibar"].sum()
    bear = result["bearish_cdl_multibar"].sum()
    print(f"bullish_cdl_multibar: {bull}  bearish_cdl_multibar: {bear}  total_bars: {len(df)}")
