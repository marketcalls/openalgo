"""The status API: the rolling request counter and the /status endpoint.

Loads the resource module by path, matching test_sip_api_security.py --
importing it as a package pulls in a chain that `test/sandbox/` shadows under
pytest.
"""

import importlib.util
import threading
from pathlib import Path

import pytest
from flask import Flask
from flask_restx import Api

from limiter import limiter
from services import status_service
from utils import request_counter

_MODULE_PATH = Path(__file__).parents[1] / "restx_api" / "status.py"
_SPEC = importlib.util.spec_from_file_location("status_api_under_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
status_api = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(status_api)


@pytest.fixture(autouse=True)
def clean_counter():
    request_counter._reset_for_tests()
    yield
    request_counter._reset_for_tests()


# --------------------------------------------------------------- the counter


def test_every_kind_is_reported_with_zero_when_nothing_was_counted():
    result = request_counter.counts(now=1000)

    assert set(result) == {"last_60s", "last_300s"}
    for window in result.values():
        assert window == dict.fromkeys(request_counter.KINDS, 0)


def test_a_request_counts_in_each_window_it_falls_inside():
    request_counter.record("quotes", now=1000)  # 100s before "now"
    request_counter.record("quotes", now=1050)  # 50s before
    request_counter.record("quotes", now=1100)  # this second
    request_counter.record("positionbook", now=1100)

    result = request_counter.counts(now=1100)

    assert result["last_60s"]["quotes"] == 2
    assert result["last_300s"]["quotes"] == 3
    assert result["last_60s"]["positionbook"] == 1
    assert result["last_300s"]["history"] == 0


def test_requests_older_than_the_longest_window_are_dropped():
    request_counter.record("history", now=1000)

    assert request_counter.counts(now=1299)["last_300s"]["history"] == 1
    assert request_counter.counts(now=1300)["last_300s"]["history"] == 0
    assert len(request_counter._buckets["history"]) == 0


def test_memory_stays_bounded_by_one_bucket_per_second():
    for second in range(2000):
        for _ in range(3):
            request_counter.record("quotes", now=second)

    assert len(request_counter._buckets["quotes"]) <= request_counter.MAX_WINDOW_SEC
    assert request_counter.counts(now=1999)["last_60s"]["quotes"] == 180


def test_an_unknown_kind_is_ignored_and_grows_nothing():
    request_counter.record("not-a-kind", now=1000)

    assert "not-a-kind" not in request_counter._buckets
    assert "not-a-kind" not in request_counter.counts(now=1000)["last_60s"]


def test_concurrent_records_are_all_counted():
    threads_n, per_thread = 8, 500
    barrier = threading.Barrier(threads_n)

    def worker():
        barrier.wait()
        for _ in range(per_thread):
            request_counter.record("quotes", now=5000)

    workers = [threading.Thread(target=worker) for _ in range(threads_n)]
    for t in workers:
        t.start()
    for t in workers:
        t.join()

    assert request_counter.counts(now=5000)["last_60s"]["quotes"] == threads_n * per_thread


def test_the_quotes_service_counts_a_call_before_it_reaches_the_broker(monkeypatch):
    """The count is taken where the request leaves for the broker, so a UI page
    calling the service directly is counted like an API call."""
    from services import quotes_service

    monkeypatch.setattr(quotes_service, "validate_symbol_exchange", lambda s, e: (False, "no"))

    quotes_service.get_quotes_with_auth("token", None, "zerodha", "INFY", "NSE")

    assert request_counter.counts()["last_60s"]["quotes"] == 1


# --------------------------------------------------------------- the endpoint


@pytest.fixture
def client(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    monkeypatch.setattr(limiter, "enabled", False)
    rest_api = Api(app)
    rest_api.add_namespace(status_api.api, path="/status")
    return app.test_client()


def test_an_invalid_api_key_is_refused_and_nothing_is_read(client, monkeypatch):
    read = []
    monkeypatch.setattr(status_service, "verify_api_key", lambda _k: None)
    monkeypatch.setattr(status_service, "get_active_status", lambda: read.append(1) or {})

    response = client.post("/status", json={"apikey": "wrong"})

    assert response.status_code == 403
    assert response.get_json() == {"status": "error", "message": "Invalid openalgo apikey"}
    assert read == []


def test_a_missing_api_key_is_a_validation_error(client):
    response = client.post("/status", json={})

    assert response.status_code == 400
    assert response.get_json()["status"] == "error"


def test_a_valid_key_returns_feed_streams_threads_and_request_counts(client, monkeypatch):
    monkeypatch.setattr(status_service, "verify_api_key", lambda _k: "admin")
    monkeypatch.setattr(
        status_service,
        "read_websocket_connections",
        lambda: ({"zerodha": {"broker": "zerodha", "count": 1, "symbols": 500}}, 1, 500),
    )
    request_counter.record("quotes")
    request_counter.record("quotes")
    request_counter.record("positionbook")

    response = client.post("/status", json={"apikey": "good"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "success"
    data = body["data"]
    assert data["broker_feed"] == {
        "connections": 1,
        "subscribed_symbols": 500,
        "pools": {"zerodha": {"broker": "zerodha", "count": 1, "symbols": 500}},
    }
    assert set(data["streams"]) == {"open", "by_kind"}
    assert set(data["threads"]) == {
        "active",
        "web_server_threads",
        "browser_connections",
        "headroom",
    }
    assert data["threads"]["active"] >= 1
    assert data["requests"]["last_60s"]["quotes"] == 2
    assert data["requests"]["last_300s"]["positionbook"] == 1
    assert data["requests"]["last_300s"]["history"] == 0


def test_an_internal_failure_does_not_leak_its_detail(client, monkeypatch):
    monkeypatch.setattr(status_service, "verify_api_key", lambda _k: "admin")

    def boom():
        raise RuntimeError("secret internals")

    monkeypatch.setattr(status_service, "read_websocket_connections", boom)

    response = client.post("/status", json={"apikey": "good"})

    assert response.status_code == 500
    assert "secret" not in response.get_data(as_text=True)
