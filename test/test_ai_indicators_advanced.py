import pandas as pd
import numpy as np
import pytest
from ai.indicators_advanced import (
    compute_smc_indicators,
    compute_candlestick_patterns,
    compute_cpr_levels,
    compute_fibonacci_levels,
    compute_harmonic_patterns,
    compute_rsi_divergence,
    compute_volume_signals,
)


def _make_ohlcv(n: int = 200, trend: str = "up") -> pd.DataFrame:
    rng = np.random.default_rng(42)
    if trend == "up":
        close = 100 + np.arange(n) * 0.3 + rng.standard_normal(n) * 0.5
    elif trend == "down":
        close = 200 - np.arange(n) * 0.3 + rng.standard_normal(n) * 0.5
    else:
        close = 100 + rng.standard_normal(n) * 1.0
    return pd.DataFrame({
        "open": close + rng.standard_normal(n) * 0.2,
        "high": close + abs(rng.standard_normal(n) * 0.8),
        "low": close - abs(rng.standard_normal(n) * 0.8),
        "close": close,
        "volume": rng.integers(1000, 10000, size=n).astype(float),
    })


class TestSMC:
    def test_returns_dataframe(self):
        df = _make_ohlcv(200)
        result = compute_smc_indicators(df)
        assert isinstance(result, pd.DataFrame)

    def test_has_bos_columns(self):
        df = _make_ohlcv(200)
        result = compute_smc_indicators(df)
        assert "smc_bos_bullish" in result.columns
        assert "smc_bos_bearish" in result.columns

    def test_has_fvg_columns(self):
        df = _make_ohlcv(200)
        result = compute_smc_indicators(df)
        assert "smc_fvg_bullish" in result.columns
        assert "smc_fvg_bearish" in result.columns

    def test_has_ob_columns(self):
        df = _make_ohlcv(200)
        result = compute_smc_indicators(df)
        assert "smc_ob_bullish" in result.columns
        assert "smc_ob_bearish" in result.columns

    def test_has_choch_columns(self):
        df = _make_ohlcv(200)
        result = compute_smc_indicators(df)
        assert "smc_choch_bullish" in result.columns
        assert "smc_choch_bearish" in result.columns

    def test_does_not_mutate_input(self):
        df = _make_ohlcv(100)
        orig_cols = list(df.columns)
        compute_smc_indicators(df)
        assert list(df.columns) == orig_cols


class TestCandlestickPatterns:
    def test_returns_dataframe(self):
        result = compute_candlestick_patterns(_make_ohlcv(100))
        assert isinstance(result, pd.DataFrame)

    def test_has_pattern_columns(self):
        result = compute_candlestick_patterns(_make_ohlcv(100))
        expected = ["cdl_doji", "cdl_hammer", "cdl_engulfing_bull", "cdl_engulfing_bear"]
        for col in expected:
            assert col in result.columns, f"Missing {col}"

    def test_binary_values(self):
        result = compute_candlestick_patterns(_make_ohlcv(200))
        for col in result.columns:
            if col.startswith("cdl_"):
                assert set(result[col].dropna().unique()).issubset({0, 1, True, False}), f"{col} not binary"


class TestCPR:
    def test_returns_dataframe(self):
        result = compute_cpr_levels(_make_ohlcv(100))
        assert isinstance(result, pd.DataFrame)

    def test_has_pivot_columns(self):
        result = compute_cpr_levels(_make_ohlcv(100))
        for col in ["pivot", "bc", "tc", "r1", "s1", "r2", "s2"]:
            assert col in result.columns, f"Missing {col}"


class TestFibonacci:
    def test_returns_dataframe(self):
        result = compute_fibonacci_levels(_make_ohlcv(200))
        assert isinstance(result, pd.DataFrame)

    def test_has_fib_signal(self):
        result = compute_fibonacci_levels(_make_ohlcv(200))
        assert "fib_long" in result.columns
        assert "fib_short" in result.columns


class TestHarmonics:
    def test_returns_dataframe(self):
        result = compute_harmonic_patterns(_make_ohlcv(200))
        assert isinstance(result, pd.DataFrame)

    def test_has_harmonic_columns(self):
        result = compute_harmonic_patterns(_make_ohlcv(200))
        assert "harmonic_bullish" in result.columns
        assert "harmonic_bearish" in result.columns


class TestDivergence:
    def test_returns_dataframe(self):
        result = compute_rsi_divergence(_make_ohlcv(100))
        assert isinstance(result, pd.DataFrame)

    def test_has_divergence_columns(self):
        result = compute_rsi_divergence(_make_ohlcv(100))
        assert "rsi_bull_divergence" in result.columns
        assert "rsi_bear_divergence" in result.columns


class TestVolume:
    def test_returns_dataframe(self):
        result = compute_volume_signals(_make_ohlcv(100))
        assert isinstance(result, pd.DataFrame)

    def test_has_volume_columns(self):
        result = compute_volume_signals(_make_ohlcv(100))
        assert "volume_exhaustion" in result.columns
        assert "vwap_bb_confluence" in result.columns
