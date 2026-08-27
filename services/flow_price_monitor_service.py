# services/flow_price_monitor_service.py
"""
Flow Price Monitor Service
Real-time price monitoring for Price Alert triggers (Flask/sync version)
Uses polling instead of WebSocket for simplicity in Flask context
"""

import atexit
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

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
    # Guards _alerts together with _running/_stop_event/_monitor_thread. The
    # emptiness check that stops the loop and the registration that starts it
    # are check-then-act pairs run from both request threads and the monitor
    # thread itself, so they must not interleave. RLock because _check_alert
    # re-enters through remove_alert from inside the loop.
    _alerts_lock = threading.RLock()

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
        self._alerts_lock = threading.RLock()
        logger.debug("FlowPriceMonitor initialized")

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

        with self._alerts_lock:
            self._alerts[workflow_id] = alert
            logger.info(
                f"Added price alert for workflow {workflow_id}: "
                f"{symbol}@{exchange} {condition} {target_price}"
            )

            if not self._running:
                self._start_monitoring()

        return True

    def remove_alert(self, workflow_id: int) -> bool:
        """Remove a price alert for a workflow"""
        with self._alerts_lock:
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

        # Clear only the generation this call is stopping. A concurrent
        # _start_monitoring may already have installed a newer thread here, and
        # nulling that one would leave the live loop unreferenced and unjoinable.
        thread = self._monitor_thread
        if thread is not None:
            self._monitor_thread = None

        # remove_alert() is called from inside the monitoring loop when a
        # one-shot alert expires, and joining the current thread raises
        # RuntimeError. The loop exits on the stop event anyway.
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

        logger.info("Price monitoring stopped")

    def _monitoring_loop(self, stop_event: threading.Event | None = None):
        """Main monitoring loop that polls prices.

        Watches the event it was started with, not whatever the instance
        currently holds, so a restart cannot resurrect it.
        """
        from utils.db_sessions import remove_all_scoped_sessions

        stop_event = stop_event or self._stop_event
        while not stop_event.is_set():
            try:
                self._check_all_alerts()
            except Exception as e:
                logger.exception(f"Error in monitoring loop: {e}")
            finally:
                # Quote lookups bind scoped sessions to this thread, which has
                # no Flask app context, so teardown_appcontext never fires. Left
                # alone they accumulate a connection per generation of this loop.
                remove_all_scoped_sessions()

            # Wait for next poll interval
            stop_event.wait(timeout=self._poll_interval)

    def _check_all_alerts(self):
        """Check all active alerts against current prices"""
        with self._alerts_lock:
            workflow_ids = list(self._alerts.keys())

        for workflow_id in workflow_ids:
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

                if alert.trigger == "every_time":
                    # Keep watching; record the price so an edge-triggered
                    # crossing needs a fresh cross rather than re-firing.
                    alert.last_price = current_price

                # De-registration of a one-shot alert belongs to the run it
                # launched, not to this thread. Removing it here raced the
                # worker and lost: submit() usually keeps the GIL, so the alert
                # was gone before the pool thread read it and the run was
                # dropped as "no longer registered".
                self._trigger_workflow(alert, current_price)
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

    def _trigger_workflow(self, alert: PriceAlert, trigger_price: float):
        """Queue one execution for this alert, at most one at a time.

        Coalesced deliberately. The pool's queue is unbounded, so an every_time
        alert whose workflow runs slower than the poll interval would stack a
        task per tick and execute long after the price that caused it. One
        pending run per workflow keeps the alert responsive without a backlog.

        The whole alert object is passed, not its id, so the worker can prove
        the registration it is about to consume is still the one that produced
        it. A deactivate/reactivate cycle installs a new PriceAlert under the
        same id, and an id-keyed removal would delete that new one.
        """
        workflow_id = alert.workflow_id
        api_key = alert.api_key
        one_shot = alert.trigger != "every_time"

        with self._pending_lock:
            if workflow_id in self._pending:
                logger.debug(
                    f"Price alert for workflow {workflow_id} already has a run queued; "
                    "skipping this tick."
                )
                return
            self._pending.add(workflow_id)

        # Whether the workflow actually ran. A one-shot alert is only spent by
        # a run that reached the graph.
        executed = False

        def run_workflow():
            nonlocal executed
            try:
                # Re-checked here, not only at submit time: a queued run can sit
                # behind a slow execution while the alert is removed, the watch
                # expires, or the workflow is deactivated. execute_workflow does
                # not require the workflow to be active, so without this a stale
                # price event could still place orders.
                if self._alerts.get(workflow_id) is not alert:
                    logger.info(
                        f"Dropping queued price-alert run for workflow {workflow_id}: "
                        "the alert was removed or replaced before this run claimed it."
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
                # `already_running` means this event never reached the graph.
                # Anything else did run, whatever the broker made of it.
                executed = not result.get("already_running")

            except Exception as e:
                logger.exception(f"Failed to execute workflow {workflow_id}: {e}")
            finally:
                if one_shot:
                    if executed:
                        self._retire_one_shot(alert)
                    else:
                        # Nothing ran, so the alert must not be consumed. It was
                        # retired unconditionally here, which meant a one-shot
                        # colliding with an in-flight run -- or dropped by a
                        # guard above -- was silently spent and its workflow
                        # deactivated, with the event lost for good.
                        alert.triggered = False
                        logger.info(
                            f"Re-arming one-shot price alert for workflow {workflow_id}: "
                            "the run did not execute."
                        )
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
            # The one-shot latch is set before submitting, so that a second tick
            # cannot queue the same alert twice. If the submit itself fails the
            # latch has to come back off, or _check_all_alerts skips this alert
            # for the rest of the process and the trigger is dead.
            if one_shot:
                alert.triggered = False
                logger.error(
                    f"Could not queue the price-alert run for workflow {workflow_id}; "
                    "the alert stays armed."
                )
            raise

    def _retire_one_shot(self, alert: PriceAlert) -> None:
        """Consume a one-shot alert: drop the watch and clear the active flag.

        Both halves matter. Dropping only the in-memory watch left the row
        `is_active`, so the UI kept showing the workflow as armed, the activate
        endpoint answered `already_active` and refused to re-arm it, and
        `restore_price_alerts` would re-arm the spent alert on the next restart
        and fire an order the user believed was one-time.

        Removal is by identity, so a run that finishes after the user has
        deactivated and reactivated cannot delete the newer registration.
        """
        workflow_id = alert.workflow_id
        with self._alerts_lock:
            if self._alerts.get(workflow_id) is not alert:
                logger.debug(
                    f"One-shot price alert for workflow {workflow_id} was already "
                    "replaced; leaving the current registration alone."
                )
                return
            self.remove_alert(workflow_id)

        try:
            from database.flow_db import deactivate_workflow

            deactivate_workflow(workflow_id)
            logger.info(
                f"One-shot price alert for workflow {workflow_id} consumed; "
                "workflow deactivated."
            )
        except Exception:
            logger.exception(
                f"Could not deactivate workflow {workflow_id} after its one-shot "
                "price alert fired"
            )

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
        """Stop polling and release the worker pool.

        Registered with atexit below, mirroring the scalping risk monitor. It
        previously had no caller anywhere, so the poll thread and the executor
        pool were simply abandoned at process exit -- and unlike the sibling
        order-update monitor it never released the pool at all, leaving its
        threads and their file descriptors held.

        Idempotent: atexit may fire after an explicit call.
        """
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True

        self._stop_monitoring()
        with self._alerts_lock:
            self._alerts.clear()
        # Let an in-flight workflow finish rather than killing it mid-order; the
        # pool's threads are released with it instead of outliving the process.
        _WORKFLOW_POOL.shutdown(wait=False)
        logger.info("FlowPriceMonitor shutdown")


def restore_price_alerts() -> int:
    """Re-register alerts for already-active priceAlert workflows.

    Alerts live only in memory, but `is_active` is persisted. Without this, a
    server restart leaves such workflows marked active while watching nothing,
    and the activate endpoint rejects them as `already_active` -- so they stay
    silently dead until manually deactivated and reactivated. This mirrors
    restore_order_update_watches; call once at startup, after the DB is ready.

    Safe to call repeatedly: add_alert replaces the entry for a workflow id
    rather than stacking a second one. A one-shot alert that has already fired
    is not restored, because _retire_one_shot clears is_active when it is
    consumed -- otherwise every restart would re-arm a spent alert.
    """
    from database.flow_db import get_active_workflows, get_workflow_api_key

    monitor = get_flow_price_monitor()
    restored = 0
    for workflow in get_active_workflows():
        trigger_node = next(
            (n for n in (workflow.nodes or []) if n.get("type") == "priceAlert"), None
        )
        if not trigger_node:
            continue
        api_key = get_workflow_api_key(workflow)
        if not api_key:
            logger.warning(
                f"Cannot restore price alert for workflow {workflow.id}: no stored API key"
            )
            continue
        data = trigger_node.get("data", {}) or {}
        symbol = data.get("symbol", "")
        if not symbol:
            logger.warning(
                f"Cannot restore price alert for workflow {workflow.id}: no symbol configured"
            )
            continue
        try:
            monitor.add_alert(
                workflow_id=workflow.id,
                symbol=symbol,
                exchange=data.get("exchange", "NSE"),
                condition=data.get("condition", "greater_than"),
                target_price=float(data.get("price", 0) or 0),
                price_lower=data.get("priceLower"),
                price_upper=data.get("priceUpper"),
                percentage=data.get("percentage"),
                api_key=api_key,
                trigger=data.get("trigger", "once"),
                expiration=data.get("expiration", "none"),
            )
            restored += 1
        except (TypeError, ValueError) as e:
            logger.warning(f"Skipping invalid price alert for workflow {workflow.id}: {e}")
        except Exception:
            logger.exception(f"Failed to restore price alert for workflow {workflow.id}")
    if restored:
        logger.info(f"Restored {restored} price alert(s) from active workflows")
    return restored


# Singleton instance
flow_price_monitor = FlowPriceMonitor()

# Release the poll thread and the worker pool on the way out. Without this the
# monitor's file descriptors were held until the process was killed.
def _shutdown_at_exit() -> None:
    """atexit entry point.

    Logging handlers are often already closed by the time interpreter shutdown
    reaches us -- pytest closes its capture streams first -- and logging into a
    closed stream prints a "Logging error" traceback that looks like a fault
    but is only ordering. Nothing after this point needs a log line, so quiet
    the loggers before releasing the pool.
    """
    logging.disable(logging.CRITICAL)
    try:
        flow_price_monitor.shutdown()
    except Exception:
        pass


atexit.register(_shutdown_at_exit)


def get_flow_price_monitor() -> FlowPriceMonitor:
    """Get the global price monitor instance"""
    return flow_price_monitor
