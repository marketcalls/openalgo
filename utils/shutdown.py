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

**The signal handlers are for the dev server only.** Under gunicorn the
``__main__`` block never runs; gunicorn manages worker lifecycle itself and
installs its own handlers, so :func:`install_signal_handlers` is never called
there.

**Under gunicorn the entry points are hooks, not signals.** The launcher's
gunicorn hooks call :func:`begin_drain` when the worker is told to stop (so
long-lived streams end inside the graceful window) and :func:`shutdown_runtime`
from ``worker_exit`` and ``worker_int``. ``atexit`` stays registered where it
was, as a backstop only: the gthread worker never reaches it while a pool
thread is still streaming.

Other modules add work to the teardown with :func:`register_shutdown_hook`.
An *early* hook (stopping running strategies, say) runs before the steps
below; a late one runs after them and before the session sweep. Each hook runs
within its own time budget, and all of them together within
``SHUTDOWN_BUDGET_S``, because a stop window has a hard end and a hook that
hangs must not be the reason the ones after it never ran.
"""

import signal
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from utils import real_threading, stream_registry
from utils.logging import get_logger

logger = get_logger(__name__)

#: Set once teardown has run. Ctrl+C twice, or SIGINT racing SIGTERM, must not
#: start a second sweep: the second pass would join a thread that has already
#: gone, and a user hammering Ctrl+C would be stalling the exit they are asking
#: for.
_shutdown_done = False

#: Guards the check-and-set of ``_shutdown_done`` only, never the steps. Taken
#: without blocking: a second caller (a gunicorn hook racing a signal, or a
#: signal landing mid-teardown) returns at once rather than waiting.
_shutdown_guard = real_threading.Lock()

#: Everything registered hooks may spend together, in seconds.
SHUTDOWN_BUDGET_S = 25.0


@dataclass(frozen=True)
class _Hook:
    fn: Callable[[], None]
    name: str
    budget_s: float
    early: bool


_hooks: list[_Hook] = []
_hooks_lock = threading.Lock()

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


def begin_drain() -> None:
    """Tell long-lived streams to end. Safe to call from a signal handler.

    One assignment: no lock, no I/O, no logging, nothing that can block or
    raise. Idempotent. The launcher's gunicorn hooks call it when the worker
    is asked to stop, so streams return inside the graceful window instead of
    holding their threads until the worker is killed.
    """
    stream_registry.request_drain()


def register_shutdown_hook(
    fn: Callable[[], None],
    *,
    name: str,
    budget_s: float = 20.0,
    early: bool = False,
) -> None:
    """Add ``fn`` to what :func:`shutdown_runtime` runs.

    Args:
        fn: Called with no arguments. It runs on a helper thread and is given
            up on (left running, daemon) when its budget runs out.
        name: Shown in the log if the hook fails or overruns.
        budget_s: Seconds the hook may take.
        early: Run before the built-in steps (stopping strategies, say)
            rather than after them.
    """
    with _hooks_lock:
        _hooks.append(_Hook(fn=fn, name=name, budget_s=float(budget_s), early=early))


def _registered_hooks(early: bool) -> list[_Hook]:
    with _hooks_lock:
        return [hook for hook in _hooks if hook.early is early]


def _run_hooks(hooks: list[_Hook], deadline: float) -> None:
    """Run each hook within its budget and within the overall deadline.

    A hook runs on a plain thread (green under eventlet) and is joined with a
    timeout, so one that hangs costs its budget and no more. Never raises.
    """
    for hook in hooks:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            logger.warning(f"Shutdown hook {hook.name} skipped: the shutdown time budget is spent")
            continue

        def _call(hook=hook):
            try:
                hook.fn()
            except Exception:
                logger.exception(f"Shutdown hook {hook.name} failed; continuing teardown")

        try:
            worker = threading.Thread(target=_call, name=f"shutdown-{hook.name}", daemon=True)
            worker.start()
            worker.join(min(hook.budget_s, remaining))
            if worker.is_alive():
                logger.warning(
                    f"Shutdown hook {hook.name} did not finish within its time "
                    "budget; continuing teardown without it"
                )
        except Exception:
            logger.exception(f"Shutdown hook {hook.name} could not be run; continuing teardown")


def _signal_streams_to_stop() -> None:
    """Set the stream stop event, so generators end rather than being cut off."""
    stream_registry.request_drain()
    stream_registry.STOP.set()


def _run_late_hooks(deadline: float) -> None:
    """Run the hooks registered without ``early``, before the session sweep."""
    _run_hooks(_registered_hooks(early=False), deadline)


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

    Idempotent and safe from any number of callers: the dev server's signal
    handler, and under gunicorn the ``worker_exit`` and ``worker_int`` hooks,
    which can race each other and a signal. The flag is checked and set under
    a lock taken without blocking, and the lock covers only that, never the
    steps: a signal handler that can block on a shutdown already in progress
    is the "it will not stop" symptom issue #2031 reports. The flag is set
    before the steps run, so a second Ctrl+C returns immediately instead of
    waiting on the first.

    Registered hooks run too: early ones first, late ones after the built-in
    steps and before the session sweep, all within ``SHUTDOWN_BUDGET_S``.
    """
    global _shutdown_done

    if not _shutdown_guard.acquire(blocking=False):
        return
    try:
        if _shutdown_done:
            return
        _shutdown_done = True
    finally:
        _shutdown_guard.release()

    deadline = time.monotonic() + SHUTDOWN_BUDGET_S

    try:
        _signal_streams_to_stop()
    except Exception:
        logger.exception("Could not signal streams to stop; continuing teardown")

    _run_hooks(_registered_hooks(early=True), deadline)

    def _late_hooks() -> None:
        _run_late_hooks(deadline)

    for step in (
        _stop_health_collector,
        _stop_flow_scheduler,
        _stop_historify_scheduler,
        _stop_chartink_scheduler,
        _stop_python_strategy_scheduler,
        _stop_squareoff_scheduler,
        _stop_strategy_module,
        _stop_websocket_proxy,
        _late_hooks,
        _remove_all_scoped_sessions,
    ):
        try:
            step()
        except Exception:
            # Logged rather than swallowed: a teardown that quietly does nothing
            # is indistinguishable from the orphan this is meant to stop.
            logger.exception(f"Shutdown step {step.__name__} failed; continuing teardown")


