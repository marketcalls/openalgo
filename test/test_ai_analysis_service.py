# test/test_ai_analysis_service.py
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from services.ai_analysis_service import analyze_symbol, AnalysisResult


def _mock_ohlcv():
    np.random.seed(42)
    n = 100
    close = 100 + np.arange(n) * 0.3 + np.random.randn(n) * 0.2
    return pd.DataFrame({
        "open": close + np.random.randn(n) * 0.1,
        "high": close + abs(np.random.randn(n) * 0.3),
        "low": close - abs(np.random.randn(n) * 0.3),
        "close": close,
        "volume": np.random.randint(1000, 10000, n).astype(float),
    })


@patch("services.ai_analysis_service.fetch_ohlcv")
def test_analyze_symbol_returns_result(mock_fetch):
    from ai.data_bridge import OHLCVResult
    mock_fetch.return_value = OHLCVResult(
        success=True, df=_mock_ohlcv(),
        symbol="RELIANCE", exchange="NSE", interval="1d", error=None,
    )
    result = analyze_symbol("RELIANCE", "NSE", "1d", api_key="test")
    assert result.success is True
    assert result.signal is not None
    assert result.confidence >= 0


@patch("services.ai_analysis_service.fetch_ohlcv")
def test_analyze_symbol_handles_no_data(mock_fetch):
    from ai.data_bridge import OHLCVResult
    mock_fetch.return_value = OHLCVResult(
        success=False, df=pd.DataFrame(),
        symbol="INVALID", exchange="NSE", interval="1d", error="No data",
    )
    result = analyze_symbol("INVALID", "NSE", "1d", api_key="test")
    assert result.success is False
    assert result.error == "No data"


@patch("services.ai_analysis_service.fetch_ohlcv")
def test_analyze_symbol_includes_indicators(mock_fetch):
    from ai.data_bridge import OHLCVResult
    mock_fetch.return_value = OHLCVResult(
        success=True, df=_mock_ohlcv(),
        symbol="SBIN", exchange="NSE", interval="1d", error=None,
    )
    result = analyze_symbol("SBIN", "NSE", "1d", api_key="test")
    assert result.success is True
    assert "rsi_14" in result.latest_indicators
    assert "macd" in result.latest_indicators
