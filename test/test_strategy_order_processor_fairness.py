"""Regression test for issue #1735: smart orders starving regular orders in
the strategy background order processor (`blueprints/strategy.py`).

Root cause: `process_orders()` used to always `time_module.sleep(1); continue`
after handling one smart order. The `continue` restarted the loop at the top,
which checks the smart-order queue again before ever reaching the
regular-order block below it - so a steady stream of smart orders starved
regular orders indefinitely, not just delayed them by a few seconds.

Run:
    uv run pytest test/test_strategy_order_processor_fairness.py -v
"""

import os
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from blueprints import strategy as strat  # noqa: E402


def _drain(q):
    while True:
        try:
            q.get_nowait()
        except Exception:
            break


@pytest.fixture(autouse=True)
def _reset_processor_state():
    """Each test gets empty queues and a fresh smart-order rate-limit clock."""
    _drain(strat.smart_order_queue)
    _drain(strat.regular_order_queue)
    strat.last_regular_orders.clear()
    strat.last_smart_order_time = 0.0
    yield
    _drain(strat.smart_order_queue)
    _drain(strat.regular_order_queue)


def _fake_response(ok=True):
    resp = MagicMock()
    resp.is_success = ok
    resp.text = ""
    return resp


def _wait_until(predicate, timeout, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_regular_order_is_not_starved_by_a_smart_order_backlog():
    """A backlog of smart orders must not block a regular order indefinitely."""
    # Old code needed >= 1s per queued smart order before even looking at the
    # regular queue - 5 smart orders here means 5s+ before the old code would
    # reach the regular order at all.
    for i in range(5):
        strat.smart_order_queue.put({"payload": {"symbol": f"SMART{i}", "strategy": "t"}})
    strat.regular_order_queue.put({"payload": {"symbol": "REGULAR", "strategy": "t"}})

    with patch("utils.httpx_client.get_httpx_client") as get_client:
        get_client.return_value.post.return_value = _fake_response()

        worker = threading.Thread(target=strat.process_orders, daemon=True)
        worker.start()
        try:
            got_it = _wait_until(lambda: len(strat.last_regular_orders) >= 1, timeout=0.9)
        finally:
            strat.regular_order_queue.put(None)
            strat.smart_order_queue.put(None)
            worker.join(timeout=5)

    assert got_it, (
        "regular order was not serviced within 0.9s despite a 5-item smart-order "
        "backlog - the sleep(1)+continue starvation is back"
    )


def test_smart_orders_still_capped_near_one_per_second():
    """The fix must preserve the smart-order rate limit, not just remove it."""
    for i in range(3):
        strat.smart_order_queue.put({"payload": {"symbol": f"SMART{i}", "strategy": "t"}})

    with patch("utils.httpx_client.get_httpx_client") as get_client:
        get_client.return_value.post.return_value = _fake_response()

        worker = threading.Thread(target=strat.process_orders, daemon=True)
        worker.start()
        try:
            time.sleep(0.3)  # well under the 1/sec smart-order cap
            remaining = strat.smart_order_queue.qsize()
        finally:
            strat.regular_order_queue.put(None)
            strat.smart_order_queue.put(None)
            worker.join(timeout=5)

    assert remaining >= 2, (
        f"expected at most 1 of 3 smart orders drained within 0.3s (cap is "
        f"1/sec), but {3 - remaining} were drained - the fix must preserve "
        f"the smart-order rate limit, not remove it"
    )
