"""Stopping child strategies when the shutdown itself is interrupted.

**The failure this file is about.** A run is a child process that places orders
and outlives its parent, so the thing that stops every one of them at exit is
the last defence against a strategy still trading with nothing able to stop it.
That function runs from ``atexit``, which means it runs while the interpreter is
already leaving after the first Ctrl+C, and it waits several seconds per child
for each to finish the bar it is on.

A shutdown that pauses looks stuck, so somebody presses Ctrl+C again. That
second signal raised ``SystemExit`` straight into the waiting loop. ``SystemExit``
is not an ``Exception``, so the per-child guard did not catch it, the loop ended,
and every run after the one being waited on was left running. The symptom an
operator sees is only ``Exception ignored in atexit callback``, which reads as
shutdown noise and not as strategies that are still trading.
"""

import pytest

from services import openscript_runner_service as service


class FakeProcess:
    """A child that can be asked to stop, and records whether it was."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None


@pytest.fixture
def three_runs(monkeypatch):
    """Three runs registered, as a worker would hold them."""
    runs = {f"openscript_s{n}": FakeProcess(1000 + n) for n in (1, 2, 3)}
    monkeypatch.setattr(
        service,
        "RUNNING_RUNS",
        {
            run_id: {"process": held, "pid": held.pid, "script": f"s{n}.oscript"}
            for n, (run_id, held) in enumerate(runs.items(), start=1)
        },
    )
    monkeypatch.setattr(service, "STOPPING_RUNS", set())
    return runs


def test_a_second_ctrl_c_still_stops_every_remaining_run(three_runs, monkeypatch):
    """THE DEFECT. One interrupted stop must not abandon the runs behind it.

    A run left behind keeps polling and placing orders with the platform gone.
    Catching ``Exception`` rather than ``BaseException`` in the loop is enough to
    produce it, and nothing on screen says it happened.
    """
    asked = []

    def stop_run(run_id, forget=True):
        asked.append(run_id)
        # The second child is the one being waited on when the impatient
        # keypress arrives, which is how the signal handler's exit gets in here.
        if len(asked) == 2:
            raise SystemExit(130)
        return True, "stopped"

    monkeypatch.setattr(service, "stop_run", stop_run)

    with pytest.raises(SystemExit):
        service.stop_every_run()

    assert len(asked) == 3, "the runs after the interrupted one were abandoned"


def test_the_exit_is_honoured_once_the_children_are_dealt_with(three_runs, monkeypatch):
    """Catches the interrupt being swallowed.

    Finishing the loop is the safety-critical half; it is not licence to ignore
    what the operator asked for. A direct caller must still exit, and with the
    code it was given.
    """

    def stop_run(run_id, forget=True):
        raise SystemExit(130)

    monkeypatch.setattr(service, "stop_run", stop_run)

    with pytest.raises(SystemExit) as left:
        service.stop_every_run()

    assert left.value.code == 130


def test_a_keyboard_interrupt_is_handled_the_same_way(three_runs, monkeypatch):
    """Catches a guard written for ``SystemExit`` alone.

    A signal arriving where no handler is installed, or on a thread, raises
    ``KeyboardInterrupt`` instead. It is not an ``Exception`` either, so it
    abandons the remaining runs in exactly the same way.
    """
    asked = []

    def stop_run(run_id, forget=True):
        asked.append(run_id)
        if len(asked) == 1:
            raise KeyboardInterrupt
        return True, "stopped"

    monkeypatch.setattr(service, "stop_run", stop_run)

    with pytest.raises(KeyboardInterrupt):
        service.stop_every_run()

    assert len(asked) == 3


def test_an_ordinary_failure_still_only_costs_that_one_run(three_runs, monkeypatch):
    """The behaviour that was already right, kept.

    One child that cannot be stopped must not stop the others being stopped, and
    must not turn an exit into a failure.
    """

    def stop_run(run_id, forget=True):
        if run_id.endswith("s2"):
            raise OSError("no such process")
        return True, "stopped"

    monkeypatch.setattr(service, "stop_run", stop_run)

    stopped = service.stop_every_run()

    assert len(stopped) == 2


def test_nothing_running_is_not_an_error(monkeypatch):
    monkeypatch.setattr(service, "RUNNING_RUNS", {})
    monkeypatch.setattr(service, "STOPPING_RUNS", set())

    assert service.stop_every_run() == []


# ---------------------------------------------------------------------------
# The signal handler that fires the exit into the callback
# ---------------------------------------------------------------------------


def test_a_repeat_signal_does_not_raise_into_the_teardown(monkeypatch):
    """THE CAUSE.

    The first signal tears down and exits. By the time a second arrives the
    interpreter is running its ``atexit`` callbacks, one of which is stopping
    child strategies. Raising again puts ``SystemExit`` inside that work, which
    is what produced ``Exception ignored in atexit callback`` and, before the fix
    above, abandoned the remaining runs.
    """
    from utils import shutdown

    monkeypatch.setattr(shutdown, "_shutdown_done", True)
    ran = []
    monkeypatch.setattr(shutdown, "shutdown_runtime", lambda: ran.append(1))

    # Must simply return. Anything raised here lands in whatever is winding down.
    assert shutdown._handle_signal(2, None) is None
    assert ran == [], "the teardown was run a second time"


def test_the_first_signal_still_tears_down_and_exits(monkeypatch):
    """Catches the guard being applied to every signal.

    A handler that never exits leaves the process alive holding the database the
    next start needs, which is the failure that module exists to prevent.
    """
    from utils import shutdown

    monkeypatch.setattr(shutdown, "_shutdown_done", False)
    ran = []
    monkeypatch.setattr(shutdown, "shutdown_runtime", lambda: ran.append(1))

    with pytest.raises(SystemExit) as left:
        shutdown._handle_signal(2, None)

    assert ran == [1]
    assert left.value.code == 130


# ---------------------------------------------------------------------------
# The way out of the interpreter
# ---------------------------------------------------------------------------


def test_the_exit_path_prints_nothing_alarming(three_runs, monkeypatch):
    """Catches the interrupt being re-raised out of an atexit callback.

    By then the exit code is already set by the first signal, so re-raising can
    only print "Exception ignored in atexit callback". An operator reads that as
    a crash during shutdown, and it hides the line that says what actually
    happened. The children have been dealt with before this point either way.
    """
    asked = []

    def stop_run(run_id, forget=True):
        asked.append(run_id)
        if len(asked) == 1:
            raise SystemExit(130)
        return True, "stopped"

    monkeypatch.setattr(service, "stop_run", stop_run)

    # Must not raise. This is what atexit calls.
    service._stop_every_run_at_exit()

    assert len(asked) == 3, "the runs after the interrupted one were abandoned"


def test_the_exit_path_still_swallows_an_ordinary_failure(three_runs, monkeypatch):
    def stop_run(run_id, forget=True):
        raise OSError("gone")

    monkeypatch.setattr(service, "stop_run", stop_run)

    service._stop_every_run_at_exit()


def test_the_registered_callback_is_the_one_that_swallows():
    """Catches the raising form being registered instead.

    The two differ only in the last step, so registering the wrong one is a
    one-word mistake that brings the confusing message straight back and, worse,
    reads as though it were deliberate.

    Checked against the source because the interpreter offers no way to ask what
    is registered: ``atexit`` has no public listing and unregistering to look
    would remove the very callback under test. A source check is the honest
    shape here, and it is exactly as strong as the mistake it is for.
    """
    import inspect

    source = inspect.getsource(service)

    assert "atexit.register(_stop_every_run_at_exit)" in source
    assert "atexit.register(stop_every_run)" not in source
