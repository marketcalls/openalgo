"""
Order Status Poller — background thread that polls broker for order fill confirmations.

Singleton pattern. Polls at 1 request/second. Priority queue with exits before entries.
Emits SocketIO events for real-time dashboard updates (PRD V1 §17.5).
Recovers pending orders on startup (PRD V1 §17.4).
"""

import queue
import threading
import time

from extensions import socketio
from utils.logging import get_logger

logger = get_logger(__name__)

# Singleton state
_poller_thread = None
_poller_lock = threading.Lock()
_poll_queue = queue.PriorityQueue()
_running = False

# Priority: lower number = higher priority (exits before entries)
PRIORITY_EXIT = 0
PRIORITY_ENTRY = 1


def enqueue_order(orderid, strategy_id, strategy_type, user_id, is_entry=True):
    """Add an order to the polling queue.

    Args:
        orderid: Broker order ID to poll
        strategy_id: Strategy that placed the order
        strategy_type: 'webhook' or 'chartink'
        user_id: User who owns the strategy
        is_entry: True for entry orders, False for exit orders
    """
    priority = PRIORITY_ENTRY if is_entry else PRIORITY_EXIT
    item = {
        "orderid": orderid,
        "strategy_id": strategy_id,
        "strategy_type": strategy_type,
        "user_id": user_id,
        "is_entry": is_entry,
        "retries": 0,
        "max_retries": 30,  # 30 seconds of polling
    }
    _poll_queue.put((priority, time.time(), item))
    _ensure_running()
    logger.info(f"Enqueued order {orderid} for status polling (entry={is_entry})")


def recover_pending_orders():
    """Re-enqueue pending/open orders from DB on startup (PRD V1 §17.4).

    Called once when the poller starts to recover orders that were being
    tracked before a crash or restart.
    """
    from database.strategy_position_db import get_pending_orders

    try:
        pending = get_pending_orders()
        if not pending:
            logger.info("No pending orders to recover")
            return

        for order in pending:
            enqueue_order(
                orderid=order.orderid,
                strategy_id=order.strategy_id,
                strategy_type=order.strategy_type,
                user_id=order.user_id,
                is_entry=order.is_entry,
            )

        logger.info(f"Recovered {len(pending)} pending orders for polling")
    except Exception as e:
        logger.exception(f"Error recovering pending orders: {e}")


def _ensure_running():
    """Start the poller thread if not already running."""
    global _poller_thread, _running
    with _poller_lock:
        if not _running:
            _running = True
            _poller_thread = threading.Thread(target=_poll_loop, daemon=True)
            _poller_thread.start()
            logger.info("Order status poller started")


def _poll_loop():
    """Main polling loop — runs in background thread."""
    global _running

    while _running:
        try:
            # Get next order to poll (blocks for up to 5 seconds)
            try:
                priority, enqueue_time, item = _poll_queue.get(timeout=5)
            except queue.Empty:
                continue

            orderid = item["orderid"]
            retries = item["retries"]

            if retries >= item["max_retries"]:
                logger.warning(f"Order {orderid} exceeded max poll retries ({item['max_retries']})")
                _emit_order_event(item, "timeout", {})
                continue

            # Poll broker for order status
            try:
                status = _check_order_status(item)

                if status == "complete":
                    logger.info(f"Order {orderid} confirmed complete")
                elif status in ("rejected", "cancelled"):
                    logger.warning(f"Order {orderid} status: {status}")
                    _handle_failed_order(item, status)
                elif status in ("pending", "open"):
                    # Update order status to 'open' in DB if broker says open
                    if status == "open":
                        from database.strategy_position_db import update_order_status
                        update_order_status(orderid, "open")

                    # Re-enqueue for retry
                    item["retries"] = retries + 1
                    _poll_queue.put((priority, time.time(), item))
                else:
                    # Unknown status, retry
                    item["retries"] = retries + 1
                    _poll_queue.put((priority, time.time(), item))

            except Exception as e:
                logger.exception(f"Error polling order {orderid}: {e}")
                item["retries"] = retries + 1
                _poll_queue.put((priority, time.time(), item))

            # Rate limit: 1 request per second
            time.sleep(1)

        except Exception as e:
            logger.exception(f"Error in poller loop: {e}")
            time.sleep(1)
        finally:
            # Clean up scoped session to prevent connection leaks (PRD V1 §17.2)
            try:
                from database.strategy_position_db import db_session
                db_session.remove()
            except Exception:
                pass


def _check_order_status(item):
    """Check order status with broker and process result.

    Returns order status string: 'complete', 'pending', 'open', 'rejected', 'cancelled'.
    """
    from services.orderstatus_service import get_order_status
    from services.websocket_service import get_user_api_key

    orderid = item["orderid"]
    user_id = item["user_id"]
    strategy_id = item["strategy_id"]
    strategy_type = item["strategy_type"]

    # Get auth token for the user via their API key
    api_key = get_user_api_key(user_id)
    if not api_key:
        logger.error(f"No API key found for user {user_id}, cannot poll order {orderid}")
        return "error"

    success, response, status_code = get_order_status(
        status_data={"orderid": orderid},
        api_key=api_key,
    )

    if not success:
        logger.warning(f"Order status check failed for {orderid}: {response.get('message')}")
        return "pending"  # Treat as pending to retry

    order_data = response.get("data", {})
    order_status = order_data.get("order_status", "").lower()

    if order_status == "complete":
        average_price = float(order_data.get("average_price", 0))
        filled_quantity = int(order_data.get("filled_quantity", order_data.get("quantity", 0)))

        # Look up strategy and symbol_mapping for risk parameter resolution (C-1)
        strategy, symbol_mapping = _lookup_strategy_and_mapping(
            strategy_id, strategy_type, orderid
        )

        # Confirm fill in position tracker with strategy context
        from services.strategy_position_service import confirm_fill

        result = confirm_fill(
            orderid=orderid,
            average_price=average_price,
            filled_quantity=filled_quantity,
            strategy=strategy,
            symbol_mapping=symbol_mapping,
        )

        # Emit SocketIO events for fill confirmation
        _emit_fill_events(item, result, average_price, filled_quantity)

    return order_status


