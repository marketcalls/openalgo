"""Kotak quotes rate-limit handling.

Neo's quotes endpoint refuses on concurrency rather than on rate: probed
2026-09-23, 20 back-to-back sequential requests ran 20/20 and every sequential
pacing from a 0.10s gap up ran 14/14, while 6 simultaneous requests drew an
HTTP 429 and 8 lost 14 of 24. _make_quotes_request handled none of it -- a 429
returned None, and since NIFTY carries a single index candidate there was no
second attempt, so get_quotes returned None, quotes_service turned that into
HTTP 500 "Failed to fetch quotes" and the option services reported "Failed to
fetch LTP for NIFTY" (QA OS-12, OS-13).

These pin the retry, the in-flight gate and the request timeout.
"""

import threading
import time
from unittest.mock import patch

import pytest

import broker.kotak.api.data as kotak_data

AUTH = "sess:::sid:::https://gw-napi.kotaksecurities.com:::acc"
OK_BODY = '[{"exchange_token": "Nifty 50", "ltp": "23446.8000"}]'


class FakeResponse:
    def __init__(self, status_code, text=OK_BODY, headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


@pytest.fixture
def broker_data():
    return kotak_data.BrokerData(AUTH)


@pytest.fixture(autouse=True)
def no_real_sleep():
    """Keep the backoff arithmetic without paying it in test time."""
    with patch.object(kotak_data.time, "sleep") as slept:
        yield slept


def _client(responses):
    """A stand-in httpx client returning each response in turn."""
    calls = []

    class Client:
        def get(self, url, headers=None, timeout=None):
            calls.append({"url": url, "timeout": timeout})
            return responses[min(len(calls) - 1, len(responses) - 1)]

    return Client(), calls


def test_a_429_is_retried_and_then_succeeds(broker_data, no_real_sleep):
    client, calls = _client([FakeResponse(429, '{"error":true}'), FakeResponse(200)])

    with patch.object(kotak_data, "get_httpx_client", return_value=client):
        result = broker_data._make_quotes_request("nse_cm|Nifty 50")

    assert result == [{"exchange_token": "Nifty 50", "ltp": "23446.8000"}]
    assert len(calls) == 2, "the 429 should have been retried"
    no_real_sleep.assert_called_once()


def test_backoff_grows_and_gives_up(broker_data, no_real_sleep):
    client, calls = _client([FakeResponse(429, '{"error":true}')])

    with patch.object(kotak_data, "get_httpx_client", return_value=client):
        result = broker_data._make_quotes_request("nse_cm|Nifty 50")

    # Exhausted, so the caller still learns it failed rather than getting a
    # zero-priced quote it cannot tell from a real one.
    assert result is None
    assert len(calls) == kotak_data.QUOTES_MAX_RETRIES + 1
    waits = [c.args[0] for c in no_real_sleep.call_args_list]
    assert waits == [0.5, 1.0, 2.0]
    assert waits == sorted(waits), "backoff must not shrink"


def test_retry_after_header_is_honoured(broker_data, no_real_sleep):
    client, _ = _client(
        [FakeResponse(429, '{"error":true}', {"Retry-After": "3"}), FakeResponse(200)]
    )

    with patch.object(kotak_data, "get_httpx_client", return_value=client):
        broker_data._make_quotes_request("nse_cm|Nifty 50")

    assert no_real_sleep.call_args_list[0].args[0] == 3.0


def test_a_non_429_error_is_not_retried(broker_data, no_real_sleep):
    # Retrying a 401 or a 404 just spends the budget that a real 429 needs.
    client, calls = _client([FakeResponse(404, '{"stat":"Not_Ok"}')])

    with patch.object(kotak_data, "get_httpx_client", return_value=client):
        result = broker_data._make_quotes_request("nse_cm|Nifty 50")

    assert result is None
    assert len(calls) == 1
    no_real_sleep.assert_not_called()


def test_request_carries_an_explicit_timeout(broker_data):
    # Without one it inherits the shared client's 120s and can hang a page.
    client, calls = _client([FakeResponse(200)])

    with patch.object(kotak_data, "get_httpx_client", return_value=client):
        broker_data._make_quotes_request("nse_cm|Nifty 50")

    assert calls[0]["timeout"] == kotak_data.QUOTES_TIMEOUT
    assert 0 < kotak_data.QUOTES_TIMEOUT <= 30


def test_no_more_than_the_gate_allows_are_ever_in_flight():
    """The gate is what actually prevents the 429, so measure it directly."""
    live = 0
    peak = 0
    lock = threading.Lock()

    class Client:
        def get(self, url, headers=None, timeout=None):
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(0.02)  # hold the slot long enough for others to pile up
            with lock:
                live -= 1
            return FakeResponse(200)

    def call():
        # A fresh handler per call, exactly as the services build one per request.
        kotak_data.BrokerData(AUTH)._make_quotes_request("nse_cm|Nifty 50")

    with patch.object(kotak_data, "get_httpx_client", return_value=Client()):
        threads = [threading.Thread(target=call) for _ in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert peak <= kotak_data.QUOTES_MAX_INFLIGHT, f"{peak} requests were in flight at once"


def test_the_gate_is_module_level_not_per_instance():
    # Services construct a new BrokerData per request, so a gate held on the
    # instance would admit every caller at once and gate nothing.
    assert isinstance(kotak_data._quotes_gate, type(threading.Semaphore(1)))
    a, b = kotak_data.BrokerData(AUTH), kotak_data.BrokerData(AUTH)
    assert not hasattr(a, "_quotes_gate") and not hasattr(b, "_quotes_gate")
