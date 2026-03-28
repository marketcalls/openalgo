"""
# ============================================================
# INDICATOR: SMC Order Blocks (OB)
# Source: smart-money-concepts library (joshyattridge)
# ============================================================
# An Order Block (OB) is a specific candle where institutional orders were placed.
# It forms when price breaks above a swing high (bullish OB) or below a swing low (bearish OB).
# The OB is the last bearish candle before a bullish move (or last bullish candle before a bearish move).
#
# Order Blocks on RELIANCE 15m (swing_length=3):
#   Bull OB: 11 signals, 100.0% win rate (small sample!)
#   Bear OB: 11 signals,  90.9% win rate (small sample!)
# ============================================================
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

# -- PARAMETERS -------------------------------------------------------------
DEFAULT_SWING_LENGTH = 3      # Sensitivity of swing detection
DEFAULT_CLOSE_MITIGATION = False  # If True, OB mitigated only when close crosses it (stricter)

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
    Adds Order Block (OB) columns to OHLCV DataFrame.

    Output columns (0/1 booleans, adapter-compatible):
      bullish_ob  — 1 where bullish OB detected  → adapter: bull → +1
      bearish_ob  — 1 where bearish OB detected  → adapter: bear → -1
    """
    smc = _load_smc()

    work = df.copy().reset_index(drop=True)
    swing = smc.swing_highs_lows(work, swing_length=DEFAULT_SWING_LENGTH)
    ob_result = smc.ob(work, swing, close_mitigation=DEFAULT_CLOSE_MITIGATION)

    out = df.copy().reset_index(drop=True)
    out["bullish_ob"] = (ob_result["OB"] == 1).astype(int)
    out["bearish_ob"] = (ob_result["OB"] == -1).astype(int)

    return out


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                            "ml/stock_advisor_starter_pack/local_project/src"))
    from core.constants import DEFAULT_RELIANCE_ROOT
    from data.load_symbol_timeframes import load_symbol_timeframes
    datasets = load_symbol_timeframes(DEFAULT_RELIANCE_ROOT, symbol="RELIANCE")
    df = datasets["15m"].frame
    result = calculate_indicators(df)
    bull = result["bullish_ob"].sum()
    bear = result["bearish_ob"].sum()
    print(f"bullish_ob: {bull}  bearish_ob: {bear}  total_bars: {len(df)}")
