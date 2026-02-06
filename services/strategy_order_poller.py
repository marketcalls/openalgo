"""
Strategy Order Status Poller

Single background thread that polls the OrderStatus API at 1 req/sec rate limit.
Uses a priority queue: exit orders (SL/target triggers) are polled before entries.

On completion:
- Updates StrategyOrder status
- Routes to StrategyPositionTracker for position creation/update
- Emits SocketIO events for real-time UI updates

On restart: loads all pending orders from DB and re-queues them.
"""

import os
import queue
import threading
import time

from utils.logging import get_logger

logger = get_logger(__name__)

# Priority levels: lower = higher priority
EXIT_PRIORITY = 0  # Exit orders polled first (time-critical)
ENTRY_PRIORITY = 1  # Entry orders polled after exits

POLL_INTERVAL = float(os.getenv("STRATEGY_ORDER_POLL_INTERVAL", "1"))


class OrderStatusPoller:
    """Polls broker OrderStatus API for strategy order fills.

    Single daemon thread, rate-limited to 1 request/second.
    Priority queue ensures exit order confirmations are processed first.
    """

    def __init__(self):
        self._queue = queue.PriorityQueue()
        self._thread = None
        self._running = False
        self._counter = 0  # Tie-breaker for same-priority items (FIFO within priority)
        self._lock = threading.Lock()

    def start(self):
        """Start the poller background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="StrategyOrderPoller")
        self._thread.start()
        logger.info("OrderStatusPoller started")

    def stop(self):
        """Stop the poller."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("OrderStatusPoller stopped")

    def queue_order(self, orderid, strategy_id, strategy_type, user_id, is_entry=True, exit_reason=None):
        """Add an order to the polling queue.

        Args:
            orderid: Broker order ID
            strategy_id: Strategy that placed this order
            strategy_type: 'webhook' or 'chartink'
            user_id: User who owns the strategy
            is_entry: True for entry orders, False for exit orders
            exit_reason: For exits: stoploss/target/trailstop/manual/squareoff
        """
        priority = ENTRY_PRIORITY if is_entry else EXIT_PRIORITY
        with self._lock:
            self._counter += 1
            counter = self._counter

        item = {
            "orderid": orderid,
            "strategy_id": strategy_id,
            "strategy_type": strategy_type,
            "user_id": user_id,
            "is_entry": is_entry,
            "exit_reason": exit_reason,
            "retry_count": 0,
        }
        self._queue.put((priority, counter, item))
        logger.info(
            f"Queued order {orderid} for polling (priority={'ENTRY' if is_entry else 'EXIT'}, "
            f"strategy={strategy_id}/{strategy_type})"
        )

    def reload_pending_orders(self):
        """Reload all pending/open orders from DB for restart recovery."""
        try:
            from database.strategy_position_db import get_pending_orders

            pending = get_pending_orders()
            count = 0
            for order in pending:
                self.queue_order(
                    orderid=order.orderid,
                    strategy_id=order.strategy_id,
                    strategy_type=order.strategy_type,
                    user_id=order.user_id,
                    is_entry=order.is_entry,
                    exit_reason=order.exit_reason,
                )
                count += 1
            if count > 0:
                logger.info(f"Reloaded {count} pending orders for polling")
        except Exception as e:
            logger.exception(f"Error reloading pending orders: {e}")

    @property
    def queue_size(self):
        """Current number of orders waiting to be polled."""
        return self._queue.qsize()

    def _poll_loop(self):
        """Main polling loop — runs in background thread."""
        while self._running:
            try:
                # Block with timeout so we can check _running flag
                try:
                    priority, counter, item = self._queue.get(timeout=2)
                except queue.Empty:
                    continue

                self._process_order(item)

                # Rate limit: 1 request per second
                time.sleep(POLL_INTERVAL)

            except Exception as e:
                logger.exception(f"Error in poll loop: {e}")
                time.sleep(POLL_INTERVAL)

    def _process_order(self, item):
        """Process a single order — poll status and route result."""
        orderid = item["orderid"]
        strategy_id = item["strategy_id"]
        strategy_type = item["strategy_type"]
        user_id = item["user_id"]
        is_entry = item["is_entry"]
        exit_reason = item.get("exit_reason")

        try:
            # Get auth credentials for this user
            from database.auth_db import get_api_key_for_tradingview, get_auth_token_broker

            api_key = get_api_key_for_tradingview(user_id)
            if not api_key:
                logger.error(f"No API key for user {user_id}, cannot poll order {orderid}")
                return

            auth_token, broker = get_auth_token_broker(api_key)
            if auth_token is None:
                logger.error(f"Invalid auth for user {user_id}, cannot poll order {orderid}")
                return

            # Call OrderStatus service
            from services.orderstatus_service import get_order_status_with_auth

            status_data = {"orderid": orderid}
            original_data = {"orderid": orderid, "apikey": api_key}
            success, response, status_code = get_order_status_with_auth(
                status_data, auth_token, broker, original_data
            )

            if not success:
                logger.warning(f"OrderStatus failed for {orderid}: {response.get('message', 'unknown')}")
                self._handle_retry(item)
                return

            order_data = response.get("data", {})
            order_status = order_data.get("order_status", "").lower()
            average_price = float(order_data.get("average_price", 0))
            filled_quantity = int(order_data.get("filled_quantity", order_data.get("quantity", 0)))

            logger.info(
                f"Order {orderid} status={order_status}, avg_price={average_price}, "
                f"filled_qty={filled_quantity}"
            )

            if order_status == "complete":
                self._on_complete(item, average_price, filled_quantity)
            elif order_status in ("rejected", "cancelled"):
                self._on_rejected_or_cancelled(item, order_status, order_data)
            elif order_status in ("open", "pending", "trigger pending"):
                # Still pending — re-queue at same priority
                self._requeue(item)
            else:
                logger.warning(f"Unknown order status '{order_status}' for {orderid}")
                self._requeue(item)

        except Exception as e:
            logger.exception(f"Error processing order {orderid}: {e}")
            self._handle_retry(item)
        finally:
            # Clean up scoped session for this thread
            try:
                from database.strategy_position_db import db_session

                db_session.remove()
            except Exception:
                pass

    def _on_complete(self, item, average_price, filled_quantity):
        """Handle a completed (filled) order."""
        orderid = item["orderid"]
        is_entry = item["is_entry"]

        # Update order record in DB
        from database.strategy_position_db import update_order_status

        update_order_status(orderid, "complete", average_price, filled_quantity)

        # Emit SocketIO event
        self._emit_order_event("strategy_order_filled", item, {
            "average_price": average_price,
            "filled_quantity": filled_quantity,
        })

        # Route to position tracker
        try:
            from services.strategy_position_tracker import position_tracker

            if is_entry:
                position_tracker.on_entry_fill(item, average_price, filled_quantity)
            else:
                position_tracker.on_exit_fill(item, average_price, filled_quantity)
        except Exception as e:
            logger.exception(f"Error routing fill for {orderid} to position tracker: {e}")

    def _on_rejected_or_cancelled(self, item, status, order_data):
        """Handle a rejected or cancelled order."""
        orderid = item["orderid"]
        is_entry = item["is_entry"]

        from database.strategy_position_db import update_order_status

        update_order_status(orderid, status)

        event_name = f"strategy_order_{status}"
        self._emit_order_event(event_name, item, {
            "reason": order_data.get("rejection_reason", order_data.get("text", "")),
        })

        # If exit order was rejected, position stays open — clear exiting state
        if not is_entry:
            try:
                from database.strategy_position_db import (
                    StrategyPosition,
                    db_session,
                    get_active_positions,
                )

                # Find the position that was being exited and reset its state
                positions = get_active_positions(
                    strategy_id=item["strategy_id"],
                    symbol=order_data.get("symbol"),
                    exchange=order_data.get("exchange"),
                )
                for pos in positions:
                    if pos.position_state == "exiting":
                        pos.position_state = "active"
                        pos.exit_reason = None
                        pos.exit_detail = None
                        db_session.commit()
                        logger.warning(
                            f"Exit order {orderid} {status} — position {pos.id} reset to active"
                        )
            except Exception as e:
                logger.exception(f"Error resetting position state after {status}: {e}")

    def _requeue(self, item):
        """Re-queue an order that is still pending."""
        priority = ENTRY_PRIORITY if item["is_entry"] else EXIT_PRIORITY
        with self._lock:
            self._counter += 1
            counter = self._counter
        self._queue.put((priority, counter, item))

    def _handle_retry(self, item):
        """Handle retry logic for failed polls."""
        item["retry_count"] = item.get("retry_count", 0) + 1
        max_retries = 30  # Give up after 30 failed attempts (~30 seconds)
        if item["retry_count"] < max_retries:
            self._requeue(item)
        else:
            logger.error(
                f"Giving up on order {item['orderid']} after {max_retries} retries"
            )

    def _emit_order_event(self, event_name, item, extra_data=None):
        """Emit a SocketIO event for an order status change."""
        try:
            from extensions import socketio

            payload = {
                "orderid": item["orderid"],
                "strategy_id": item["strategy_id"],
                "strategy_type": item["strategy_type"],
                "is_entry": item["is_entry"],
                "exit_reason": item.get("exit_reason"),
            }
            if extra_data:
                payload.update(extra_data)

            socketio.emit(event_name, payload)
        except Exception as e:
            logger.debug(f"Error emitting {event_name}: {e}")


# Module-level singleton
order_poller = OrderStatusPoller()
