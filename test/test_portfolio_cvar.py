"""Tests for CVaR portfolio optimisation module."""
import numpy as np
import pandas as pd
import pytest


def make_returns(n_assets=4, n_days=252):
    """Fake daily returns matrix: shape (n_days, n_assets)."""
    np.random.seed(42)
    return np.random.normal(0.001, 0.02, (n_days, n_assets))


def test_compute_cvar_basic():
    from ai.portfolio_cvar import compute_cvar
    returns = make_returns()
    weights = np.array([0.25, 0.25, 0.25, 0.25])
    result = compute_cvar(returns, weights, confidence=0.95)
    assert "cvar_95" in result
    assert "var_95" in result
    assert result["cvar_95"] < 0        # CVaR is a loss
    assert result["cvar_95"] <= result["var_95"]  # CVaR <= VaR


def test_compute_cvar_99():
    from ai.portfolio_cvar import compute_cvar
    returns = make_returns()
    weights = np.array([0.25, 0.25, 0.25, 0.25])
    result_95 = compute_cvar(returns, weights, confidence=0.95)
    result_99 = compute_cvar(returns, weights, confidence=0.99)
    assert "cvar_99" in result_99
    # 99% CVaR should be worse (more negative) than 95%
    assert result_99["cvar_99"] <= result_95["cvar_95"]


def test_optimise_min_cvar():
    from ai.portfolio_cvar import optimise_min_cvar
    returns = make_returns(n_assets=4)
    result = optimise_min_cvar(returns)
    assert "weights" in result
    assert len(result["weights"]) == 4
    assert abs(sum(result["weights"]) - 1.0) < 1e-4   # weights sum to 1
    assert all(w >= -0.01 for w in result["weights"])  # no short selling


def test_optimise_max_sharpe():
    from ai.portfolio_cvar import optimise_max_sharpe
    returns = make_returns(n_assets=4)
    result = optimise_max_sharpe(returns)
    assert "weights" in result
    assert "sharpe" in result
    assert abs(sum(result["weights"]) - 1.0) < 1e-4


def test_run_portfolio_analysis_full():
    from ai.portfolio_cvar import run_portfolio_analysis
    symbols = ["A", "B", "C"]
    returns_dict = {
        s: pd.Series(np.random.normal(0.001, 0.02, 252)) for s in symbols
    }
    result = run_portfolio_analysis(symbols=symbols, returns_dict=returns_dict)
    assert result["status"] == "success"
    assert "min_cvar_weights" in result
    assert "max_sharpe_weights" in result
    assert "cvar_95" in result
    assert "efficient_frontier" in result
    assert isinstance(result["efficient_frontier"], list)
