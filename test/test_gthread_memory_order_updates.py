"""Slow strategy updates must not create an unbounded second event queue."""

import gc
import importlib.util
import subprocess
import sys
import threading
import weakref
from concurrent.futures import Future, ThreadPoolExecutor

import pytest

import restx_api  # noqa: F401
from services.strategy_module import order_events


class Update:
    def __init__(self, order_id):
        self.orderid = str(order_id)
        self.payload = bytearray(4096)


def test_slow_update_worker_bounds_retained_events_and_applies_every_update(monkeypatch):
    release = threading.Event()
    started = threading.Event()
    caller = threading.get_ident()
    applied = []
    held_too_long = []
    refs = []
    pool = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(order_events, "_POOL", pool)
    if hasattr(order_events, "_UPDATE_SLOTS"):
        monkeypatch.setattr(order_events, "_UPDATE_SLOTS", threading.BoundedSemaphore(128))

    def apply(order_id, event):
        if threading.get_ident() != caller:
            started.set()
            # Generous, and never a bare assert: an assertion raised here lands
            # in the pool's Future, where nobody reads it, and the update then
            # simply goes missing. On a busy CI runner that read as "511 of 512
            # applied", a lost update the code under test never made.
            if not release.wait(60):
                held_too_long.append(order_id)
        applied.append(order_id)

    monkeypatch.setattr(order_events, "_apply_update", apply)
    try:
        for i in range(512):
            event = Update(i)
            refs.append(weakref.ref(event))
            order_events._on_order_update(event)
            if i == 0:
                assert started.wait(3)
        del event
        gc.collect()
        retained = sum(ref() is not None for ref in refs)
        assert retained <= 128, f"slow worker retained {retained} payloads after 512 updates"
    finally:
        release.set()
        pool.shutdown(wait=True)
    gc.collect()
    assert not held_too_long, f"the test held updates {held_too_long} for over a minute"
    assert len(applied) == 512 and len(set(applied)) == 512
    assert not any(ref() is not None for ref in refs)


@pytest.mark.parametrize("outcome", ["completed", "cancelled", "failed_task", "failed_submit"])
def test_update_admission_is_returned_on_every_future_exit(monkeypatch, outcome):
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(order_events, "_UPDATE_SLOTS", slots)
    future = Future()

    class Pool:
        def submit(self, *args):
            if outcome == "failed_submit":
                raise RuntimeError("stopping")
            return future

    monkeypatch.setattr(order_events, "_POOL", Pool())
    order_events._on_order_update(Update("one"))
    if outcome == "completed":
        future.set_result(None)
    elif outcome == "cancelled":
        future.cancel()
    elif outcome == "failed_task":
        future.set_exception(RuntimeError("task failed"))
    assert slots.acquire(blocking=False), "completed/cancelled work leaked an admission slot"


@pytest.mark.skipif(importlib.util.find_spec("eventlet") is None, reason="requires eventlet")
def test_update_retention_bound_also_holds_with_eventlet():
    script = """
import eventlet
eventlet.monkey_patch()
import dotenv
dotenv.load_dotenv = lambda *a, **k: False
dotenv.main.load_dotenv = dotenv.load_dotenv
import runpy
import pytest
test = runpy.run_path('test/test_gthread_memory_order_updates.py')
with pytest.MonkeyPatch.context() as patch:
    test['test_slow_update_worker_bounds_retained_events_and_applies_every_update'](patch)
print('OK')
"""
    result = subprocess.run(
        [sys.executable, "-u", "-c", script], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
