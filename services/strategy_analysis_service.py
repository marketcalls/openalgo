"""Strategy Analysis Service -- advanced strategy endpoints.

Provides Fibonacci, Harmonic, Elliott Wave, Smart Money Concepts,
Hedge Strategy, Strategy Decision (confluence voting), Multi-Timeframe,
Candlestick Patterns, and Support/Resistance analysis.

All functions accept (symbol, exchange, interval, api_key) and return dicts.
Uses indicators_advanced.py (self-contained) as the primary computation engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ai.data_bridge import fetch_ohlcv
from ai.indicators import compute_indicators
from ai.indicators_advanced import (
    compute_all_advanced,
    compute_candlestick_patterns,
    compute_cpr_levels,
    compute_fibonacci_levels,
    compute_harmonic_patterns,
    compute_rsi_divergence,
    compute_smc_indicators,
    compute_volume_signals,
    _extract_zigzag,
)
from utils.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nan_safe(val):
    """Convert NaN / inf to None for JSON serialisation."""
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    return round(float(val), 4)


def _fetch_and_enrich(
    symbol: str, exchange: str, interval: str, api_key: str,
    start_date: str | None = None, end_date: str | None = None,
) -> tuple[bool, pd.DataFrame | None, str | None]:
    """Fetch OHLCV, compute base + advanced indicators.  Return (ok, df, err)."""
    ohlcv = fetch_ohlcv(symbol, exchange, interval, api_key, start_date, end_date)
    if not ohlcv.success:
        return False, None, ohlcv.error
    if len(ohlcv.df) < 20:
        return False, None, f"Insufficient data: {len(ohlcv.df)} rows (need >= 20)"

    df = compute_indicators(ohlcv.df)
    df = compute_all_advanced(df)
    return True, df, None


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute ATR for trade-level calculations."""
    try:
        import ta
        return ta.volatility.AverageTrueRange(
            df["high"], df["low"], df["close"], window=period,
        ).average_true_range()
    except Exception:
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        return tr.rolling(period).mean()


# ---------------------------------------------------------------------------
# 1. Fibonacci Analysis
# ---------------------------------------------------------------------------

def analyze_fibonacci(
    symbol: str, exchange: str, interval: str, api_key: str,
    lookback: int = 50, **kw,
) -> dict:
    ok, df, err = _fetch_and_enrich(symbol, exchange, interval, api_key, **kw)
    if not ok:
        return {"success": False, "error": err}

    last = df.iloc[-1]
    close = float(last["close"])

    # Get swing high/low from lookback window
    window = df.tail(lookback)
    swing_high = float(window["high"].max())
    swing_low = float(window["low"].min())
    rng = swing_high - swing_low

    fib_ratios = [0.236, 0.382, 0.500, 0.618, 0.786]
    levels = {}
    for r in fib_ratios:
        levels[f"fib_{r}"] = round(swing_high - r * rng, 2)

    # Determine which fib zone the price is in
    zone = "above_all"
    for r in fib_ratios:
        level_val = swing_high - r * rng
        if close < level_val:
            zone = f"below_{r}"

    # Signal from the advanced fib columns
    fib_long = int(last.get("fib_long", 0))
    fib_short = int(last.get("fib_short", 0))

    signal = "neutral"
    if fib_long:
        signal = "bullish"
    elif fib_short:
        signal = "bearish"

    # Recent fib signals (last 10 bars)
    recent_long = int(df["fib_long"].iloc[-10:].sum()) if "fib_long" in df.columns else 0
    recent_short = int(df["fib_short"].iloc[-10:].sum()) if "fib_short" in df.columns else 0

    return {
        "success": True,
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "close": round(close, 2),
            "swing_high": round(swing_high, 2),
            "swing_low": round(swing_low, 2),
            "lookback": lookback,
            "levels": levels,
            "zone": zone,
            "signal": signal,
            "fib_long_current": fib_long,
            "fib_short_current": fib_short,
            "recent_fib_longs": recent_long,
            "recent_fib_shorts": recent_short,
            "data_points": len(df),
        },
    }


