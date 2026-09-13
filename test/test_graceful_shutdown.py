"""Ctrl+C on the dev server must tear down in order before the process exits.

Reported as issue #2031: on Windows, stopping ``uv run app.py`` and starting it
again immediately fails with "database is locked" on ``health.db``, and repeated
attempts leave orphaned Python processes behind.

The lock itself is a red herring. A SQLite lock is an OS file lock and the
kernel drops it when the process dies, so a *dead* process cannot hold one. The
only thing that can still be holding ``health.db`` is an old instance that is
**still alive**, and the health collector writes to it every
``HEALTH_SAMPLE_INTERVAL`` seconds (10 by default) for as long as it runs. Each
orphan is therefore a permanent writer competing with the new instance.

So the fix is not to wait longer for the lock. ``database/__init__.py`` already
waits, cooperatively, for ``LOCK_RETRY_BUDGET_S`` (15s) and
``test_sqlite_lock_cooperative.py`` pins the reason it must not be done with
``PRAGMA busy_timeout``. The fix is to stop the writer and let the process go.

These tests drive ``shutdown_runtime`` directly rather than raising signals: the
handler is one line, the ordering it guards is the part that can regress, and a
test that raises SIGINT into the pytest process is a test that can take the
runner down with it.

The same gap left six APScheduler instances running. Each is on a daemon thread,
so the interpreter does not wait for it, and it keeps firing while the process
tears down, into thread pools ``concurrent.futures`` has already closed. Every
tick from then on raises ``cannot schedule new futures after shutdown``. The
strategy module reconciles pending stops every five seconds, so it is the one
that fills the console. They are writers as much as the collector is, and the
tests below pin that they stop, that they stop in an order where a slow step
cannot strand a quick one, and that not one of them waits on a job in flight.
"""

import inspect
import sys
import threading
import time

import pytest

from utils import shutdown as shutdown_mod

#: Every teardown step, in the order shutdown_runtime runs them.
#
# The collector first, for the reason issue #2031 turns on. Then the five
# schedulers that stop without waiting for anything. Then the strategy module,
# whose teardown joins two threads and unsubscribes a websocket, because a step
# that can be slow must not be the reason a quick one behind it never ran, and
# the websocket proxy after them because its cleanup joins a thread. Then the
# session sweep, last, because everything above can bind one.
_STEP_NAMES = (
    "_stop_health_collector",
    "_stop_flow_scheduler",
    "_stop_historify_scheduler",
    "_stop_chartink_scheduler",
    "_stop_python_strategy_scheduler",
    "_stop_squareoff_scheduler",
    "_stop_strategy_module",
    "_stop_websocket_proxy",
    "_remove_all_scoped_sessions",
)

