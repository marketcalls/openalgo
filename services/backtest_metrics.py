# services/backtest_metrics.py
"""
Backtest Performance Metrics Calculator

Calculates all standard quantitative trading metrics from backtest results:
Sharpe, Sortino, Max Drawdown, CAGR, Win Rate, Profit Factor, etc.

Handles edge cases: zero trades, flat equity, single bar, inf values.
"""

import numpy as np
import pandas as pd

from utils.logging import get_logger

logger = get_logger(__name__)


def calculate_metrics(trades, equity_curve, initial_capital, interval):
    """
    Calculate all performance metrics from backtest results.

    Args:
        trades: list of trade dicts from BacktestClient
        equity_curve: list of {timestamp, equity, drawdown} dicts
        initial_capital: starting capital (float)
        interval: bar interval string ('1m', '5m', '15m', '30m', '1h', 'D')

    Returns:
        dict with all computed metrics
    """
    if not equity_curve or len(equity_curve) < 2:
        return _empty_metrics(initial_capital)

    try:
        equity_values = [e["equity"] for e in equity_curve]
        equity = pd.Series(equity_values, dtype=float)
        returns = equity.pct_change().dropna()

        # Replace inf/nan in returns
        returns = returns.replace([np.inf, -np.inf], 0.0).fillna(0.0)

        # Annualization factor
        bars_per_year = _get_bars_per_year(interval)

        metrics = {}

        # ── Return Metrics ──
        final_equity = float(equity.iloc[-1])
        metrics["final_capital"] = round(final_equity, 2)
        if initial_capital > 0:
            metrics["total_return_pct"] = round(
                (final_equity - initial_capital) / initial_capital * 100, 4
            )
        else:
            metrics["total_return_pct"] = 0.0

        # CAGR
        total_bars = len(equity)
        if total_bars > 1 and final_equity > 0 and initial_capital > 0 and bars_per_year > 0:
            years = total_bars / bars_per_year
            if years > 0:
                ratio = final_equity / initial_capital
                if ratio > 0:
                    metrics["cagr"] = round(
                        (ratio ** (1.0 / years) - 1) * 100, 4
                    )
                else:
                    metrics["cagr"] = -100.0
            else:
                metrics["cagr"] = 0.0
        else:
            metrics["cagr"] = 0.0

        # ── Risk Metrics ──
        std = float(returns.std())
        mean = float(returns.mean())

        if len(returns) > 1 and std > 0:
            metrics["sharpe_ratio"] = round(
                mean / std * np.sqrt(bars_per_year), 4
            )
        else:
            metrics["sharpe_ratio"] = 0.0

        # Sortino — only downside deviation
        downside = returns[returns < 0]
        if len(downside) > 1:
            down_std = float(downside.std())
            if down_std > 0:
                metrics["sortino_ratio"] = round(
                    mean / down_std * np.sqrt(bars_per_year), 4
                )
            else:
                metrics["sortino_ratio"] = 0.0
        else:
            metrics["sortino_ratio"] = 0.0

        # Max drawdown
        dd_values = [e.get("drawdown", 0) for e in equity_curve]
        max_dd = max(dd_values) if dd_values else 0.0
        metrics["max_drawdown_pct"] = round(max_dd * 100, 4)

        # Calmar — use signed CAGR (not abs) so losing strategies show negative Calmar
        if metrics["max_drawdown_pct"] > 0:
            metrics["calmar_ratio"] = round(
                metrics["cagr"] / metrics["max_drawdown_pct"], 4
            )
        else:
            metrics["calmar_ratio"] = 0.0

        # ── Trade Metrics ──
        _compute_trade_metrics(metrics, trades)

        # ── Monthly Returns ──
        metrics["monthly_returns"] = _compute_monthly_returns(equity_curve)

        return metrics

    except Exception as e:
        logger.exception(f"Error calculating metrics: {e}")
        return _empty_metrics(initial_capital)


