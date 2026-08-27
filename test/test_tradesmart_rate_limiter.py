"""TradeSmart's shared per-user rate limiting.

TradeSmart bills every data call against ONE per-user budget with two rolling
windows, 10/sec and 120/min. An earlier revision assumed /GetQuotes had been
raised to 100/sec and was exempt from the per-minute allowance; live logs
disproved both -- a single option-chain request tripped
"Order Recieved 11 in a current second exceeds Limit 10 for user" and
"Order Recieved 121 in a current minute exceeds Limit 120 for user", both on
/GetQuotes. These tests pin the corrected model.
"""

import threading
import time
from collections import deque

import pytest

from broker.tradesmart.api import rate_limiter as rl


@pytest.fixture(autouse=True)
def _reset_gate():
    """Each test starts with a cold window, and leaves one behind."""
    rl._reserved_call_times = deque()
    yield
    rl._reserved_call_times = deque()


class TestCeilings:
    def test_per_second_pace_stays_under_the_broker_cap(self):
        """Broker rejects the 11th call in a second; we stop short of that."""
        assert rl.TRADESMART_MAX_PER_SECOND < 10

    def test_per_minute_pace_stays_under_the_broker_cap(self):
        """Broker rejects the 121st call in a minute; we stop short of that."""
        assert rl.TRADESMART_MAX_PER_MINUTE < 120

    def test_quotes_are_not_exempt_from_any_window(self):
        """/GetQuotes bills against the same budget as history.

        The per-minute rejections observed in production were all on
        /GetQuotes, so routing quotes to a separate or per-second-only gate
        would let the account blow the minute ceiling.
        """
        for _ in range(rl.TRADESMART_MAX_PER_MINUTE):
            rl._reserve_slot()
        # The budget is now spent for the minute -- a history call must wait,
        # proving quotes consumed the same counter history draws from.
        assert rl._reserve_slot() > 30.0


class TestPacing:
    def test_a_burst_up_to_the_cap_goes_out_immediately(self):
        """Burst-friendly: the gate does not space calls that fit the window."""
        started = time.monotonic()
        for _ in range(rl.TRADESMART_MAX_PER_SECOND):
            rl.apply_rate_limit("/GetQuotes")
        assert time.monotonic() - started < 0.1

    def test_the_call_after_the_cap_waits_a_full_second(self):
        for _ in range(rl.TRADESMART_MAX_PER_SECOND):
            rl._reserve_slot()
        wait = rl._reserve_slot()
        assert 0.9 <= wait <= 1.05, f"expected ~1s wait, got {wait:.3f}s"

    def test_an_option_chain_batch_is_paced_not_rejected(self):
        """82 quotes (a 41-strike chain) spread over ~10s instead of failing."""
        waits = [rl._reserve_slot() for _ in range(82)]
        expected = (82 - 1) // rl.TRADESMART_MAX_PER_SECOND
        assert expected - 0.5 <= max(waits) <= expected + 0.5

    def test_history_and_quotes_share_one_budget(self):
        """No independent gates -- the broker counts per user, not per path."""
        for _ in range(rl.TRADESMART_MAX_PER_SECOND):
            rl.apply_rate_limit("/TPSeries")
        assert rl._reserve_slot() > 0.9


class TestWindowBookkeeping:
    def test_entries_older_than_a_minute_stop_constraining(self):
        """A stale window must not throttle a fresh burst."""
        rl._reserved_call_times = deque([time.time() - 120.0] * rl.TRADESMART_MAX_PER_MINUTE)
        assert rl._reserve_slot() == pytest.approx(0.0, abs=0.05)

    def test_reservations_stay_ordered(self):
        for _ in range(50):
            rl._reserve_slot()
        stamps = list(rl._reserved_call_times)
        assert stamps == sorted(stamps)


class TestConcurrency:
    def test_threads_space_out_rather_than_firing_together(self):
        """The slot is reserved under the lock, so waiters do not collide.

        If the timestamp were only written after sleeping, every thread would
        measure against the same stale window and fire at once.
        """
        stamps: list[float] = []
        stamps_lock = threading.Lock()

        def call():
            rl.apply_rate_limit("/GetQuotes")
            with stamps_lock:
                stamps.append(time.monotonic())

        n = rl.TRADESMART_MAX_PER_SECOND * 2
        threads = [threading.Thread(target=call) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(stamps) == n
        stamps.sort()
        # The second half must land a second after the first, not alongside it.
        assert stamps[-1] - stamps[0] >= 0.9

    def test_sleep_happens_outside_the_lock(self):
        """A waiter must not block others from computing their slot.

        Holding the lock across sleep would serialise the threads into
        sequential sleeps; with the sleep outside, total wall time stays close
        to the span of the reserved slots rather than their sum.
        """
        started = time.monotonic()
        threads = [
            threading.Thread(target=rl.apply_rate_limit, args=("/GetQuotes",))
            for _ in range(rl.TRADESMART_MAX_PER_SECOND * 2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert time.monotonic() - started < 2.0


class TestRateLimitDetection:
    def test_detects_the_per_minute_message(self):
        assert rl.is_rate_limit_error(
            {
                "stat": "Not_Ok",
                "emsg": "Invalid Input :  Order Recieved 121 in a current minute "
                "exceeds Limit 120 for user",
            }
        )

    def test_detects_the_per_second_message(self):
        assert rl.is_rate_limit_error(
            {
                "stat": "Not_Ok",
                "emsg": "Invalid Input :  Order Recieved 11 in a current second "
                "exceeds Limit 10 for user",
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
