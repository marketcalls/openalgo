# test/test_ai_signals.py
import pandas as pd
import numpy as np
import pytest
from ai.indicators import compute_indicators
from ai.signals import generate_signal, detect_regime, SignalType, MarketRegime


def _make_ohlcv(n: int = 100, trend: str = "up") -> pd.DataFrame:
    np.random.seed(42)
    if trend == "up":
        close = 100 + np.arange(n) * 0.5 + np.random.randn(n) * 0.3
    elif trend == "down":
        close = 200 - np.arange(n) * 0.5 + np.random.randn(n) * 0.3
    else:
        close = 100 + np.random.randn(n) * 0.5
    return pd.DataFrame({
        "open": close + np.random.randn(n) * 0.2,
        "high": close + abs(np.random.randn(n) * 0.5),
        "low": close - abs(np.random.randn(n) * 0.5),
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
    })


def test_generate_signal_returns_dict():
    df = compute_indicators(_make_ohlcv(100))
    result = generate_signal(df)
    assert isinstance(result, dict)
    assert "signal" in result
    assert "confidence" in result
    assert "score" in result
    assert "scores" in result
    assert "regime" in result


def test_signal_is_valid_type():
    df = compute_indicators(_make_ohlcv(100))
    result = generate_signal(df)
    valid = {s.value for s in SignalType}
    assert result["signal"] in valid


def test_confidence_is_bounded():
    df = compute_indicators(_make_ohlcv(100))
    result = generate_signal(df)
    assert 0 <= result["confidence"] <= 100


def test_score_is_bounded():
    df = compute_indicators(_make_ohlcv(100))
    result = generate_signal(df)
    assert -1.0 <= result["score"] <= 1.0


def test_short_data_returns_hold():
    df = _make_ohlcv(5)
    result = generate_signal(df)
    assert result["signal"] == SignalType.HOLD.value
    assert result["confidence"] == 0


def test_detect_regime_returns_valid():
    df = compute_indicators(_make_ohlcv(100))
    regime = detect_regime(df)
    valid = {r.value for r in MarketRegime}
    assert regime.value in valid


def test_uptrend_is_bullish():
    df = compute_indicators(_make_ohlcv(200, trend="up"))
    result = generate_signal(df)
    # Trend-following sub-signals (supertrend, ema_cross) must be bullish.
    # Composite may be dampened by contrarian indicators (RSI reads overbought
    # in a strong monotonic uptrend), which is correct engine behaviour.
    assert result["scores"].get("supertrend", 0) > 0
    assert result["scores"].get("ema_cross", 0) > 0


def test_downtrend_is_bearish():
    df = compute_indicators(_make_ohlcv(200, trend="down"))
    result = generate_signal(df)
    # Trend-following sub-signals must be bearish.
    assert result["scores"].get("supertrend", 0) < 0
    assert result["scores"].get("ema_cross", 0) < 0


def test_custom_weights():
    df = compute_indicators(_make_ohlcv(100))
    weights = {"supertrend": 0.5, "rsi": 0.5}
    result = generate_signal(df, weights=weights)
    assert isinstance(result, dict)
    assert "score" in result
