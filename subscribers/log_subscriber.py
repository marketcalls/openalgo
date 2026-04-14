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
