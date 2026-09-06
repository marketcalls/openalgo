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

import os
import subprocess
import sys
import threading
import time

import pytest

from blueprints import python_strategy as ps

IS_WINDOWS = os.name == "nt"


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
    stopping = set(ps.STOPPING_STRATEGIES)
    yield
    ps.RUNNING_STRATEGIES.clear()
    ps.RUNNING_STRATEGIES.update(running)
    ps.STRATEGY_CONFIGS.clear()
    ps.STRATEGY_CONFIGS.update(configs)
    ps.STOPPING_STRATEGIES.clear()
    ps.STOPPING_STRATEGIES.update(stopping)


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

    def observer():
        # Give the stop time to reach its wait, then try to take the lock. The
        # process stays alive for 1.0s and the elapsed assertion below proves
        # the stop was still waiting at this point, so no completion guard is
        # needed here.
        time.sleep(0.3)
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


def test_a_second_stop_during_the_wait_does_not_signal_twice(quiet_stop, monkeypatch):
    """Claiming means only one caller owns the termination.

    The config keeps a live-looking PID, so without the stopping marker the
    second stop falls through to the orphan branch, finds `check_process_status`
    true and signals the same process again. Pinned by asserting the second
    caller is refused *and* that only one signal was sent.
    """
    process = FakePopen(alive_for=1.0)
    _register("sid-double", process)

    # The orphan branch is reached by PID, so make that PID look alive and
    # record any attempt to terminate it by that route.
    orphan_kills = []
    monkeypatch.setattr(ps, "check_process_status", lambda pid: True)
    monkeypatch.setattr(
        ps, "terminate_process_cross_platform", lambda pid: orphan_kills.append(pid)
    )

    results = {}
    second_started = threading.Event()

    def second_stop():
        second_started.set()
        results["second"] = ps.stop_strategy_process("sid-double")

    other = threading.Thread(target=second_stop, daemon=True)

    def launch_second():
        # Fire once the first stop is definitely inside its wait.
        time.sleep(0.2)
        other.start()

    threading.Thread(target=launch_second, daemon=True).start()
    results["first"] = ps.stop_strategy_process("sid-double")
    assert second_started.wait(timeout=3), "the second stop never ran"
    other.join(timeout=3)

    assert results["first"][0] is True
    assert results["second"][0] is False
    assert "stopping" in results["second"][1].lower()
    assert process.terminate_calls == 1, "the process was signalled more than once"
    assert orphan_kills == [], f"the second stop reached the orphan path: {orphan_kills}"


def test_a_start_during_the_wait_is_refused(quiet_stop, monkeypatch, tmp_path):
    """A start arriving mid-termination must not launch a replacement.

    Without the stopping marker the strategy is in neither registry during the
    wait, so start sees it as absent, spawns a second process, and the finishing
    stop then writes is_running=False over the new one's config, leaving a live
    trading process nothing will stop.
    """
    process = FakePopen(alive_for=1.0)
    _register("sid-restart", process)

    # Give the start everything it needs to succeed, so the only thing that can
    # stop it is the stopping claim. Without a real file it would fail on
    # "Strategy file not found" and the test would pass for the wrong reason.
    script = tmp_path / "sid_restart.py"
    script.write_text("import time\ntime.sleep(60)\n", encoding="utf-8")
    ps.STRATEGY_CONFIGS["sid-restart"]["file_path"] = str(script)

    # Spy on the spawn path itself: the assertion that matters is that no second
    # process was created, not merely that the call returned False.
    # create_subprocess_args is used only by start_strategy_process and runs
    # immediately before subprocess.Popen, so reaching it means a spawn was
    # about to happen. Patching subprocess.Popen directly is not an option here:
    # stop_strategy_process branches on isinstance(process, subprocess.Popen),
    # which a non-class stand-in breaks.
    spawned = []

    def _spy_args():
        spawned.append("start reached the spawn path")
        raise AssertionError("start_strategy_process tried to spawn a replacement")

    monkeypatch.setattr(ps, "create_subprocess_args", _spy_args)
    monkeypatch.setattr(ps, "check_process_status", lambda pid: False)
    # Clear the gates that would otherwise refuse the start before it ever
    # reaches the spawn, so the spy above is genuinely reachable and the
    # assertion is not vacuous. Verified: with the stopping guard removed, this
    # test fails on the spy, not on one of these.
    monkeypatch.setattr(ps, "check_master_contract_ready", lambda: (True, "ready"))

    results = {}
    start_ran = threading.Event()

    def try_start():
        time.sleep(0.2)  # while the stop is still waiting
        results["start"] = ps.start_strategy_process("sid-restart")
        start_ran.set()

    threading.Thread(target=try_start, daemon=True).start()
    results["stop"] = ps.stop_strategy_process("sid-restart")
    assert start_ran.wait(timeout=3), "the start never ran"

    # Asserted first: this is the consequence that matters. Without the claim a
    # second process is spawned, and the failing message below is only how that
    # surfaces.
    assert spawned == [], (
        "start reached the spawn path while a stop was in flight, so a second "
        "process would have been created for one strategy"
    )
    assert results["stop"][0] is True
    assert results["start"][0] is False
    assert "stopping" in results["start"][1].lower()


