from __future__ import annotations

import math

import pandas as pd


def compute_equity_curve(trade_returns: pd.Series, initial_capital: float = 100_000.0) -> pd.Series:
    equity = (1 + trade_returns.fillna(0.0)).cumprod() * initial_capital
    return equity


def compute_max_drawdown_pct(equity_curve: pd.Series) -> float:
    rolling_peak = equity_curve.cummax()
    drawdown = equity_curve / rolling_peak - 1.0
    return float(drawdown.min()) if len(drawdown) else 0.0


def compute_sharpe_ratio(
    trade_returns: pd.Series,
    annualization_factor: float | None = None,
) -> float:
    """Compute annualized Sharpe ratio.

    Parameters
    ----------
    trade_returns:
        Per-trade return series (not per-bar / per-day).
    annualization_factor:
        Number of trades per year used for sqrt-annualization.
        Pass ``trades_per_year = len(returns) / (date_range_days / 365)``
        when calling from the backtest engine.
        Defaults to 252 for backward compatibility, but that constant is only
        correct for *daily* return series — callers with per-trade returns
        should supply the actual trades-per-year value.
    """
    clean = trade_returns.dropna()
    if clean.empty or clean.std(ddof=0) == 0:
        return 0.0
    if annualization_factor is None:
        annualization_factor = 252  # backward-compat default
    return float(math.sqrt(annualization_factor) * clean.mean() / clean.std(ddof=0))
