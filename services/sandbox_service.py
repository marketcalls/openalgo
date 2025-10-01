# services/sandbox_service.py
"""
Sandbox Service - Routes analyzer mode requests to sandbox implementation

This service acts as a bridge between existing services and the sandbox mode.
When analyzer mode is enabled, all trading operations are routed to the sandbox
virtual trading environment instead of the live broker.
"""

import copy
from typing import Tuple, Dict, Any, Optional
from database.settings_db import get_analyze_mode
from database.auth_db import verify_api_key
from database.apilog_db import async_log_order, executor
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from utils.logging import get_logger
from services.telegram_alert_service import telegram_alert_service

# Import sandbox managers
from sandbox.order_manager import OrderManager
from sandbox.position_manager import PositionManager
from sandbox.holdings_manager import HoldingsManager
from sandbox.fund_manager import FundManager, get_user_funds

logger = get_logger(__name__)


def is_sandbox_mode() -> bool:
    """Check if sandbox/analyzer mode is enabled"""
    return get_analyze_mode()


def get_user_id_from_apikey(api_key: str) -> Optional[str]:
    """Get user ID from API key"""
    try:
        user_id = verify_api_key(api_key)
        return user_id
    except Exception as e:
        logger.error(f"Error getting user ID from API key: {e}")
        return None