# ---------------------------------------------------------------------------
# 2. Harmonic Pattern Detection
# ---------------------------------------------------------------------------

def analyze_harmonic(
    symbol: str, exchange: str, interval: str, api_key: str, **kw,
) -> dict:
    ok, df, err = _fetch_and_enrich(symbol, exchange, interval, api_key, **kw)
    if not ok:
        return {"success": False, "error": err}

    last = df.iloc[-1]
    close = float(last["close"])

    bull = int(df["harmonic_bullish"].iloc[-5:].sum()) if "harmonic_bullish" in df.columns else 0
    bear = int(df["harmonic_bearish"].iloc[-5:].sum()) if "harmonic_bearish" in df.columns else 0

    total_bull = int(df["harmonic_bullish"].sum()) if "harmonic_bullish" in df.columns else 0
    total_bear = int(df["harmonic_bearish"].sum()) if "harmonic_bearish" in df.columns else 0

    signal = "neutral"
    if bull > bear:
        signal = "bullish"
    elif bear > bull:
        signal = "bearish"

    # Extract zigzag pivots for detail
    pivots = _extract_zigzag(df)
    pivot_prices = [round(p[1], 2) for p in pivots[-6:]] if len(pivots) >= 2 else []

    return {
        "success": True,
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "close": round(close, 2),
            "signal": signal,
            "recent_bullish": bull,
            "recent_bearish": bear,
            "total_bullish": total_bull,
            "total_bearish": total_bear,
            "zigzag_pivots": pivot_prices,
            "data_points": len(df),
        },
    }


# ---------------------------------------------------------------------------
# 3. Elliott Wave Analysis (heuristic: swing structure + wave counting)
# ---------------------------------------------------------------------------

def analyze_elliott_wave(
    symbol: str, exchange: str, interval: str, api_key: str, **kw,
) -> dict:
    ok, df, err = _fetch_and_enrich(symbol, exchange, interval, api_key, **kw)
    if not ok:
        return {"success": False, "error": err}

    close = float(df["close"].iloc[-1])
    pivots = _extract_zigzag(df, pct=2.0)

    if len(pivots) < 6:
        return {
            "success": True,
            "data": {
                "symbol": symbol, "exchange": exchange, "interval": interval,
                "close": round(close, 2),
                "wave_count": 0,
                "current_wave": "insufficient_data",
                "trend": "neutral",
                "signal": "neutral",
                "waves": [],
                "data_points": len(df),
            },
        }

    # Count alternating waves from the most recent major pivot
    waves = []
    for i, (idx, price, _) in enumerate(pivots[-10:]):
        waves.append({"index": int(idx), "price": round(price, 2)})

    # Determine if we are in an impulse or corrective phase
    # Simple heuristic: compare last 5 pivots
    recent = pivots[-5:]
    prices = [p[1] for p in recent]

    # Check for 5-wave impulse (3 moves in trend direction, 2 corrections)
    up_moves = sum(1 for i in range(1, len(prices)) if prices[i] > prices[i - 1])
    down_moves = len(prices) - 1 - up_moves

    if up_moves >= 3:
        trend = "bullish"
        # Check if we might be in wave 4 or 5
        if prices[-1] < prices[-2]:
            current_wave = "corrective_4"
            signal = "bullish"  # expecting wave 5 up
        else:
            current_wave = "impulse_5"
            signal = "bearish"  # end of impulse, expect correction
    elif down_moves >= 3:
        trend = "bearish"
        if prices[-1] > prices[-2]:
            current_wave = "corrective_4"
            signal = "bearish"
        else:
            current_wave = "impulse_5"
            signal = "bullish"
    else:
        trend = "neutral"
        current_wave = "corrective_abc"
        signal = "neutral"

    return {
        "success": True,
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "close": round(close, 2),
            "wave_count": len(waves),
            "current_wave": current_wave,
            "trend": trend,
            "signal": signal,
            "up_moves": up_moves,
            "down_moves": down_moves,
            "waves": waves,
            "data_points": len(df),
        },
    }


