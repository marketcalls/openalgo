"""SIP backtesting service.

Follows the standard service contract in ``docs/prompt/services_documentation.md``:
every entry point returns ``(success, response, status_code)``, where response
carries ``status`` plus either data or an error ``message``. Conversion to a
Flask response happens at the resource boundary, not here.

Price loading is delegated to ``portfolio.data.load_prices``, which already
handles both sources -- Historify (``source='db'``) and the broker history API
(``source='api'``) -- for NSE and BSE, with caching and clear errors when a
symbol has no usable history. Duplicating that here would mean two behaviours
for the same question.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from typing import Any

from portfolio.costs import CostSchedule, schedule_for
from portfolio.data import (
    BENCHMARK_EXCHANGES,
    SUPPORTED_EXCHANGES,
    DataError,
    load_prices,
)
from portfolio.engine import Costs
from sip.analytics import (
    drawdown,
    frequency_comparison,
    headline,
    lumpsum_comparison,
    monthly_value_heatmap,
    rolling_xirr,
    sip_date_heatmap,
    start_date_heatmap,
    underwater,
    yearly_breakdown,
)
from sip.crisis import crisis_sip_analysis, crisis_summary
from sip.engine import SipError, run_sip
from sip.schedule import FREQUENCIES, ScheduleError
from sip.xirr import xirr_or_none
from utils.logging import get_logger

logger = get_logger(__name__)

MAX_SIP_YEARS = 30


def _error(message: str, status: int = 400) -> tuple[bool, dict[str, Any], int]:
    return False, {"status": "error", "message": message}, status


def _parse_date(value: str, field: str) -> date:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be YYYY-MM-DD, got {value!r}") from exc


def _build_costs(
    *,
    cost_model: str,
    brokerage_percent: float,
    brokerage_flat: float,
    cost_exchange: str,
    charge_overrides: dict[str, dict] | None,
    gst_rate: float | None,
    cost_bps: float,
    slippage: float,
) -> Costs | CostSchedule:
    """Build the cost model for a SIP.

    Mirrors ``portfolio_service._build_costs`` deliberately: a SIP installment
    and a portfolio buy of the same size must report the same charges, or the
    two tools would disagree about the same trade.
    """
    if cost_model == "flat_bps":
        return Costs(bps=cost_bps, slippage=slippage)

    overrides = {k: dict(v) for k, v in (charge_overrides or {}).items()}
    # A brokerage typed into the simple fields wins over the preset, so the
    # basic inputs still work without opening the full charge panel.
    if (brokerage_percent or brokerage_flat) and "brokerage" not in overrides:
        overrides["brokerage"] = {
            "flat": brokerage_flat,
            "rate": brokerage_percent / 100.0,
            "cap": 20.0,
        }
    schedule = schedule_for(f"india_delivery_{cost_exchange.lower()}", overrides)
    patch: dict[str, float] = {"slippage": slippage}
    if gst_rate is not None:
        patch["tax_rate"] = gst_rate
    return dataclasses.replace(schedule, **patch)


def list_frequencies() -> tuple[bool, dict[str, Any], int]:
    """SIP frequencies the engine supports, for populating a dropdown."""
    labels = {
        "weekly": "Weekly",
        "fortnightly": "Fortnightly",
        "monthly": "Monthly",
        "quarterly": "Quarterly",
    }
    return True, {
        "status": "success",
        "data": [{"value": f, "label": labels.get(f, f.title())} for f in FREQUENCIES],
    }, 200


def run_sip_backtest(
    symbol: str,
    exchange: str,
    start_date: str,
    end_date: str,
    amount: float,
    *,
    frequency: str = "monthly",
    day_of_month: int = 1,
    step_up_percent: float = 0.0,
    brokerage_percent: float = 0.0,
    brokerage_flat: float = 0.0,
    cost_model: str = "indian_equity",
    cost_exchange: str = "NSE",
    charge_overrides: dict[str, dict] | None = None,
    gst_rate: float | None = None,
    cost_bps: float = 0.0,
    slippage: float = 0.0,
    benchmark: str | None = None,
    benchmark_exchange: str = "NSE_INDEX",
    source: str = "db",
    api_key: str | None = None,
    auth_token: str | None = None,
    feed_token: str | None = None,
    broker: str | None = None,
    include_grids: bool = True,
) -> tuple[bool, dict[str, Any], int]:
    """Backtest a SIP into one symbol and return every metric the UI needs.

    Args:
        symbol, exchange: an equity symbol on NSE or BSE, in OpenAlgo format
            (the base symbol -- ``INFY``, ``SBIN``, ``TATAMOTORS``).
        start_date, end_date: ``YYYY-MM-DD``. ``start_date`` is the date the
            SIP begins; the first installment lands on or after it.
        amount: the installment before any step-up.
        frequency: weekly, fortnightly, monthly or quarterly.
        day_of_month: target day for monthly and quarterly SIPs, 1-28.
        step_up_percent: annual increase applied on each anniversary.
        brokerage_percent, brokerage_flat: charged per installment.
        benchmark, benchmark_exchange: an index to run the *same schedule*
            against, so the comparison is SIP-to-SIP rather than SIP-to-index.
        source: ``'db'`` for Historify, ``'api'`` for the broker history API.
        include_grids: heatmaps and rolling windows re-run the simulation many
            times; skip them for a fast summary.

    Returns:
        ``(success, response, status_code)``.
    """
    try:
        start = _parse_date(start_date, "start_date")
        end = _parse_date(end_date, "end_date")
    except ValueError as exc:
        return _error(str(exc))

    if end <= start:
        return _error("end_date must be after start_date")
    if (end - start).days > MAX_SIP_YEARS * 366:
        return _error(f"SIP window cannot exceed {MAX_SIP_YEARS} years")
    if amount is None or float(amount) <= 0:
        return _error("amount must be a positive number")
    if frequency not in FREQUENCIES:
        return _error(f"frequency must be one of {', '.join(FREQUENCIES)}")
    exchange = (exchange or "NSE").upper()
    if exchange not in SUPPORTED_EXCHANGES:
        return _error(
            f"exchange must be one of {', '.join(SUPPORTED_EXCHANGES)} for a SIP"
        )
    if benchmark and benchmark_exchange.upper() not in BENCHMARK_EXCHANGES:
        return _error(
            f"benchmark_exchange must be one of {', '.join(BENCHMARK_EXCHANGES)}"
        )

    creds = {
        "api_key": api_key,
        "auth_token": auth_token,
        "feed_token": feed_token,
        "broker": broker,
    }

    try:
        matrix = load_prices(
            [symbol], [exchange], str(start), str(end), source=source, **creds
        )
    except DataError as exc:
        return _error(str(exc), 422)
    except Exception as exc:  # noqa: BLE001 - surface the reason, not a 500
        logger.exception(f"SIP price load failed for {symbol}: {exc}")
        return _error(f"could not load prices for {symbol}: {exc}", 502)

    closes = matrix.closes[matrix.closes.columns[0]]
    warnings = list(matrix.warnings.get(symbol, []))

    try:
        costs = _build_costs(
            cost_model=cost_model,
            brokerage_percent=brokerage_percent,
            brokerage_flat=brokerage_flat,
            cost_exchange=cost_exchange,
            charge_overrides=charge_overrides,
            gst_rate=gst_rate,
            cost_bps=cost_bps,
            slippage=slippage,
        )
    except ValueError as exc:
        return _error(str(exc))

    sip_kw = {
        "frequency": frequency,
        "day_of_month": day_of_month,
        "step_up_percent": step_up_percent,
        "costs": costs,
    }

    try:
        result = run_sip(
            closes, symbol, exchange, start, end, float(amount),
            warnings=[str(w) for w in warnings], **sip_kw,
        )
    except (SipError, ScheduleError) as exc:
        return _error(str(exc), 422)

    payload: dict[str, Any] = {
        "status": "success",
        "request": {
            "symbol": symbol,
            "exchange": exchange,
            "start_date": str(start),
            "end_date": str(end),
            "amount": float(amount),
            "frequency": frequency,
            "day_of_month": day_of_month,
            "step_up_percent": step_up_percent,
            "source": matrix.source,
        },
        "headline": headline(result),
        "underwater": underwater(result),
        "drawdown": drawdown(result),
        "yearly": yearly_breakdown(result),
        "monthly_heatmap": monthly_value_heatmap(result),
        "lumpsum": lumpsum_comparison(closes, result, start, end, costs=costs),
        "charges": {
            "total": round(result.charges, 2),
            "per_installment": round(
                result.charges / max(result.installment_count, 1), 2
            ),
            # Share of everything paid in that went to charges rather than units.
            "drag": round(result.charges / result.total_invested, 6)
            if result.total_invested
            else None,
            "breakdown": result.charge_breakdown,
            "model": cost_model,
            "exchange": cost_exchange,
        },
        "frequency_comparison": frequency_comparison(
            closes, start, end, float(amount),
            **{k: v for k, v in sip_kw.items() if k != "frequency"},
        ),
        "curves": {
            "value": [
                {"date": str(d.date()), "value": round(float(v), 2)}
                for d, v in result.value.items()
            ],
            "invested": [
                {"date": str(d.date()), "value": round(float(v), 2)}
                for d, v in result.invested.items()
            ],
        },
        "installments": [
            {
                "requested": str(i.requested),
                "executed": str(i.executed),
                "amount": round(i.amount, 2),
            }
            for i in result.installments
        ],
        "warnings": result.warnings,
    }

    if include_grids:
        payload["rolling_xirr"] = rolling_xirr(closes, float(amount), **sip_kw)
        payload["start_date_heatmap"] = start_date_heatmap(
            closes, float(amount), **sip_kw
        )
        crisis_rows = crisis_sip_analysis(closes, float(amount), sip_kw=sip_kw)
        payload["crisis"] = {
            "summary": crisis_summary(crisis_rows),
            "periods": crisis_rows,
        }
        payload["sip_date_heatmap"] = (
            sip_date_heatmap(closes, start, end, float(amount), **sip_kw)
            if frequency in ("monthly", "quarterly")
            else None
        )

    if benchmark:
        payload["benchmark"] = _benchmark_sip(
            benchmark, benchmark_exchange.upper(), start, end, float(amount),
            result, source, creds, sip_kw,
        )

    return True, payload, 200


def _benchmark_sip(
    symbol: str,
    exchange: str,
    start: date,
    end: date,
    amount: float,
    result,
    source: str,
    creds: dict,
    sip_kw: dict,
) -> dict[str, Any]:
    """Run the identical SIP schedule into an index.

    Comparing a SIP against an index's CAGR would be comparing two different
    things. The only fair benchmark is the same money, on the same dates, into
    the index -- so this reruns the whole simulation rather than annualising a
    price series.
    """
    try:
        matrix = load_prices(
            [symbol], [exchange], str(start), str(end), source=source,
            allowed_exchanges=BENCHMARK_EXCHANGES, **creds,
        )
        closes = matrix.closes[matrix.closes.columns[0]]
        bench = run_sip(closes, symbol, exchange, start, end, amount, **sip_kw)
    except Exception as exc:  # noqa: BLE001 - a missing benchmark is not fatal
        logger.warning(f"benchmark SIP failed for {symbol}: {exc}")
        return {"symbol": symbol, "exchange": exchange, "error": str(exc)}

    bench_xirr = xirr_or_none(bench.cash_flows)
    self_xirr = xirr_or_none(result.cash_flows)

    return {
        "symbol": symbol,
        "exchange": exchange,
        "headline": headline(bench),
        "xirr": bench_xirr,
        "excess_xirr": (self_xirr - bench_xirr)
        if (self_xirr is not None and bench_xirr is not None) else None,
        "beat_benchmark": bool(
            self_xirr is not None and bench_xirr is not None and self_xirr > bench_xirr
        ),
        "curve": [
            {"date": str(d.date()), "value": round(float(v), 2)}
            for d, v in bench.value.items()
        ],
    }
