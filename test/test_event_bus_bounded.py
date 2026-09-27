"""EventBus backpressure and Flow lock-registry lifetime (issue #1739).

Two unbounded structures were reported:

* ``EventBus`` dispatches through a ThreadPoolExecutor whose work queue is an
  unbounded ``queue.SimpleQueue``. A publisher outrunning its subscribers grew
  it until the process was OOM-killed - and production is a single gunicorn
  worker that never restarts, so nothing reclaims it.
* ``flow_executor_service._workflow_locks`` kept a lock per workflow id forever.

The reported trigger (market tick spikes) is not real - ticks travel over ZMQ
and never touch the bus - but order/GTT/fill events genuinely burst.
"""

import os
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.event_bus import Event, EventBus  # noqa: E402


class _Gate:
    """A subscriber that blocks until released, to build a queue on purpose."""

    def __init__(self):
        self.release = threading.Event()
        self.started = threading.Semaphore(0)
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, event):
        with self._lock:
            self.calls += 1
        self.started.release()
        self.release.wait(timeout=30)


def test_publish_is_bounded_and_sheds_load():
    """Queue depth must stop at max_pending instead of growing without limit."""
    bus = EventBus(workers=2, max_pending=50)
    gate = _Gate()
    bus.subscribe("t", gate)

    try:
        for _ in range(500):
            bus.publish(Event(topic="t"))

        stats = bus.stats()
        assert stats["pending"] <= 50, f"queue grew past the cap: {stats}"
        assert stats["dropped"] > 0, "nothing was shed despite 500 publishes over a cap of 50"
        assert stats["pending"] + stats["dropped"] == 500
    finally:
        gate.release.set()
        bus._executor.shutdown(wait=True)


def test_publish_never_blocks_the_publisher():
    """Shedding, not blocking: the order path must not stall behind subscribers."""
    bus = EventBus(workers=1, max_pending=5)
    gate = _Gate()
    bus.subscribe("t", gate)

    try:
        start = time.perf_counter()
        for _ in range(200):
            bus.publish(Event(topic="t"))
        elapsed = time.perf_counter() - start

        assert elapsed < 2.0, (
            f"publish took {elapsed:.1f}s for 200 events - it is blocking on a full queue "
            f"instead of dropping"
        )
    finally:
        gate.release.set()
        bus._executor.shutdown(wait=True)


def test_pending_returns_to_zero_after_draining():
    """The counter must not leak, or the bus wedges shut after enough events."""
    bus = EventBus(workers=4, max_pending=100)
    seen = []
    bus.subscribe("t", lambda e: seen.append(e))

    for _ in range(50):
        bus.publish(Event(topic="t"))
    bus._executor.shutdown(wait=True)

    assert len(seen) == 50, "events were dropped while well under the cap"
    assert bus.stats()["pending"] == 0, f"pending leaked: {bus.stats()}"


def test_a_failing_subscriber_still_releases_its_slot():
    """An exception in a callback must not permanently consume capacity."""
    bus = EventBus(workers=2, max_pending=10)

    def boom(event):
        raise RuntimeError("subscriber blew up")

    bus.subscribe("t", boom)

    for _ in range(30):
        bus.publish(Event(topic="t"))
    bus._executor.shutdown(wait=True)

    assert bus.stats()["pending"] == 0, f"a raising subscriber leaked pending slots: {bus.stats()}"


# --- Flow workflow lock registry --------------------------------------------


@pytest.fixture
def flow_locks():
    fes = pytest.importorskip("services.flow_executor_service")
    return fes


def test_concurrent_callers_share_one_lock(flow_locks):
    """The property a size-capped, evicting registry would silently break.

    execute_workflow guards on ``lock.locked()``. If two callers can ever get
    different lock objects for the same workflow, that guard passes for both and
    the workflow executes twice - placing every order in it twice.
    """
    held = flow_locks.get_workflow_lock(4242)
    held.acquire()
    try:
        second = flow_locks.get_workflow_lock(4242)
        assert second is held, "a concurrent caller got a different lock object"
        assert second.locked(), "the duplicate-execution guard would not have fired"
    finally:
        held.release()


def test_registry_does_not_retain_idle_workflows(flow_locks):
    """Entries must not accumulate for every workflow id ever executed."""
    import gc

    for workflow_id in range(9000, 9200):
        lock = flow_locks.get_workflow_lock(workflow_id)
        with lock:
            pass
        del lock

    gc.collect()

    retained = [wid for wid in range(9000, 9200) if wid in flow_locks._workflow_locks]
    assert not retained, f"{len(retained)} idle workflow locks were retained"
