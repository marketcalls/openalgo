"""TradeSmart's per-endpoint rate limiting.

TradeSmart raised /GetQuotes to 100 requests per second while the other data
endpoints stayed on the older 120-per-minute allowance. A single shared gate
cannot serve both: paced for the minute budget it throttles quotes to under 1%
of what the broker now allows, and paced for the second budget it lets history
calls run 60x over their ceiling.
"""

import threading
import time

import pytest

from broker.tradesmart.api import rate_limiter as rl


@pytest.fixture(autouse=True)
def _reset_gates():
    """Each test starts with both clocks cold, and leaves them cold."""
    rl._QUOTES_GATE._last_call = 0.0
    rl._DEFAULT_GATE._last_call = 0.0
    yield
    rl._QUOTES_GATE._last_call = 0.0
    rl._DEFAULT_GATE._last_call = 0.0


class TestRouting:
    def test_quotes_get_the_per_second_budget(self):
        assert rl.interval_for("/GetQuotes") == rl.QUOTES_MIN_INTERVAL

    @pytest.mark.parametrize("endpoint", ["/TPSeries", "/EODChartData"])
    def test_history_stays_on_the_per_minute_budget(self, endpoint):
        assert rl.interval_for(endpoint) == rl.DEFAULT_MIN_INTERVAL

    @pytest.mark.parametrize("endpoint", [None, "/SomeEndpointAddedLater"])
    def test_unclassified_endpoints_are_paced_conservatively(self, endpoint):
        """An unknown endpoint must not be handed the per-second allowance."""
        assert rl.interval_for(endpoint) == rl.DEFAULT_MIN_INTERVAL

    def test_quotes_budget_is_actually_faster(self):
        assert rl.QUOTES_MIN_INTERVAL < rl.DEFAULT_MIN_INTERVAL

    def test_quotes_pace_stays_under_the_documented_cap(self):
        """~90/sec, with headroom under the broker's 100/sec."""
        per_second = 1.0 / rl.QUOTES_MIN_INTERVAL
        assert 80 <= per_second <= 100

    def test_default_pace_stays_under_the_documented_cap(self):
        per_minute = 60.0 / rl.DEFAULT_MIN_INTERVAL
        assert per_minute <= 120


class TestPacing:
    def test_quotes_burst_is_fast(self):
        """20 quote calls used to cost 11s at 0.55s each; now well under 1s."""
        started = time.monotonic()
        for _ in range(20):
            rl.apply_rate_limit("/GetQuotes")
        elapsed = time.monotonic() - started
        assert elapsed < 1.0, f"20 quote calls took {elapsed:.2f}s"

    def test_history_is_still_throttled(self):
        """Three history calls must still be spaced by the per-minute gate."""
        started = time.monotonic()
        for _ in range(3):
            rl.apply_rate_limit("/TPSeries")
        elapsed = time.monotonic() - started
        assert elapsed >= 2 * rl.DEFAULT_MIN_INTERVAL * 0.9

    def test_the_two_budgets_are_independent(self):
        """A history call must not consume the quotes budget."""
        rl.apply_rate_limit("/TPSeries")  # takes the slow gate
        started = time.monotonic()
        rl.apply_rate_limit("/GetQuotes")  # must not wait behind it
        assert time.monotonic() - started < 0.1


class TestConcurrency:
    def test_threads_space_out_rather_than_firing_together(self):
        """The slot is reserved under the lock, so waiters do not collide.

        If the timestamp were only written after sleeping, every thread would
        measure against the same stale value and fire at once.
        """
        stamps: list[float] = []
        stamps_lock = threading.Lock()

        def call():
            rl.apply_rate_limit("/GetQuotes")
            with stamps_lock:
                stamps.append(time.monotonic())

        threads = [threading.Thread(target=call) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(stamps) == 12
        stamps.sort()
        span = stamps[-1] - stamps[0]
        # 12 calls at ~1/90s each occupy roughly 0.12s; allow generous slack for
        # scheduler jitter, but they must not all land in the same instant.
        assert span >= rl.QUOTES_MIN_INTERVAL * 11 * 0.5, (
            f"12 concurrent quote calls spanned only {span:.4f}s - the gate is "
            "not spacing them"
        )

    def test_sleep_happens_outside_the_lock(self):
        """A waiter must not block others from computing their slot.

        Holding the lock across sleep would serialise 12 threads into 12
        sequential sleeps; with the sleep outside, total wall time stays close
        to the span of the reserved slots.
        """
        started = time.monotonic()
        threads = [
            threading.Thread(target=rl.apply_rate_limit, args=("/GetQuotes",))
            for _ in range(12)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert time.monotonic() - started < 2.0


class TestRateLimitDetection:
    def test_detects_the_noren_limit_message(self):
        assert rl.is_rate_limit_error(
            {
                "stat": "Not_Ok",
                "emsg": "Invalid Input :  Order Recieved 141 in a current minute "
                "exceeds Limit 120 for user",
            }
        )

    def test_matches_a_changed_ceiling(self):
        """The number is not hardcoded, so a new limit is still recognised."""
        assert rl.is_rate_limit_error(
            {"stat": "Not_Ok", "emsg": "Order Recieved 101 exceeds Limit 100 for user"}
        )

    @pytest.mark.parametrize(
        "response",
        [
            {"stat": "Ok", "lp": "100"},
            {"stat": "Not_Ok", "emsg": "Session expired"},
            {"stat": "Not_Ok"},
            {"stat": "Not_Ok", "emsg": None},
            None,
            [],
            "not a dict",
        ],
    )
    def test_ignores_everything_else(self, response):
        assert rl.is_rate_limit_error(response) is False


class TestRetryDelay:
    def test_backs_off_exponentially(self):
        assert [rl.retry_delay(i) for i in range(3)] == [2.0, 4.0, 8.0]
