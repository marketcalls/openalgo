"""Stopping a strategy must not freeze the app while the process dies.

`stop_strategy_process` held PROCESS_LOCK across `process.wait(timeout=5)`.
Two separate faults sat in that one line:

1. `Popen.wait(timeout=...)` blocks inside C, `waitpid` on Linux and
   `WaitForSingleObject` on Windows. Under gunicorn-eventlet one OS thread
   runs every greenlet, so the call stops the entire worker for the length of
   the timeout, not just the caller. Moving the wait out of the lock, which is
   what the bug report proposed, would not have fixed this half: the hub is
   frozen by the C call itself. The psutil branch of the same function was
   already fixed this way (`wait_for_psutil_process_exit`); the
   `subprocess.Popen` branch was not.
2. The lock is process-wide and every start, stop, restart and status read
   takes it, so holding it for the death of a subprocess serialised all of
   them behind it.

The first two tests assert the defects themselves, so this file cannot pass
vacuously: `test_wait_never_calls_the_blocking_popen_wait` fails on the old
code because it called `process.wait`, and
`test_lock_is_free_while_the_process_is_dying` fails because the lock was held
throughout.

Reported as issue #1737.
"""

import subprocess
import sys
import threading
import time

import pytest

from blueprints import python_strategy as ps


class FakePopen(subprocess.Popen):
    """A Popen that stays alive for `alive_for` seconds after a signal.

    Subclasses Popen so `isinstance(process, subprocess.Popen)` still selects
    the branch under test, without spawning anything.
    """

    def __init__(self, alive_for=0.0):
        self.pid = 424242
        self._alive_for = alive_for
        self._signalled_at = None
        self.wait_calls = []
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self):
        if self._signalled_at is None:
            return None
        if time.monotonic() - self._signalled_at < self._alive_for:
            return None
        return 0

    def wait(self, timeout=None):
        # The defect, faithfully reproduced: the real Popen.wait blocks inside
        # C until the process exits or the timeout expires, and is not a yield
        # point. Blocking here is what lets the lock test show the contention
        # rather than merely showing that nothing waited.
        self.wait_calls.append(timeout)
        deadline = time.monotonic() + (timeout if timeout is not None else 30)
        while time.monotonic() < deadline:
            if self.poll() is not None:
                return 0
            time.sleep(0.02)
        raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout)

    def terminate(self):
        self.terminate_calls += 1
        if self._signalled_at is None:
            self._signalled_at = time.monotonic()

    def kill(self):
        self.kill_calls += 1
        self._signalled_at = time.monotonic()
        self._alive_for = 0.0


@pytest.fixture(autouse=True)
def clean_registries():
    """Leave the module-level registries as they were found."""
    running = dict(ps.RUNNING_STRATEGIES)
    configs = dict(ps.STRATEGY_CONFIGS)
    yield
    ps.RUNNING_STRATEGIES.clear()
    ps.RUNNING_STRATEGIES.update(running)
    ps.STRATEGY_CONFIGS.clear()
    ps.STRATEGY_CONFIGS.update(configs)


@pytest.fixture
def quiet_stop(monkeypatch):
    """Stub the side effects a stop performs so the tests stay in-memory."""
    monkeypatch.setattr(ps, "save_configs", lambda: None)
    monkeypatch.setattr(ps, "broadcast_status_update", lambda *a, **k: None)
    monkeypatch.setattr(ps, "cleanup_strategy_logs", lambda *a, **k: None)
    monkeypatch.setattr(ps, "close_log_handle_safely", lambda *a, **k: None)
    monkeypatch.setattr(ps, "get_schedule_status", lambda cfg: ("stopped", "Stopped"))


def _register(strategy_id, process):
    ps.RUNNING_STRATEGIES[strategy_id] = {
        "process": process,
        "pid": process.pid,
        "log_handle": None,
    }
    ps.STRATEGY_CONFIGS[strategy_id] = {
        "id": strategy_id,
        "name": strategy_id,
        "is_running": True,
        "pid": process.pid,
    }


