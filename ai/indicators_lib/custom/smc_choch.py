"""
INDICATOR: SMC Change of Character (CHoCH)
Source: smart-money-concepts library (joshyattridge)
Signal: bullish CHoCH (market structure flips from bearish to bullish)
        bearish CHoCH (market structure flips from bullish to bearish)

CHoCH is a reversal signal — it marks the FIRST break against the prior trend,
indicating a potential change in market character (direction reversal).
Unlike BOS (continuation), CHoCH signals the end of a trend.

CHoCH on RELIANCE 15m (swing_length=3): ~30-60 signals per 500 bars
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_SWING_LENGTH = 3
DEFAULT_CLOSE_BREAK  = True

_SMC_PATH = Path(r"D:\test1\opensource_indicators\smart-money-concepts\smartmoneyconcepts\smc.py")


def _load_smc():
    """Load SMC library with explicit UTF-8 encoding."""
    with open(_SMC_PATH, "r", encoding="utf-8") as f:
        source = f.read()
    mod = types.ModuleType("_smc_lib")
    mod.__file__ = str(_SMC_PATH)
    exec(compile(source, str(_SMC_PATH), "exec"), mod.__dict__)
    return mod.smc


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds Change of Character (CHoCH) columns to OHLCV DataFrame.

    Output columns (0/1 booleans, adapter-compatible):
      bullish_smc_choch  -- 1 where bullish CHoCH detected  -> adapter: bull -> +1
      bearish_smc_choch  -- 1 where bearish CHoCH detected  -> adapter: bear -> -1
    """
    smc = _load_smc()

    work = df.copy().reset_index(drop=True)
    swing      = smc.swing_highs_lows(work, swing_length=DEFAULT_SWING_LENGTH)
    bos_result = smc.bos_choch(work, swing, close_break=DEFAULT_CLOSE_BREAK)

    # CHOCH column: 1 = bullish CHoCH, -1 = bearish CHoCH, NaN = no signal
    choch = bos_result["CHOCH"].fillna(0)

    out = df.copy().reset_index(drop=True)
    out["bullish_smc_choch"] = (choch == 1).astype(int)
    out["bearish_smc_choch"] = (choch == -1).astype(int)
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_smc_choch"]
        bear = result["bearish_smc_choch"]
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
    bull = result["bullish_smc_choch"].sum()
    bear = result["bearish_smc_choch"].sum()
    print(f"bullish_smc_choch: {bull}  bearish_smc_choch: {bear}  total_bars: {len(df)}")
