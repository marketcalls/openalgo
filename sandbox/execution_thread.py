# sandbox/execution_thread.py
"""
Execution Engine Thread Manager

Manages the execution engine as a daemon thread that:
- Starts automatically when analyzer mode is enabled
- Stops gracefully when analyzer mode is disabled
- Runs continuously in the background monitoring and executing orders
- Supports WebSocket-based or polling-based execution
- Automatic fallback to polling if WebSocket is unavailable
"""

import os
import threading
import time

from database.sandbox_db import get_config
from utils.logging import get_logger

logger = get_logger(__name__)

# Global thread instance
_execution_thread = None
_websocket_engine = None
_thread_lock = threading.Lock()
_stop_event = threading.Event()
_current_engine_type = None  # Track which engine type is running
_auto_upgrade_thread = None
_auto_upgrade_stop_event = threading.Event()
_auto_upgrade_enabled = False


class ExecutionEngineThread(threading.Thread):
    """Daemon thread that runs the execution engine"""

    def __init__(self):
        super().__init__(daemon=True, name="SandboxExecutionEngine")
        self.stop_event = threading.Event()
        self.check_interval = int(get_config("order_check_interval", "5"))

    def run(self):
        """Main thread loop"""
        from sandbox.execution_engine import ExecutionEngine

        logger.debug("Sandbox Execution Engine thread started")
        engine = ExecutionEngine()

        while not self.stop_event.is_set():
            try:
                engine.check_and_execute_pending_orders()
            except Exception as e:
                logger.exception(f"Error in execution engine thread: {e}")

            # Sleep in small increments to allow quick shutdown
            for _ in range(self.check_interval):
                if self.stop_event.is_set():
                    break
                time.sleep(1)

        logger.info("Sandbox Execution Engine thread stopped")

    def stop(self):
        """Signal the thread to stop"""
        self.stop_event.set()


def _is_websocket_proxy_healthy() -> bool:
    """Check if WebSocket proxy server is running and accepting connections"""
    import os
    import socket

    try:
        # Get WebSocket proxy host and port from environment
        ws_host = os.getenv("WEBSOCKET_HOST", "127.0.0.1")
        ws_port = int(os.getenv("WEBSOCKET_PORT", "8765"))

        # Try to connect to the WebSocket proxy server
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)  # 2 second timeout
        result = sock.connect_ex((ws_host, ws_port))
        sock.close()

        if result == 0:
            logger.debug(f"WebSocket proxy is healthy at {ws_host}:{ws_port}")
            return True
        else:
            logger.debug(f"WebSocket proxy not reachable at {ws_host}:{ws_port}")
            return False
    except Exception as e:
        logger.debug(f"WebSocket proxy health check failed: {e}")
        return False


def start_execution_engine(engine_type: str = None):
    """
    Start the execution engine daemon thread
    Thread-safe - only one instance will run

    Args:
        engine_type: 'websocket', 'polling', or None (auto-detect)

    Engine selection priority:
    1. If engine_type param is provided, use it
    2. Otherwise, check SANDBOX_ENGINE_TYPE env var
    3. Default: 'websocket' (with automatic fallback to polling if unavailable)

    Fallback behavior:
    - Always tries WebSocket first (unless explicitly set to 'polling')
    - Automatically falls back to polling if WebSocket proxy is unhealthy
    - WebSocket engine has built-in fallback to polling if data becomes stale
    """
    global _execution_thread, _websocket_engine, _current_engine_type
    global _auto_upgrade_thread, _auto_upgrade_enabled

    with _thread_lock:
        # Check if any engine is already running
        if _execution_thread is not None and _execution_thread.is_alive():
            logger.debug("Polling execution engine already running")
            return True, "Execution engine already running (type: polling)"

        if _websocket_engine is not None:
            from sandbox.websocket_execution_engine import is_websocket_execution_engine_running

            if is_websocket_execution_engine_running():
                logger.debug("WebSocket execution engine already running")
                return True, "Execution engine already running (type: websocket)"

        # Determine engine type - default to websocket (with auto-fallback)
        if engine_type is None:
            engine_type = os.getenv("SANDBOX_ENGINE_TYPE", "websocket").lower()
            if os.getenv("SANDBOX_ENGINE_TYPE"):
                logger.info(f"Sandbox engine type forced by env: {engine_type}")

        logger.debug(f"Starting execution engine with type: {engine_type}")

        try:
            if engine_type == "websocket":
                # Try WebSocket engine first
                if _is_websocket_proxy_healthy():
                    from sandbox.websocket_execution_engine import (
                        get_websocket_execution_engine,
                        start_websocket_execution_engine,
                    )

                    success, message = start_websocket_execution_engine()
                    if success:
                        _websocket_engine = get_websocket_execution_engine()
                        _current_engine_type = "websocket"
                        logger.debug("WebSocket execution engine started (with built-in fallback)")
                        return True, "WebSocket execution engine started"
                    else:
                        logger.warning(
                            f"Failed to start WebSocket engine: {message}, falling back to polling"
                        )
                else:
                    logger.warning(
                        "WebSocket proxy not healthy at startup, falling back to polling engine"
                    )

                # Fallback to polling
                engine_type = "polling"
                _auto_upgrade_enabled = True

            # Start polling engine (default)
            _execution_thread = ExecutionEngineThread()
            _execution_thread.start()
            _current_engine_type = "polling"
            logger.debug("Polling execution engine started successfully")
            if _auto_upgrade_enabled:
                _start_websocket_upgrade_watcher()
            return True, "Polling execution engine started"

        except Exception as e:
            logger.exception(f"Failed to start execution engine: {e}")
            return False, f"Failed to start execution engine: {str(e)}"


