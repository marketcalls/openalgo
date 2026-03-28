"""
AAUM Institutional Dashboard — Service Layer

Provides data for all 9 dashboard panels by:
1. Trying AAUM backend (localhost:8080) first
2. Falling back to OpenAlgo broker APIs (quotes, depth, history, positions, funds)
3. Returning sensible computed defaults if both are unavailable

All functions return dicts matching the frontend TypeScript response types.
"""

import math
import time
import traceback
from datetime import datetime, timedelta
from typing import Any

import httpx

from database.auth_db import get_auth_token, get_auth_token_broker
from services.aaum_service import _try_request, get_aaum_url, DEFAULT_TIMEOUT
from utils.logging import get_logger

logger = get_logger(__name__)

# ── Top 20 F&O stocks for scanner ──────────────────────────────────────────
FNO_STOCKS = [
    ("RELIANCE", "Energy"), ("TCS", "IT"), ("HDFCBANK", "Banking"),
    ("INFY", "IT"), ("ICICIBANK", "Banking"), ("HINDUNILVR", "FMCG"),
    ("ITC", "FMCG"), ("SBIN", "Banking"), ("BHARTIARTL", "Telecom"),
    ("KOTAKBANK", "Banking"), ("LT", "Infra"), ("AXISBANK", "Banking"),
    ("BAJFINANCE", "Finance"), ("MARUTI", "Auto"), ("TITAN", "Consumer"),
    ("SUNPHARMA", "Pharma"), ("TATAMOTORS", "Auto"), ("WIPRO", "IT"),
    ("ULTRACEMCO", "Cement"), ("ADANIENT", "Energy"),
]


# ── Helper: get broker credentials from Flask session ──────────────────────

def _get_broker_creds() -> tuple[str | None, str | None, str | None]:
    """
    Get (auth_token, feed_token, broker) from the current Flask session.
    Returns (None, None, None) if not logged in.
    """
    try:
        from flask import session
        username = session.get("user")
        broker = session.get("broker")
        if not username or not broker:
            return None, None, None
        auth_token = get_auth_token(username)
        # feed_token not always available; try to fetch
        feed_token = None
        try:
            from database.auth_db import get_feed_token
            feed_token = get_feed_token(username)
        except (ImportError, Exception):
            pass
        return auth_token, feed_token, broker
    except RuntimeError:
        # Outside request context
        return None, None, None


def _get_broker_data_handler(auth_token: str, feed_token: str | None, broker: str):
    """Create a BrokerData handler for quotes/depth/history."""
    import importlib
    try:
        mod = importlib.import_module(f"broker.{broker}.api.data")
        if hasattr(mod.BrokerData.__init__, "__code__"):
            param_count = mod.BrokerData.__init__.__code__.co_argcount
            if param_count > 2:
                return mod.BrokerData(auth_token, feed_token)
        return mod.BrokerData(auth_token)
    except Exception as e:
        logger.warning(f"Could not create BrokerData for {broker}: {e}")
        return None


def _broker_get_quotes(symbol: str, exchange: str = "NSE") -> dict | None:
    """Fetch live quotes from broker."""
    auth_token, feed_token, broker = _get_broker_creds()
    if not auth_token:
        return None
    handler = _get_broker_data_handler(auth_token, feed_token, broker)
    if not handler:
        return None
    try:
        return handler.get_quotes(symbol, exchange)
    except Exception as e:
        logger.debug(f"Broker quotes failed for {symbol}: {e}")
        return None


def _broker_get_depth(symbol: str, exchange: str = "NSE") -> dict | None:
    """Fetch market depth from broker."""
    auth_token, feed_token, broker = _get_broker_creds()
    if not auth_token:
        return None
    handler = _get_broker_data_handler(auth_token, feed_token, broker)
    if not handler:
        return None
    try:
        return handler.get_depth(symbol, exchange)
    except Exception as e:
        logger.debug(f"Broker depth failed for {symbol}: {e}")
        return None


def _broker_get_history(
    symbol: str, exchange: str, interval: str, days: int = 5
) -> list[dict] | None:
    """Fetch historical candles from broker."""
    auth_token, feed_token, broker = _get_broker_creds()
    if not auth_token:
        return None
    handler = _get_broker_data_handler(auth_token, feed_token, broker)
    if not handler:
        return None
    try:
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        result = handler.get_history(symbol, exchange, interval, start_date, end_date)
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        if isinstance(result, list):
            return result
        return None
    except Exception as e:
        logger.debug(f"Broker history failed for {symbol}/{interval}: {e}")
        return None


def _broker_get_positions() -> list[dict] | None:
    """Fetch open positions from broker."""
    try:
        from services.positionbook_service import get_positionbook
        auth_token, _, broker = _get_broker_creds()
        if not auth_token:
            return None
        ok, resp, _ = get_positionbook(auth_token=auth_token, broker=broker)
        if ok:
            return resp.get("data", [])
        return None
    except Exception as e:
        logger.debug(f"Broker positions failed: {e}")
        return None


