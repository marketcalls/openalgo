#!/usr/bin/env python3
"""Prometheus exporter for local Lean live result files."""

from __future__ import annotations

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def parse_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if not text:
        return 0.0

    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    text = text.replace(",", "").replace("$", "").replace("%", "")
    text = text.replace("USD", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    number = float(match.group(0))
    return -number if negative else number


def prometheus_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class LeanMetrics:
    def __init__(self, launcher_dir: Path, algorithm: str) -> None:
        self.launcher_dir = launcher_dir
        self.algorithm = algorithm

    @property
    def status_path(self) -> Path:
        return self.launcher_dir / f"{self.algorithm}.json"

    @property
    def order_events_path(self) -> Path:
        return self.launcher_dir / f"{self.algorithm}-order-events.json"

    def load_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text())
        except FileNotFoundError:
            return default
        except json.JSONDecodeError:
            return default

    def metric(self, name: str, value: float, labels: dict[str, str] | None = None) -> str:
        labels = labels or {}
        labels.setdefault("algorithm", self.algorithm)
        label_text = ",".join(f'{key}="{prometheus_escape(val)}"' for key, val in sorted(labels.items()))
        return f"{name}{{{label_text}}} {value}"

    def render(self) -> str:
        status = self.load_json(self.status_path, {})
        orders = self.load_json(self.order_events_path, [])
        now = time.time()

        runtime = status.get("runtimeStatistics", {})
        state = status.get("state", {})
        holdings = status.get("holdings", {})
        cash = status.get("cash", {})

        lines = [
            "# HELP lean_exporter_up Lean exporter can read the status file.",
            "# TYPE lean_exporter_up gauge",
            self.metric("lean_exporter_up", 1.0 if status else 0.0),
            "# HELP lean_status_file_age_seconds Seconds since the Lean status file was modified.",
            "# TYPE lean_status_file_age_seconds gauge",
            self.metric(
                "lean_status_file_age_seconds",
                max(0.0, now - self.status_path.stat().st_mtime) if self.status_path.exists() else 0.0,
            ),
            "# HELP lean_algorithm_running 1 when Lean reports status Running.",
            "# TYPE lean_algorithm_running gauge",
            self.metric("lean_algorithm_running", 1.0 if state.get("Status") == "Running" else 0.0),
            "# HELP lean_equity Current strategy equity.",
            "# TYPE lean_equity gauge",
            self.metric("lean_equity", parse_number(runtime.get("Equity"))),
            "# HELP lean_holdings_value Current holdings market value.",
            "# TYPE lean_holdings_value gauge",
            self.metric("lean_holdings_value", parse_number(runtime.get("Holdings"))),
            "# HELP lean_net_profit Current net profit.",
            "# TYPE lean_net_profit gauge",
            self.metric("lean_net_profit", parse_number(runtime.get("Net Profit"))),
            "# HELP lean_unrealized_profit Current unrealized profit.",
            "# TYPE lean_unrealized_profit gauge",
            self.metric("lean_unrealized_profit", parse_number(runtime.get("Unrealized"))),
            "# HELP lean_fees Current fees.",
            "# TYPE lean_fees gauge",
            self.metric("lean_fees", parse_number(runtime.get("Fees"))),
            "# HELP lean_return_percent Current return percent.",
            "# TYPE lean_return_percent gauge",
            self.metric("lean_return_percent", parse_number(runtime.get("Return"))),
            "# HELP lean_volume Current total sale volume.",
            "# TYPE lean_volume gauge",
            self.metric("lean_volume", parse_number(runtime.get("Volume"))),
            "# HELP lean_order_count Current order count from Lean state.",
            "# TYPE lean_order_count gauge",
            self.metric("lean_order_count", parse_number(state.get("OrderCount"))),
            "# HELP lean_log_count Current log count from Lean state.",
            "# TYPE lean_log_count gauge",
            self.metric("lean_log_count", parse_number(state.get("LogCount"))),
        ]

        start_time = state.get("StartTime")
        if start_time:
            try:
                started = time.strptime(start_time.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
                lines.append("# HELP lean_runtime_seconds Seconds since algorithm start.")
                lines.append("# TYPE lean_runtime_seconds gauge")
                lines.append(self.metric("lean_runtime_seconds", max(0.0, now - time.mktime(started))))
            except ValueError:
                pass

        for symbol, holding in holdings.items():
            labels = {"symbol": symbol}
            lines.extend(
                [
                    self.metric("lean_holding_quantity", parse_number(holding.get("q")), labels),
                    self.metric("lean_holding_price", parse_number(holding.get("p")), labels),
                    self.metric("lean_holding_value", parse_number(holding.get("v")), labels),
                    self.metric("lean_holding_unrealized_profit", parse_number(holding.get("u")), labels),
                    self.metric("lean_holding_unrealized_percent", parse_number(holding.get("up")), labels),
                ]
            )

        for currency, data in cash.items():
            lines.append(self.metric("lean_cash_value", parse_number(data.get("valueInAccountCurrency")), {"currency": currency}))

        filled_orders = [order for order in orders if str(order.get("status", "")).lower() == "filled"]
        submitted_orders = [order for order in orders if str(order.get("status", "")).lower() == "submitted"]
        lines.extend(
            [
                self.metric("lean_order_events_total", float(len(orders))),
                self.metric("lean_order_events_filled_total", float(len(filled_orders))),
                self.metric("lean_order_events_submitted_total", float(len(submitted_orders))),
                self.metric("lean_order_fees_total", sum(parse_number(order.get("orderFeeAmount")) for order in filled_orders)),
            ]
        )
        if filled_orders:
            last = max(filled_orders, key=lambda order: parse_number(order.get("time")))
            labels = {
                "symbol": str(last.get("symbolValue") or last.get("symbol") or ""),
                "direction": str(last.get("direction") or ""),
            }
            lines.append(self.metric("lean_last_fill_price", parse_number(last.get("fillPrice")), labels))
            lines.append(self.metric("lean_last_fill_quantity", parse_number(last.get("fillQuantity")), labels))
            lines.append(self.metric("lean_last_fill_time", parse_number(last.get("time")), labels))

        return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Expose local Lean live metrics for Prometheus.")
    parser.add_argument("--launcher-dir", default="/Users/arifkhan/github/Lean/Launcher/bin/Debug")
    parser.add_argument("--algorithm", default="MesSimpleBuySellTestStrategy")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9108)
    args = parser.parse_args()

    metrics = LeanMetrics(Path(args.launcher_dir), args.algorithm)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path not in {"/", "/metrics"}:
                self.send_error(404)
                return
            payload = metrics.render().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Lean metrics exporter listening on http://{args.host}:{args.port}/metrics")
    server.serve_forever()


if __name__ == "__main__":
    main()
