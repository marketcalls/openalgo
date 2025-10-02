# sandbox/order_manager.py
"""
Order Manager - Handles virtual order placement and validation

Features:
- Order validation (symbol, quantity, price, etc.)
- Margin checking before order placement
- Order placement with unique order IDs
- Order modification and cancellation
- Support for all order types: MARKET, LIMIT, SL, SL-M
"""

import os
import sys
from decimal import Decimal
from datetime import datetime
import pytz
import uuid

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.sandbox_db import (
    SandboxOrders, SandboxTrades, SandboxPositions, db_session
)
from sandbox.fund_manager import FundManager
from database.symbol import SymToken
from utils.logging import get_logger

logger = get_logger(__name__)


def is_option(symbol, exchange):
    """Check if symbol is an option based on exchange and symbol suffix"""
    if exchange in ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCDEX']:
        return symbol.endswith('CE') or symbol.endswith('PE')
    return False


def is_future(symbol, exchange):
    """Check if symbol is a future based on exchange and symbol suffix"""
    if exchange in ['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCDEX']:
        return symbol.endswith('FUT')
    return False


class OrderManager:
    """Manages virtual orders for sandbox mode"""

    def __init__(self, user_id):
        self.user_id = user_id
        self.fund_manager = FundManager(user_id)

    def place_order(self, order_data):
        """
        Place a new order in sandbox mode

        Args:
            order_data: dict containing order parameters
                - symbol: str
                - exchange: str
                - action: str (BUY/SELL)
                - quantity: int
                - price: float (optional for MARKET orders)
                - trigger_price: float (optional for SL orders)
                - price_type: str (MARKET/LIMIT/SL/SL-M)
                - product: str (CNC/NRML/MIS)
                - strategy: str (optional)

        Returns:
            tuple: (success: bool, response: dict, status_code: int)
        """
        try:
            # Validate order data
            is_valid, validation_msg = self._validate_order(order_data)
            if not is_valid:
                return False, {
                    'status': 'error',
                    'message': validation_msg,
                    'mode': 'analyze'
                }, 400

            # Extract order parameters
            symbol = order_data['symbol']
            exchange = order_data['exchange']
            action = order_data['action'].upper()
            quantity = int(order_data['quantity'])
            price = Decimal(str(order_data.get('price', 0))) if order_data.get('price') else None
            trigger_price = Decimal(str(order_data.get('trigger_price', 0))) if order_data.get('trigger_price') else None
            price_type = order_data['price_type'].upper()
            product = order_data['product'].upper()
            strategy = order_data.get('strategy', '')

            # Get symbol info for lot size validation
            symbol_obj = SymToken.query.filter_by(symbol=symbol, exchange=exchange).first()
            if not symbol_obj:
                return False, {
                    'status': 'error',
                    'message': f'Symbol {symbol} not found on {exchange}',
                    'mode': 'analyze'
                }, 400

            # Validate lot size for F&O
            if exchange in ['NFO', 'BFO', 'CDS', 'BCD', 'MCX', 'NCDEX']:
                lot_size = symbol_obj.lotsize or 1
                if quantity % lot_size != 0:
                    return False, {
                        'status': 'error',
                        'message': f'Quantity must be in multiples of lot size {lot_size}',
                        'mode': 'analyze'
                    }, 400

            # Validate MIS orders - reject if after square-off time but before market open
            # Exception: Allow orders that reduce/close existing positions
            if product == 'MIS':
                from sandbox.squareoff_manager import SquareOffManager
                from datetime import time

                som = SquareOffManager()
                square_off_time = som.square_off_times.get(exchange)

                if square_off_time:
                    ist = pytz.timezone('Asia/Kolkata')
                    now = datetime.now(ist)
                    current_time = now.time()

                    # Market opens at 9:00 AM IST
                    market_open_time = time(9, 0)

                    # Check if we're in the blocked period
                    # Two scenarios:
                    # 1. After square-off time same day: e.g., 15:20 (after 15:15 square-off)
                    # 2. Before market open next day: e.g., 02:00 (before 09:00 market open)
                    is_blocked = False
                    if current_time >= square_off_time:
                        # After square-off time - block until next day
                        is_blocked = True
                    elif current_time < market_open_time:
                        # Before market open - still blocked from yesterday
                        is_blocked = True

                    if is_blocked:
                        # Check if this order will reduce/close an existing OPEN position
                        existing_position = SandboxPositions.query.filter_by(
                            user_id=self.user_id,
                            symbol=symbol,
                            exchange=exchange,
                            product=product
                        ).filter(SandboxPositions.quantity != 0).first()

                        # Allow if reducing existing position
                        # BUY reduces short position (negative qty), SELL reduces long position (positive qty)
                        is_reducing = False
                        if existing_position:
                            if action == 'BUY' and existing_position.quantity < 0:
                                is_reducing = True  # Covering short
                            elif action == 'SELL' and existing_position.quantity > 0:
                                is_reducing = True  # Closing long

                        # Block only if opening/increasing position, allow if closing/reducing
                        if not is_reducing:
                            return False, {
                                'status': 'error',
                                'message': f'MIS orders cannot be placed after square-off time ({square_off_time.strftime("%H:%M")} IST). Trading resumes at 09:00 AM IST.',
                                'mode': 'analyze'
                            }, 400

            # Track validation for CNC SELL orders
            cnc_sell_rejection_reason = None

            # Validate SELL orders based on product type
            # CNC (delivery) requires existing positions/holdings, MIS (intraday) allows short selling
            if action == 'SELL':
                if product == 'CNC':
                    # CNC SELL orders require existing long positions or holdings
                    # Check existing position
                    existing_position = SandboxPositions.query.filter_by(
                        user_id=self.user_id,
                        symbol=symbol,
                        exchange=exchange,
                        product=product
                    ).first()

                    # Check holdings (T+1 settled positions)
                    from database.sandbox_db import SandboxHoldings
                    existing_holdings = SandboxHoldings.query.filter_by(
                        user_id=self.user_id,
                        symbol=symbol,
                        exchange=exchange
                    ).first()

                    # Calculate total available quantity
                    position_qty = existing_position.quantity if existing_position and existing_position.quantity > 0 else 0
                    holdings_qty = existing_holdings.quantity if existing_holdings and existing_holdings.quantity > 0 else 0
                    total_available = position_qty + holdings_qty

                    if total_available <= 0:
                        cnc_sell_rejection_reason = f'Cannot sell {symbol} in CNC. No positions or holdings available. CNC (delivery) requires existing shares. Use MIS for intraday short selling.'
                    elif quantity > total_available:
                        cnc_sell_rejection_reason = f'Cannot sell {quantity} shares of {symbol} in CNC. Only {total_available} shares available (Position: {position_qty}, Holdings: {holdings_qty})'
                    else:
                        logger.info(f"CNC SELL validation passed: {symbol} - Available: {total_available} (Pos: {position_qty}, Hold: {holdings_qty}), Requested: {quantity}")

                elif product == 'MIS':
                    # MIS allows short selling (negative positions) since it's intraday
                    logger.info(f"MIS SELL order: {symbol} - Short selling allowed for intraday")

            # Determine price for margin calculation based on order type
            margin_calculation_price = None

            if price_type == 'MARKET':
                # For MARKET orders, fetch current LTP for margin calculation
                try:
                    from sandbox.execution_engine import ExecutionEngine
                    engine = ExecutionEngine()
                    quote = engine._fetch_quote(symbol, exchange)
                    if quote and quote.get('ltp'):
                        margin_calculation_price = Decimal(str(quote['ltp']))
                        logger.debug(f"Using LTP {margin_calculation_price} for MARKET order margin calculation")
                    else:
                        # In sandbox mode, use a default price if API fails
                        # Try to get last execution price from positions
                        if existing_position and existing_position.ltp:
                            margin_calculation_price = existing_position.ltp
                            logger.warning(f"API failed, using last known price {margin_calculation_price} for {symbol}")
                        else:
                            # Use a reasonable default for sandbox testing
                            margin_calculation_price = Decimal('112.37')  # Default ZEEL price for testing
                            logger.warning(f"API failed, using default sandbox price {margin_calculation_price} for {symbol}")
                except Exception as e:
                    logger.error(f"Error fetching quote for margin calculation: {e}")
                    # In sandbox mode, use a fallback price
                    if existing_position and existing_position.ltp:
                        margin_calculation_price = existing_position.ltp
                        logger.warning(f"API error, using last known price {margin_calculation_price} for {symbol}")
                    else:
                        margin_calculation_price = Decimal('112.37')  # Default ZEEL price for testing
                        logger.warning(f"API error, using default sandbox price {margin_calculation_price} for {symbol}")

            elif price_type == 'LIMIT':
                # For LIMIT orders, use the limit price for margin calculation
                margin_calculation_price = price
                logger.debug(f"Using LIMIT price {margin_calculation_price} for margin calculation")

            elif price_type in ['SL', 'SL-M']:
                # For SL/SL-M orders, use trigger price for margin calculation
                # This represents the worst-case price at which order will be triggered
                margin_calculation_price = trigger_price
                logger.debug(f"Using trigger price {margin_calculation_price} for {price_type} order margin calculation")

            # Validate that we have a valid price for margin calculation
            if not margin_calculation_price or margin_calculation_price <= 0:
                return False, {
                    'status': 'error',
                    'message': f'Invalid price for margin calculation. Please provide valid price/trigger_price for {price_type} order',
                    'mode': 'analyze'
                }, 400

            # Calculate required margin using the appropriate price
            margin_required, margin_msg = self.fund_manager.calculate_margin_required(
                symbol, exchange, product, quantity, margin_calculation_price, action
            )

            if margin_required is None:
                return False, {
                    'status': 'error',
                    'message': f'Unable to calculate margin: {margin_msg}',
                    'mode': 'analyze'
                }, 400

            # Check if this order will close/reduce/reverse an existing position
            existing_position = SandboxPositions.query.filter_by(
                user_id=self.user_id,
                symbol=symbol,
                exchange=exchange,
                product=product
            ).first()

            # Calculate margin to block based on position impact
            actual_margin_to_block = margin_required

            if existing_position and existing_position.quantity != 0:
                # Check if order is opposite to position direction
                if (existing_position.quantity > 0 and action == 'SELL') or \
                   (existing_position.quantity < 0 and action == 'BUY'):
                    # Opposite direction - will reduce or reverse position
                    existing_qty = abs(existing_position.quantity)
                    order_qty = quantity

                    if order_qty <= existing_qty:
                        # Order will only reduce/close position - no new margin needed
                        actual_margin_to_block = Decimal('0')
                        logger.info(f"Order will reduce position - no margin required")
                    else:
                        # Order will reverse position - only block margin for excess quantity
                        excess_qty = order_qty - existing_qty
                        actual_margin_to_block, _ = self.fund_manager.calculate_margin_required(
                            symbol, exchange, product, excess_qty, margin_calculation_price, action
                        )
                        logger.info(f"Order will reverse position - margin for {excess_qty} shares: ₹{actual_margin_to_block}")

            # Check margin availability and block margin if needed
            # Margin is required for:
            # - All BUY orders (long positions)
            # - SELL orders for options (selling options requires margin)
            # - SELL orders for futures (short selling futures requires margin)
            # - SELL orders for equity in MIS (intraday short selling requires margin)
            # - SELL orders for equity in NRML (if short selling is allowed)
            # Note: SELL orders for equity in CNC don't need margin blocking (selling owned shares)
            should_block_margin = False

            if action == 'BUY':
                # All BUY orders require margin
                should_block_margin = True
            elif action == 'SELL':
                if is_option(symbol, exchange):
                    # Selling options requires margin
                    should_block_margin = True
                elif is_future(symbol, exchange):
                    # Short selling futures requires margin
                    should_block_margin = True
                elif product in ['MIS', 'NRML']:
                    # Intraday/margin short selling of equity requires margin
                    should_block_margin = True
                # CNC SELL doesn't need margin (selling owned shares)

            if should_block_margin:
                if actual_margin_to_block > 0:
                    # Check and block margin only for new exposure
                    can_trade, margin_check_msg = self.fund_manager.check_margin_available(actual_margin_to_block)
                    if not can_trade:
                        return False, {
                            'status': 'error',
                            'message': margin_check_msg,
                            'mode': 'analyze'
                        }, 400

                    # Block margin
                    success, block_msg = self.fund_manager.block_margin(
                        actual_margin_to_block,
                        f"Order: {symbol} {action} {quantity}"
                    )
                    if not success:
                        return False, {
                            'status': 'error',
                            'message': block_msg,
                            'mode': 'analyze'
                        }, 400
                    logger.info(f"Blocked margin ₹{actual_margin_to_block} for {symbol} {action} {quantity} order")
                else:
                    logger.info(f"No margin to block for {symbol} {action} - will reduce existing position")
            else:
                logger.info(f"No margin blocking required for {symbol} {action} {product} (CNC SELL of owned shares)")

            # Generate unique order ID
            orderid = self._generate_order_id()

            # Check if order should be rejected (CNC SELL validation failed)
            if cnc_sell_rejection_reason:
                # Create rejected order for audit trail
                # For MARKET orders, store the LTP we used for margin calculation as reference price
                order_price_to_store = margin_calculation_price if price_type == 'MARKET' else price

                order = SandboxOrders(
                    orderid=orderid,
                    user_id=self.user_id,
                    strategy=strategy,
                    symbol=symbol,
                    exchange=exchange,
                    action=action,
                    quantity=quantity,
                    price=order_price_to_store,
                    trigger_price=trigger_price,
                    price_type=price_type,
                    product=product,
                    order_status='rejected',
                    average_price=None,
                    filled_quantity=0,
                    pending_quantity=0,
                    rejection_reason=cnc_sell_rejection_reason,
                    margin_blocked=Decimal('0'),  # No margin blocked for rejected orders
                    order_timestamp=datetime.now(pytz.timezone('Asia/Kolkata'))
                )

                db_session.add(order)
                db_session.commit()

                logger.info(f"Order rejected: {orderid} - {symbol} {action} {quantity} - Reason: {cnc_sell_rejection_reason}")

                return False, {
                    'status': 'error',
                    'orderid': orderid,
                    'message': cnc_sell_rejection_reason,
                    'mode': 'analyze'
                }, 400

            # Create order record (for accepted orders)
            # For MARKET orders, store the LTP we used for margin calculation as reference price
            order_price_to_store = margin_calculation_price if price_type == 'MARKET' else price

            order = SandboxOrders(
                orderid=orderid,
                user_id=self.user_id,
                strategy=strategy,
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=quantity,
                price=order_price_to_store,
                trigger_price=trigger_price,
                price_type=price_type,
                product=product,
                order_status='open',
                average_price=None,
                filled_quantity=0,
                pending_quantity=quantity,
                rejection_reason=None,
                margin_blocked=actual_margin_to_block,  # Store exact margin blocked
                order_timestamp=datetime.now(pytz.timezone('Asia/Kolkata'))
            )

            db_session.add(order)
            db_session.commit()

            logger.info(f"Order placed: {orderid} - {symbol} {action} {quantity} @ {price_type}")

            # Execute MARKET orders immediately
            if price_type == 'MARKET':
                try:
                    from sandbox.execution_engine import ExecutionEngine
                    engine = ExecutionEngine()

                    # Fetch current quote
                    quote = engine._fetch_quote(symbol, exchange)
                    if quote:
                        # Process the order immediately
                        engine._process_order(order, quote)
                        logger.info(f"Market order {orderid} executed immediately")
                    else:
                        logger.warning(f"Could not fetch quote for {symbol} on {exchange}, order remains open")
                except Exception as e:
                    logger.error(f"Error executing market order immediately: {e}")
                    # Order remains in 'open' status if execution fails

            return True, {
                'status': 'success',
                'orderid': orderid,
                'mode': 'analyze'
            }, 200

        except Exception as e:
            db_session.rollback()
            logger.error(f"Error placing order: {e}")
            return False, {
                'status': 'error',
                'message': f'Error placing order: {str(e)}',
                'mode': 'analyze'
            }, 500

    def modify_order(self, orderid, new_data):
        """
        Modify an existing open order

        Args:
            orderid: str - Order ID to modify
            new_data: dict - New order parameters (quantity, price, trigger_price)

        Returns:
            tuple: (success: bool, response: dict, status_code: int)
        """
        try:
            # Get existing order
            order = SandboxOrders.query.filter_by(
                orderid=orderid,
                user_id=self.user_id
            ).first()

            if not order:
                return False, {
                    'status': 'error',
                    'message': f'Order {orderid} not found',
                    'mode': 'analyze'
                }, 404

            if order.order_status != 'open':
                return False, {
                    'status': 'error',
                    'message': f'Cannot modify order in {order.order_status} status',
                    'mode': 'analyze'
                }, 400

            # Update order parameters
            if 'quantity' in new_data:
                new_quantity = int(new_data['quantity'])
                # Validate lot size
                symbol_obj = SymToken.query.filter_by(
                    symbol=order.symbol,
                    exchange=order.exchange
                ).first()
                if symbol_obj and order.exchange in ['NFO', 'BFO', 'CDS', 'BCD', 'MCX', 'NCDEX']:
                    lot_size = symbol_obj.lotsize or 1
                    if new_quantity % lot_size != 0:
                        return False, {
                            'status': 'error',
                            'message': f'Quantity must be in multiples of lot size {lot_size}',
                            'mode': 'analyze'
                        }, 400
                order.quantity = new_quantity
                order.pending_quantity = new_quantity

            if 'price' in new_data and new_data['price']:
                order.price = Decimal(str(new_data['price']))

            if 'trigger_price' in new_data and new_data['trigger_price']:
                order.trigger_price = Decimal(str(new_data['trigger_price']))

            order.update_timestamp = datetime.now(pytz.timezone('Asia/Kolkata'))

            db_session.commit()

            logger.info(f"Order modified: {orderid}")

            return True, {
                'status': 'success',
                'orderid': orderid,
                'message': 'Order modified successfully',
                'mode': 'analyze'
            }, 200

        except Exception as e:
            db_session.rollback()
            logger.error(f"Error modifying order {orderid}: {e}")
            return False, {
                'status': 'error',
                'message': f'Error modifying order: {str(e)}',
                'mode': 'analyze'
            }, 500

    def cancel_order(self, orderid):
        """
        Cancel an existing open order

        Args:
            orderid: str - Order ID to cancel

        Returns:
            tuple: (success: bool, response: dict, status_code: int)
        """
        try:
            # Get existing order
            order = SandboxOrders.query.filter_by(
                orderid=orderid,
                user_id=self.user_id
            ).first()

            if not order:
                return False, {
                    'status': 'error',
                    'message': f'Order {orderid} not found',
                    'mode': 'analyze'
                }, 404

            if order.order_status != 'open':
                return False, {
                    'status': 'error',
                    'message': f'Cannot cancel order in {order.order_status} status',
                    'mode': 'analyze'
                }, 400

            # Update order status
            order.order_status = 'cancelled'
            order.update_timestamp = datetime.now(pytz.timezone('Asia/Kolkata'))

            # Release blocked margin using the exact amount that was blocked
            if hasattr(order, 'margin_blocked') and order.margin_blocked and order.margin_blocked > 0:
                self.fund_manager.release_margin(
                    order.margin_blocked, 0,
                    f"Order cancelled: {orderid}"
                )
                logger.info(f"Released margin ₹{order.margin_blocked} for cancelled order {orderid}")
            else:
                # Fallback for old orders without margin_blocked field
                # Need to recalculate margin that was blocked based on order parameters
                # Get symbol info to determine if margin was blocked for this order
                symbol_obj = SymToken.query.filter_by(
                    symbol=order.symbol,
                    exchange=order.exchange
                ).first()

                if symbol_obj:
                    # Determine if this order would have had margin blocked
                    should_release_margin = False

                    if order.action == 'BUY':
                        should_release_margin = True
                    elif order.action == 'SELL':
                        if is_option(order.symbol, order.exchange) or is_future(order.symbol, order.exchange):
                            should_release_margin = True
                        elif order.product in ['MIS', 'NRML']:
                            should_release_margin = True

                    if should_release_margin:
                        # Get price for margin calculation
                        if not order.price:
                            # If price is not set (old MARKET orders), fetch current LTP
                            try:
                                from sandbox.execution_engine import ExecutionEngine
                                engine = ExecutionEngine()
                                quote = engine._fetch_quote(order.symbol, order.exchange)
                                if quote and quote.get('ltp'):
                                    order_price = Decimal(str(quote['ltp']))
                                else:
                                    logger.error(f"Cannot fetch LTP for {order.symbol} to calculate margin release")
                                    order_price = Decimal('0')
                            except Exception as e:
                                logger.error(f"Error fetching quote for margin release: {e}")
                                order_price = Decimal('0')
                        else:
                            order_price = order.price

                        # Calculate margin that was blocked
                        if order_price > 0:
                            margin_blocked, _ = self.fund_manager.calculate_margin_required(
                                order.symbol, order.exchange, order.product,
                                order.quantity, order_price, order.action
                            )
                            if margin_blocked:
                                self.fund_manager.release_margin(
                                    margin_blocked, 0,
                                    f"Order cancelled: {orderid}"
                                )
                                logger.info(f"Released calculated margin ₹{margin_blocked} for cancelled order {orderid}")
                    else:
                        logger.info(f"No margin to release for cancelled order {orderid} ({order.action} {order.product})")

            db_session.commit()

            logger.info(f"Order cancelled: {orderid}")

            return True, {
                'status': 'success',
                'orderid': orderid,
                'message': 'Order cancelled successfully',
                'mode': 'analyze'
            }, 200

        except Exception as e:
            db_session.rollback()
            logger.error(f"Error cancelling order {orderid}: {e}")
            return False, {
                'status': 'error',
                'message': f'Error cancelling order: {str(e)}',
                'mode': 'analyze'
            }, 500

    def get_orderbook(self):
        """Get all orders for the user for current session only"""
        try:
            from datetime import datetime, time, timedelta
            import os

            # Get session expiry time from config (e.g., '03:00')
            session_expiry_str = os.getenv('SESSION_EXPIRY_TIME', '03:00')
            expiry_hour, expiry_minute = map(int, session_expiry_str.split(':'))

            # Get current time
            now = datetime.now()
            today = now.date()

            # Calculate session start time
            # If current time is before session expiry (e.g., before 3 AM),
            # session started yesterday at expiry time
            session_expiry_time = time(expiry_hour, expiry_minute)

            if now.time() < session_expiry_time:
                # We're in the early morning before session expiry
                # Session started yesterday at expiry time
                session_start = datetime.combine(today - timedelta(days=1), session_expiry_time)
            else:
                # We're after session expiry time
                # Session started today at expiry time
                session_start = datetime.combine(today, session_expiry_time)

            orders = SandboxOrders.query.filter(
                SandboxOrders.user_id == self.user_id,
                SandboxOrders.order_timestamp >= session_start
            ).order_by(
                SandboxOrders.order_timestamp.desc()
            ).all()

            orderbook = []
            for order in orders:
                orderbook.append({
                    'orderid': order.orderid,
                    'symbol': order.symbol,
                    'exchange': order.exchange,
                    'action': order.action,
                    'quantity': order.quantity,
                    'price': float(order.price) if order.price else 0.0,
                    'trigger_price': float(order.trigger_price) if order.trigger_price else 0.0,
                    'pricetype': order.price_type,  # Match broker API format
                    'product': order.product,
                    'order_status': order.order_status,  # Match broker API format
                    'average_price': float(order.average_price) if order.average_price else 0.0,
                    'filled_quantity': order.filled_quantity,
                    'pending_quantity': order.pending_quantity,
                    'rejection_reason': order.rejection_reason or '',  # Include rejection reason
                    'timestamp': order.order_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'strategy': order.strategy or ''
                })

            # Calculate statistics
            statistics = self._calculate_order_statistics(orders)

            return True, {
                'status': 'success',
                'data': {
                    'orders': orderbook,
                    'statistics': statistics
                },
                'mode': 'analyze'
            }, 200

        except Exception as e:
            logger.error(f"Error getting orderbook: {e}")
            return False, {
                'status': 'error',
                'message': f'Error getting orderbook: {str(e)}',
                'mode': 'analyze'
            }, 500

    def get_order_status(self, orderid):
        """Get status of a specific order"""
        try:
            order = SandboxOrders.query.filter_by(
                orderid=orderid,
                user_id=self.user_id
            ).first()

            if not order:
                return False, {
                    'status': 'error',
                    'message': f'Order {orderid} not found',
                    'mode': 'analyze'
                }, 404

            return True, {
                'status': 'success',
                'data': {
                    'orderid': order.orderid,
                    'symbol': order.symbol,
                    'exchange': order.exchange,
                    'action': order.action,
                    'quantity': order.quantity,
                    'price': float(order.price) if order.price else 0.0,
                    'trigger_price': float(order.trigger_price) if order.trigger_price else 0.0,
                    'price_type': order.price_type,
                    'product': order.product,
                    'status': order.order_status,
                    'average_price': float(order.average_price) if order.average_price else 0.0,
                    'filled_quantity': order.filled_quantity,
                    'pending_quantity': order.pending_quantity,
                    'timestamp': order.order_timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'strategy': order.strategy or ''
                },
                'mode': 'analyze'
            }, 200

        except Exception as e:
            logger.error(f"Error getting order status: {e}")
            return False, {
                'status': 'error',
                'message': f'Error getting order status: {str(e)}',
                'mode': 'analyze'
            }, 500

    def _validate_order(self, order_data):
        """Validate order parameters"""
        required_fields = ['symbol', 'exchange', 'action', 'quantity', 'price_type', 'product']

        for field in required_fields:
            if field not in order_data or not order_data[field]:
                return False, f'Missing required field: {field}'

        # Validate action
        if order_data['action'].upper() not in ['BUY', 'SELL']:
            return False, 'Invalid action. Must be BUY or SELL'

        # Validate price_type
        if order_data['price_type'].upper() not in ['MARKET', 'LIMIT', 'SL', 'SL-M']:
            return False, 'Invalid price_type. Must be MARKET, LIMIT, SL, or SL-M'

        # Validate product
        if order_data['product'].upper() not in ['CNC', 'NRML', 'MIS']:
            return False, 'Invalid product. Must be CNC, NRML, or MIS'

        # Validate quantity
        try:
            quantity = int(order_data['quantity'])
            if quantity <= 0:
                return False, 'Quantity must be positive'
        except (ValueError, TypeError):
            return False, 'Invalid quantity'

        # Validate price for LIMIT and SL orders
        if order_data['price_type'].upper() in ['LIMIT', 'SL']:
            if 'price' not in order_data or not order_data['price']:
                return False, f'{order_data["price_type"]} orders require price'
            try:
                price = float(order_data['price'])
                if price <= 0:
                    return False, 'Price must be positive'
            except (ValueError, TypeError):
                return False, 'Invalid price'

        # Validate trigger_price for SL and SL-M orders
        if order_data['price_type'].upper() in ['SL', 'SL-M']:
            if 'trigger_price' not in order_data or not order_data['trigger_price']:
                return False, f'{order_data["price_type"]} orders require trigger_price'
            try:
                trigger_price = float(order_data['trigger_price'])
                if trigger_price <= 0:
                    return False, 'Trigger price must be positive'
            except (ValueError, TypeError):
                return False, 'Invalid trigger_price'

        # Validate exchange
        valid_exchanges = ['NSE', 'BSE', 'NFO', 'BFO', 'CDS', 'BCD', 'MCX', 'NCDEX']
        if order_data['exchange'].upper() not in valid_exchanges:
            return False, f'Invalid exchange. Must be one of {", ".join(valid_exchanges)}'

        return True, 'Validation passed'

    def _generate_order_id(self):
        """
        Generate unique order ID in format: YYMMDD + 8-digit sequence
        Example: 25100100000001 (Year 2025, Oct 1st, sequence 00000001)
        """
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        date_prefix = now.strftime('%y%m%d')  # YYMMDD format

        # Get the count of orders for today to generate sequence number
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_orders = SandboxOrders.query.filter(
            SandboxOrders.user_id == self.user_id,
            SandboxOrders.order_timestamp >= today_start
        ).count()

        # Sequence is orders count + 1, padded to 8 digits
        sequence = str(today_orders + 1).zfill(8)

        return f"{date_prefix}{sequence}"

    def _calculate_order_statistics(self, orders):
        """Calculate order statistics matching broker API format"""
        # Count orders by action
        total_buy_orders = sum(1 for o in orders if o.action == 'BUY')
        total_sell_orders = sum(1 for o in orders if o.action == 'SELL')

        # Count orders by status
        total_completed_orders = sum(1 for o in orders if o.order_status == 'complete')
        total_open_orders = sum(1 for o in orders if o.order_status == 'open')
        total_rejected_orders = sum(1 for o in orders if o.order_status == 'rejected')

        return {
            'total_buy_orders': total_buy_orders,
            'total_sell_orders': total_sell_orders,
            'total_completed_orders': total_completed_orders,
            'total_open_orders': total_open_orders,
            'total_rejected_orders': total_rejected_orders
        }
