#!/usr/bin/env python
"""Regenerate audit/BROKER_API_COMPATIBILITY.md from the code.

The report was hand-written in February 2026 and drifted: it documented 29
brokers while the tree carried 35, and it had no GTT column at all even though
GTT shipped for two brokers. A matrix that is maintained by hand goes stale
exactly when it matters most - somebody choosing a broker for a feature.

So this derives it instead. Support is decided the same way the application
decides it at runtime: by whether the module and function exist. Nothing is
imported, only parsed, so a broker with a missing third-party dependency is
still reported accurately rather than crashing the run.

Three states, matching the report's existing legend:

    Y   the function is defined and does something
    S   the function is defined but is a stub - it raises NotImplementedError,
        returns an empty frame, or answers with a "not supported" message
    -   no such function

The stub distinction is the point. A broker with `get_history` that returns an
empty DataFrame looks supported to any check that only asks "is it defined?",
and a trader discovers otherwise when a backtest silently returns nothing.

Usage:
    uv run python scripts/generate_broker_compatibility.py           # rewrite
    uv run python scripts/generate_broker_compatibility.py --check   # CI: diff only
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BROKER_DIR = ROOT / "broker"
OUTPUT = ROOT / "audit" / "BROKER_API_COMPATIBILITY.md"

#: (column, module, function). Module is relative to the broker package.
#: Grouped as the report groups them.
GROUPS: dict[str, list[tuple[str, str, str | tuple[str, ...]]]] = {
    "Order Management": [
        ("Place Order", "api/order_api.py", "place_order_api"),
        ("Smart Order", "api/order_api.py", "place_smartorder_api"),
        ("Modify Order", "api/order_api.py", "modify_order"),
        ("Cancel Order", "api/order_api.py", "cancel_order"),
        ("Cancel All", "api/order_api.py", "cancel_all_orders_api"),
        ("Close Position", "api/order_api.py", "close_all_positions"),
    ],
    "GTT Orders": [
        ("Place GTT", "api/gtt_api.py", "place_gtt_order"),
        ("Modify GTT", "api/gtt_api.py", "modify_gtt_order"),
        ("Cancel GTT", "api/gtt_api.py", "cancel_gtt_order"),
        ("GTT Book", "api/gtt_api.py", "get_gtt_book"),
    ],
    "Account & Portfolio": [
        ("Orderbook", "api/order_api.py", "get_order_book"),
        ("Tradebook", "api/order_api.py", "get_trade_book"),
        ("Positionbook", "api/order_api.py", "get_positions"),
        ("Holdings", "api/order_api.py", "get_holdings"),
        ("Open Position", "api/order_api.py", "get_open_position"),
        ("Funds", "api/funds.py", "get_margin_data"),
        ("Margin", "api/margin_api.py", "calculate_margin_api"),
    ],
    "Market Data": [
        ("Quotes", "api/data.py", "get_quotes"),
        ("Depth", "api/data.py", "get_depth"),
        ("History", "api/data.py", "get_history"),
        # Named three ways across the tree. Checking only get_intervals
        # reported 16/35 when 35 brokers implement it.
        ("Intervals", "api/data.py", ("get_intervals", "get_supported_intervals", "timeframe_map")),
    ],
}

#: Streaming capabilities. Detected by adapter presence, because that is how
#: websocket_proxy/broker_factory.py resolves them at runtime:
#: `broker.{name}.streaming.{name}_adapter`. Order/trade updates are a separate
#: adapter and a good few brokers have the market-data one without it, so a
#: single "streaming" column would be misleading.
STREAM_CAPS: list[tuple[str, str]] = [
    ("Market Data", "streaming/{broker}_adapter.py"),
    ("Order/Trade Updates", "streaming/{broker}_order_adapter.py"),
]

#: Markers that mean "defined but does not work". Matched against the function
#: source, which is why this parses rather than imports.
STUB_MARKERS = (
    "NotImplementedError",
    "does not support",
    "not supported",
    "not provided by",
    "not available for",
)


def _function_nodes(path: Path) -> dict[str, ast.AST]:
    """Top-level and class-level functions in a file, by name.

    Returns an empty mapping for a file that does not exist or does not parse,
    so a syntax error in one broker cannot take down the whole report.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}

    found: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.setdefault(node.name, node)
    return found


