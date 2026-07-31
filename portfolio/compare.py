"""
Compare portfolios, or the same portfolio under different rules.

The question an investor actually faces is rarely "how did this do" but "which
of these should I hold" — a different split, or the same split rebalanced
monthly against yearly. Answering it means running several backtests over the
same prices, which the price cache makes almost free: the history is read once
and every variant reuses it.

Variants are compared on a single aligned window. If one holding has a later
listing date than another, every variant is measured over the sessions common
to all of them, because two results computed over different periods are not a
comparison.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from portfolio.costs import CostSchedule
from portfolio.data import PriceMatrix
from portfolio.engine import Costs, run_backtest
from portfolio.rebalance import RebalancePolicy


@dataclass
class Variant:
    """One thing being compared."""

    label: str
    weights: dict[str, float]
    policy: RebalancePolicy
    costs: Costs | CostSchedule | None = None


def compare(
    prices: PriceMatrix,
    variants: list[Variant],
    *,
    benchmark_returns: pd.Series | None = None,
    initial_capital: float = 100_000.0,
    rf: float = 0.0,
) -> dict:
    """
    Run each variant over the same prices and line the results up.

    Returns per-variant metrics plus the equity curves, so the caller can draw
    them on one axis — which is the only way the difference between two
    rebalancing schedules becomes visible, since their headline returns often
    sit within a percent of each other.
    """
    import openstatz.stats as st

    rows: list[dict] = []
    curves: dict[str, list[dict]] = {}

    for variant in variants:
        result = run_backtest(
            prices,
            variant.weights,
            policy=variant.policy,
            costs=variant.costs,
            initial_capital=initial_capital,
        )
        returns = result.returns
        equity = result.equity

        row = {
            "label": variant.label,
            "rule": variant.policy.rule,
            "drift_band": variant.policy.drift_band,
            "total_return": result.total_return,
            "cagr": float(st.cagr(returns, rf=rf)),
            "volatility": float(st.volatility(returns)),
            "sharpe": float(st.sharpe(returns, rf=rf)),
            "sortino": float(st.sortino(returns, rf=rf)),
            "max_drawdown": float(st.max_drawdown((1.0 + returns).cumprod())),
            "calmar": float(st.calmar(returns)),
            # The two numbers that explain why a schedule that trades more can
            # end up behind one that trades less.
            "cost_drag": result.cost_drag,
            "turnover": float(result.turnover.sum()),
            "rebalances": len(result.rebalance_dates),
        }
        if benchmark_returns is not None and len(benchmark_returns) > 0:
            joined = pd.concat([returns, benchmark_returns], axis=1, join="inner").dropna()
            if not joined.empty:
                row["beta"] = float(st.greeks(joined.iloc[:, 0], joined.iloc[:, 1])["beta"])
        rows.append(row)

        # Sampled, since a comparison chart needs shape rather than every session.
        step = max(1, len(equity) // 300)
        thinned = equity.iloc[::step]
        curves[variant.label] = [
            {"date": d.date().isoformat(), "value": round(float(v), 2)}
            for d, v in thinned.items()
        ]

    # Rank on risk-adjusted return rather than raw return: the whole reason to
    # compare rebalancing schedules is that the one with the highest return is
    # frequently not the one worth holding.
    ranked = sorted(rows, key=lambda r: (r["sharpe"] if r["sharpe"] == r["sharpe"] else -9e9), reverse=True)
    best = ranked[0]["label"] if ranked else None

    return {
        "variants": rows,
        "curves": curves,
        "best_by_sharpe": best,
        "best_by_return": (
            max(rows, key=lambda r: r["total_return"])["label"] if rows else None
        ),
        "sessions": prices.sessions,
        "start": str(prices.start),
        "end": str(prices.end),
    }


def rebalancing_sweep(
    prices: PriceMatrix,
    weights: dict[str, float],
    *,
    costs: Costs | CostSchedule | None = None,
    initial_capital: float = 100_000.0,
    rf: float = 0.0,
    drift_bands: tuple[float, ...] = (0.05,),
) -> dict:
    """
    The same allocation under every rebalancing rule, plus drift bands.

    This is the comparison worth running by default: it is one decision, it is
    reversible, and the cost of getting it wrong is paid quietly in turnover
    rather than loudly in returns.
    """
    variants = [
        Variant(f"{rule.title()}", weights, RebalancePolicy(rule), costs)
        for rule in ("never", "yearly", "quarterly", "monthly")
    ]
    variants += [
        Variant(
            f"Drift {int(band * 100)}%",
            weights,
            RebalancePolicy("never", drift_band=band),
            costs,
        )
        for band in drift_bands
    ]
    return compare(
        prices, variants, initial_capital=initial_capital, rf=rf
    )