# ---------------------------------------------------------------------------
# 4. Smart Money Concepts Detail
# ---------------------------------------------------------------------------

def analyze_smart_money(
    symbol: str, exchange: str, interval: str, api_key: str, **kw,
) -> dict:
    ok, df, err = _fetch_and_enrich(symbol, exchange, interval, api_key, **kw)
    if not ok:
        return {"success": False, "error": err}

    close = float(df["close"].iloc[-1])
    last = df.iloc[-1]

    # SMC components from last bar and recent bars
    smc_cols = {
        "bos_bullish": "smc_bos_bullish",
        "bos_bearish": "smc_bos_bearish",
        "choch_bullish": "smc_choch_bullish",
        "choch_bearish": "smc_choch_bearish",
        "fvg_bullish": "smc_fvg_bullish",
        "fvg_bearish": "smc_fvg_bearish",
        "ob_bullish": "smc_ob_bullish",
        "ob_bearish": "smc_ob_bearish",
    }

    current = {}
    recent = {}  # last 5 bars
    for label, col in smc_cols.items():
        current[label] = int(last.get(col, 0))
        recent[label] = int(df[col].iloc[-5:].sum()) if col in df.columns else 0

    # Aggregate bias
    bull_score = sum(v for k, v in current.items() if "bullish" in k)
    bear_score = sum(v for k, v in current.items() if "bearish" in k)
    recent_bull = sum(v for k, v in recent.items() if "bullish" in k)
    recent_bear = sum(v for k, v in recent.items() if "bearish" in k)

    if recent_bull > recent_bear:
        signal = "bullish"
    elif recent_bear > recent_bull:
        signal = "bearish"
    else:
        signal = "neutral"

    # Find recent FVG zones (gaps)
    fvg_zones = []
    for i in range(max(0, len(df) - 20), len(df)):
        if df["smc_fvg_bullish"].iloc[i] == 1:
            fvg_zones.append({
                "type": "bullish",
                "bar": int(i),
                "high": round(float(df["high"].iloc[i]), 2),
                "low": round(float(df["low"].iloc[i]), 2),
            })
        if df["smc_fvg_bearish"].iloc[i] == 1:
            fvg_zones.append({
                "type": "bearish",
                "bar": int(i),
                "high": round(float(df["high"].iloc[i]), 2),
                "low": round(float(df["low"].iloc[i]), 2),
            })

    # Find recent order block zones
    ob_zones = []
    for i in range(max(0, len(df) - 20), len(df)):
        if df["smc_ob_bullish"].iloc[i] == 1:
            ob_zones.append({
                "type": "bullish",
                "bar": int(i),
                "high": round(float(df["high"].iloc[i]), 2),
                "low": round(float(df["low"].iloc[i]), 2),
            })
        if df["smc_ob_bearish"].iloc[i] == 1:
            ob_zones.append({
                "type": "bearish",
                "bar": int(i),
                "high": round(float(df["high"].iloc[i]), 2),
                "low": round(float(df["low"].iloc[i]), 2),
            })

    return {
        "success": True,
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "close": round(close, 2),
            "signal": signal,
            "current_bar": current,
            "recent_5_bars": recent,
            "bull_score": bull_score + recent_bull,
            "bear_score": bear_score + recent_bear,
            "fvg_zones": fvg_zones[-5:],  # last 5
            "ob_zones": ob_zones[-5:],
            "data_points": len(df),
        },
    }


# ---------------------------------------------------------------------------
# 5. Hedge Strategy (mean reversion, momentum, vol regime, risk metrics)
# ---------------------------------------------------------------------------