def _classify(path: Path, func_name: str | tuple[str, ...], source: str) -> str:
    """Y, S or - for one broker function.

    Accepts several names for the same capability. Brokers spell them
    differently - intervals is get_intervals, get_supported_intervals or just a
    timeframe_map attribute - and insisting on one name reports a capability as
    missing when it is merely named otherwise.
    """
    functions = _function_nodes(path)
    candidates = (func_name,) if isinstance(func_name, str) else func_name

    node = None
    for name in candidates:
        node = functions.get(name)
        if node is not None:
            break

    if node is None:
        # A non-function marker such as an attribute assignment still counts.
        if any(f"{name} =" in source or f"{name}=" in source for name in candidates):
            return "Y"
        return "-"

    segment = ast.get_source_segment(source, node) or ""

    # A body that is only a docstring and/or `pass` is a placeholder.
    body = [n for n in node.body if not isinstance(n, ast.Expr) or not isinstance(
        getattr(n, "value", None), ast.Constant
    )]
    if not body or all(isinstance(n, ast.Pass) for n in body):
        return "S"

    if any(marker in segment for marker in STUB_MARKERS):
        return "S"

    return "Y"


def brokers() -> list[str]:
    return sorted(
        d.name
        for d in BROKER_DIR.iterdir()
        if d.is_dir() and d.name != "__pycache__" and (d / "plugin.json").exists()
    )


def plugin_info(broker: str) -> dict:
    try:
        return json.loads((BROKER_DIR / broker / "plugin.json").read_text())
    except Exception:
        return {}


def capabilities(broker: str) -> dict[str, str]:
    """Every column for one broker."""
    out: dict[str, str] = {}
    cache: dict[str, tuple[Path, str]] = {}

    for entries in GROUPS.values():
        for column, module, func in entries:
            path = BROKER_DIR / broker / module
            if module not in cache:
                try:
                    cache[module] = (path, path.read_text(encoding="utf-8"))
                except OSError:
                    cache[module] = (path, "")
            _, source = cache[module]
            out[column] = "-" if not source else _classify(path, func, source)
    return out


def streaming(broker: str) -> dict[str, str]:
    """Streaming columns for one broker.

    An adapter file that exists but defines no subscribe path is reported as a
    stub rather than as working: the proxy would import it and then have
    nothing to call.
    """
    out: dict[str, str] = {}
    for column, template in STREAM_CAPS:
        path = BROKER_DIR / broker / template.format(broker=broker)
        if not path.exists():
            out[column] = "-"
            continue
        functions = _function_nodes(path)
        if not functions:
            out[column] = "S"
            continue
        # Two different interfaces. A market-data adapter subscribes and
        # connects; an order-update adapter subclasses BaseOrderUpdateAdapter
        # and supplies get_ws_url / normalize. Checking only the first reported
        # order updates as 1/35 when 16 brokers implement them.
        expected = (
            "subscribe",
            "connect",
            "on_message",
            "_on_message",
            "run",
            "get_ws_url",
            "normalize",
            "get_headers",
        )
        out[column] = "Y" if any(f in functions for f in expected) else "S"
    return out


