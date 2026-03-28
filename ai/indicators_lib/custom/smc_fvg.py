"""
# ============================================================
# INDICATOR: SMC Fair Value Gap (FVG)
# Source: smart-money-concepts library (joshyattridge)
# ============================================================
# A Fair Value Gap forms when three consecutive candles create a price gap:
#   Bullish FVG: high[i-1] < low[i+1] AND candle[i] is bullish  → price likely fills gap by going up
#   Bearish FVG: low[i-1] > high[i+1] AND candle[i] is bearish  → price likely fills gap by going down
#
# NOTE: FVG detection uses bar i+1 data (1-bar pattern overlap). The signal is placed at bar i.
# ============================================================
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

# -- PARAMETERS -------------------------------------------------------------
DEFAULT_SWING_LENGTH = 3          # Not used by FVG directly, but kept for consistency
DEFAULT_JOIN_CONSECUTIVE = False  # Merge consecutive FVGs into one larger gap

_SMC_PATH = Path(r"D:\test1\opensource_indicators\smart-money-concepts\smartmoneyconcepts\smc.py")


def _load_smc():
    """Load SMC library with explicit UTF-8 encoding (handles Unicode in source)."""
    with open(_SMC_PATH, "r", encoding="utf-8") as f:
        source = f.read()
    mod = types.ModuleType("_smc_lib")
    mod.__file__ = str(_SMC_PATH)
    exec(compile(source, str(_SMC_PATH), "exec"), mod.__dict__)
    return mod.smc


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds Fair Value Gap columns to OHLCV DataFrame.

    Output columns (0/1 booleans, adapter-compatible):
      bullish_fvg  — 1 where a bullish FVG was detected  → adapter: bull → +1
      bearish_fvg  — 1 where a bearish FVG was detected  → adapter: bear → -1
    """
    smc = _load_smc()

    # SMC expects integer-indexed DataFrame
    work = df.copy().reset_index(drop=True)

    fvg_result = smc.fvg(work, join_consecutive=DEFAULT_JOIN_CONSECUTIVE)

    out = df.copy().reset_index(drop=True)
    out["bullish_fvg"] = (fvg_result["FVG"] == 1).astype(int)
    out["bearish_fvg"] = (fvg_result["FVG"] == -1).astype(int)

    return out


if __name__ == "__main__":
    # Quick self-test
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                            "ml/stock_advisor_starter_pack/local_project/src"))
    from core.constants import DEFAULT_RELIANCE_ROOT
    from data.load_symbol_timeframes import load_symbol_timeframes
    datasets = load_symbol_timeframes(DEFAULT_RELIANCE_ROOT, symbol="RELIANCE")
    df = datasets["15m"].frame
    result = calculate_indicators(df)
    bull = result["bullish_fvg"].sum()
    bear = result["bearish_fvg"].sum()
    print(f"bullish_fvg: {bull}  bearish_fvg: {bear}  total_bars: {len(df)}")