def analyze_hedge_strategy(
    symbol: str, exchange: str, interval: str, api_key: str, **kw,
) -> dict:
    ok, df, err = _fetch_and_enrich(symbol, exchange, interval, api_key, **kw)
    if not ok:
        return {"success": False, "error": err}

    close = float(df["close"].iloc[-1])
    last = df.iloc[-1]

    # --- Mean Reversion ---
    bb_pband = _nan_safe(last.get("bb_pband"))
    rsi = _nan_safe(last.get("rsi_14"))
    sma_50 = _nan_safe(last.get("sma_50"))
    sma_200 = _nan_safe(last.get("sma_200"))

    mr_signal = "neutral"
    if rsi is not None and bb_pband is not None:
        if rsi < 30 and bb_pband < 0.1:
            mr_signal = "bullish"  # oversold near lower BB
        elif rsi > 70 and bb_pband > 0.9:
            mr_signal = "bearish"  # overbought near upper BB

    # --- Momentum ---
    macd_hist = _nan_safe(last.get("macd_hist"))
    adx = _nan_safe(last.get("adx_14"))
    supertrend_dir = _nan_safe(last.get("supertrend_dir"))

    mom_signal = "neutral"
    if macd_hist is not None:
        if macd_hist > 0 and (supertrend_dir is None or supertrend_dir > 0):
            mom_signal = "bullish"
        elif macd_hist < 0 and (supertrend_dir is None or supertrend_dir < 0):
            mom_signal = "bearish"

    # --- Volatility Regime ---
    atr_series = _atr(df)
    current_atr = float(atr_series.iloc[-1]) if not math.isnan(atr_series.iloc[-1]) else 0
    avg_atr = float(atr_series.tail(50).mean()) if len(atr_series) >= 50 else current_atr
    vol_ratio = current_atr / avg_atr if avg_atr > 0 else 1.0

    if vol_ratio > 1.5:
        vol_regime = "high"
    elif vol_ratio < 0.7:
        vol_regime = "low"
    else:
        vol_regime = "normal"

    # --- Risk Metrics ---
    returns = df["close"].pct_change().dropna()
    daily_vol = float(returns.std()) if len(returns) > 5 else 0
    annualized_vol = round(daily_vol * (252 ** 0.5) * 100, 2)
    max_drawdown = 0.0
    if len(returns) > 10:
        cum = (1 + returns).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        max_drawdown = round(float(dd.min()) * 100, 2)

    sharpe = 0.0
    if daily_vol > 0 and len(returns) > 20:
        mean_ret = float(returns.mean())
        sharpe = round((mean_ret / daily_vol) * (252 ** 0.5), 2)

    # --- Combined Hedge Signal ---
    scores = {"mean_reversion": mr_signal, "momentum": mom_signal}
    bull_count = sum(1 for s in scores.values() if s == "bullish")
    bear_count = sum(1 for s in scores.values() if s == "bearish")

    if bull_count > bear_count:
        hedge_signal = "bullish"
    elif bear_count > bull_count:
        hedge_signal = "bearish"
    else:
        hedge_signal = "neutral"

    return {
        "success": True,
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "close": round(close, 2),
            "signal": hedge_signal,
            "mean_reversion": {
                "signal": mr_signal,
                "rsi": rsi,
                "bb_pband": bb_pband,
            },
            "momentum": {
                "signal": mom_signal,
                "macd_hist": macd_hist,
                "adx": adx,
                "supertrend_dir": supertrend_dir,
            },
            "volatility": {
                "regime": vol_regime,
                "current_atr": round(current_atr, 4),
                "avg_atr": round(avg_atr, 4),
                "vol_ratio": round(vol_ratio, 2),
            },
            "risk_metrics": {
                "annualized_vol_pct": annualized_vol,
                "max_drawdown_pct": max_drawdown,
                "sharpe_ratio": sharpe,
                "daily_vol": round(daily_vol * 100, 4),
            },
            "data_points": len(df),
        },
    }


# ---------------------------------------------------------------------------
# 6. Strategy Decision -- Confluence Voting Engine
# ---------------------------------------------------------------------------

