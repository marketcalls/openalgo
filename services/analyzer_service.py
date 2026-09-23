import copy
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Dict, Optional, Tuple

from database.analyzer_db import AnalyzerLog, db_session
from database.apilog_db import async_log_order
from database.apilog_db import executor as log_executor
from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode, set_analyze_mode
from utils.keyed_locks import LockBusy
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Changing the analyzer (sandbox) mode as one step
# ---------------------------------------------------------------------------

#: Held across writing the mode and bringing the sandbox execution engine and
#: square-off scheduler in line with it. The three places that change the
#: mode used to do the two separately, so a double click or two devices could
#: interleave them: one request set Sandbox, the other set Live and stopped an
#: engine that was not running yet, then the first started it, leaving Live
#: mode with the sandbox engine running (or Sandbox mode with the engine and
#: square-off stopped, so sandbox SL and LIMIT orders never triggered). A
#: stdlib lock, green under eventlet, because its holder does database work and
#: joins the engine thread. A real OS thread under eventlet (the Telegram bot)
#: reaches it through utils.real_threading.run_on_hub.
_MODE_LOCK = threading.Lock()

#: How long a mode change waits for one already in progress, under the gthread
#: worker only. Elsewhere it waits as long as it takes, as the steps it now
#: queues behind always did.
MODE_TRANSITION_TIMEOUT_SECONDS = 30.0

MODE_BUSY_MESSAGE = "Another mode change is still in progress. Try again in a moment."


@contextmanager
def mode_transition(timeout: float | None = MODE_TRANSITION_TIMEOUT_SECONDS) -> Iterator[None]:
    """Hold the analyzer-mode lock for a change that must not interleave with another.

    For a mode change and for anything that must not run beside one (a
    sandbox reset, say).

    Args:
        timeout: Seconds to wait for a change already in progress. Applied
            only under the gthread worker; elsewhere the wait is unbounded.

    Raises:
        LockBusy: Under gthread, when another change held the lock for longer
            than ``timeout``. Its message is ``MODE_BUSY_MESSAGE``.
    """
    from utils.runtime import gthread_active

    wait = timeout if (timeout is not None and gthread_active()) else None
    acquired = _MODE_LOCK.acquire() if wait is None else _MODE_LOCK.acquire(timeout=wait)
    if not acquired:
        raise LockBusy("analyze_mode", name="analyzer-mode", timeout=wait)
    try:
        yield
    finally:
        _MODE_LOCK.release()


def _reconcile_sandbox(mode: bool, *, with_scheduler: bool, catchup: bool) -> None:
    """Start or stop the sandbox machinery so it matches ``mode``.

    Args:
        mode: The persisted analyzer mode.
        with_scheduler: Also start or stop the square-off scheduler.
        catchup: When turning on, run the missed-settlement catch-up.
    """
    from sandbox.execution_thread import start_execution_engine, stop_execution_engine
    from sandbox.squareoff_thread import start_squareoff_scheduler, stop_squareoff_scheduler

    if mode:
        success, message = start_execution_engine()
        if not success:
            logger.warning(f"Failed to start execution engine: {message}")
        if with_scheduler:
            start_squareoff_scheduler()

        if catchup:
            # Run catch-up settlement for any missed settlements while app was stopped
            from sandbox.position_manager import catchup_missed_settlements

            try:
                catchup_missed_settlements()
                logger.info("Catch-up settlement check completed")
            except Exception as e:
                logger.exception(f"Error in catch-up settlement: {e}")

        if with_scheduler:
            logger.info("Analyzer mode enabled - Execution engine and square-off scheduler started")
        elif success:
            logger.info("Execution engine started for Analyze mode")
    else:
        success, message = stop_execution_engine()
        if not success:
            logger.warning(f"Failed to stop execution engine: {message}")
        if with_scheduler:
            stop_squareoff_scheduler()
            logger.info(
                "Analyzer mode disabled - Execution engine and square-off scheduler stopped"
            )
        elif success:
            logger.info("Execution engine stopped for Live mode")


def apply_analyze_mode(
    new_mode: bool | None = None,
    *,
    toggle: bool = False,
    with_scheduler: bool = True,
    catchup: bool = True,
    timeout: float | None = MODE_TRANSITION_TIMEOUT_SECONDS,
) -> bool:
    """Set the analyzer mode and bring the sandbox engine in line with it, as one step.

    The engine is reconciled to the mode that was actually persisted, read
    back after the write, and it is reconciled even when the write raised, so
    the mode and the engine cannot be left disagreeing. When nothing races,
    the steps and their outcome are exactly what each caller did before.

    Args:
        new_mode: The mode to set. Ignored when ``toggle`` is True.
        toggle: Flip the current mode instead, read under the lock.
        with_scheduler: Also start or stop the square-off scheduler.
        catchup: When turning on, run the missed-settlement catch-up.
        timeout: See :func:`mode_transition`.

    Returns:
        The persisted mode: True for analyzer (sandbox) mode.

    Raises:
        LockBusy: Under gthread, another change is still in progress.
        Exception: Whatever writing the mode raised, after the reconcile.
    """
    with mode_transition(timeout):
        if toggle:
            new_mode = not get_analyze_mode()
        try:
            set_analyze_mode(bool(new_mode))
        finally:
            persisted = bool(get_analyze_mode())
            _reconcile_sandbox(persisted, with_scheduler=with_scheduler, catchup=catchup)
        return persisted


