"""
Portfolio Backtester — a time-series momentum and allocation engine for
investors, self-hosted inside OpenAlgo.

Scope is deliberately investor-shaped, not trader-shaped: daily bars, weight
targets, and calendar or drift-band rebalancing. There is no matching engine,
no latency model and no order book, because none of those change the answer to
"what would this allocation have returned". That is also why this is built on
pandas/numpy rather than an event-driven backtester -- the whole computation is
a price matrix, a weight vector and a set of rebalance dates.

Analytics come from `openstatz`, which owns the metric formulas so they cannot
drift between this engine and the rest of the ecosystem.
"""

from portfolio.data import (
    PriceMatrix,
    DataError,
    MissingHistory,
    UnsupportedExchange,
    SUPPORTED_EXCHANGES,
    load_prices,
    split_artifacts,
)

__all__ = [
    "PriceMatrix",
    "DataError",
    "MissingHistory",
    "UnsupportedExchange",
    "SUPPORTED_EXCHANGES",
    "load_prices",
    "split_artifacts",
]
