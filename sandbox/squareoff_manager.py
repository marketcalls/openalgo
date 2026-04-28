# sandbox/squareoff_manager.py
"""
Square-Off Manager - Handles automatic position closure at exchange-specific times

Features:
- Auto square-off for MIS positions at configured times
- Exchange-specific timings (NSE/BSE: 3:15 PM, CDS/BCD: 4:45 PM, MCX: 11:30 PM, NCDEX: 5:00 PM)
- Market order creation for position closure
- Background scheduler for automatic execution
- Configurable square-off times
"""

import os
import sys
from datetime import datetime, time
from decimal import Decimal

import pytz

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.sandbox_db import SandboxPositions, db_session, get_config
from sandbox.position_manager import PositionManager
from utils.logging import get_logger

logger = get_logger(__name__)


class SquareOffManager:
    """Manages automatic square-off of MIS positions"""

    def __init__(self):
        self.ist = pytz.timezone("Asia/Kolkata")

        # Load square-off times from config
        self.square_off_times = {
            "NSE": self._parse_time(get_config("nse_bse_square_off_time", "15:15")),
            "BSE": self._parse_time(get_config("nse_bse_square_off_time", "15:15")),
            "NFO": self._parse_time(get_config("nse_bse_square_off_time", "15:15")),
            "BFO": self._parse_time(get_config("nse_bse_square_off_time", "15:15")),
            "CDS": self._parse_time(get_config("cds_bcd_square_off_time", "16:45")),
            "BCD": self._parse_time(get_config("cds_bcd_square_off_time", "16:45")),
            "MCX": self._parse_time(get_config("mcx_square_off_time", "23:30")),
            "NCDEX": self._parse_time(get_config("ncdex_square_off_time", "17:00")),
        }

    def _parse_time(self, time_str):
        """Parse time string (HH:MM) to time object"""
        try:
            hour, minute = map(int, time_str.split(":"))
            return time(hour=hour, minute=minute)
        except Exception as e:
            logger.exception(f"Error parsing time '{time_str}': {e}")
            return time(15, 15)  # Default to 3:15 PM

    def check_and_square_off(self):
        """
        Check if it's time to square-off positions and execute
        Should be called frequently (e.g., every minute)
        """
        try:
            now = datetime.now(self.ist)
            current_time = now.time()

            # Step 1: Cancel all open MIS orders past square-off time
            cancelled_count = self._cancel_open_mis_orders(current_time)

            # Step 2: Get all open MIS positions (quantity != 0)
            mis_positions = (
                SandboxPositions.query.filter_by(product="MIS")
                .filter(SandboxPositions.quantity != 0)
                .all()
            )

            positions_to_close = []
            if mis_positions:
                # Check each position against its exchange's square-off time
                for position in mis_positions:
                    exchange = position.exchange
                    square_off_time = self.square_off_times.get(exchange)

                    if not square_off_time:
                        logger.warning(f"No square-off time configured for exchange {exchange}")
                        continue

                    # Check if current time has passed square-off time
                    if current_time >= square_off_time:
                        positions_to_close.append(position)
            else:
                logger.debug("No MIS positions to square-off")

            if positions_to_close:
                logger.info(f"Found {len(positions_to_close)} MIS positions to square-off")
                self._square_off_positions(positions_to_close)
            else:
                logger.debug(f"No positions due for square-off at {current_time.strftime('%H:%M')}")

            # Notify UI if anything changed. The per-position close goes through
            # _execute_order (already publishes SandboxOrderFilledEvent), so
            # Positions/OrderBook will refresh per-fill. But the auto-cancel
            # path bypasses the service layer entirely, so without this emit
            # OrderBook would miss the cancellations until manual refresh.
            if cancelled_count or positions_to_close:
                try:
                    from events import SandboxAutoSquareOffEvent
                    from utils.event_bus import bus

                    bus.publish(
                        SandboxAutoSquareOffEvent(
                            mode="analyze",
                            api_type="sandbox.auto_squareoff",
                            cancelled_orders=cancelled_count,
                            closed_positions=len(positions_to_close),
                        )
                    )
                except Exception as pub_err:
                    logger.debug(f"Failed to publish SandboxAutoSquareOffEvent: {pub_err}")

        except Exception as e:
            logger.exception(f"Error checking square-off conditions: {e}")

    def _cancel_open_mis_orders(self, current_time):
        """Cancel all open MIS orders past their exchange's square-off time.

        Returns the number of orders successfully cancelled, so the caller
        can decide whether to emit a UI-refresh event.
        """
        cancelled_count = 0
        try:
            from database.sandbox_db import SandboxOrders
            from sandbox.order_manager import OrderManager

            # Get all open MIS orders
            open_orders = SandboxOrders.query.filter_by(product="MIS", order_status="open").all()

            if not open_orders:
                return 0

            for order in open_orders:
                exchange = order.exchange
                square_off_time = self.square_off_times.get(exchange)

                if not square_off_time:
                    continue

                # Check if current time has passed square-off time for this exchange
                if current_time >= square_off_time:
                    try:
                        order_manager = OrderManager(order.user_id)
                        success, response, status_code = order_manager.cancel_order(order.orderid)

                        if success:
                            logger.info(
                                f"Auto-cancelled MIS order {order.orderid} for {order.symbol} past square-off time"
                            )
                            cancelled_count += 1
                        else:
                            logger.error(
                                f"Failed to cancel MIS order {order.orderid}: {response.get('message', 'Unknown error')}"
                            )

                    except Exception as e:
                        logger.exception(f"Error cancelling MIS order {order.orderid}: {e}")

            if cancelled_count > 0:
                logger.info(
                    f"Auto-cancelled {cancelled_count} open MIS orders past square-off time"
                )

        except Exception as e:
            logger.exception(f"Error in _cancel_open_mis_orders: {e}")

        return cancelled_count

    def _square_off_positions(self, positions):
        """Square-off a list of positions"""
        success_count = 0
        error_count = 0

        for position in positions:
            try:
                pm = PositionManager(position.user_id)
                success, response, status_code = pm.close_position(
                    position.symbol, position.exchange, position.product
                )

                if success:
                    logger.info(
                        f"Auto square-off: {position.symbol} for user {position.user_id} - "
                        f"OrderID: {response.get('orderid', 'N/A')}"
                    )
                    success_count += 1
                else:
                    logger.error(
                        f"Failed to square-off {position.symbol} for user {position.user_id}: "
                        f"{response.get('message', 'Unknown error')}"
                    )
                    error_count += 1

            except Exception as e:
                logger.exception(f"Error squaring-off position {position.symbol}: {e}")
                error_count += 1

        logger.info(f"Square-off completed: {success_count} successful, {error_count} failed")

    def force_square_off_all_mis(self):
        """Force square-off all MIS positions immediately"""
        try:
            mis_positions = (
                SandboxPositions.query.filter_by(product="MIS")
                .filter(SandboxPositions.quantity != 0)
                .all()
            )

            if not mis_positions:
                logger.info("No MIS positions to force square-off")
                return True, "No positions to square-off"

            logger.warning(f"Force squaring-off {len(mis_positions)} MIS positions")
            self._square_off_positions(mis_positions)

            return True, f"Force square-off initiated for {len(mis_positions)} positions"

        except Exception as e:
            logger.exception(f"Error force squaring-off positions: {e}")
            return False, f"Error: {str(e)}"

    def get_time_to_square_off(self, exchange):
        """Get time remaining until square-off for an exchange"""
        try:
            square_off_time = self.square_off_times.get(exchange)

            if not square_off_time:
                return None

            now = datetime.now(self.ist)
            current_time = now.time()

            # Create datetime objects for comparison
            square_off_dt = datetime.combine(now.date(), square_off_time)
            current_dt = datetime.combine(now.date(), current_time)

            # Calculate time difference
            time_diff = square_off_dt - current_dt

            # If time has passed, return 0 or negative
            return time_diff.total_seconds()

        except Exception as e:
            logger.exception(f"Error calculating time to square-off: {e}")
            return None

    def get_square_off_status(self):
        """Get status of square-off times for all exchanges"""
        try:
            now = datetime.now(self.ist)
            current_time = now.time()

            status = {}

            for exchange, square_off_time in self.square_off_times.items():
                time_to_square_off = self.get_time_to_square_off(exchange)

                status[exchange] = {
                    "square_off_time": square_off_time.strftime("%H:%M"),
                    "current_time": current_time.strftime("%H:%M"),
                    "time_remaining_seconds": int(time_to_square_off) if time_to_square_off else 0,
                    "is_past_square_off": current_time >= square_off_time,
                }

            return status

        except Exception as e:
            logger.exception(f"Error getting square-off status: {e}")
            return {}


def run_square_off_check():
    """Run one cycle of square-off check"""
    som = SquareOffManager()
    som.check_and_square_off()


if __name__ == "__main__":
    """Run square-off manager in standalone mode"""
    import time as time_module

    logger.info("Starting Sandbox Square-Off Manager")

    from database.sandbox_db import init_db

    init_db()

    som = SquareOffManager()

    # Display square-off times
    status = som.get_square_off_status()
    logger.info("Configured square-off times:")
    for exchange, info in status.items():
        logger.info(f"  {exchange}: {info['square_off_time']} IST")

    # Run check every minute
    check_interval = 60  # 1 minute

    try:
        while True:
            run_square_off_check()
            time_module.sleep(check_interval)
    except KeyboardInterrupt:
        logger.info("Square-off manager stopped by user")
    except Exception as e:
        logger.exception(f"Square-off manager error: {e}")
