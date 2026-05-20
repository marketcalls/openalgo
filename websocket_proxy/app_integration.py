import asyncio
import atexit
import os
import platform
import signal
import subprocess
import sys
import threading

from utils.logging import get_logger, highlight_url

from .server import main as websocket_main

# Import the original threading module to run the asyncio event loop in a real
# OS thread, bypassing eventlet's monkey-patching which turns threading.Thread
# into green threads where asyncio.new_event_loop() cannot work.
if "eventlet" in sys.modules:
    import eventlet

    _original_threading = eventlet.patcher.original("threading")
else:
    _original_threading = threading


def _eventlet_active() -> bool:
    """True when eventlet has monkey-patched the stdlib (gunicorn worker)."""
    try:
        from eventlet.patcher import is_monkey_patched
        return bool(is_monkey_patched("socket"))
    except Exception:
        return False


# Set the correct event loop policy for Windows to avoid ZeroMQ warnings
if platform.system() == "Windows":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Global flag to track if the WebSocket server has been started
# Used to prevent multiple instances in Flask debug mode
_websocket_server_started = False
_websocket_proxy_instance = None
_websocket_thread = None
_websocket_subprocess = None  # set when running under eventlet (gunicorn)

logger = get_logger(__name__)


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

    # If we spawned the WS as a subprocess (gunicorn+eventlet path), there is
    # no in-process thread or proxy instance to clean up — just kill the child.
    if _websocket_subprocess is not None:
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
    """Handle SIGINT (Ctrl+C) and SIGTERM signals"""
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    cleanup_websocket_server()
    # Use os._exit() for immediate termination across all platforms
    os._exit(0)


def _spawn_websocket_subprocess():
    """
    Spawn the WebSocket proxy as a child *process* (not a thread).

    Required under gunicorn+eventlet: an in-process asyncio thread shares the
    process with the eventlet hub, and any eventlet-monkey-patched semaphore
    (stdlib logging RLock, socketio lock, broker adapter `threading.Lock`)
    touched from both threads triggers `greenlet.error: Cannot switch to a
    different thread` and silently corrupts WS state (GitHub issue #1421).

    The child runs `python -m websocket_proxy.server` in a fresh interpreter
    with no eventlet monkey-patching, so all the offending primitives are
    real OS locks. Systemd's cgroup-based KillMode (default: control-group)
    cleans up the child when the unit stops; our atexit handler covers
    graceful gunicorn shutdown.
    """
    global _websocket_subprocess

    if _websocket_subprocess is not None and _websocket_subprocess.poll() is None:
        logger.debug("WebSocket subprocess already running, skipping spawn")
        return

    # Find the openalgo project root (parent of websocket_proxy/)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    cmd = [sys.executable, "-u", "-m", "websocket_proxy.server"]
    logger.debug(f"Spawning WebSocket subprocess: {' '.join(cmd)} (cwd={project_root})")

    try:
        # Inherit stdout/stderr so the child's logging lands in the same
        # systemd journal as gunicorn. The WS server already uses Python
        # logging via utils.logging, so file/json log handlers fire too.
        _websocket_subprocess = subprocess.Popen(
            cmd,
            cwd=project_root,
            stdout=None,
            stderr=None,
            # Do NOT set start_new_session=True — staying in the gunicorn
            # cgroup means systemd reaps the child if gunicorn dies hard.
        )
        logger.info(f"WebSocket subprocess started with PID {_websocket_subprocess.pid}")
    except Exception as e:
        logger.exception(f"Failed to spawn WebSocket subprocess: {e}")
        _websocket_subprocess = None
        return

    # Graceful shutdown on clean gunicorn exit
    atexit.register(_terminate_websocket_subprocess)


def _terminate_websocket_subprocess():
    """SIGTERM the WS child on shutdown; SIGKILL if it ignores TERM."""
    global _websocket_subprocess
    if _websocket_subprocess is None:
        return
    if _websocket_subprocess.poll() is not None:
        _websocket_subprocess = None
        return
    try:
        logger.info(f"Terminating WebSocket subprocess PID {_websocket_subprocess.pid}")
        _websocket_subprocess.terminate()
        try:
            _websocket_subprocess.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("WebSocket subprocess did not exit on SIGTERM, sending SIGKILL")
            _websocket_subprocess.kill()
            _websocket_subprocess.wait(timeout=5)
    except Exception as e:
        logger.warning(f"Error terminating WebSocket subprocess: {e}")
    finally:
        _websocket_subprocess = None


def start_websocket_server():
    """
    Start the WebSocket proxy server.

    Under gunicorn+eventlet: spawned as a child process (avoids the
    eventlet/asyncio cross-OS-thread greenlet crash class).

    Under the dev server (no eventlet): run as a real OS thread inside the
    Flask process, preserving the long-standing dev workflow.
    """
    global _websocket_proxy_instance, _websocket_thread

    if _eventlet_active():
        _spawn_websocket_subprocess()
        # Register signal handlers so Ctrl+C in dev forwards cleanly. Under
        # systemd these are typically replaced by the unit's signal handling.
        try:
            signal.signal(signal.SIGINT, signal_handler)
            if hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, signal_handler)
        except Exception as e:
            logger.warning(f"Could not register signal handlers: {e}")
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

    # Start the WebSocket server in a daemon thread
    _websocket_thread = _original_threading.Thread(
        target=run_websocket_server,
        daemon=False,  # Changed to False so we can properly clean up
    )
    _websocket_thread.start()

    # Register cleanup handlers
    atexit.register(cleanup_websocket_server)

    # Register signal handlers for graceful shutdown
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
            logger.debug("Starting WebSocket server in Flask application process")
            start_websocket_server()
            logger.debug("WebSocket server integration with Flask complete")
        else:
            logger.debug("WebSocket server already running, skipping initialization")
    else:
        logger.debug("Skipping WebSocket server in parent/monitor process")