def _compute_trade_metrics(metrics, trades):
    """Compute trade-level statistics."""
    if not trades:
        metrics.update({
            "total_trades": 0, "winning_trades": 0, "losing_trades": 0,
            "win_rate": 0.0, "profit_factor": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0,
            "max_win": 0.0, "max_loss": 0.0,
            "expectancy": 0.0, "avg_holding_bars": 0,
            "total_commission": 0.0, "total_slippage": 0.0,
        })
        return

    wins = [t for t in trades if t.get("net_pnl", 0) > 0]
    losses = [t for t in trades if t.get("net_pnl", 0) <= 0]

    metrics["total_trades"] = len(trades)
    metrics["winning_trades"] = len(wins)
    metrics["losing_trades"] = len(losses)

    if len(trades) > 0:
        metrics["win_rate"] = round(len(wins) / len(trades) * 100, 4)
    else:
        metrics["win_rate"] = 0.0

    gross_profit = sum(t.get("net_pnl", 0) for t in wins)
    gross_loss = abs(sum(t.get("net_pnl", 0) for t in losses))

    if gross_loss > 0:
        pf = gross_profit / gross_loss
        # Cap profit factor at 999.99 to avoid serialization issues
        metrics["profit_factor"] = round(min(pf, 999.99), 4)
    elif gross_profit > 0:
        metrics["profit_factor"] = 999.99  # effectively infinite
    else:
        metrics["profit_factor"] = 0.0

    # Win/loss averages
    if wins:
        win_pnls = [t.get("net_pnl", 0) for t in wins]
        metrics["avg_win"] = round(float(np.mean(win_pnls)), 2)
        metrics["max_win"] = round(float(max(win_pnls)), 2)
    else:
        metrics["avg_win"] = 0.0
        metrics["max_win"] = 0.0

    if losses:
        loss_pnls = [t.get("net_pnl", 0) for t in losses]
        metrics["avg_loss"] = round(float(np.mean(loss_pnls)), 2)
        metrics["max_loss"] = round(float(min(loss_pnls)), 2)
    else:
        metrics["avg_loss"] = 0.0
        metrics["max_loss"] = 0.0

    # Expectancy
    wr = metrics["win_rate"] / 100.0
    metrics["expectancy"] = round(
        wr * metrics["avg_win"] + (1.0 - wr) * metrics["avg_loss"], 2
    )

    # Average holding bars
    bars_held = [t.get("bars_held", 0) for t in trades if t.get("bars_held", 0) > 0]
    if bars_held:
        metrics["avg_holding_bars"] = round(float(np.mean(bars_held)))
    else:
        metrics["avg_holding_bars"] = 0

    # Totals
    metrics["total_commission"] = round(
        sum(t.get("commission", 0) for t in trades), 2
    )
    metrics["total_slippage"] = round(
        sum(t.get("slippage_cost", 0) for t in trades), 2
    )


def _compute_monthly_returns(equity_curve):
    """Compute monthly returns for calendar heatmap."""
    try:
        if len(equity_curve) < 2:
            return {}

        timestamps = [e["timestamp"] for e in equity_curve]
        equities = [e["equity"] for e in equity_curve]

        equity_ts = pd.Series(
            equities,
            index=pd.to_datetime(timestamps, unit="s"),
            dtype=float,
        )

        # Resample to monthly, take last value
        monthly = equity_ts.resample("ME").last().dropna()
        if len(monthly) < 2:
            return {}

        monthly_returns = monthly.pct_change().dropna() * 100.0

        return {
            str(k.date()): round(float(v), 2)
            for k, v in monthly_returns.items()
            if not np.isnan(v) and not np.isinf(v)
        }
    except Exception as e:
        logger.debug(f"Could not compute monthly returns: {e}")
        return {}


def _get_bars_per_year(interval):
    """Get the number of bars per year for annualization."""
    mapping = {
        "1m": 252 * 375,
        "3m": 252 * 125,
        "5m": 252 * 75,
        "10m": 252 * 37,
        "15m": 252 * 25,
        "30m": 252 * 12,
        "1h": 252 * 6,
        "D": 252,
        "W": 52,
        "M": 12,
    }
    return mapping.get(interval, 252)


def _empty_metrics(initial_capital=0):
    """Return empty metrics when no data is available."""
    return {
        "final_capital": round(float(initial_capital), 2),
        "total_return_pct": 0.0,
        "cagr": 0.0,
        "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0,
        "max_drawdown_pct": 0.0,
        "calmar_ratio": 0.0,
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "win_rate": 0.0,
        "profit_factor": 0.0,
        "avg_win": 0.0,
        "avg_loss": 0.0,
        "max_win": 0.0,
        "max_loss": 0.0,
        "expectancy": 0.0,
        "avg_holding_bars": 0,
        "total_commission": 0.0,
        "total_slippage": 0.0,
        "monthly_returns": {},
    }