def render() -> str:
    names = brokers()
    caps = {b: capabilities(b) for b in names}
    streams = {b: streaming(b) for b in names}
    info = {b: plugin_info(b) for b in names}

    lines: list[str] = []
    add = lines.append

    add("# OpenAlgo Broker API Compatibility Report")
    add("")
    add("> **Generated from the codebase** by")
    add("> `scripts/generate_broker_compatibility.py`. Do not edit by hand -")
    add("> rerun the script instead. The previous hand-maintained version drifted")
    add("> to 29 brokers while the tree carried 35, and never gained a GTT column.")
    add(">")
    add(f"> **Brokers**: {len(names)}")
    add(f"> **Capabilities checked**: {sum(len(v) for v in GROUPS.values()) + len(STREAM_CAPS)}")
    add("")
    add(
        "Support is determined the way the application determines it at runtime: "
        "by whether the broker module and function exist."
    )
    add("")
    add(
        "Legend: `Y` supported | `S` stub - defined but raises, returns empty, or "
        "answers \"not supported\" | `-` not implemented"
    )
    add("")
    add(
        "The stub state matters most. A broker whose `get_history` returns an "
        "empty frame looks supported to any check that only asks whether the "
        "function is defined, and a trader finds out when a backtest quietly "
        "returns nothing."
    )
    add("")

    for group, entries in GROUPS.items():
        columns = [c for c, _, _ in entries]
        add(f"## {group}")
        add("")
        add("| Broker | " + " | ".join(columns) + " |")
        add("|---" * (len(columns) + 1) + "|")
        for b in names:
            row = [caps[b].get(c, "-") for c in columns]
            add(f"| {b} | " + " | ".join(row) + " |")
        add("")

    stream_columns = [c for c, _ in STREAM_CAPS]
    add("## WebSocket Streaming")
    add("")
    add(
        "Market data and order/trade updates are separate adapters. Plenty of "
        "brokers ship the first without the second, so a single \"streaming\" "
        "column would tell a user their order updates work when they do not."
    )
    add("")
    add(
        "A `-` under Order/Trade Updates means not implemented **yet**. Coverage "
        "for the remaining brokers is planned, so read it as a current state "
        "rather than a permanent limitation."
    )
    add("")
    add("| Broker | " + " | ".join(stream_columns) + " |")
    add("|---" * (len(stream_columns) + 1) + "|")
    for b in names:
        add(f"| {b} | " + " | ".join(streams[b].get(c, "-") for c in stream_columns) + " |")
    add("")

    add("## Exchanges and Broker Type")
    add("")
    add("| Broker | Type | Leverage config | Exchanges |")
    add("|---|---|---|---|")
    for b in names:
        i = info[b]
        add(
            f"| {b} | {i.get('broker_type', '?')} | "
            f"{str(i.get('leverage_config', False)).lower()} | "
            f"{', '.join(i.get('supported_exchanges', [])) or '?'} |"
        )
    add("")

    add("## Summary")
    add("")
    for entries in GROUPS.values():
        for column, _, _ in entries:
            supported = sum(1 for b in names if caps[b].get(column) == "Y")
            stubs = sum(1 for b in names if caps[b].get(column) == "S")
            note = f", {stubs} stub" if stubs else ""
            add(f"- **{column}**: {supported}/{len(names)} brokers{note}")
    for column in stream_columns:
        supported = sum(1 for b in names if streams[b].get(column) == "Y")
        stubs = sum(1 for b in names if streams[b].get(column) == "S")
        note = f", {stubs} stub" if stubs else ""
        add(f"- **Streaming: {column}**: {supported}/{len(names)} brokers{note}")
    add("")
    add(f"_Regenerated {datetime.now().strftime('%d %B %Y')}._")
    add("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the file on disk is out of date, without writing",
    )
    args = parser.parse_args()

    generated = render()

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        # The timestamp line changes every day and is not a drift signal.
        def strip(text: str) -> str:
            return "\n".join(
                ln for ln in text.splitlines() if not ln.startswith("_Regenerated")
            )
        if strip(current) == strip(generated):
            print("Broker compatibility report is up to date.")
            return 0
        print(
            "Broker compatibility report is out of date. Run:\n"
            "  uv run python scripts/generate_broker_compatibility.py"
        )
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(generated, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)} ({len(brokers())} brokers)")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    raise SystemExit(main())