def _vote(signal_str: str) -> int:
    """Convert signal string to vote: +1 bull, -1 bear, 0 neutral."""
    if signal_str == "bullish":
        return 1
    elif signal_str == "bearish":
        return -1
    return 0


def analyze_strategy_decision(
    symbol: str, exchange: str, interval: str, api_key: str, **kw,
) -> dict:
    """Run all strategy analyses, collect votes, compute confluence."""
    ok, df, err = _fetch_and_enrich(symbol, exchange, interval, api_key, **kw)
    if not ok:
        return {"success": False, "error": err}

    close = float(df["close"].iloc[-1])
    last = df.iloc[-1]

    # Collect votes from each module
    votes = {}

    # 1. Fibonacci
    fib_long = int(last.get("fib_long", 0))
    fib_short = int(last.get("fib_short", 0))
    if fib_long:
        votes["fibonacci"] = +1
    elif fib_short:
        votes["fibonacci"] = -1
    else:
        votes["fibonacci"] = 0

    # 2. Harmonic
    h_bull = int(df["harmonic_bullish"].iloc[-5:].sum()) if "harmonic_bullish" in df.columns else 0
    h_bear = int(df["harmonic_bearish"].iloc[-5:].sum()) if "harmonic_bearish" in df.columns else 0
    if h_bull > h_bear:
        votes["harmonic"] = +1
    elif h_bear > h_bull:
        votes["harmonic"] = -1
    else:
        votes["harmonic"] = 0

    # 3. SMC
    smc_bull = sum(int(last.get(c, 0)) for c in [
        "smc_bos_bullish", "smc_choch_bullish", "smc_fvg_bullish", "smc_ob_bullish"])
    smc_bear = sum(int(last.get(c, 0)) for c in [
        "smc_bos_bearish", "smc_choch_bearish", "smc_fvg_bearish", "smc_ob_bearish"])
    if smc_bull > smc_bear:
        votes["smc"] = +1
    elif smc_bear > smc_bull:
        votes["smc"] = -1
    else:
        votes["smc"] = 0

    # 4. Candlestick patterns
    cdl_bull = sum(1 for c in df.columns if c.startswith("cdl_") and "bull" in c and last.get(c, 0) == 1)
    cdl_bear = sum(1 for c in df.columns if c.startswith("cdl_") and "bear" in c and last.get(c, 0) == 1)
    # Single-candle patterns: hammer=bull, shooting_star=bear, etc.
    if "cdl_hammer" in df.columns and last.get("cdl_hammer", 0):
        cdl_bull += 1
    if "cdl_shooting_star" in df.columns and last.get("cdl_shooting_star", 0):
        cdl_bear += 1
    if "cdl_morning_star" in df.columns and last.get("cdl_morning_star", 0):
        cdl_bull += 1
    if "cdl_evening_star" in df.columns and last.get("cdl_evening_star", 0):
        cdl_bear += 1

    if cdl_bull > cdl_bear:
        votes["candlestick"] = +1
    elif cdl_bear > cdl_bull:
        votes["candlestick"] = -1
    else:
        votes["candlestick"] = 0

    # 5. RSI Divergence
    rsi_bull_div = int(last.get("rsi_bull_divergence", 0))
    rsi_bear_div = int(last.get("rsi_bear_divergence", 0))
    if rsi_bull_div:
        votes["rsi_divergence"] = +1
    elif rsi_bear_div:
        votes["rsi_divergence"] = -1
    else:
        votes["rsi_divergence"] = 0

    # 6. Volume exhaustion + VWAP confluence
    vol_exhaustion = int(last.get("volume_exhaustion", 0))
    rsi_val = _nan_safe(last.get("rsi_14"))
    if vol_exhaustion:
        if rsi_val and rsi_val < 40:
            votes["volume"] = +1  # climactic selling
        elif rsi_val and rsi_val > 60:
            votes["volume"] = -1  # climactic buying
        else:
            votes["volume"] = 0
    else:
        votes["volume"] = 0

    # 7. Trend (EMA/SMA/Supertrend)
    ema_9 = _nan_safe(last.get("ema_9"))
    ema_21 = _nan_safe(last.get("ema_21"))
    st_dir = _nan_safe(last.get("supertrend_dir"))
    trend_votes = 0
    if ema_9 and ema_21:
        trend_votes += 1 if ema_9 > ema_21 else -1
    if st_dir:
        trend_votes += 1 if st_dir > 0 else -1
    votes["trend"] = max(-1, min(1, trend_votes))

    # 8. Momentum (MACD + ADX)
    macd_hist = _nan_safe(last.get("macd_hist"))
    adx_val = _nan_safe(last.get("adx_14"))
    if macd_hist and adx_val and adx_val > 20:
        votes["momentum"] = +1 if macd_hist > 0 else -1
    else:
        votes["momentum"] = 0

    # --- Confluence computation ---
    total_modules = len(votes)
    bull_count = sum(1 for v in votes.values() if v > 0)
    bear_count = sum(1 for v in votes.values() if v < 0)
    neutral_count = sum(1 for v in votes.values() if v == 0)

    net_score = sum(votes.values())

    confluence = round(max(bull_count, bear_count) / total_modules * 100, 1) if total_modules > 0 else 0

    if net_score > 0:
        direction = "bullish"
    elif net_score < 0:
        direction = "bearish"
    else:
        direction = "neutral"

    # --- Entry / SL / Targets using ATR ---
    atr_series = _atr(df)
    atr_val = float(atr_series.iloc[-1]) if not math.isnan(atr_series.iloc[-1]) else close * 0.02

    if direction == "bullish":
        entry = round(close, 2)
        stop_loss = round(close - 1.5 * atr_val, 2)
        target_1 = round(close + 1.0 * atr_val, 2)
        target_2 = round(close + 2.0 * atr_val, 2)
        target_3 = round(close + 3.0 * atr_val, 2)
    elif direction == "bearish":
        entry = round(close, 2)
        stop_loss = round(close + 1.5 * atr_val, 2)
        target_1 = round(close - 1.0 * atr_val, 2)
        target_2 = round(close - 2.0 * atr_val, 2)
        target_3 = round(close - 3.0 * atr_val, 2)
    else:
        entry = round(close, 2)
        stop_loss = round(close - 1.5 * atr_val, 2)
        target_1 = round(close + 1.0 * atr_val, 2)
        target_2 = round(close + 2.0 * atr_val, 2)
        target_3 = round(close + 3.0 * atr_val, 2)

    risk = abs(entry - stop_loss)
    rr1 = round(abs(target_1 - entry) / risk, 2) if risk > 0 else 0
    rr2 = round(abs(target_2 - entry) / risk, 2) if risk > 0 else 0
    rr3 = round(abs(target_3 - entry) / risk, 2) if risk > 0 else 0

    # Confidence label
    if confluence >= 75:
        confidence_label = "HIGH"
    elif confluence >= 50:
        confidence_label = "MEDIUM"
    else:
        confidence_label = "LOW"

    return {
        "success": True,
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "close": round(close, 2),
            "direction": direction,
            "net_score": net_score,
            "confluence_pct": confluence,
            "confidence_label": confidence_label,
            "bull_count": bull_count,
            "bear_count": bear_count,
            "neutral_count": neutral_count,
            "total_modules": total_modules,
            "votes": votes,
            "trade_setup": {
                "entry": entry,
                "stop_loss": stop_loss,
                "target_1": target_1,
                "target_2": target_2,
                "target_3": target_3,
                "risk_reward_1": rr1,
                "risk_reward_2": rr2,
                "risk_reward_3": rr3,
                "atr": round(atr_val, 4),
            },
            "data_points": len(df),
        },
    }


