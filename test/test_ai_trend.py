import pandas as pd
import numpy as np
import pytest
from ai.trend_analysis import compute_trend_score, TrendReport


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


def test_returns_trend_report():
    result = compute_trend_score(_make_ohlcv(200))
    assert isinstance(result, TrendReport)


def test_has_required_fields():
    result = compute_trend_score(_make_ohlcv(200))
    assert 0 <= result.strength <= 100
    assert result.direction in ("bullish", "bearish", "neutral")
    assert isinstance(result.details, dict)


def test_uptrend_is_bullish():
    result = compute_trend_score(_make_ohlcv(200, "up"))
    assert result.direction == "bullish"
    assert result.strength > 40


def test_downtrend_is_bearish():
    result = compute_trend_score(_make_ohlcv(200, "down"))
    assert result.direction == "bearish"
    assert result.strength > 40


def test_sideways_is_neutral_or_weak():
    result = compute_trend_score(_make_ohlcv(200, "sideways"))
    assert result.strength < 60


def test_short_data_returns_neutral():
    result = compute_trend_score(_make_ohlcv(5))
    assert result.direction == "neutral"
    assert result.strength == 0


def test_details_has_components():
    result = compute_trend_score(_make_ohlcv(200))
    assert "adx" in result.details
    assert "ema_alignment" in result.details
    assert "supertrend" in result.details
    assert "price_vs_sma" in result.details
