"""
INDICATOR: Market Profile Value Area Breakout
Library: py-market-profile (D:\test1\opensource_indicators\py-market-profile\src\)
Signal: bullish when close breaks above prior session's VAH; bearish when breaks below VAL
Rules:
  - First session: no prior -> 0 for all bars
  - Prior session with <20 bars: 0 for current session
  - Calendar gap >7 days: 0 (stale level)
  - Edge-triggered: only the first crossing bar fires
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

_LIB_PATH = Path(r"D:\test1\opensource_indicators\py-market-profile\src")
sys.path.insert(0, str(_LIB_PATH))

TICK_SIZE         = 0.05
MIN_SESSION_BARS  = 20
MAX_GAP_CALENDAR  = 7   # calendar days proxy for >5 trading days


def _compute_va(sess_df: pd.DataFrame):
    """Compute (val, vah) for session DataFrame. Returns (None, None) on error."""
    from market_profile import MarketProfile
    try:
        mp = MarketProfile(sess_df, tick_size=TICK_SIZE, mode="vol")
        # Slice using the full session range (DatetimeIndex labels)
        sl = mp[sess_df.index[0]:sess_df.index[-1]]
        val, vah = sl.value_area   # returns (VAL_price, VAH_price)
        if val is None or vah is None:
            return None, None
        return float(val), float(vah)
    except Exception:
        return None, None


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Returns df with bullish_mp_va (1/0) and bearish_mp_va (1/0)."""
    # Build working copy with capitalized columns required by py-market-profile
    work = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })

    # Attach DatetimeIndex so MarketProfile slicing works
    if "datetime" in df.columns:
        dt_idx = pd.to_datetime(df["datetime"].values)
    else:
        dt_idx = pd.date_range("2020-01-01", periods=len(df), freq="15min")
    work.index = dt_idx
    work["_date"] = dt_idx.normalize()   # calendar date for grouping

    sessions = sorted(work["_date"].unique())
    n = len(df)
    bullish = np.zeros(n, dtype=int)
    bearish = np.zeros(n, dtype=int)

    prev_val  = None
    prev_vah  = None
    prev_date = None
    prev_len  = 0

    for s_idx, sess_date in enumerate(sessions):
        sess_mask    = work["_date"] == sess_date
        sess_indices = np.where(sess_mask.values)[0]
        sess_df      = work[sess_mask].drop(columns=["_date"])

        if s_idx == 0:
            # No prior session -> store this session's profile, output 0
            prev_val, prev_vah = _compute_va(sess_df)
            prev_date = sess_date
            prev_len  = len(sess_df)
            continue

        # Staleness check
        gap_days = (sess_date - prev_date).days
        if gap_days > MAX_GAP_CALENDAR:
            prev_val, prev_vah = _compute_va(sess_df)
            prev_date = sess_date
            prev_len  = len(sess_df)
            continue

        # Partial prior session check
        if prev_len < MIN_SESSION_BARS or prev_val is None or prev_vah is None:
            prev_val, prev_vah = _compute_va(sess_df)
            prev_date = sess_date
            prev_len  = len(sess_df)
            continue

        # Apply edge-triggered VAH/VAL signals to this session's bars
        above_vah = False
        below_val = False
        close_arr = df["close"].values

        for j, idx in enumerate(sess_indices):
            c = close_arr[idx]
            if j == 0:
                above_vah = c > prev_vah
                below_val = c < prev_val
            else:
                now_above = c > prev_vah
                now_below = c < prev_val
                if now_above and not above_vah:
                    bullish[idx] = 1
                if now_below and not below_val:
                    bearish[idx] = 1
                above_vah = now_above
                below_val = now_below

        prev_val, prev_vah = _compute_va(sess_df)
        prev_date = sess_date
        prev_len  = len(sess_df)

    out = df.copy()
    out["bullish_mp_va"] = bullish
    out["bearish_mp_va"] = bearish
    return out


def _verify(df: pd.DataFrame) -> dict:
    try:
        result = calculate_indicators(df)
        bull = result["bullish_mp_va"]
        bear = result["bearish_mp_va"]
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