# ---------------------------------------------------------------------------
# 7. Multi-Timeframe Analysis
# ---------------------------------------------------------------------------

# Timeframe weights (higher TF = more weight)
TF_WEIGHTS = {
    "5m": 1, "15m": 2, "60m": 3,
    "D": 5, "W": 7, "M": 10,
    # aliases
    "1d": 5, "1w": 7, "1M": 10,
    "5min": 1, "15min": 2, "1h": 3,
}


def analyze_multi_timeframe(
    symbol: str, exchange: str, api_key: str,
    timeframes: list[str] | None = None,
    **kw,
) -> dict:
    """Run strategy decision across multiple timeframes and compute weighted confluence."""
    if timeframes is None:
        timeframes = ["5m", "15m", "60m", "D", "W", "M"]

    from services.ai_analysis_service import analyze_symbol

    per_tf = {}
    weighted_score = 0.0
    total_weight = 0.0

    for tf in timeframes:
        try:
            result = analyze_symbol(symbol, exchange, tf, api_key)
            if result.success:
                # Map signal to numeric
                sig_map = {"BUY": 1, "SELL": -1, "STRONG_BUY": 2, "STRONG_SELL": -2}
                numeric = sig_map.get(result.signal, 0)
                w = TF_WEIGHTS.get(tf, 1)

                per_tf[tf] = {
                    "signal": result.signal,
                    "score": round(result.score, 2),
                    "confidence": round(result.confidence, 2),
                    "regime": result.regime,
                    "weight": w,
                    "weighted_contribution": round(numeric * w, 2),
                }

                weighted_score += numeric * w
                total_weight += w
            else:
                per_tf[tf] = {
                    "signal": None,
                    "error": result.error,
                    "weight": TF_WEIGHTS.get(tf, 1),
                }
        except Exception as e:
            logger.warning(f"MTF analysis failed for {tf}: {e}")
            per_tf[tf] = {"signal": None, "error": str(e), "weight": TF_WEIGHTS.get(tf, 1)}

    # Compute overall
    if total_weight > 0:
        overall_score = weighted_score / total_weight
    else:
        overall_score = 0

    if overall_score > 0.5:
        overall_signal = "bullish"
    elif overall_score < -0.5:
        overall_signal = "bearish"
    else:
        overall_signal = "neutral"

    # Confluence: % of timeframes agreeing with overall
    agree = sum(1 for v in per_tf.values() if v.get("signal") and (
        (overall_signal == "bullish" and v["signal"] in ("BUY", "STRONG_BUY")) or
        (overall_signal == "bearish" and v["signal"] in ("SELL", "STRONG_SELL"))
    ))
    active = sum(1 for v in per_tf.values() if v.get("signal") is not None)
    tf_confluence = round(agree / active * 100, 1) if active > 0 else 0

    return {
        "success": True,
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "overall_signal": overall_signal,
            "overall_score": round(overall_score, 3),
            "tf_confluence_pct": tf_confluence,
            "timeframes_analyzed": active,
            "timeframes_agreeing": agree,
            "per_timeframe": per_tf,
        },
    }


