"""Trend strength analysis using ADX, EMA alignment, Supertrend, and price-vs-SMA.

Produces a TrendReport with:
- strength: 0-100 (how strong the trend is)
- direction: "bullish" | "bearish" | "neutral"
- details: individual component scores
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import ta
from utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TrendReport:
    strength: float  # 0-100
    direction: str   # "bullish", "bearish", "neutral"
    details: dict = field(default_factory=dict)


def _safe(func, *args, **kwargs):
    """Safely compute an indicator, returning None on error."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.debug(f"Indicator skipped: {e}")
        return None


def _compute_supertrend_direction(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> int:
    """Compute Supertrend direction: 1 = bullish, -1 = bearish, 0 = indeterminate.

    Uses proper iterative Supertrend calculation (matches indicators.py logic).
    """
    h, l, c = df["high"], df["low"], df["close"]
    hl2 = (h + l) / 2
    atr = ta.volatility.AverageTrueRange(h, l, c, window=period).average_true_range()

    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    direction = pd.Series(1, index=df.index)

    for i in range(period, len(df)):
        if c.iloc[i] > upper_band.iloc[i - 1]:
            direction.iloc[i] = 1
        elif c.iloc[i] < lower_band.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
            if direction.iloc[i] == 1 and lower_band.iloc[i] < lower_band.iloc[i - 1]:
                lower_band.iloc[i] = lower_band.iloc[i - 1]
            if direction.iloc[i] == -1 and upper_band.iloc[i] > upper_band.iloc[i - 1]:
                upper_band.iloc[i] = upper_band.iloc[i - 1]

    return int(direction.iloc[-1])


def compute_trend_score(df: pd.DataFrame) -> TrendReport:
    """Compute trend strength and direction from OHLCV data."""
    if len(df) < 30:
        return TrendReport(strength=0, direction="neutral", details={})

    df = df.copy()
    c = df["close"]
    h, l = df["high"], df["low"]
    scores = {}
    directions = []

    # 1. ADX strength (0-100, >25 = trending) — weight 35%
    try:
        adx_ind = ta.trend.ADXIndicator(h, l, c, window=14)
        adx = adx_ind.adx().iloc[-1]
        dmp = adx_ind.adx_pos().iloc[-1]
        dmn = adx_ind.adx_neg().iloc[-1]
        if pd.notna(adx):
            scores["adx"] = min(adx, 100)
            if dmp > dmn:
                directions.append(1)
            elif dmn > dmp:
                directions.append(-1)
    except Exception:
        scores["adx"] = 0

    # 2. EMA alignment (9 > 21 > 50 = strong uptrend) — weight 30%
    try:
        ema9 = _safe(lambda: ta.trend.EMAIndicator(c, window=9).ema_indicator().iloc[-1])
        ema21 = _safe(lambda: ta.trend.EMAIndicator(c, window=21).ema_indicator().iloc[-1])
        if ema9 is not None and ema21 is not None:
            if len(df) >= 50:
                sma50 = _safe(lambda: ta.trend.SMAIndicator(c, window=50).sma_indicator().iloc[-1])
                if sma50 is not None:
                    if ema9 > ema21 > sma50:
                        scores["ema_alignment"] = 100
                        directions.append(1)
                    elif ema9 < ema21 < sma50:
                        scores["ema_alignment"] = 100
                        directions.append(-1)
                    elif ema9 > ema21:
                        scores["ema_alignment"] = 50
                        directions.append(1)
                    elif ema9 < ema21:
                        scores["ema_alignment"] = 50
                        directions.append(-1)
                    else:
                        scores["ema_alignment"] = 0
                else:
                    scores["ema_alignment"] = 0
            else:
                if ema9 > ema21:
                    scores["ema_alignment"] = 60
                    directions.append(1)
                elif ema9 < ema21:
                    scores["ema_alignment"] = 60
                    directions.append(-1)
                else:
                    scores["ema_alignment"] = 0
        else:
            scores["ema_alignment"] = 0
    except Exception:
        scores["ema_alignment"] = 0

    # 3. Supertrend direction — weight 20%
    try:
        st_dir = _compute_supertrend_direction(df)
        if st_dir == 1:
            scores["supertrend"] = 80
            directions.append(1)
        elif st_dir == -1:
            scores["supertrend"] = 80
            directions.append(-1)
        else:
            scores["supertrend"] = 20
    except Exception:
        scores["supertrend"] = 0

    # 4. Price vs SMA200 (long-term trend) — weight 15%
    try:
        if len(df) >= 200:
            sma200 = ta.trend.SMAIndicator(c, window=200).sma_indicator().iloc[-1]
            pct_above = (c.iloc[-1] - sma200) / sma200 * 100
            scores["price_vs_sma"] = min(abs(pct_above) * 10, 100)
            directions.append(1 if pct_above > 0 else -1)
        else:
            scores["price_vs_sma"] = 0
    except Exception:
        scores["price_vs_sma"] = 0

    # Aggregate with weights
    weights = {"adx": 0.35, "ema_alignment": 0.30, "supertrend": 0.20, "price_vs_sma": 0.15}
    total = sum(scores.get(k, 0) * w for k, w in weights.items())
    strength = round(total, 1)

    # Direction by majority vote
    bull_count = sum(1 for d in directions if d > 0)
    bear_count = sum(1 for d in directions if d < 0)
    if bull_count > bear_count:
        direction = "bullish"
    elif bear_count > bull_count:
        direction = "bearish"
    else:
        direction = "neutral"

    return TrendReport(strength=strength, direction=direction, details=scores)
