"""
Regression tests for the IndMoney rate limiter.

The behaviour under test is safety-critical: an order write that is retried
after a 429 can place a SECOND live order, because placement/modify/cancel are
not idempotent and INDstocks offers no idempotency key. The read/write
classification boundary is what decides whether a retry happens at all, so it
is pinned here alongside the retry policy itself.
"""

import pytest

from broker.indmoney.api import rate_limiter as rl


class FakeResponse:
    def __init__(self, status_code, retry_after=None):
        self.status_code = status_code
        self.headers = {"Retry-After": retry_after} if retry_after else {}


class FakeClient:
    """Counts attempts and replays a fixed sequence of status codes."""

    def __init__(self, codes):
        self._codes = list(codes)
        self.attempts = 0

    def request(self, method, url, **kwargs):
        self.attempts += 1
        code = self._codes.pop(0) if self._codes else 200
        return FakeResponse(code, retry_after="0.01")


@pytest.fixture(autouse=True)
def _fast_and_isolated(monkeypatch):
    """Keep backoff negligible and pacing state clean between tests."""
    monkeypatch.setattr(rl, "BASE_BACKOFF", 0.001)
    rl._next_free.clear()
    rl._daily.clear()
    yield
    rl._next_free.clear()
    rl._daily.clear()


# --- classification: the read/write boundary decides retry eligibility -------


@pytest.mark.parametrize(
    ("url", "method", "expected"),
    [
        # Order WRITES - 10/s, never retried
        ("https://api.indstocks.com/order", "POST", "order"),
        ("https://api.indstocks.com/order/modify", "POST", "order"),
        ("https://api.indstocks.com/order/cancel", "POST", "order"),
        ("https://api.indstocks.com/smart/order", "POST", "order"),
        ("https://api.indstocks.com/smart/order/modify", "POST", "order"),
        ("https://api.indstocks.com/smart/order/cancel", "POST", "order"),
        # The SAME paths read back are Non-Trading ("Order History") - 15/s
        ("https://api.indstocks.com/order", "GET", "non_trading"),
        ("https://api.indstocks.com/order/trades", "GET", "non_trading"),
        ("https://api.indstocks.com/order-book", "GET", "non_trading"),
        ("https://api.indstocks.com/trade-book", "GET", "non_trading"),
        ("https://api.indstocks.com/user/profile", "GET", "non_trading"),
        ("https://api.indstocks.com/funds", "GET", "non_trading"),
        ("https://api.indstocks.com/portfolio/holdings", "GET", "non_trading"),
        # Market data - 5/s
        ("https://api.indstocks.com/market/quotes/full", "GET", "quote"),
        ("https://api.indstocks.com/market/quotes/ltp", "GET", "quote"),
        ("https://api.indstocks.com/market/quotes/mkt", "GET", "quote"),
        ("https://api.indstocks.com/market/historical/1day", "GET", "data"),
        ("https://api.indstocks.com/market/instruments", "GET", "data"),
        ("https://api.indstocks.com/margin", "GET", "data"),
    ],
)
def test_classify(url, method, expected):
    assert rl.classify(url, method) == expected


def test_paced_below_documented_ceiling():
    """Every bucket is paced under its documented ceiling, never at or above."""
    for bucket, documented in rl._DOCUMENTED_RATE.items():
        assert rl._RATE_PER_SECOND[bucket] < documented


# --- the safety-critical bit: order writes are never retried ----------------


@pytest.mark.parametrize(
    "url",
    [
        "https://api.indstocks.com/order",
        "https://api.indstocks.com/order/modify",
        "https://api.indstocks.com/order/cancel",
        "https://api.indstocks.com/smart/order",
        "https://api.indstocks.com/smart/order/cancel",
    ],
)
def test_order_write_is_never_retried_on_429(url):
    """
    A 429 the broker had already accepted must not be replayed - that is a
    duplicate live order. Exactly one attempt, and the 429 is returned to the
    caller to reconcile against the order book.
    """
    client = FakeClient([429, 429, 429, 429])
    response = rl.rate_limited_request(client, "POST", url)

    assert client.attempts == 1
    assert response.status_code == 429


def test_order_write_success_is_not_affected():
    client = FakeClient([200])
    response = rl.rate_limited_request(client, "POST", "https://api.indstocks.com/order")

    assert client.attempts == 1
    assert response.status_code == 200


# --- reads still retry ------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "method"),
    [
        ("https://api.indstocks.com/funds", "GET"),
        ("https://api.indstocks.com/order-book", "GET"),
        ("https://api.indstocks.com/order", "GET"),  # read on an order path
        ("https://api.indstocks.com/market/quotes/ltp", "GET"),
    ],
)
def test_reads_retry_on_429(url, method):
    client = FakeClient([429] * (rl.MAX_RETRIES + 5))
    response = rl.rate_limited_request(client, method, url)

    assert client.attempts == rl.MAX_RETRIES + 1
    assert response.status_code == 429


def test_read_retry_stops_once_it_succeeds():
    client = FakeClient([429, 429, 200])
    response = rl.rate_limited_request(client, "GET", "https://api.indstocks.com/funds")

    assert client.attempts == 3
    assert response.status_code == 200


def test_status_alias_is_set_for_legacy_callers():
    """Much of the broker code reads `.status` rather than `.status_code`."""
    client = FakeClient([200])
    response = rl.rate_limited_request(client, "GET", "https://api.indstocks.com/funds")

    assert response.status == response.status_code == 200


# --- backoff ----------------------------------------------------------------


def test_retry_after_header_is_honoured():
    assert rl.retry_delay({"Retry-After": "2.5"}, 0) == 2.5


def test_retry_after_is_capped():
    assert rl.retry_delay({"Retry-After": "9999"}, 0) == rl.MAX_BACKOFF


def test_backoff_is_exponential_and_capped():
    assert rl.retry_delay({}, 0) == rl.BASE_BACKOFF
    assert rl.retry_delay({}, 2) == rl.BASE_BACKOFF * 4
    assert rl.retry_delay({}, 99) == rl.MAX_BACKOFF


def test_garbage_retry_after_falls_back_to_backoff():
    assert rl.retry_delay({"Retry-After": "not-a-number"}, 1) == rl.BASE_BACKOFF * 2
