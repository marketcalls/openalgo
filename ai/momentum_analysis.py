"""Momentum analysis using RSI, MACD, Stochastic, and Rate of Change.

Produces MomentumReport with:
- score: -100 to +100 (negative = bearish momentum, positive = bullish)
- bias: "bullish" | "bearish" | "neutral"
- details: per-component scores + overbought/oversold flags
"""

from dataclasses import dataclass, field

import pandas as pd
import ta
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MomentumReport:
    score: float     # -100 to +100
    bias: str        # "bullish", "bearish", "neutral"
    details: dict = field(default_factory=dict)


def compute_momentum_score(df: pd.DataFrame) -> MomentumReport:
    """Compute momentum score from RSI, MACD, Stochastic, ROC."""
    if len(df) < 30:
        return MomentumReport(score=0, bias="neutral", details={})

    df = df.copy()
    c = df["close"]
    h, l = df["high"], df["low"]
    components = []
    details = {}

    # 1. RSI (14) -- mapped to -100..+100
    try:
        rsi = ta.momentum.RSIIndicator(c, window=14).rsi().iloc[-1]
        if pd.notna(rsi):
            rsi_score = (rsi - 50) * 2  # 50 -> 0, 70 -> +40, 30 -> -40
            components.append(("rsi", rsi_score, 0.30))
            details["rsi"] = round(rsi, 1)
            if rsi > 70:
                details["overbought"] = True
            elif rsi < 30:
                details["oversold"] = True
    except Exception:
        pass

    # 2. MACD histogram direction
    try:
        macd_ind = ta.trend.MACD(c, window_slow=26, window_fast=12, window_sign=9)
        hist = macd_ind.macd_diff().iloc[-1]
        prev_hist = macd_ind.macd_diff().iloc[-2]
        if pd.notna(hist) and pd.notna(prev_hist):
            # Positive and rising = strong bullish
            if hist > 0 and hist > prev_hist:
                macd_score = 80
            elif hist > 0:
                macd_score = 30
            elif hist < 0 and hist < prev_hist:
                macd_score = -80
            elif hist < 0:
                macd_score = -30
            else:
                macd_score = 0
            components.append(("macd", macd_score, 0.30))
            details["macd"] = round(float(hist), 4)
    except Exception:
        pass

    # 3. Stochastic %K
    try:
        stoch = ta.momentum.StochasticOscillator(h, l, c, window=14, smooth_window=3)
        k = stoch.stoch().iloc[-1]
        if pd.notna(k):
            stoch_score = (k - 50) * 2
            components.append(("stochastic", stoch_score, 0.20))
            details["stochastic"] = round(k, 1)
    except Exception:
        pass

    # 4. Rate of Change (10-period)
    try:
        roc = c.pct_change(10).iloc[-1] * 100
        if pd.notna(roc):
            roc_score = max(min(roc * 10, 100), -100)
            components.append(("roc", roc_score, 0.20))
            details["roc"] = round(roc, 2)
    except Exception:
        pass

    if not components:
        return MomentumReport(score=0, bias="neutral", details=details)

    # Weighted aggregate
    total_weight = sum(w for _, _, w in components)
    score = sum(s * w for _, s, w in components) / total_weight if total_weight > 0 else 0
    score = round(max(min(score, 100), -100), 1)

    if score > 20:
        bias = "bullish"
    elif score < -20:
        bias = "bearish"
    else:
        bias = "neutral"

    return MomentumReport(score=score, bias=bias, details=details)
