import importlib
import traceback
import copy
from typing import Tuple, Dict, Any, Optional, List

from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from utils.api_analyzer import analyze_request
from utils.logging import get_logger
from services.telegram_alert_service import telegram_alert_service

# Initialize logger
logger = get_logger(__name__)

def emit_analyzer_error(request_data: Dict[str, Any], error_message: str) -> Dict[str, Any]:
    """
    Helper function to emit analyzer error events
    
    Args:
        request_data: Original request data
        error_message: Error message to emit
        
    Returns:
        Error response dictionary
    """
    error_response = {
        'mode': 'analyze',
        'status': 'error',
        'message': error_message
    }
    
    # Store complete request data without apikey
    analyzer_request = request_data.copy()
    if 'apikey' in analyzer_request:
        del analyzer_request['apikey']
    analyzer_request['api_type'] = 'cancelallorder'
    
    # Log to analyzer database
    executor.submit(async_log_analyzer, analyzer_request, error_response, 'cancelallorder')
    
    # Emit socket event
    socketio.emit('analyzer_update', {
        'request': analyzer_request,
        'response': error_response
    })
    
    return error_response

def import_broker_module(broker_name: str) -> Optional[Any]:
    """
    Dynamically import the broker-specific order API module.
    
    Args:
        broker_name: Name of the broker
        
    Returns:
        The imported module or None if import fails
    """
    try:
        module_path = f'broker.{broker_name}.api.order_api'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

def cancel_all_orders_with_auth(
    order_data: Dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Cancel all orders using provided auth token.
    
    Args:
        order_data: Order data
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    order_request_data = copy.deepcopy(original_data)
    if 'apikey' in order_request_data:
        order_request_data.pop('apikey', None)
    
    # If in analyze mode, route to sandbox for virtual trading
    if get_analyze_mode():
        from services.sandbox_service import sandbox_cancel_all_orders

        api_key = original_data.get('apikey')
        if not api_key:
            return False, emit_analyzer_error(original_data, 'API key required for sandbox mode'), 400

        # Route to sandbox cancel all orders
        success, response_data, status_code = sandbox_cancel_all_orders(
            order_data,
            api_key,
            original_data
        )

        # Store complete request data without apikey
        analyzer_request = order_request_data.copy()
        analyzer_request['api_type'] = 'cancelallorder'

        # Log to analyzer database with complete request and response
        executor.submit(async_log_analyzer, analyzer_request, response_data, 'cancelallorder')

        # Emit socket event for toast notification
        socketio.emit('analyzer_update', {
            'request': analyzer_request,
            'response': response_data
        })

        # Send Telegram alert for analyze mode
        telegram_alert_service.send_order_alert('cancelallorder', order_data, response_data, order_data.get('apikey'))
        return success, response_data, status_code

    broker_module = import_broker_module(broker)
    if broker_module is None:
        error_response = {
            'status': 'error',
            'message': 'Broker-specific module not found'
        }
        executor.submit(async_log_order, 'cancelallorder', original_data, error_response)
        return False, error_response, 404

    try:
        # Use the dynamically imported module's function to cancel all orders
        canceled_orders, failed_cancellations = broker_module.cancel_all_orders_api(order_data, auth_token)
    except Exception as e:
        logger.error(f"Error in broker_module.cancel_all_orders_api: {e}")
        traceback.print_exc()
        error_response = {
            'status': 'error',
            'message': 'Failed to cancel all orders due to internal error'
        }
        executor.submit(async_log_order, 'cancelallorder', original_data, error_response)
        return False, error_response, 500

    # Emit events for each canceled order
    for orderid in canceled_orders:
        socketio.emit('cancel_order_event', {
            'status': 'success', 
            'orderid': orderid,
            'mode': 'live'
        })

    # Prepare response data
    response_data = {
        'status': 'success',
        'canceled_orders': canceled_orders,
        'failed_cancellations': failed_cancellations,
        'message': f'Canceled {len(canceled_orders)} orders. Failed to cancel {len(failed_cancellations)} orders.'
    }

    # Log the action asynchronously
    executor.submit(async_log_order, 'cancelallorder', order_request_data, response_data)

    # Send Telegram alert for live mode
    telegram_alert_service.send_order_alert('cancelallorder', order_data, response_data, order_data.get('apikey'))

    return True, response_data, 200

def cancel_all_orders(
    order_data: Dict[str, Any] = None,
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Cancel all open orders.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        order_data: Order data (optional, may contain additional filters)
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    if order_data is None:
        order_data = {}
    
    original_data = copy.deepcopy(order_data)
    if api_key:
        original_data['apikey'] = api_key
    
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Add API key to order data
        order_data['apikey'] = api_key
        
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403
        
        return cancel_all_orders_with_auth(order_data, AUTH_TOKEN, broker_name, original_data)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return cancel_all_orders_with_auth(order_data, auth_token, broker, original_data)
    
    # Case 3: Invalid parameters
    else:
        error_response = {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }
        return False, error_response, 400