def test_wait_never_calls_the_blocking_popen_wait(quiet_stop):
    """The eventlet-unsafe call must not be reached at all.

    Fails on the old code, which called `process.wait(timeout=5)` directly.
    """
    process = FakePopen(alive_for=0.3)
    _register("sid-blocking", process)

    ok, _ = ps.stop_strategy_process("sid-blocking")

    assert ok is True
    assert process.wait_calls == [], (
        f"Popen.wait was called with {process.wait_calls}; it blocks the eventlet "
        "hub and must be replaced by a cooperative poll"
    )
    assert process.terminate_calls == 1


def test_lock_is_free_while_the_process_is_dying(quiet_stop):
    """PROCESS_LOCK must be acquirable while the stop waits for the exit.

    Fails on the old code, where the whole termination ran inside the lock.
    """
    process = FakePopen(alive_for=1.0)
    _register("sid-lock", process)

    lock_was_free = threading.Event()
    stop_finished = threading.Event()

    def observer():
        # Give the stop time to reach its wait, then try to take the lock.
        time.sleep(0.3)
        if stop_finished.is_set():
            return  # Stop already returned; the window was never observed.
        if ps.PROCESS_LOCK.acquire(timeout=0.2):
            try:
                lock_was_free.set()
            finally:
                ps.PROCESS_LOCK.release()

    watcher = threading.Thread(target=observer, daemon=True)
    watcher.start()

    started = time.monotonic()
    ok, _ = ps.stop_strategy_process("sid-lock")
    elapsed = time.monotonic() - started

    watcher.join(timeout=2)

    assert ok is True
    assert elapsed >= 0.9, "the stop should have waited for the process to exit"
    assert lock_was_free.is_set(), (
        "PROCESS_LOCK was held for the whole termination; every other start, "
        "stop and status read blocks behind it"
    )


def test_a_process_that_refuses_to_die_is_still_tracked(quiet_stop, monkeypatch):
    """A failed stop must leave the strategy in RUNNING_STRATEGIES.

    The process is still alive, so dropping the entry would leave nothing
    tracking it and no way to stop it again.
    """
    monkeypatch.setattr(ps, "terminate_popen_safely", lambda *a, **k: False)

    process = FakePopen(alive_for=99.0)
    _register("sid-immortal", process)

    ok, message = ps.stop_strategy_process("sid-immortal")

    assert ok is False
    assert "Failed to stop" in message
    assert "sid-immortal" in ps.RUNNING_STRATEGIES


def test_a_second_stop_during_the_wait_does_not_signal_twice(quiet_stop):
    """Claiming under the lock means only one caller owns the termination."""
    process = FakePopen(alive_for=0.8)
    _register("sid-double", process)

    results = {}

    def second_stop():
        time.sleep(0.2)  # while the first stop is still waiting
        results["second"] = ps.stop_strategy_process("sid-double")

    other = threading.Thread(target=second_stop, daemon=True)
    other.start()
    results["first"] = ps.stop_strategy_process("sid-double")
    other.join(timeout=3)

    assert results["first"][0] is True
    assert results["second"][0] is False
    assert process.terminate_calls == 1, "the process was signalled more than once"


def test_wait_for_popen_exit_returns_on_a_live_process():
    """The poll helper reports False when the process outlives the timeout."""
    process = FakePopen(alive_for=99.0)
    process.terminate()

    started = time.monotonic()
    assert ps.wait_for_popen_exit(process, 0.3) is False
    assert time.monotonic() - started >= 0.25
    assert process.wait_calls == []


def test_wait_for_popen_exit_returns_immediately_when_already_dead():
    """An already-exited process costs nothing."""
    process = FakePopen(alive_for=0.0)
    process.terminate()

    started = time.monotonic()
    assert ps.wait_for_popen_exit(process, 5) is True
    assert time.monotonic() - started < 0.2


@pytest.mark.skipif(not sys.executable, reason="needs a python interpreter")
def test_stops_a_real_subprocess():
    """End to end against a real child, on whichever platform runs the suite."""
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert process.poll() is None
        assert ps.terminate_popen_safely(process, process.pid, 5, 2) is True
        assert process.poll() is not None
    finally:
        if process.poll() is None:  # pragma: no cover - safety net
            process.kill()
            process.wait(timeout=5)
