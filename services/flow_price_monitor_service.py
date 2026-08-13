# services/flow_price_monitor_service.py
"""
Flow Price Monitor Service
Real-time price monitoring for Price Alert triggers (Flask/sync version)
Uses polling instead of WebSocket for simplicity in Flask context
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Set

from services.flow_openalgo_client import FlowOpenAlgoClient, get_flow_client
from utils.env_config import env_int
from utils.logging import get_logger

logger = get_logger(__name__)

# Shared and bounded, never one thread per fire: an every_time alert on a fast
# poll interval would otherwise spawn a thread per tick, each running a whole
# workflow. Mirrors the order-update monitor's pool.
_WORKFLOW_POOL = ThreadPoolExecutor(
    max_workers=env_int("FLOW_PRICE_ALERT_WORKERS", 4, minimum=1),
    thread_name_prefix="flow-price-alert",
)


@dataclass
class PriceAlert:
    """Represents an active price alert"""

    workflow_id: int
    symbol: str
    exchange: str
    condition: str
    target_price: float
    price_lower: float | None = None
    price_upper: float | None = None
    percentage: float | None = None
    last_price: float | None = None
    triggered: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    api_key: str | None = None
    # The editor offers these; they were previously dropped at activation, so
    # "Every Time" silently behaved as "Only Once" and expiry never applied.
    trigger: str = "once"
    expiration: str = "none"


class FlowPriceMonitor:
    """
    Singleton service that monitors prices using polling
    and triggers workflows when price conditions are met.
    """

    _instance: Optional["FlowPriceMonitor"] = None
    _lock = threading.Lock()

    # Class-level defaults. _trigger_workflow relies on these, and an instance
    # can exist without __init__ having run (the singleton is created in
    # __new__, and test harnesses build one directly), so they must never be
    # merely instance attributes.
    _pending: set[int] = set()
    _pending_lock = threading.Lock()

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
        self._alerts: dict[int, PriceAlert] = {}
        self._running = False
        self._monitor_thread: threading.Thread | None = None
        self._poll_interval = 5  # seconds
        self._stop_event = threading.Event()
        # Workflows with a queued or running price-alert execution, so a tick
        # cannot stack another one behind it. Class-level defaults above cover
        # an instance built without __init__.
        self._pending = set()
        self._pending_lock = threading.Lock()
        logger.info("FlowPriceMonitor initialized")

    # The editor and this monitor grew separate vocabularies for the same four
    # conditions, so every alert the UI could produce fell through to the final
    # `return False` and the trigger never fired. Both spellings are accepted;
    # the UI's are the ones users actually have saved.
    _CONDITION_ALIASES = {
        "above": "greater_than",
        "price_above": "greater_than",
        "below": "less_than",
        "price_below": "less_than",
        "crosses_above": "crossing_up",
        "cross_above": "crossing_up",
        "crosses_below": "crossing_down",
        "cross_below": "crossing_down",
        "crosses": "crossing",
    }

    @classmethod
    def normalize_condition(cls, value: str | None) -> str:
        """Canonical condition name, accepting either vocabulary."""
        raw = str(value or "").strip().lower().replace("-", "_")
        return cls._CONDITION_ALIASES.get(raw, raw)

    def add_alert(
        self,
        workflow_id: int,
        symbol: str,
        exchange: str,
        condition: str,
        target_price: float,
        price_lower: float | None = None,
        price_upper: float | None = None,
        percentage: float | None = None,
        api_key: str | None = None,
        trigger: str = "once",
        expiration: str = "none",
    ) -> bool:
        """Add a price alert for a workflow"""
        condition = self.normalize_condition(condition)
        alert = PriceAlert(
            workflow_id=workflow_id,
            symbol=symbol,
            exchange=exchange,
            condition=condition,
            target_price=target_price,
            price_lower=price_lower,
            price_upper=price_upper,
            percentage=percentage,
            api_key=api_key,
            trigger=str(trigger or "once").strip().lower(),
            expiration=str(expiration or "none").strip().lower(),
        )

        self._alerts[workflow_id] = alert
        logger.info(
            f"Added price alert for workflow {workflow_id}: {symbol}@{exchange} {condition} {target_price}"
        )

        if not self._running:
            self._start_monitoring()

        return True

    def remove_alert(self, workflow_id: int) -> bool:
        """Remove a price alert for a workflow"""
        if workflow_id not in self._alerts:
            return False

        del self._alerts[workflow_id]
        logger.info(f"Removed price alert for workflow {workflow_id}")

        if not self._alerts and self._running:
            self._stop_monitoring()

        return True

    def get_alert(self, workflow_id: int) -> PriceAlert | None:
        """Get alert for a workflow"""
        return self._alerts.get(workflow_id)

    def get_active_alerts_count(self) -> int:
        """Get count of active alerts"""
        return len(self._alerts)

    def _start_monitoring(self):
        """Start the price monitoring thread"""
        if self._running:
            return

        # A fresh event per generation. Sharing one and clearing it on restart
        # revived a previous loop that had been told to stop but had not yet
        # exited, leaving two loops polling and double-submitting every_time
        # executions.
        self._stop_event = threading.Event()
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitoring_loop, args=(self._stop_event,), daemon=True
        )
        self._monitor_thread.start()
        logger.info(f"Price monitoring started with {len(self._alerts)} alerts")

    def _stop_monitoring(self):
        """Stop the price monitoring thread"""
        if not self._running:
            return

        # Signals only this generation. A later start creates its own event, so
        # this loop can never be un-stopped by a restart.
        self._stop_event.set()
        self._running = False

        if self._monitor_thread:
            # remove_alert() is called from inside the monitoring loop when a
            # one-shot alert fires or expires, and joining the current thread
            # raises RuntimeError. The loop exits on the stop event anyway.
            if self._monitor_thread is not threading.current_thread():
                self._monitor_thread.join(timeout=5)
            self._monitor_thread = None

        logger.info("Price monitoring stopped")

    def _monitoring_loop(self, stop_event: threading.Event | None = None):
        """Main monitoring loop that polls prices.

        Watches the event it was started with, not whatever the instance
        currently holds, so a restart cannot resurrect it.
        """
        stop_event = stop_event or self._stop_event
        while not stop_event.is_set():
            try:
                self._check_all_alerts()
            except Exception as e:
                logger.exception(f"Error in monitoring loop: {e}")

            # Wait for next poll interval
            stop_event.wait(timeout=self._poll_interval)

    def _check_all_alerts(self):
        """Check all active alerts against current prices"""
        for workflow_id in list(self._alerts.keys()):
            alert = self._alerts.get(workflow_id)
            if alert and not alert.triggered:
                try:
                    self._check_alert(alert)
                except Exception as e:
                    logger.exception(f"Error checking alert for workflow {workflow_id}: {e}")

    # Windows the editor offers for "expiration". A watch past its window is
    # removed rather than left running for the life of the process.
    _EXPIRATION_WINDOWS = {
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
        "1w": timedelta(weeks=1),
    }

    def _is_expired(self, alert: PriceAlert) -> bool:
        window = self._EXPIRATION_WINDOWS.get(alert.expiration)
        if window is None:
            return False
        return datetime.now() - alert.created_at >= window

    def _check_alert(self, alert: PriceAlert):
        """Check a single alert against current price"""
        if not alert.api_key:
            logger.warning(f"No API key for alert workflow {alert.workflow_id}")
            return

        if self._is_expired(alert):
            logger.info(
                f"Price alert for workflow {alert.workflow_id} expired after "
                f"{alert.expiration}; no longer watching."
            )
            self.remove_alert(alert.workflow_id)
            return

        try:
            client = get_flow_client(alert.api_key)
            result = client.get_quotes(symbol=alert.symbol, exchange=alert.exchange)

            if result.get("status") != "success":
                logger.debug(f"Failed to get quote for {alert.symbol}: {result}")
                return

            data = result.get("data", {})
            current_price = float(data.get("ltp", 0) if data else 0)

            if current_price <= 0:
                return

            condition_met = self._evaluate_condition(alert, current_price)

            if condition_met and not alert.triggered:
                # `triggered` is the one-shot latch, and _check_all_alerts skips
                # any alert carrying it. Setting it for an every_time alert left
                # the watch registered but permanently ignored.
                if alert.trigger != "every_time":
                    alert.triggered = True
                logger.info(
                    f"Price alert triggered for workflow {alert.workflow_id}: "
                    f"{alert.symbol}@{alert.exchange} {alert.condition} "
                    f"(price: {current_price}, target: {alert.target_price})"
                )

                self._trigger_workflow(alert.workflow_id, current_price, alert.api_key)
                if alert.trigger == "every_time":
                    # Keep watching; record the price so an edge-triggered
                    # crossing needs a fresh cross rather than re-firing.
                    alert.last_price = current_price
                else:
                    self.remove_alert(alert.workflow_id)
            else:
                alert.last_price = current_price

        except Exception as e:
            logger.exception(f"Error checking price for {alert.symbol}: {e}")

    def _evaluate_condition(self, alert: PriceAlert, current_price: float) -> bool:
        """Evaluate if the price condition is met"""
        condition = self.normalize_condition(alert.condition)
        target = alert.target_price
        last_price = alert.last_price

        tolerance = current_price * 0.001

        if condition == "greater_than":
            return current_price > target

        elif condition == "less_than":
            return current_price < target

        elif condition == "crossing":
            return abs(current_price - target) <= tolerance

        elif condition == "crossing_up":
            if last_price is None:
                return current_price > target
            return last_price <= target and current_price > target

        elif condition == "crossing_down":
            if last_price is None:
                return current_price < target
            return last_price >= target and current_price < target

        elif condition in ["entering_channel", "inside_channel"]:
            lower = alert.price_lower or target
            upper = alert.price_upper or target
            return lower <= current_price <= upper

        elif condition in ["exiting_channel", "outside_channel"]:
            lower = alert.price_lower or target
            upper = alert.price_upper or target
            return current_price < lower or current_price > upper

        elif condition == "moving_up":
            if last_price is None:
                return False
            return current_price > last_price

        elif condition == "moving_down":
            if last_price is None:
                return False
            return current_price < last_price

        elif condition == "moving_up_percent":
            if last_price is None or last_price == 0:
                return False
            pct_change = ((current_price - last_price) / last_price) * 100
            return pct_change >= (alert.percentage or 0)

        elif condition == "moving_down_percent":
            if last_price is None or last_price == 0:
                return False
            pct_change = ((last_price - current_price) / last_price) * 100
            return pct_change >= (alert.percentage or 0)

        # Never silently false: an unknown condition means the alert can never
        # fire, which is indistinguishable from "the level was not reached".
        logger.error(
            f"Price alert for workflow {alert.workflow_id} has an unrecognized "
            f"condition {alert.condition!r}; it can never trigger."
        )
        return False

    def _trigger_workflow(self, workflow_id: int, trigger_price: float, api_key: str):
        """Queue one execution for this workflow, at most one at a time.

        Coalesced deliberately. The pool's queue is unbounded, so an every_time
        alert whose workflow runs slower than the poll interval would stack a
        task per tick and execute long after the price that caused it. One
        pending run per workflow keeps the alert responsive without a backlog.
        """
        with self._pending_lock:
            if workflow_id in self._pending:
                logger.debug(
                    f"Price alert for workflow {workflow_id} already has a run queued; "
                    "skipping this tick."
                )
                return
            self._pending.add(workflow_id)

        def run_workflow():
            try:
                # Re-checked here, not only at submit time: a queued run can sit
                # behind a slow execution while the alert is removed, the watch
                # expires, or the workflow is deactivated. execute_workflow does
                # not require the workflow to be active, so without this a stale
                # price event could still place orders.
                if workflow_id not in self._alerts:
                    logger.info(
                        f"Dropping queued price-alert run for workflow {workflow_id}: "
                        "the alert is no longer registered."
                    )
                    return
                if not self._workflow_is_active(workflow_id):
                    logger.info(
                        f"Dropping queued price-alert run for workflow {workflow_id}: "
                        "the workflow is no longer active."
                    )
                    return

                from services.flow_executor_service import execute_workflow

                webhook_data = {
                    "trigger_type": "price_alert",
                    "trigger_price": trigger_price,
                    "triggered_at": datetime.now().isoformat(),
                }

                result = execute_workflow(workflow_id, webhook_data=webhook_data, api_key=api_key)
                logger.info(f"Workflow {workflow_id} execution result: {result.get('status')}")

            except Exception as e:
                logger.exception(f"Failed to execute workflow {workflow_id}: {e}")
            finally:
                with self._pending_lock:
                    self._pending.discard(workflow_id)
                # No Flask app context on a pool thread, so teardown_appcontext
                # never fires and every session the run touched would stay bound
                # to the thread holding its connection.
                from utils.db_sessions import remove_all_scoped_sessions

                remove_all_scoped_sessions()

        try:
            _WORKFLOW_POOL.submit(run_workflow)
        except Exception:
            with self._pending_lock:
                self._pending.discard(workflow_id)
            raise

    @staticmethod
    def _workflow_is_active(workflow_id: int) -> bool:
        """Whether the workflow is still active. Fails closed on error."""
        try:
            from database.flow_db import get_workflow

            workflow = get_workflow(workflow_id)
            return bool(workflow and workflow.is_active)
        except Exception:
            logger.exception(f"Could not confirm workflow {workflow_id} is active")
            return False

    def is_running(self) -> bool:
        """Check if monitoring is active"""
        return self._running

    def get_status(self) -> dict[str, Any]:
        """Get current monitor status"""
        return {
            "running": self._running,
            "alerts_count": len(self._alerts),
            "poll_interval": self._poll_interval,
            "alerts": [
                {
                    "workflow_id": alert.workflow_id,
                    "symbol": alert.symbol,
                    "exchange": alert.exchange,
                    "condition": alert.condition,
                    "target_price": alert.target_price,
                    "last_price": alert.last_price,
                    "triggered": alert.triggered,
                }
                for alert in self._alerts.values()
            ],
        }

    def shutdown(self):
        """Shutdown the price monitor"""
        self._stop_monitoring()
        self._alerts.clear()
        logger.info("FlowPriceMonitor shutdown")


# Singleton instance
flow_price_monitor = FlowPriceMonitor()


def get_flow_price_monitor() -> FlowPriceMonitor:
    """Get the global price monitor instance"""
    return flow_price_monitor
