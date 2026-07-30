"""
Where did the out- or under-performance come from?

The textbook answer is Brinson-Fachler: split excess return into an allocation
effect and a selection effect by comparing the portfolio's weight and return in
each segment against the benchmark's. That needs the benchmark's **constituent
weights and per-segment returns**, and openalgo has neither -- the benchmark is
a single index price series, and nothing in the codebase holds index membership.
Computing Brinson without them would mean inventing the very numbers the method
exists to compare against.

So this decomposes what the data supports, and it answers the two questions an
investor actually asks:

- **Selection** -- were these the right things to own? Measured as what an
  equal-weighted basket of the same holdings would have returned against the
  benchmark. It isolates the picks from the sizing.
- **Allocation** -- did the weighting help? Measured as the actual portfolio
  against that equal-weighted basket. Positive means capital was concentrated
  in the holdings that did better.

The two sum exactly to the excess return over the benchmark, which is the
property that makes it an attribution rather than two loosely related numbers.

Per-holding contribution to excess is also reported: ``w_i x (r_i - r_bench)``,
which sums to the excess for the same reason weights sum to one.
"""

from __future__ import annotations

import pandas as pd


def _compound(series: pd.Series) -> float:
    return float((1.0 + series.dropna()).prod() - 1.0)


def attribution(
    holding_returns: pd.DataFrame,
    weights: pd.Series,
    benchmark_returns: pd.Series | None,
) -> dict:
    """
    Split excess return into selection (the picks) and allocation (the sizing).

    ``weights`` should be the weights actually held on average, not the targets:
    a portfolio that drifted was not the one the targets describe, and
    attributing its result to targets it stopped following would be wrong.
    """
    if holding_returns.empty or benchmark_returns is None or benchmark_returns.empty:
        return {"available": False, "reason": "a benchmark is required to attribute against"}

    aligned = holding_returns.join(
        benchmark_returns.rename("__benchmark__"), how="inner"
    ).dropna()
    if aligned.empty or len(aligned) < 2:
        return {"available": False, "reason": "no overlapping sessions with the benchmark"}

    bench = aligned["__benchmark__"]
    holdings = aligned.drop(columns="__benchmark__")
    symbols = [c for c in holdings.columns if c in weights.index]
    if not symbols:
        return {"available": False, "reason": "no priced holdings to attribute"}

    w = weights[symbols].astype(float)
    w = w / w.sum()
    equal = pd.Series(1.0 / len(symbols), index=symbols)

    # Portfolio and equal-weight paths, compounded rather than summed: an
    # arithmetic split would not reconcile with the equity curve the rest of
    # the report is built from.
    actual_path = (holdings[symbols] * w).sum(axis=1)
    equal_path = (holdings[symbols] * equal).sum(axis=1)

    actual = _compound(actual_path)
    equal_return = _compound(equal_path)
    benchmark = _compound(bench)

    selection = equal_return - benchmark
    allocation = actual - equal_return
    excess = actual - benchmark

    bench_total = benchmark
    rows = []
    for symbol in symbols:
        own = _compound(holdings[symbol])
        rows.append(
            {
                "symbol": symbol,
                "weight": round(float(w[symbol]), 5),
                "return": round(own, 6),
                "vs_benchmark": round(own - bench_total, 6),
                # Sums to the excess: this is the holding's share of the
                # out- or under-performance, not its standalone result.
                "contribution": round(float(w[symbol]) * (own - bench_total), 6),
            }
        )
    rows.sort(key=lambda r: r["contribution"], reverse=True)

    return {
        "available": True,
        "portfolio_return": round(actual, 6),
        "equal_weight_return": round(equal_return, 6),
        "benchmark_return": round(benchmark, 6),
        "excess_return": round(excess, 6),
        "selection_effect": round(selection, 6),
        "allocation_effect": round(allocation, 6),
        "holdings": rows,
        "method": (
            "Selection is an equal-weighted basket of the same holdings against "
            "the benchmark; allocation is the actual portfolio against that "
            "basket. Brinson-Fachler is not used because it needs the "
            "benchmark's constituent weights and segment returns, which are not "
            "available here."
        ),
    }