#: How often the drain watcher looks for a drain request, in seconds.
DRAIN_WATCH_SECONDS = 0.5

_drain_watcher_started = False


def close_socketio_sessions() -> int | None:
    """End every Socket.IO session, so the threads serving them return.

    Under the gthread worker each open Engine.IO session holds a worker thread
    for as long as it lives. A graceful stop waits for those threads, so one
    still held when the window closes turns the stop into a kill that skips the
    teardown. Browsers reconnect by themselves once the server is back.

    Each session is closed without waiting, as the launcher's own stop drain
    does. Engine.IO's ``disconnect()`` closes every session with ``wait=True``,
    which joins that session's queue; a polling session whose client is not
    reading (a tab asleep, or one that has already taken its close packet)
    never finishes it, so this thread would block on the first such session
    for good and never close the rest.

    Returns:
        How many sessions were closed, or None if the server could not be reached.
    """
    try:
        from extensions import socketio

        eio = socketio.server.eio
        sessions = []
        for _attempt in range(3):
            try:
                sessions = list(eio.sockets.values())
                break
            except RuntimeError:  # the dict changed size while being copied
                continue
    except Exception:
        logger.exception("Could not close browser connections for shutdown")
        return None
    closed = 0
    for session in sessions:
        try:
            session.close(wait=False)
            closed += 1
        except Exception:
            logger.debug("Could not close one browser connection for shutdown", exc_info=True)
    return closed


def _watch_for_drain() -> None:
    """Close Socket.IO sessions once a drain is requested. Runs on its own thread."""
    while not stream_registry.should_stop():
        time.sleep(DRAIN_WATCH_SECONDS)
    count = close_socketio_sessions()
    if count:
        logger.info(f"Shutting down: closed {count} browser connection(s)")


def start_drain_watcher() -> bool:
    """Under the gthread worker, close Socket.IO sessions when a drain begins.

    :func:`begin_drain` is one assignment, safe from a signal handler, so it
    cannot close sessions itself; this thread notices the request and does it
    while gunicorn's graceful window is still open. Idempotent. A no-op under
    eventlet, where a session costs a greenlet rather than a thread, and on the
    development server, where nothing drains.

    Returns:
        True when the watcher is running after the call.
    """
    global _drain_watcher_started

    from utils import runtime

    if not runtime.gthread_active():
        return False
    with _hooks_lock:
        if _drain_watcher_started:
            return True
        _drain_watcher_started = True
    threading.Thread(target=_watch_for_drain, name="drain-watcher", daemon=True).start()
    return True


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
