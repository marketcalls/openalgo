"""
INDICATOR: Swing Structure Shift (HH/HL/LH/LL)
Source: smartmoneyconcepts library for swing detection + pure-pandas structure logic
Signal: bullish structure shift when a Higher Low (HL) forms after a Lower Low (LL)
        -- first sign that downtrend is ending
        bearish structure shift when a Lower High (LH) forms after a Higher High (HH)
        -- first sign that uptrend is ending

Logic:
  1. Use smc.swing_highs_lows() to find confirmed swing highs and lows (swing_length=3)
  2. Track last 2 swing highs -> HH if current > prior, LH if current < prior
  3. Track last 2 swing lows  -> HL if current > prior, LL if current < prior
  4. Bullish: first HL after a LL sequence (prior swing low was LL, current is HL)
  5. Bearish: first LH after a HH sequence (prior swing high was HH, current is LH)

Signals fire at the confirmed swing point bar (no future lookahead).
"""
import sys
import types
from pathlib import Path
import numpy as np
import pandas as pd

_SMC_PATH = Path(r"D:\test1\opensource_indicators\smart-money-concepts\smartmoneyconcepts\smc.py")


def _load_smc():
    """Load SMC library with explicit UTF-8 encoding."""
    with open(_SMC_PATH, "r", encoding="utf-8") as f:
        source = f.read()
    mod = types.ModuleType("_smc_lib")
    mod.__file__ = str(_SMC_PATH)
    exec(compile(source, str(_SMC_PATH), "exec"), mod.__dict__)
    return mod.smc


DEFAULT_SWING_LENGTH = 3


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns df with bullish_swing_structure (1/0) and bearish_swing_structure (1/0).
    Bullish = HL after LL (structure shift up); Bearish = LH after HH (structure shift down).
    """
    smc = _load_smc()

    work = df.copy().reset_index(drop=True)
    swing = smc.swing_highs_lows(work, swing_length=DEFAULT_SWING_LENGTH)
    # swing["HighLow"]: 1 = swing high, -1 = swing low, NaN = neither

    n = len(df)
    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    swing_hl = swing["HighLow"].fillna(0).values

    # Collect swing high indices and prices
    swing_high_idxs = []
    swing_low_idxs  = []

    high_arr = df["high"].values
    low_arr  = df["low"].values

    for i in range(n):
        if swing_hl[i] == 1:
            swing_high_idxs.append(i)
        elif swing_hl[i] == -1:
            swing_low_idxs.append(i)

    # Track structure shifts for swing highs (HH -> LH = bearish shift)
    prev_sh_price = None
    prev_sh_type  = None  # "HH" or "LH"

    for idx in swing_high_idxs:
        price = high_arr[idx]
        if prev_sh_price is None:
            prev_sh_price = price
            prev_sh_type  = None
            continue
        if price > prev_sh_price:
            curr_type = "HH"
        else:
            curr_type = "LH"
        # Bearish structure shift: first LH after a HH
        if curr_type == "LH" and prev_sh_type == "HH":
            bearish[idx] = 1
        prev_sh_price = price
        prev_sh_type  = curr_type

    # Track structure shifts for swing lows (LL -> HL = bullish shift)
    prev_sl_price = None
    prev_sl_type  = None  # "HL" or "LL"

    for idx in swing_low_idxs:
        price = low_arr[idx]
        if prev_sl_price is None:
            prev_sl_price = price
            prev_sl_type  = None
            continue
        if price > prev_sl_price:
            curr_type = "HL"
        else:
            curr_type = "LL"
        # Bullish structure shift: first HL after a LL
        if curr_type == "HL" and prev_sl_type == "LL":
            bullish[idx] = 1
        prev_sl_price = price
        prev_sl_type  = curr_type

    out = df.copy().reset_index(drop=True)
    out["bullish_swing_structure"] = bullish
    out["bearish_swing_structure"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_swing_structure"]
        bear = result["bearish_swing_structure"]
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
    bull = result["bullish_swing_structure"].sum()
    bear = result["bearish_swing_structure"].sum()
    print(f"bullish_swing_structure: {bull}  bearish_swing_structure: {bear}  total_bars: {len(df)}")
