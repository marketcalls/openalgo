"""Where the websocket proxy runs, and keeping it running.

The proxy (``websocket_proxy/server.py``) serves market data on
``WEBSOCKET_PORT`` and is the single binder of the ZeroMQ bus on ``ZMQ_PORT``.
Exactly one must run per installation, in one of three places, chosen by
:func:`resolve_proxy_mode`:

* ``subprocess``: a child process of the gunicorn worker, under either worker
  class. The child runs unpatched, so its asyncio loop and the broker adapters'
  threads never share an eventlet hub (issue #1421), and under gthread the
  proxy stays out of the process that places orders.
* ``thread``: a real OS thread inside the development server (``uv run
  app.py``), the long-standing local workflow.
* ``external``: somebody else runs it. Docker's ``start.sh`` starts
  ``python -m websocket_proxy.server`` itself.

The choice used to be inferred from whether eventlet was active, which under
the gthread worker would have moved the whole proxy into the trading worker.
Under eventlet the result is unchanged: gunicorn gives ``subprocess``, Docker
gives ``external``, the development server gives ``thread``.

Under the gthread worker only, the child is also supervised: if it exits
unexpectedly it is restarted once its ports are free, with backoff; and it
exits by itself if the worker that started it dies without cleaning up, so an
orphan cannot keep the ports. Under eventlet neither is done, as before.

**Signal handlers.** Under the gthread worker this module installs none. Its
handler replaces gunicorn's graceful SIGTERM handling with one that cleans up
and calls ``os._exit(0)``, which kills in-flight requests, an order whose
broker call was already sent among them; under gthread gunicorn drains, and
``atexit`` and the shutdown hooks (``utils/shutdown.py``) stop the child.
Under the eventlet worker the handler is installed exactly as before, because
an install that has not opted in must see no change, and a graceful eventlet
stop waits for every open browser long-poll (measured about 23 seconds with
one tab open, against an immediate exit). The development server's thread
mode keeps its handler.
"""

import asyncio
import atexit
import os
import platform
import signal
import subprocess
import sys
import threading
import time

from utils import runtime as _runtime
from utils.logging import get_logger, highlight_url

from .server import main as websocket_main

# The original threading module, to run the asyncio event loop in a real OS
# thread, bypassing eventlet's monkey-patching which turns threading.Thread
# into green threads where asyncio.new_event_loop() cannot work. Chosen by
# whether eventlet patched this process, never by whether it was imported.
_original_threading = _runtime.original("threading")


def _eventlet_active() -> bool:
    """True when eventlet has monkey-patched the stdlib (gunicorn worker).

    Asks utils.runtime, which never imports eventlet: importing it here merely
    to ask used to put it into sys.modules under the gthread worker, flipping
    every later "eventlet in sys.modules" check in the process.
    """
    return _runtime.is_monkey_patched("socket")


# Set the correct event loop policy for Windows to avoid ZeroMQ warnings
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Global flag to track if the WebSocket server has been started
# Used to prevent multiple instances in Flask debug mode
_websocket_server_started = False
_websocket_proxy_instance = None
_websocket_thread = None
_websocket_subprocess = None  # set when the proxy runs as a child process

logger = get_logger(__name__)

#: The internal override for the topology. Set by the launcher or start.sh,
#: never documented as a setting in .sample.env.
PROXY_MODE_ENV = "WEBSOCKET_PROXY_MODE"
PROXY_MODES = ("subprocess", "thread", "external")

#: Passed to the child so it can tell when the worker that started it is gone.
PARENT_PID_ENV = "OPENALGO_PROXY_PARENT_PID"

#: Supervisor timing. Module constants so tests can shorten them.
SUPERVISOR_POLL_SECONDS = 1.0
RESTART_BACKOFF_SECONDS = (1.0, 2.0, 5.0, 10.0, 30.0)
STABLE_UPTIME_SECONDS = 300.0
PORT_FREE_WAIT_SECONDS = 15.0
FAILURE_WINDOW_SECONDS = 600.0
FAILURES_BEFORE_SLOW_RETRY = 5
SLOW_RETRY_SECONDS = 60.0

