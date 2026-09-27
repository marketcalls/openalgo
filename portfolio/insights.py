"""
SWOT for a portfolio, derived rather than asserted.

Products in this space print things like "High Concentration Risk" with no
number attached, which leaves the reader unable to tell an observation from a
slogan. Every finding here carries the figure that produced it and the
threshold it crossed, so a user can disagree with the judgement rather than
only with the vibe.

Nothing is invented: each rule reads values the report already computed --
health pillars, correlation clusters, attribution, crisis behaviour, the
rebalancing sweep -- and turns the ones that crossed a line into a sentence.
A portfolio with nothing wrong produces few findings, which is the correct
outcome and not an empty state to be padded.

Opportunities and threats are forward-looking by nature and are phrased as
observations about the present, never as predictions: "this holding is 62% of
the book" rather than "this will fall".
"""

from __future__ import annotations

from dataclasses import dataclass, field

STRENGTH = "strength"
WEAKNESS = "weakness"
OPPORTUNITY = "opportunity"
THREAT = "threat"


@dataclass
class Finding:
    kind: str
    tag: str
    title: str
    detail: str
    #: 0-1. Drives ordering and which one becomes the headline.
    severity: float = 0.5
    evidence: dict = field(default_factory=dict)


def _pct(value: float | None, dp: int = 1) -> str:
    return "n/a" if value is None else f"{value * 100:.{dp}f}%"


