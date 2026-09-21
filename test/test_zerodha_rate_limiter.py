"""
Tests for the Zerodha rate limiter (GitHub issue #1710).

The reported failure was "Error fetching multiquotes: API Error: Too many
requests" from /gammadensity on a live deployment. Three things had to be true
for that to happen, and each has a test here:

  1. Quote is capped at 1 request/second, the tightest limit Kite publishes.
  2. Pacing has to be process-wide, because a fresh BrokerData is built for
     every request, so nothing kept on the instance survives to the next call.
  3. A rejection arrives as HTTP 200 with an error body, not only as a 429, so
     status-code-only detection would never retry.
"""

import threading
import time

import pytest

from broker.zerodha.api import rate_limiter as rl


@pytest.fixture(autouse=True)
def _reset_clocks():
    """Each test starts from an idle limiter."""
    with rl._lock:
        for key in rl._last_call:
            rl._last_call[key] = 0.0
    yield


# --- classification -------------------------------------------------------


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("/quote?i=NSE:SBIN", "quote"),
        ("/quote/ltp?i=NSE:SBIN&i=NSE:TCS", "quote"),
        ("/quote/ohlc?i=NSE:INFY", "quote"),
        ("/instruments/historical/408065/day?from=2024-01-01&to=2024-02-01", "historical"),
        ("/orders", "order"),
        ("/orders/regular", "order"),
        ("/trades", "order"),
        ("/gtt/triggers", "order"),
        ("/portfolio/holdings", "other"),
        ("/portfolio/positions", "other"),
        ("/user/margins", "other"),
        ("/margins/basket?consider_positions=true", "other"),
        ("/instruments", "other"),
    ],
)
def test_category_for(endpoint, expected):
    assert rl.category_for(endpoint) == expected


def test_historical_is_not_mistaken_for_the_instruments_dump():
    """/instruments/historical contains "/instruments" and must not fall to "other"."""
    assert rl.category_for("/instruments/historical/408065/minute") == "historical"
    assert rl.LIMITS["historical"] > rl.LIMITS["other"]


# --- pacing ---------------------------------------------------------------


def test_quote_calls_are_spaced_by_at_least_one_second():
    start = time.monotonic()
    rl.apply_rate_limit("/quote?i=NSE:SBIN")
    rl.apply_rate_limit("/quote?i=NSE:TCS")
    elapsed = time.monotonic() - start

    # Documented cap is 1/sec. The first call is free, the second waits.
    assert elapsed >= 1.0


def test_a_single_call_of_500_symbols_is_not_delayed():
    """
    Batching and pacing are separate concerns.

    /quote takes 500 instruments per request and the whole request costs one
    unit, so one batch must not be slowed down. The old code conflated the two
    and only threw in a sleep above 500 symbols.
    """
    start = time.monotonic()
    rl.apply_rate_limit("/quote?" + "&".join(f"i=NSE:SYM{n}" for n in range(500)))
    assert time.monotonic() - start < 0.1


def test_the_classes_do_not_share_a_budget():
    """A burst of quote traffic must not hold up order placement."""
    rl.apply_rate_limit("/quote?i=NSE:SBIN")

    start = time.monotonic()
    rl.apply_rate_limit("/orders/regular")
    assert time.monotonic() - start < 0.1


def test_concurrent_callers_queue_instead_of_firing_together():
    """
    The real-world shape of the bug: several requests in flight at once.

    Each thread builds its own BrokerData, so only module-level state can
    serialise them. Three quote calls must span at least two intervals.
    """
    fired = []
    lock = threading.Lock()

    def call():
        rl.apply_rate_limit("/quote?i=NSE:SBIN")
        with lock:
            fired.append(time.monotonic())

    start = time.monotonic()
    threads = [threading.Thread(target=call) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(fired) == 3
    assert max(fired) - start >= 2.0

    gaps = [b - a for a, b in zip(sorted(fired), sorted(fired)[1:], strict=False)]
    assert all(gap >= 0.9 for gap in gaps), gaps


# --- rejection detection --------------------------------------------------


def test_http_429_counts_as_rate_limited():
    assert rl.is_rate_limited(None, 429)
    assert rl.is_rate_limited({"status": "success"}, 429)


def test_a_200_carrying_the_error_body_counts_as_rate_limited():
    """This is the form the reported traceback actually showed."""
    body = {
        "status": "error",
        "message": "Too many requests",
        "error_type": "NetworkException",
    }
    assert rl.is_rate_limited(body, 200)


def test_ordinary_errors_are_not_treated_as_rate_limits():
    assert not rl.is_rate_limited({"status": "success", "data": {}}, 200)
    assert not rl.is_rate_limited(
        {"status": "error", "message": "Invalid session", "error_type": "TokenException"}, 403
    )
    assert not rl.is_rate_limited("<html>gateway timeout</html>", 504)
    assert not rl.is_rate_limited(None, None)


# --- backoff --------------------------------------------------------------


def test_retry_after_header_is_honoured():
    assert rl.retry_delay({"Retry-After": "5"}, 0, "/quote") == 5.0
    assert rl.retry_delay({"retry-after": "2.5"}, 0, "/quote") == 2.5


def test_a_junk_retry_after_falls_back_to_backoff():
    assert rl.retry_delay({"Retry-After": "soon"}, 0, "/quote") == rl.retry_delay(
        {}, 0, "/quote"
    )


def test_backoff_grows_and_never_dips_under_the_class_interval():
    delays = [rl.retry_delay({}, n, "/quote") for n in range(3)]
    assert delays == sorted(delays)
    assert all(d >= rl.LIMITS["quote"] for d in delays)


# --- the request wrapper --------------------------------------------------


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    """Rejects the first ``fail_times`` calls the way Kite does."""

    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            return _FakeResponse(
                {"status": "error", "message": "Too many requests"}, status_code=200
            )
        return _FakeResponse({"status": "success", "data": {"NSE:SBIN": {"last_price": 800}}})


def test_request_retries_a_rejection_and_returns_the_good_body():
    client = _FakeClient(fail_times=1)
    response, data = rl.request(client, "GET", f"{rl.BASE_URL}/portfolio/holdings")

    assert client.calls == 2
    assert response.status_code == 200
    assert data["status"] == "success"


def test_request_gives_up_after_max_retries_and_returns_the_rejection():
    """
    The caller's own error handling still runs.

    Returning the last response rather than raising keeps every existing call
    site behaving exactly as it did before.
    """
    client = _FakeClient(fail_times=99)
    response, data = rl.request(client, "GET", f"{rl.BASE_URL}/portfolio/holdings")

    assert client.calls == rl.MAX_RETRIES + 1
    assert data["message"] == "Too many requests"
    assert response.status_code == 200


def test_request_passes_a_non_json_body_back_as_none():
    class _HtmlClient:
        def get(self, url, **kwargs):
            return _FakeResponse(None, status_code=502)

    response, data = rl.request(_HtmlClient(), "GET", f"{rl.BASE_URL}/portfolio/holdings")
    assert data is None
    assert response.status_code == 502