#: How the child is started. A list so tests can substitute a stand-in.
SPAWN_COMMAND = [sys.executable, "-u", "-m", "websocket_proxy.server"]

# Supervisor state. A plain lock: only in-memory bookkeeping happens under it.
_state_lock = threading.Lock()
_stopping = False
_supervisor_thread = None
_resolved_mode = None
_restarts = 0
_last_exit_code = None
_last_restart_at = None
_unknown_mode_warned = False


def resolve_proxy_mode() -> str:
    """Decide where the websocket proxy runs in this process.

    Returns:
        ``"subprocess"``, ``"thread"`` or ``"external"``. A valid
        ``WEBSOCKET_PROXY_MODE`` wins. Otherwise Docker (``/.dockerenv`` or
        ``APP_MODE=standalone``) is ``external``, because start.sh runs the
        proxy; any gunicorn worker is ``subprocess``; anything else, the
        development server, is ``thread``.
    """
    global _unknown_mode_warned

    raw = os.environ.get(PROXY_MODE_ENV, "").strip().strip("'\"").lower()
    if raw in PROXY_MODES:
        return raw
    if raw and not _unknown_mode_warned:
        _unknown_mode_warned = True
        logger.warning(
            f"Ignoring {PROXY_MODE_ENV}={raw!r}: expected one of {', '.join(PROXY_MODES)}"
        )
    if (
        os.path.exists("/.dockerenv")
        or os.environ.get("APP_MODE", "").strip().strip("'\"") == "standalone"
    ):
        return "external"
    if _runtime.under_gunicorn():
        return "subprocess"
    return "thread"


def proxy_status() -> dict:
    """What the admin runtime report shows about the proxy.

    Returns:
        ``{"mode", "pid", "alive", "restarts", "last_exit_code",
        "last_restart_at"}``. ``pid`` and ``alive`` describe the child process
        in subprocess mode; in thread mode ``alive`` is the thread's.
    """
    mode = _resolved_mode or resolve_proxy_mode()
    proc = _websocket_subprocess
    pid = None
    alive = None
    if proc is not None:
        pid = proc.pid
        try:
            alive = proc.poll() is None
        except Exception:
            alive = None
    elif mode == "thread" and _websocket_thread is not None:
        alive = _websocket_thread.is_alive()
    with _state_lock:
        return {
            "mode": mode,
            "pid": pid,
            "alive": alive,
            "restarts": _restarts,
            "last_exit_code": _last_exit_code,
            "last_restart_at": _last_restart_at,
        }


# Check if we're in the Flask child process that should start the WebSocket server
def should_start_websocket():
    """
    Determine if the current process should start the WebSocket server

    In Flask debug mode with reloader enabled, we only want to start the
    WebSocket server in the child process, not the parent process that
    monitors for file changes.

    Returns:
        bool: True if we should start the WebSocket server, False otherwise
    """
    # In debug mode, only start in the Flask child process
    if os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true"):
        # WERKZEUG_RUN_MAIN is set to 'true' by Flask in the child process
        # that actually runs the application
        return os.environ.get("WERKZEUG_RUN_MAIN") == "true"

    # In non-debug mode, always start
    return True


