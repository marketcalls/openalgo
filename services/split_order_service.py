import importlib
import traceback
import copy
from typing import Tuple, Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor as log_executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from utils.api_analyzer import analyze_request, generate_order_id
from utils.constants import (
    VALID_EXCHANGES,
    VALID_ACTIONS,
    VALID_PRICE_TYPES,
    VALID_PRODUCT_TYPES,
    REQUIRED_ORDER_FIELDS
)
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Maximum number of orders allowed
MAX_ORDERS = 100

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
    analyzer_request['api_type'] = 'splitorder'
    
    # Log to analyzer database
    log_executor.submit(async_log_analyzer, analyzer_request, error_response, 'splitorder')
    
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

def place_single_order(
    order_data: Dict[str, Any], 
    broker_module: Any, 
    auth_token: str, 
    order_num: int, 
    total_orders: int
) -> Dict[str, Any]:
    """
    Place a single order and emit event
    
    Args:
        order_data: Order data
        broker_module: Broker module
        auth_token: Authentication token
        order_num: Order number in the sequence
        total_orders: Total number of orders
        
    Returns:
        Order result dictionary
    """
    try:
        # Place the order using place_order_api
        res, response_data, order_id = broker_module.place_order_api(order_data, auth_token)

        if res.status == 200:
            # Emit order event for toast notification with batch info
            socketio.emit('order_event', {
                'symbol': order_data['symbol'],
                'action': order_data['action'],
                'orderid': order_id,
                'exchange': order_data.get('exchange', 'Unknown'),
                'price_type': order_data.get('pricetype', 'Unknown'),
                'product_type': order_data.get('product', 'Unknown'),
                'mode': 'live',
                'order_num': order_num,
                'quantity': int(order_data['quantity']),
                'batch_order': True,
                'is_last_order': order_num == total_orders
            })

            # Return response without batch info
            return {
                'order_num': order_num,
                'quantity': int(order_data['quantity']),
                'status': 'success',
                'orderid': order_id
            }
        else:
            message = response_data.get('message', 'Failed to place order') if isinstance(response_data, dict) else 'Failed to place order'
            return {
                'order_num': order_num,
                'quantity': int(order_data['quantity']),
                'status': 'error',
                'message': message
            }

    except Exception as e:
        logger.error(f"Error placing order {order_num}: {e}")
        return {
            'order_num': order_num,
            'quantity': int(order_data['quantity']),
            'status': 'error',
            'message': 'Failed to place order due to internal error'
        }

