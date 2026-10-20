"""gunicorn hooks for OpenAlgo's launcher (``install/openalgo-gunicorn.sh -c``).

Passing this file with ``-c`` also means gunicorn never auto-loads a stray
``gunicorn.conf.py`` from the working folder. It defines no settings: the
launcher passes every option on the command line.

**Imports.** gunicorn executes this file in the arbiter before it loads the
worker class, and loading the eventlet worker monkey-patches the process. So
this file imports nothing at module scope, and each hook imports what it
needs when it runs, inside the worker, after the app loaded.

**What the hooks do.**

* ``post_worker_init`` records the worker in ``utils.runtime`` so the app can
  report the real web server and thread budget, then adds the drain to the
  worker's stop signal (see below).
* ``worker_int`` and ``worker_exit`` run ``utils.shutdown.shutdown_runtime()``,
  which stops the schedulers, the strategy module and the market data proxy
  in order. The interpreter's ``atexit`` handlers are only a backstop: a
  gthread worker never reaches them while a request thread is still streaming.

**The drain.** On SIGTERM gunicorn stops accepting connections and waits for
the open ones to finish, up to ``--graceful-timeout``. Under gthread every
open connection that has not finished holds that wait: a Socket.IO long-poll
until its next ping, an idle keep-alive connection until ``--keep-alive``
expires. So when the worker is told to stop, the wrapper also calls
``utils.shutdown.begin_drain()`` (streams end), expires idle keep-alive
connections, and closes the Engine.IO sessions so their long-polls return at
once. Browsers reconnect by themselves once the server is back.

The drain runs after the SIGTERM handler that is in place when the worker has
loaded the app, which is called first and unchanged. If that handler ends the
process by itself (the market data proxy's does when it runs inside the
worker), the drain never runs and the stop is what it was before.

**Nothing here may fail a worker.** Every hook body is wrapped, and anything
unexpected is logged through gunicorn's own logger and ignored.
"""


def _log(owner, level, message):
    """Log through gunicorn's logger, never raising."""
    try:
        getattr(owner.log, level)(message)
    except Exception:
        pass


def post_worker_init(worker):
    """Record the worker for diagnostics and add the drain to its stop signal."""
    try:
        from utils import runtime

        runtime.register_gunicorn_worker(worker)
    except Exception as error:
        _log(worker, "warning", f"OpenAlgo could not record the web server details: {error}")
    try:
        _install_drain(worker)
    except Exception as error:
        _log(worker, "warning", f"OpenAlgo could not add the stop drain: {error}")


def worker_int(worker):
    """SIGINT or SIGQUIT reached the worker: stop OpenAlgo's background work."""
    _shutdown_runtime(worker)


def worker_exit(server, worker):
    """The worker is exiting: stop OpenAlgo's background work."""
    _shutdown_runtime(worker)


def _shutdown_runtime(worker):
    """Run utils.shutdown.shutdown_runtime() once the app has been loaded."""
    if getattr(worker, "wsgi", None) is None:
        return
    try:
        from utils.shutdown import shutdown_runtime

        shutdown_runtime()
    except Exception as error:
        _log(worker, "warning", f"OpenAlgo shutdown steps did not complete: {error}")


def _install_drain(worker):
    """Run the drain after whatever SIGTERM handler the worker has.

    The handler in place is called first and unchanged: gunicorn's own, or one
    the app chained in front of it while loading (the ngrok cleanup does, and
    then calls gunicorn's). If that handler ends the process itself, as the
    market data proxy's does when it runs inside the worker, the drain never
    runs and the stop is exactly what it was before.
    """
    import signal

    current = signal.getsignal(signal.SIGTERM)
    if not callable(current):
        return

    # Resolved now, in normal context, so the signal handler does no imports.
    try:
        from utils.shutdown import begin_drain
    except Exception:
        begin_drain = None

    def _on_term(sig, frame):
        current(sig, frame)
        if begin_drain is not None:
            try:
                begin_drain()
            except Exception:
                pass
        _schedule_connection_drain(worker)

    signal.signal(signal.SIGTERM, _on_term)
    if hasattr(signal, "siginterrupt"):
        signal.siginterrupt(signal.SIGTERM, False)


def _schedule_connection_drain(worker):
    """Ask the gthread worker's main loop to drain connections.

    Called from the signal handler, so it only queues work: gthread's method
    queue is what gunicorn itself uses from its own handler. Other worker
    classes have no such queue, and need nothing more.
    """
    queue = getattr(worker, "method_queue", None)
    defer = getattr(queue, "defer", None)
    if defer is None:
        return
    try:
        defer(_drain_connections, worker)
    except Exception:
        pass


def _drain_connections(worker):
    """Runs on the gthread main loop once the worker has been told to stop."""
    _begin_early_shutdown(worker)

    # Idle keep-alive and not-yet-readable connections: give them an expiry in
    # the past, so the shutdown loop closes them now instead of after
    # --keep-alive seconds.
    for name in ("keepalived_conns", "pending_conns"):
        try:
            for conn in list(getattr(worker, name, None) or ()):
                conn.timeout = 0
        except Exception:
            pass

    sessions = _engineio_sessions(worker)
    if not sessions:
        return
    try:
        import threading

        threading.Thread(
            target=_close_sessions,
            args=(worker, sessions),
            name="openalgo-drain-socketio",
            daemon=True,
        ).start()
    except Exception as error:
        _log(worker, "warning", f"OpenAlgo could not close browser sessions at stop: {error}")


def _begin_early_shutdown(worker):
    """Start stopping strategies now, beside the open requests.

    gunicorn gives a stopping worker one graceful window: it waits for open
    requests and only then runs ``worker_exit``, and it kills the worker when
    the window ends. Stopping the Python strategies and OpenScript runs only
    from ``worker_exit`` left them whatever the requests had not used, which
    after a slow request could be nothing. gthread only; ``worker_exit`` still
    waits for them.
    """
    try:
        from utils import runtime
        from utils.shutdown import begin_early_shutdown

        if runtime.gthread_active():
            begin_early_shutdown()
    except Exception as error:
        _log(worker, "warning", f"OpenAlgo could not start stopping strategies early: {error}")


def _engineio_sessions(worker):
    """Return the open Engine.IO sessions of the app this worker serves."""
    try:
        extensions = getattr(worker.wsgi, "extensions", None) or {}
        sockets = extensions["socketio"].server.eio.sockets
    except Exception:
        return []
    for _attempt in range(3):
        try:
            return list(sockets.values())
        except RuntimeError:
            continue
    return []


def _close_sessions(worker, sessions):
    """Close each Engine.IO session so its long-poll returns and frees a thread."""
    closed = 0
    for session in sessions:
        try:
            session.close(wait=False)
            closed += 1
        except Exception:
            pass
    if closed:
        _log(worker, "info", f"Closed {closed} browser session(s) so the stop can finish.")
