import importlib
import traceback
import copy
from typing import Tuple, Dict, Any, Optional

from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from utils.logging import get_logger

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
    analyzer_request['api_type'] = 'cancelorder'
    
    # Log to analyzer database
    executor.submit(async_log_analyzer, analyzer_request, error_response, 'cancelorder')
    
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

def cancel_order_with_auth(
    orderid: str,
    auth_token: str,
    broker: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Cancel an order using provided auth token.
    
    Args:
        orderid: Order ID to cancel
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
    
    # If in analyze mode, return success response
    if get_analyze_mode():
        # Store complete request data without apikey
        analyzer_request = order_request_data.copy()
        analyzer_request['api_type'] = 'cancelorder'
        
        response_data = {
            'mode': 'analyze',
            'orderid': orderid,
            'status': 'success'
        }
        
        # Log to analyzer database with complete request and response
        executor.submit(async_log_analyzer, analyzer_request, response_data, 'cancelorder')
        
        # Emit socket event for toast notification
        socketio.emit('analyzer_update', {
            'request': analyzer_request,
            'response': response_data
        })
        
        return True, response_data, 200

    broker_module = import_broker_module(broker)
    if broker_module is None:
        error_response = {
            'status': 'error',
            'message': 'Broker-specific module not found'
        }
        executor.submit(async_log_order, 'cancelorder', original_data, error_response)
        return False, error_response, 404

    try:
        # Use the dynamically imported module's function to cancel the order
        response_message, status_code = broker_module.cancel_order(orderid, auth_token)
    except Exception as e:
        logger.error(f"Error in broker_module.cancel_order: {e}")
        traceback.print_exc()
        error_response = {
            'status': 'error',
            'message': 'Failed to cancel order due to internal error'
        }
        executor.submit(async_log_order, 'cancelorder', original_data, error_response)
        return False, error_response, 500

    if status_code == 200:
        socketio.emit('cancel_order_event', {
            'status': response_message.get('status'),
            'orderid': orderid,
            'mode': 'live'
        })
        order_response_data = {
            'status': 'success',
            'orderid': orderid
        }
        executor.submit(async_log_order, 'cancelorder', order_request_data, order_response_data)
        return True, order_response_data, 200
    else:
        message = response_message.get('message', 'Failed to cancel order') if isinstance(response_message, dict) else 'Failed to cancel order'
        error_response = {
            'status': 'error',
            'message': message
        }
        executor.submit(async_log_order, 'cancelorder', original_data, error_response)
        return False, error_response, status_code

def cancel_order(
    orderid: str,
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Cancel an order.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        orderid: Order ID to cancel
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = {'orderid': orderid}
    if api_key:
        original_data['apikey'] = api_key
    
    # Validate order ID
    if not orderid:
        error_message = 'Order ID is missing'
        error_response = {'status': 'error', 'message': error_message}
        executor.submit(async_log_order, 'cancelorder', original_data, error_response)
        return False, error_response, 400
    
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403
        
        return cancel_order_with_auth(orderid, AUTH_TOKEN, broker_name, original_data)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return cancel_order_with_auth(orderid, auth_token, broker, original_data)
    
    # Case 3: Invalid parameters
    else:
        error_response = {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }
        return False, error_response, 400