def split_order_with_auth(
    split_data: Dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Split a large order into multiple orders of specified size using provided auth token.
    
    Args:
        split_data: Split order data
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    split_request_data = copy.deepcopy(original_data)
    if 'apikey' in split_request_data:
        split_request_data.pop('apikey', None)
    
    # Validate quantities
    try:
        split_size = int(split_data['splitsize'])
        total_quantity = int(split_data['quantity'])
        if split_size <= 0:
            error_message = 'Split size must be greater than 0'
            if get_analyze_mode():
                return False, emit_analyzer_error(original_data, error_message), 400
            error_response = {'status': 'error', 'message': error_message}
            log_executor.submit(async_log_order, 'splitorder', original_data, error_response)
            return False, error_response, 400

        # Calculate number of full-size orders and remaining quantity
        num_full_orders = total_quantity // split_size
        remaining_qty = total_quantity % split_size

        # Check if total number of orders exceeds limit
        total_orders = num_full_orders + (1 if remaining_qty > 0 else 0)
        if total_orders > MAX_ORDERS:
            error_message = f'Total number of orders would exceed maximum limit of {MAX_ORDERS}'
            if get_analyze_mode():
                return False, emit_analyzer_error(original_data, error_message), 400
            error_response = {'status': 'error', 'message': error_message}
            log_executor.submit(async_log_order, 'splitorder', original_data, error_response)
            return False, error_response, 400

    except ValueError:
        error_message = 'Invalid quantity or split size'
        if get_analyze_mode():
            return False, emit_analyzer_error(original_data, error_message), 400
        error_response = {'status': 'error', 'message': error_message}
        log_executor.submit(async_log_order, 'splitorder', original_data, error_response)
        return False, error_response, 400
    
    # If in analyze mode, analyze each order
    if get_analyze_mode():
        analyze_results = []
        
        # Analyze full-size orders
        for i in range(num_full_orders):
            order_data = copy.deepcopy(split_data)
            order_data['quantity'] = str(split_size)
            
            # Analyze the order
            _, analysis = analyze_request(order_data, 'splitorder', True)
            
            if analysis.get('status') == 'success':
                analyze_results.append({
                    'order_num': i + 1,
                    'quantity': split_size,
                    'status': 'success',
                    'orderid': generate_order_id()
                })
            else:
                analyze_results.append({
                    'order_num': i + 1,
                    'quantity': split_size,
                    'status': 'error',
                    'message': analysis.get('message', 'Analysis failed')
                })

        # Analyze remaining quantity if any
        if remaining_qty > 0:
            order_data = copy.deepcopy(split_data)
            order_data['quantity'] = str(remaining_qty)
            
            _, analysis = analyze_request(order_data, 'splitorder', True)
            
            if analysis.get('status') == 'success':
                analyze_results.append({
                    'order_num': num_full_orders + 1,
                    'quantity': remaining_qty,
                    'status': 'success',
                    'orderid': generate_order_id()
                })
            else:
                analyze_results.append({
                    'order_num': num_full_orders + 1,
                    'quantity': remaining_qty,
                    'status': 'error',
                    'message': analysis.get('message', 'Analysis failed')
                })

        response_data = {
            'mode': 'analyze',
            'status': 'success',
            'total_quantity': total_quantity,
            'split_size': split_size,
            'results': analyze_results
        }

        # Store complete request data without apikey
        analyzer_request = split_request_data.copy()
        analyzer_request['api_type'] = 'splitorder'
        
        # Log to analyzer database
        log_executor.submit(async_log_analyzer, analyzer_request, response_data, 'splitorder')
        
        # Emit socket event for toast notification
        socketio.emit('analyzer_update', {
            'request': analyzer_request,
            'response': response_data
        })
        
        return True, response_data, 200

    # Live mode - process actual orders
    broker_module = import_broker_module(broker)
    if broker_module is None:
        error_response = {
            'status': 'error',
            'message': 'Broker-specific module not found'
        }
        log_executor.submit(async_log_order, 'splitorder', original_data, error_response)
        return False, error_response, 404

    # Process orders concurrently
    results = []
    
    # Create a ThreadPoolExecutor for concurrent order placement
    with ThreadPoolExecutor(max_workers=10) as order_executor:
        # Prepare orders for concurrent execution
        futures = []
        
        # Submit full-size orders
        for i in range(num_full_orders):
            order_data = copy.deepcopy(split_data)
            order_data['quantity'] = str(split_size)
            futures.append(
                order_executor.submit(
                    place_single_order,
                    order_data,
                    broker_module,
                    auth_token,
                    i + 1,
                    total_orders
                )
            )

        # Submit remaining quantity order if any
        if remaining_qty > 0:
            order_data = copy.deepcopy(split_data)
            order_data['quantity'] = str(remaining_qty)
            futures.append(
                order_executor.submit(
                    place_single_order,
                    order_data,
                    broker_module,
                    auth_token,
                    total_orders,
                    total_orders
                )
            )

        # Collect results as they complete
        for future in as_completed(futures):
            result = future.result()
            results.append(result)

        # Sort results by order_num to maintain order in response
        results.sort(key=lambda x: x['order_num'])

        # Log the split order results
        response_data = {
            'status': 'success',
            'total_quantity': total_quantity,
            'split_size': split_size,
            'results': results
        }
        log_executor.submit(async_log_order, 'splitorder', split_request_data, response_data)

        return True, response_data, 200

def split_order(
    split_data: Dict[str, Any],
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Split a large order into multiple orders of specified size.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        split_data: Split order data
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(split_data)
    if api_key:
        original_data['apikey'] = api_key
    
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Add API key to split data
        split_data['apikey'] = api_key
        
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403
        
        return split_order_with_auth(split_data, AUTH_TOKEN, broker_name, original_data)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return split_order_with_auth(split_data, auth_token, broker, original_data)
    
    # Case 3: Invalid parameters
    else:
        error_response = {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }
        return False, error_response, 400
