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

**The same gap left every scheduler running.** A process on its way out still
holds six APScheduler instances: the strategy module's, Flow's, Historify's,
Chartink's, the Python strategy host's and the sandbox square-off. Each runs on
a daemon thread, so the interpreter does not wait for it and it keeps firing
while the interpreter tears itself down. The thread pools those jobs submit to
are closed first, by the exit hook ``concurrent.futures`` installs, so every
tick from then on raises ``RuntimeError: cannot schedule new futures after
shutdown`` and logs a traceback. The strategy module reconciles pending stops
every five seconds, so it is the one that fills the console. Stopping them here
ends that, and it also stops a job from binding one more session after the
sweep below has run.

**And the proxy thread is what made Ctrl+C hang.** On the dev server the
websocket proxy runs on a real OS thread inside this process. It was created
non-daemon with its cleanup registered through ``atexit``, and those two cannot
both work: ``atexit`` runs only once the interpreter has joined every
non-daemon thread, so the cleanup that releases the proxy thread was queued
behind the wait for it. What used to break the tie was the proxy module's own
SIGINT handler, which cleaned up and called ``os._exit(0)``. This module
registers its handler later in ``app.py`` and replaced it, so Ctrl+C stopped
reaching that cleanup and the server stopped exiting at all. Stopping the proxy
here restores it, at a point where the rest of the teardown still runs.

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


def _imported(name: str):
    """The module under ``name`` if it is already imported, else ``None``.

    Looked up in ``sys.modules`` rather than imported. A module nothing has
    loaded owns no running scheduler, so there is nothing for these steps to
    stop, and importing one here to find that out is how a teardown starts the
    very thing it means to stop: importing ``blueprints.chartink`` calls
    ``scheduler.start()`` at module scope.
    """
    return sys.modules.get(name)


def _stop_strategy_module() -> None:
    """Stop strategy checkpointing, its scheduler and the risk price feed."""
    module = _imported("services.strategy_module.runtime")
    if module is not None:
        module.stop_strategy_module()


def _stop_flow_scheduler() -> None:
    """Stop the Flow workflow scheduler."""
    module = _imported("services.flow_scheduler_service")
    if module is not None:
        module.get_flow_scheduler().shutdown()


def _stop_historify_scheduler() -> None:
    """Stop the Historify download scheduler."""
    module = _imported("services.historify_scheduler_service")
    if module is not None:
        module.get_historify_scheduler().shutdown()


def _stop_chartink_scheduler() -> None:
    """Stop the Chartink time-based control scheduler."""
    module = _imported("blueprints.chartink")
    if module is not None and module.scheduler.running:
        module.scheduler.shutdown(wait=False)


def _stop_python_strategy_scheduler() -> None:
    """Stop the Python strategy host scheduler.

    Its ``atexit`` hook stops the strategy subprocesses, not the scheduler that
    starts them, and ``atexit`` runs after the interpreter has already joined
    threads. This is the earlier point.
    """
    module = _imported("blueprints.python_strategy")
    scheduler = getattr(module, "SCHEDULER", None) if module is not None else None
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)


def _stop_squareoff_scheduler() -> None:
    """Stop the sandbox square-off scheduler, without waiting on a job."""
    module = _imported("sandbox.squareoff_thread")
    if module is not None:
        module.stop_squareoff_scheduler(wait=False)


def _stop_websocket_proxy() -> None:
    """Stop the in-process websocket proxy and join its thread.

    The dev server runs the proxy on a real OS thread. Its cleanup clears the
    running flag, which the proxy polls twice a second, then closes the server
    handle and the ZeroMQ socket and joins.

    This is the step that ends the hang. The proxy keeps serving while the
    interpreter tears down, and until something clears that flag the thread
    has no reason to return.
    """
    module = _imported("websocket_proxy.app_integration")
    if module is not None:
        module.cleanup_websocket_server()


def shutdown_runtime() -> None:
    """Stop background writers and release this thread's sessions.

    Ordered, and the order is the point: ``collect_metrics`` removes its own
    session in a ``finally``, so the collector is only safe to leave once it has
    stopped. Sweeping sessions first would let one more sample start in between,
    which is exactly the write that would still be in flight at exit.

    The schedulers sit between the two for the same reason. A job that fires
    after the sweep runs outside any Flask app context, so nothing unbinds what
    it binds, and the session it opens is still open when the process goes.

    Among the schedulers the order is by what a step can cost. Five of them
    stop without waiting for anything, so they are unconditionally quick and
    run first. The strategy module follows, because its teardown joins two
    threads and unsubscribes a websocket, and a step that can be slow must
    never be the reason a quick one behind it did not get to run. Nothing
    here waits on a job in flight: a signal handler that blocks leaves the
    process alive, and a live process is the only thing that can still be
    holding a database (issue #2031).

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

    for step in (
        _stop_health_collector,
        _stop_flow_scheduler,
        _stop_historify_scheduler,
        _stop_chartink_scheduler,
        _stop_python_strategy_scheduler,
        _stop_squareoff_scheduler,
        _stop_strategy_module,
        _stop_websocket_proxy,
        _remove_all_scoped_sessions,
    ):
        try:
            step()
        except Exception:
            # Logged rather than swallowed: a teardown that quietly does nothing
            # is indistinguishable from the orphan this is meant to stop.
            logger.exception(f"Shutdown step {step.__name__} failed; continuing teardown")


def _handle_signal(signum, _frame):
    """Tear down, then exit with the code a shell expects from a signal.

    **A second signal is not a second shutdown, and must not raise.** Once the
    first has run, the interpreter is already on its way out and its ``atexit``
    callbacks are running: one of them stops the child processes that place
    orders, and it waits several seconds per child for each to finish the bar it
    is on. Raising ``SystemExit`` here again lands it inside whichever callback
    is in flight, and the operator sees it as ``Exception ignored in atexit
    callback``.

    The keypress that does it is the ordinary one. A shutdown that pauses looks
    stuck, so somebody presses Ctrl+C again, and the thing that pause is buying
    is the orderly stop of a live strategy.

    So a later signal says what is already happening and returns. There is
    deliberately no third-strike force exit: the only way to make this process
    leave faster than its children is to abandon them, which is the outcome this
    whole path exists to prevent. An operator who truly wants that can kill the
    process from outside, which is a decision rather than a repeated keystroke.
    """
    if _shutdown_done:
        logger.info(
            f"Received signal {signum} while already shutting down; "
            "waiting for running strategies to stop"
        )
        return

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
