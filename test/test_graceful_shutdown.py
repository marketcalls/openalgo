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
"""

import pytest

from utils import shutdown as shutdown_mod


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test starts with the guard cleared."""
    shutdown_mod._shutdown_done = False
    yield
    shutdown_mod._shutdown_done = False


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