def _lookup_strategy_and_mapping(strategy_id, strategy_type, orderid):
    """Look up the Strategy and SymbolMapping objects for risk resolution.

    Returns (strategy, symbol_mapping) tuple. Either can be None if not found.
    """
    strategy = None
    symbol_mapping = None

    try:
        # Look up the StrategyOrder to get the symbol for mapping lookup
        from database.strategy_position_db import StrategyOrder
        order = StrategyOrder.query.filter_by(orderid=orderid).first()
        if not order:
            return None, None

        if strategy_type == "chartink":
            from database.chartink_db import get_strategy, get_symbol_mappings
        else:
            from database.strategy_db import get_strategy, get_symbol_mappings

        strategy = get_strategy(strategy_id)
        if strategy:
            mappings = get_symbol_mappings(strategy_id)
            # Find the mapping that matches this order's symbol
            for m in mappings:
                mapping_symbol = getattr(m, "symbol", None) or getattr(m, "chartink_symbol", None)
                if mapping_symbol == order.symbol:
                    symbol_mapping = m
                    break
    except Exception as e:
        logger.warning(f"Could not look up strategy/mapping for order {orderid}: {e}")

    return strategy, symbol_mapping


def _emit_fill_events(item, order_result, average_price, filled_quantity):
    """Emit SocketIO events after fill confirmation (PRD V1 §17.5)."""
    if not order_result:
        return

    orderid = item["orderid"]
    strategy_id = item["strategy_id"]
    strategy_type = item["strategy_type"]

    try:
        if item["is_entry"]:
            # Entry fill → position opened
            socketio.start_background_task(
                socketio.emit,
                "strategy_order_filled",
                {
                    "orderid": orderid,
                    "strategy_id": strategy_id,
                    "strategy_type": strategy_type,
                    "symbol": order_result.symbol,
                    "action": order_result.action,
                    "average_price": average_price,
                    "filled_quantity": filled_quantity,
                    "is_entry": True,
                },
            )
            socketio.start_background_task(
                socketio.emit,
                "strategy_position_opened",
                {
                    "strategy_id": strategy_id,
                    "strategy_type": strategy_type,
                    "symbol": order_result.symbol,
                    "action": order_result.action,
                    "quantity": filled_quantity,
                    "average_price": average_price,
                    "position_id": order_result.position_id,
                },
            )
        else:
            # Exit fill → position closed
            socketio.start_background_task(
                socketio.emit,
                "strategy_order_filled",
                {
                    "orderid": orderid,
                    "strategy_id": strategy_id,
                    "strategy_type": strategy_type,
                    "symbol": order_result.symbol,
                    "action": order_result.action,
                    "average_price": average_price,
                    "filled_quantity": filled_quantity,
                    "is_entry": False,
                },
            )
            socketio.start_background_task(
                socketio.emit,
                "strategy_position_closed",
                {
                    "strategy_id": strategy_id,
                    "strategy_type": strategy_type,
                    "symbol": order_result.symbol,
                    "position_id": order_result.position_id,
                    "exit_reason": order_result.exit_reason,
                },
            )
    except Exception as e:
        logger.warning(f"Error emitting fill events for order {orderid}: {e}")


def _emit_order_event(item, status, extra):
    """Emit a SocketIO event for order status changes."""
    try:
        payload = {
            "orderid": item["orderid"],
            "strategy_id": item["strategy_id"],
            "strategy_type": item["strategy_type"],
            "status": status,
            "is_entry": item["is_entry"],
            **extra,
        }
        socketio.start_background_task(
            socketio.emit, "strategy_order_update", payload
        )
    except Exception as e:
        logger.warning(f"Error emitting order event for {item['orderid']}: {e}")


def _handle_failed_order(item, status):
    """Handle rejected or cancelled orders."""
    from database.strategy_position_db import get_position, update_order_status, update_position_state

    orderid = item["orderid"]

    # Update order status
    update_order_status(orderid, status)

    # If this was an entry order, clean up the pending position
    if item["is_entry"]:
        from database.strategy_position_db import StrategyOrder

        order = StrategyOrder.query.filter_by(orderid=orderid).first()
        if order and order.position_id:
            update_position_state(order.position_id, "closed")
            logger.info(f"Closed pending position for rejected order {orderid}")

    # Emit rejection/cancellation event
    _emit_order_event(item, status, {"reason": status})

    if item["is_entry"]:
        socketio.start_background_task(
            socketio.emit,
            "strategy_position_closed",
            {
                "strategy_id": item["strategy_id"],
                "strategy_type": item["strategy_type"],
                "status": status,
                "orderid": orderid,
                "reason": f"Entry order {status}",
            },
        )


def stop():
    """Stop the poller thread."""
    global _running
    _running = False
    logger.info("Order status poller stopped")


def get_queue_size():
    """Get current queue size (for monitoring)."""
    return _poll_queue.qsize()
