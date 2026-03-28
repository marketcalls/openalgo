"""CVaR Portfolio Optimisation — GPU-optional via CuPy, fallback to NumPy.

CVaR (Conditional Value at Risk) = expected loss beyond the VaR threshold.
Minimising CVaR produces portfolios that limit tail-risk losses.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize, Bounds

from utils.logging import get_logger

logger = get_logger(__name__)

# Try GPU acceleration; silently fall back to numpy
try:
    import cupy as cp
    _USE_GPU = True
    logger.info("CuPy detected — using GPU for Monte Carlo")
except ImportError:
    cp = None
    _USE_GPU = False


def _xp():
    """Return cupy if available, else numpy."""
    return cp if _USE_GPU else np


def _to_np(arr) -> np.ndarray:
    """Move array to CPU numpy if it's on GPU."""
    if _USE_GPU and cp is not None and isinstance(arr, cp.ndarray):
        return cp.asnumpy(arr)
    return np.asarray(arr)


def compute_cvar(
    returns: np.ndarray,
    weights: np.ndarray,
    confidence: float = 0.95,
) -> dict:
    """Compute VaR and CVaR for a weighted portfolio.

    Args:
        returns: shape (T, N) daily returns matrix
        weights: shape (N,) portfolio weights summing to 1
        confidence: 0.95 or 0.99

    Returns:
        dict with cvar_{pct} and var_{pct} keys (negative = loss)
    """
    xp = _xp()
    R = xp.asarray(returns, dtype=xp.float64)
    w = xp.asarray(weights, dtype=xp.float64)
    port_returns = R @ w                          # (T,)
    sorted_r = xp.sort(port_returns)
    cutoff = int((1 - confidence) * len(sorted_r))
    cutoff = max(cutoff, 1)
    var = float(_to_np(sorted_r[cutoff]))
    cvar = float(_to_np(sorted_r[:cutoff].mean()))
    pct = int(confidence * 100)
    return {f"var_{pct}": round(var, 6), f"cvar_{pct}": round(cvar, 6)}


def optimise_min_cvar(returns: np.ndarray, confidence: float = 0.95) -> dict:
    """Find portfolio weights that minimise CVaR at given confidence level."""
    n = returns.shape[1]
    pct = int(confidence * 100)

    def _objective(w: np.ndarray) -> float:
        r = compute_cvar(returns, w, confidence)
        return r[f"cvar_{pct}"]  # already negative; minimising makes it less negative

    w0 = np.ones(n) / n
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    bounds = Bounds(lb=0.0, ub=1.0)
    res = minimize(
        _objective, w0, method="SLSQP", bounds=bounds, constraints=constraints,
        options={"maxiter": 500, "ftol": 1e-9},
    )
    w_sum = res.x.sum()
    weights = (res.x / w_sum).tolist() if w_sum > 1e-10 else (np.ones(n) / n).tolist()
    metrics = compute_cvar(returns, np.array(weights), confidence)
    return {"weights": weights, **metrics, "converged": bool(res.success)}


def optimise_max_sharpe(returns: np.ndarray, risk_free: float = 0.065 / 252) -> dict:
    """Find portfolio weights that maximise Sharpe ratio."""
    n = returns.shape[1]
    mean_r = returns.mean(axis=0)
    cov = np.cov(returns.T)

    def _neg_sharpe(w: np.ndarray) -> float:
        ret = float(w @ mean_r)
        vol = float(np.sqrt(w @ cov @ w))
        return -(ret - risk_free) / (vol + 1e-9)

    w0 = np.ones(n) / n
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    bounds = Bounds(lb=0.0, ub=1.0)
    res = minimize(
        _neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints,
        options={"maxiter": 500},
    )
    w_sum = res.x.sum()
    weights = (res.x / w_sum).tolist() if w_sum > 1e-10 else (np.ones(n) / n).tolist()
    sharpe = -_neg_sharpe(np.array(weights))
    ann_return = float(np.array(weights) @ mean_r) * 252
    ann_vol = float(np.sqrt(np.array(weights) @ cov @ np.array(weights))) * np.sqrt(252)
    return {
        "weights": weights,
        "sharpe": round(float(sharpe), 4),
        "annual_return": round(ann_return, 4),
        "annual_volatility": round(ann_vol, 4),
        "converged": bool(res.success),
    }


def _efficient_frontier(returns: np.ndarray, n_points: int = 20) -> list[dict]:
    """Sample the efficient frontier as (annualised_return, annualised_vol) pairs."""
    n = returns.shape[1]
    mean_r = returns.mean(axis=0)
    cov = np.cov(returns.T)
    target_returns = np.linspace(mean_r.min(), mean_r.max(), n_points)
    frontier = []
    for target in target_returns:
        constraints = [
            {"type": "eq", "fun": lambda w: w.sum() - 1.0},
            {"type": "eq", "fun": lambda w, t=target: float(w @ mean_r) - t},
        ]
        res = minimize(
            lambda w: float(np.sqrt(w @ cov @ w)),
            np.ones(n) / n,
            method="SLSQP",
            bounds=Bounds(0.0, 1.0),
            constraints=constraints,
            options={"maxiter": 200},
        )
        if res.success:
            vol = float(np.sqrt(res.x @ cov @ res.x)) * np.sqrt(252)
            ret = float(res.x @ mean_r) * 252
            frontier.append({"volatility": round(vol, 4), "return": round(ret, 4)})
    return frontier


def run_portfolio_analysis(
    symbols: list[str],
    returns_dict: dict,
    confidence: float = 0.95,
) -> dict:
    """Full portfolio analysis: CVaR, Sharpe, and efficient frontier."""
    try:
        df = pd.DataFrame(returns_dict)[symbols].dropna()
        if len(df) < 30:
            return {"status": "error", "message": "Need at least 30 days of return data"}
        returns = df.values.astype(np.float64)

        equal_w = np.ones(len(symbols)) / len(symbols)
        eq_metrics_95 = compute_cvar(returns, equal_w, 0.95)
        eq_metrics_99 = compute_cvar(returns, equal_w, 0.99)

        min_cvar_result = optimise_min_cvar(returns, confidence)
        max_sharpe_result = optimise_max_sharpe(returns)
        frontier = _efficient_frontier(returns)

        cvar_99 = compute_cvar(
            returns, np.array(min_cvar_result["weights"]), 0.99
        ).get("cvar_99", 0)

        return {
            "status": "success",
            "symbols": symbols,
            "n_days": len(df),
            "gpu_used": _USE_GPU,
            "equal_weight_metrics": {**eq_metrics_95, **eq_metrics_99},
            "min_cvar_weights": dict(
                zip(symbols, [round(w, 4) for w in min_cvar_result["weights"]])
            ),
            "max_sharpe_weights": dict(
                zip(symbols, [round(w, 4) for w in max_sharpe_result["weights"]])
            ),
            "cvar_95": min_cvar_result.get("cvar_95", 0),
            "cvar_99": cvar_99,
            "sharpe": max_sharpe_result["sharpe"],
            "annual_return": max_sharpe_result["annual_return"],
            "annual_volatility": max_sharpe_result["annual_volatility"],
            "efficient_frontier": frontier,
        }
    except Exception:
        logger.exception("Portfolio CVaR analysis failed")
        return {"status": "error", "message": "Portfolio optimisation failed"}
