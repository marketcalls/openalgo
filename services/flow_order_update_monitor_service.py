# services/flow_order_update_monitor_service.py
"""
Flow Order Update Monitor Service
Push-based trigger for the `orderUpdateTrigger` node: fires a workflow the
moment an order's status changes (filled, partially filled, rejected,
cancelled), instead of polling getOrderStatus in a loop.

Mirrors FlowPriceMonitor's singleton/add_alert/remove_alert shape
(services/flow_price_monitor_service.py) but is push-based: it subscribes
once to the existing in-process EventBus "order.update" topic (the same
OrderUpdateEvent already relayed to the account-level WebSocket stream —
see docs/prompt/websockets-format.md "Order Updates") instead of running its
own polling thread.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)

# order_status values a watch can match on; "any" matches every update.
VALID_STATUSES = {"any", "open", "trigger pending", "complete", "rejected", "cancelled"}


@dataclass
class OrderUpdateWatch:
    """One workflow's subscription to order-update events."""

    workflow_id: int
    api_key: str
    order_id: str | None = None
    symbol: str | None = None
    exchange: str | None = None
    status: str = "complete"
    trigger: str = "once"
    triggered: bool = False
    created_at: datetime = field(default_factory=datetime.now)


class FlowOrderUpdateMonitor:
    """Singleton service that fires workflows on live order-update events."""

    _instance: Optional["FlowOrderUpdateMonitor"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._watches: dict[int, OrderUpdateWatch] = {}
        self._watches_lock = threading.Lock()
        bus.subscribe("order.update", self._on_order_update, name="FlowOrderUpdateMonitor")
        logger.info("FlowOrderUpdateMonitor initialized (subscribed to order.update)")

    def add_watch(
        self,
        workflow_id: int,
        api_key: str,
        order_id: str | None = None,
        symbol: str | None = None,
        exchange: str | None = None,
        status: str = "complete",
        trigger: str = "once",
    ) -> bool:
        """Watch for order-update events matching the given filters.

        At least one of `order_id` / `symbol` must be set — an unfiltered
        watch would fire the workflow on every order in the account.
        """
        if not order_id and not symbol:
            raise ValueError("orderUpdateTrigger needs an Order ID or a Symbol to watch")
        watch = OrderUpdateWatch(
            workflow_id=workflow_id,
            api_key=api_key,
            order_id=order_id or None,
            symbol=symbol or None,
            exchange=exchange or None,
            status=status if status in VALID_STATUSES else "complete",
            trigger=trigger,
        )
        with self._watches_lock:
            self._watches[workflow_id] = watch
        logger.info(
            f"Added order-update watch for workflow {workflow_id}: "
            f"orderid={order_id} symbol={symbol} status={status}"
        )
        return True

    def remove_watch(self, workflow_id: int) -> bool:
        with self._watches_lock:
            return self._watches.pop(workflow_id, None) is not None

    def get_watch(self, workflow_id: int) -> OrderUpdateWatch | None:
        return self._watches.get(workflow_id)

    def get_status(self) -> dict[str, Any]:
        with self._watches_lock:
            watches = list(self._watches.values())
        return {
            "watches_count": len(watches),
            "watches": [
                {
                    "workflow_id": w.workflow_id,
                    "order_id": w.order_id,
                    "symbol": w.symbol,
                    "exchange": w.exchange,
                    "status": w.status,
                    "triggered": w.triggered,
                }
                for w in watches
            ],
        }

    def _on_order_update(self, event) -> None:
        """EventBus callback — runs on the bus's shared thread pool, so keep
        it fast and hand off actual workflow execution to its own thread."""
        with self._watches_lock:
            matches = [
                w for w in self._watches.values() if not w.triggered and self._matches(w, event)
            ]
        for watch in matches:
            self._fire(watch, event)

    @staticmethod
    def _matches(watch: OrderUpdateWatch, event) -> bool:
        if watch.status != "any" and event.order_status != watch.status:
            return False
        if watch.order_id and event.orderid != watch.order_id:
            return False
        if watch.symbol and event.symbol != watch.symbol:
            return False
        if watch.exchange and event.exchange and event.exchange != watch.exchange:
            return False
        return True

    def _fire(self, watch: OrderUpdateWatch, event) -> None:
        watch.triggered = True
        logger.info(
            f"Order-update trigger fired for workflow {watch.workflow_id}: "
            f"orderid={event.orderid} status={event.order_status}"
        )

        def run_workflow():
            try:
                from services.flow_executor_service import execute_workflow

                webhook_data = {
                    "trigger_type": "order_update",
                    "orderid": event.orderid,
                    "symbol": event.symbol,
                    "exchange": event.exchange,
                    "order_status": event.order_status,
                    "filled_quantity": event.filled_quantity,
                    "average_price": event.average_price,
                    "rejection_reason": getattr(event, "rejection_reason", ""),
                    "triggered_at": datetime.now().isoformat(),
                }
                result = execute_workflow(
                    watch.workflow_id, webhook_data=webhook_data, api_key=watch.api_key
                )
                logger.info(
                    f"Workflow {watch.workflow_id} execution result: {result.get('status')}"
                )
            except Exception:
                logger.exception(f"Failed to execute workflow {watch.workflow_id}")
            finally:
                if watch.trigger != "every_time":
                    self.remove_watch(watch.workflow_id)
                else:
                    watch.triggered = False

        threading.Thread(target=run_workflow, daemon=True).start()

    def shutdown(self):
        bus.unsubscribe("order.update", self._on_order_update)
        with self._watches_lock:
            self._watches.clear()
        logger.info("FlowOrderUpdateMonitor shutdown")


# Singleton instance
flow_order_update_monitor = FlowOrderUpdateMonitor()


def get_flow_order_update_monitor() -> FlowOrderUpdateMonitor:
    """Get the global order-update monitor instance"""
    return flow_order_update_monitor