def cleanup_websocket_server():
    """Clean up WebSocket server resources - cross-platform compatible"""
    global _websocket_proxy_instance, _websocket_thread

    # If we spawned the WS as a subprocess, there is no in-process thread or
    # proxy instance to clean up: stop the supervisor, then the child.
    if _websocket_subprocess is not None or _supervisor_thread is not None:
        _terminate_websocket_subprocess()
        return

    try:
        logger.info("Cleaning up WebSocket server...")

        if _websocket_proxy_instance:
            # For Windows compatibility, set a shutdown flag instead of trying to
            # manipulate the event loop from a different thread
            _websocket_proxy_instance.running = False

            # Try to close the server gracefully
            try:
                if (
                    hasattr(_websocket_proxy_instance, "server")
                    and _websocket_proxy_instance.server
                ):
                    try:
                        _websocket_proxy_instance.server.close()
                    except Exception as e:
                        logger.warning(f"Error closing server handle: {e}")

                # Close ZMQ resources immediately
                if (
                    hasattr(_websocket_proxy_instance, "socket")
                    and _websocket_proxy_instance.socket
                ):
                    try:
                        import zmq

                        _websocket_proxy_instance.socket.setsockopt(zmq.LINGER, 0)
                        _websocket_proxy_instance.socket.close()
                    except Exception as e:
                        logger.warning(f"Error closing ZMQ socket: {e}")

                if (
                    hasattr(_websocket_proxy_instance, "context")
                    and _websocket_proxy_instance.context
                ):
                    try:
                        _websocket_proxy_instance.context.term()
                    except Exception as e:
                        logger.warning(f"Error terminating ZMQ context: {e}")

            except Exception as e:
                logger.exception(f"Error during WebSocket cleanup: {e}")
            finally:
                _websocket_proxy_instance = None

        if _websocket_thread and _websocket_thread.is_alive():
            logger.info("Waiting for WebSocket thread to finish...")
            _websocket_thread.join(timeout=5.0)  # Increased timeout for slow broker disconnects
            if _websocket_thread.is_alive():
                logger.warning("WebSocket thread did not finish gracefully")
            _websocket_thread = None

        # Clean up shared ZMQ context (handles app restart without process exit)
        try:
            from .base_adapter import BaseBrokerWebSocketAdapter
            BaseBrokerWebSocketAdapter.cleanup_shared_context()
            logger.info("Shared ZMQ context cleaned up")
        except Exception as e:
            logger.warning(f"Error cleaning up shared ZMQ context: {e}")

        logger.info("WebSocket server cleanup completed")

    except Exception as e:
        logger.exception(f"Error during WebSocket cleanup: {e}")
        # Last resort: force cleanup
        _websocket_proxy_instance = None
        _websocket_thread = None


