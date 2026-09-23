#!/usr/bin/env python3
"""Check a running OpenAlgo against your broker after switching web servers.

Run it on the server (or anywhere that can reach it) with your OpenAlgo API
key, after you switch to gthread or back. It calls the read-only parts of the
REST API that talk to your broker, several times and optionally in parallel,
and prints a table of what passed and how long each call took:

    funds, positionbook, orderbook, tradebook, holdings, quotes,
    multiquotes, depth, history, intervals

It never places a live order. The optional ``--order-check`` places one small
LIMIT buy far below the market and cancels it at once, and only when the
instance reports analyzer (sandbox) mode, checked just before the order; in
live mode it refuses and says so. The price is half the last traded price, so
even an order that somehow reached a live book would not fill.

Usage:
    uv run python scripts/gthread_broker_smoke.py --url http://127.0.0.1:5000 \\
        [--symbol SBIN --exchange NSE] [--repeat 3] [--parallel 4] [--order-check]

The API key is asked for when it is not given with --apikey, so it does not
land in your shell history. It is never printed.

Exit status 0 when every call passed, 1 when any failed, 2 when the order
check was refused.
"""

from __future__ import annotations

import argparse
import getpass
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

REFUSED = 2


class Client:
    """POSTs JSON to /api/v1 with the API key in the body."""

    def __init__(self, url: str, apikey: str, timeout: float = 30.0):
        self.base = url.rstrip("/") + "/api/v1"
        self.apikey = apikey
        self.timeout = timeout

    def call(self, endpoint: str, payload: dict | None = None) -> tuple[bool, float, dict, str]:
        """Return (ok, milliseconds, body, detail). Never raises."""
        body = {"apikey": self.apikey, **(payload or {})}
        request = urllib.request.Request(
            f"{self.base}/{endpoint}",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            raw = error.read()
            status = error.code
        except (urllib.error.URLError, OSError) as error:
            elapsed = (time.monotonic() - started) * 1000
            return False, elapsed, {}, f"could not reach OpenAlgo ({error})"
        elapsed = (time.monotonic() - started) * 1000
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False, elapsed, {}, f"answered {status} with a non-JSON body"
        ok = status == 200 and data.get("status") == "success"
        detail = "" if ok else str(data.get("message") or f"answered {status}")
        return ok, elapsed, data, detail


def read_only_calls(symbol: str, exchange: str, second: str | None) -> list[tuple[str, str, dict]]:
    """(label, endpoint, payload) for every read-only check, in table order."""
    today = date.today()
    symbols = [{"symbol": symbol, "exchange": exchange}]
    if second:
        symbols.append({"symbol": second, "exchange": exchange})
    return [
        ("funds", "funds", {}),
        ("positionbook", "positionbook", {}),
        ("orderbook", "orderbook", {}),
        ("tradebook", "tradebook", {}),
        ("holdings", "holdings", {}),
        ("quotes", "quotes", {"symbol": symbol, "exchange": exchange}),
        ("multiquotes", "multiquotes", {"symbols": symbols}),
        ("depth", "depth", {"symbol": symbol, "exchange": exchange}),
        (
            "history",
            "history",
            {
                "symbol": symbol,
                "exchange": exchange,
                "interval": "D",
                "start_date": (today - timedelta(days=10)).isoformat(),
                "end_date": today.isoformat(),
            },
        ),
        ("intervals", "intervals", {}),
    ]


def run_read_only(client: Client, calls, repeat: int, parallel: int) -> list[dict]:
    """Run every call ``repeat`` times, ``parallel`` at a time. One row per call."""
    jobs = [(label, endpoint, payload) for _ in range(repeat) for label, endpoint, payload in calls]
    results: dict[str, list] = {label: [] for label, _endpoint, _payload in calls}
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        futures = [
            (label, pool.submit(client.call, endpoint, payload))
            for label, endpoint, payload in jobs
        ]
        for label, future in futures:
            results[label].append(future.result())
    rows = []
    for label, outcomes in results.items():
        times = [elapsed for _ok, elapsed, _data, _detail in outcomes]
        failures = [detail for ok, _elapsed, _data, detail in outcomes if not ok]
        rows.append(
            {
                "check": label,
                "ok": not failures,
                "runs": len(outcomes),
                "median_ms": statistics.median(times),
                "max_ms": max(times),
                "detail": failures[0] if failures else "",
            }
        )
    return rows


def in_analyzer_mode(client: Client) -> tuple[bool, str]:
    """True only when the instance says it routes orders to the sandbox."""
    ok, _elapsed, data, detail = client.call("analyzer")
    if not ok:
        return False, detail or "the analyzer status could not be read"
    info = data.get("data") or {}
    if info.get("mode") == "analyze" and info.get("analyze_mode") is True:
        return True, ""
    return False, "OpenAlgo is in live mode"


def order_check(client: Client, symbol: str, exchange: str) -> tuple[list[dict], int]:
    """Place and cancel one far-from-market LIMIT order, in analyzer mode only."""
    rows: list[dict] = []

    def row(check, ok, elapsed, detail):
        rows.append(
            {
                "check": check,
                "ok": ok,
                "runs": 1,
                "median_ms": elapsed,
                "max_ms": elapsed,
                "detail": detail,
            }
        )

    sandbox, reason = in_analyzer_mode(client)
    if not sandbox:
        row("order check", False, 0.0, f"refused: {reason}. It only runs in analyzer mode.")
        return rows, REFUSED

    ok, elapsed, data, detail = client.call("quotes", {"symbol": symbol, "exchange": exchange})
    ltp = (data.get("data") or {}).get("ltp") if ok else None
    if not ltp or float(ltp) <= 0:
        row("order check", False, elapsed, f"refused: no last traded price for {symbol} ({detail})")
        return rows, REFUSED
    price = round(float(ltp) * 0.5, 1)

    # Asked again right before the order: a switch to live in between must win.
    sandbox, reason = in_analyzer_mode(client)
    if not sandbox:
        row("order check", False, 0.0, f"refused: {reason}. It only runs in analyzer mode.")
        return rows, REFUSED

    ok, elapsed, data, detail = client.call(
        "placeorder",
        {
            "strategy": "gthread-smoke",
            "symbol": symbol,
            "exchange": exchange,
            "action": "BUY",
            "quantity": 1,
            "pricetype": "LIMIT",
            "product": "MIS",
            "price": price,
        },
    )
    orderid = data.get("orderid")
    went_live = data.get("mode") not in (None, "analyze")
    if went_live:
        # Analyzer mode was switched off in the moment between the check and
        # the order. Cancel it straight away and say so plainly.
        row(
            "placeorder (sandbox)", False, elapsed, "the order reached live mode; cancelling it now"
        )
    else:
        row(
            "placeorder (sandbox)",
            ok and bool(orderid),
            elapsed,
            detail or f"LIMIT BUY 1 at {price}",
        )
    if not orderid:
        return rows, 1

    ok, elapsed, data, detail = client.call(
        "cancelorder", {"strategy": "gthread-smoke", "orderid": orderid}
    )
    if went_live and not ok:
        detail = f"cancel order {orderid} in your broker's order book now ({detail})"
    row("cancelorder (sandbox)", ok, elapsed, detail or f"order {orderid} cancelled")
    return rows, 0 if all(r["ok"] for r in rows) else 1


def print_table(rows: list[dict]) -> None:
    print(f"{'check':<24}{'result':<8}{'runs':>5}{'median ms':>11}{'max ms':>9}  detail")
    for r in rows:
        print(
            f"{r['check']:<24}{'PASS' if r['ok'] else 'FAIL':<8}{r['runs']:>5}"
            f"{r['median_ms']:>11.0f}{r['max_ms']:>9.0f}  {r['detail'][:80]}"
        )
    passed = sum(1 for r in rows if r["ok"])
    print(f"\n{passed} passed, {len(rows) - passed} failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Broker smoke for a running OpenAlgo")
    parser.add_argument("--url", default="http://127.0.0.1:5000", help="OpenAlgo address")
    parser.add_argument("--apikey", help="OpenAlgo API key (asked for when omitted)")
    parser.add_argument("--symbol", default="SBIN")
    parser.add_argument("--second-symbol", default="INFY", help="also used by multiquotes")
    parser.add_argument("--exchange", default="NSE")
    parser.add_argument("--repeat", type=int, default=1, help="run every call this many times")
    parser.add_argument("--parallel", type=int, default=1, help="calls in flight at once")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds per call")
    parser.add_argument(
        "--order-check",
        action="store_true",
        help="place and cancel one far-from-market sandbox order (analyzer mode only)",
    )
    args = parser.parse_args(argv)

    apikey = args.apikey or getpass.getpass("OpenAlgo API key: ")
    if not apikey:
        print("An API key is needed. Generate one at /apikey in OpenAlgo.")
        return 1
    client = Client(args.url, apikey, timeout=args.timeout)

    print(f"OpenAlgo broker smoke against {args.url}")
    calls = read_only_calls(args.symbol, args.exchange, args.second_symbol)
    rows = run_read_only(client, calls, max(1, args.repeat), args.parallel)
    status = 0 if all(r["ok"] for r in rows) else 1
    if args.order_check:
        order_rows, order_status = order_check(client, args.symbol, args.exchange)
        rows.extend(order_rows)
        status = max(status, order_status)
    print()
    print_table(rows)
    return status


if __name__ == "__main__":
    sys.exit(main())
