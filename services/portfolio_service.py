"""
Portfolio backtest service facade.

Follows the service-layer contract used across OpenAlgo: returns
``(success, payload, status_code)`` and never raises for an input the caller
could have got wrong. The engine itself raises freely -- a backtest that
cannot be trusted must not quietly return a number -- so this layer is where
those become 4xx responses with the reason attached.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from portfolio.analytics import (
    average_pairwise_correlation,
    concentration,
    correlation_matrix,
    diversification_ratio,
    summary,
)
from portfolio.data import DataError, load_prices
from portfolio.engine import Costs, run_backtest
from portfolio.health import portfolio_health
from portfolio.rebalance import RebalancePolicy
from utils.logging import get_logger

logger = get_logger(__name__)

# A backtest holds every symbol's full history in memory and is synchronous.
# The cap is about keeping one request bounded, not about the maths.
MAX_SYMBOLS = 50


def _curve(series: pd.Series) -> list[dict[str, Any]]:
    """A date/value series as JSON rows, rounded to something a chart can use."""
    return [
        {"date": stamp.date().isoformat(), "value": round(float(value), 4)}
        for stamp, value in series.items()
    ]


def _clean(value: Any) -> Any:
    """
    NaN and infinity are not JSON. They arise legitimately -- a capture ratio
    for a regime that never occurred, a correlation with too little overlap --
    so they become null rather than being dropped, which would silently change
    the shape of the response.
    """
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return round(value, 6)
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    return value


def run_portfolio_backtest(
    holdings: list[dict[str, Any]],
    start_date: str,
    end_date: str,
    *,
    benchmark: str | None = None,
    benchmark_exchange: str = "NSE",
    rebalance: str = "never",
    drift_band: float = 0.0,
    cost_bps: float = 0.0,
    slippage: float = 0.0,
    initial_capital: float = 100_000.0,
    risk_free_rate: float = 0.0,
    source: str = "db",
    api_key: str | None = None,
    auth_token: str | None = None,
    feed_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Run one portfolio backtest and return everything the UI tabs need.

    ``holdings`` is ``[{"symbol", "exchange", "weight"}, ...]``. Weights may be
    percentages or fractions; only their ratio matters.
    """
    if not holdings:
        return False, {"status": "error", "message": "no holdings supplied"}, 400
    if len(holdings) > MAX_SYMBOLS:
        return (
            False,
            {
                "status": "error",
                "message": f"{len(holdings)} holdings exceeds the {MAX_SYMBOLS} limit",
            },
            400,
        )

    try:
        symbols = [str(h["symbol"]).strip().upper() for h in holdings]
        exchanges = [str(h.get("exchange", "NSE")).strip().upper() for h in holdings]
        weights = {s: float(h.get("weight", 0)) for s, h in zip(symbols, holdings)}
    except (KeyError, TypeError, ValueError) as exc:
        return False, {"status": "error", "message": f"malformed holding: {exc}"}, 400

    if len(set(symbols)) != len(symbols):
        return False, {"status": "error", "message": "duplicate symbol in holdings"}, 400

    fetch = dict(
        source=source, api_key=api_key, auth_token=auth_token,
        feed_token=feed_token, broker=broker,
    )

    try:
        prices = load_prices(symbols, exchanges, start_date, end_date, **fetch)
        result = run_backtest(
            prices,
            weights,
            policy=RebalancePolicy(rule=rebalance, drift_band=drift_band),
            costs=Costs(bps=cost_bps, slippage=slippage),
            initial_capital=initial_capital,
        )
    except DataError as exc:
        # The caller asked for something the data cannot answer: a symbol with
        # no history, an unsupported exchange, a window with no overlap.
        return False, {"status": "error", "message": str(exc)}, 422
    except ValueError as exc:
        return False, {"status": "error", "message": str(exc)}, 400
    except Exception as exc:  # noqa: BLE001 - the facade must not leak a 500 body
        logger.exception("portfolio backtest failed")
        return False, {"status": "error", "message": f"backtest failed: {exc}"}, 500

    bench_returns = None
    bench_curve: list[dict[str, Any]] = []
    if benchmark:
        try:
            bench_prices = load_prices(
                [benchmark.strip().upper()], benchmark_exchange,
                start_date, end_date, **fetch,
            )
            # Aligned to the portfolio's sessions so every relative number is
            # computed on the same days rather than on a longer benchmark run.
            bench_close = bench_prices.closes.iloc[:, 0].reindex(prices.closes.index)
            bench_close = bench_close.ffill().dropna()
            if len(bench_close) > 1:
                bench_returns = bench_close.pct_change().iloc[1:]
                bench_curve = _curve(bench_close / bench_close.iloc[0] * initial_capital)
        except DataError as exc:
            # A missing benchmark degrades the report; it does not invalidate
            # the portfolio the user actually asked about.
            logger.warning("benchmark %s unavailable: %s", benchmark, exc)

    returns = result.returns
    holding_returns = prices.returns()
    target_weights = pd.Series(result.meta["target_weights"])

    corr = correlation_matrix(holding_returns)
    metrics = _clean(summary(returns, bench_returns, rf=risk_free_rate))
    payload = {
        "status": "success",
        "meta": {
            **result.meta,
            "source": result.source,
            "start": str(prices.start),
            "end": str(prices.end),
            "benchmark": benchmark,
            "risk_free_rate": risk_free_rate,
            # Broker history is price-return, so dividends are absent from
            # every figure here. Stated rather than implied.
            "total_return_basis": "price",
            "data_warnings": prices.warnings,
        },
        "equity": _curve(result.equity),
        "benchmark_equity": bench_curve,
        "metrics": metrics,
        "items": _clean(
            [
                {"symbol": symbol, **{k: v for k, v in row.items()}}
                for symbol, row in result.items.to_dict(orient="index").items()
            ]
        ),
        "correlation": {
            "symbols": list(corr.columns),
            "matrix": _clean(corr.to_numpy().tolist()) if not corr.empty else [],
            "average_pairwise": _clean(average_pairwise_correlation(holding_returns)),
        },
        "diversification": _clean(
            {
                **concentration(target_weights),
                "diversification_ratio": diversification_ratio(
                    target_weights, holding_returns
                ),
            }
        ),
        # The grade with its working attached, so it can be argued with rather
        # than merely believed.
        "health": portfolio_health(
            weights=target_weights,
            returns=holding_returns,
            closes=prices.closes,
            sharpe=metrics.get("sharpe", float("nan")) or float("nan"),
            sortino=metrics.get("sortino", float("nan")) or float("nan"),
            max_drawdown=metrics.get("max_drawdown", float("nan")) or float("nan"),
            cost_drag=result.cost_drag,
            turnover=float(result.turnover.sum()),
        ),
        "rebalancing": {
            "rule": rebalance,
            "drift_band": drift_band,
            "count": len(result.rebalance_dates),
            "cost_drag": _clean(result.cost_drag),
            "turnover_total": _clean(float(result.turnover.sum())),
            "dates": [d.date().isoformat() for d in result.rebalance_dates],
        },
    }
    return True, payload, 200
