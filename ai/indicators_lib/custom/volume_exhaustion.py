"""
INDICATOR: Volume Exhaustion Reversal
Source: Pure pandas (no external library required)
Signal: bullish when a volume spike (z-score > 2.0) coincides with a downward price bar
        that is immediately followed by a higher close (buying exhaustion at bottom)
        bearish when a volume spike coincides with an upward price bar followed by
        a lower close (selling exhaustion at top)

Pattern: "Volume Exhaustion" is when an extreme-volume bar (z > 2 sd above 20-bar mean)
occurs in the direction of the trend (down bar for bearish move, up bar for bull move)
but the NEXT bar reverses direction -- suggesting the move is exhausted.

This is a repeating reversal pattern used in VSA (Volume Spread Analysis):
- Climactic selling: high vol + down close bar + next bar closes higher -> buy
- Climactic buying:  high vol + up close bar + next bar closes lower  -> sell

Signal fires on the bar AFTER the exhaustion bar (i.e., the reversal confirmation bar).
No lookahead: uses only past volume data for z-score, signal fires on confirmed reversal bar.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

DEFAULT_VOL_WINDOW   = 20    # bars for rolling mean/std of volume
DEFAULT_Z_THRESHOLD  = 2.0   # z-score above this = volume spike


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns df with bullish_vol_exhaustion (1/0) and bearish_vol_exhaustion (1/0).
    Signal fires on bar i (reversal bar), based on bar i-1 (exhaustion bar).
    """
    close  = df["close"].values
    volume = df["volume"].values
    n      = len(df)

    # Rolling z-score of volume (past-only: mean/std from bars [i-W, i-1])
    vol_mean = pd.Series(volume).rolling(DEFAULT_VOL_WINDOW, min_periods=DEFAULT_VOL_WINDOW).mean().values
    vol_std  = pd.Series(volume).rolling(DEFAULT_VOL_WINDOW, min_periods=DEFAULT_VOL_WINDOW).std().values

    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    for i in range(1, n):
        # Check bar i-1 for exhaustion
        m = vol_mean[i - 1]
        s = vol_std[i - 1]
        if np.isnan(m) or np.isnan(s) or s < 1e-9:
            continue

        v_prev = volume[i - 1]
        z      = (v_prev - m) / s

        if z < DEFAULT_Z_THRESHOLD:
            continue  # not a volume spike

        c_prev = close[i - 1]
        c_pprev = close[i - 2] if i >= 2 else c_prev
        c_curr = close[i]

        # Bar i-1 is a DOWN bar (close < previous close) -- bearish exhaustion candle
        if c_prev < c_pprev:
            # Bar i reverses up (closes higher than bar i-1) -> bullish exhaustion
            if c_curr > c_prev:
                bullish[i] = 1

        # Bar i-1 is an UP bar (close > previous close) -- bullish exhaustion candle
        elif c_prev > c_pprev:
            # Bar i reverses down (closes lower than bar i-1) -> bearish exhaustion
            if c_curr < c_prev:
                bearish[i] = 1

    out = df.copy()
    out["bullish_vol_exhaustion"] = bullish
    out["bearish_vol_exhaustion"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_vol_exhaustion"]
        bear = result["bearish_vol_exhaustion"]
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
    bull = result["bullish_vol_exhaustion"].sum()
    bear = result["bearish_vol_exhaustion"].sum()
    print(f"bullish_vol_exhaustion: {bull}  bearish_vol_exhaustion: {bear}  total_bars: {len(df)}")
