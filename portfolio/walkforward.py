"""
Walk-forward and Monte Carlo: does the result survive contact with doubt?

A single backtest over one window answers "what happened". Neither of these
answers that -- they answer the harder question an investor should ask before
committing money, which is whether the answer would have held on windows they
did not pick, and how much of it was luck.

Both are deliberately thin. openstatz owns the resampling maths; what lives
here is the portfolio-shaped framing around it.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

import numpy as np
import pandas as pd

from portfolio.costs import CostSchedule
from portfolio.data import PriceMatrix
from portfolio.engine import Costs, run_backtest
from portfolio.rebalance import RebalancePolicy

TRADING_DAYS = 252


@dataclass
class WalkForwardWindow:
    start: str
    end: str
    total_return: float
    cagr: float
    max_drawdown: float
    sessions: int


def walk_forward(
    prices: PriceMatrix,
    weights: dict[str, float],
    *,
    policy: RebalancePolicy | None = None,
    costs: Costs | CostSchedule | None = None,
    initial_capital: float = 100_000.0,
    window_years: float = 1.0,
    step_years: float = 0.5,
) -> dict:
    """
    Re-run the same allocation over rolling sub-windows.

    A strategy whose whole result came from one exceptional stretch looks very
    different here from one that worked repeatedly, and the headline CAGR
    cannot tell them apart. The spread across windows is the point, not the
    average of them.

    Windows overlap by design (``step`` is smaller than ``window``): the
    question is how the allocation behaved across many starting points, and
    non-overlapping windows would leave too few of them to say anything.
    """
    window = int(window_years * TRADING_DAYS)
    step = max(1, int(step_years * TRADING_DAYS))
    index = prices.closes.index

    if len(index) < window + 1:
        return {
            "windows": [],
            "summary": None,
            "note": (
                f"{len(index)} sessions is shorter than the "
                f"{window}-session window"
            ),
        }

    windows: list[WalkForwardWindow] = []
    for begin in range(0, len(index) - window + 1, step):
        chunk = prices.closes.iloc[begin : begin + window]
        sub = PriceMatrix(
            closes=chunk,
            source=prices.source,
            start=chunk.index[0].date(),
            end=chunk.index[-1].date(),
        )
        r = run_backtest(
            sub,
            weights,
            policy=policy,
            costs=costs,
            initial_capital=initial_capital,
        )
        equity = r.equity
        years = len(chunk) / TRADING_DAYS
        total = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
        drawdown = float((equity / equity.cummax() - 1.0).min())
        windows.append(
            WalkForwardWindow(
                start=str(chunk.index[0].date()),
                end=str(chunk.index[-1].date()),
                total_return=total,
                cagr=float((1.0 + total) ** (1.0 / years) - 1.0) if years > 0 else float("nan"),
                max_drawdown=drawdown,
                sessions=len(chunk),
            )
        )

    returns = np.array([w.total_return for w in windows], dtype=float)
    return {
        "windows": [w.__dict__ for w in windows],
        "summary": {
            "count": len(windows),
            "window_years": window_years,
            "step_years": step_years,
            "best": float(returns.max()),
            "worst": float(returns.min()),
            "median": float(np.median(returns)),
            # The number that matters most: an allocation that was positive in
            # 9 of 10 windows is a different proposition from one that was
            # positive in 5, even at the same average.
            "positive_share": float((returns > 0).mean()),
            "spread": float(returns.max() - returns.min()),
        },
        "note": None,
    }


def _bootstrap_path(
    values: np.ndarray,
    block: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Sample full blocks, then trim to exactly the source-series length."""
    blocks = max(1, ceil(len(values) / block))
    starts = rng.integers(0, len(values) - block + 1, size=blocks)
    return np.concatenate([values[start : start + block] for start in starts])[
        : len(values)
    ]


def monte_carlo(
    returns: pd.Series,
    *,
    simulations: int = 1000,
    block: int = 20,
    seed: int = 12345,
) -> dict:
    """
    Resample the return series to ask how much of the outcome was sequence luck.

    Uses a **block** bootstrap rather than an i.i.d. one. Drawing single days
    independently destroys autocorrelation and volatility clustering, which
    makes drawdowns look far milder than markets actually produce -- the very
    statistic an investor most needs to be honest about. Blocks of roughly a
    month keep that structure intact.

    ``seed`` is fixed so a given portfolio and window always produce the same
    figures: a risk number that changes each time it is looked at invites
    re-rolling until it flatters.
    """
    values = returns.dropna().to_numpy(dtype=float)
    n = len(values)
    if n < block * 2:
        return {"note": f"{n} sessions is too few for {block}-session blocks", "paths": 0}

    rng = np.random.default_rng(seed)
    finals = np.empty(simulations, dtype=float)
    drawdowns = np.empty(simulations, dtype=float)

    for i in range(simulations):
        path = _bootstrap_path(values, block, rng)
        curve = np.cumprod(1.0 + path)
        finals[i] = curve[-1] - 1.0
        drawdowns[i] = float((curve / np.maximum.accumulate(curve) - 1.0).min())

    years = n / TRADING_DAYS
    cagrs = np.sign(1.0 + finals) * np.abs(1.0 + finals) ** (1.0 / years) - 1.0

    def band(a: np.ndarray) -> dict:
        return {
            "p05": float(np.percentile(a, 5)),
            "p25": float(np.percentile(a, 25)),
            "median": float(np.median(a)),
            "p75": float(np.percentile(a, 75)),
            "p95": float(np.percentile(a, 95)),
        }

    return {
        "paths": simulations,
        "block": block,
        "seed": seed,
        "total_return": band(finals),
        "cagr": band(cagrs),
        "max_drawdown": band(drawdowns),
        # What an investor actually wants from this: the chance of ending
        # behind, and how bad the bad cases got.
        "probability_of_loss": float((finals < 0).mean()),
        "worst_drawdown_seen": float(drawdowns.min()),
        "note": None,
    }