def stop_execution_engine():
    """
    Stop the execution engine daemon thread gracefully.
    Handles both WebSocket and polling engine types.
    """
    global _execution_thread, _websocket_engine, _current_engine_type
    global _auto_upgrade_thread, _auto_upgrade_enabled

    with _thread_lock:
        stopped_any = False

        # Stop auto-upgrade watcher
        _stop_websocket_upgrade_watcher()

        # Stop WebSocket engine if running
        if _websocket_engine is not None:
            try:
                from sandbox.websocket_execution_engine import stop_websocket_execution_engine

                success, message = stop_websocket_execution_engine()
                if success:
                    logger.info("WebSocket execution engine stopped")
                    stopped_any = True
                _websocket_engine = None
            except Exception as e:
                logger.exception(f"Error stopping WebSocket execution engine: {e}")

        # Stop polling engine if running
        if _execution_thread is not None and _execution_thread.is_alive():
            try:
                logger.info("Stopping polling execution engine thread...")
                _execution_thread.stop()

                # Wait up to 10 seconds for thread to stop
                _execution_thread.join(timeout=10)

                if _execution_thread.is_alive():
                    logger.warning("Polling execution engine thread did not stop gracefully")
                else:
                    logger.info("Polling execution engine thread stopped successfully")
                    stopped_any = True

                _execution_thread = None
            except Exception as e:
                logger.exception(f"Error stopping polling execution engine: {e}")

        _current_engine_type = None
        _auto_upgrade_enabled = False

        if stopped_any:
            return True, "Execution engine stopped"
        else:
            return True, "Execution engine not running"


def _start_websocket_upgrade_watcher():
    """Start a background watcher to upgrade polling -> websocket when available."""
    global _auto_upgrade_thread, _auto_upgrade_stop_event

    if _auto_upgrade_thread and _auto_upgrade_thread.is_alive():
        return

    _auto_upgrade_stop_event.clear()

    def _watch():
        global _execution_thread, _websocket_engine, _current_engine_type
        while not _auto_upgrade_stop_event.is_set():
            time.sleep(5)
            if _auto_upgrade_stop_event.is_set():
                break
            if not _is_websocket_proxy_healthy():
                continue
            with _thread_lock:
                # Only upgrade if polling is running and websocket engine is not
                if _execution_thread is None or not _execution_thread.is_alive():
                    continue
                if _websocket_engine is not None:
                    continue
                try:
                    from sandbox.websocket_execution_engine import (
                        get_websocket_execution_engine,
                        start_websocket_execution_engine,
                    )

                    success, message = start_websocket_execution_engine()
                    if success:
                        _websocket_engine = get_websocket_execution_engine()
                        _current_engine_type = "websocket"
                        logger.debug("WebSocket execution engine started (auto-upgrade)")

                        # Stop polling engine after successful upgrade
                        _execution_thread.stop()
                        _execution_thread.join(timeout=10)
                        if _execution_thread.is_alive():
                            logger.warning("Polling execution engine did not stop after upgrade")
                        else:
                            logger.info("Polling execution engine stopped after upgrade")
                        _execution_thread = None
                        break
                    else:
                        logger.warning(
                            f"Auto-upgrade failed to start WebSocket engine: {message}"
                        )
                except Exception as e:
                    logger.exception(f"Error during auto-upgrade to WebSocket engine: {e}")

    _auto_upgrade_thread = threading.Thread(
        target=_watch, daemon=True, name="SandboxEngine-WsUpgradeWatcher"
    )
    _auto_upgrade_thread.start()


def _stop_websocket_upgrade_watcher():
    """Stop the background websocket upgrade watcher."""
    global _auto_upgrade_thread, _auto_upgrade_stop_event

    _auto_upgrade_stop_event.set()
    if _auto_upgrade_thread and _auto_upgrade_thread.is_alive():
        _auto_upgrade_thread.join(timeout=5)
    _auto_upgrade_thread = None


def is_execution_engine_running():
    """Check if any execution engine is running"""
    global _execution_thread, _websocket_engine

    # Check polling engine
    if _execution_thread is not None and _execution_thread.is_alive():
        return True

    # Check WebSocket engine
    if _websocket_engine is not None:
        try:
            from sandbox.websocket_execution_engine import is_websocket_execution_engine_running

            if is_websocket_execution_engine_running():
                return True
        except Exception:
            pass

    return False


def get_execution_engine_status():
    """Get status information about the execution engine"""
    global _current_engine_type

    running = is_execution_engine_running()
    engine_type = _current_engine_type if running else None

    status = {
        "running": running,
        "engine_type": engine_type,
        "check_interval": int(get_config("order_check_interval", "5")),
        "configured_type": os.getenv("SANDBOX_ENGINE_TYPE", "polling"),
    }

    # Add thread info for polling engine
    if _execution_thread is not None:
        status["thread_name"] = _execution_thread.name
        status["thread_alive"] = _execution_thread.is_alive()

    # Add WebSocket engine info if available
    if _websocket_engine is not None:
        status["websocket_engine"] = True

    return status