def signal_handler(signum, frame):
    """Handle SIGINT (Ctrl+C) and SIGTERM signals. Development server only."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    cleanup_websocket_server()
    # Use os._exit() for immediate termination across all platforms
    os._exit(0)


def _supervised() -> bool:
    """True when the child is supervised and watches its parent: gthread only.

    Under eventlet a crashed child has always stayed down until a restart, and
    an orphan left by a killed worker has kept serving; both are kept exactly
    as they were for installs that have not opted in to gthread.
    """
    return _runtime.gthread_active()


def _launch_child():
    """Start the proxy child process and return it, or None if it could not start."""
    # Find the openalgo project root (parent of websocket_proxy/)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = list(SPAWN_COMMAND)
    logger.debug(f"Spawning WebSocket subprocess: {' '.join(cmd)} (cwd={project_root})")

    env = None
    if _supervised():
        env = dict(os.environ)
        env[PARENT_PID_ENV] = str(os.getpid())

    try:
        # Inherit stdout/stderr so the child's logging lands in the same
        # systemd journal as gunicorn. The WS server already uses Python
        # logging via utils.logging, so file/json log handlers fire too.
        proc = subprocess.Popen(
            cmd,
            cwd=project_root,
            stdout=None,
            stderr=None,
            env=env,
            # Do NOT set start_new_session=True — staying in the gunicorn
            # cgroup means systemd reaps the child if gunicorn dies hard.
        )
    except Exception as e:
        logger.exception(f"Failed to spawn WebSocket subprocess: {e}")
        return None
    logger.debug(f"WebSocket subprocess started with PID {proc.pid}")
    return proc


def _spawn_websocket_subprocess():
    """
    Spawn the WebSocket proxy as a child *process* (not a thread).

    Required under gunicorn+eventlet: an in-process asyncio thread shares the
    process with the eventlet hub, and any eventlet-monkey-patched semaphore
    (stdlib logging RLock, socketio lock, broker adapter `threading.Lock`)
    touched from both threads triggers `greenlet.error: Cannot switch to a
    different thread` and silently corrupts WS state (GitHub issue #1421).
    Under gthread it keeps the proxy and its broker feeds out of the process
    that places orders.

    The child runs `python -m websocket_proxy.server` in a fresh interpreter
    with no eventlet monkey-patching, so all the offending primitives are
    real OS locks. Systemd's cgroup-based KillMode (default: control-group)
    cleans up the child when the unit stops; our atexit handler and the
    shutdown hooks cover graceful gunicorn shutdown.
    """
    global _websocket_subprocess

    if _websocket_subprocess is not None and _websocket_subprocess.poll() is None:
        logger.debug("WebSocket subprocess already running, skipping spawn")
        return

    proc = _launch_child()
    _websocket_subprocess = proc
    if proc is None:
        return

    # Graceful shutdown on clean gunicorn exit
    atexit.register(_terminate_websocket_subprocess)

    if _supervised():
        _start_supervisor()


def _ports() -> list[tuple[str, int]]:
    """The two ports the child binds: the WebSocket port and the ZeroMQ bus."""
    ports = []
    try:
        ports.append(
            (os.getenv("WEBSOCKET_HOST", "127.0.0.1"), int(os.getenv("WEBSOCKET_PORT", "8765")))
        )
    except ValueError:
        pass
    try:
        ports.append((os.getenv("ZMQ_HOST", "127.0.0.1"), int(os.getenv("ZMQ_PORT", "5555"))))
    except ValueError:
        pass
    return ports


def _ports_free() -> bool:
    from .port_check import is_port_in_use

    return not any(is_port_in_use(host, port, log=False) for host, port in _ports())


def _should_stop_supervising() -> bool:
    if _stopping:
        return True
    try:
        from utils import stream_registry

        return stream_registry.should_stop()
    except Exception:
        return False


def _sleep_unless_stopping(seconds: float) -> bool:
    """Sleep up to ``seconds``. True if supervision should stop meanwhile."""
    deadline = time.monotonic() + seconds
    while not _should_stop_supervising():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(SUPERVISOR_POLL_SECONDS, remaining))
    return True


def _supervise() -> None:
    """Restart the child when it exits unexpectedly, until shutdown begins.

    Waits for both ports to be free before each restart, so a restart never
    races a dying child (or an orphan) for the ZeroMQ bind: a second binder
    would slide nowhere, it would simply fail, and "subscribe succeeds but no
    ticks arrive" is the symptom the bus invariant exists to prevent.
    """
    global _websocket_subprocess, _restarts, _last_exit_code, _last_restart_at

    failures: list[float] = []
    backoff_index = 0
    started_at = time.monotonic()

    while not _sleep_unless_stopping(SUPERVISOR_POLL_SECONDS):
        proc = _websocket_subprocess
        if proc is not None:
            code = proc.poll()
            if code is None:
                if backoff_index and time.monotonic() - started_at >= STABLE_UPTIME_SECONDS:
                    backoff_index = 0
                continue
        # No child at all means the last restart could not even launch one;
        # that is retried like an exit, not left alone.
        if _should_stop_supervising():
            return

        now = time.monotonic()
        failures = [t for t in failures if now - t < FAILURE_WINDOW_SECONDS]
        failures.append(now)
        if proc is not None:
            with _state_lock:
                _last_exit_code = code
            logger.warning(
                "Live market data stopped unexpectedly and is being restarted. "
                "Charts and live prices may pause for a few seconds."
            )

        # Wait for the old child's ports to be released.
        waited = 0.0
        while not _ports_free() and waited < PORT_FREE_WAIT_SECONDS:
            if _sleep_unless_stopping(0.5):
                return
            waited += 0.5

        if len(failures) >= FAILURES_BEFORE_SLOW_RETRY:
            delay = SLOW_RETRY_SECONDS
            logger.error(
                "Live market data keeps stopping; retrying once a minute. "
                "Check log/errors.jsonl for the reason, or restart OpenAlgo."
            )
        else:
            delay = RESTART_BACKOFF_SECONDS[min(backoff_index, len(RESTART_BACKOFF_SECONDS) - 1)]
            backoff_index += 1
        if _sleep_unless_stopping(delay):
            return

        proc = _launch_child()
        _websocket_subprocess = proc
        started_at = time.monotonic()
        with _state_lock:
            _restarts += 1
            _last_restart_at = time.time()
        if proc is None:
            logger.error("Live market data could not be restarted; will try again.")


def _start_supervisor() -> None:
    """Start the one supervisor thread for this process. Idempotent."""
    global _supervisor_thread

    with _state_lock:
        if _supervisor_thread is not None and _supervisor_thread.is_alive():
            return
        # A plain thread: green under eventlet (never used there today), real
        # under gthread. It sleeps and polls a Popen, nothing more.
        _supervisor_thread = threading.Thread(
            target=_supervise, daemon=True, name="ws-proxy-supervisor"
        )
        thread = _supervisor_thread
    thread.start()


def _wait_for_exit(proc, timeout: float) -> bool:
    """Poll ``proc`` until it exits or ``timeout`` passes. True if it exited.

    Polling rather than ``Popen.wait``: this runs at interpreter exit and from
    shutdown hooks, and under eventlet a green wait from the hub's own context
    raised "do not call blocking functions from the mainloop" and left the
    child running. The sleep is the unpatched one, which is harmless at exit.
    """
    from utils.real_threading import sleep as real_sleep

    deadline = time.monotonic() + timeout
    while proc.poll() is None:
        if time.monotonic() >= deadline:
            return False
        real_sleep(0.05)
    return True


def _terminate_websocket_subprocess():
    """SIGTERM the WS child on shutdown; SIGKILL if it ignores TERM.

    Sets the stopping flag first, so the supervisor never restarts a child
    that shutdown is stopping.
    """
    global _websocket_subprocess, _stopping
    _stopping = True
    proc = _websocket_subprocess
    if proc is None:
        return
    if proc.poll() is not None:
        _websocket_subprocess = None
        return
    try:
        logger.info(f"Terminating WebSocket subprocess PID {proc.pid}")
        proc.terminate()
        if not _wait_for_exit(proc, 10):
            logger.warning("WebSocket subprocess did not exit on SIGTERM, sending SIGKILL")
            proc.kill()
            _wait_for_exit(proc, 5)
    except Exception as e:
        logger.warning(f"Error terminating WebSocket subprocess: {e}")
    finally:
        _websocket_subprocess = None


def _signal_handlers_wanted(mode: str) -> bool:
    """Whether this module installs :func:`signal_handler` for ``mode``.

    * Never under the gthread worker: gunicorn's graceful stop is kept.
    * Under the eventlet worker (subprocess mode), exactly as before.
    * On the development server's thread mode, as before (the Ctrl+C path).
    """
    if _runtime.gthread_active():
        return False
    if mode == "subprocess":
        return _eventlet_active()
    if mode == "thread":
        return not _runtime.under_gunicorn()
    return False


def _install_signal_handlers() -> None:
    """Replace SIGINT and SIGTERM with :func:`signal_handler`."""
    try:
        # SIGINT (Ctrl+C) - Available on all platforms
        signal.signal(signal.SIGINT, signal_handler)
        signals_registered = ["SIGINT"]

        # SIGTERM - Available on Unix-like systems (Mac, Linux)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, signal_handler)
            signals_registered.append("SIGTERM")

        logger.debug(f"Signal handlers registered: {', '.join(signals_registered)}")
    except Exception as e:
        logger.warning(f"Could not register signal handlers: {e}")


def start_websocket_server(mode: str | None = None):
    """
    Start the WebSocket proxy server where :func:`resolve_proxy_mode` says.

    Args:
        mode: ``"subprocess"``, ``"thread"`` or ``"external"``; resolved when
            omitted.

    Returns:
        The proxy thread in thread mode, otherwise None.
    """
    global _websocket_proxy_instance, _websocket_thread, _resolved_mode

    mode = mode or resolve_proxy_mode()
    _resolved_mode = mode

    if mode == "external":
        logger.debug(
            "Running in Docker/standalone mode - WebSocket server started separately by start.sh"
        )
        return None

    if mode == "subprocess":
        _spawn_websocket_subprocess()
        # Under eventlet, forward Ctrl+C and SIGTERM to the cleanup exactly as
        # before. Under gthread, none: gunicorn's own graceful stop drains
        # requests, and atexit plus the shutdown hooks stop the child.
        if _signal_handlers_wanted(mode):
            _install_signal_handlers()
        return None

    logger.debug("Starting WebSocket proxy server in a separate thread")

    def run_websocket_server():
        """Run the WebSocket server in an event loop"""
        global _websocket_proxy_instance
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # Import here to avoid circular imports
            import os

            from dotenv import load_dotenv

            from .server import WebSocketProxy

            load_dotenv()
            ws_host = os.getenv("WEBSOCKET_HOST", "127.0.0.1")
            ws_port = int(os.getenv("WEBSOCKET_PORT", "8765"))

            # Create and store the proxy instance
            _websocket_proxy_instance = WebSocketProxy(host=ws_host, port=ws_port)

            # Start the proxy
            loop.run_until_complete(_websocket_proxy_instance.start())

        except Exception as e:
            logger.exception(f"Error in WebSocket server thread: {e}")
            _websocket_proxy_instance = None
        finally:
            # Always close the event loop to prevent FD leak
            if loop is not None:
                try:
                    # Cancel all pending tasks
                    pending = asyncio.all_tasks(loop)
                    for task in pending:
                        task.cancel()
                    # Run until all tasks are cancelled
                    if pending:
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.close()
                    logger.debug("Event loop closed successfully")
                except Exception as loop_err:
                    logger.warning(f"Error closing event loop: {loop_err}")

    # Daemon, and the cleanup below is what makes that safe.
    #
    # This thread was non-daemon, with cleanup_websocket_server registered
    # through atexit. Those two cannot both work: atexit runs only after the
    # interpreter has finished joining every non-daemon thread, so the cleanup
    # that releases this thread was queued behind the wait for this thread.
    # Nothing in that pair ever completes on its own.
    #
    # What used to break the tie was signal_handler below, which cleaned up and
    # called os._exit(0). utils/shutdown.py registers its SIGINT handler later
    # in app.py and replaced it, so Ctrl+C stopped reaching the cleanup and the
    # dev server stopped exiting. utils.shutdown now stops the proxy itself,
    # before the interpreter starts joining threads, and daemon=True is what
    # keeps a cleanup that times out from wedging the exit anyway.
    _websocket_thread = _original_threading.Thread(
        target=run_websocket_server,
        daemon=True,
        name="websocket-proxy",
    )
    _websocket_thread.start()

    # Register cleanup handlers
    atexit.register(cleanup_websocket_server)

    # Register signal handlers for graceful shutdown (development server only)
    if _signal_handlers_wanted("thread"):
        _install_signal_handlers()

    logger.debug("WebSocket proxy server thread started")
    return _websocket_thread


def start_websocket_proxy(app):
    """
    Integrate the WebSocket proxy server with a Flask application.
    This should be called during app initialization.

    Args:
        app: Flask application instance
    """
    global _websocket_server_started

    # Check if this process should start the WebSocket server
    if should_start_websocket():
        # Our flag will prevent multiple starts if called multiple times
        if not _websocket_server_started:
            _websocket_server_started = True
            mode = resolve_proxy_mode()
            logger.debug(f"Starting WebSocket server ({mode} mode)")
            start_websocket_server(mode)
            logger.debug("WebSocket server integration with Flask complete")
        else:
            logger.debug("WebSocket server already running, skipping initialization")
    else:
        logger.debug("Skipping WebSocket server in parent/monitor process")
