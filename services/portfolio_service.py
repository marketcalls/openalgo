"""
Portfolio backtest service facade.

Follows the service-layer contract used across OpenAlgo: returns
``(success, payload, status_code)`` and never raises for an input the caller
could have got wrong. The engine itself raises freely -- a backtest that
cannot be trusted must not quietly return a number -- so this layer is where
those become 4xx responses with the reason attached.
"""

from __future__ import annotations

import dataclasses

from typing import Any

import pandas as pd

from portfolio.analytics import (
    average_pairwise_correlation,
    concentration,
    correlation_matrix,
    diversification_ratio,
    summary,
)
from portfolio.data import BENCHMARK_EXCHANGES, DataError, load_prices
from portfolio.costs import CostSchedule, schedule_for
from portfolio.crisis import crisis_analysis
from portfolio.grouping import structure
from portfolio.engine import Costs, run_backtest
from portfolio.health import portfolio_health
from portfolio.rebalance import RebalancePolicy
from portfolio.walkforward import monte_carlo, walk_forward
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


def _symbol_names(symbols: list[str]) -> dict[str, str]:
    """Listing names, for the instrument-class heuristic. Best effort."""
    try:
        from database.symbol import SymToken, db_session

        rows = (
            db_session.query(SymToken.symbol, SymToken.name)
            .filter(SymToken.symbol.in_(symbols))
            .all()
        )
        return {r[0]: r[1] or "" for r in rows}
    except Exception:  # noqa: BLE001 -- a label is not worth failing a run over
        logger.debug("symbol names unavailable", exc_info=True)
        return {}


