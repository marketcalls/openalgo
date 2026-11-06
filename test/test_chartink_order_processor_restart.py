"""Chartink: the order processor restarts after its thread dies.

ensure_order_processor() trusted a module flag that only the processor's own
normal exit (the poison pill) cleared. A thread that died any other way left
the flag set, so every later order was queued for a processor that no longer
existed and was never placed. The guard now also checks the thread itself.
"""

import queue
import time

import blueprints.chartink as chartink


class _DiesOnce:
    """A queue whose first read kills the processor thread outright."""

    def __init__(self):
        self.calls = 0

    def get_nowait(self):
        self.calls += 1
        if self.calls == 1:
            raise SystemExit
        return None  # poison pill: the restarted processor exits cleanly


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_processor_restarts_after_its_thread_dies(monkeypatch):
    dying = _DiesOnce()
    monkeypatch.setattr(chartink, "smart_order_queue", dying)
    monkeypatch.setattr(chartink, "regular_order_queue", queue.Queue())
    monkeypatch.setattr(chartink, "order_processor_running", False)

    chartink.ensure_order_processor()
    assert _wait_for(lambda: dying.calls == 1)
    time.sleep(0.2)  # let the thread finish dying

    chartink.ensure_order_processor()

    assert _wait_for(lambda: dying.calls >= 2), "a dead order processor was never restarted"
    assert _wait_for(lambda: chartink.order_processor_running is False)


def test_running_processor_is_not_duplicated(monkeypatch):
    monkeypatch.setattr(chartink, "smart_order_queue", queue.Queue())
    monkeypatch.setattr(chartink, "regular_order_queue", queue.Queue())
    monkeypatch.setattr(chartink, "order_processor_running", False)
    monkeypatch.setattr(chartink, "_order_processor_thread", None, raising=False)

    chartink.ensure_order_processor()
    first = chartink._order_processor_thread
    chartink.ensure_order_processor()
    assert chartink._order_processor_thread is first

    chartink.smart_order_queue.put(None)
    first.join(timeout=5)
    assert not first.is_alive()
