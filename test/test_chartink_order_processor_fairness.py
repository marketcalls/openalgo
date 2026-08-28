"""Regression test for the same starvation bug as issue #1735, duplicated in
the ChartInk webhook order processor (`blueprints/chartink.py`).

`blueprints/chartink.py::process_orders()` is a separate implementation of
the same smart-order/regular-order queue processor as
`blueprints/strategy.py`, and had the identical bug: it always
`time_module.sleep(1); continue`'d after handling one smart order, which
restarted the loop before ever reaching the regular-order block - so a
steady stream of smart orders starved regular orders indefinitely.

Run:
    uv run pytest test/test_chartink_order_processor_fairness.py -v
"""

import os
import sys
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from blueprints import chartink as ck  # noqa: E402


def _drain(q):
    while True:
        try:
            q.get_nowait()
        except Exception:
            break


@pytest.fixture(autouse=True)
def _reset_processor_state():
    """Each test gets empty queues and a fresh smart-order rate-limit clock."""
    _drain(ck.smart_order_queue)
    _drain(ck.regular_order_queue)
    ck.last_regular_orders.clear()
    ck.last_smart_order_time = 0.0
    yield
    _drain(ck.smart_order_queue)
    _drain(ck.regular_order_queue)


def _fake_response(ok=True):
    resp = MagicMock()
    resp.ok = ok
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
    for i in range(5):
        ck.smart_order_queue.put({"payload": {"symbol": f"SMART{i}", "strategy": "t"}})
    ck.regular_order_queue.put({"payload": {"symbol": "REGULAR", "strategy": "t"}})

    with patch("requests.post", return_value=_fake_response()):
        worker = threading.Thread(target=ck.process_orders, daemon=True)
        worker.start()
        try:
            got_it = _wait_until(lambda: len(ck.last_regular_orders) >= 1, timeout=0.9)
        finally:
            ck.regular_order_queue.put(None)
            ck.smart_order_queue.put(None)
            worker.join(timeout=5)

    assert got_it, (
        "regular order was not serviced within 0.9s despite a 5-item smart-order "
        "backlog - the sleep(1)+continue starvation is back"
    )


def test_smart_orders_still_capped_near_one_per_second():
    """The fix must preserve the smart-order rate limit, not just remove it."""
    for i in range(3):
        ck.smart_order_queue.put({"payload": {"symbol": f"SMART{i}", "strategy": "t"}})

    with patch("requests.post", return_value=_fake_response()):
        worker = threading.Thread(target=ck.process_orders, daemon=True)
        worker.start()
        try:
            time.sleep(0.3)  # well under the 1/sec smart-order cap
            remaining = ck.smart_order_queue.qsize()
        finally:
            ck.regular_order_queue.put(None)
            ck.smart_order_queue.put(None)
            worker.join(timeout=5)

    assert remaining >= 2, (
        f"expected at most 1 of 3 smart orders drained within 0.3s (cap is "
        f"1/sec), but {3 - remaining} were drained - the fix must preserve "
        f"the smart-order rate limit, not remove it"
    )
