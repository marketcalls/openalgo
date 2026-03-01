# test/test_backtest_metrics.py
"""Tests for backtest performance metrics calculator."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pytest

from services.backtest_metrics import (
    _compute_monthly_returns,
    _compute_trade_metrics,
    _empty_metrics,
    _get_bars_per_year,
    calculate_metrics,
)


@pytest.fixture
def sample_equity_curve():
    """Equity curve with known drawdown pattern."""
    return [
        {"timestamp": 1704067200, "equity": 100000, "drawdown": 0.0},
        {"timestamp": 1704153600, "equity": 101000, "drawdown": 0.0},
        {"timestamp": 1704240000, "equity": 99000, "drawdown": 0.0198},
        {"timestamp": 1704326400, "equity": 102000, "drawdown": 0.0},
        {"timestamp": 1704412800, "equity": 103000, "drawdown": 0.0},
        {"timestamp": 1704499200, "equity": 100500, "drawdown": 0.0243},
        {"timestamp": 1704585600, "equity": 105000, "drawdown": 0.0},
    ]


@pytest.fixture
def sample_trades():
    """Mix of winning and losing trades."""
    return [
        {"trade_num": 1, "net_pnl": 500, "bars_held": 3, "commission": 20, "slippage_cost": 5},
        {"trade_num": 2, "net_pnl": -200, "bars_held": 2, "commission": 20, "slippage_cost": 3},
        {"trade_num": 3, "net_pnl": 800, "bars_held": 5, "commission": 20, "slippage_cost": 8},
        {"trade_num": 4, "net_pnl": -100, "bars_held": 1, "commission": 20, "slippage_cost": 2},
        {"trade_num": 5, "net_pnl": 300, "bars_held": 4, "commission": 20, "slippage_cost": 4},
    ]


class TestCalculateMetrics:
    def test_basic_metrics(self, sample_trades, sample_equity_curve):
        metrics = calculate_metrics(sample_trades, sample_equity_curve, 100000, "D")
        assert metrics["final_capital"] == 105000
        assert metrics["total_return_pct"] == 5.0
        assert metrics["total_trades"] == 5
        assert metrics["winning_trades"] == 3
        assert metrics["losing_trades"] == 2

    def test_empty_equity_curve(self):
        metrics = calculate_metrics([], [], 100000, "D")
        assert metrics["final_capital"] == 100000
        assert metrics["total_return_pct"] == 0.0
        assert metrics["total_trades"] == 0

    def test_single_bar_returns_empty(self):
        curve = [{"timestamp": 1, "equity": 100000, "drawdown": 0.0}]
        metrics = calculate_metrics([], curve, 100000, "D")
        assert metrics["total_return_pct"] == 0.0

    def test_no_trades(self, sample_equity_curve):
        metrics = calculate_metrics([], sample_equity_curve, 100000, "D")
        assert metrics["total_trades"] == 0
        assert metrics["win_rate"] == 0.0
        assert metrics["profit_factor"] == 0.0


class TestTradeMetrics:
    def test_win_rate(self, sample_trades):
        metrics = {}
        _compute_trade_metrics(metrics, sample_trades)
        assert metrics["win_rate"] == 60.0  # 3 out of 5

    def test_profit_factor(self, sample_trades):
        metrics = {}
        _compute_trade_metrics(metrics, sample_trades)
        # Gross profit = 500 + 800 + 300 = 1600
        # Gross loss = |-200| + |-100| = 300
        # PF = 1600 / 300 = 5.333
        assert round(metrics["profit_factor"], 2) == 5.33

    def test_all_winners(self):
        trades = [
            {"trade_num": 1, "net_pnl": 100, "bars_held": 1, "commission": 10, "slippage_cost": 0},
            {"trade_num": 2, "net_pnl": 200, "bars_held": 2, "commission": 10, "slippage_cost": 0},
        ]
        metrics = {}
        _compute_trade_metrics(metrics, trades)
        assert metrics["win_rate"] == 100.0
        assert metrics["profit_factor"] == 999.99  # capped infinite

    def test_no_trades(self):
        metrics = {}
        _compute_trade_metrics(metrics, [])
        assert metrics["total_trades"] == 0
        assert metrics["win_rate"] == 0.0
        assert metrics["expectancy"] == 0.0

    def test_avg_holding_bars(self, sample_trades):
        metrics = {}
        _compute_trade_metrics(metrics, sample_trades)
        # (3 + 2 + 5 + 1 + 4) / 5 = 3
        assert metrics["avg_holding_bars"] == 3


class TestBarsPerYear:
    def test_daily(self):
        assert _get_bars_per_year("D") == 252

    def test_5min(self):
        assert _get_bars_per_year("5m") == 252 * 75

    def test_1min(self):
        assert _get_bars_per_year("1m") == 252 * 375

    def test_unknown_defaults_to_daily(self):
        assert _get_bars_per_year("unknown") == 252


class TestEmptyMetrics:
    def test_has_all_keys(self):
        m = _empty_metrics(100000)
        assert "final_capital" in m
        assert "sharpe_ratio" in m
        assert "monthly_returns" in m
        assert m["final_capital"] == 100000

    def test_zero_default(self):
        m = _empty_metrics()
        assert m["final_capital"] == 0.0