def _allocation_path(weights: pd.DataFrame, max_points: int = 400) -> dict[str, Any]:
    """
    Portfolio weights over time, thinned to something a chart can draw.

    Note there is no cash sleeve: this engine is long-only and fully invested,
    so the weights always sum to 1. A cash band would be a straight zero, and
    drawing one would imply a capability the engine does not have.
    """
    if weights.empty:
        return {"dates": [], "symbols": [], "series": {}, "average": {}}

    step = max(1, len(weights) // max_points)
    thinned = weights.iloc[::step]
    # Always keep the final session: it is the allocation the user ends with,
    # and dropping it would misreport where the drift landed.
    if thinned.index[-1] != weights.index[-1]:
        thinned = pd.concat([thinned, weights.iloc[[-1]]])

    return {
        "dates": [d.date().isoformat() for d in thinned.index],
        "symbols": list(weights.columns),
        "series": {c: [round(float(v), 5) for v in thinned[c]] for c in weights.columns},
        # What each holding averaged over the whole run -- the target weight
        # only describes the moments just after a rebalance.
        "average": {c: round(float(weights[c].mean()), 5) for c in weights.columns},
    }


def _series_analytics(
    returns: pd.Series, rf: float, benchmark: pd.Series | None = None
) -> dict[str, Any]:
    """
    The series openstatz can produce that a table of headline numbers cannot
    convey: when the drawdowns happened, how the risk profile moved, and the
    month-by-month grid an investor actually reads a track record from.

    Every one is derived from the same return series the metrics come from, so
    a chart and a statistic can never disagree.
    """
    import openstatz.stats as st

    out: dict[str, Any] = {}

    # Underwater curve. The shape matters more than the single worst number:
    # a portfolio that spends years recovering is a different proposition from
    # one that snaps back, at identical max drawdown.
    dd = st.to_drawdown_series(returns)
    # Percent, not the fraction openstatz returns. The chart draws its own
    # price axis from these numbers, so a fraction renders the axis as -0.21
    # where a reader expects -21%.
    out["drawdown"] = _curve(dd * 100.0)

    try:
        details = st.drawdown_details(dd)
        if details is not None and len(details) > 0:
            worst = details.sort_values("max drawdown").head(5)
            out["drawdown_episodes"] = [
                {
                    "start": str(row.get("start", ""))[:10],
                    "valley": str(row.get("valley", ""))[:10],
                    "end": str(row.get("end", ""))[:10],
                    "days": int(row.get("days", 0) or 0),
                    "depth": _clean(float(row.get("max drawdown", 0.0)) / 100.0),
                }
                for _, row in worst.iterrows()
            ]
    except Exception:  # noqa: BLE001 — a chart is not worth failing a run over
        logger.debug("drawdown_details unavailable", exc_info=True)

    # Rolling risk, so a flattering full-period Sharpe cannot hide a
    # deteriorating one.
    window = 126 if len(returns) > 200 else max(20, len(returns) // 4)
    if len(returns) > window:
        out["rolling"] = {
            "window": window,
            "sharpe": _curve(st.rolling_sharpe(returns, rf=rf, rolling_period=window).dropna()),
            "volatility": _curve(st.rolling_volatility(returns, rolling_period=window).dropna()),
        }

    # The month-by-month grid, years down and months across.
    try:
        grid = st.monthly_returns(returns)
        out["monthly_returns"] = {
            "years": [str(y) for y in grid.index],
            "columns": [str(c) for c in grid.columns],
            "values": _clean(grid.to_numpy().tolist()),
        }
    except Exception:  # noqa: BLE001
        logger.debug("monthly_returns unavailable", exc_info=True)

    # Return quantiles: the spread of returns at each holding period, which is
    # how openstatz presents this and what QuantStats calls "Return Quantiles".
    #
    # A line of weekly returns is unreadable noise over five years; the point of
    # looking at weekly is the *distribution* -- where the middle half sits and
    # how far the tails reach -- and that only shows in a box plot. Comparing
    # the boxes across periods also answers the question an investor actually
    # has: how long do I have to hold before losing money becomes unusual.
    try:
        buckets = st.distribution(returns, prepare_returns=False)
        quantiles = []
        for period, payload in buckets.items():
            values = pd.Series(payload["values"]).dropna()
            if values.empty:
                continue
            outliers = pd.Series(payload.get("outliers", [])).dropna()
            quantiles.append(
                {
                    "period": period,
                    "count": int(len(values)),
                    "min": _clean(float(values.min())),
                    "q1": _clean(float(values.quantile(0.25))),
                    "median": _clean(float(values.median())),
                    "q3": _clean(float(values.quantile(0.75))),
                    "max": _clean(float(values.max())),
                    "mean": _clean(float(values.mean())),
                    # Share of periods that ended down -- the plain-language
                    # version of the same picture.
                    "negative_share": _clean(float((values < 0).mean())),
                    "outliers": _clean([float(v) for v in outliers.tolist()[:40]]),
                }
            )
        out["return_quantiles"] = quantiles
    except Exception:  # noqa: BLE001
        logger.debug("distribution unavailable", exc_info=True)

    # Weekly returns as a grid: years down, ISO week across, so it reads the
    # same way as the monthly heatmap and a year can be picked out of it.
    #
    # Week numbers come from isocalendar(). openstatz's own aggregate_returns
    # path uses DatetimeIndex.week, which pandas removed in 2.0, so it raises
    # on any current pandas -- the compounding here matches what that path
    # intended, on a boundary that still exists.
    weekly_compounded = returns.resample("W-MON").apply(lambda x: (1.0 + x).prod() - 1.0)
    weekly_compounded = weekly_compounded.dropna()
    if not weekly_compounded.empty:
        iso = weekly_compounded.index.isocalendar()
        frame = pd.DataFrame(
            {
                "year": iso["year"].to_numpy(),
                "week": iso["week"].to_numpy(),
                "value": weekly_compounded.to_numpy(),
            }
        )
        grid = frame.pivot_table(
            index="year", columns="week", values="value", aggfunc="last"
        ).sort_index()
        weeks = [int(w) for w in grid.columns]
        out["weekly_grid"] = {
            "years": [str(y) for y in grid.index],
            "weeks": weeks,
            "values": _clean(grid.to_numpy().tolist()),
        }

    # Weekly series is still returned for anything that wants the raw path.
    from openstatz.utils import aggregate_returns

    # Compounded weekly on the W-MON boundary openstatz itself uses elsewhere.
    #
    # Not aggregate_returns(returns, "W"): that path calls DatetimeIndex.week,
    # which pandas removed in 2.0 in favour of .isocalendar().week, so it
    # raises AttributeError on any current pandas. Yearly below is unaffected --
    # it groups on index.year, which still exists.
    weekly = returns.resample("W-MON").apply(lambda x: (1.0 + x).prod() - 1.0)
    out["weekly_returns"] = _curve(weekly.dropna())

    # Year on year against the benchmark, using openstatz's own comparison so
    # the columns match what its tearsheet calls "EOY Returns vs Benchmark":
    # benchmark, portfolio, the multiplier between them, and whether the year
    # was won.
    #
    # These come back as percentages, unlike monthly_returns and
    # to_drawdown_series which return fractions -- the library is not
    # consistent about it, so the conversion is explicit rather than assumed.
    rows: list[dict[str, Any]] = []
    if benchmark is not None and len(benchmark) > 0:
        joined = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
        if not joined.empty:
            table = st.compare(
                joined.iloc[:, 0], joined.iloc[:, 1], "YE", prepare_returns=False
            )
            for year, row in table.iterrows():
                bench_pct = float(row["Benchmark"])
                port_pct = float(row["Returns"])
                rows.append(
                    {
                        "year": str(year),
                        "benchmark": _clean(bench_pct / 100.0),
                        "portfolio": _clean(port_pct / 100.0),
                        "difference": _clean((port_pct - bench_pct) / 100.0),
                        # Straight from openstatz so the verdict cannot drift
                        # from what its own tearsheet would print.
                        "won": str(row["Won"]).strip() == "+",
                        # Meaningless when the benchmark fell -- a negative
                        # denominator makes the ratio unreadable -- so it is
                        # omitted rather than shown as a confusing number.
                        "multiplier": (
                            _clean(float(row["Multiplier"])) if bench_pct > 0 else None
                        ),
                    }
                )
    else:
        yearly_port = aggregate_returns(returns, "YE").dropna()
        rows = [
            {"year": str(year), "portfolio": _clean(float(value))}
            for year, value in yearly_port.items()
        ]
    out["yearly_returns"] = rows

    return out


def run_portfolio_backtest(
    holdings: list[dict[str, Any]],
    start_date: str,
    end_date: str,
    *,
    benchmark: str | None = None,
    benchmark_exchange: str = "NSE_INDEX",
    rebalance: str = "never",
    drift_band: float = 0.0,
    cost_model: str = "indian_equity",
    brokerage_pct: float = 0.0,
    cost_exchange: str = "NSE",
    charge_overrides: dict[str, dict] | None = None,
    gst_rate: float | None = None,
    walk_window_years: float = 1.0,
    walk_step_years: float = 0.5,
    mc_simulations: int = 1000,
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
        policy_used = RebalancePolicy(rule=rebalance, drift_band=drift_band)
        # The real delivery-equity schedule by default: STT on both legs, stamp
        # duty on the buy only, GST on fees but not on taxes. A flat rate cannot
        # express that asymmetry, so it is offered only for comparison.
        if cost_model == "indian_equity":
            preset = f"india_delivery_{cost_exchange.lower()}"
            schedule = schedule_for(preset, charge_overrides or {})
            # Tax and slippage sit on the schedule rather than on a charge.
            patch: dict = {"slippage": slippage}
            if gst_rate is not None:
                patch["tax_rate"] = gst_rate
            charged: Costs | CostSchedule = dataclasses.replace(schedule, **patch)
        else:
            charged = Costs(bps=cost_bps, slippage=slippage)
        result = run_backtest(
            prices,
            weights,
            policy=policy_used,
            costs=charged,
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
                start_date, end_date,
                # Indices only: you cannot hold one, but it is the right thing
                # to measure a portfolio against.
                allowed_exchanges=BENCHMARK_EXCHANGES,
                **fetch,
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
        "series": _series_analytics(returns, risk_free_rate, bench_returns),
        # Does the result survive doubt? A single window answers "what
        # happened"; these answer whether it would have held on windows the
        # user did not pick, and how much of it was sequence luck.
        "walk_forward": _clean(
            walk_forward(
                prices, weights, policy=policy_used, costs=charged,
                window_years=walk_window_years, step_years=walk_step_years,
            )
        ),
        "monte_carlo": _clean(monte_carlo(returns, simulations=mc_simulations)),
        # What the portfolio is made of. Not a sector pie: the symbol master
        # has no sector field, so co-movement clustering answers the same
        # question from data that exists.
        "structure": _clean(structure(target_weights, holding_returns, _symbol_names(symbols))),
        # The weight path, for the allocation-over-time chart. Sampled weekly:
        # 2,500 sessions x N holdings is a lot of JSON to describe a shape that
        # only changes on rebalance dates and drifts smoothly between them.
        "allocation": _clean(_allocation_path(result.weights)),
        # How it behaved when it mattered. An average return says nothing about
        # the days an investor actually remembers.
        "crisis": _clean(crisis_analysis(returns, bench_returns)),
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
        # What the trading actually cost, itemised the way a contract note is.
        # STT is the dominant line and brokerage is usually zero -- which is why
        # "zero brokerage" does not make rebalancing free.
        "costs": _clean(
            {
                "model": cost_model,
                **(
                    charged.breakdown(
                        buy_value=float(result.turnover.sum()) * initial_capital,
                        sell_value=float(result.turnover.sum()) * initial_capital,
                        orders=int(result.meta.get("orders", 0)),
                    )
                    if isinstance(charged, CostSchedule)
                    else {"total": float(result.turnover.sum()) * initial_capital * charged.total}
                ),
                "schedule": (
                    charged.name if isinstance(charged, CostSchedule) else "flat bps"
                ),
                "drag": result.cost_drag,
                "turnover": float(result.turnover.sum()),
            }
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
