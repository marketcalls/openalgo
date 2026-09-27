"""
Portfolio Health: a graded score whose working is shown.

The products this competes with print a number like "35.1/100 (D)" and stop.
That is unfalsifiable — the investor cannot tell whether it is a considered
assessment or a guess, cannot see which holding dragged it down, and cannot
learn anything actionable from it.

So every pillar here publishes three things alongside its score: the raw
inputs it read, the formula it applied, and the weight it carries in the
total. A user who disagrees with the grade can see exactly which pillar they
disagree with and why.

Pillars are scored 0-100 on explicit, bounded scales. The bounds are judgement
calls -- there is no objective "Sharpe of 2.0 is perfect" -- so they are stated
as constants and shown in the formula string rather than buried in arithmetic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from portfolio.analytics import average_pairwise_correlation, concentration

# Where each pillar's scale starts and ends. Named so the formula strings can
# quote them, and so changing a judgement means changing one line.
EFFECTIVE_HOLDINGS_FLOOR = 1.0    # everything in one name
EFFECTIVE_HOLDINGS_CEIL = 12.0    # past here, more names add little
CORRELATION_FLOOR = 0.0           # genuinely unrelated holdings
CORRELATION_CEIL = 0.9            # one bet wearing several names
SHARPE_FLOOR = 0.0
SHARPE_CEIL = 2.0
DRAWDOWN_FLOOR = -0.50            # a halving
DRAWDOWN_CEIL = -0.10             # a normal correction
COST_DRAG_FLOOR = 0.05            # 5% of capital lost to trading
TREND_LOOKBACK = 200              # sessions, the conventional long-term filter

GRADES = ((80, "A"), (65, "B"), (50, "C"), (35, "D"), (0, "F"))


def _scale(value: float, low: float, high: float) -> float:
    """Map ``value`` onto 0-100 between ``low`` and ``high``, clamped."""
    if not np.isfinite(value):
        return float("nan")
    if high == low:
        return 50.0
    return float(np.clip((value - low) / (high - low), 0.0, 1.0) * 100.0)


@dataclass
class Pillar:
    """One scored dimension, with its working attached."""

    key: str
    label: str
    score: float
    weight: float
    formula: str
    inputs: dict = field(default_factory=dict)
    comment: str = ""


def concentration_pillar(weights: pd.Series) -> Pillar:
    c = concentration(weights)
    eff = c["effective_holdings"]
    score = _scale(eff, EFFECTIVE_HOLDINGS_FLOOR, EFFECTIVE_HOLDINGS_CEIL)
    return Pillar(
        key="concentration",
        label="Concentration",
        score=score,
        weight=0.20,
        formula=(
            f"effective holdings = 1 / HHI, scaled linearly from "
            f"{EFFECTIVE_HOLDINGS_FLOOR:.0f} (all in one name) to "
            f"{EFFECTIVE_HOLDINGS_CEIL:.0f}"
        ),
        inputs={k: round(v, 4) for k, v in c.items()},
        # The comment has to speak to the score's own basis. Comparing balance
        # against the holding count instead said "weights are well spread" on a
        # two-ETF book scoring 8/100, which reads as the pillar contradicting
        # itself.
        comment=(
            f"{c['holdings']} holdings, behaving like {eff:.1f} independent bets"
            if eff < 4
            else f"spread across roughly {eff:.1f} independent bets"
        ),
    )


def diversification_pillar(returns: pd.DataFrame) -> Pillar:
    avg = average_pairwise_correlation(returns)
    # Inverted: low correlation is healthy, so the scale runs from the ceiling
    # down to the floor.
    score = _scale(-avg, -CORRELATION_CEIL, -CORRELATION_FLOOR)
    return Pillar(
        key="diversification",
        label="True diversification",
        score=score,
        weight=0.20,
        formula=(
            f"mean pairwise correlation, scaled from {CORRELATION_CEIL} (moves as "
            f"one) to {CORRELATION_FLOOR} (unrelated); lower is better"
        ),
        inputs={"average_pairwise_correlation": None if not np.isfinite(avg) else round(avg, 4)},
        comment=(
            "holdings move together, so the spread is nominal"
            if np.isfinite(avg) and avg > 0.7
            else "holdings move independently enough to diversify"
        ),
    )


def efficiency_pillar(sharpe: float, sortino: float) -> Pillar:
    score = _scale(sharpe, SHARPE_FLOOR, SHARPE_CEIL)
    return Pillar(
        key="efficiency",
        label="Risk-adjusted efficiency",
        score=score,
        weight=0.20,
        formula=f"Sharpe ratio scaled from {SHARPE_FLOOR} to {SHARPE_CEIL}",
        inputs={
            "sharpe": None if not np.isfinite(sharpe) else round(sharpe, 4),
            "sortino": None if not np.isfinite(sortino) else round(sortino, 4),
        },
        comment=(
            "taking risk without being paid for it"
            if np.isfinite(sharpe) and sharpe < 0.5
            else "modest reward for the risk taken"
            if np.isfinite(sharpe) and sharpe < 1.2
            else "returns are compensating well for the risk taken"
        ),
    )


def drawdown_pillar(max_drawdown: float) -> Pillar:
    score = _scale(max_drawdown, DRAWDOWN_FLOOR, DRAWDOWN_CEIL)
    return Pillar(
        key="drawdown",
        label="Drawdown resilience",
        score=score,
        weight=0.20,
        formula=(
            f"worst peak-to-trough fall, scaled from {DRAWDOWN_FLOOR:.0%} to "
            f"{DRAWDOWN_CEIL:.0%}"
        ),
        inputs={"max_drawdown": None if not np.isfinite(max_drawdown) else round(max_drawdown, 4)},
        comment=(
            "a fall this deep needs a large gain to recover"
            if np.isfinite(max_drawdown) and max_drawdown < -0.30
            else "falls have stayed within normal bounds"
        ),
    )


def trend_pillar(closes: pd.DataFrame, weights: pd.Series) -> Pillar:
    """
    Weighted share of the portfolio trading above its own long-term average.

    Weighted rather than counted, because a 40% holding rolling over matters
    more than a 2% one.

    The moving average is pandas' own rather than the openalgo indicators SDK:
    this repository is itself a package named ``openalgo``, so inside it
    ``from openalgo import indicators`` resolves to the project rather than to
    the installed SDK, and which one wins depends on how sys.path was built.
    A 200-session mean does not justify an import that ambiguous, and both
    compute the same number.
    """
    above: dict[str, bool] = {}
    for symbol in closes.columns:
        series = closes[symbol].dropna()
        if len(series) < TREND_LOOKBACK:
            continue  # not enough history to have a long-term trend
        last_sma = series.rolling(TREND_LOOKBACK).mean().iloc[-1]
        if np.isfinite(last_sma):
            above[symbol] = bool(series.iloc[-1] > last_sma)

    if not above:
        return Pillar(
            key="trend",
            label="Trend health",
            score=float("nan"),
            weight=0.10,
            formula=f"weight above the {TREND_LOOKBACK}-session moving average",
            inputs={"measured": 0},
            comment=f"less than {TREND_LOOKBACK} sessions of history",
        )

    w = weights / weights.sum()
    covered = w[list(above)].sum()
    share = float(sum(w[s] for s, ok in above.items() if ok) / covered) if covered else 0.0
    return Pillar(
        key="trend",
        label="Trend health",
        score=share * 100.0,
        weight=0.10,
        formula=(
            f"portfolio weight trading above its {TREND_LOOKBACK}-session simple "
            f"moving average, as a share of the weight that could be measured"
        ),
        inputs={
            "above": sorted(s for s, ok in above.items() if ok),
            "below": sorted(s for s, ok in above.items() if not ok),
            "measured_weight": round(float(covered), 4),
        },
        comment=(
            "most of the book is below its long-term average"
            if share < 0.5
            else "most of the book is trending up"
        ),
    )


def cost_pillar(cost_drag: float, turnover: float) -> Pillar:
    score = _scale(-cost_drag, -COST_DRAG_FLOOR, 0.0)
    return Pillar(
        key="cost",
        label="Cost efficiency",
        score=score,
        weight=0.10,
        formula=(
            f"return given up to trading costs, scaled from {COST_DRAG_FLOOR:.0%} "
            f"to 0%; lower is better"
        ),
        inputs={
            "cost_drag": round(float(cost_drag), 6),
            "turnover_total": round(float(turnover), 4),
        },
        comment=(
            "rebalancing is eating a meaningful share of the return"
            if cost_drag > 0.02
            else "trading costs are not material"
        ),
    )


def grade_for(score: float) -> str:
    for cutoff, letter in GRADES:
        if score >= cutoff:
            return letter
    return "F"


def portfolio_health(
    *,
    weights: pd.Series,
    returns: pd.DataFrame,
    closes: pd.DataFrame,
    sharpe: float,
    sortino: float,
    max_drawdown: float,
    cost_drag: float,
    turnover: float,
) -> dict:
    """
    Score the portfolio and return the grade together with every pillar's
    working, so the number can be argued with rather than merely believed.

    A pillar that cannot be measured (too little history for a trend, a single
    holding for correlation) is dropped from the weighted average rather than
    scored zero -- absence of evidence is not a failing grade -- and the
    remaining weights are renormalised.
    """
    pillars = [
        concentration_pillar(weights),
        diversification_pillar(returns),
        efficiency_pillar(sharpe, sortino),
        drawdown_pillar(max_drawdown),
        trend_pillar(closes, weights),
        cost_pillar(cost_drag, turnover),
    ]

    scored = [p for p in pillars if np.isfinite(p.score)]
    total_weight = sum(p.weight for p in scored)
    overall = (
        float(sum(p.score * p.weight for p in scored) / total_weight)
        if total_weight > 0
        else float("nan")
    )

    return {
        "score": None if not np.isfinite(overall) else round(overall, 1),
        "grade": grade_for(overall) if np.isfinite(overall) else None,
        "pillars": [
            {
                **asdict(p),
                "score": None if not np.isfinite(p.score) else round(p.score, 1),
                # What this pillar actually contributed, after renormalising
                # around any pillar that could not be measured.
                "effective_weight": (
                    round(p.weight / total_weight, 4)
                    if np.isfinite(p.score) and total_weight > 0
                    else 0.0
                ),
            }
            for p in pillars
        ],
        "unmeasured": [p.key for p in pillars if not np.isfinite(p.score)],
    }