def get_analyzer_status_with_auth(
    analyzer_data: dict[str, Any], auth_token: str, broker: str, original_data: dict[str, Any]
) -> tuple[bool, dict[str, Any], int]:
    """
    Get analyzer mode status and statistics.

    Args:
        analyzer_data: Analyzer data (currently just apikey)
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    request_data = copy.deepcopy(original_data)
    if "apikey" in request_data:
        request_data.pop("apikey", None)

    try:
        # Get current analyzer mode
        current_mode = get_analyze_mode()

        # Get analyzer logs count
        logs_count = db_session.query(AnalyzerLog).count()

        response_data = {
            "status": "success",
            "data": {
                "mode": "analyze" if current_mode else "live",
                "analyze_mode": current_mode,
                "total_logs": logs_count,
            },
        }

        log_executor.submit(async_log_order, "analyzer_status", request_data, response_data)
        return True, response_data, 200

    except Exception as e:
        logger.exception(f"Error getting analyzer status: {e}")
        error_response = {"status": "error", "message": str(e)}
        log_executor.submit(async_log_order, "analyzer_status", original_data, error_response)
        return False, error_response, 500


def toggle_analyzer_mode_with_auth(
    analyzer_data: dict[str, Any], auth_token: str, broker: str, original_data: dict[str, Any]
) -> tuple[bool, dict[str, Any], int]:
    """
    Toggle analyzer mode on/off.

    Args:
        analyzer_data: Analyzer data containing mode
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    request_data = copy.deepcopy(original_data)
    if "apikey" in request_data:
        request_data.pop("apikey", None)

    try:
        # Get the requested mode
        new_mode = analyzer_data.get("mode", False)

        # Set the analyzer mode and start or stop the execution engine and
        # square-off scheduler to match, as one step.
        try:
            new_mode = apply_analyze_mode(new_mode)
        except LockBusy:
            busy_response = {"status": "error", "message": MODE_BUSY_MESSAGE}
            log_executor.submit(async_log_order, "analyzer_toggle", original_data, busy_response)
            return False, busy_response, 409

        # Get logs count for response
        logs_count = db_session.query(AnalyzerLog).count()

        response_data = {
            "status": "success",
            "data": {
                "mode": "analyze" if new_mode else "live",
                "analyze_mode": new_mode,
                "total_logs": logs_count,
                "message": f"Analyzer mode switched to {'analyze' if new_mode else 'live'}",
            },
        }

        log_executor.submit(async_log_order, "analyzer_toggle", request_data, response_data)
        return True, response_data, 200

    except Exception as e:
        logger.exception(f"Error toggling analyzer mode: {e}")
        error_response = {"status": "error", "message": str(e)}
        log_executor.submit(async_log_order, "analyzer_toggle", original_data, error_response)
        return False, error_response, 500


def get_analyzer_status(
    analyzer_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get analyzer mode status and statistics.
    Supports both API-based authentication and direct internal calls.

    Args:
        analyzer_data: Analyzer data (currently just apikey)
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(analyzer_data)
    if api_key:
        original_data["apikey"] = api_key

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Add API key to analyzer data
        analyzer_data["apikey"] = api_key

        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {"status": "error", "message": "Invalid openalgo apikey"}
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403

        return get_analyzer_status_with_auth(analyzer_data, AUTH_TOKEN, broker_name, original_data)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_analyzer_status_with_auth(analyzer_data, auth_token, broker, original_data)

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400


def toggle_analyzer_mode(
    analyzer_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Toggle analyzer mode on/off.
    Supports both API-based authentication and direct internal calls.

    Args:
        analyzer_data: Analyzer data containing mode
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(analyzer_data)
    if api_key:
        original_data["apikey"] = api_key

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Add API key to analyzer data
        analyzer_data["apikey"] = api_key

        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {"status": "error", "message": "Invalid openalgo apikey"}
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403

        # Check if in semi-auto mode - block analyzer toggle for RA compliance
        from database.auth_db import get_order_mode

        order_mode = get_order_mode(api_key)

        if order_mode == "semi_auto":
            error_response = {
                "status": "error",
                "message": "Operation analyzer/toggle is not allowed in Semi-Auto mode. This operation can only be performed by the client via the UI. This restriction ensures SEBI Research Analyst compliance where mode switching is a client-only decision.",
            }
            log_executor.submit(async_log_order, "analyzer_toggle", original_data, error_response)
            return False, error_response, 403

        return toggle_analyzer_mode_with_auth(analyzer_data, AUTH_TOKEN, broker_name, original_data)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return toggle_analyzer_mode_with_auth(analyzer_data, auth_token, broker, original_data)

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400
