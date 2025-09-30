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
    db_session, get_config
)
from sandbox.fund_manager import FundManager
from services.quotes_service import get_quotes
from database.auth_db import get_auth_token_broker
from utils.logging import get_logger

logger = get_logger(__name__)


class ExecutionEngine:
    """Executes pending orders based on market data"""

    def __init__(self):
        self.order_rate_limit = int(get_config('order_rate_limit', '10'))
        self.api_rate_limit = int(get_config('api_rate_limit', '50'))
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
        """
        try:
            # Get any user's API key for fetching quotes
            from database.auth_db import ApiKeys, decrypt_token
            api_key_obj = ApiKeys.query.first()

            if not api_key_obj:
                logger.warning("No API keys found for fetching quotes")
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
                logger.warning(f"Failed to fetch quote for {symbol}: {response.get('message', 'Unknown error')}")
                return None

        except Exception as e:
            logger.error(f"Error fetching quote for {symbol} on {exchange}: {e}")
            return None

    def _process_order(self, order, quote):
        """
        Process a single order based on current quote
        Determines if order should be executed based on price type
        """
        try:
            ltp = Decimal(str(quote.get('ltp', 0)))

            if ltp <= 0:
                logger.warning(f"Invalid LTP for order {order.orderid}: {ltp}")
                return

            # Determine if order should be executed based on price type
            should_execute = False
            execution_price = None

            if order.price_type == 'MARKET':
                # Market orders execute immediately at LTP
                should_execute = True
                execution_price = ltp

            elif order.price_type == 'LIMIT':
                # Limit BUY: Execute if LTP <= Limit Price
                # Limit SELL: Execute if LTP >= Limit Price
                if order.action == 'BUY' and ltp <= order.price:
                    should_execute = True
                    execution_price = order.price  # Execute at limit price
                elif order.action == 'SELL' and ltp >= order.price:
                    should_execute = True
                    execution_price = order.price  # Execute at limit price

            elif order.price_type == 'SL':
                # Stop Loss Limit order
                # BUY: Execute at limit price when LTP >= trigger price
                # SELL: Execute at limit price when LTP <= trigger price
                if order.action == 'BUY' and ltp >= order.trigger_price:
                    if ltp <= order.price:
                        should_execute = True
                        execution_price = order.price
                elif order.action == 'SELL' and ltp <= order.trigger_price:
                    if ltp >= order.price:
                        should_execute = True
                        execution_price = order.price

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
                    created_at=datetime.now(pytz.timezone('Asia/Kolkata'))
                )
                db_session.add(position)
                logger.info(f"Created new position: {order.symbol} {order.action} {order.quantity}")

            else:
                # Update existing position (netting logic)
                old_quantity = position.quantity
                new_quantity = order.quantity if order.action == 'BUY' else -order.quantity
                final_quantity = old_quantity + new_quantity

                if final_quantity == 0:
                    # Position closed completely
                    # Calculate realized P&L
                    realized_pnl = self._calculate_realized_pnl(
                        old_quantity, position.average_price,
                        abs(new_quantity), execution_price
                    )

                    # Release all margin for this position
                    margin_to_release, _ = fund_manager.calculate_margin_required(
                        order.symbol, order.exchange, order.product,
                        abs(old_quantity), position.average_price
                    )

                    if margin_to_release:
                        fund_manager.release_margin(
                            margin_to_release,
                            realized_pnl,
                            f"Position closed: {order.symbol}"
                        )

                    # Keep position with 0 quantity to show it was closed
                    position.quantity = 0
                    position.ltp = execution_price
                    position.pnl = Decimal('0.00')
                    position.pnl_percent = Decimal('0.00')
                    logger.info(f"Position closed: {order.symbol}, Realized P&L: ₹{realized_pnl}")

                elif (old_quantity > 0 and final_quantity > 0) or (old_quantity < 0 and final_quantity < 0):
                    # Adding to existing position (same direction)
                    # Calculate new average price
                    total_value = (abs(old_quantity) * position.average_price) + (abs(new_quantity) * execution_price)
                    total_quantity = abs(old_quantity) + abs(new_quantity)
                    new_average_price = total_value / total_quantity

                    position.quantity = final_quantity
                    position.average_price = new_average_price
                    position.ltp = execution_price

                    # Block additional margin for the new quantity
                    additional_margin, _ = fund_manager.calculate_margin_required(
                        order.symbol, order.exchange, order.product,
                        abs(new_quantity), execution_price
                    )
                    if additional_margin:
                        fund_manager.block_margin(
                            additional_margin,
                            f"Added to position: {order.symbol}"
                        )

                    logger.info(f"Added to position: {order.symbol}, New qty: {final_quantity}, Avg: {new_average_price}")

                else:
                    # Reducing position (opposite direction)
                    reduced_quantity = min(abs(old_quantity), abs(new_quantity))

                    # Calculate realized P&L for reduced portion
                    realized_pnl = self._calculate_realized_pnl(
                        old_quantity, position.average_price,
                        reduced_quantity, execution_price
                    )

                    # Release margin for reduced quantity
                    margin_to_release, _ = fund_manager.calculate_margin_required(
                        order.symbol, order.exchange, order.product,
                        reduced_quantity, position.average_price
                    )

                    if margin_to_release:
                        fund_manager.release_margin(
                            margin_to_release,
                            realized_pnl,
                            f"Position reduced: {order.symbol}"
                        )

                    # If position reversed, recalculate average price for new position
                    if abs(new_quantity) > abs(old_quantity):
                        # Position reversed
                        remaining_quantity = abs(new_quantity) - abs(old_quantity)
                        position.quantity = remaining_quantity if order.action == 'BUY' else -remaining_quantity
                        position.average_price = execution_price

                        # Block margin for reversed position
                        new_margin, _ = fund_manager.calculate_margin_required(
                            order.symbol, order.exchange, order.product,
                            remaining_quantity, execution_price
                        )
                        if new_margin:
                            fund_manager.block_margin(
                                new_margin,
                                f"Position reversed: {order.symbol}"
                            )
                    else:
                        # Position reduced but not reversed
                        position.quantity = final_quantity

                    position.ltp = execution_price
                    logger.info(f"Reduced position: {order.symbol}, New qty: {final_quantity}, Realized P&L: ₹{realized_pnl}")

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