def build_findings(report: dict) -> dict:
    """
    Turn a finished backtest report into a SWOT, plus the single headline.

    ``report`` is the payload the service already assembles, so this adds no
    computation of its own and cannot disagree with the numbers shown elsewhere.
    """
    metrics = report.get("metrics") or {}
    health = report.get("health") or {}
    structure = report.get("structure") or {}
    attribution = report.get("attribution") or {}
    crisis = (report.get("crisis") or {}).get("summary") or {}
    sweep = report.get("rebalancing_sweep") or {}
    costs = report.get("costs") or {}
    items = report.get("items") or []

    out: list[Finding] = []

    # ── Versus the benchmark ────────────────────────────────────────────────
    excess = metrics.get("excess_cagr")
    if excess is not None:
        if excess < -0.01:
            out.append(Finding(
                WEAKNESS, "Lagging the market",
                "Lagging the market",
                f"The portfolio is behind its benchmark by {_pct(abs(excess))} a year. "
                f"It compounded at {_pct(metrics.get('cagr'))} against "
                f"{_pct(metrics.get('benchmark_cagr'))}.",
                severity=min(1.0, 0.5 + abs(excess) * 4),
                evidence={"excess_cagr": excess},
            ))
        elif excess > 0.01:
            out.append(Finding(
                STRENGTH, "Beating the market",
                "Ahead of the benchmark",
                f"The portfolio is ahead by {_pct(excess)} a year, compounding at "
                f"{_pct(metrics.get('cagr'))} against {_pct(metrics.get('benchmark_cagr'))}.",
                severity=min(1.0, 0.5 + excess * 4),
                evidence={"excess_cagr": excess},
            ))

    # ── Is the risk being paid for ──────────────────────────────────────────
    sharpe = metrics.get("sharpe")
    if sharpe is not None:
        if sharpe < 0:
            out.append(Finding(
                WEAKNESS, "Unrewarded risk",
                "Risk without reward",
                f"Sharpe is {sharpe:.2f}: the portfolio carried "
                f"{_pct(metrics.get('volatility'))} volatility and was not paid for it.",
                severity=0.9,
                evidence={"sharpe": sharpe},
            ))
        elif sharpe > 1.0:
            out.append(Finding(
                STRENGTH, "Efficient",
                "Well paid for the risk taken",
                f"Sharpe is {sharpe:.2f} on {_pct(metrics.get('volatility'))} volatility.",
                severity=min(1.0, sharpe / 2),
                evidence={"sharpe": sharpe},
            ))

    # ── Defensiveness, from capture rather than from a claim ───────────────
    up, down = metrics.get("up_capture"), metrics.get("down_capture")
    if up is not None and down is not None and down > 0:
        if down < up:
            out.append(Finding(
                STRENGTH, "Defensive",
                "Falls less than it rises",
                f"It captures {up * 100:.0f}% of the benchmark's up moves and only "
                f"{down * 100:.0f}% of its falls.",
                severity=0.6,
                evidence={"up_capture": up, "down_capture": down},
            ))
        elif down > up + 0.1:
            out.append(Finding(
                WEAKNESS, "Poor asymmetry",
                "Falls more than it rises",
                f"It takes {down * 100:.0f}% of the benchmark's falls but only "
                f"{up * 100:.0f}% of its gains.",
                severity=0.8,
                evidence={"up_capture": up, "down_capture": down},
            ))

    # ── Concentration, in substance not in name ────────────────────────────
    bets = structure.get("effective_bets")
    largest = structure.get("largest_cluster_weight")
    if bets is not None and largest is not None and items:
        if largest > 0.5 and len(items) > 2:
            members = next(
                (c["members"] for c in structure.get("clusters", []) if c["weight"] == largest),
                [],
            )
            out.append(Finding(
                THREAT, "Concentration",
                "Concentrated despite the holding count",
                f"{_pct(largest, 0)} of the book moves as one position "
                f"({', '.join(members[:4])}{'...' if len(members) > 4 else ''}). "
                f"{len(items)} holdings behave like {bets} independent bets.",
                severity=min(1.0, largest + 0.2),
                evidence={"largest_cluster_weight": largest, "effective_bets": bets},
            ))
        elif bets >= max(3, len(items) * 0.7):
            out.append(Finding(
                STRENGTH, "Genuinely diversified",
                "Holdings move independently",
                f"{len(items)} holdings behave like {bets} independent bets, so a "
                f"shock to one is unlikely to take the rest with it.",
                severity=0.5,
                evidence={"effective_bets": bets},
            ))

    # ── Single-name weight ─────────────────────────────────────────────────
    heaviest = max(items, key=lambda i: i.get("weight_final") or 0, default=None)
    if heaviest and (heaviest.get("weight_final") or 0) > 0.4 and len(items) > 1:
        out.append(Finding(
            THREAT, "Single-name risk",
            "One holding dominates",
            f"{heaviest['symbol']} is {_pct(heaviest['weight_final'], 0)} of the "
            f"portfolio. Its result is close to the portfolio's result.",
            severity=min(1.0, (heaviest.get("weight_final") or 0) + 0.3),
            evidence={"symbol": heaviest["symbol"], "weight": heaviest.get("weight_final")},
        ))

    # ── Drawdown ───────────────────────────────────────────────────────────
    dd = metrics.get("max_drawdown")
    if dd is not None:
        if dd < -0.30:
            out.append(Finding(
                THREAT, "Deep drawdown",
                "It has fallen a long way before",
                f"The worst peak-to-trough fall was {_pct(dd)}, which needs a "
                f"{_pct(1 / (1 + dd) - 1)} gain simply to recover.",
                severity=min(1.0, abs(dd) + 0.4),
                evidence={"max_drawdown": dd},
            ))
        elif dd > -0.15:
            out.append(Finding(
                STRENGTH, "Shallow drawdowns",
                "Falls have stayed contained",
                f"The worst fall was {_pct(dd)}.",
                severity=0.4,
                evidence={"max_drawdown": dd},
            ))

    # ── What actually drove the result ─────────────────────────────────────
    if attribution.get("available") and attribution.get("holdings"):
        rows = attribution["holdings"]
        best, worst = rows[0], rows[-1]
        if worst["contribution"] < -0.02:
            out.append(Finding(
                WEAKNESS, "Wealth eroder",
                f"{worst['symbol']} is costing the portfolio",
                f"It returned {_pct(worst['return'])} against the benchmark's "
                f"{_pct(attribution.get('benchmark_return'))}, taking "
                f"{_pct(abs(worst['contribution']))} off the result at "
                f"{_pct(worst['weight'], 0)} weight.",
                severity=min(1.0, abs(worst["contribution"]) * 3 + 0.4),
                evidence={"symbol": worst["symbol"], "contribution": worst["contribution"]},
            ))
        if best["contribution"] > 0.02 and best["weight"] < 0.15:
            out.append(Finding(
                OPPORTUNITY, "Underweight winner",
                f"{best['symbol']} did well on a small position",
                f"It returned {_pct(best['return'])} but held only "
                f"{_pct(best['weight'], 0)} of the book. A larger position would "
                f"have contributed more than the {_pct(best['contribution'])} it did.",
                severity=0.6,
                evidence={"symbol": best["symbol"], "weight": best["weight"]},
            ))
        selection = attribution.get("selection_effect")
        allocation = attribution.get("allocation_effect")
        if selection is not None and allocation is not None and allocation < -0.02:
            out.append(Finding(
                OPPORTUNITY, "Sizing is costing you",
                "The weighting is working against the picks",
                f"An equal-weighted version of the same holdings would have "
                f"returned {_pct(attribution.get('equal_weight_return'))} against the "
                f"actual {_pct(attribution.get('portfolio_return'))}. The picks added "
                f"{_pct(selection)}; the sizing took {_pct(abs(allocation))} back.",
                severity=0.7,
                evidence={"allocation_effect": allocation},
            ))

    # ── Rebalancing, straight from the sweep ───────────────────────────────
    variants = sweep.get("variants") or []
    current_rule = (report.get("meta") or {}).get("rule")
    best_label = sweep.get("best_by_sharpe")
    if variants and best_label:
        current = next((v for v in variants if v["rule"] == current_rule), None)
        best = next((v for v in variants if v["label"] == best_label), None)
        if current and best and best["label"] != current["label"]:
            gain = best["sharpe"] - current["sharpe"]
            if gain > 0.02:
                out.append(Finding(
                    OPPORTUNITY, "Better rebalancing rule",
                    f"{best['label']} rebalancing suits this portfolio better",
                    f"It reaches a Sharpe of {best['sharpe']:.2f} against "
                    f"{current['sharpe']:.2f} today, with "
                    f"{_pct(best['cost_drag'], 2)} of cost drag against "
                    f"{_pct(current['cost_drag'], 2)}.",
                    severity=0.55,
                    evidence={"suggested": best["label"], "sharpe_gain": gain},
                ))

    # ── Costs ──────────────────────────────────────────────────────────────
    drag = costs.get("drag")
    if drag is not None and drag > 0.01:
        out.append(Finding(
            WEAKNESS, "Cost drag",
            "Trading is eating the return",
            f"Costs took {_pct(drag, 2)} of the total return, on "
            f"{_pct(costs.get('turnover'), 0)} of turnover.",
            severity=min(1.0, drag * 20 + 0.3),
            evidence={"cost_drag": drag},
        ))

    # ── Behaviour when it mattered ─────────────────────────────────────────
    hit = crisis.get("hit_rate")
    if hit is not None and crisis.get("count", 0) >= 3:
        if hit >= 0.6:
            out.append(Finding(
                STRENGTH, "Holds up in stress",
                "It has beaten the benchmark in most crises",
                f"It outperformed in {hit * 100:.0f}% of the "
                f"{crisis['count']} stress periods covered, averaging "
                f"{_pct(crisis.get('average_return'))}.",
                severity=0.6,
                evidence={"hit_rate": hit},
            ))
        elif hit <= 0.4:
            out.append(Finding(
                THREAT, "Weak in stress",
                "It has lagged in most crises",
                f"It beat the benchmark in only {hit * 100:.0f}% of the "
                f"{crisis['count']} stress periods covered.",
                severity=0.7,
                evidence={"hit_rate": hit},
            ))

    # ── Whatever health flagged that nothing above caught ──────────────────
    for pillar in health.get("pillars", []):
        score = pillar.get("score")
        if score is None:
            continue
        if score < 30 and not any(f.tag.lower() == pillar["label"].lower() for f in out):
            out.append(Finding(
                WEAKNESS, pillar["label"],
                f"{pillar['label']} scores {score:.0f}/100",
                f"{pillar['comment']}. Measured as: {pillar['formula']}.",
                severity=0.4 + (30 - score) / 100,
                evidence={"pillar": pillar["key"], "score": score},
            ))

    out.sort(key=lambda f: f.severity, reverse=True)

    grouped = {
        "strengths": [f.__dict__ for f in out if f.kind == STRENGTH],
        "weaknesses": [f.__dict__ for f in out if f.kind == WEAKNESS],
        "opportunities": [f.__dict__ for f in out if f.kind == OPPORTUNITY],
        "threats": [f.__dict__ for f in out if f.kind == THREAT],
    }

    # The headline is the most severe finding of any kind, because the single
    # most important thing about a portfolio is as often a strength as a fault.
    headline = out[0].__dict__ if out else None

    return {
        "headline": headline,
        "tags": [{"kind": f.kind, "label": f.tag} for f in out[:6]],
        **grouped,
        "counts": {k: len(v) for k, v in grouped.items()},
    }
