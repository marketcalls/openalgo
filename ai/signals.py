"""Weighted composite signal engine adapted from VAYU.

Fuses 6 sub-signals (supertrend, RSI, MACD, EMA cross, Bollinger, ADX)
into a single score [-1, +1] mapped to SignalType.
"""

from enum import Enum

import pandas as pd
from utils.logging import get_logger

logger = get_logger(__name__)

# Default weights (same as VAYU)
DEFAULT_WEIGHTS = {
    "supertrend": 0.25,
    "rsi": 0.20,
    "macd": 0.20,
    "ema_cross": 0.15,
    "bollinger": 0.10,
    "adx_strength": 0.10,
}


class SignalType(str, Enum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class MarketRegime(str, Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"


def detect_regime(df: pd.DataFrame) -> MarketRegime:
    """Detect market regime using ADX + ATR percentile."""
    if len(df) < 50:
        return MarketRegime.RANGING

    latest = df.iloc[-1]
    adx_val = latest.get("adx_14")
    atr_val = latest.get("atr_14")

    atr_pctile = 50
    if atr_val is not None and pd.notna(atr_val) and "atr_14" in df.columns:
        atr_series = df["atr_14"].dropna()
        if len(atr_series) > 0:
            atr_pctile = (atr_series < atr_val).sum() / len(atr_series) * 100

    if adx_val is None or pd.isna(adx_val):
        return MarketRegime.RANGING

    trending = adx_val > 25
    sma_50 = latest.get("sma_50")
    close = latest.get("close", 0)

    if trending and sma_50 is not None and pd.notna(sma_50) and close > sma_50:
        return MarketRegime.TRENDING_UP
    elif trending:
        return MarketRegime.TRENDING_DOWN
    elif atr_pctile > 60:
        return MarketRegime.VOLATILE
    else:
        return MarketRegime.RANGING


def generate_signal(
    df: pd.DataFrame,
    weights: dict[str, float] | None = None,
) -> dict:
    """Generate composite signal from indicator DataFrame.

    Args:
        df: DataFrame with indicator columns (from compute_indicators)
        weights: Optional custom weights dict. Defaults to DEFAULT_WEIGHTS.

    Returns:
        {"signal", "confidence", "score", "scores", "regime"}
    """
    if len(df) < 20:
        return {
            "signal": SignalType.HOLD.value,
            "confidence": 0,
            "score": 0.0,
            "scores": {},
            "regime": MarketRegime.RANGING.value,
        }

    w = weights if weights else DEFAULT_WEIGHTS
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest
    scores = {}

    # 1. Supertrend (25%)
    st_dir = latest.get("supertrend_dir")
    prev_st_dir = prev.get("supertrend_dir")
    if st_dir is not None and pd.notna(st_dir):
        if prev_st_dir is not None and pd.notna(prev_st_dir):
            if st_dir == 1 and prev_st_dir == -1:
                scores["supertrend"] = 1.0
            elif st_dir == 1:
                scores["supertrend"] = 0.4
            elif st_dir == -1 and prev_st_dir == 1:
                scores["supertrend"] = -1.0
            else:
                scores["supertrend"] = -0.4
        elif st_dir == 1:
            scores["supertrend"] = 0.3
        else:
            scores["supertrend"] = -0.3

    # 2. RSI (20%)
    rsi = latest.get("rsi_14")
    if rsi is not None and pd.notna(rsi):
        if rsi < 30:
            scores["rsi"] = 0.8
        elif rsi < 40:
            scores["rsi"] = 0.3
        elif rsi > 70:
            scores["rsi"] = -0.8
        elif rsi > 60:
            scores["rsi"] = -0.3
        else:
            scores["rsi"] = 0.0

    # 3. MACD (20%)
    macd_hist = latest.get("macd_hist")
    prev_hist = prev.get("macd_hist")
    if macd_hist is not None and pd.notna(macd_hist):
        if prev_hist is not None and pd.notna(prev_hist):
            if macd_hist > 0 and prev_hist <= 0:
                scores["macd"] = 0.8
            elif macd_hist < 0 and prev_hist >= 0:
                scores["macd"] = -0.8
            elif macd_hist > 0:
                scores["macd"] = 0.3
            else:
                scores["macd"] = -0.3
        elif macd_hist > 0:
            scores["macd"] = 0.2
        else:
            scores["macd"] = -0.2

    # 4. EMA crossover (15%)
    ema9 = latest.get("ema_9")
    ema21 = latest.get("ema_21")
    if ema9 is not None and ema21 is not None and pd.notna(ema9) and pd.notna(ema21):
        prev_ema9 = prev.get("ema_9", ema9)
        prev_ema21 = prev.get("ema_21", ema21)
        if pd.notna(prev_ema9) and pd.notna(prev_ema21):
            if ema9 > ema21 and prev_ema9 <= prev_ema21:
                scores["ema_cross"] = 0.8
            elif ema9 < ema21 and prev_ema9 >= prev_ema21:
                scores["ema_cross"] = -0.8
            elif ema9 > ema21:
                scores["ema_cross"] = 0.3
            else:
                scores["ema_cross"] = -0.3

    # 5. Bollinger Band (10%)
    bbp = latest.get("bb_pband")
    if bbp is not None and pd.notna(bbp):
        if bbp < 0.0:
            scores["bollinger"] = 0.6
        elif bbp < 0.2:
            scores["bollinger"] = 0.3
        elif bbp > 1.0:
            scores["bollinger"] = -0.6
        elif bbp > 0.8:
            scores["bollinger"] = -0.3
        else:
            scores["bollinger"] = 0.0

    # 6. ADX strength (10%)
    adx_val = latest.get("adx_14")
    if adx_val is not None and pd.notna(adx_val):
        scores["adx_strength"] = 0.2 if adx_val > 25 else -0.1

    # Weighted aggregation
    weighted_sum = 0.0
    total_weight = 0.0
    for key, score in scores.items():
        weight = w.get(key, 0.1)
        weighted_sum += weight * score
        total_weight += weight

    final_score = weighted_sum / total_weight if total_weight > 0 else 0.0
    confidence = min(abs(final_score) * 100, 100)

    if final_score >= 0.5:
        signal = SignalType.STRONG_BUY
    elif final_score > 0.2:
        signal = SignalType.BUY
    elif final_score <= -0.5:
        signal = SignalType.STRONG_SELL
    elif final_score < -0.2:
        signal = SignalType.SELL
    else:
        signal = SignalType.HOLD

    regime = detect_regime(df)

    return {
        "signal": signal.value,
        "confidence": round(confidence, 1),
        "score": round(final_score, 4),
        "scores": {k: round(v, 4) for k, v in scores.items()},
        "regime": regime.value,
    }
