"""Ordered teardown for the development server.

Issue #2031: on Windows, stopping ``uv run app.py`` with Ctrl+C and starting it
again immediately fails with "database is locked" on ``health.db``, and repeated
attempts leave orphaned Python processes competing for the same files.

**The lock is a symptom, not the cause.** A SQLite lock is an OS file lock and
the kernel releases it when the process dies, so a process that has actually
exited cannot still be holding ``health.db``. The only thing that can be holding
it is an old instance that is *still running*, and the health collector writes a
sample every ``HEALTH_SAMPLE_INTERVAL`` seconds (10 by default) for as long as
that instance lives. Every orphan is a permanent writer, which is why the
reporter saw each successive start fail more often than the last.

So this module does not try to wait longer for the lock. ``database/__init__``
already waits for it cooperatively, for ``LOCK_RETRY_BUDGET_S`` (15 seconds),
and deliberately does **not** use ``PRAGMA busy_timeout`` to do it: that wait is
served by C code that never yields, so under gunicorn+eventlet it freezes the
hub and the greenlet holding the lock can never be scheduled to release it. See
``test_sqlite_lock_cooperative.py``. Raising a busy timeout here would reinstate
a defect the project has already fixed, and would not help anyway, because the
connect listener sets ``busy_timeout`` on every connection after ``connect_args``
have been applied.

What is genuinely missing is an ordered stop. ``socketio.run()`` is the last
statement in ``app.py`` and nothing runs after it, so there is no point at which
the collector is told to stop. This module supplies that point.

**Production does not use this.** Under gunicorn the ``__main__`` block never
runs; gunicorn manages worker lifecycle itself and installs its own handlers.
This is for the dev server, which is what the issue is about.
"""

import signal
import sys

from utils.logging import get_logger

logger = get_logger(__name__)

#: Set once teardown has run. Ctrl+C twice, or SIGINT racing SIGTERM, must not
#: start a second sweep: the second pass would join a thread that has already
#: gone, and a user hammering Ctrl+C would be stalling the exit they are asking
#: for.
_shutdown_done = False

#: Guards against the reloader importing this twice and stacking handlers.
_handlers_installed = False


def _stop_health_collector() -> None:
    """Stop the background sampler. Imported lazily: see ``shutdown_runtime``."""
    from utils.health_monitor import stop_health_collector

    stop_health_collector()


def _remove_all_scoped_sessions() -> None:
    """Release this thread's scoped sessions."""
    from utils.db_sessions import remove_all_scoped_sessions

    remove_all_scoped_sessions()


def shutdown_runtime() -> None:
    """Stop background writers and release this thread's sessions.

    Ordered, and the order is the point: ``collect_metrics`` removes its own
    session in a ``finally``, so the collector is only safe to leave once it has
    stopped. Sweeping sessions first would let one more sample start in between,
    which is exactly the write that would still be in flight at exit.

    Never raises. This runs from a signal handler, and a teardown step that
    propagates would leave the process up holding the file the next start needs,
    which is the failure this module exists to prevent. Steps are therefore
    independent: one failing does not skip the rest.

    The imports are deliberately inside the call. ``HEALTH_MONITOR_ENABLED=false``
    is supported, and importing the health monitor at module scope would build
    the engine that a disabled monitor never wanted.

    Guarded by a plain flag rather than a lock. The only caller is the signal
    handler on the main thread and CPython runs those one at a time, so a lock
    would buy nothing here, and a lock on a signal path is a standing invitation
    to deadlock the moment someone widens its critical section to cover the
    steps below. The flag is set before the steps run, so a second Ctrl+C
    returns immediately instead of waiting on the first.
    """
    global _shutdown_done

    if _shutdown_done:
        return
    _shutdown_done = True

    for step in (_stop_health_collector, _remove_all_scoped_sessions):
        try:
            step()
        except Exception:
            # Logged rather than swallowed: a teardown that quietly does nothing
            # is indistinguishable from the orphan this is meant to stop.
            logger.exception(f"Shutdown step {step.__name__} failed; continuing teardown")


def _handle_signal(signum, _frame):
    """Tear down, then exit with the code a shell expects from a signal."""
    logger.info(f"Received signal {signum}, shutting down")
    shutdown_runtime()
    raise SystemExit(128 + int(signum))


def install_signal_handlers() -> None:
    """Install the handlers on the process that actually serves requests.

    Idempotent, and safe to call from a non-main thread, where ``signal.signal``
    raises ``ValueError``: the dev server is started from the main thread, but
    this must not be the thing that breaks an embedding that does not.

    On Windows, Ctrl+C delivers SIGINT and Ctrl+Break delivers SIGBREAK; SIGTERM
    exists but is not what a console sends, so all three are registered where the
    platform defines them.
    """
    global _handlers_installed

    if _handlers_installed:
        return
    _handlers_installed = True

    names = ["SIGINT", "SIGTERM"]
    if sys.platform == "win32":
        names.append("SIGBREAK")

    for name in names:
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            signal.signal(signum, _handle_signal)
        except (ValueError, OSError):
            # Not the main thread, or the platform refuses this signal. The
            # server still runs; it just exits the way it did before.
            logger.debug(f"Could not install a handler for {name}")