def sandbox_place_order(
    order_data: Dict[str, Any],
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Place order in sandbox mode

    Args:
        order_data: Validated order data
        api_key: OpenAlgo API key
        original_data: Original request data for logging

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    try:
        # Get user ID from API key
        user_id = get_user_id_from_apikey(api_key)
        if not user_id:
            return False, {
                'status': 'error',
                'message': 'Invalid API key',
                'mode': 'analyze'
            }, 403

        # Initialize order manager for user
        order_manager = OrderManager(user_id)

        # Convert order_data to sandbox format
        # API uses 'pricetype' and 'product', sandbox uses 'price_type' and 'product'
        sandbox_order_data = {
            'symbol': order_data.get('symbol'),
            'exchange': order_data.get('exchange'),
            'action': order_data.get('action'),
            'quantity': order_data.get('quantity'),
            'price': order_data.get('price', 0),
            'trigger_price': order_data.get('trigger_price', 0),
            'price_type': order_data.get('pricetype') or order_data.get('price_type', 'MARKET'),
            'product': order_data.get('product') or order_data.get('product_type', 'MIS'),
            'strategy': order_data.get('strategy', '')
        }

        # Place order in sandbox
        success, response, status_code = order_manager.place_order(sandbox_order_data)

        # Prepare logging data
        log_request = copy.deepcopy(original_data)
        if 'apikey' in log_request:
            log_request.pop('apikey', None)
        log_request['api_type'] = 'placeorder'

        # Log to analyzer database
        executor.submit(async_log_analyzer, log_request, response, 'placeorder')

        # Emit socket event
        socketio.emit('analyzer_update', {
            'request': log_request,
            'response': response
        })

        # Send Telegram alert
        telegram_alert_service.send_order_alert('placeorder', order_data, response, api_key)

        return success, response, status_code

    except Exception as e:
        logger.error(f"Error in sandbox_place_order: {e}")
        return False, {
            'status': 'error',
            'message': f'Sandbox order placement error: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_modify_order(
    order_data: Dict[str, Any],
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """Modify order in sandbox mode"""
    try:
        user_id = get_user_id_from_apikey(api_key)
        if not user_id:
            return False, {
                'status': 'error',
                'message': 'Invalid API key',
                'mode': 'analyze'
            }, 403

        order_manager = OrderManager(user_id)

        # Extract orderid and new data
        orderid = order_data.get('orderid') or order_data.get('order_id')
        new_data = {}
        if 'quantity' in order_data:
            new_data['quantity'] = order_data['quantity']
        if 'price' in order_data:
            new_data['price'] = order_data['price']
        if 'trigger_price' in order_data:
            new_data['trigger_price'] = order_data['trigger_price']

        success, response, status_code = order_manager.modify_order(orderid, new_data)

        # Log and emit
        log_request = copy.deepcopy(original_data)
        if 'apikey' in log_request:
            log_request.pop('apikey', None)
        log_request['api_type'] = 'modifyorder'

        executor.submit(async_log_analyzer, log_request, response, 'modifyorder')
        socketio.emit('analyzer_update', {'request': log_request, 'response': response})

        return success, response, status_code

    except Exception as e:
        logger.error(f"Error in sandbox_modify_order: {e}")
        return False, {
            'status': 'error',
            'message': f'Sandbox order modification error: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_cancel_order(
    order_data: Dict[str, Any],
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """Cancel order in sandbox mode"""
    try:
        user_id = get_user_id_from_apikey(api_key)
        if not user_id:
            return False, {
                'status': 'error',
                'message': 'Invalid API key',
                'mode': 'analyze'
            }, 403

        order_manager = OrderManager(user_id)

        orderid = order_data.get('orderid') or order_data.get('order_id')
        success, response, status_code = order_manager.cancel_order(orderid)

        # Log and emit
        log_request = copy.deepcopy(original_data)
        if 'apikey' in log_request:
            log_request.pop('apikey', None)
        log_request['api_type'] = 'cancelorder'

        executor.submit(async_log_analyzer, log_request, response, 'cancelorder')
        socketio.emit('analyzer_update', {'request': log_request, 'response': response})

        return success, response, status_code

    except Exception as e:
        logger.error(f"Error in sandbox_cancel_order: {e}")
        return False, {
            'status': 'error',
            'message': f'Sandbox order cancellation error: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_get_orderbook(
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """Get orderbook in sandbox mode"""
    try:
        user_id = get_user_id_from_apikey(api_key)
        if not user_id:
            return False, {
                'status': 'error',
                'message': 'Invalid API key',
                'mode': 'analyze'
            }, 403

        order_manager = OrderManager(user_id)
        success, response, status_code = order_manager.get_orderbook()

        return success, response, status_code

    except Exception as e:
        logger.error(f"Error in sandbox_get_orderbook: {e}")
        return False, {
            'status': 'error',
            'message': f'Error getting orderbook: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_get_order_status(
    order_data: Dict[str, Any],
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """Get order status in sandbox mode"""
    try:
        user_id = get_user_id_from_apikey(api_key)
        if not user_id:
            return False, {
                'status': 'error',
                'message': 'Invalid API key',
                'mode': 'analyze'
            }, 403

        order_manager = OrderManager(user_id)

        orderid = order_data.get('orderid') or order_data.get('order_id')
        success, response, status_code = order_manager.get_order_status(orderid)

        return success, response, status_code

    except Exception as e:
        logger.error(f"Error in sandbox_get_order_status: {e}")
        return False, {
            'status': 'error',
            'message': f'Error getting order status: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_get_positions(
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """Get open positions in sandbox mode"""
    try:
        user_id = get_user_id_from_apikey(api_key)
        if not user_id:
            return False, {
                'status': 'error',
                'message': 'Invalid API key',
                'mode': 'analyze'
            }, 403

        position_manager = PositionManager(user_id)
        success, response, status_code = position_manager.get_open_positions(update_mtm=True)

        return success, response, status_code

    except Exception as e:
        logger.error(f"Error in sandbox_get_positions: {e}")
        return False, {
            'status': 'error',
            'message': f'Error getting positions: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_get_holdings(
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """Get holdings in sandbox mode"""
    try:
        user_id = get_user_id_from_apikey(api_key)
        if not user_id:
            return False, {
                'status': 'error',
                'message': 'Invalid API key',
                'mode': 'analyze'
            }, 403

        holdings_manager = HoldingsManager(user_id)
        success, response, status_code = holdings_manager.get_holdings(update_mtm=True)

        return success, response, status_code

    except Exception as e:
        logger.error(f"Error in sandbox_get_holdings: {e}")
        return False, {
            'status': 'error',
            'message': f'Error getting holdings: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_get_tradebook(
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """Get tradebook in sandbox mode"""
    try:
        user_id = get_user_id_from_apikey(api_key)
        if not user_id:
            return False, {
                'status': 'error',
                'message': 'Invalid API key',
                'mode': 'analyze'
            }, 403

        position_manager = PositionManager(user_id)
        success, response, status_code = position_manager.get_tradebook()

        return success, response, status_code

    except Exception as e:
        logger.error(f"Error in sandbox_get_tradebook: {e}")
        return False, {
            'status': 'error',
            'message': f'Error getting tradebook: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_get_funds(
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """Get funds/margins in sandbox mode"""
    try:
        user_id = get_user_id_from_apikey(api_key)
        if not user_id:
            return False, {
                'status': 'error',
                'message': 'Invalid API key',
                'mode': 'analyze'
            }, 403

        funds = get_user_funds(user_id)

        if funds:
            return True, {
                'status': 'success',
                'data': funds,
                'mode': 'analyze'
            }, 200
        else:
            return False, {
                'status': 'error',
                'message': 'Error getting funds',
                'mode': 'analyze'
            }, 500

    except Exception as e:
        logger.error(f"Error in sandbox_get_funds: {e}")
        return False, {
            'status': 'error',
            'message': f'Error getting funds: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_close_position(
    position_data: Dict[str, Any],
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """Close position in sandbox mode"""
    try:
        user_id = get_user_id_from_apikey(api_key)
        if not user_id:
            return False, {
                'status': 'error',
                'message': 'Invalid API key',
                'mode': 'analyze'
            }, 403

        position_manager = PositionManager(user_id)

        symbol = position_data.get('symbol')
        exchange = position_data.get('exchange')
        product = position_data.get('product_type') or position_data.get('product')

        # If no specific position specified, close all positions
        if not symbol and not exchange:
            # Get all open positions
            success, positions_response, status_code = position_manager.get_open_positions()
            if not success:
                return False, positions_response, status_code

            positions = positions_response.get('data', [])

            if not positions:
                return True, {
                    'status': 'success',
                    'message': 'No open positions to close',
                    'mode': 'analyze'
                }, 200

            closed_count = 0
            failed_count = 0

            # Close each position
            for pos in positions:
                pos_symbol = pos.get('symbol')
                pos_exchange = pos.get('exchange')
                pos_product = pos.get('product')

                if pos.get('quantity', 0) != 0:
                    success, _, _ = position_manager.close_position(pos_symbol, pos_exchange, pos_product)
                    if success:
                        closed_count += 1
                    else:
                        failed_count += 1

            message = f'Closed {closed_count} positions'
            if failed_count > 0:
                message += f' (Failed to close {failed_count} positions)'

            return True, {
                'status': 'success',
                'message': message,
                'closed_positions': closed_count,
                'failed_closures': failed_count,
                'mode': 'analyze'
            }, 200
        else:
            # Close specific position
            success, response, status_code = position_manager.close_position(symbol, exchange, product)
            return success, response, status_code

    except Exception as e:
        logger.error(f"Error in sandbox_close_position: {e}")
        return False, {
            'status': 'error',
            'message': f'Error closing position: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_place_smart_order(
    order_data: Dict[str, Any],
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Place smart order in sandbox mode.
    Smart orders adjust positions to match a target position size.
    """
    try:
        user_id = get_user_id_from_apikey(api_key)
        if not user_id:
            return False, {
                'status': 'error',
                'message': 'Invalid API key',
                'mode': 'analyze'
            }, 403

        position_manager = PositionManager(user_id)
        order_manager = OrderManager(user_id)

        symbol = order_data.get('symbol')
        exchange = order_data.get('exchange')
        product = order_data.get('product_type', 'MIS')
        target_quantity = int(order_data.get('position_size', 0))
        original_quantity = int(order_data.get('quantity', 0))
        original_action = order_data.get('action')

        # Get current position
        success, positions_response, status_code = position_manager.get_open_positions()
        if not success:
            return False, positions_response, status_code

        positions = positions_response.get('data', [])
        current_quantity = 0

        for pos in positions:
            if (pos.get('symbol') == symbol and
                pos.get('exchange') == exchange and
                pos.get('product') == product):
                current_quantity = pos.get('quantity', 0)
                break

        # Special case: position_size=0 with quantity!=0 means fresh trade
        if target_quantity == 0 and current_quantity == 0 and original_quantity != 0:
            # Use the original action and quantity for fresh trade
            action = original_action
            quantity = original_quantity
        elif target_quantity == current_quantity:
            # Position already matches
            if original_quantity == 0:
                message = 'No OpenPosition Found. Not placing Exit order.'
            else:
                message = 'Positions Already Matched. No Action needed.'
            return True, {
                'status': 'success',
                'message': message,
                'mode': 'analyze'
            }, 200
        elif target_quantity == 0 and current_quantity > 0:
            # Close long position
            action = 'SELL'
            quantity = abs(current_quantity)
        elif target_quantity == 0 and current_quantity < 0:
            # Close short position
            action = 'BUY'
            quantity = abs(current_quantity)
        elif current_quantity == 0:
            # Open new position
            action = 'BUY' if target_quantity > 0 else 'SELL'
            quantity = abs(target_quantity)
        else:
            # Adjust existing position
            quantity_diff = target_quantity - current_quantity
            if quantity_diff > 0:
                action = 'BUY'
                quantity = abs(quantity_diff)
            else:
                action = 'SELL'
                quantity = abs(quantity_diff)

        # Place the order to reach target position
        sandbox_order_data = {
            'symbol': symbol,
            'exchange': exchange,
            'action': action,
            'quantity': quantity,
            'price': order_data.get('price', 0),
            'trigger_price': order_data.get('trigger_price', 0),
            'price_type': order_data.get('price_type', 'MARKET'),
            'product': product,
            'strategy': order_data.get('strategy', '')
        }

        success, response, status_code = order_manager.place_order(sandbox_order_data)

        return success, response, status_code

    except Exception as e:
        logger.error(f"Error in sandbox_place_smart_order: {e}")
        return False, {
            'status': 'error',
            'message': f'Error placing smart order: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_cancel_all_orders(
    order_data: Dict[str, Any],
    api_key: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """Cancel all open orders in sandbox mode"""
    try:
        user_id = get_user_id_from_apikey(api_key)
        if not user_id:
            return False, {
                'status': 'error',
                'message': 'Invalid API key',
                'mode': 'analyze'
            }, 403

        order_manager = OrderManager(user_id)

        # Get all open orders from orderbook
        success, orderbook_response, status_code = order_manager.get_orderbook()
        if not success:
            return False, orderbook_response, status_code

        orders = orderbook_response.get('data', {}).get('orders', [])
        open_orders = [order for order in orders if order.get('order_status') in ['open', 'pending', 'trigger_pending']]

        if not open_orders:
            return True, {
                'status': 'success',
                'message': 'No open orders to cancel',
                'canceled_orders': [],
                'failed_cancellations': [],
                'mode': 'analyze'
            }, 200

        canceled_orders = []
        failed_cancellations = []

        # Cancel each open order
        for order in open_orders:
            orderid = order.get('orderid')
            success, response, status_code = order_manager.cancel_order(orderid)

            if success:
                canceled_orders.append(orderid)
            else:
                failed_cancellations.append({
                    'orderid': orderid,
                    'message': response.get('message', 'Failed to cancel')
                })

        message = f'Canceled {len(canceled_orders)} orders. Failed to cancel {len(failed_cancellations)} orders.'

        return True, {
            'status': 'success',
            'message': message,
            'canceled_orders': canceled_orders,
            'failed_cancellations': failed_cancellations,
            'mode': 'analyze'
        }, 200

    except Exception as e:
        logger.error(f"Error in sandbox_cancel_all_orders: {e}")
        return False, {
            'status': 'error',
            'message': f'Error canceling all orders: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_reload_squareoff_schedule() -> Tuple[bool, Dict[str, Any], int]:
    """
    Reload square-off schedule from config without restarting the app
    Useful when square-off times are changed in sandbox settings

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    try:
        from sandbox.squareoff_thread import reload_squareoff_schedule, get_squareoff_scheduler_status

        # Reload the schedule from config
        success, message = reload_squareoff_schedule()

        if success:
            # Get updated status
            status = get_squareoff_scheduler_status()

            return True, {
                'status': 'success',
                'message': message,
                'scheduler_status': status,
                'mode': 'analyze'
            }, 200
        else:
            return False, {
                'status': 'error',
                'message': message,
                'mode': 'analyze'
            }, 500

    except Exception as e:
        logger.error(f"Error reloading square-off schedule: {e}")
        return False, {
            'status': 'error',
            'message': f'Error reloading schedule: {str(e)}',
            'mode': 'analyze'
        }, 500


def sandbox_get_squareoff_status() -> Tuple[bool, Dict[str, Any], int]:
    """
    Get current square-off scheduler status and job details

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    try:
        from sandbox.squareoff_thread import get_squareoff_scheduler_status

        status = get_squareoff_scheduler_status()

        return True, {
            'status': 'success',
            'data': status,
            'mode': 'analyze'
        }, 200

    except Exception as e:
        logger.error(f"Error getting square-off status: {e}")
        return False, {
            'status': 'error',
            'message': f'Error getting status: {str(e)}',
            'mode': 'analyze'
        }, 500
