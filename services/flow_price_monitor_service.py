# services/flow_price_monitor_service.py
"""
Flow Price Monitor Service
Real-time price monitoring for Price Alert triggers (Flask/sync version)
Uses polling instead of WebSocket for simplicity in Flask context
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Set

from services.flow_openalgo_client import FlowOpenAlgoClient, get_flow_client

logger = logging.getLogger(__name__)


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


class FlowPriceMonitor:
    """
    Singleton service that monitors prices using polling
    and triggers workflows when price conditions are met.
    """

    _instance: Optional["FlowPriceMonitor"] = None
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
        self._alerts: dict[int, PriceAlert] = {}
        self._running = False
        self._monitor_thread: threading.Thread | None = None
        self._poll_interval = 5  # seconds
        self._stop_event = threading.Event()
        logger.info("FlowPriceMonitor initialized")

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
    ) -> bool:
        """Add a price alert for a workflow"""
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

        self._stop_event.clear()
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self._monitor_thread.start()
        logger.info(f"Price monitoring started with {len(self._alerts)} alerts")

    def _stop_monitoring(self):
        """Stop the price monitoring thread"""
        if not self._running:
            return

        self._stop_event.set()
        self._running = False

        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None

        logger.info("Price monitoring stopped")

    def _monitoring_loop(self):
        """Main monitoring loop that polls prices"""
        while not self._stop_event.is_set():
            try:
                self._check_all_alerts()
            except Exception as e:
                logger.exception(f"Error in monitoring loop: {e}")

            # Wait for next poll interval
            self._stop_event.wait(timeout=self._poll_interval)

    def _check_all_alerts(self):
        """Check all active alerts against current prices"""
        for workflow_id in list(self._alerts.keys()):
            alert = self._alerts.get(workflow_id)
            if alert and not alert.triggered:
                try:
                    self._check_alert(alert)
                except Exception as e:
                    logger.exception(f"Error checking alert for workflow {workflow_id}: {e}")

    def _check_alert(self, alert: PriceAlert):
        """Check a single alert against current price"""
        if not alert.api_key:
            logger.warning(f"No API key for alert workflow {alert.workflow_id}")
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
                alert.triggered = True
                logger.info(
                    f"Price alert triggered for workflow {alert.workflow_id}: "
                    f"{alert.symbol}@{alert.exchange} {alert.condition} "
                    f"(price: {current_price}, target: {alert.target_price})"
                )

                self._trigger_workflow(alert.workflow_id, current_price, alert.api_key)
                self.remove_alert(alert.workflow_id)
            else:
                alert.last_price = current_price

        except Exception as e:
            logger.exception(f"Error checking price for {alert.symbol}: {e}")

    def _evaluate_condition(self, alert: PriceAlert, current_price: float) -> bool:
        """Evaluate if the price condition is met"""
        condition = alert.condition
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

        return False

    def _trigger_workflow(self, workflow_id: int, trigger_price: float, api_key: str):
        """Trigger workflow execution"""

        def run_workflow():
            try:
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

        thread = threading.Thread(target=run_workflow, daemon=True)
        thread.start()

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
