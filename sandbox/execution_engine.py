# sandbox/execution_engine.py
"""
Execution Engine - Monitors and executes pending orders

Features:
- Background order monitoring (every 5 seconds configurable)
- Real-time quote fetching from broker
- Order execution based on price type (MARKET, LIMIT, SL, SL-M)
- Trade creation and position updates
- Rate limit compliance (10 orders/second, 50 API calls/second)
- Batch processing for efficiency
"""

import os
import sys
from decimal import Decimal
from datetime import datetime
import pytz
import time
import uuid

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.sandbox_db import (
    SandboxOrders, SandboxTrades, SandboxPositions,
    db_session
)
from sandbox.fund_manager import FundManager
from services.quotes_service import get_quotes
from database.auth_db import get_auth_token_broker
from utils.logging import get_logger

logger = get_logger(__name__)


class ExecutionEngine:
    """Executes pending orders based on market data"""

    def __init__(self):
        # Read rate limits from .env (same as API protection)
        self.order_rate_limit = int(os.getenv('ORDER_RATE_LIMIT', '10 per second').split()[0])
        self.api_rate_limit = int(os.getenv('API_RATE_LIMIT', '50 per second').split()[0])
        self.batch_delay = 1.0  # 1 second between batches

    def check_and_execute_pending_orders(self):
        """
        Main execution loop - checks all pending orders and executes if conditions met
        Respects rate limits through batch processing
        """
        try:
            # Get all pending orders
            pending_orders = SandboxOrders.query.filter_by(order_status='open').all()

            if not pending_orders:
                logger.debug("No pending orders to process")
                return

            logger.info(f"Processing {len(pending_orders)} pending orders")

            # Group orders by user and symbol for efficient quote fetching
            orders_by_symbol = {}
            for order in pending_orders:
                key = (order.symbol, order.exchange)
                if key not in orders_by_symbol:
                    orders_by_symbol[key] = []
                orders_by_symbol[key].append(order)

            # Fetch quotes in batches (respecting API rate limit of 50/second)
            quote_cache = {}
            symbols_list = list(orders_by_symbol.keys())

            for i in range(0, len(symbols_list), self.api_rate_limit):
                batch = symbols_list[i:i + self.api_rate_limit]

                for symbol, exchange in batch:
                    quote_cache[(symbol, exchange)] = self._fetch_quote(symbol, exchange)

                # Wait 1 second before next batch if more symbols remain
                if i + self.api_rate_limit < len(symbols_list):
                    time.sleep(self.batch_delay)

            # Process orders in batches (respecting order rate limit of 10/second)
            orders_processed = 0
            for i in range(0, len(pending_orders), self.order_rate_limit):
                batch = pending_orders[i:i + self.order_rate_limit]

                for order in batch:
                    quote = quote_cache.get((order.symbol, order.exchange))
                    if quote:
                        self._process_order(order, quote)
                        orders_processed += 1

                # Wait 1 second before next batch if more orders remain
                if i + self.order_rate_limit < len(pending_orders):
                    time.sleep(self.batch_delay)

            logger.info(f"Processed {orders_processed} orders")

        except Exception as e:
            logger.error(f"Error in execution engine: {e}")

    def _fetch_quote(self, symbol, exchange):
        """
        Fetch real-time quote for a symbol using API key
        Returns dict with ltp, high, low, open, close, etc.
        Returns None if quote cannot be fetched (permission error, API error, etc.)
        """
        try:
            # Get any user's API key for fetching quotes
            from database.auth_db import ApiKeys, decrypt_token
            api_key_obj = ApiKeys.query.first()

            if not api_key_obj:
                logger.debug("No API keys found for fetching quotes")
                return None

            # Decrypt the API key
            api_key = decrypt_token(api_key_obj.api_key_encrypted)

            # Use quotes service with API key authentication
            success, response, status_code = get_quotes(
                symbol=symbol,
                exchange=exchange,
                api_key=api_key
            )

            if success and 'data' in response:
                quote_data = response['data']
                logger.debug(f"Fetched quote for {symbol}: LTP={quote_data.get('ltp', 0)}")
                return quote_data
            else:
                # Log at debug level to avoid spam for permission errors
                logger.debug(f"Could not fetch quote for {symbol}: {response.get('message', 'Unknown error')}")
                return None

        except Exception as e:
            # Handle all exceptions gracefully - don't stop execution engine
            logger.debug(f"Exception fetching quote for {symbol}: {str(e)}")
            return None

    def _process_order(self, order, quote):
        """
        Process a single order based on current quote
        Determines if order should be executed based on price type
        """
        try:
            # Check if this order already has a trade (prevent duplicates)
            # This can happen with MARKET orders that are executed immediately on placement
            # but the order status hasn't been updated to 'complete' yet due to race condition
            existing_trade = SandboxTrades.query.filter_by(orderid=order.orderid).first()
            if existing_trade:
                logger.debug(f"Order {order.orderid} already has trade {existing_trade.tradeid}, skipping execution")
                # Update order status to complete if it's still open (race condition cleanup)
                if order.order_status == 'open':
                    order.order_status = 'complete'
                    order.average_price = existing_trade.price
                    order.filled_quantity = order.quantity
                    order.pending_quantity = 0
                    order.update_timestamp = datetime.now(pytz.timezone('Asia/Kolkata'))
                    db_session.commit()
                    logger.info(f"Updated order {order.orderid} status to complete (was in race condition)")
                return

            ltp = Decimal(str(quote.get('ltp', 0)))
            bid = Decimal(str(quote.get('bid', 0)))
            ask = Decimal(str(quote.get('ask', 0)))

            if ltp <= 0:
                logger.warning(f"Invalid LTP for order {order.orderid}: {ltp}")
                return

            # Determine if order should be executed based on price type
            should_execute = False
            execution_price = None

            if order.price_type == 'MARKET':
                # Market orders execute immediately at bid/ask (more realistic)
                # BUY: Execute at ask price (pay seller's asking price)
                # SELL: Execute at bid price (receive buyer's bid price)
                # If bid/ask is 0, fall back to LTP
                should_execute = True
                if order.action == 'BUY':
                    execution_price = ask if ask > 0 else ltp
                else:  # SELL
                    execution_price = bid if bid > 0 else ltp

            elif order.price_type == 'LIMIT':
                # Limit BUY: Execute if LTP <= Limit Price (you get filled at LTP or better)
                # Limit SELL: Execute if LTP >= Limit Price (you get filled at LTP or better)
                if order.action == 'BUY' and ltp <= order.price:
                    should_execute = True
                    execution_price = ltp  # Execute at current market price (LTP), which is better than limit
                elif order.action == 'SELL' and ltp >= order.price:
                    should_execute = True
                    execution_price = ltp  # Execute at current market price (LTP), which is better than limit

            elif order.price_type == 'SL':
                # Stop Loss Limit order
                # SL BUY: When LTP >= trigger price, order activates. Execute at LTP if LTP <= limit price
                # SL SELL: When LTP <= trigger price, order activates. Execute at LTP if LTP >= limit price
                if order.action == 'BUY' and ltp >= order.trigger_price:
                    if ltp <= order.price:
                        should_execute = True
                        execution_price = ltp  # Execute at current market price (LTP)
                elif order.action == 'SELL' and ltp <= order.trigger_price:
                    if ltp >= order.price:
                        should_execute = True
                        execution_price = ltp  # Execute at current market price (LTP)

            elif order.price_type == 'SL-M':
                # Stop Loss Market order
                # BUY: Execute at market when LTP >= trigger price
                # SELL: Execute at market when LTP <= trigger price
                if order.action == 'BUY' and ltp >= order.trigger_price:
                    should_execute = True
                    execution_price = ltp
                elif order.action == 'SELL' and ltp <= order.trigger_price:
                    should_execute = True
                    execution_price = ltp

            # Execute the order if conditions are met
            if should_execute:
                self._execute_order(order, execution_price)

        except Exception as e:
            logger.error(f"Error processing order {order.orderid}: {e}")

    def _execute_order(self, order, execution_price):
        """
        Execute an order - create trade, update positions, release/adjust margin
        """
        try:
            logger.info(f"Executing order {order.orderid}: {order.symbol} {order.action} {order.quantity} @ {execution_price}")

            # Generate trade ID
            tradeid = self._generate_trade_id()

            # Create trade record
            trade = SandboxTrades(
                tradeid=tradeid,
                orderid=order.orderid,
                user_id=order.user_id,
                symbol=order.symbol,
                exchange=order.exchange,
                action=order.action,
                quantity=order.quantity,
                price=execution_price,
                product=order.product,
                strategy=order.strategy,
                trade_timestamp=datetime.now(pytz.timezone('Asia/Kolkata'))
            )

            db_session.add(trade)

            # Update order status
            order.order_status = 'complete'
            order.average_price = execution_price
            order.filled_quantity = order.quantity
            order.pending_quantity = 0
            order.update_timestamp = datetime.now(pytz.timezone('Asia/Kolkata'))

            db_session.commit()

            # Update position
            self._update_position(order, execution_price)

            logger.info(f"Order {order.orderid} executed successfully. Trade ID: {tradeid}")

        except Exception as e:
            db_session.rollback()
            logger.error(f"Error executing order {order.orderid}: {e}")

            # Mark order as rejected
            try:
                order.order_status = 'rejected'
                order.rejection_reason = f"Execution error: {str(e)}"
                order.update_timestamp = datetime.now(pytz.timezone('Asia/Kolkata'))
                db_session.commit()
            except:
                db_session.rollback()

    def _update_position(self, order, execution_price):
        """
        Update or create position after trade execution
        Handle netting for opposite positions

        Note: Margin was already blocked when order was placed (for pending orders like LIMIT/SL/SL-M)
        or during immediate execution (for MARKET orders). We only need to release margin when
        positions are closed/reduced.
        """
        try:
            fund_manager = FundManager(order.user_id)

            # Check if position exists
            position = SandboxPositions.query.filter_by(
                user_id=order.user_id,
                symbol=order.symbol,
                exchange=order.exchange,
                product=order.product
            ).first()

            if not position:
                # Create new position
                # Store the exact margin that was blocked at order placement time
                order_margin = order.margin_blocked if hasattr(order, 'margin_blocked') and order.margin_blocked else Decimal('0.00')
                position = SandboxPositions(
                    user_id=order.user_id,
                    symbol=order.symbol,
                    exchange=order.exchange,
                    product=order.product,
                    quantity=order.quantity if order.action == 'BUY' else -order.quantity,
                    average_price=execution_price,
                    ltp=execution_price,
                    pnl=Decimal('0.00'),
                    pnl_percent=Decimal('0.00'),
                    accumulated_realized_pnl=Decimal('0.00'),
                    margin_blocked=order_margin,  # Store exact margin from order
                    created_at=datetime.now(pytz.timezone('Asia/Kolkata'))
                )
                db_session.add(position)
                logger.info(f"Created new position: {order.symbol} {order.action} {order.quantity} (margin blocked: ₹{order_margin})")

            else:
                # Update existing position (netting logic)
                old_quantity = position.quantity
                new_quantity = order.quantity if order.action == 'BUY' else -order.quantity
                final_quantity = old_quantity + new_quantity

                # Special case: Reopening a closed position (old_quantity = 0)
                if old_quantity == 0:
                    # Keep accumulated realized P&L from previous trades, start fresh unrealized P&L
                    position.quantity = new_quantity
                    position.average_price = execution_price
                    position.ltp = execution_price
                    position.pnl = Decimal('0.00')  # Reset current P&L (will be updated by MTM)
                    position.pnl_percent = Decimal('0.00')
                    # accumulated_realized_pnl stays as is from previous closed trades
                    # Store the exact margin that was blocked at order placement time
                    order_margin = order.margin_blocked if hasattr(order, 'margin_blocked') and order.margin_blocked else Decimal('0.00')
                    position.margin_blocked = order_margin
                    logger.info(f"Reopened position: {order.symbol} {order.action} {order.quantity} (accumulated realized P&L: ₹{position.accumulated_realized_pnl}) (margin blocked: ₹{order_margin})")

                elif final_quantity == 0:
                    # Position closed completely
                    # Calculate realized P&L
                    realized_pnl = self._calculate_realized_pnl(
                        old_quantity, position.average_price,
                        abs(new_quantity), execution_price
                    )

                    # Release the EXACT margin that was stored in the position
                    # This prevents over-release when execution price differs from order placement price
                    margin_to_release = position.margin_blocked if hasattr(position, 'margin_blocked') and position.margin_blocked else Decimal('0.00')

                    if margin_to_release > 0:
                        fund_manager.release_margin(
                            margin_to_release,
                            realized_pnl,
                            f"Position closed: {order.symbol}"
                        )
                        logger.info(f"Released exact margin ₹{margin_to_release} for closed position (from position.margin_blocked)")

                    # Keep position with 0 quantity to show it was closed
                    # Add realized P&L to accumulated realized P&L (for day's trading)
                    position.accumulated_realized_pnl += realized_pnl

                    position.quantity = 0
                    position.margin_blocked = Decimal('0.00')  # Reset margin to 0 when position fully closed
                    position.ltp = execution_price
                    position.pnl = position.accumulated_realized_pnl  # Display total accumulated P&L
                    position.pnl_percent = Decimal('0.00')
                    logger.info(f"Position closed: {order.symbol}, Realized P&L: ₹{realized_pnl}, Total Accumulated P&L: ₹{position.accumulated_realized_pnl}")

                elif (old_quantity > 0 and final_quantity > old_quantity) or (old_quantity < 0 and final_quantity < old_quantity):
                    # Adding to existing position (same direction, position size increasing)
                    # Calculate new average price
                    total_value = (abs(old_quantity) * position.average_price) + (abs(new_quantity) * execution_price)
                    total_quantity = abs(old_quantity) + abs(new_quantity)
                    new_average_price = total_value / total_quantity

                    position.quantity = final_quantity
                    position.average_price = new_average_price
                    position.ltp = execution_price

                    # Accumulate margin - add the margin blocked for this order to existing position margin
                    order_margin = order.margin_blocked if hasattr(order, 'margin_blocked') and order.margin_blocked else Decimal('0.00')
                    position.margin_blocked = (position.margin_blocked if hasattr(position, 'margin_blocked') and position.margin_blocked else Decimal('0.00')) + order_margin
                    logger.info(f"Added to position: {order.symbol}, New qty: {final_quantity}, Avg: {new_average_price} (total margin blocked: ₹{position.margin_blocked})")

                else:
                    # Reducing position (opposite direction) or position reversal
                    reduced_quantity = min(abs(old_quantity), abs(new_quantity))

                    # Calculate realized P&L for reduced portion
                    realized_pnl = self._calculate_realized_pnl(
                        old_quantity, position.average_price,
                        reduced_quantity, execution_price
                    )

                    # Add realized P&L to accumulated realized P&L
                    # This tracks all partial closes throughout the day
                    position.accumulated_realized_pnl = (position.accumulated_realized_pnl or Decimal('0.00')) + realized_pnl

                    # Release margin PROPORTIONALLY for reduced quantity
                    # Use exact margin stored in position, release proportionally
                    current_margin = position.margin_blocked if hasattr(position, 'margin_blocked') and position.margin_blocked else Decimal('0.00')

                    if abs(old_quantity) > 0:
                        # Calculate proportion of position being reduced
                        reduction_proportion = Decimal(str(reduced_quantity)) / Decimal(str(abs(old_quantity)))
                        margin_to_release = current_margin * reduction_proportion
                    else:
                        margin_to_release = Decimal('0.00')

                    if margin_to_release > 0:
                        fund_manager.release_margin(
                            margin_to_release,
                            realized_pnl,
                            f"Position reduced: {order.symbol}"
                        )
                        logger.info(f"Released proportional margin ₹{margin_to_release} for reduced position ({reduction_proportion*100:.1f}% of ₹{current_margin})")

                    # Update remaining margin after proportional release
                    remaining_margin = current_margin - margin_to_release

                    # If position reversed, set margin for new reversed position
                    if abs(new_quantity) > abs(old_quantity):
                        # Position reversed - remaining quantity creates opposite position
                        remaining_quantity = abs(new_quantity) - abs(old_quantity)
                        position.quantity = remaining_quantity if order.action == 'BUY' else -remaining_quantity
                        position.average_price = execution_price

                        # For reversed position, the new margin comes from the excess quantity in the order
                        # The old position's margin was fully released, new position gets fresh margin
                        # Note: order.margin_blocked contains margin for the FULL order quantity
                        # We need to calculate what portion corresponds to the excess quantity
                        if abs(new_quantity) > 0:
                            excess_proportion = Decimal(str(remaining_quantity)) / Decimal(str(abs(new_quantity)))
                            order_margin = order.margin_blocked if hasattr(order, 'margin_blocked') and order.margin_blocked else Decimal('0.00')
                            new_position_margin = order_margin * excess_proportion
                            position.margin_blocked = new_position_margin
                            logger.info(f"Position reversed: {order.symbol}, New qty: {position.quantity} (new margin: ₹{new_position_margin})")
                        else:
                            position.margin_blocked = Decimal('0.00')
                    else:
                        # Position reduced but not reversed - keep remaining margin
                        position.quantity = final_quantity
                        position.margin_blocked = remaining_margin
                        logger.info(f"Position reduced: {order.symbol}, New qty: {final_quantity}, Remaining margin: ₹{remaining_margin}")

                    position.ltp = execution_price
                    logger.info(f"Partial close: {order.symbol}, New qty: {final_quantity}, Realized P&L: ₹{realized_pnl}")

            db_session.commit()

        except Exception as e:
            db_session.rollback()
            logger.error(f"Error updating position for order {order.orderid}: {e}")
            raise

    def _calculate_realized_pnl(self, old_quantity, avg_price, close_quantity, close_price):
        """Calculate realized P&L for closed positions"""
        try:
            avg_price = Decimal(str(avg_price))
            close_price = Decimal(str(close_price))
            close_quantity = Decimal(str(close_quantity))

            if old_quantity > 0:
                # Long position closed
                pnl = (close_price - avg_price) * close_quantity
            else:
                # Short position closed
                pnl = (avg_price - close_price) * close_quantity

            return pnl

        except Exception as e:
            logger.error(f"Error calculating realized P&L: {e}")
            return Decimal('0.00')

    def _generate_trade_id(self):
        """Generate unique trade ID"""
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        timestamp = now.strftime('%Y%m%d-%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        return f"TRADE-{timestamp}-{unique_id}"


def run_execution_engine_once():
    """Run one cycle of the execution engine"""
    engine = ExecutionEngine()
    engine.check_and_execute_pending_orders()


if __name__ == '__main__':
    """Run execution engine in standalone mode for testing"""
    logger.info("Starting Sandbox Execution Engine")

    # Get check interval from config
    from database.sandbox_db import init_db
    init_db()

    check_interval = int(get_config('order_check_interval', '5'))
    logger.info(f"Order check interval: {check_interval} seconds")

    try:
        while True:
            run_execution_engine_once()
            time.sleep(check_interval)
    except KeyboardInterrupt:
        logger.info("Execution engine stopped by user")
    except Exception as e:
        logger.error(f"Execution engine error: {e}")
