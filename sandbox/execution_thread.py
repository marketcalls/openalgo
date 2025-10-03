# sandbox/execution_thread.py
"""
Execution Engine Thread Manager

Manages the execution engine as a daemon thread that:
- Starts automatically when analyzer mode is enabled
- Stops gracefully when analyzer mode is disabled
- Runs continuously in the background monitoring and executing orders
"""

import threading
import time
from utils.logging import get_logger
from database.sandbox_db import get_config

logger = get_logger(__name__)

# Global thread instance
_execution_thread = None
_thread_lock = threading.Lock()
_stop_event = threading.Event()


class ExecutionEngineThread(threading.Thread):
    """Daemon thread that runs the execution engine"""

    def __init__(self):
        super().__init__(daemon=True, name="SandboxExecutionEngine")
        self.stop_event = threading.Event()
        self.check_interval = int(get_config('order_check_interval', '5'))

    def run(self):
        """Main thread loop"""
        from sandbox.execution_engine import ExecutionEngine

        logger.info("Sandbox Execution Engine thread started")
        engine = ExecutionEngine()

        while not self.stop_event.is_set():
            try:
                engine.check_and_execute_pending_orders()
            except Exception as e:
                logger.error(f"Error in execution engine thread: {e}")

            # Sleep in small increments to allow quick shutdown
            for _ in range(self.check_interval):
                if self.stop_event.is_set():
                    break
                time.sleep(1)

        logger.info("Sandbox Execution Engine thread stopped")

    def stop(self):
        """Signal the thread to stop"""
        self.stop_event.set()


def start_execution_engine():
    """
    Start the execution engine daemon thread
    Thread-safe - only one instance will run
    """
    global _execution_thread

    with _thread_lock:
        if _execution_thread is not None and _execution_thread.is_alive():
            logger.debug("Execution engine thread already running")
            return True, "Execution engine already running"

        try:
            _execution_thread = ExecutionEngineThread()
            _execution_thread.start()
            logger.info("Execution engine thread started successfully")
            return True, "Execution engine started"
        except Exception as e:
            logger.error(f"Failed to start execution engine thread: {e}")
            return False, f"Failed to start execution engine: {str(e)}"


def stop_execution_engine():
    """
    Stop the execution engine daemon thread gracefully
    """
    global _execution_thread

    with _thread_lock:
        if _execution_thread is None or not _execution_thread.is_alive():
            logger.debug("Execution engine thread not running")
            return True, "Execution engine not running"

        try:
            logger.info("Stopping execution engine thread...")
            _execution_thread.stop()

            # Wait up to 10 seconds for thread to stop
            _execution_thread.join(timeout=10)

            if _execution_thread.is_alive():
                logger.warning("Execution engine thread did not stop gracefully")
                return False, "Execution engine failed to stop"

            _execution_thread = None
            logger.info("Execution engine thread stopped successfully")
            return True, "Execution engine stopped"
        except Exception as e:
            logger.error(f"Error stopping execution engine thread: {e}")
            return False, f"Error stopping execution engine: {str(e)}"


def is_execution_engine_running():
    """Check if execution engine thread is running"""
    global _execution_thread
    return _execution_thread is not None and _execution_thread.is_alive()


def get_execution_engine_status():
    """Get status information about the execution engine"""
    return {
        'running': is_execution_engine_running(),
        'thread_name': _execution_thread.name if _execution_thread else None,
        'check_interval': int(get_config('order_check_interval', '5'))
    }
