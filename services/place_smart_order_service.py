import importlib
import traceback
import copy
import time
from typing import Tuple, Dict, Any, Optional

from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from utils.api_analyzer import analyze_request, generate_order_id
from utils.constants import (
    VALID_EXCHANGES,
    VALID_ACTIONS,
    VALID_PRICE_TYPES,
    VALID_PRODUCT_TYPES,
    REQUIRED_SMART_ORDER_FIELDS
)
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Smart order delay
SMART_ORDER_DELAY = "0.5"  # Default value, can be overridden by environment variable

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
    analyzer_request['api_type'] = 'placesmartorder'
    
    # Log to analyzer database
    executor.submit(async_log_analyzer, analyzer_request, error_response, 'placesmartorder')
    
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

def validate_smart_order(order_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate smart order data
    
    Args:
        order_data: Order data to validate
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Error message (str) or None if validation succeeded
    """
    # Check for missing mandatory fields
    missing_fields = [field for field in REQUIRED_SMART_ORDER_FIELDS if field not in order_data]
    if missing_fields:
        return False, f'Missing mandatory field(s): {", ".join(missing_fields)}'

    # Validate exchange
    if 'exchange' in order_data and order_data['exchange'] not in VALID_EXCHANGES:
        return False, f'Invalid exchange. Must be one of: {", ".join(VALID_EXCHANGES)}'

    # Convert action to uppercase and validate
    if 'action' in order_data:
        order_data['action'] = order_data['action'].upper()
        if order_data['action'] not in VALID_ACTIONS:
            return False, f'Invalid action. Must be one of: {", ".join(VALID_ACTIONS)} (case insensitive)'

    # Validate price type if provided
    if 'price_type' in order_data and order_data['price_type'] not in VALID_PRICE_TYPES:
        return False, f'Invalid price type. Must be one of: {", ".join(VALID_PRICE_TYPES)}'

    # Validate product type if provided
    if 'product_type' in order_data and order_data['product_type'] not in VALID_PRODUCT_TYPES:
        return False, f'Invalid product type. Must be one of: {", ".join(VALID_PRODUCT_TYPES)}'

    return True, None

def place_smart_order_with_auth(
    order_data: Dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: Dict[str, Any],
    smart_order_delay: str = SMART_ORDER_DELAY
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Place a smart order using provided auth token.
    
    Args:
        order_data: Smart order data
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging
        smart_order_delay: Delay in seconds between order placement and response
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    order_request_data = copy.deepcopy(original_data)
    if 'apikey' in order_request_data:
        order_request_data.pop('apikey', None)
    
    # Validate order data
    is_valid, error_message = validate_smart_order(order_data)
    if not is_valid:
        if get_analyze_mode():
            return False, emit_analyzer_error(original_data, error_message), 400
        error_response = {'status': 'error', 'message': error_message}
        executor.submit(async_log_order, 'placesmartorder', original_data, error_response)
        return False, error_response, 400
    
    # If in analyze mode, analyze the request and return
    if get_analyze_mode():
        _, analysis = analyze_request(order_data, 'placesmartorder', True)
        
        # Store complete request data without apikey
        analyzer_request = order_request_data.copy()
        analyzer_request['api_type'] = 'placesmartorder'
        
        if analysis.get('status') == 'success':
            response_data = {
                'mode': 'analyze',
                'orderid': generate_order_id(),
                'status': 'success'
            }
        else:
            response_data = {
                'mode': 'analyze',
                'status': 'error',
                'message': analysis.get('message', 'Analysis failed')
            }
        
        # Log to analyzer database with complete request and response
        executor.submit(async_log_analyzer, analyzer_request, response_data, 'placesmartorder')
        
        # Emit socket event for toast notification
        socketio.emit('analyzer_update', {
            'request': analyzer_request,
            'response': response_data
        })
        
        return True, response_data, 200

    # Live Mode - Proceed with actual order placement
    broker_module = import_broker_module(broker)
    if broker_module is None:
        error_response = {
            'status': 'error',
            'message': 'Broker-specific module not found'
        }
        executor.submit(async_log_order, 'placesmartorder', original_data, error_response)
        return False, error_response, 404

    try:
        res, response_data, order_id = broker_module.place_smartorder_api(order_data, auth_token)
        
        # Handle case where position size matches current position
        if res is None and response_data.get('status') == 'success' and 'No action needed' in response_data.get('message', ''):
            # Log the no-action-needed case
            order_response_data = {
                'status': 'success',
                'message': 'Positions Already Matched. No Action needed.'
            }
            executor.submit(async_log_order, 'placesmartorder', order_request_data, order_response_data)
            
            # Emit notification for matched positions
            socketio.emit('order_notification', {
                'symbol': order_data.get('symbol'),
                'status': 'info',
                'message': ' Positions Already Matched. No Action needed.'
            })
            return True, order_response_data, 200

        # Log successful order immediately after placement
        if res and res.status == 200:
            order_response_data = {'status': 'success', 'orderid': order_id}
            executor.submit(async_log_order, 'placesmartorder', order_request_data, order_response_data)
            socketio.emit('order_event', {
                'symbol': order_data.get('symbol'),
                'action': order_data.get('action'),
                'orderid': order_id,
                'mode': 'live'
            })
        
    except Exception as e:
        logger.error(f"Error in broker_module.place_smartorder_api: {e}")
        traceback.print_exc()
        error_response = {
            'status': 'error',
            'message': 'Failed to place smart order due to internal error'
        }
        executor.submit(async_log_order, 'placesmartorder', original_data, error_response)
        return False, error_response, 500

    # Add delay if needed
    try:
        time.sleep(float(smart_order_delay))
    except Exception as e:
        logger.error(f"Invalid SMART_ORDER_DELAY value: {smart_order_delay}")
        traceback.print_exc()

    if res and res.status == 200:
        return True, order_response_data, 200
    else:
        message = response_data.get('message', 'Failed to place smart order') if isinstance(response_data, dict) else 'Failed to place smart order'
        error_response = {
            'status': 'error',
            'message': message
        }
        executor.submit(async_log_order, 'placesmartorder', original_data, error_response)
        status_code = res.status if res and hasattr(res, 'status') else 500
        return False, error_response, status_code

def place_smart_order(
    order_data: Dict[str, Any],
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None,
    smart_order_delay: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Place a smart order.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        order_data: Smart order data
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        smart_order_delay: Delay in seconds between order placement and response
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(order_data)
    if api_key:
        original_data['apikey'] = api_key
    
    # Use default delay if not provided
    if smart_order_delay is None:
        smart_order_delay = SMART_ORDER_DELAY
    
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
        
        return place_smart_order_with_auth(order_data, AUTH_TOKEN, broker_name, original_data, smart_order_delay)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return place_smart_order_with_auth(order_data, auth_token, broker, original_data, smart_order_delay)
    
    # Case 3: Invalid parameters
    else:
        error_response = {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }
        return False, error_response, 400
