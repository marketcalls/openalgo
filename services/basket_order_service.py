import importlib
import traceback
import copy
from typing import Tuple, Dict, Any, Optional, List, Union
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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    analyzer_request['api_type'] = 'basketorder'
    
    # Log to analyzer database
    log_executor.submit(async_log_analyzer, analyzer_request, error_response, 'basketorder')
    
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

def validate_order(order_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate individual order data
    
    Args:
        order_data: Order data to validate
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Error message (str) or None if validation succeeded
    """
    # Check for missing mandatory fields
    missing_fields = [field for field in REQUIRED_ORDER_FIELDS if field not in order_data]
    if missing_fields:
        return False, f'Missing mandatory field(s): {", ".join(missing_fields)}'

    # Validate exchange
    if order_data.get('exchange') not in VALID_EXCHANGES:
        return False, f'Invalid exchange. Must be one of: {", ".join(VALID_EXCHANGES)}'

    # Convert action to uppercase and validate
    if 'action' in order_data:
        order_data['action'] = order_data['action'].upper()
        if order_data['action'] not in VALID_ACTIONS:
            return False, f'Invalid action. Must be one of: {", ".join(VALID_ACTIONS)} (case insensitive)'

    # Validate price type
    if 'pricetype' in order_data and order_data['pricetype'] not in VALID_PRICE_TYPES:
        return False, f'Invalid price type. Must be one of: {", ".join(VALID_PRICE_TYPES)}'

    # Validate product type
    if 'product' in order_data and order_data['product'] not in VALID_PRODUCT_TYPES:
        return False, f'Invalid product type. Must be one of: {", ".join(VALID_PRODUCT_TYPES)}'

    return True, None

def place_single_order(
    order_data: Dict[str, Any], 
    broker_module: Any, 
    auth_token: str, 
    total_orders: int, 
    order_index: int
) -> Dict[str, Any]:
    """
    Place a single order and emit event
    
    Args:
        order_data: Order data
        broker_module: Broker module
        auth_token: Authentication token
        total_orders: Total number of orders in the basket
        order_index: Index of the current order
        
    Returns:
        Order result dictionary
    """
    try:
        # Place the order
        res, response_data, order_id = broker_module.place_order_api(order_data, auth_token)

        if res.status == 200:
            # Emit order event for toast notification
            socketio.emit('order_event', {
                'symbol': order_data['symbol'],
                'action': order_data['action'],
                'orderid': order_id,
                'exchange': order_data.get('exchange', 'Unknown'),
                'price_type': order_data.get('pricetype', 'Unknown'),
                'product_type': order_data.get('product', 'Unknown'),
                'mode': 'live',
                'batch_order': True,
                'is_last_order': order_index == total_orders - 1
            })

            return {
                'symbol': order_data['symbol'],
                'status': 'success',
                'orderid': order_id
            }
        else:
            message = response_data.get('message', 'Failed to place order') if isinstance(response_data, dict) else 'Failed to place order'
            return {
                'symbol': order_data['symbol'],
                'status': 'error',
                'message': message
            }

    except Exception as e:
        logger.error(f"Error placing order for {order_data.get('symbol', 'Unknown')}: {e}")
        return {
            'symbol': order_data.get('symbol', 'Unknown'),
            'status': 'error',
            'message': 'Failed to place order due to internal error'
        }

def process_basket_order_with_auth(
    basket_data: Dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Process a basket order using provided auth token.
    
    Args:
        basket_data: Validated basket order data
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    basket_request_data = copy.deepcopy(original_data)
    if 'apikey' in basket_request_data:
        basket_request_data.pop('apikey', None)
    
    api_key = basket_data.get('apikey')
    
    # If in analyze mode, analyze each order and return
    if get_analyze_mode():
        analyze_results = []
        total_orders = len(basket_data['orders'])
        
        for i, order in enumerate(basket_data['orders']):
            # Create order data with common fields from basket order
            order_with_auth = order.copy()
            order_with_auth['apikey'] = api_key
            order_with_auth['strategy'] = basket_data['strategy']
            
            # Validate order
            is_valid, error_message = validate_order(order_with_auth)
            if not is_valid:
                analyze_results.append({
                    'symbol': order.get('symbol', 'Unknown'),
                    'status': 'error',
                    'message': error_message
                })
                continue

            # Analyze the order
            _, analysis = analyze_request(order_with_auth, 'basketorder', True)
            
            if analysis.get('status') == 'success':
                analyze_results.append({
                    'symbol': order.get('symbol', 'Unknown'),
                    'status': 'success',
                    'orderid': generate_order_id(),
                    'batch_order': True,
                    'is_last_order': i == total_orders - 1
                })
            else:
                analyze_results.append({
                    'symbol': order.get('symbol', 'Unknown'),
                    'status': 'error',
                    'message': analysis.get('message', 'Analysis failed')
                })

        response_data = {
            'mode': 'analyze',
            'status': 'success',
            'results': analyze_results
        }

        # Store complete request data without apikey
        analyzer_request = basket_request_data.copy()
        analyzer_request['api_type'] = 'basketorder'
        
        # Log to analyzer database
        log_executor.submit(async_log_analyzer, analyzer_request, response_data, 'basketorder')
        
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
        log_executor.submit(async_log_order, 'basketorder', original_data, error_response)
        return False, error_response, 404

    # Sort orders to prioritize BUY orders before SELL orders
    buy_orders = [order for order in basket_data['orders'] if order.get('action', '').upper() == 'BUY']
    sell_orders = [order for order in basket_data['orders'] if order.get('action', '').upper() == 'SELL']
    sorted_orders = buy_orders + sell_orders
    
    results = []
    total_orders = len(sorted_orders)
    
    # Process BUY orders first
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Process all BUY orders first
        buy_futures = []
        for i, order in enumerate(buy_orders):
            # Create order with authentication fields without modifying original
            order_with_auth = {**order, 'apikey': api_key, 'strategy': basket_data['strategy']}
            buy_futures.append(
                executor.submit(
                    place_single_order,
                    order_with_auth,
                    broker_module,
                    auth_token,
                    total_orders,
                    i
                )
            )
        
        # Wait for all BUY orders to complete
        for future in as_completed(buy_futures):
            result = future.result()
            if result:
                results.append(result)
        
        # Then process SELL orders
        sell_futures = []
        for i, order in enumerate(sell_orders, start=len(buy_orders)):
            # Create order with authentication fields without modifying original
            order_with_auth = {**order, 'apikey': api_key, 'strategy': basket_data['strategy']}
            sell_futures.append(
                executor.submit(
                    place_single_order,
                    order_with_auth,
                    broker_module,
                    auth_token,
                    total_orders,
                    i
                )
            )
        
        # Wait for all SELL orders to complete
        for future in as_completed(sell_futures):
            result = future.result()
            if result:
                results.append(result)

    # Sort results to maintain order consistency
    results.sort(key=lambda x: 0 if x.get('action', '').upper() == 'BUY' else 1)

    # Log the basket order results
    response_data = {
        'status': 'success',
        'results': results
    }
    log_executor.submit(async_log_order, 'basketorder', basket_request_data, response_data)

    return True, response_data, 200

def place_basket_order(
    basket_data: Dict[str, Any],
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Place a basket of orders.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        basket_data: Basket order data containing orders and strategy
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(basket_data)
    
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Add API key to basket data
        basket_data['apikey'] = api_key
        
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403
        
        return process_basket_order_with_auth(basket_data, AUTH_TOKEN, broker_name, original_data)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return process_basket_order_with_auth(basket_data, auth_token, broker, original_data)
    
    # Case 3: Invalid parameters
    else:
        error_response = {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }
        return False, error_response, 400
