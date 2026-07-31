"""
Explain excess return using only data OpenAlgo actually has.

This is deliberately not Brinson-Fachler. Brinson needs benchmark constituent
weights and segment returns, while OpenAlgo has only a benchmark price series.
The supported decomposition is:

- selection: an equal-weighted basket of the same holdings versus benchmark;
- allocation: the realized gross portfolio path versus that equal basket;
- costs: the engine's net portfolio path versus its gross path.

Those effects reconcile exactly to the net excess return. Per-holding excess
contributions are only published when the engine's full-period contribution
rows cover the same sessions.
"""

from __future__ import annotations

from math import isclose

import pandas as pd


def _compound(series: pd.Series) -> float:
    return float((1.0 + series.dropna()).prod() - 1.0)


def attribution(
    holding_returns: pd.DataFrame,
    realized_weights: pd.DataFrame,
    target_weights: pd.Series,
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series | None,
    item_contributions: pd.Series | None = None,
) -> dict:
    """Split net excess return into selection, allocation, and trading costs."""
    if holding_returns.empty or benchmark_returns is None or benchmark_returns.empty:
        return {"available": False, "reason": "a benchmark is required to attribute against"}

    symbols = [
        symbol
        for symbol in holding_returns.columns
        if symbol in realized_weights.columns and symbol in target_weights.index
    ]
    if not symbols:
        return {"available": False, "reason": "no priced holdings to attribute"}

    target = target_weights[symbols].astype(float)
    if target.sum() <= 0:
        return {"available": False, "reason": "target weights sum to zero"}
    target = target / target.sum()

    # A session's return is earned on the allocation held at the previous
    # close. The engine's row for the current close already includes any
    # rebalance performed after that session's price move.
    lagged_weights = realized_weights[symbols].shift(1).reindex(holding_returns.index)
    holdings = holding_returns[symbols].copy()
    holdings.columns = [f"holding:{symbol}" for symbol in symbols]
    lagged_weights = lagged_weights.copy()
    lagged_weights.columns = [f"weight:{symbol}" for symbol in symbols]

    aligned = pd.concat(
        [
            holdings,
            lagged_weights,
            portfolio_returns.rename("__net__"),
            benchmark_returns.rename("__benchmark__"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 2:
        return {"available": False, "reason": "no overlapping sessions with the benchmark"}

    gross_path = sum(
        aligned[f"holding:{symbol}"] * aligned[f"weight:{symbol}"]
        for symbol in symbols
    )
    equal_path = aligned[[f"holding:{symbol}" for symbol in symbols]].mean(axis=1)
    net_path = aligned["__net__"]
    benchmark_path = aligned["__benchmark__"]

    gross_return = _compound(gross_path)
    net_return = _compound(net_path)
    equal_return = _compound(equal_path)
    benchmark_return = _compound(benchmark_path)

    selection = equal_return - benchmark_return
    allocation = gross_return - equal_return
    cost_effect = net_return - gross_return
    excess = net_return - benchmark_return

    exact_periods = (
        holding_returns.index.equals(portfolio_returns.index)
        and holding_returns.index.equals(benchmark_returns.index)
        and len(aligned) == len(holding_returns)
    )
    rows: list[dict] = []
    holdings_reason = None
    if exact_periods and item_contributions is not None:
        contributions = item_contributions.reindex(symbols)
        if contributions.notna().all() and isclose(
            float(contributions.sum()),
            net_return,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            for symbol in symbols:
                own_return = _compound(aligned[f"holding:{symbol}"])
                rows.append(
                    {
                        "symbol": symbol,
                        "weight": float(target[symbol]),
                        "return": own_return,
                        "vs_benchmark": own_return - benchmark_return,
                        "contribution": (
                            float(contributions[symbol])
                            - float(target[symbol]) * benchmark_return
                        ),
                    }
                )
            rows.sort(key=lambda row: row["contribution"], reverse=True)
        else:
            holdings_reason = (
                "engine holding contributions do not reconcile to this period"
            )
    else:
        holdings_reason = (
            "per-holding contributions require the benchmark and engine result "
            "to cover identical sessions"
        )

    return {
        "available": True,
        "portfolio_return": net_return,
        "gross_portfolio_return": gross_return,
        "equal_weight_return": equal_return,
        "benchmark_return": benchmark_return,
        "excess_return": excess,
        "selection_effect": selection,
        "allocation_effect": allocation,
        "cost_effect": cost_effect,
        "holdings": rows,
        "holdings_reason": holdings_reason,
        "method": (
            "Selection compares an equal-weighted basket of the same holdings "
            "with the benchmark; allocation compares the realized gross "
            "portfolio with that basket; costs compare the engine's net and "
            "gross paths. Brinson-Fachler is not used because benchmark "
            "constituent weights and segment returns are unavailable."
        ),
    }