# ---------------------------------------------------------------------------
# 8. Candlestick Patterns
# ---------------------------------------------------------------------------

def analyze_candlestick_patterns(
    symbol: str, exchange: str, interval: str, api_key: str, **kw,
) -> dict:
    ok, df, err = _fetch_and_enrich(symbol, exchange, interval, api_key, **kw)
    if not ok:
        return {"success": False, "error": err}

    close = float(df["close"].iloc[-1])

    # Collect all cdl_ columns
    pattern_cols = [c for c in df.columns if c.startswith("cdl_")]

    # Current bar patterns
    current_patterns = []
    for col in pattern_cols:
        if df[col].iloc[-1] == 1:
            current_patterns.append(col.replace("cdl_", ""))

    # Recent patterns (last 5 bars)
    recent_patterns = {}
    for col in pattern_cols:
        count = int(df[col].iloc[-5:].sum())
        if count > 0:
            recent_patterns[col.replace("cdl_", "")] = count

    # Classify bullish vs bearish patterns
    bullish_patterns = [
        "hammer", "inverted_hammer", "engulfing_bull", "harami_bull",
        "morning_star", "piercing_line", "three_white_soldiers",
    ]
    bearish_patterns = [
        "shooting_star", "hanging_man", "engulfing_bear", "harami_bear",
        "evening_star", "dark_cloud", "three_black_crows",
    ]

    bull_active = [p for p in current_patterns if p in bullish_patterns]
    bear_active = [p for p in current_patterns if p in bearish_patterns]

    if len(bull_active) > len(bear_active):
        signal = "bullish"
    elif len(bear_active) > len(bull_active):
        signal = "bearish"
    else:
        signal = "neutral"

    # Total pattern counts across all data
    total_counts = {}
    for col in pattern_cols:
        total = int(df[col].sum())
        if total > 0:
            total_counts[col.replace("cdl_", "")] = total

    return {
        "success": True,
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "close": round(close, 2),
            "signal": signal,
            "current_bar_patterns": current_patterns,
            "bullish_active": bull_active,
            "bearish_active": bear_active,
            "recent_5_bars": recent_patterns,
            "total_pattern_counts": total_counts,
            "data_points": len(df),
        },
    }