def test_the_stopping_claim_is_released_when_termination_fails(quiet_stop, monkeypatch):
    """A failed stop must not leave the strategy permanently unstoppable."""
    monkeypatch.setattr(ps, "terminate_popen_safely", lambda *a, **k: False)

    process = FakePopen(alive_for=99.0)
    _register("sid-release", process)

    ok, _ = ps.stop_strategy_process("sid-release")

    assert ok is False
    assert "sid-release" not in ps.STOPPING_STRATEGIES, (
        "the claim was never released, so this strategy can never be started "
        "or stopped again for the life of the process"
    )
    assert "sid-release" in ps.RUNNING_STRATEGIES


def test_an_orphan_that_survives_termination_is_not_reported_stopped(quiet_stop, monkeypatch):
    """terminate_process_cross_platform swallows its own errors.

    A clean return from it is therefore not evidence the process died, so the
    config must not be cleared on a survivor: doing so leaves a live trading
    process with nothing tracking it and no route to stop it.
    """
    monkeypatch.setattr(ps, "terminate_process_cross_platform", lambda pid: None)
    monkeypatch.setattr(ps, "check_process_status", lambda pid: True)  # never dies

    ps.STRATEGY_CONFIGS["sid-orphan"] = {
        "id": "sid-orphan",
        "name": "sid-orphan",
        "is_running": True,
        "pid": 987654,
    }

    ok, message = ps.stop_strategy_process("sid-orphan")

    assert ok is False
    assert "987654" in message
    config = ps.STRATEGY_CONFIGS["sid-orphan"]
    assert config["is_running"] is True, "a surviving process was marked stopped"
    assert config["pid"] == 987654, "the PID was cleared while the process was alive"
    assert "sid-orphan" not in ps.STOPPING_STRATEGIES


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
        # Its own session, exactly as the production spawn does. On Linux
        # terminate_popen_safely signals the process GROUP, so a child sharing
        # the pytest runner's group would take SIGTERM and then SIGKILL out to
        # the whole test run.
        start_new_session=not IS_WINDOWS,
    )
    try:
        assert process.poll() is None
        assert ps.terminate_popen_safely(process, process.pid, 5, 2) is True
        assert process.poll() is not None
    finally:
        if process.poll() is None:  # pragma: no cover - safety net
            process.kill()
            process.wait(timeout=5)


# ---------------------------------------------------------------------------
# Deleting a strategy must abort on a live process, but not on stale metadata.
#
# delete_strategy now refuses when the stop fails, so that a running process is
# never left with its config and file deleted underneath it. `is_running` in the
# config goes stale whenever the app exits without running cleanup, though, and
# the stop for one of those returns "Strategy not running". Refusing on that
# made the strategy permanently undeletable: every later attempt took the same
# path and failed the same way.
# ---------------------------------------------------------------------------


def test_stale_running_metadata_does_not_block_deletion(quiet_stop, monkeypatch):
    """A dead PID left behind by an unclean shutdown must still be deletable."""
    monkeypatch.setattr(ps, "check_process_status", lambda pid: False)

    ps.STRATEGY_CONFIGS["sid-stale"] = {
        "id": "sid-stale",
        "name": "sid-stale",
        "is_running": True,  # stale: the app died without clearing it
        "pid": 999999,  # long gone
    }

    stopped, message = ps.stop_strategy_process("sid-stale")
    assert stopped is False
    assert message == "Strategy not running"

    # The guard delete_strategy consults must not treat this as protectable.
    assert ps._strategy_may_still_be_running("sid-stale") is False


def test_a_live_process_still_blocks_deletion(quiet_stop, monkeypatch):
    """The protection itself must survive the fix above."""
    monkeypatch.setattr(ps, "check_process_status", lambda pid: True)

    ps.STRATEGY_CONFIGS["sid-live"] = {
        "id": "sid-live",
        "name": "sid-live",
        "is_running": True,
        "pid": 4242,
    }

    assert ps._strategy_may_still_be_running("sid-live") is True


def test_a_tracked_or_stopping_strategy_blocks_deletion(quiet_stop, monkeypatch):
    """Tracked, or mid-stop, both count as still running."""
    monkeypatch.setattr(ps, "check_process_status", lambda pid: False)

    process = FakePopen(alive_for=0.0)
    _register("sid-tracked", process)
    assert ps._strategy_may_still_be_running("sid-tracked") is True

    ps.RUNNING_STRATEGIES.pop("sid-tracked", None)
    ps.STRATEGY_CONFIGS["sid-tracked"]["pid"] = None
    assert ps._strategy_may_still_be_running("sid-tracked") is False

    ps.STOPPING_STRATEGIES.add("sid-tracked")
    assert ps._strategy_may_still_be_running("sid-tracked") is True
