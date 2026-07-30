"""
The backtest itself: weights + prices + a rebalancing policy -> an equity curve.

Deliberately a drift-and-reset simulation rather than an order-level one. Held
weights drift with prices between rebalance dates and snap back to target on
them, which is what a weight-target portfolio actually does. There is no order
book because a daily-bar investor portfolio does not need one.

Costs are modelled and reported, not assumed away. A frictionless backtest
flatters every rebalancing schedule -- the more often it trades, the more it
flatters -- so turnover and the return it consumed are first-class outputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from portfolio.data import PriceMatrix
from portfolio.rebalance import RebalancePolicy, calendar_dates, drifted


@dataclass(frozen=True)
class Costs:
    """
    Round-trip trading costs, as fractions of traded value.

    ``bps`` covers brokerage, exchange fees and taxes as one number; ``slippage``
    is the execution gap. Both apply to the *traded* value at each rebalance,
    not to the whole portfolio, so a small drift correction costs little.
    """

    bps: float = 0.0
    slippage: float = 0.0

    @property
    def total(self) -> float:
        return (self.bps / 10_000.0) + self.slippage


@dataclass
class BacktestResult:
    """Everything a tearsheet or an API response needs from one run."""

    equity: pd.Series
    weights: pd.DataFrame
    rebalance_dates: pd.DatetimeIndex
    turnover: pd.Series
    cost_drag: float
    source: str
    meta: dict = field(default_factory=dict)

    @property
    def returns(self) -> pd.Series:
        """Daily portfolio returns, net of costs."""
        return self.equity.pct_change().iloc[1:]

    @property
    def total_return(self) -> float:
        return float(self.equity.iloc[-1] / self.equity.iloc[0] - 1.0)


def normalise_weights(weights: dict[str, float], symbols: list[str]) -> np.ndarray:
    """
    Order weights to match ``symbols`` and scale them to sum to 1.

    Accepts percentages or fractions -- the UI collects "40.0" meaning 40% --
    since the only thing that matters downstream is the ratio between them.
    """
    missing = [s for s in symbols if s not in weights]
    if missing:
        raise ValueError(f"no weight given for {', '.join(missing)}")
    extra = [s for s in weights if s not in symbols]
    if extra:
        raise ValueError(f"weight given for unheld symbol(s): {', '.join(extra)}")

    vector = np.array([float(weights[s]) for s in symbols], dtype=float)
    if np.any(vector < 0):
        raise ValueError("negative weights are not supported; this is a long-only engine")
    total = vector.sum()
    if total <= 0:
        raise ValueError("weights sum to zero")
    return vector / total


def run_backtest(
    prices: PriceMatrix,
    weights: dict[str, float],
    *,
    policy: RebalancePolicy | None = None,
    costs: Costs | None = None,
    initial_capital: float = 100_000.0,
) -> BacktestResult:
    """
    Simulate ``weights`` over ``prices`` under ``policy``.

    Returns an equity curve net of costs, the weight path, the sessions that
    were rebalanced, per-rebalance turnover, and the total return given up to
    costs -- the last of which is what makes two rebalancing schedules
    comparable on an honest basis.
    """
    policy = policy or RebalancePolicy()
    costs = costs or Costs()

    symbols = prices.symbols
    target = normalise_weights(weights, symbols)
    closes = prices.closes
    index = closes.index

    # Bar-over-bar growth per holding. Row i is the move from i-1 to i, so the
    # first row is 1.0: nothing has moved on the day the portfolio is bought.
    growth = closes.div(closes.shift(1)).fillna(1.0).to_numpy()

    scheduled = set(calendar_dates(index, policy.rule))

    equity = np.empty(len(index), dtype=float)
    weight_path = np.empty((len(index), len(symbols)), dtype=float)
    turnover_at: dict[pd.Timestamp, float] = {}

    value = float(initial_capital)
    held = target.copy()
    gross_value = value  # the same run with costs switched off, for the drag

    for i, stamp in enumerate(index):
        if i > 0:
            # Drift: each sleeve grows by its own bar return, so the weights
            # move on their own between rebalances.
            grown = held * growth[i]
            step = grown.sum()
            value *= step
            gross_value *= step
            held = grown / step

            if stamp in scheduled or drifted(held, target, policy.drift_band):
                # Turnover is one-way: the fraction of the portfolio that had to
                # change hands to get back to target.
                traded = float(np.abs(held - target).sum()) / 2.0
                if traded > 0:
                    value *= 1.0 - traded * costs.total
                    turnover_at[stamp] = traded
                held = target.copy()

        equity[i] = value
        weight_path[i] = held

    equity_series = pd.Series(equity, index=index, name="equity")
    gross_total = gross_value / float(initial_capital) - 1.0
    net_total = equity[-1] / float(initial_capital) - 1.0

    return BacktestResult(
        equity=equity_series,
        weights=pd.DataFrame(weight_path, index=index, columns=symbols),
        rebalance_dates=pd.DatetimeIndex(sorted(turnover_at)),
        turnover=pd.Series(turnover_at, dtype=float).sort_index(),
        # What costs took out of the total return, in return terms. Zero when
        # nothing traded, which is the buy-and-hold case.
        cost_drag=float(gross_total - net_total),
        source=prices.source,
        meta={
            "symbols": symbols,
            "target_weights": dict(zip(symbols, target.tolist())),
            "rule": policy.rule,
            "drift_band": policy.drift_band,
            "cost_bps": costs.bps,
            "slippage": costs.slippage,
            "initial_capital": initial_capital,
            "sessions": len(index),
        },
    )
