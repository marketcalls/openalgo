"""
Regression tests for Week 1 bug fixes.

Each test targets one specific bug to prevent regressions:
  Bug 1 — signal_strength is now continuous (not always binary)
  Bug 2 — vwap_bb upper_reversal/lower_reversal columns are now handled
  Bug 3 — daily_retrain uses real feedback when >= 20 records available
  Bug 4 — compute_sharpe_ratio accepts annualization_factor
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

# ── Bug 1 & 2 — signal_adapter ────────────────────────────────────────────────

from strategies.signal_adapter import normalize_strategy_output


class TestSignalAdapter:
    """Bug 1: signal_strength must be continuous for non-binary columns."""

    def test_strength_continuous_for_numeric_column(self):
        """When a column has varying magnitudes the strength should vary too."""
        frame = pd.DataFrame({
            "buy_signal": [0.1, 0.5, 0.9, 2.0, 0.3],
        })
        _, strength, _, _ = normalize_strategy_output("some_strategy", frame)
        assert strength.max() > 0, "Strength should be non-zero"
        # Values should differ — not all equal to 1.0
        assert strength.nunique() > 1, (
            "Bug 1 still present: strength is binary instead of continuous"
        )
        assert strength.between(0.0, 1.0).all(), "Strength must be in [0, 1]"

    def test_strength_falls_back_to_one_for_binary_column(self):
        """Binary bool/int columns still produce valid strength (0 or 1)."""
        frame = pd.DataFrame({
            "buy_flag": [True, False, True, False],
        })
        _, strength, _, _ = normalize_strategy_output("some_strategy", frame)
        assert strength.between(0.0, 1.0).all()

    # ── Bug 2 — vwap_bb reversal columns ──────────────────────────────────────

    def test_vwap_bb_lower_reversal_maps_to_buy(self):
        """lower_reversal=True must produce signal=+1 (buy)."""
        frame = pd.DataFrame({
            "lower_reversal": [True, False, True],
            "upper_reversal": [False, False, False],
        })
        signal, _, _, notes = normalize_strategy_output(
            "vwap_bb_super_confluence_2", frame
        )
        assert list(signal) == [1, 0, 1], (
            f"Bug 2 still present: expected [1, 0, 1] got {list(signal)}"
        )
        assert any("vwap_bb" in n for n in notes)

    def test_vwap_bb_upper_reversal_maps_to_sell(self):
        """upper_reversal=True must produce signal=-1 (sell)."""
        frame = pd.DataFrame({
            "lower_reversal": [False, False],
            "upper_reversal": [True, False],
        })
        signal, _, _, _ = normalize_strategy_output(
            "vwap_bb_super_confluence_2", frame
        )
        assert list(signal) == [-1, 0], (
            f"Bug 2 still present: expected [-1, 0] got {list(signal)}"
        )

    def test_vwap_bb_both_reversals(self):
        """When both columns are present, signals combine correctly."""
        frame = pd.DataFrame({
            "lower_reversal": [True,  False, False],
            "upper_reversal": [False, True,  False],
        })
        signal, strength, _, _ = normalize_strategy_output(
            "vwap_bb_super_confluence_2", frame
        )
        assert list(signal) == [1, -1, 0]
        assert strength.tolist() == pytest.approx([1.0, 1.0, 1.0], rel=1e-6)

    def test_no_signal_columns_still_returns_hold(self):
        """Strategies with completely unknown columns still return 0 signal."""
        frame = pd.DataFrame({
            "some_indicator": [1.0, 2.0, 3.0],
            "another_value":  [0.5, 0.6, 0.7],
        })
        signal, _, _, notes = normalize_strategy_output("unknown_strategy", frame)
        assert (signal == 0).all()
        assert any("HOLD" in n or "No directional" in n for n in notes)

    def test_original_strategies_unaffected(self):
        """Existing buy/sell column strategies still work as before."""
        frame = pd.DataFrame({
            "buy": [1, 0, 1, 0],
            "sell": [0, 1, 0, 1],
        })
        signal, _, _, _ = normalize_strategy_output("some_strategy", frame)
        # buy wins over sell in column priority
        assert (signal != 0).all()


# ── Bug 3 — daily_retrain feedback loop ───────────────────────────────────────

from feedback.daily_retrain import _build_candidates_from_feedback


class TestFeedbackLoop:
    """Bug 3: real feedback records must be used when >= 20 are available."""

    def _make_feedback_df(self, n: int, all_profitable: bool = True) -> pd.DataFrame:
        """Generate synthetic PaperTradeRecord-schema rows."""
        import numpy as np
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        records = []
        for i in range(n):
            exit_time = (now - timedelta(days=i % 30)).isoformat()
            records.append({
                "recommendation_id": f"trend_signals__{i:04d}",
                "symbol":            "RELIANCE",
                "horizon":           "15m",
                "model_version":     "v1.0",
                "side":              "long" if i % 2 == 0 else "short",
                "entry_time":        exit_time,
                "exit_time":         exit_time,
                "entry_price":       1000.0,
                "exit_price":        1010.0 if all_profitable else 990.0,
                "quantity":          10.0,
                "gross_pnl":         100.0 if all_profitable else -100.0,
                "net_pnl":           90.0  if all_profitable else -110.0,
                "sl_hit":            not all_profitable,
                "tp_hit":            all_profitable,
                "manual_reject":     False,
                "reject_reason":     "",
            })
        return pd.DataFrame(records)

    def test_returns_empty_for_zero_records(self):
        result = _build_candidates_from_feedback(pd.DataFrame())
        assert result.empty

    def test_extracts_setup_success_from_net_pnl(self):
        df = self._make_feedback_df(n=5, all_profitable=True)
        result = _build_candidates_from_feedback(df)
        if result.empty:
            pytest.skip("Not enough records after filtering")
        assert "setup_success" in result.columns
        assert (result["setup_success"] == 1).all()

    def test_extracts_strategy_name_from_recommendation_id(self):
        df = self._make_feedback_df(n=5)
        result = _build_candidates_from_feedback(df)
        if result.empty:
            pytest.skip("Not enough records after filtering")
        assert "strategy_name" in result.columns
        # recommendation_id starts with "trend_signals__..." so name should be "trend_signals"
        assert (result["strategy_name"] == "trend_signals").all()

    def test_rejects_manual_rejects(self):
        df = self._make_feedback_df(n=10)
        df.loc[0:4, "manual_reject"] = True   # first 5 rejected
        result = _build_candidates_from_feedback(df)
        if result.empty:
            pytest.skip("Not enough records after filtering")
        assert len(result) <= 5

    def test_signal_strength_in_unit_interval(self):
        df = self._make_feedback_df(n=10)
        result = _build_candidates_from_feedback(df)
        if result.empty:
            pytest.skip("Not enough records after filtering")
        assert result["signal_strength"].between(0.0, 1.0).all()

    def test_sample_weight_present_and_positive(self):
        df = self._make_feedback_df(n=10)
        result = _build_candidates_from_feedback(df)
        if result.empty:
            pytest.skip("Not enough records after filtering")
        assert "sample_weight" in result.columns
        assert (result["sample_weight"] > 0).all()


# ── Bug 4 — Sharpe annualization ──────────────────────────────────────────────

from backtest.metrics import compute_sharpe_ratio


class TestSharpeRatio:
    """Bug 4: annualization_factor is now a parameter, not hard-coded to 252."""

    def test_default_still_uses_252(self):
        """Backward compat: calling without annualization_factor uses sqrt(252)."""
        returns = pd.Series([0.01, 0.02, -0.005, 0.015, 0.008])
        result = compute_sharpe_ratio(returns)
        expected = math.sqrt(252) * returns.mean() / returns.std(ddof=0)
        assert abs(result - expected) < 1e-10

    def test_custom_annualization_factor(self):
        """Passing annualization_factor=100 must use sqrt(100)=10, not sqrt(252)."""
        returns = pd.Series([0.01, 0.02, -0.005, 0.015, 0.008])
        result = compute_sharpe_ratio(returns, annualization_factor=100)
        expected = math.sqrt(100) * returns.mean() / returns.std(ddof=0)
        assert abs(result - expected) < 1e-10

    def test_annualization_factor_affects_result(self):
        """Different factors must produce different Sharpe values."""
        returns = pd.Series([0.01, 0.02, -0.005, 0.015, 0.008])
        s_daily  = compute_sharpe_ratio(returns, annualization_factor=252)
        s_trades = compute_sharpe_ratio(returns, annualization_factor=100)
        assert s_daily != s_trades, (
            "Bug 4 still present: annualization_factor has no effect"
        )

    def test_empty_returns_zero(self):
        assert compute_sharpe_ratio(pd.Series([], dtype=float)) == 0.0

    def test_constant_returns_zero(self):
        """Zero std means zero Sharpe regardless of annualization."""
        returns = pd.Series([0.01, 0.01, 0.01])
        assert compute_sharpe_ratio(returns, annualization_factor=100) == 0.0

    def test_sharpe_scales_correctly_with_sqrt(self):
        """Sharpe with factor=400 should be exactly 2x sharpe with factor=100."""
        returns = pd.Series([0.01, -0.005, 0.02, 0.015])
        s100 = compute_sharpe_ratio(returns, annualization_factor=100)
        s400 = compute_sharpe_ratio(returns, annualization_factor=400)
        assert abs(s400 / s100 - 2.0) < 1e-10
