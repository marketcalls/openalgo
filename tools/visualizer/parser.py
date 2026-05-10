#!/usr/bin/env python3
"""Parse Lean backtest artifacts into a normalized run payload."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


STRATEGY_EQUITY_KEY = "Strategy Equity"
EQUITY_KEY = "Equity"


@dataclass(frozen=True)
class LeanArtifacts:
    algorithm_type: str
    launcher_dir: Path
    summary_json: Path | None
    detailed_json: Path | None
    log_txt: Path | None


class ParseError(RuntimeError):
    """Raised when Lean artifacts cannot be parsed."""


def discover_artifacts(launcher_dir: Path, algorithm_type: str) -> LeanArtifacts:
    summary_json = launcher_dir / f"{algorithm_type}-summary.json"
    detailed_json = launcher_dir / f"{algorithm_type}.json"
    log_txt = launcher_dir / f"{algorithm_type}-log.txt"

    return LeanArtifacts(
        algorithm_type=algorithm_type,
        launcher_dir=launcher_dir,
        summary_json=summary_json if summary_json.exists() else None,
        detailed_json=detailed_json if detailed_json.exists() else None,
        log_txt=log_txt if log_txt.exists() else None,
    )


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ParseError(f"Expected JSON object in {path}")
    return data


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (float, int)):
        return float(value)
    text = str(value).strip().replace("$", "").replace(",", "").replace("%", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _extract_equity_points(summary: dict[str, Any]) -> list[dict[str, float | int]]:
    charts = summary.get("charts") if isinstance(summary.get("charts"), dict) else {}
    strategy_equity = charts.get(STRATEGY_EQUITY_KEY) if isinstance(charts.get(STRATEGY_EQUITY_KEY), dict) else {}
    series = strategy_equity.get("series") if isinstance(strategy_equity.get("series"), dict) else {}
    equity = series.get(EQUITY_KEY) if isinstance(series.get(EQUITY_KEY), dict) else {}
    values = equity.get("values") if isinstance(equity.get("values"), list) else []

    points: list[dict[str, float | int]] = []
    for entry in values:
        if not isinstance(entry, list) or len(entry) < 2:
            continue
        timestamp = int(_to_float(entry[0]))
        # Lean can emit either line-series [t, v] points or OHLC [t, o, h, l, c] points.
        value_index = 4 if len(entry) >= 5 else 1
        value = _to_float(entry[value_index])
        points.append({"t": timestamp, "v": value})
    return points


def _extract_equity_candles(summary: dict[str, Any]) -> list[dict[str, float | int]]:
    charts = summary.get("charts") if isinstance(summary.get("charts"), dict) else {}
    strategy_equity = charts.get(STRATEGY_EQUITY_KEY) if isinstance(charts.get(STRATEGY_EQUITY_KEY), dict) else {}
    series = strategy_equity.get("series") if isinstance(strategy_equity.get("series"), dict) else {}
    equity = series.get(EQUITY_KEY) if isinstance(series.get(EQUITY_KEY), dict) else {}
    values = equity.get("values") if isinstance(equity.get("values"), list) else []

    candles: list[dict[str, float | int]] = []
    for entry in values:
        if not isinstance(entry, list) or len(entry) < 2:
            continue

        timestamp = int(_to_float(entry[0]))

        if len(entry) >= 5:
            open_v = _to_float(entry[1])
            high_v = _to_float(entry[2])
            low_v = _to_float(entry[3])
            close_v = _to_float(entry[4])
        else:
            close_v = _to_float(entry[1])
            open_v = close_v
            high_v = close_v
            low_v = close_v

        candles.append({"t": timestamp, "o": open_v, "h": high_v, "l": low_v, "c": close_v})

    return candles


def _compute_drawdown_series(equity_points: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
    peak = 0.0
    drawdown: list[dict[str, float | int]] = []

    for point in equity_points:
        value = _to_float(point.get("v"), default=0.0)
        if value > peak:
            peak = value
        dd = 0.0
        if peak > 0:
            dd = ((value - peak) / peak) * 100.0
        drawdown.append({"t": int(point["t"]), "v": dd})

    return drawdown


def _extract_trades(detailed: dict[str, Any]) -> list[dict[str, Any]]:
    performance = detailed.get("totalPerformance") if isinstance(detailed.get("totalPerformance"), dict) else {}
    closed_trades = performance.get("closedTrades") if isinstance(performance.get("closedTrades"), list) else []

    trades: list[dict[str, Any]] = []
    for trade in closed_trades:
        if not isinstance(trade, dict):
            continue
        trades.append(
            {
                "symbol": str(trade.get("symbol", "")),
                "direction": str(trade.get("direction", "")),
                "quantity": _to_float(trade.get("quantity")),
                "entryPrice": _to_float(trade.get("entryPrice")),
                "exitPrice": _to_float(trade.get("exitPrice")),
                "profitLoss": _to_float(trade.get("profitLoss")),
                "startDateTime": str(trade.get("startDateTime", "")),
                "endDateTime": str(trade.get("endDateTime", "")),
            }
        )

    return trades


def _direction_to_text(value: Any) -> str:
    mapping = {
        0: "Buy",
        1: "Sell",
        2: "Hold",
    }
    if isinstance(value, int):
        return mapping.get(value, str(value))
    text = str(value or "").strip()
    return text or "Unknown"


def _extract_iso_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    if "T" in text:
        return text.split("T", 1)[0]

    return text[:10] if len(text) >= 10 else text


def extract_orders_from_detailed(detailed: dict[str, Any]) -> list[dict[str, Any]]:
    orders_obj = detailed.get("orders") if isinstance(detailed.get("orders"), dict) else {}

    orders: list[dict[str, Any]] = []
    for raw_order in orders_obj.values():
        if not isinstance(raw_order, dict):
            continue

        symbol_obj = raw_order.get("symbol") if isinstance(raw_order.get("symbol"), dict) else {}
        symbol = str(symbol_obj.get("value") or raw_order.get("symbol") or "")

        timestamp = str(
            raw_order.get("lastFillTime")
            or raw_order.get("time")
            or raw_order.get("createdTime")
            or ""
        )

        orders.append(
            {
                "id": int(_to_float(raw_order.get("id"), default=0.0)),
                "symbol": symbol,
                "symbolId": str(symbol_obj.get("id", "")),
                "direction": _direction_to_text(raw_order.get("direction")),
                "quantity": _to_float(raw_order.get("quantity")),
                "price": _to_float(raw_order.get("price")),
                "value": _to_float(raw_order.get("value")),
                "time": timestamp,
                "status": str(raw_order.get("status", "")),
                "tag": str(raw_order.get("tag", "")),
            }
        )

    orders.sort(key=lambda item: str(item.get("time", "")))
    return orders


def _extract_date_range(
    summary: dict[str, Any],
    detailed: dict[str, Any],
    equity_points: list[dict[str, float | int]],
) -> dict[str, str]:
    configuration = summary.get("algorithmConfiguration") if isinstance(summary.get("algorithmConfiguration"), dict) else {}
    performance = detailed.get("totalPerformance") if isinstance(detailed.get("totalPerformance"), dict) else {}
    trade_statistics = (
        performance.get("tradeStatistics") if isinstance(performance.get("tradeStatistics"), dict) else {}
    )

    start_date = str(configuration.get("startDate", "")).strip()
    end_date = str(configuration.get("endDate", "")).strip()

    trade_start_date = _extract_iso_date(trade_statistics.get("startDateTime"))
    trade_end_date = _extract_iso_date(trade_statistics.get("endDateTime"))

    if trade_start_date:
        start_date = trade_start_date
    if trade_end_date:
        end_date = trade_end_date

    if not start_date and equity_points:
        start_date = datetime.fromtimestamp(int(equity_points[0]["t"]), tz=UTC).date().isoformat()
    if not end_date and equity_points:
        end_date = datetime.fromtimestamp(int(equity_points[-1]["t"]), tz=UTC).date().isoformat()

    return {
        "start": start_date,
        "end": end_date,
    }


def parse_lean_results(launcher_dir: Path, algorithm_type: str) -> tuple[dict[str, Any], LeanArtifacts]:
    artifacts = discover_artifacts(launcher_dir=launcher_dir, algorithm_type=algorithm_type)
    summary = _load_json(artifacts.summary_json)
    detailed = _load_json(artifacts.detailed_json)

    if not summary and not detailed:
        raise ParseError(
            "No Lean result JSON files were found. "
            f"Expected {algorithm_type}-summary.json or {algorithm_type}.json in {launcher_dir}"
        )

    statistics = summary.get("statistics") if isinstance(summary.get("statistics"), dict) else {}
    runtime_statistics = (
        summary.get("runtimeStatistics") if isinstance(summary.get("runtimeStatistics"), dict) else {}
    )
    state = summary.get("state") if isinstance(summary.get("state"), dict) else {}

    equity_points = _extract_equity_points(summary)
    equity_candles = _extract_equity_candles(summary)
    drawdown_points = _compute_drawdown_series(equity_points)
    trades = _extract_trades(detailed)
    orders = extract_orders_from_detailed(detailed)
    date_range = _extract_date_range(summary, detailed, equity_points)

    payload: dict[str, Any] = {
        "algorithmType": algorithm_type,
        "status": str(state.get("Status", "Unknown")),
        "startedAt": str(state.get("StartTime", "")),
        "finishedAt": str(state.get("EndTime", "")),
        "dateRange": date_range,
        "summary": {
            "startEquity": _to_float(statistics.get("Start Equity")),
            "endEquity": _to_float(statistics.get("End Equity")),
            "netProfitPct": _to_float(statistics.get("Net Profit")),
            "drawdownPct": _to_float(statistics.get("Drawdown")),
            "sharpeRatio": _to_float(statistics.get("Sharpe Ratio")),
            "sortinoRatio": _to_float(statistics.get("Sortino Ratio")),
            "totalOrders": int(_to_float(statistics.get("Total Orders"))),
            "totalFees": _to_float(statistics.get("Total Fees")),
            "runtimeReturn": str(runtime_statistics.get("Return", "")),
        },
        "equity": equity_points,
        "equityCandles": equity_candles,
        "drawdown": drawdown_points,
        "trades": trades,
        "orders": orders,
        "raw": {
            "statistics": statistics,
            "runtimeStatistics": runtime_statistics,
            "state": state,
        },
    }

    return payload, artifacts
