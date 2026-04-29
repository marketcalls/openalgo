import logging
import threading
import time
from datetime import datetime
from typing import Any, Optional

from database.auth_db import get_api_key_for_tradingview
from database.superorder_db import SuperOrder, db_session
from services.quotes_service import get_multiquotes

logger = logging.getLogger(__name__)


class SuperOrderMonitor:
    """
    Background monitor that checks PENDING and ACTIVE Super Orders.
    """

    _instance = None
    _lock = threading.Lock()
    _running = False
    _thread = None

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def start(self, interval: int = 5):
        """Start the background monitoring thread."""
        with self._lock:
            if self._running:
                logger.debug("Super Order Monitor is already running.")
                return

            self._running = True
            self._thread = threading.Thread(
                target=self._monitor_loop,
                args=(interval,),
                daemon=True,
                name="SuperOrderMonitorThread",
            )
            self._thread.start()
            logger.info("Super Order Monitor started.")

    def stop(self):
        """Stop the monitoring thread."""
        with self._lock:
            self._running = False
            if self._thread:
                self._thread.join(timeout=2.0)
                logger.info("Super Order Monitor stopped.")

    def _verify_imports(self):
        """Validate required service imports at startup to prevent silent loop failures."""
        try:
            from services.cancel_order_service import cancel_order
            from services.orderstatus_service import get_order_status
            from services.place_order_service import place_order
            from services.quotes_service import get_multiquotes
            # Just accessing the variables ensures they resolve
            _ = get_order_status
            _ = place_order
            _ = cancel_order
            _ = get_multiquotes
        except ImportError as e:
            logger.critical(f"FATAL: Missing dependency for Super Order Monitor: {e}")
            raise RuntimeError(f"Super Order Monitor failed to initialize: {e}") from e

    def _monitor_loop(self, interval: int):
        try:
            self._verify_imports()
        except RuntimeError:
            self._running = False
            return

        while self._running:
            try:
                self._process_super_orders()
            except Exception as e:
                logger.exception(f"Error in Super Order Monitor loop: {e}")

            time.sleep(interval)

    def _process_super_orders(self):
        """Fetch and process PENDING and ACTIVE orders."""
        try:
            # Refresh session to ensure we have the latest data
            db_session.remove()

            orders = SuperOrder.query.filter(
                SuperOrder.status.in_(["PENDING", "ACTIVE"])
            ).all()

            if not orders:
                return

            # Group by user to minimize api_key fetches and batch quotes
            orders_by_user = {}
            for order in orders:
                orders_by_user.setdefault(order.user_id, []).append(order)

            for user_id, user_orders in orders_by_user.items():
                api_key = get_api_key_for_tradingview(user_id)
                if not api_key:
                    logger.warning(
                        f"No API key found for user {user_id}, skipping super orders."
                    )
                    continue

                active_orders = [o for o in user_orders if o.status == "ACTIVE"]
                pending_orders = [o for o in user_orders if o.status == "PENDING"]

                # Check PENDING orders to see if they got filled
                self._check_pending_orders(pending_orders, api_key)

                # Fetch quotes for ACTIVE orders
                if active_orders:
                    self._process_active_orders(active_orders, api_key)

            # Check for expired orders
            self._cancel_expired_orders(orders)

        except Exception as e:
            logger.exception(f"Failed processing super orders: {e}")
            db_session.rollback()

    def _cancel_expired_orders(self, orders: list[SuperOrder]):
        from services.cancel_order_service import cancel_order
        now = datetime.now()
        for order in orders:
            if order.expires_at and now >= order.expires_at:
                logger.info(
                    f"Super Order {order.id} expired at {order.expires_at}. Cancelling."
                )
                api_key = get_api_key_for_tradingview(order.user_id)

                # Update status
                order.status = "CANCELLED"

                if order.status == "PENDING" and order.main_order_id:
                    cancel_order(orderid=order.main_order_id, api_key=api_key)
                elif order.status == "ACTIVE":
                    if order.target_order_id:
                        cancel_order(orderid=order.target_order_id, api_key=api_key)
                    if order.stoploss_order_id:
                        cancel_order(orderid=order.stoploss_order_id, api_key=api_key)

                db_session.commit()

    def _check_pending_orders(self, pending_orders: list[SuperOrder], api_key: str):
        from services.orderstatus_service import get_order_status
        for order in pending_orders:
            if not order.main_order_id:
                continue

            success, response, status_code = get_order_status(
                # Ensure we bypass global analyze mode so we read the actual LIVE status
                # since Super Orders are live broker orders.
                {"orderid": order.main_order_id, "mode": "live"},
                api_key=api_key
            )
            if success and response.get("status") == "success":
                data = response.get("data", {})
                status = str(data.get("order_status", "")).upper()

                filled_qty = int(data.get("filled_quantity", 0)) or int(
                    data.get("traded_quantity", 0)
                )

                if status in ["COMPLETE", "COMPLETED", "FILLED"]:
                    # Order filled, move to ACTIVE
                    order.status = "ACTIVE"
                    if filled_qty > 0 and filled_qty < order.quantity:
                        # Update quantity to what was actually filled
                        order.quantity = filled_qty

                    db_session.commit()
                    logger.info(
                        f"Super Order {order.id} main leg filled, moving to ACTIVE."
                    )
                elif status == "OPEN" and filled_qty > 0:
                    # Partially filled order, move to ACTIVE for the filled quantity
                    order.status = "ACTIVE"
                    order.quantity = filled_qty
                    db_session.commit()
                    logger.info(
                        f"Super Order {order.id} main leg partially filled, moving to ACTIVE with qty {filled_qty}."
                    )
                elif status in ["REJECTED", "CANCELLED"]:
                    # Handle case where it was partially filled and then cancelled
                    if filled_qty > 0:
                        order.status = "ACTIVE"
                        order.quantity = filled_qty
                        logger.info(
                            f"Super Order {order.id} main leg cancelled after part fill, moving to ACTIVE with qty {filled_qty}."
                        )
                    else:
                        order.status = "FAILED" if status == "REJECTED" else "CANCELLED"
                        logger.info(
                            f"Super Order {order.id} main leg {status}, updating state."
                        )
                    db_session.commit()
            else:
                logger.debug(
                    f"Could not fetch order status for main leg {order.main_order_id} of Super Order {order.id}"
                )

    def _process_active_orders(self, active_orders: list[SuperOrder], api_key: str):
        # Gather unique symbols
        unique_symbol_tuples = {(o.symbol, o.exchange) for o in active_orders}
        symbols = [
            {"symbol": sym, "exchange": exch} for sym, exch in unique_symbol_tuples
        ]

        # Batch quote fetch
        success, mq_response, _ = get_multiquotes(symbols=symbols, api_key=api_key)

        if not success or "results" not in mq_response:
            logger.warning(
                f"Failed to fetch multiquotes for active super orders: {mq_response.get('message')}"
            )
            return

        quotes_dict = {}
        for result in mq_response["results"]:
            sym = result.get("symbol")
            exch = result.get("exchange")
            data = result.get("data", {})
            ltp = data.get("ltp")
            if sym and exch and ltp is not None:
                quotes_dict[(sym, exch)] = float(ltp)

        for order in active_orders:
            ltp = quotes_dict.get((order.symbol, order.exchange))

            logger.info(f"Checking Super Order {order.id}: symbol={order.symbol}, LTP={ltp}, target={order.target_price}, sl={order.stoploss_price}")

            if ltp is None:
                continue

            # Process trailing stoploss
            self._apply_trailing_stoploss(order, ltp)

            # Check for triggers
            triggered_leg = None

            # Target Trigger
            if order.transaction_type.upper() == "BUY":
                if ltp >= float(order.target_price):
                    triggered_leg = "TARGET"
                elif ltp <= float(order.stoploss_price):
                    triggered_leg = "STOPLOSS"
            else:  # SELL
                if ltp <= float(order.target_price):
                    triggered_leg = "TARGET"
                elif ltp >= float(order.stoploss_price):
                    triggered_leg = "STOPLOSS"

            if triggered_leg:
                logger.info(
                    f"Super Order {order.id}: {triggered_leg.capitalize()} price reached. Firing exit order at {ltp}."
                )
                self._execute_leg(order, triggered_leg, api_key)

    def _apply_trailing_stoploss(self, order: SuperOrder, ltp: float):
        if not order.trail_jump or float(order.trail_jump) <= 0:
            return

        trail_jump = float(order.trail_jump)
        entry = float(order.entry_price)
        current_sl = float(order.stoploss_price)

        # OCO + Trailing logic:
        # If BUY, and price moves UP by trail_jump increments above entry, move SL UP
        # If SELL, and price moves DOWN by trail_jump increments below entry, move SL DOWN

        updated = False

        # Calculate original stoploss distance
        sl_distance = abs(entry - float(order.stoploss_price))

        if order.transaction_type.upper() == "BUY":
            if ltp > entry:
                increments = int((ltp - entry) / trail_jump)
                if increments > 0:
                    # Original stop loss + increments * trail_jump
                    # We compute the distance from entry
                    # Actually, a better way is to move it by trail_jump for each trail_jump the LTP moves from entry.
                    new_sl = entry - sl_distance + (increments * trail_jump)
                    # For safety, make sure we only ever move SL UP, and it's less than LTP
                    if new_sl > current_sl and new_sl < ltp:
                        order.stoploss_price = new_sl
                        updated = True
        else:
            if ltp < entry:
                increments = int((entry - ltp) / trail_jump)
                if increments > 0:
                    # Original stop loss - increments * trail_jump
                    new_sl = entry + sl_distance - (increments * trail_jump)
                    # Make sure we only ever move SL DOWN, and it's greater than LTP
                    if new_sl < current_sl and new_sl > ltp:
                        order.stoploss_price = new_sl
                        updated = True

        if updated:
            db_session.commit()
            logger.info(
                f"Super Order {order.id} Trailing SL updated to {order.stoploss_price} (LTP: {ltp})"
            )

    def _execute_leg(self, order: SuperOrder, leg_type: str, api_key: str):
        from services.place_order_service import place_order
        # We need to send an opposing market order to exit the position
        exit_action = "SELL" if order.transaction_type.upper() == "BUY" else "BUY"

        leg_data = {
            "apikey": api_key,
            "strategy": f"SuperOrder_{leg_type}",
            "symbol": order.symbol,
            "exchange": order.exchange,
            "action": exit_action,
            "quantity": order.quantity,
            "pricetype": "MARKET",
            "product": order.product_type,
            "price": 0,
        }

        success, response_data, status_code = place_order(
            order_data=leg_data,
            api_key=api_key,
        )

        if success:
            order_id_str = str(response_data.get("orderid"))
            if leg_type == "TARGET":
                order.target_order_id = order_id_str
                other_leg = "stop-loss"
            else:
                order.stoploss_order_id = order_id_str
                other_leg = "target"

            order.status = "CLOSED"
            db_session.commit()
            logger.info(
                f"Super Order {order.id}: {leg_type.capitalize()} leg executed. Cancelling {other_leg} leg. Status -> CLOSED."
            )
        else:
            logger.error(
                f"Failed to execute {leg_type} for Super Order {order.id}: {response_data}"
            )
            # Keep active, let it retry on next tick


# Global instance
superorder_monitor = SuperOrderMonitor()


def start_superorder_monitor():
    superorder_monitor.start()