# ---------------------------------------------------------------------------
# 9. Support / Resistance from CPR Pivots
# ---------------------------------------------------------------------------

def analyze_support_resistance(
    symbol: str, exchange: str, interval: str, api_key: str, **kw,
) -> dict:
    ok, df, err = _fetch_and_enrich(symbol, exchange, interval, api_key, **kw)
    if not ok:
        return {"success": False, "error": err}

    close = float(df["close"].iloc[-1])
    last = df.iloc[-1]

    # CPR levels
    pivot_cols = ["pivot", "bc", "tc", "r1", "r2", "r3", "s1", "s2", "s3"]
    levels = {}
    for col in pivot_cols:
        val = _nan_safe(last.get(col))
        if val is not None:
            levels[col] = val

    # Additional S/R from recent swing high/low
    lookbacks = [20, 50, 100]
    swing_levels = {}
    for lb in lookbacks:
        if len(df) >= lb:
            window = df.tail(lb)
            swing_levels[f"high_{lb}"] = round(float(window["high"].max()), 2)
            swing_levels[f"low_{lb}"] = round(float(window["low"].min()), 2)

    # Fibonacci S/R (from 50-bar lookback)
    fib_levels = {}
    if len(df) >= 50:
        window = df.tail(50)
        sh = float(window["high"].max())
        sl = float(window["low"].min())
        rng = sh - sl
        for ratio in [0.236, 0.382, 0.500, 0.618, 0.786]:
            fib_levels[f"fib_{ratio}"] = round(sh - ratio * rng, 2)

    # Determine nearest support and resistance
    all_levels = {}
    all_levels.update(levels)
    all_levels.update(swing_levels)
    all_levels.update(fib_levels)

    support_levels = {k: v for k, v in all_levels.items() if v < close}
    resistance_levels = {k: v for k, v in all_levels.items() if v > close}

    nearest_support = None
    nearest_resistance = None
    if support_levels:
        nearest_support = max(support_levels.items(), key=lambda x: x[1])
    if resistance_levels:
        nearest_resistance = min(resistance_levels.items(), key=lambda x: x[1])

    return {
        "success": True,
        "data": {
            "symbol": symbol,
            "exchange": exchange,
            "interval": interval,
            "close": round(close, 2),
            "pivot_levels": levels,
            "swing_levels": swing_levels,
            "fibonacci_levels": fib_levels,
            "nearest_support": {
                "level": nearest_support[0],
                "price": nearest_support[1],
            } if nearest_support else None,
            "nearest_resistance": {
                "level": nearest_resistance[0],
                "price": nearest_resistance[1],
            } if nearest_resistance else None,
            "all_support": dict(sorted(support_levels.items(), key=lambda x: -x[1])),
            "all_resistance": dict(sorted(resistance_levels.items(), key=lambda x: x[1])),
            "data_points": len(df),
        },
    }
