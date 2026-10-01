"""scripts/gthread_broker_smoke.py reads only, and orders only in analyzer mode.

The script runs against a trader's live instance with their API key, so the
one thing it must never do is place a live order. A small fake OpenAlgo on a
local port records every call: the default run makes read-only calls only,
and the order check refuses in live mode, refuses if analyzer mode is
switched off between its check and the order, and in analyzer mode places a
LIMIT order at half the last price and cancels it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
READ_ONLY = {
    "funds",
    "positionbook",
    "orderbook",
    "tradebook",
    "holdings",
    "quotes",
    "multiquotes",
    "depth",
    "history",
    "intervals",
}


def _load():
    spec = importlib.util.spec_from_file_location(
        "gthread_broker_smoke_under_test", ROOT / "scripts" / "gthread_broker_smoke.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load()


class FakeOpenAlgo:
    """Answers /api/v1/<endpoint> like OpenAlgo, and remembers every call."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.analyze = False
        self.analyzer_answers: list[bool] = []
        self.failing: set[str] = set()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                endpoint = self.path.split("/api/v1/", 1)[1].strip("/")
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.calls.append((endpoint, body))
                status, payload = fake.answer(endpoint, body)
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def answer(self, endpoint, body):
        if endpoint in self.failing:
            return 500, {"status": "error", "message": "Broker did not answer"}
        if endpoint == "analyzer":
            analyze = self.analyzer_answers.pop(0) if self.analyzer_answers else self.analyze
            return 200, {
                "status": "success",
                "data": {"mode": "analyze" if analyze else "live", "analyze_mode": analyze},
            }
        if endpoint == "quotes":
            return 200, {"status": "success", "data": {"ltp": 812.4}}
        if endpoint == "placeorder":
            return 200, {"status": "success", "orderid": "S1", "mode": "analyze"}
        if endpoint == "cancelorder":
            return 200, {"status": "success", "orderid": body.get("orderid"), "mode": "analyze"}
        return 200, {"status": "success", "data": []}

    def endpoints(self) -> list[str]:
        return [endpoint for endpoint, _body in self.calls]

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake():
    server = FakeOpenAlgo()
    yield server
    server.close()


def test_the_default_run_is_read_only_and_never_prints_the_key(fake, capsys):
    status = smoke.main(
        ["--url", fake.url, "--apikey", "secret-key-123", "--repeat", "2", "--parallel", "4"]
    )
    out = capsys.readouterr().out
    assert status == 0, out
    assert set(fake.endpoints()) == READ_ONLY
    assert len(fake.calls) == 2 * len(READ_ONLY)
    assert all(body["apikey"] == "secret-key-123" for _endpoint, body in fake.calls)
    assert "secret-key-123" not in out
    assert "10 passed, 0 failed" in out


def test_a_failing_call_fails_the_run_with_the_brokers_words(fake, capsys):
    fake.failing = {"depth"}
    status = smoke.main(["--url", fake.url, "--apikey", "k"])
    out = capsys.readouterr().out
    assert status == 1
    assert "depth" in out and "FAIL" in out and "Broker did not answer" in out


def test_the_order_check_refuses_in_live_mode(fake, capsys):
    fake.analyze = False
    status = smoke.main(["--url", fake.url, "--apikey", "k", "--order-check"])
    out = capsys.readouterr().out
    assert status == smoke.REFUSED
    assert "placeorder" not in fake.endpoints() and "cancelorder" not in fake.endpoints()
    assert "live mode" in out


def test_a_switch_to_live_just_before_the_order_is_refused(fake, capsys):
    fake.analyzer_answers = [True, False]
    status = smoke.main(["--url", fake.url, "--apikey", "k", "--order-check"])
    assert status == smoke.REFUSED
    assert "placeorder" not in fake.endpoints()


def test_the_order_check_in_analyzer_mode_places_far_away_and_cancels(fake, capsys):
    fake.analyze = True
    status = smoke.main(["--url", fake.url, "--apikey", "k", "--order-check"])
    out = capsys.readouterr().out
    assert status == 0, out
    order = next(body for endpoint, body in fake.calls if endpoint == "placeorder")
    assert order["pricetype"] == "LIMIT" and order["action"] == "BUY" and order["quantity"] == 1
    assert order["price"] == pytest.approx(406.2)
    cancel = next(body for endpoint, body in fake.calls if endpoint == "cancelorder")
    assert cancel["orderid"] == "S1"
    assert fake.endpoints().index("cancelorder") > fake.endpoints().index("placeorder")
    analyzer_calls = [i for i, name in enumerate(fake.endpoints()) if name == "analyzer"]
    assert analyzer_calls[-1] < fake.endpoints().index("placeorder")
