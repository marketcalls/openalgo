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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from utils.env_config import env_int
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)

# Shared and bounded, never one thread per event: order updates arrive in
# bursts (a basket filling leg by leg), and each run executes a whole workflow
# holding DB sessions and broker calls. A module-level pool caps that
# concurrency and reuses its threads for the life of the worker.
_WORKFLOW_POOL = ThreadPoolExecutor(
    max_workers=env_int("FLOW_ORDER_UPDATE_WORKERS", 4, minimum=1),
    thread_name_prefix="flow-order-update",
)

# order_status values a watch can match on; "any" matches every update.
VALID_STATUSES = {"any", "open", "trigger pending", "complete", "rejected", "cancelled"}


def normalize_status(value: str | None) -> str:
    """Canonicalize an order_status for comparison.

    Broker adapters disagree on the multi-word spelling: Zerodha's order
    adapter emits "trigger pending" (matching docs/prompt/websockets-format.md
    and the sandbox engine) while other paths use "trigger_pending". Comparing
    raw strings makes the Trigger Pending filter silently never match. Fold
    underscores to spaces and lowercase so both spellings compare equal.
    """
    return str(value or "").strip().lower().replace("_", " ")


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
    # Owning account (OpenAlgo username), resolved from the workflow's API key
    # at activation. Used to keep one account's order events from firing
    # another account's watch — see _matches().
    user_id: str | None = None
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
        logger.debug("FlowOrderUpdateMonitor initialized (subscribed to order.update)")

    def add_watch(
        self,
        workflow_id: int,
        api_key: str,
        order_id: str | None = None,
        symbol: str | None = None,
        exchange: str | None = None,
        status: str = "complete",
        trigger: str = "once",
        user_id: str | None = None,
    ) -> bool:
        """Watch for order-update events matching the given filters.

        At least one of `order_id` / `symbol` must be set — an unfiltered
        watch would fire the workflow on every order in the account.

        `order_id` must be a literal broker order id. `{{...}}` interpolation
        is rejected: a trigger node has no upstream context to resolve
        against, so the placeholder would be stored verbatim and could never
        match a real order id.
        """
        if not order_id and not symbol:
            raise ValueError("orderUpdateTrigger needs an Order ID or a Symbol to watch")
        if order_id and "{{" in order_id:
            raise ValueError(
                "orderUpdateTrigger Order ID must be a literal order id, not a "
                "{{variable}} reference - a trigger node has no upstream node to "
                "resolve it from. Leave it blank and filter by Symbol instead."
            )
        normalized_status = normalize_status(status)
        if normalized_status not in VALID_STATUSES:
            raise ValueError(
                f"orderUpdateTrigger status must be one of {sorted(VALID_STATUSES)}, got {status!r}"
            )
        if user_id is None:
            user_id = self._resolve_user_id(api_key) if api_key else None
        if not user_id:
            # Fail closed. An unscoped watch would match any account's order
            # event and then execute this workflow with the stored API key.
            raise ValueError(
                "orderUpdateTrigger could not resolve the owning account from the "
                "workflow's API key. Re-save the workflow with a valid API key."
            )
        watch = OrderUpdateWatch(
            workflow_id=workflow_id,
            api_key=api_key,
            order_id=order_id or None,
            symbol=symbol or None,
            exchange=exchange or None,
            status=normalized_status,
            trigger=trigger,
            user_id=user_id,
        )
        with self._watches_lock:
            self._watches[workflow_id] = watch
        logger.info(
            f"Added order-update watch for workflow {workflow_id}: "
            f"orderid={order_id} symbol={symbol} status={normalized_status} user={user_id}"
        )
        return True

    @staticmethod
    def _resolve_user_id(api_key: str) -> str | None:
        """Map an OpenAlgo API key to its owning username (the same identity
        order adapters put in event.request_data["user_id"])."""
        try:
            from database.auth_db import verify_api_key

            return verify_api_key(api_key)
        except Exception:
            logger.exception("Could not resolve owner for order-update watch")
            return None

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
        it fast and hand off actual workflow execution to its own thread.

        The `triggered` claim is made *inside* the lock: the bus dispatches
        callbacks on a pool, so two order events arriving concurrently could
        otherwise both pass a `not w.triggered` check and fire a `once` watch
        twice (duplicate orders).
        """
        claimed = []
        with self._watches_lock:
            for watch in self._watches.values():
                if watch.triggered or not self._matches(watch, event):
                    continue
                watch.triggered = True  # atomic claim under the lock
                claimed.append(watch)
        for watch in claimed:
            self._fire(watch, event)

    @staticmethod
    def _event_user_id(event) -> str | None:
        """Owning account of an order event, as set by the order adapters and
        the sandbox engine in `request_data["user_id"]`."""
        data = getattr(event, "request_data", None) or {}
        user_id = data.get("user_id")
        return str(user_id) if user_id else None

    def _matches(self, watch: OrderUpdateWatch, event) -> bool:
        # Account scoping. A workflow executes with its owner's API key, so a
        # symbol-only watch must never be fired by a different account's fill.
        # Strict: an event that carries no identity cannot satisfy an
        # owner-scoped watch. Order adapters always populate user_id, and the
        # sandbox engine takes it as a required constructor argument, so a
        # missing value means the event's origin is unknown - not that it
        # belongs to this account.
        if watch.user_id and self._event_user_id(event) != watch.user_id:
            return False
        if watch.status != "any" and normalize_status(event.order_status) != watch.status:
            return False
        if watch.order_id and event.orderid != watch.order_id:
            return False
        if watch.symbol and event.symbol != watch.symbol:
            return False
        # An explicit exchange filter must not be satisfied by a missing value.
        if watch.exchange and event.exchange != watch.exchange:
            return False
        return True

    def _fire(self, watch: OrderUpdateWatch, event) -> None:
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
                # No app context here, so teardown_appcontext never runs and
                # every scoped session this workflow touched would stay bound
                # to the pool thread, holding its connection indefinitely.
                from utils.db_sessions import remove_all_scoped_sessions

                remove_all_scoped_sessions()

        _WORKFLOW_POOL.submit(run_workflow)

    def shutdown(self):
        bus.unsubscribe("order.update", self._on_order_update)
        with self._watches_lock:
            self._watches.clear()
        # Let in-flight workflows finish; the pool's threads are released with
        # it rather than left running past shutdown.
        _WORKFLOW_POOL.shutdown(wait=False)
        logger.info("FlowOrderUpdateMonitor shutdown")


# Singleton instance
flow_order_update_monitor = FlowOrderUpdateMonitor()


def get_flow_order_update_monitor() -> FlowOrderUpdateMonitor:
    """Get the global order-update monitor instance"""
    return flow_order_update_monitor


def restore_order_update_watches() -> int:
    """Re-register watches for already-active orderUpdateTrigger workflows.

    Watches live only in memory, but `is_active` is persisted. Without this,
    a server restart leaves such workflows marked active while firing
    nothing, and the activate endpoint rejects them as `already_active` — so
    they stay silently dead until manually deactivated and reactivated.
    Call once at startup, after the DB is ready.
    """
    from database.flow_db import get_active_workflows, get_workflow_api_key

    monitor = get_flow_order_update_monitor()
    restored = 0
    for workflow in get_active_workflows():
        trigger_node = next(
            (n for n in (workflow.nodes or []) if n.get("type") == "orderUpdateTrigger"), None
        )
        if not trigger_node:
            continue
        api_key = get_workflow_api_key(workflow)
        if not api_key:
            logger.warning(
                f"Cannot restore order-update watch for workflow {workflow.id}: no stored API key"
            )
            continue
        data = trigger_node.get("data", {}) or {}
        try:
            monitor.add_watch(
                workflow_id=workflow.id,
                api_key=api_key,
                order_id=data.get("orderId") or None,
                symbol=data.get("symbol") or None,
                exchange=data.get("exchange") or None,
                status=data.get("status", "complete"),
                trigger=data.get("trigger", "once"),
            )
            restored += 1
        except ValueError as e:
            logger.warning(f"Skipping invalid order-update watch for workflow {workflow.id}: {e}")
        except Exception:
            logger.exception(f"Failed to restore order-update watch for workflow {workflow.id}")
    if restored:
        logger.info(f"Restored {restored} order-update watch(es) from active workflows")
    return restored
