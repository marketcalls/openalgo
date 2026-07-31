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

from portfolio.costs import CostSchedule, EquityCosts
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

    def __post_init__(self) -> None:
        for name in ("bps", "slippage"):
            value = getattr(self, name)
            if not np.isfinite(value) or value < 0:
                raise ValueError(f"flat cost {name} must be finite and non-negative")

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
    cost_breakdown: dict[str, float] = field(default_factory=dict)
    #: One row per holding: what it made, what it cost, what it contributed.
    items: pd.DataFrame = field(default_factory=pd.DataFrame)
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
    if not np.isfinite(vector).all():
        raise ValueError("weights must be finite")
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
    costs: Costs | EquityCosts | CostSchedule | None = None,
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
    if not np.isfinite(initial_capital) or initial_capital <= 0:
        raise ValueError("initial capital must be positive and finite")

    symbols = prices.symbols
    target = normalise_weights(weights, symbols)
    closes = prices.closes
    close_values = closes.to_numpy(dtype=float)
    if not np.isfinite(close_values).all() or (close_values <= 0).any():
        raise ValueError("price matrix must contain only positive finite closes")
    index = closes.index

    # Bar-over-bar growth per holding. Row i is the move from i-1 to i, so the
    # first row is 1.0: nothing has moved on the day the portfolio is bought.
    growth = closes.div(closes.shift(1)).fillna(1.0).to_numpy()

    scheduled = set(calendar_dates(index, policy.rule))

    equity = np.empty(len(index), dtype=float)
    weight_path = np.empty((len(index), len(symbols)), dtype=float)
    turnover_at: dict[pd.Timestamp, float] = {}
    order_count = 0
    if isinstance(costs, (EquityCosts, CostSchedule)):
        cost_breakdown = dict.fromkeys(costs.breakdown(0.0, 0.0, orders=0), 0.0)
    else:
        cost_breakdown = {"total": 0.0, "orders": 0.0}

    # Held in currency per symbol rather than as weights. Weights are a ratio
    # and cannot answer "how much did this holding actually make", which is the
    # question an investor asks first; currency can, and weights divide back
    # out of it exactly.
    sleeve = target * float(initial_capital)
    price_pnl = np.zeros(len(symbols), dtype=float)   # made or lost on price
    cost_paid = np.zeros(len(symbols), dtype=float)   # costs charged to it
    gross_sleeve = sleeve.copy()  # the same run with costs off, for the drag

    for i, stamp in enumerate(index):
        if i > 0:
            # Drift: each sleeve grows by its own bar return, so the weights
            # move on their own between rebalances.
            grown = sleeve * growth[i]
            price_pnl += grown - sleeve
            sleeve = grown
            value = sleeve.sum()
            gross_sleeve = gross_sleeve * growth[i]

            held = sleeve / value
            if stamp in scheduled or drifted(held, target, policy.drift_band):
                desired = target * value
                # Turnover is one-way: the fraction of the portfolio that had
                # to change hands to get back to target.
                traded = float(np.abs(desired - sleeve).sum()) / 2.0 / value
                if traded > 0:
                    traded_value = traded * value
                    # A rebalance conserves value, so the rupees bought equal
                    # the rupees sold. That split matters: stamp duty is charged
                    # on the buy leg only, which a single blended rate cannot
                    # express.
                    # One order per holding whose position actually changed --
                    # a flat per-order brokerage depends on that count, not on
                    # the value.
                    orders = int((np.abs(desired - sleeve) > 1e-9).sum())
                    order_count += orders
                    if isinstance(costs, (EquityCosts, CostSchedule)):
                        lines = costs.breakdown(traded_value, traded_value, orders)
                        for key, amount in lines.items():
                            cost_breakdown[key] = cost_breakdown.get(key, 0.0) + amount
                        charge = lines["total"]
                    else:
                        charge = traded_value * costs.total
                        cost_breakdown["total"] += charge
                        cost_breakdown["orders"] += float(orders)
                    # Attributed by each symbol's share of the traded value, so
                    # the holding that forced the trade carries the cost.
                    moved = np.abs(desired - sleeve)
                    share = moved / moved.sum() if moved.sum() > 0 else moved
                    cost_paid += charge * share
                    value -= charge
                    turnover_at[stamp] = traded
                sleeve = target * value
                # The cost-free twin rebalances on the same sessions; only the
                # charge is skipped, so the difference is costs and nothing else.
                gross_sleeve = target * gross_sleeve.sum()
        else:
            value = sleeve.sum()

        equity[i] = value
        weight_path[i] = sleeve / value

    equity_series = pd.Series(equity, index=index, name="equity")
    gross_total = gross_sleeve.sum() / float(initial_capital) - 1.0
    net_total = equity[-1] / float(initial_capital) - 1.0

    # Itemised P&L. `contribution_pct` is each holding's share of the total
    # return in percentage points, so the column sums to the portfolio return --
    # which is the property that makes it an attribution rather than a list of
    # individual performances. A holding's own return and its contribution
    # differ whenever its weight is not 100%, and diverge further under
    # rebalancing, where capital is added to laggards and taken from winners.
    net_pnl = price_pnl - cost_paid
    first_close = closes.iloc[0].to_numpy()
    last_close = closes.iloc[-1].to_numpy()
    items = pd.DataFrame(
        {
            "weight_target": target,
            "weight_final": weight_path[-1],
            "invested": target * float(initial_capital),
            "price_pnl": price_pnl,
            "costs": cost_paid,
            "net_pnl": net_pnl,
            "contribution_pct": net_pnl / float(initial_capital),
            "symbol_return": (last_close / first_close) - 1.0,
        },
        index=pd.Index(symbols, name="symbol"),
    )

    return BacktestResult(
        equity=equity_series,
        items=items,
        weights=pd.DataFrame(weight_path, index=index, columns=symbols),
        rebalance_dates=pd.DatetimeIndex(sorted(turnover_at)),
        turnover=pd.Series(turnover_at, dtype=float).sort_index(),
        # What costs took out of the total return, in return terms. Zero when
        # nothing traded, which is the buy-and-hold case.
        cost_drag=float(gross_total - net_total),
        source=prices.source,
        cost_breakdown=cost_breakdown,
        meta={
            "symbols": symbols,
            "target_weights": dict(zip(symbols, target.tolist(), strict=True)),
            "rule": policy.rule,
            "drift_band": policy.drift_band,
            "cost_model": (
                {"kind": "schedule", "name": costs.name}
                if isinstance(costs, CostSchedule)
                else {"kind": "indian_equity", "exchange": costs.exchange}
                if isinstance(costs, EquityCosts)
                else {"kind": "flat_bps", "bps": costs.bps}
            ),
            "orders": order_count,
            "slippage": getattr(costs, "slippage", 0.0),
            "initial_capital": initial_capital,
            "sessions": len(index),
        },
    )
