"""Tests for sandbox order-state and catch-up serialization (gate A9).

Covers GT-A9-08 (order state transitions) and GT-A9-09 (catch-up single-flight).

Both were carried as `INVESTIGATE:`. Both turned out to be real: an unguarded
check-then-act on order status that releases margin twice, and an unguarded
catch-up sweep reachable from two login paths at once.
"""

import importlib
import importlib.util
import inspect
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_real_sandbox():
    """Import the real `sandbox` package, not `test/sandbox/`.

    pytest puts the test directory on sys.path, and `test/sandbox/` is itself a
    package, so a plain import resolves there. Loading a module by file path is
    not enough either: these modules do `from sandbox.fund_manager import ...`
    internally, which goes back through the shadowed name.

    So bind the real package to `sandbox` for the duration of the import, then
    put whatever was there back.
    """
    saved = {k: v for k, v in sys.modules.items() if k == "sandbox" or k.startswith("sandbox.")}
    for key in list(saved):
        del sys.modules[key]

    spec = importlib.util.spec_from_file_location(
        "sandbox", REPO / "sandbox" / "__init__.py", submodule_search_locations=[str(REPO / "sandbox")]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["sandbox"] = package
    spec.loader.exec_module(package)

    try:
        return (
            importlib.import_module("sandbox.order_manager"),
            importlib.import_module("sandbox.catch_up_processor"),
        )
    finally:
        for key in [k for k in sys.modules if k == "sandbox" or k.startswith("sandbox.")]:
            del sys.modules[key]
        sys.modules.update(saved)


order_manager, catch_up = _load_real_sandbox()
OrderManager = order_manager.OrderManager


# --------------------------------------------------------------------------
# GT-A9-08: order state transitions
# --------------------------------------------------------------------------


def test_state_lock_is_shared_across_instances():
    """Callers build a fresh OrderManager per request, so a per-instance lock
    would guard nothing at all."""
    assert OrderManager("u1")._state_lock is OrderManager("u2")._state_lock


def test_cancel_and_modify_both_run_under_the_lock():
    for fn in ("cancel_order", "modify_order"):
        src = inspect.getsource(getattr(OrderManager, fn))
        assert "_state_lock" in src, f"{fn} does not take the state lock"


def test_the_guarded_body_still_checks_status_before_releasing_margin():
    """The check, the status change and the margin release must stay one unit.

    Two concurrent cancels of one order both read status "open", both pass the
    check, both set "cancelled", and both release the blocked margin --
    inflating available balance. fund_manager's own lock does not help: each
    release is individually valid, there are simply two of them.
    """
    src = inspect.getsource(OrderManager._cancel_order_locked)
    check_at = src.index("order_status not in")
    set_at = src.index('order_status = "cancelled"')
    release_at = src.index("release_margin")
    assert check_at < set_at < release_at, "check/set/release order changed"


def test_double_cancel_releases_margin_once_under_the_lock():
    """Behavioural: the guarded shape must admit exactly one transition."""
    released = []
    order_status = {"value": "open"}
    lock = OrderManager._state_lock
    barrier = threading.Barrier(8)

    def cancel_guarded(_b=barrier):
        _b.wait()
        with lock:
            if order_status["value"] not in ("open", "trigger pending"):
                return
            time.sleep(0.001)  # widen the window
            order_status["value"] = "cancelled"
            released.append(1)

    threads = [threading.Thread(target=cancel_guarded) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(released) == 1, f"margin released {len(released)} times"


def test_unguarded_double_cancel_really_does_double_release():
    """The control. Without it the test above proves nothing."""
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        doubled = False
        for _ in range(5):
            released = []
            order_status = {"value": "open"}
            barrier = threading.Barrier(8)

            def cancel_unguarded(_b=barrier, _s=order_status, _r=released):
                _b.wait()
                if _s["value"] not in ("open", "trigger pending"):
                    return
                time.sleep(0.001)  # the window the lock closes
                _s["value"] = "cancelled"
                _r.append(1)

            threads = [threading.Thread(target=cancel_unguarded) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            if len(released) > 1:
                doubled = True
                break
    finally:
        sys.setswitchinterval(old)

    assert doubled, "expected an unguarded cancel to release more than once"


# --------------------------------------------------------------------------
# GT-A9-09: catch-up single-flight
# --------------------------------------------------------------------------


def test_catch_up_has_a_single_flight_guard():
    assert hasattr(catch_up, "_catch_up_lock")
    src = inspect.getsource(catch_up.run_catch_up_tasks)
    assert "acquire(blocking=False)" in src, "must skip, not queue"


def test_a_second_trigger_skips_rather_than_queueing(monkeypatch):
    """Reachable from two login paths on separate threads, and OpenAlgo allows
    five concurrent device sessions. Queueing would simply run the whole sweep
    again the moment the first finished."""
    runs = []

    def slow_sweep():
        runs.append(1)
        time.sleep(0.05)

    monkeypatch.setattr(catch_up, "_run_catch_up_tasks_locked", slow_sweep)

    threads = [threading.Thread(target=catch_up.run_catch_up_tasks) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(runs) == 1, f"catch-up ran {len(runs)} times concurrently"


def test_the_guard_is_released_even_when_the_sweep_raises(monkeypatch):
    """A sweep that throws must not wedge every later trigger."""

    def boom():
        raise RuntimeError("sweep failed")

    monkeypatch.setattr(catch_up, "_run_catch_up_tasks_locked", boom)
    try:
        catch_up.run_catch_up_tasks()
    except RuntimeError:
        pass

    assert catch_up._catch_up_lock.acquire(blocking=False), "lock was left held"
    catch_up._catch_up_lock.release()
