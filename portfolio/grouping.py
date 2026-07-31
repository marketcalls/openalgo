"""
What is this portfolio actually made of?

The obvious answer is a sector pie chart. OpenAlgo's symbol master has no
sector or market-cap field -- it carries symbol, name, exchange, token, expiry,
strike, lotsize, instrument type and tick size, and nothing else -- so a sector
breakdown here would have to be invented, stale, or fetched from somewhere that
does not exist yet. The reference products that show one mostly print
"Other 100%" for the same reason.

So this measures grouping the way the data allows, which is arguably the better
question anyway: **which holdings actually move together**. A sector label is a
proxy for co-movement; correlation is the thing itself. Two banks in different
"sectors" that trade as one position are one bet, and a sector chart would
happily show them as two.

Instrument class (ETF against single stock) is inferred from the name, and
flagged as a heuristic, because that is honestly all the field supports.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Words that identify a pooled vehicle in an Indian listing name. Names are all
# the symbol master offers, so this is a heuristic and labelled as one.
_FUND_MARKERS = ("ETF", "BEES", "FUND", "INDEX", "NIFTY", "SENSEX", "GOLD", "SILVER")


def classify_instrument(symbol: str, name: str | None) -> str:
    """
    ``fund`` for a pooled vehicle, ``stock`` for a single company.

    A guess from the listing name, not a lookup: the symbol master has no
    instrument-class field that distinguishes them -- NIFTYBEES and RELIANCE
    both carry the series code 'EQ'.
    """
    haystack = f"{symbol} {name or ''}".upper()
    return "fund" if any(marker in haystack for marker in _FUND_MARKERS) else "stock"


def correlation_clusters(
    returns: pd.DataFrame, threshold: float = 0.6
) -> list[list[str]]:
    """
    Group holdings that move together above ``threshold``.

    0.6 rather than the instinctive 0.7, calibrated against real daily NSE
    returns: over 2016-2026 the highest pair among NIFTYBEES, GOLDBEES,
    RELIANCE, INFY, ICICIBANK and SBIN is 0.69, two large private banks sit at
    0.64, and gold is flat against everything. A 0.7 threshold can therefore
    never fire on daily Indian equity data, which makes the clustering look
    reassuring precisely when it should not.

    Single-linkage: a holding joins a group if it is correlated with *any*
    member, which is the right rule for the question being asked. If A moves
    with B and B moves with C, a shock to B hits all three, whatever the
    correlation between A and C happens to be.
    """
    symbols = list(returns.columns)
    if len(symbols) < 2:
        return [[s] for s in symbols]

    corr = returns.corr().to_numpy()
    parent = list(range(len(symbols)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            value = corr[i, j]
            if np.isfinite(value) and value >= threshold:
                a, b = find(i), find(j)
                if a != b:
                    parent[b] = a

    groups: dict[int, list[str]] = {}
    for i, symbol in enumerate(symbols):
        groups.setdefault(find(i), []).append(symbol)
    # Largest first: the biggest cluster is the one that matters.
    return sorted(groups.values(), key=len, reverse=True)


def structure(
    weights: pd.Series,
    returns: pd.DataFrame,
    names: dict[str, str] | None = None,
    *,
    threshold: float = 0.6,
) -> dict:
    """
    Composition of the portfolio: instrument class, and co-movement clusters.

    ``effective_bets`` is the headline. A portfolio of ten holdings that all
    move together is one bet wearing ten names, and this counts the clusters
    rather than the names.
    """
    names = names or {}
    total = float(weights.sum()) or 1.0
    w = weights / total

    classes: dict[str, float] = {}
    for symbol in weights.index:
        kind = classify_instrument(symbol, names.get(symbol))
        classes[kind] = classes.get(kind, 0.0) + float(w[symbol])

    clusters = correlation_clusters(returns, threshold)
    cluster_rows = []
    for i, members in enumerate(clusters):
        held = [m for m in members if m in w.index]
        weight = float(sum(w[m] for m in held))
        cluster_rows.append(
            {
                "id": i + 1,
                "members": held,
                "weight": round(weight, 5),
                # A cluster of one is a genuinely independent holding.
                "independent": len(held) == 1,
            }
        )
    cluster_rows.sort(key=lambda r: r["weight"], reverse=True)

    return {
        "instrument_classes": {k: round(v, 5) for k, v in classes.items()},
        "instrument_class_basis": "inferred from the listing name",
        "clusters": cluster_rows,
        "threshold": threshold,
        "effective_bets": len(cluster_rows),
        "largest_cluster_weight": (
            round(max((r["weight"] for r in cluster_rows), default=0.0), 5)
        ),
        # Stated rather than silently omitted, so nobody reads the absence of a
        # sector chart as an oversight.
        "sector_note": (
            "Sector and market-cap breakdowns are not shown: OpenAlgo's symbol "
            "master carries no sector or market-cap field, and inventing one "
            "would be worse than omitting it. Co-movement clustering answers "
            "the same question from data that actually exists."
        ),
    }
