"""
Order Status Poller — background thread that polls broker for order fill confirmations.

Singleton pattern. Polls at 1 request/second. Priority queue with exits before entries.
"""

import queue
import threading
import time

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
                # No items to poll, check if we should stop
                if _poll_queue.empty():
                    continue
                continue

            orderid = item["orderid"]
            retries = item["retries"]

            if retries >= item["max_retries"]:
                logger.warning(f"Order {orderid} exceeded max poll retries ({item['max_retries']})")
                continue

            # Poll broker for order status
            try:
                status = _check_order_status(item)

                if status == "complete":
                    logger.info(f"Order {orderid} confirmed complete")
                    # Fill confirmation is handled inside _check_order_status
                elif status in ("rejected", "cancelled"):
                    logger.warning(f"Order {orderid} status: {status}")
                    _handle_failed_order(item, status)
                elif status in ("pending", "open"):
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


def _check_order_status(item):
    """Check order status with broker and process result.

    Returns order status string: 'complete', 'pending', 'open', 'rejected', 'cancelled'.
    """
    from services.orderstatus_service import get_order_status
    from services.websocket_service import get_user_api_key

    orderid = item["orderid"]
    user_id = item["user_id"]

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

        # Confirm fill in position tracker
        from services.strategy_position_service import confirm_fill

        confirm_fill(
            orderid=orderid,
            average_price=average_price,
            filled_quantity=filled_quantity,
        )

    return order_status


def _handle_failed_order(item, status):
    """Handle rejected or cancelled orders."""
    from database.strategy_position_db import get_position, update_order_status, update_position_state

    orderid = item["orderid"]

    # Update order status
    update_order_status(orderid, status)

    # If this was an entry order, clean up the pending position
    if item["is_entry"]:
        from database.strategy_position_db import StrategyOrder, db_session

        order = StrategyOrder.query.filter_by(orderid=orderid).first()
        if order and order.position_id:
            update_position_state(order.position_id, "closed")
            logger.info(f"Closed pending position for rejected order {orderid}")


def stop():
    """Stop the poller thread."""
    global _running
    _running = False
    logger.info("Order status poller stopped")


def get_queue_size():
    """Get current queue size (for monitoring)."""
    return _poll_queue.qsize()
