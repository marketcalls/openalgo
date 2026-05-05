"""
Log subscriber — handles all order logging for both live and analyze modes.

Live mode  → writes to order_logs table via async_log_order
Analyze mode → writes to analyzer_logs table via async_log_analyzer

Note: These functions are called directly (not via executor.submit) because the
EventBus already dispatches callbacks in its own ThreadPoolExecutor. Double-submitting
to a second pool would waste thread capacity without benefit.
"""

from database.analyzer_db import async_log_analyzer
from database.apilog_db import async_log_order
from utils.logging import get_logger

logger = get_logger(__name__)


def _log_event(event):
    """Route to the correct logging function based on mode."""
    if event.mode == "analyze":
        async_log_analyzer(event.request_data, event.response_data, event.api_type)
    else:
        async_log_order(event.api_type, event.request_data, event.response_data)


# All handlers delegate to _log_event — the EventBus thread pool provides isolation
on_order_placed = _log_event
on_order_failed = _log_event
on_smart_order_no_action = _log_event
on_order_modified = _log_event
on_order_modify_failed = _log_event
on_order_cancelled = _log_event
on_order_cancel_failed = _log_event
on_all_orders_cancelled = _log_event
on_position_closed = _log_event
on_basket_completed = _log_event
on_split_completed = _log_event
on_options_completed = _log_event
on_multiorder_completed = _log_event
on_analyzer_error = _log_event


# -----------------------------------------------------------------------------
# Strategy v2 + Account events
#
# Strategy events use the standard Python logger — they carry a structured set
# of fields (strategy_id, run_id, etc.) that's most useful as a single tagged
# log line per event. Errors go through logger.exception() so they land in
# log/errors.jsonl with a traceback when present.
# -----------------------------------------------------------------------------


def _log_strategy_event(level: str, event):
    """Render a one-line tagged log entry. Routes ENGINE_ERROR / EXIT_FAILED
    through logger.exception so the JSON error log captures them."""
    fields = []
    for f in ("strategy_id", "run_id", "leg_id", "old_state", "new_state",
              "rule", "ltp", "threshold", "reason", "exit_reason",
              "advances", "new_sl", "user_id", "webhook_id"):
        v = getattr(event, f, None)
        if v not in (None, "", 0, 0.0):
            fields.append(f"{f}={v!r}")
    msg = f"[{event.topic}] " + " ".join(fields)

    if level == "exception":
        logger.exception(msg)
    elif level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)
    else:
        logger.info(msg)


def on_strategy_signal_received(event):
    _log_strategy_event("info", event)


def on_strategy_signal_rejected(event):
    _log_strategy_event("warning", event)


def on_strategy_run_started(event):
    _log_strategy_event("info", event)


def on_strategy_state_changed(event):
    _log_strategy_event("info", event)


def on_strategy_leg_resolved(event):
    _log_strategy_event("info", event)


def on_strategy_leg_filled(event):
    _log_strategy_event("info", event)


def on_strategy_rms_triggered(event):
    _log_strategy_event("info", event)


def on_strategy_trail_advanced(event):
    _log_strategy_event("info", event)


def on_strategy_exit_triggered(event):
    _log_strategy_event("info", event)


def on_strategy_enter_failed(event):
    _log_strategy_event("error", event)


def on_strategy_exit_failed(event):
    _log_strategy_event("error", event)


def on_strategy_run_closed(event):
    _log_strategy_event("info", event)


def on_strategy_engine_error(event):
    _log_strategy_event("exception", event)


def on_strategy_webhook_secret_rotated(event):
    _log_strategy_event("info", event)


def on_strategy_webhook_banned(event):
    _log_strategy_event("warning", event)


def on_account_locked(event):
    _log_strategy_event("warning", event)


def on_account_unlocked(event):
    _log_strategy_event("info", event)
