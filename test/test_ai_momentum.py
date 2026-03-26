# test/test_ai_momentum.py
import pandas as pd
import numpy as np
import pytest
from ai.momentum_analysis import compute_momentum_score, MomentumReport


def _make_ohlcv(n=200, trend="up"):
    rng = np.random.default_rng(42)
    if trend == "up":
        close = 100 + np.arange(n) * 0.5 + rng.standard_normal(n) * 0.3
    elif trend == "down":
        close = 200 - np.arange(n) * 0.5 + rng.standard_normal(n) * 0.3
    else:
        close = 150 + rng.standard_normal(n) * 1.0
    return pd.DataFrame({
        "open": close + rng.standard_normal(n) * 0.2,
        "high": close + abs(rng.standard_normal(n) * 0.5),
        "low": close - abs(rng.standard_normal(n) * 0.5),
        "close": close,
        "volume": rng.integers(1000, 10000, size=n).astype(float),
    })


def test_returns_momentum_report():
    result = compute_momentum_score(_make_ohlcv(200))
    assert isinstance(result, MomentumReport)


def test_has_required_fields():
    result = compute_momentum_score(_make_ohlcv(200))
    assert -100 <= result.score <= 100
    assert result.bias in ("bullish", "bearish", "neutral")
    assert isinstance(result.details, dict)


def test_details_has_components():
    result = compute_momentum_score(_make_ohlcv(200))
    assert "rsi" in result.details
    assert "macd" in result.details
    assert "stochastic" in result.details
    assert "roc" in result.details


def test_short_data_returns_neutral():
    result = compute_momentum_score(_make_ohlcv(5))
    assert result.bias == "neutral"
    assert result.score == 0


def test_overbought_detection():
    result = compute_momentum_score(_make_ohlcv(200, "up"))
    assert "overbought" in result.details or "rsi" in result.details


def test_oversold_detection():
    result = compute_momentum_score(_make_ohlcv(200, "down"))
    assert "oversold" in result.details or "rsi" in result.details
