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
    SandboxOrders, SandboxTrades, db_session
)
from sandbox.fund_manager import FundManager
from database.symbol import SymToken
from utils.logging import get_logger

logger = get_logger(__name__)


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

            # For market orders, we need to get current quote for margin calculation
            if price_type == 'MARKET':
                # Use a reference price for margin calculation (will be filled at actual LTP)
                # Get last close price or use a default
                price = Decimal('100')  # Placeholder - will be replaced by execution engine

            # Calculate required margin
            margin_required, margin_msg = self.fund_manager.calculate_margin_required(
                symbol, exchange, product, quantity, price
            )

            if margin_required is None:
                return False, {
                    'status': 'error',
                    'message': f'Unable to calculate margin: {margin_msg}',
                    'mode': 'analyze'
                }, 400

            # Check margin availability (only for BUY orders and SELL orders for options)
            if action == 'BUY' or (action == 'SELL' and symbol_obj.instrumenttype in ['OPTIDX', 'OPTSTK', 'OPTCUR', 'OPTCOM']):
                can_trade, margin_check_msg = self.fund_manager.check_margin_available(margin_required)
                if not can_trade:
                    return False, {
                        'status': 'error',
                        'message': margin_check_msg,
                        'mode': 'analyze'
                    }, 400

                # Block margin
                success, block_msg = self.fund_manager.block_margin(
                    margin_required,
                    f"Order: {symbol} {action} {quantity}"
                )
                if not success:
                    return False, {
                        'status': 'error',
                        'message': block_msg,
                        'mode': 'analyze'
                    }, 400

            # Generate unique order ID
            orderid = self._generate_order_id()

            # Create order record
            order = SandboxOrders(
                orderid=orderid,
                user_id=self.user_id,
                strategy=strategy,
                symbol=symbol,
                exchange=exchange,
                action=action,
                quantity=quantity,
                price=price,
                trigger_price=trigger_price,
                price_type=price_type,
                product=product,
                order_status='open',
                average_price=None,
                filled_quantity=0,
                pending_quantity=quantity,
                rejection_reason=None,
                order_timestamp=datetime.now(pytz.timezone('Asia/Kolkata'))
            )

            db_session.add(order)
            db_session.commit()

            logger.info(f"Order placed: {orderid} - {symbol} {action} {quantity} @ {price_type}")

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

            # Release blocked margin
            if order.action == 'BUY':
                # Calculate margin that was blocked
                margin_blocked, _ = self.fund_manager.calculate_margin_required(
                    order.symbol, order.exchange, order.product,
                    order.quantity, order.price or Decimal('100')
                )
                if margin_blocked:
                    self.fund_manager.release_margin(
                        margin_blocked, 0,
                        f"Order cancelled: {orderid}"
                    )

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
        """Get all orders for the user"""
        try:
            orders = SandboxOrders.query.filter_by(user_id=self.user_id).order_by(
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
                    'price_type': order.price_type,
                    'product': order.product,
                    'status': order.order_status,
                    'average_price': float(order.average_price) if order.average_price else 0.0,
                    'filled_quantity': order.filled_quantity,
                    'pending_quantity': order.pending_quantity,
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
        """Generate unique order ID"""
        # Format: SANDBOX-YYYYMMDD-HHMMSS-UUID
        now = datetime.now(pytz.timezone('Asia/Kolkata'))
        timestamp = now.strftime('%Y%m%d-%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        return f"SANDBOX-{timestamp}-{unique_id}"

    def _calculate_order_statistics(self, orders):
        """Calculate order statistics"""
        total_orders = len(orders)
        completed_orders = sum(1 for o in orders if o.order_status == 'complete')
        open_orders = sum(1 for o in orders if o.order_status == 'open')
        rejected_orders = sum(1 for o in orders if o.order_status == 'rejected')
        cancelled_orders = sum(1 for o in orders if o.order_status == 'cancelled')

        return {
            'total_orders': total_orders,
            'completed': completed_orders,
            'open': open_orders,
            'rejected': rejected_orders,
            'cancelled': cancelled_orders
        }