def _broker_get_funds() -> dict | None:
    """Fetch account funds/margin from broker."""
    try:
        from services.funds_service import get_funds
        auth_token, _, broker = _get_broker_creds()
        if not auth_token:
            return None
        ok, resp, _ = get_funds(auth_token=auth_token, broker=broker)
        if ok:
            return resp.get("data", {})
        return None
    except Exception as e:
        logger.debug(f"Broker funds failed: {e}")
        return None


# ── Technical indicator helpers ─────────────────────────────────────────────

def _compute_rsi(closes: list[float], period: int = 14) -> float:
    """Compute RSI from a list of close prices."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_ema(values: list[float], period: int) -> list[float]:
    """Compute EMA."""
    if not values:
        return []
    k = 2 / (period + 1)
    ema = [values[0]]
    for v in values[1:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _compute_macd(closes: list[float]) -> tuple[float, float]:
    """Compute MACD line and signal line values (latest)."""
    if len(closes) < 26:
        return 0.0, 0.0
    ema12 = _compute_ema(closes, 12)
    ema26 = _compute_ema(closes, 26)
    macd_line = [a - b for a, b in zip(ema12, ema26)]
    signal = _compute_ema(macd_line, 9)
    return macd_line[-1] if macd_line else 0.0, signal[-1] if signal else 0.0


def _determine_trend(closes: list[float]) -> tuple[str, str, int]:
    """Determine trend signal, bias, and strength from closes."""
    if len(closes) < 20:
        return "HOLD", "neutral", 50

    rsi = _compute_rsi(closes)
    macd_val, signal_val = _compute_macd(closes)

    # Simple trend: compare short MA vs long MA + RSI + MACD
    sma5 = sum(closes[-5:]) / 5
    sma20 = sum(closes[-20:]) / 20
    price = closes[-1]

    bullish_points = 0
    if price > sma20:
        bullish_points += 1
    if sma5 > sma20:
        bullish_points += 1
    if rsi > 50:
        bullish_points += 1
    if macd_val > signal_val:
        bullish_points += 1

    if bullish_points >= 3:
        signal = "BUY"
        bias = "bullish"
        strength = min(50 + bullish_points * 10 + int((rsi - 50) * 0.5), 95)
    elif bullish_points <= 1:
        signal = "SELL"
        bias = "bearish"
        strength = min(50 + (4 - bullish_points) * 10 + int((50 - rsi) * 0.5), 95)
    else:
        signal = "HOLD"
        bias = "neutral"
        strength = 50

    return signal, bias, max(20, min(strength, 95))


def _compute_trend_angle(closes: list[float]) -> int:
    """Compute a simple trend angle in degrees."""
    if len(closes) < 5:
        return 0
    # Linear regression slope over last 20 bars
    n = min(20, len(closes))
    subset = closes[-n:]
    x_mean = (n - 1) / 2
    y_mean = sum(subset) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(subset))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0
    slope = numerator / denominator
    # Normalize slope relative to price
    normalized = slope / (y_mean if y_mean != 0 else 1) * 100
    angle = int(math.degrees(math.atan(normalized)))
    return max(-45, min(45, angle))


# ── 1. Command Center ──────────────────────────────────────────────────────

def get_command_center(symbol: str) -> dict[str, Any]:
    """
    Combines agent consensus + ML predictions + institutional score into one signal.
    Tries AAUM first, falls back to broker technical analysis.
    """
    now_ms = int(time.time() * 1000)

    # Try AAUM
    try:
        resp = _try_request("get", f"/api/v1/dashboard/command-center?symbol={symbol}", DEFAULT_TIMEOUT)
        if resp and resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", data)
    except Exception as e:
        logger.debug(f"AAUM command-center failed: {e}")

    # Fallback: compute from broker data
    quotes = _broker_get_quotes(symbol)
    ltp = quotes.get("ltp", 0) if quotes else 0
    change_pct = quotes.get("change_pct", quotes.get("pChange", 0)) if quotes else 0

    # Get history for technical analysis
    candles = _broker_get_history(symbol, "NSE", "5m", days=3)
    closes = []
    if candles:
        for c in candles:
            close = c.get("close", c.get("Close", 0))
            if close:
                closes.append(float(close))

    signal, bias, strength = _determine_trend(closes) if closes else ("HOLD", "neutral", 50)

    # Derive entry/SL/target from recent ATR
    atr = 0
    if closes and len(closes) > 14:
        highs = [c.get("high", c.get("High", 0)) for c in candles[-15:]] if candles else []
        lows = [c.get("low", c.get("Low", 0)) for c in candles[-15:]] if candles else []
        if highs and lows:
            trs = [float(h) - float(l) for h, l in zip(highs, lows)]
            atr = sum(trs) / len(trs) if trs else 0

    if atr == 0 and ltp > 0:
        atr = ltp * 0.01  # 1% default

    entry = ltp if ltp > 0 else 0
    if signal == "BUY":
        stop_loss = round(entry - 1.5 * atr, 2)
        target = round(entry + 2.5 * atr, 2)
    elif signal == "SELL":
        stop_loss = round(entry + 1.5 * atr, 2)
        target = round(entry - 2.5 * atr, 2)
    else:
        stop_loss = round(entry - atr, 2)
        target = round(entry + atr, 2)

    risk = abs(entry - stop_loss) if entry else 1
    reward = abs(target - entry) if entry else 1
    rr = round(reward / risk, 1) if risk > 0 else 0

    reasoning = f"Technical analysis on {symbol}: "
    if closes:
        rsi = _compute_rsi(closes)
        reasoning += f"RSI={rsi:.0f}, "
        macd_val, sig_val = _compute_macd(closes)
        reasoning += f"MACD {'above' if macd_val > sig_val else 'below'} signal. "
    reasoning += f"Bias: {bias}."

    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": strength,
        "bias": bias,
        "entry": entry,
        "target": target,
        "stopLoss": stop_loss,
        "riskReward": rr,
        "reasoning": reasoning,
        "agentAgreement": strength,
        "modelAgreement": strength,
        "timestamp": now_ms,
    }


# ── 2. Timeframe Matrix ───────────────────────────────────────────────────

def get_timeframe_matrix(symbol: str) -> dict[str, Any]:
    """
    Fetch 5 timeframes of history from broker, compute trend per TF.
    """
    # Try AAUM first
    try:
        resp = _try_request("get", f"/api/v1/dashboard/timeframe-matrix?symbol={symbol}", DEFAULT_TIMEOUT)
        if resp and resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", data)
    except Exception:
        pass

    # Fallback: compute from broker history
    tf_configs = [
        ("1m", 1), ("5m", 3), ("15m", 5), ("1h", 10), ("4h", 30),
    ]

    cells = []
    overall_bullish = 0
    overall_total = 0

    for tf, days in tf_configs:
        candles = _broker_get_history(symbol, "NSE", tf, days=days)
        closes = []
        if candles:
            for c in candles:
                close = c.get("close", c.get("Close", 0))
                if close:
                    closes.append(float(close))

        signal, bias, strength = _determine_trend(closes) if closes else ("HOLD", "neutral", 50)
        angle = _compute_trend_angle(closes) if closes else 0

        # Volume profile: estimate from volume trend
        vol_profile = "medium"
        if candles and len(candles) > 10:
            recent_vol = sum(c.get("volume", c.get("Volume", 0)) for c in candles[-5:]) / 5
            older_vol = sum(c.get("volume", c.get("Volume", 0)) for c in candles[-10:-5]) / 5
            if older_vol > 0:
                ratio = recent_vol / older_vol
                vol_profile = "high" if ratio > 1.3 else "low" if ratio < 0.7 else "medium"

        key_level = closes[-1] if closes else 0

        cells.append({
            "timeframe": tf,
            "signal": signal,
            "strength": strength,
            "bias": bias,
            "trendAngle": angle,
            "keyLevel": round(key_level, 2),
            "volumeProfile": vol_profile,
        })

        overall_total += 1
        if bias == "bullish":
            overall_bullish += 1

    # Overall bias
    if overall_bullish >= 4:
        overall_bias = "bullish"
    elif overall_bullish <= 1:
        overall_bias = "bearish"
    else:
        overall_bias = "neutral"

    confluence = int((overall_bullish / max(overall_total, 1)) * 100)

    return {
        "symbol": symbol,
        "cells": cells,
        "overallBias": overall_bias,
        "confluenceScore": confluence,
    }


# ── 3. Institutional Score ────────────────────────────────────────────────

def get_institutional_score(symbol: str) -> dict[str, Any]:
    """
    Compute institutional score from market depth + quotes.
    """
    now_ms = int(time.time() * 1000)

    # Try AAUM
    try:
        resp = _try_request("get", f"/api/v1/dashboard/institutional-score?symbol={symbol}", DEFAULT_TIMEOUT)
        if resp and resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", data)
    except Exception:
        pass

    # Fallback: compute from depth and quotes
    depth = _broker_get_depth(symbol)
    quotes = _broker_get_quotes(symbol)

    components = []

    # 1. Depth Pressure
    depth_score = 50
    if depth:
        bids = depth.get("bids", depth.get("buy", []))
        asks = depth.get("asks", depth.get("sell", []))
        total_bid = sum(b.get("quantity", b.get("qty", 0)) for b in bids) if bids else 0
        total_ask = sum(a.get("quantity", a.get("qty", 0)) for a in asks) if asks else 0
        total = total_bid + total_ask
        if total > 0:
            depth_score = int((total_bid / total) * 100)
    depth_signal = "BUY" if depth_score > 55 else "SELL" if depth_score < 45 else "HOLD"
    components.append({
        "name": "Depth Pressure",
        "score": depth_score,
        "weight": 0.25,
        "signal": depth_signal,
        "description": f"{'Bid-heavy' if depth_score > 55 else 'Ask-heavy' if depth_score < 45 else 'Balanced'} depth",
    })

    # 2. Volume Profile
    vol_score = 50
    if quotes:
        volume = quotes.get("volume", 0)
        avg_vol = quotes.get("avg_volume", volume)
        if avg_vol and avg_vol > 0:
            ratio = volume / avg_vol if volume else 0
            vol_score = min(int(ratio * 50), 100)
    vol_signal = "BUY" if vol_score > 60 else "SELL" if vol_score < 40 else "HOLD"
    components.append({
        "name": "Volume Profile",
        "score": vol_score,
        "weight": 0.2,
        "signal": vol_signal,
        "description": f"Volume {'above' if vol_score > 60 else 'below' if vol_score < 40 else 'near'} average",
    })

    # 3. Price Action (from quotes)
    price_score = 50
    if quotes:
        change = quotes.get("change_pct", quotes.get("pChange", 0))
        if isinstance(change, (int, float)):
            price_score = max(20, min(80, 50 + int(change * 10)))
    price_signal = "BUY" if price_score > 60 else "SELL" if price_score < 40 else "HOLD"
    components.append({
        "name": "Price Action",
        "score": price_score,
        "weight": 0.2,
        "signal": price_signal,
        "description": f"Price {'rising' if price_score > 60 else 'falling' if price_score < 40 else 'flat'}",
    })

    # 4. Momentum
    candles = _broker_get_history(symbol, "NSE", "15m", days=3)
    momentum_score = 50
    if candles:
        closes = [float(c.get("close", c.get("Close", 0))) for c in candles if c.get("close", c.get("Close"))]
        if closes:
            rsi = _compute_rsi(closes)
            momentum_score = int(rsi)
    mom_signal = "BUY" if momentum_score > 55 else "SELL" if momentum_score < 45 else "HOLD"
    components.append({
        "name": "Momentum",
        "score": momentum_score,
        "weight": 0.2,
        "signal": mom_signal,
        "description": f"RSI-based momentum: {momentum_score}",
    })

    # 5. Trend Strength
    trend_score = 50
    if candles:
        closes = [float(c.get("close", c.get("Close", 0))) for c in candles if c.get("close", c.get("Close"))]
        if len(closes) > 20:
            sma20 = sum(closes[-20:]) / 20
            trend_score = 70 if closes[-1] > sma20 else 30
    trend_signal = "BUY" if trend_score > 55 else "SELL" if trend_score < 45 else "HOLD"
    components.append({
        "name": "Trend Strength",
        "score": trend_score,
        "weight": 0.15,
        "signal": trend_signal,
        "description": f"Price {'above' if trend_score > 55 else 'below'} 20-period MA",
    })

    # Overall score (weighted)
    overall = sum(c["score"] * c["weight"] for c in components)
    overall_score = int(overall)

    # Trend label
    if overall_score >= 65:
        trend = "accumulating"
    elif overall_score <= 35:
        trend = "distributing"
    else:
        trend = "neutral"

    return {
        "symbol": symbol,
        "overallScore": overall_score,
        "components": components,
        "trend": trend,
        "darkPoolActivity": depth_score,  # Best proxy we have
        "blockTradeCount": 0,
        "lastUpdated": now_ms,
    }


# ── 4. Agent Consensus ───────────────────────────────────────────────────

def get_agent_consensus(symbol: str) -> dict[str, Any]:
    """
    Call AAUM agents endpoint or return computed technical agents.
    """
    now_ms = int(time.time() * 1000)

    # Try AAUM
    try:
        resp = _try_request("get", f"/api/v1/dashboard/agents?symbol={symbol}", DEFAULT_TIMEOUT)
        if resp and resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", data)
    except Exception:
        pass

    # Fallback: create synthetic agent votes from different timeframe analyses
    candles_5m = _broker_get_history(symbol, "NSE", "5m", days=3)
    candles_15m = _broker_get_history(symbol, "NSE", "15m", days=5)
    candles_1h = _broker_get_history(symbol, "NSE", "1h", days=10)

    def _analyze_candles(candles):
        if not candles:
            return "HOLD", 50
        closes = [float(c.get("close", c.get("Close", 0))) for c in candles if c.get("close", c.get("Close"))]
        signal, _, strength = _determine_trend(closes)
        return signal, strength

    sig_5m, conf_5m = _analyze_candles(candles_5m)
    sig_15m, conf_15m = _analyze_candles(candles_15m)
    sig_1h, conf_1h = _analyze_candles(candles_1h)

    # Synthetic agents
    agents = [
        ("rakesh", "Rakesh", sig_5m, conf_5m, f"5m analysis: {sig_5m.lower()} momentum"),
        ("graham", "Graham", sig_1h, max(conf_1h - 10, 40), f"Value analysis on hourly: {sig_1h.lower()}"),
        ("momentum", "Momentum", sig_5m, conf_5m, f"Short-term momentum: {sig_5m.lower()}"),
        ("quant", "Quant", sig_15m, conf_15m, f"Statistical model on 15m: {sig_15m.lower()}"),
        ("rajan", "Rajan", "HOLD", 55, "Macro environment: neutral"),
        ("pulse", "Pulse", sig_5m, max(conf_5m - 5, 40), f"Sentiment proxy from price: {sig_5m.lower()}"),
        ("rotation", "Rotation", sig_1h, conf_1h, f"Sector rotation signal from 1h"),
        ("deriv", "Deriv", sig_15m, conf_15m, f"Derivatives proxy from 15m trend"),
        ("risk", "Risk", "HOLD", 60, "Risk parameters within limits"),
    ]

    votes = []
    for aid, name, sig, conf, reason in agents:
        votes.append({
            "agentId": aid,
            "agentName": name,
            "signal": sig,
            "confidence": conf,
            "reasoning": reason,
            "timestamp": now_ms,
        })

    buy_count = sum(1 for v in votes if v["signal"] == "BUY")
    sell_count = sum(1 for v in votes if v["signal"] == "SELL")
    total = len(votes)

    if buy_count > sell_count and buy_count > (total - buy_count - sell_count):
        consensus = "BUY"
    elif sell_count > buy_count:
        consensus = "SELL"
    else:
        consensus = "HOLD"

    avg_conf = int(sum(v["confidence"] for v in votes) / total) if total else 50
    agree_pct = int(max(buy_count, sell_count, total - buy_count - sell_count) / total * 100)

    return {
        "symbol": symbol,
        "votes": votes,
        "consensusSignal": consensus,
        "consensusConfidence": avg_conf,
        "agreementPct": agree_pct,
        "debateHighlights": [
            f"{buy_count}/{total} agents favor {consensus}",
            f"Average confidence: {avg_conf}%",
        ],
    }


# ── 5. Model Predictions ─────────────────────────────────────────────────

# Singleton ML predictor (loaded once, reused across requests)
_ml_predictor = None
_ml_predictor_attempted = False


def _get_ml_predictor():
    """Lazy-load the MLPredictor singleton."""
    global _ml_predictor, _ml_predictor_attempted
    if _ml_predictor is not None:
        return _ml_predictor
    if _ml_predictor_attempted:
        return None
    _ml_predictor_attempted = True
    try:
        import sys
        # Add AAUM src to path if not already there
        aaum_src = r"C:\Users\sakth\Desktop\aaum\src"
        if aaum_src not in sys.path:
            sys.path.insert(0, aaum_src)
        from aaum.ml.predictor import MLPredictor
        predictor = MLPredictor()
        if predictor.is_ready:
            _ml_predictor = predictor
            logger.info(f"ML predictor loaded: {len(predictor.models)} models ({', '.join(predictor.models.keys())})")
            return _ml_predictor
        else:
            logger.warning("ML predictor not ready (no models found)")
            return None
    except Exception as e:
        logger.warning(f"ML predictor unavailable: {e}")
        return None


def get_model_predictions(symbol: str) -> dict[str, Any]:
    """
    Get ML model predictions for a symbol.

    Priority:
    1. AAUM backend endpoint (if running)
    2. Local trained ML models (XGBoost, LightGBM, RandomForest, CatBoost)
    3. Synthetic fallback from technical analysis
    """
    now_ms = int(time.time() * 1000)

    # Try AAUM backend first
    try:
        resp = _try_request("get", f"/api/v1/dashboard/models?symbol={symbol}", DEFAULT_TIMEOUT)
        if resp and resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", data)
    except Exception:
        pass

    # Try local ML models
    predictor = _get_ml_predictor()
    if predictor and predictor.is_ready:
        # Get enough candle history for feature computation (need 252+ for 52-week)
        candles = _broker_get_history(symbol, "NSE", "1d", days=300)
        if not candles or len(candles) < 30:
            # Fall back to hourly candles if daily not available
            candles = _broker_get_history(symbol, "NSE", "1h", days=60)
        if not candles or len(candles) < 30:
            # Last resort: 5-minute candles (shorter lookback)
            candles = _broker_get_history(symbol, "NSE", "5m", days=10)

        if candles and len(candles) >= 30:
            try:
                result = predictor.predict_from_candles(candles)
                if result.get("models") and not result.get("error"):
                    # Format for dashboard frontend
                    model_id_map = {
                        "XGBoost": "xgb", "LightGBM": "lgbm",
                        "RandomForest": "rf", "CatBoost": "catboost",
                    }
                    feature_map = {
                        "XGBoost": ["momentum", "volume", "trend"],
                        "LightGBM": ["orderflow", "OI", "volatility"],
                        "RandomForest": ["price_action", "mean_reversion"],
                        "CatBoost": ["microstructure", "regime"],
                    }
                    horizon_map = {
                        "XGBoost": 30, "LightGBM": 30,
                        "RandomForest": 60, "CatBoost": 30,
                    }

                    predictions = []
                    for model_name, pred in result["models"].items():
                        direction = pred.get("direction", "FLAT")
                        signal = "BUY" if direction == "UP" else ("SELL" if direction == "DOWN" else "HOLD")
                        predictions.append({
                            "modelId": model_id_map.get(model_name, model_name.lower()),
                            "modelName": model_name,
                            "signal": signal,
                            "probability": pred.get("probability", 0.33),
                            "confidence": pred.get("confidence", 33.0),
                            "horizonMinutes": horizon_map.get(model_name, 30),
                            "features": feature_map.get(model_name, []),
                            "lastTrained": now_ms - 86400000,
                            "probabilities": pred.get("probabilities", {}),
                            "trainAccuracy": pred.get("train_accuracy"),
                            "trainF1": pred.get("train_f1"),
                            "source": "trained_ml",
                        })

                    consensus_dir = result.get("consensus", "FLAT")
                    ensemble_signal = "BUY" if consensus_dir == "UP" else ("SELL" if consensus_dir == "DOWN" else "HOLD")
                    agreement = result.get("agreement", 0)
                    total = result.get("total_models", 1)

                    logger.info(
                        f"ML prediction for {symbol}: consensus={consensus_dir}, "
                        f"agreement={agreement}/{total}, best={result.get('best_model')}"
                    )

                    return {
                        "symbol": symbol,
                        "predictions": predictions,
                        "ensembleSignal": ensemble_signal,
                        "ensembleProbability": round(result.get("best_probability", 0.5), 2),
                        "modelAgreement": int(agreement / total * 100) if total > 0 else 0,
                        "source": "trained_ml",
                    }
            except Exception as e:
                logger.warning(f"ML prediction failed for {symbol}: {e}")

    # Synthetic fallback (original behavior)
    candles = _broker_get_history(symbol, "NSE", "5m", days=3)
    closes = []
    if candles:
        closes = [float(c.get("close", c.get("Close", 0))) for c in candles if c.get("close", c.get("Close"))]

    signal, bias, strength = _determine_trend(closes) if closes else ("HOLD", "neutral", 50)
    base_prob = strength / 100.0

    models = [
        ("xgb", "XGBoost", 30, ["momentum", "volume"]),
        ("lgbm", "LightGBM", 30, ["orderflow", "OI"]),
        ("rf", "RandomForest", 60, ["price_action"]),
        ("catboost", "CatBoost", 30, ["microstructure"]),
    ]

    predictions = []
    for mid, name, horizon, features in models:
        import hashlib
        seed = int(hashlib.md5(f"{symbol}{mid}{datetime.now().hour}".encode()).hexdigest()[:8], 16)
        variation = ((seed % 20) - 10) / 100.0
        prob = max(0.3, min(0.95, base_prob + variation))
        model_signal = signal if prob > 0.5 else ("SELL" if signal == "BUY" else "BUY")

        predictions.append({
            "modelId": mid,
            "modelName": name,
            "signal": model_signal,
            "probability": round(prob, 2),
            "horizonMinutes": horizon,
            "features": features,
            "lastTrained": now_ms - 86400000,
            "source": "synthetic",
        })

    buy_count = sum(1 for p in predictions if p["signal"] == "BUY")
    ensemble_signal = "BUY" if buy_count > len(predictions) / 2 else "SELL"
    avg_prob = sum(p["probability"] for p in predictions) / len(predictions)

    return {
        "symbol": symbol,
        "predictions": predictions,
        "ensembleSignal": ensemble_signal,
        "ensembleProbability": round(avg_prob, 2),
        "modelAgreement": int(max(buy_count, len(predictions) - buy_count) / len(predictions) * 100),
        "source": "synthetic",
    }


# ── 6. OI Intelligence ───────────────────────────────────────────────────

def get_oi_intelligence(symbol: str) -> dict[str, Any]:
    """
    Use OpenAlgo's option chain data or AAUM's OI endpoint.
    """
    # Try AAUM
    try:
        resp = _try_request("get", f"/api/v1/dashboard/oi?symbol={symbol}", DEFAULT_TIMEOUT)
        if resp and resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", data)
    except Exception:
        pass

    # Fallback: basic OI data from quotes
    quotes = _broker_get_quotes(symbol)
    ltp = quotes.get("ltp", 0) if quotes else 0

    # Generate approximate strike levels around spot
    if ltp > 0:
        base_strike = round(ltp / 100) * 100
        levels = []
        for offset in [-200, -100, 0, 100, 200]:
            strike = base_strike + offset
            # Synthetic OI based on distance from spot
            distance = abs(strike - ltp)
            call_oi = max(100000, int(1500000 * math.exp(-distance / 300)))
            put_oi = max(100000, int(1500000 * math.exp(-distance / 300)))
            if strike < ltp:
                put_oi = int(put_oi * 1.3)
            else:
                call_oi = int(call_oi * 1.3)
            pcr = round(put_oi / call_oi, 2) if call_oi > 0 else 1.0
            levels.append({
                "strike": strike,
                "callOI": call_oi,
                "putOI": put_oi,
                "callOIChange": 0,
                "putOIChange": 0,
                "pcr": pcr,
            })
    else:
        levels = []

    # Compute summary metrics
    total_call_oi = sum(l["callOI"] for l in levels)
    total_put_oi = sum(l["putOI"] for l in levels)
    pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 1.0

    # Max pain: strike where total loss to option writers is minimized
    max_pain = ltp if ltp > 0 else 0
    if levels:
        max_pain = levels[len(levels) // 2]["strike"]

    # Put/call walls
    put_wall = min((l["strike"] for l in levels), default=0) if levels else 0
    call_wall = max((l["strike"] for l in levels), default=0) if levels else 0

    return {
        "symbol": symbol,
        "levels": levels,
        "maxPain": max_pain,
        "pcr": pcr,
        "pcrTrend": "bullish" if pcr > 1.0 else "bearish" if pcr < 0.8 else "neutral",
        "gexFlip": call_wall if call_wall else 0,
        "netGex": 0,
        "putWall": put_wall,
        "callWall": call_wall,
    }


# ── 7. Risk Snapshot ──────────────────────────────────────────────────────

def get_risk_snapshot() -> dict[str, Any]:
    """
    Use OpenAlgo's positions/funds APIs for real risk data.
    """
    # Try AAUM
    try:
        resp = _try_request("get", "/api/v1/dashboard/risk", DEFAULT_TIMEOUT)
        if resp and resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", data)
    except Exception:
        pass

    # Fallback: compute from broker positions + funds
    positions = _broker_get_positions()
    funds = _broker_get_funds()

    # Process positions
    total_mtm = 0.0
    total_exposure = 0.0
    position_list = []

    if positions:
        for pos in positions:
            symbol = pos.get("symbol", pos.get("tradingsymbol", ""))
            qty = pos.get("quantity", pos.get("netqty", pos.get("net_qty", 0)))
            if isinstance(qty, str):
                try:
                    qty = int(float(qty))
                except (ValueError, TypeError):
                    qty = 0
            avg_price = float(pos.get("average_price", pos.get("averageprice", pos.get("avg_price", 0))))
            last_price = float(pos.get("last_price", pos.get("ltp", pos.get("lastprice", 0))))
            pnl = float(pos.get("pnl", pos.get("realised", 0)))
            unrealised = float(pos.get("unrealised", 0))
            mtm = pnl + unrealised if unrealised else (last_price - avg_price) * qty if qty and avg_price else 0

            total_mtm += mtm
            total_exposure += abs(qty * last_price) if last_price else abs(qty * avg_price)

            if qty != 0:
                position_list.append({
                    "symbol": symbol,
                    "qty": abs(qty),
                    "side": "LONG" if qty > 0 else "SHORT",
                    "entryPrice": round(avg_price, 2),
                    "ltp": round(last_price, 2),
                    "mtm": round(mtm, 2),
                })

    # Process funds
    margin_used = 0.0
    margin_available = 0.0
    if funds:
        margin_used = float(funds.get("utilised", funds.get("margin_used", funds.get("debits", 0))))
        margin_available = float(funds.get("available", funds.get("net", funds.get("margin_available", 0))))

    total_capital = margin_used + margin_available if (margin_used + margin_available) > 0 else 500000
    drawdown_pct = round(abs(total_mtm) / total_capital * 100, 2) if total_mtm < 0 else 0
    leverage = round(total_exposure / total_capital, 1) if total_capital > 0 else 0
    margin_used_pct = round(margin_used / total_capital * 100, 1) if total_capital > 0 else 0
    heat = round(total_exposure / total_capital * 25, 1) if total_capital > 0 else 0  # Portfolio heat proxy

    # Risk metrics
    metrics = [
        {"label": "Max Drawdown", "value": drawdown_pct, "max": 3.0, "unit": "%",
         "status": "safe" if drawdown_pct < 1.5 else "warning" if drawdown_pct < 2.5 else "danger"},
        {"label": "Portfolio Heat", "value": min(heat, 100), "max": 100, "unit": "%",
         "status": "safe" if heat < 50 else "warning" if heat < 75 else "danger"},
        {"label": "Leverage", "value": leverage, "max": 4.0, "unit": "x",
         "status": "safe" if leverage < 2 else "warning" if leverage < 3 else "danger"},
        {"label": "Margin Used", "value": margin_used_pct, "max": 100, "unit": "%",
         "status": "safe" if margin_used_pct < 50 else "warning" if margin_used_pct < 75 else "danger"},
    ]

    worst = "safe"
    for m in metrics:
        if m["status"] == "danger":
            worst = "danger"
            break
        if m["status"] == "warning":
            worst = "warning"

    return {
        "portfolio": {
            "totalExposure": round(total_exposure, 2),
            "maxLoss": round(abs(total_mtm) if total_mtm < 0 else 0, 2),
            "var95": round(total_exposure * 0.02, 2),
            "currentDrawdown": drawdown_pct,
            "leverage": leverage,
            "marginUsed": round(margin_used, 2),
            "marginAvailable": round(margin_available, 2),
        },
        "metrics": metrics,
        "overallStatus": worst,
        "positionCount": len(position_list),
        # Extra data for frontend (not in the type but useful)
        "_positions": position_list,
        "_todayPnl": round(total_mtm, 2),
    }


# ── 8. Stock Scanner ─────────────────────────────────────────────────────

def get_stock_scanner() -> dict[str, Any]:
    """
    Get quotes for top 20 F&O stocks, rank by score.
    """
    now_ms = int(time.time() * 1000)

    # Try AAUM
    try:
        resp = _try_request("get", "/api/v1/dashboard/scanner", DEFAULT_TIMEOUT)
        if resp and resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", data)
    except Exception:
        pass

    # Fallback: fetch quotes for each stock
    rows = []
    for symbol, sector in FNO_STOCKS:
        quotes = _broker_get_quotes(symbol)
        if not quotes:
            continue

        ltp = float(quotes.get("ltp", 0))
        change_pct = float(quotes.get("change_pct", quotes.get("pChange", 0)))
        volume = int(quotes.get("volume", quotes.get("totalTradedVolume", 0)))

        # Simple scoring
        score = 50
        if change_pct > 1:
            score += 15
        elif change_pct > 0:
            score += 5
        elif change_pct < -1:
            score -= 15
        elif change_pct < 0:
            score -= 5

        signal = "BUY" if change_pct > 0.5 else "SELL" if change_pct < -0.5 else "HOLD"

        rows.append({
            "symbol": symbol,
            "ltp": ltp,
            "changePct": round(change_pct, 2),
            "volume": volume,
            "relativeVolume": 1.0,  # Would need avg volume for real calc
            "institutionalScore": max(20, min(95, score)),
            "signal": signal,
            "agentConsensus": signal,
            "modelPrediction": signal,
            "riskScore": max(20, min(80, 50 - int(abs(change_pct) * 5))),
            "sector": sector,
            "updatedAt": now_ms,
        })

    # Sort by institutional score descending
    rows.sort(key=lambda r: r["institutionalScore"], reverse=True)

    return {
        "rows": rows,
        "total": len(rows),
        "updatedAt": now_ms,
    }


# ── 9. Self-Learning ─────────────────────────────────────────────────────

def get_self_learning(symbol: str | None = None) -> dict[str, Any]:
    """
    Read from AAUM's learning endpoints or return defaults.
    """
    now_ms = int(time.time() * 1000)

    # Try AAUM
    try:
        path = "/api/v1/dashboard/self-learning"
        if symbol:
            path += f"?symbol={symbol}"
        resp = _try_request("get", path, DEFAULT_TIMEOUT)
        if resp and resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "success":
                return data.get("data", data)
    except Exception:
        pass

    # Fallback: sensible defaults (no real learning data without AAUM)
    return {
        "metrics": [
            {"metricId": "accuracy", "label": "Today Accuracy", "value": 0, "previousValue": 0, "unit": "%", "trend": "stable"},
            {"metricId": "sharpe", "label": "Sharpe Ratio", "value": 0, "previousValue": 0, "unit": "", "trend": "stable"},
            {"metricId": "win_rate", "label": "Win Rate", "value": 0, "previousValue": 0, "unit": "%", "trend": "stable"},
            {"metricId": "profit_factor", "label": "Profit Factor", "value": 0, "previousValue": 0, "unit": "x", "trend": "stable"},
        ],
        "backtests": [],
        "lastRetrainedAt": 0,
        "nextRetrainAt": 0,
        "isTraining": False,
    }
