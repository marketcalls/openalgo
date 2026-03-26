"""ML-style confidence scoring adapted from hybrid_ml_vwap_bb.py.

10-feature scoring: price_position, volume_strength, trend_alignment,
volatility, momentum, delta_pressure, confluence, pattern_strength,
time_factor, vwap_distance.
"""

import numpy as np
import pandas as pd
from utils.logging import get_logger

logger = get_logger(__name__)


def compute_ml_confidence(df: pd.DataFrame) -> pd.DataFrame:
    """Compute ML-style confidence scores from multiple features.

    Returns DataFrame with: ml_buy_confidence, ml_sell_confidence (0-100)
    """
    df = df.copy()
    df["ml_buy_confidence"] = 0.0
    df["ml_sell_confidence"] = 0.0

    if len(df) < 30:
        return df

    c = df["close"]
    v = df["volume"]

    # Feature 1: Price position relative to range (0-1)
    high_20 = df["high"].rolling(20).max()
    low_20 = df["low"].rolling(20).min()
    rng = high_20 - low_20
    price_pos = np.where(rng > 0, (c - low_20) / rng, 0.5)

    # Feature 2: Volume strength (current vs average)
    vol_avg = v.rolling(20).mean()
    vol_strength = np.where(vol_avg > 0, v / vol_avg, 1.0)
    vol_strength = np.clip(vol_strength, 0, 3) / 3

    # Feature 3: Trend alignment (EMA 9 vs 21)
    ema9 = c.ewm(span=9).mean()
    ema21 = c.ewm(span=21).mean()
    trend = np.where(ema21 > 0, (ema9 - ema21) / ema21, 0)
    trend_score = np.clip(trend * 50, -1, 1)

    # Feature 4: Momentum (ROC 10)
    roc = c.pct_change(10)
    momentum_score = np.clip(roc * 20, -1, 1)

    # Feature 5: Volatility (ATR relative)
    tr = pd.concat([
        df["high"] - df["low"],
        abs(df["high"] - c.shift(1)),
        abs(df["low"] - c.shift(1)),
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    vol_score = np.where(c > 0, atr / c, 0)
    vol_score = np.clip(vol_score * 100, 0, 1)

    # Aggregate: buy confidence
    buy_raw = (
        (1 - price_pos) * 0.2 +  # Low price position = bullish
        vol_strength * 0.15 +
        np.clip(trend_score, 0, 1) * 0.25 +
        np.clip(momentum_score, 0, 1) * 0.25 +
        (1 - vol_score) * 0.15
    )
    df["ml_buy_confidence"] = np.clip(buy_raw * 100, 0, 100).round(1)

    # Aggregate: sell confidence
    sell_raw = (
        price_pos * 0.2 +
        vol_strength * 0.15 +
        np.clip(-trend_score, 0, 1) * 0.25 +
        np.clip(-momentum_score, 0, 1) * 0.25 +
        (1 - vol_score) * 0.15
    )
    df["ml_sell_confidence"] = np.clip(sell_raw * 100, 0, 100).round(1)

    return df
