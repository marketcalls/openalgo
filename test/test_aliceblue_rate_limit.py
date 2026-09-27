"""AliceBlue rate limiting (17-rate-limits.md).

    Orders - NOT LIMITED. Placing a new order, Modifying an existing order,
    square off positions and Cancelling an order are all not limited.

    All other requests - Limited to 1800 requests per 15 minutes.

A sliding window, not a fixed interval. 1800/900s averages 2 req/sec, but a
burst of 100 quotes is legal as long as the trailing 15 minutes stays under
budget - pacing everything 0.5s apart would make an option chain slow for a
reason the broker never asked for.
"""

import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

rl = pytest.importorskip("broker.aliceblue.api.rate_limiter")


@pytest.fixture(autouse=True)
def fresh_window():
    rl.reset()
    yield
    rl.reset()


def test_orders_are_never_throttled():
    """Delaying an exit to protect a read quota would be the wrong trade."""
    rl._request_times.extend([time.monotonic()] * rl.MAX_REQUESTS_PER_WINDOW)

    start = time.perf_counter()
    slept = rl.apply_rate_limit(is_order=True)
    elapsed = time.perf_counter() - start

    assert slept == 0.0
    assert elapsed < 0.05, "an order was throttled behind the read budget"


def test_a_burst_well_inside_the_budget_is_not_paced():
    """An option chain is ~80 calls at once and must not be slowed to 2/sec."""
    start = time.perf_counter()
    for _ in range(200):
        assert rl.apply_rate_limit() == 0.0
    elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"200 calls took {elapsed:.1f}s - the limiter is pacing a legal burst"


def test_the_window_is_the_documented_size():
    assert rl.WINDOW_SECONDS == 15 * 60
    assert rl.MAX_REQUESTS_PER_WINDOW == 1800


def test_quota_is_consumed_and_reported():
    budget = rl.MAX_REQUESTS_PER_WINDOW - rl.SAFETY_MARGIN
    assert rl.remaining_quota() == budget

    for _ in range(100):
        rl.apply_rate_limit()

    assert rl.remaining_quota() == budget - 100


def test_requests_falling_out_of_the_window_free_their_slots():
    """The window slides; it is not a fixed 15-minute bucket that must expire."""
    stale = time.monotonic() - (rl.WINDOW_SECONDS + 1)
    rl._request_times.extend([stale] * 500)

    assert rl.remaining_quota() == rl.MAX_REQUESTS_PER_WINDOW - rl.SAFETY_MARGIN, (
        "timestamps older than the window still counted against the budget"
    )


def test_a_full_window_blocks_until_the_oldest_ages_out(monkeypatch):
    """Verify the wait is computed, without actually sleeping 15 minutes."""
    slept = []
    monkeypatch.setattr(rl.time, "sleep", slept.append)

    now = time.monotonic()
    budget = rl.MAX_REQUESTS_PER_WINDOW - rl.SAFETY_MARGIN
    # Oldest entry is 60s into the window, so ~840s should remain on it.
    rl._request_times.extend([now - 60] * budget)

    waited = rl.apply_rate_limit()

    assert slept, "the limiter did not block on a full window"
    assert 830 < waited < 850, f"expected roughly 840s, got {waited:.0f}s"


def test_concurrent_callers_do_not_oversubscribe_the_window():
    """Threads must queue against one clock, not all claim the same slot."""
    budget = rl.MAX_REQUESTS_PER_WINDOW - rl.SAFETY_MARGIN

    def worker():
        for _ in range(100):
            rl.apply_rate_limit()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(rl._request_times) == 800
    assert rl.remaining_quota() == budget - 800
