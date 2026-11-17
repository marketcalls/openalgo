"""Run a strategy exactly as /python would, with every order held back.

    uv run python .claude/skills/python-strategy/rehearse.py <strategy.py>
        [--seconds 90] [--exchange NSE]

What is the same as /python:
* the interpreter (OpenAlgo's own), the working folder (OpenAlgo's), the
  environment (OpenAlgo's .env plus the injected STRATEGY_ID, STRATEGY_NAME,
  OPENALGO_STRATEGY_EXCHANGE, OPENALGO_API_KEY, OPENALGO_HOST), the file
  copied alone into a folder of its own, and the host's resource limit
  bootstrap and limits, read from blueprints/python_strategy.py
* Stop: SIGTERM to the process group, then a kill after the same grace period

What is different: REST calls go to a guard on 127.0.0.1 instead of straight to
OpenAlgo. The guard forwards read-only calls (quotes, history, symbols,
positions, funds, ...) to the real OpenAlgo and answers every order call
itself, so nothing reaches the broker or the Sandbox. It applies smart-order
rules the way the brokers and the Sandbox do and keeps its own position book,
so the strategy sees its orders fill. Market data still streams from the real
WebSocket, which carries no orders.

Refuses to run a file validate.py fails, or one with OpenAlgo's address typed
in (HOST), which would send its orders around the guard.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _host  # noqa: E402
import validate as validator  # noqa: E402

READ_ONLY = {
    "ping", "analyzer", "quotes", "multiquotes", "depth", "history", "intervals",
    "funds", "orderbook", "tradebook", "positionbook", "holdings", "orderstatus",
    "openposition", "symbol", "search", "expiry", "instruments", "optionchain",
    "optiongreeks", "multioptiongreeks", "optionsymbol", "syntheticfuture", "margin",
    "market/holidays", "market/timings", "gttorderbook", "ticker",
}  # fmt: skip
ORDER_CALLS = {
    "placeorder", "placesmartorder", "optionsorder", "optionsmultiorder", "basketorder",
    "splitorder", "modifyorder", "cancelorder", "cancelallorder", "closeposition",
    "placegttorder", "modifygttorder", "cancelgttorder",
}  # fmt: skip
MESSAGES = {"telegram/notify", "whatsapp/notify"}


class Guard:
    """Forwards reads to OpenAlgo; answers orders itself."""

    def __init__(self, upstream: str):
        self.upstream = upstream.rstrip("/")
        self.http = httpx.Client(timeout=20.0)
        self.lock = threading.Lock()
        self.calls: Counter[str] = Counter()
        self.failures: Counter[str] = Counter()
        self.refused: Counter[str] = Counter()
        self.orders: list[str] = []
        self.messages: list[str] = []
        self.book: dict[tuple[str, str, str], int] = {}
        self.fills: dict[str, dict] = {}
        self.seq = 0

    # -- upstream -------------------------------------------------------------

    def forward(self, method: str, endpoint: str, query: str, body: bytes) -> tuple[int, bytes]:
        url = f"{self.upstream}/api/v1/{endpoint}" + (f"?{query}" if query else "")
        try:
            reply = self.http.request(
                method, url, content=body or None, headers={"Content-Type": "application/json"}
            )
        except httpx.HTTPError as exc:
            self.failures[endpoint] += 1
            return 502, json.dumps({"status": "error", "message": f"guard: {exc}"}).encode()
        try:
            if reply.json().get("status") != "success":
                self.failures[endpoint] += 1
        except (ValueError, AttributeError):
            pass
        return reply.status_code, reply.content

    def read(self, endpoint: str, payload: dict) -> dict:
        _status, content = self.forward("POST", endpoint, "", json.dumps(payload).encode())
        try:
            return json.loads(content)
        except ValueError:
            return {}

    def ltp(self, apikey: str, symbol: str, exchange: str) -> float:
        reply = self.read("quotes", {"apikey": apikey, "symbol": symbol, "exchange": exchange})
        return float((reply.get("data") or {}).get("ltp") or 0)

    def position(self, apikey: str, key: tuple[str, str, str]) -> int:
        if key not in self.book:
            symbol, exchange, product = key
            reply = self.read(
                "openposition",
                {"apikey": apikey, "strategy": "rehearsal", "symbol": symbol,
                 "exchange": exchange, "product": product},
            )  # fmt: skip
            self.book[key] = int(float(reply.get("quantity") or 0))
        return self.book[key]

    # -- held-back orders -----------------------------------------------------

    def fill(self, apikey, kind, action, quantity, symbol, exchange, product, note="") -> str:
        price = self.ltp(apikey, symbol, exchange)
        key = (symbol, exchange, product)
        self.position(apikey, key)
        self.book[key] += quantity if action == "BUY" else -quantity
        self.seq += 1
        order_id = f"REHEARSAL{self.seq:04d}"
        self.fills[order_id] = {
            "orderid": order_id, "symbol": symbol, "exchange": exchange, "action": action,
            "quantity": str(quantity), "product": product, "pricetype": "MARKET",
            "order_status": "complete", "average_price": price, "price": 0,
        }  # fmt: skip
        stamp = time.strftime("%H:%M:%S")
        self.orders.append(
            f"{stamp}  {action} {quantity} {symbol} {exchange} {product} near {price:.2f}"
            f"  ({kind}{note})"
        )
        return order_id

    def order(self, endpoint: str, data: dict) -> dict:
        key_ = data.get("apikey", "")
        product = str(data.get("product") or "MIS").upper()
        if endpoint == "placesmartorder":
            symbol, exchange = str(data["symbol"]).upper(), str(data["exchange"]).upper()
            target = int(float(data.get("position_size") or 0))
            asked = int(float(data.get("quantity") or 0))
            current = self.position(key_, (symbol, exchange, product))
            if target == 0 and current == 0 and asked != 0:
                action, quantity = str(data.get("action", "BUY")).upper(), asked
                note = ", size 0 on a flat account: a NEW position"
            elif target == current:
                message = (
                    "No OpenPosition Found. Not placing Exit order."
                    if asked == 0
                    else "Positions Already Matched. No Action needed."
                )
                return {"status": "success", "message": message}
            else:
                diff = target - current
                action, quantity, note = ("BUY" if diff > 0 else "SELL"), abs(diff), ""
                note = f" to size {target:+d}" + note
            order_id = self.fill(key_, "smart order", action, quantity, symbol, exchange,
                                 product, note)  # fmt: skip
            return {"status": "success", "orderid": order_id}
        if endpoint in ("placeorder", "splitorder"):
            symbol, exchange = str(data["symbol"]).upper(), str(data["exchange"]).upper()
            order_id = self.fill(key_, endpoint, str(data["action"]).upper(),
                                 int(float(data["quantity"])), symbol, exchange, product)  # fmt: skip
            return {"status": "success", "orderid": order_id}
        if endpoint in ("optionsorder", "optionsmultiorder"):
            legs = data.get("legs") if endpoint == "optionsmultiorder" else [data]
            results = []
            for n, leg in enumerate(legs or [], start=1):
                resolved = self.read(
                    "optionsymbol",
                    {"apikey": key_, "underlying": data["underlying"],
                     "exchange": data["exchange"],
                     "expiry_date": leg.get("expiry_date") or data.get("expiry_date"),
                     "offset": leg["offset"], "option_type": leg["option_type"]},
                )  # fmt: skip
                if resolved.get("status") != "success":
                    results.append({"leg": n, "status": "error",
                                    "message": resolved.get("message", "no symbol")})  # fmt: skip
                    continue
                order_id = self.fill(
                    key_, endpoint, str(leg["action"]).upper(), int(float(leg["quantity"])),
                    resolved["symbol"], resolved["exchange"],
                    str(leg.get("product") or product).upper(),
                    f", {leg['offset']} {leg['option_type']}",
                )  # fmt: skip
                results.append({"leg": n, "status": "success", "orderid": order_id,
                                "symbol": resolved["symbol"], "action": leg["action"],
                                "offset": leg["offset"], "option_type": leg["option_type"],
                                "mode": "rehearsal"})  # fmt: skip
            if endpoint == "optionsorder":
                first = results[0] if results else {"status": "error"}
                if first.get("status") != "success":
                    return {"status": "error", "message": first.get("message", "failed")}
                return {"status": "success", "orderid": first["orderid"],
                        "symbol": first["symbol"], "exchange": data.get("exchange")}  # fmt: skip
            return {"status": "success", "underlying": data.get("underlying"),
                    "results": results}  # fmt: skip
        if endpoint == "closeposition":
            for key, quantity in list(self.book.items()):
                if quantity:
                    self.fill(key_, "closeposition", "SELL" if quantity > 0 else "BUY",
                              abs(quantity), *key)  # fmt: skip
            return {"status": "success", "message": "All positions closed (rehearsal)"}
        stamp = time.strftime("%H:%M:%S")
        self.orders.append(f"{stamp}  {endpoint} {json.dumps(_public(data))}")
        return {"status": "success", "message": f"{endpoint} held back by the rehearsal"}

    # -- dispatch -------------------------------------------------------------

    def handle(self, method: str, path: str, body: bytes) -> tuple[int, bytes]:
        parts = urlsplit(path)
        if not parts.path.startswith("/api/v1/"):
            return 404, b'{"status": "error", "message": "not an OpenAlgo API path"}'
        endpoint = parts.path[len("/api/v1/") :].strip("/")
        with self.lock:
            self.calls[endpoint] += 1
        try:
            data = json.loads(body) if body else {}
        except ValueError:
            data = {}
        if endpoint in ORDER_CALLS:
            with self.lock:
                try:
                    return 200, json.dumps(self.order(endpoint, data)).encode()
                except (KeyError, ValueError, TypeError) as exc:
                    self.failures[endpoint] += 1
                    return 400, json.dumps(
                        {"status": "error", "message": f"{endpoint}: missing or bad {exc}"}
                    ).encode()
        if endpoint == "orderstatus" and str(data.get("orderid", "")).startswith("REHEARSAL"):
            with self.lock:
                found = self.fills.get(data["orderid"])
            if found:
                return 200, json.dumps({"status": "success", "data": found}).encode()
        if endpoint == "openposition":
            key = tuple(str(data.get(k, "")).upper() for k in ("symbol", "exchange", "product"))
            with self.lock:
                if key in self.book:
                    return 200, json.dumps(
                        {"status": "success", "quantity": str(self.book[key])}
                    ).encode()
        if endpoint == "positionbook":
            status, content = self.forward(method, endpoint, parts.query, body)
            return status, self.overlay_positions(content)
        if endpoint in MESSAGES:
            with self.lock:
                self.messages.append(str(data.get("message", ""))[:200])
            return 200, b'{"status": "success", "message": "held back by the rehearsal"}'
        if endpoint in READ_ONLY:
            return self.forward(method, endpoint, parts.query, body)
        with self.lock:
            self.refused[endpoint] += 1
        return 403, json.dumps(
            {"status": "error", "message": f"{endpoint} is not available during a rehearsal"}
        ).encode()

    def overlay_positions(self, content: bytes) -> bytes:
        try:
            reply = json.loads(content)
        except ValueError:
            return content
        if reply.get("status") != "success":
            return content
        rows = list(reply.get("data") or [])
        with self.lock:
            for (symbol, exchange, product), quantity in self.book.items():
                match = [r for r in rows if (str(r.get("symbol")).upper(),
                         str(r.get("exchange")).upper(), str(r.get("product")).upper())
                         == (symbol, exchange, product)]  # fmt: skip
                price = next((f["average_price"] for f in reversed(self.fills.values())
                              if f["symbol"] == symbol), 0)  # fmt: skip
                if match:
                    match[0]["quantity"] = str(quantity)
                else:
                    rows.append({"symbol": symbol, "exchange": exchange, "product": product,
                                 "quantity": str(quantity), "average_price": price})  # fmt: skip
        reply["data"] = rows
        return json.dumps(reply).encode()


def _public(data: dict) -> dict:
    return {k: v for k, v in data.items() if k != "apikey"}


def serve(guard: Guard) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _reply(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            status, content = guard.handle(method, self.path, body)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def do_POST(self):  # noqa: N802 (http.server API name)
            self._reply("POST")

        def do_GET(self):  # noqa: N802
            self._reply("GET")

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="rehearsal-guard").start()
    return server


def calendar_exchange(path: Path) -> str:
    found = validator.settings(validator.ast.parse(path.read_text(encoding="utf-8")))
    exchange = str(found.get("EXCHANGE") or "NSE").upper()
    return {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE"}.get(exchange, exchange)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rehearse a strategy as /python runs it")
    parser.add_argument("strategy", type=Path)
    parser.add_argument("--seconds", type=float, default=90.0, help="how long to let it run")
    parser.add_argument("--exchange", help="the exchange chosen at /python (default: from file)")
    args = parser.parse_args()
    path = args.strategy.resolve()

    report = validator.validate(path)
    if report.failures:
        print(f"{path.name} fails validation; fix that first:")
        for level, message in report.lines:
            if level == "FAIL":
                print(f"  FAIL  {message}")
        return 1
    if report.fixed_host:
        print(
            f"{path.name} has OpenAlgo's address typed in (HOST), so its orders would go "
            "straight to OpenAlgo instead of to the rehearsal guard. Set HOST back to "
            'os.getenv("HOST_SERVER") or os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000") '
            "to rehearse."
        )
        return 1

    facts = _host.host_facts()
    base_env = _host.strategy_env()
    if not base_env.get("OPENALGO_API_KEY"):
        print("No API key: generate one at /apikey in OpenAlgo (or set OPENALGO_API_KEY).")
        return 1
    upstream = _host.rest_host(base_env)
    guard = Guard(upstream)
    server = serve(guard)
    guard_url = f"http://127.0.0.1:{server.server_address[1]}"
    exchange = (args.exchange or calendar_exchange(path)).upper()
    sid = f"{re.sub(r'[^A-Za-z0-9_-]', '', path.stem) or 'strategy'}_rehearsal"

    folder = Path(tempfile.mkdtemp(prefix="openalgo_rehearsal_"))
    script = folder / f"{sid}.py"
    shutil.copy2(path, script)
    env = dict(base_env)
    env.update(
        {
            "STRATEGY_ID": sid,
            "STRATEGY_NAME": f"{path.stem} (rehearsal)",
            "OPENALGO_STRATEGY_EXCHANGE": exchange,
            "HOST_SERVER": guard_url,
            "OPENALGO_HOST": guard_url,
            "OPENALGO_STRATEGY_MEM_MB": str(facts["memory_mb"]),
            "OPENALGO_STRATEGY_CPU_SEC": str(facts["cpu_seconds"]),
            "OPENALGO_STRATEGY_NOFILE": str(facts["nofile"]),
            "OPENALGO_STRATEGY_NPROC": str(facts["nproc"]),
        }
    )
    log_path = path.parent / "rehearsal.log"
    posix = os.name == "posix"
    command = (
        [sys.executable, "-u", "-c", facts["bootstrap"], str(script)]
        if posix
        else [sys.executable, "-u", str(script)]
    )
    print(f"Rehearsing {path.name} for {args.seconds:.0f}s as /python runs it "
          f"(exchange {exchange}); orders are held back by the guard.")  # fmt: skip
    print(f"Log: {log_path}")
    with open(log_path, "w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=_host.REPO,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=posix,
        )
        started = time.monotonic()
        while time.monotonic() - started < args.seconds and process.poll() is None:
            time.sleep(0.5)
        ran_for = time.monotonic() - started
        exited_early = process.poll() is not None
        stop_seconds = None
        if not exited_early:
            stop_at = time.monotonic()
            if posix:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:
                process.terminate()
            try:
                process.wait(timeout=facts["stop_grace_seconds"])
                stop_seconds = time.monotonic() - stop_at
            except subprocess.TimeoutExpired:
                if posix:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
    server.shutdown()
    shutil.rmtree(folder, ignore_errors=True)

    text = log_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    tracebacks = text.count("Traceback (most recent call last)")
    errors = [line for line in lines if "| ERROR" in line]
    results: list[tuple[str, str]] = []
    if exited_early:
        results.append(("FAIL", f"exited on its own after {ran_for:.0f}s with code "
                        f"{process.returncode}; /python would show it stopped"))  # fmt: skip
    else:
        results.append(("PASS", f"ran {ran_for:.0f}s under /python's interpreter, folder, "
                        "environment and limits"))  # fmt: skip
        if stop_seconds is None:
            results.append(("FAIL", f"did not stop within {facts['stop_grace_seconds']:.0f}s "
                            "of Stop and had to be killed, so nothing after Stop ran"))  # fmt: skip
        else:
            results.append(("PASS", f"stopped {stop_seconds:.1f}s after Stop (limit "
                            f"{facts['stop_grace_seconds']:.0f}s)"))  # fmt: skip
    if tracebacks:
        results.append(("FAIL", f"{tracebacks} traceback(s) in the log"))
    if errors:
        results.append(("WARN", f"{len(errors)} ERROR line(s) in the log, first: "
                        f"{errors[0].split('| ERROR', 1)[1].strip()[:160]}"))  # fmt: skip
    seen_ok = sum(guard.calls.values()) - sum(guard.failures.values())
    if seen_ok <= 0:
        results.append(("FAIL", "never got a successful answer from OpenAlgo"))
    for endpoint, count in sorted(guard.refused.items()):
        results.append(("FAIL", f"called {endpoint} {count}x, which a strategy should not"))
    order = {"FAIL": 0, "WARN": 1, "PASS": 2}
    print()
    for level, message in sorted(results, key=lambda r: order[r[0]]):
        print(f"  {level}  {message}")
    calls = ", ".join(f"{k} {v}" for k, v in sorted(guard.calls.items()))
    print(f"  API calls: {calls or 'none'}")
    if guard.failures:
        print("  Calls OpenAlgo answered with an error: "
              + ", ".join(f"{k} {v}" for k, v in sorted(guard.failures.items())))  # fmt: skip
    print(f"  Orders held back: {len(guard.orders)}")
    for line in guard.orders:
        print(f"    {line}")
    for message in guard.messages:
        print(f"    message held back: {message}")
    tail = lines[-12:] if any(level == "FAIL" for level, _ in results) else lines[-6:]
    print("  Last log lines:")
    for line in tail:
        print(f"    {line}")
    failed = any(level == "FAIL" for level, _ in results)
    print(f"Result: {'NOT READY' if failed else 'ready for /python'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
