# test/test_ai_indicators.py
import pandas as pd
import numpy as np
import pytest
from ai.indicators import compute_indicators


def _make_ohlcv(n: int = 100) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing."""
    np.random.seed(42)
    close = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "open": close + np.random.randn(n) * 0.2,
        "high": close + abs(np.random.randn(n) * 0.5),
        "low": close - abs(np.random.randn(n) * 0.5),
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
    })


def test_returns_dataframe():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert isinstance(result, pd.DataFrame)


def test_adds_rsi_column():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert "rsi_14" in result.columns


def test_adds_macd_columns():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert "macd" in result.columns
    assert "macd_signal" in result.columns
    assert "macd_hist" in result.columns


def test_adds_ema_columns():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert "ema_9" in result.columns
    assert "ema_21" in result.columns


def test_adds_bollinger_columns():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert "bb_high" in result.columns
    assert "bb_low" in result.columns
    assert "bb_pband" in result.columns


def test_adds_supertrend_columns():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert "supertrend" in result.columns
    assert "supertrend_dir" in result.columns


def test_adds_adx_column():
    df = _make_ohlcv(100)
    result = compute_indicators(df)
    assert "adx_14" in result.columns


def test_handles_short_data():
    df = _make_ohlcv(5)
    result = compute_indicators(df)
    assert isinstance(result, pd.DataFrame)
    assert len(result) == 5


def test_does_not_mutate_input():
    df = _make_ohlcv(50)
    original_cols = list(df.columns)
    compute_indicators(df)
    assert list(df.columns) == original_cols


def test_no_exceptions_on_edge_case():
    df = pd.DataFrame({
        "open": [100.0], "high": [101.0], "low": [99.0],
        "close": [100.5], "volume": [1000.0],
    })
    result = compute_indicators(df)
    assert isinstance(result, pd.DataFrame)
