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
    SUPPORTED_EXCHANGES,
    DataError,
    MissingHistory,
    PriceMatrix,
    UnsupportedExchange,
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


def warm_analytics() -> None:
    """
    Import openstatz ahead of the first request, in the background.

    Importing it costs about 1.4 seconds -- almost all of it matplotlib and
    seaborn, pulled in by openstatz's plotting module, which this feature never
    uses because every chart is rendered in the browser. Left lazy, the first
    user to open a report pays that; imported at module scope, every Flask boot
    pays it even if nobody opens one. A daemon thread at startup costs neither.
    """
    import threading

    def _load() -> None:
        try:
            import openstatz.stats  # noqa: F401
        except Exception:  # noqa: BLE001 -- warming is best-effort
            pass

    threading.Thread(target=_load, name="portfolio-warm-analytics", daemon=True).start()