#: Captured before any fixture can replace them, so a test can run the real
#: step while the autouse stub keeps the rest of the suite off the schedulers.
_REAL = {name: getattr(shutdown_mod, name) for name in _STEP_NAMES}


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test starts with the guard cleared."""
    shutdown_mod._shutdown_done = False
    yield
    shutdown_mod._shutdown_done = False


@pytest.fixture(autouse=True)
def _no_real_schedulers(monkeypatch):
    """Keep the suite away from schedulers it did not start.

    The scheduler steps look the process up in ``sys.modules``, and a full
    pytest run imports most of this repository, so without this a test about
    ordering would really shut down the Chartink scheduler that importing
    ``blueprints.chartink`` starts. A test that wants a real step restores it
    from ``_REAL``; a later ``monkeypatch.setattr`` wins over this one.
    """
    for name in _STEP_NAMES:
        if name != "_remove_all_scoped_sessions":
            monkeypatch.setattr(shutdown_mod, name, lambda: None)


def test_the_collector_is_stopped_before_sessions_are_released(monkeypatch):
    """Order matters: a running collector re-opens a session after the sweep.

    ``collect_metrics`` removes its own session in a ``finally``, so the loop is
    only safe to leave once it has actually stopped. Releasing sessions first
    and stopping the thread after would let one more sample land in between,
    which is precisely the write that would still be in flight at exit.
    """
    calls = []
    monkeypatch.setattr(shutdown_mod, "_stop_health_collector", lambda: calls.append("stop"))
    monkeypatch.setattr(
        shutdown_mod, "_remove_all_scoped_sessions", lambda: calls.append("sessions")
    )

    shutdown_mod.shutdown_runtime()

    assert calls == ["stop", "sessions"]


def test_shutdown_runs_once_however_many_signals_arrive(monkeypatch):
    """Ctrl+C twice, or SIGINT racing SIGTERM, must not tear down twice.

    The second pass would call ``join`` on a thread that has already gone and
    sweep sessions that are already released. Harmless in isolation, but it also
    means a user hammering Ctrl+C cannot stall the exit it is trying to cause.
    """
    calls = []
    monkeypatch.setattr(shutdown_mod, "_stop_health_collector", lambda: calls.append("stop"))
    monkeypatch.setattr(
        shutdown_mod, "_remove_all_scoped_sessions", lambda: calls.append("sessions")
    )

    shutdown_mod.shutdown_runtime()
    shutdown_mod.shutdown_runtime()
    shutdown_mod.shutdown_runtime()

    assert calls == ["stop", "sessions"]


def test_a_failing_step_cannot_stop_the_process_exiting(monkeypatch):
    """Teardown is best effort. Refusing to exit is worse than exiting dirty.

    If this raised, the handler would propagate out of a signal handler and the
    process would stay up holding the very file the next start needs, which is
    the bug this module exists to prevent.
    """
    calls = []

    def _boom():
        calls.append("stop")
        raise RuntimeError("collector thread is wedged")

    monkeypatch.setattr(shutdown_mod, "_stop_health_collector", _boom)
    monkeypatch.setattr(
        shutdown_mod, "_remove_all_scoped_sessions", lambda: calls.append("sessions")
    )

    shutdown_mod.shutdown_runtime()

    # The later step still ran even though the earlier one blew up.
    assert calls == ["stop", "sessions"]


def test_teardown_continues_when_a_module_was_never_imported(monkeypatch):
    """A disabled health monitor must not turn Ctrl+C into a traceback.

    ``HEALTH_MONITOR_ENABLED=false`` is a supported configuration, and the
    import is done lazily inside the call, so an ImportError here is a real
    possibility rather than a theoretical one.
    """
    calls = []

    def _import_error():
        raise ImportError("no health monitor in this build")

    monkeypatch.setattr(shutdown_mod, "_stop_health_collector", _import_error)
    monkeypatch.setattr(
        shutdown_mod, "_remove_all_scoped_sessions", lambda: calls.append("sessions")
    )

    shutdown_mod.shutdown_runtime()

    assert calls == ["sessions"]


def test_a_signal_arriving_mid_teardown_does_not_deadlock(monkeypatch):
    """A second Ctrl+C while teardown is running must return, not block.

    The flag is set before the steps run, so re-entry is a fast return rather
    than a second teardown or a wait.

    Note this passes with a ``threading.Lock`` guard too, as long as the
    critical section covers only the flag and not the steps. It is kept because
    it pins the property that matters at the call site, not because it
    discriminates between those two implementations: a signal handler that can
    block on a shutdown already in progress is the "it will not stop" symptom
    issue #2031 reports, and this is the test that would catch someone widening
    that critical section to wrap the teardown.
    """
    calls = []

    def _reentrant_stop():
        calls.append("stop")
        # The nested call stands in for SIGINT landing during teardown.
        shutdown_mod.shutdown_runtime()
        calls.append("stop-returned")

    monkeypatch.setattr(shutdown_mod, "_stop_health_collector", _reentrant_stop)
    monkeypatch.setattr(
        shutdown_mod, "_remove_all_scoped_sessions", lambda: calls.append("sessions")
    )

    shutdown_mod.shutdown_runtime()

    # The nested call returned immediately instead of blocking, and teardown
    # still completed exactly once.
    assert calls == ["stop", "stop-returned", "sessions"]


def test_the_handler_exits_with_the_conventional_code(monkeypatch):
    """128 + signal number is what a shell expects from a signalled process."""
    monkeypatch.setattr(shutdown_mod, "_stop_health_collector", lambda: None)
    monkeypatch.setattr(shutdown_mod, "_remove_all_scoped_sessions", lambda: None)

    import signal

    with pytest.raises(SystemExit) as exc:
        shutdown_mod._handle_signal(signal.SIGINT, None)

    assert exc.value.code == 128 + int(signal.SIGINT)


def test_every_background_writer_is_stopped_before_sessions_are_released(monkeypatch):
    """All nine steps run, in the order the module documents.

    Pinned as an exact sequence rather than a set. Which steps run is the easy
    half; the half that regresses is where a new one gets inserted, and every
    position in this list is load bearing.
    """
    calls = []
    for name in _STEP_NAMES:
        monkeypatch.setattr(shutdown_mod, name, lambda n=name: calls.append(n))

    shutdown_mod.shutdown_runtime()

    assert calls == list(_STEP_NAMES)


def test_the_strategy_scheduler_is_told_to_stop(monkeypatch):
    """The reported symptom, and the step that ends it.

    Pending-stop reconciliation fires every five seconds. Left running it
    submits into a closed pool and logs a traceback a tick for as long as the
    process takes to go. ``stop_strategy_module`` existed the whole time and
    nothing called it.
    """
    stopped = []

    class _Runtime:
        @staticmethod
        def stop_strategy_module():
            stopped.append("strategy")

    monkeypatch.setitem(sys.modules, "services.strategy_module.runtime", _Runtime)
    monkeypatch.setattr(shutdown_mod, "_stop_strategy_module", _REAL["_stop_strategy_module"])
    monkeypatch.setattr(shutdown_mod, "_remove_all_scoped_sessions", lambda: None)

    shutdown_mod.shutdown_runtime()

    assert stopped == ["strategy"]


def test_no_teardown_step_waits_on_a_job_already_running(monkeypatch):
    """A signal handler that blocks is how a stopped process stays alive.

    And a live process is the only thing that can still be holding a database,
    which is the whole of issue #2031. The square-off scheduler is the one whose
    own entry point waits by default, so it is the one that has to opt out.
    """
    seen = {}

    class _Squareoff:
        @staticmethod
        def stop_squareoff_scheduler(wait=True):
            seen["wait"] = wait

    monkeypatch.setitem(sys.modules, "sandbox.squareoff_thread", _Squareoff)

    _REAL["_stop_squareoff_scheduler"]()

    assert seen == {"wait": False}


def test_an_operator_stopping_the_engine_still_waits():
    """Only the signal path declines the wait.

    An operator leaving analyze mode is not racing an exit, and the job in
    flight is closing sandbox positions, so that caller should still wait. The
    parameter exists solely to keep the two callers apart.
    """
    from sandbox.squareoff_thread import stop_squareoff_scheduler

    signature = inspect.signature(stop_squareoff_scheduler)
    assert signature.parameters["wait"].default is True


def test_a_scheduler_module_nothing_imported_is_not_imported_to_stop_it(monkeypatch):
    """Importing ``blueprints.chartink`` starts a scheduler at module scope.

    So a teardown that imports it to ask whether it is running would start, on
    the way out, the very thing it is there to stop.
    """
    monkeypatch.delitem(sys.modules, "blueprints.chartink", raising=False)

    _REAL["_stop_chartink_scheduler"]()

    assert "blueprints.chartink" not in sys.modules


def test_the_websocket_proxy_is_stopped_before_the_interpreter_joins_threads(monkeypatch):
    """The step that ends the hang.

    The dev server runs the proxy on a real OS thread, and until something
    clears its running flag the thread has no reason to return. Its cleanup was
    reachable only through ``atexit``, which runs after the interpreter has
    joined non-daemon threads, and through the proxy's own SIGINT handler,
    which this module's handler is registered later than and replaced.
    """
    cleaned = []

    class _Integration:
        @staticmethod
        def cleanup_websocket_server():
            cleaned.append("proxy")

    monkeypatch.setitem(sys.modules, "websocket_proxy.app_integration", _Integration)

    _REAL["_stop_websocket_proxy"]()

    assert cleaned == ["proxy"]


def test_the_proxy_thread_is_not_what_the_interpreter_waits_on():
    """A non-daemon proxy thread plus atexit cleanup is a deadlock by build.

    ``atexit`` runs only once every non-daemon thread has been joined, so the
    cleanup that releases the proxy thread sat behind the wait for that thread.
    Pinned on the source because the property lives in a thread constructor no
    unit test can reach without binding a real websocket port.
    """
    from websocket_proxy import app_integration

    source = inspect.getsource(app_integration.start_websocket_server)
    assert "daemon=True" in source
    assert "daemon=False" not in source


def test_the_health_collector_notices_a_stop_without_waiting_out_its_interval():
    """The collector slept a whole sampling interval in one call.

    ``stop_health_collector`` clears the flag and joins for five seconds, and a
    ``time.sleep`` already running cannot see the flag. With the default ten
    second interval the join therefore timed out every time, and Ctrl+C paid
    five seconds before the rest of the teardown had even begun. Sliced, the
    flag lands within a tenth of a second.
    """
    from utils import health_monitor

    elapsed = []

    def _sleeper():
        started = time.perf_counter()
        health_monitor._sleep(10.0)
        elapsed.append(time.perf_counter() - started)

    health_monitor._collector_running = True
    try:
        thread = threading.Thread(target=_sleeper, daemon=True)
        thread.start()
        time.sleep(0.3)
        health_monitor._collector_running = False
        thread.join(timeout=5.0)
    finally:
        health_monitor._collector_running = False

    assert elapsed, "the sleep never returned"
    assert elapsed[0] < 2.0, f"took {elapsed[0]:.2f}s to notice the stop"


def test_installing_handlers_is_idempotent(monkeypatch):
    """The reloader can import this module twice; handlers must not stack."""
    registered = []

    def _fake_signal(signum, handler):
        registered.append(signum)
        return None

    monkeypatch.setattr(shutdown_mod.signal, "signal", _fake_signal)
    monkeypatch.setattr(shutdown_mod, "_handlers_installed", False)

    shutdown_mod.install_signal_handlers()
    first = list(registered)
    shutdown_mod.install_signal_handlers()

    assert registered == first, "second install should be a no-op"
    assert first, "at least SIGINT should have been registered"
