import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from ai.data_bridge import fetch_ohlcv, OHLCVResult


def test_ohlcv_result_has_required_fields():
    result = OHLCVResult(
        success=True,
        df=pd.DataFrame(),
        symbol="RELIANCE",
        exchange="NSE",
        interval="1d",
        error=None,
    )
    assert result.success is True
    assert result.symbol == "RELIANCE"


def test_fetch_ohlcv_returns_ohlcv_result():
    with patch("ai.data_bridge._call_history_service") as mock:
        mock.return_value = {
            "status": "success",
            "data": {
                "timestamp": [1700000000, 1700086400],
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [1000, 2000],
            },
        }
        result = fetch_ohlcv("RELIANCE", "NSE", "1d", api_key="test_key")
        assert result.success is True
        assert isinstance(result.df, pd.DataFrame)
        assert list(result.df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(result.df) == 2


def test_fetch_ohlcv_handles_error():
    with patch("ai.data_bridge._call_history_service") as mock:
        mock.return_value = {"status": "error", "message": "No data found"}
        result = fetch_ohlcv("INVALID", "NSE", "1d", api_key="test_key")
        assert result.success is False
        assert result.error is not None


def test_fetch_ohlcv_handles_exception():
    with patch("ai.data_bridge._call_history_service") as mock:
        mock.side_effect = Exception("Network error")
        result = fetch_ohlcv("RELIANCE", "NSE", "1d", api_key="test_key")
        assert result.success is False
        assert "Network error" in result.error
