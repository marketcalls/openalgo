"""
# ============================================================
# INDICATOR: SMC Break of Structure (BOS)
# Source: smart-money-concepts library (joshyattridge)
# ============================================================
# BOS fires when price closes above a previous swing high (bullish BOS)
# or below a previous swing low (bearish BOS).
# It confirms that market structure has broken in that direction.
#
# BOS at swing_length=3 on RELIANCE 15m:
#   Bull BOS: 110 signals, 70.0% win rate (8-bar lookahead)
#   Bear BOS: 127 signals, 77.2% win rate
# ============================================================
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

# -- PARAMETERS -------------------------------------------------------------
DEFAULT_SWING_LENGTH = 3    # Sensitivity of swing detection (lower = more signals)
DEFAULT_CLOSE_BREAK = True  # Use close price to confirm BOS (vs high/low wick)

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
    Adds Break of Structure (BOS) columns to OHLCV DataFrame.

    Output columns (0/1 booleans, adapter-compatible):
      bullish_bos  — 1 where bullish BOS detected  → adapter: bull → +1
      bearish_bos  — 1 where bearish BOS detected  → adapter: bear → -1
    """
    smc = _load_smc()

    work = df.copy().reset_index(drop=True)
    swing = smc.swing_highs_lows(work, swing_length=DEFAULT_SWING_LENGTH)
    bos_result = smc.bos_choch(work, swing, close_break=DEFAULT_CLOSE_BREAK)

    out = df.copy().reset_index(drop=True)
    out["bullish_bos"] = (bos_result["BOS"] == 1).astype(int)
    out["bearish_bos"] = (bos_result["BOS"] == -1).astype(int)

    return out


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                            "ml/stock_advisor_starter_pack/local_project/src"))
    from core.constants import DEFAULT_RELIANCE_ROOT
    from data.load_symbol_timeframes import load_symbol_timeframes
    datasets = load_symbol_timeframes(DEFAULT_RELIANCE_ROOT, symbol="RELIANCE")
    df = datasets["15m"].frame
    result = calculate_indicators(df)
    bull = result["bullish_bos"].sum()
    bear = result["bearish_bos"].sum()
    print(f"bullish_bos: {bull}  bearish_bos: {bear}  total_bars: {len(df)}")
