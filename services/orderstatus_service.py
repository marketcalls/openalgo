import logging
import traceback
import copy
import requests
from typing import Tuple, Dict, Any, Optional

from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor as log_executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    analyzer_request['api_type'] = 'orderstatus'
    
    # Log to analyzer database
    log_executor.submit(async_log_analyzer, analyzer_request, error_response, 'orderstatus')
    
    # Emit socket event
    socketio.emit('analyzer_update', {
        'request': analyzer_request,
        'response': error_response
    })
    
    return error_response

def get_order_status_with_auth(
    status_data: Dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get status of a specific order using provided auth token.
    
    Args:
        status_data: Status data containing orderid
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    request_data = copy.deepcopy(original_data)
    if 'apikey' in request_data:
        request_data.pop('apikey', None)
    
    # If in analyze mode, return simulated response
    if get_analyze_mode():
        response_data = {
            'mode': 'analyze',
            'status': 'success',
            'data': {
                'action': 'BUY',
                'exchange': 'NSE',
                'order_status': 'COMPLETE',
                'orderid': status_data['orderid'],
                'price': 100.0,
                'pricetype': 'MARKET',
                'product': 'MIS',
                'quantity': 10,
                'symbol': 'SBIN',
                'timestamp': '09-Dec-2024 10:00:00',
                'trigger_price': 0
            }
        }

        # Store complete request data without apikey
        analyzer_request = request_data.copy()
        analyzer_request['api_type'] = 'orderstatus'
        
        # Log to analyzer database
        log_executor.submit(async_log_analyzer, analyzer_request, response_data, 'orderstatus')
        
        # Emit socket event for toast notification
        socketio.emit('analyzer_update', {
            'request': analyzer_request,
            'response': response_data
        })
        
        return True, response_data, 200

    # Live mode - get order status from orderbook
    try:
        # For internal service calls, we'll use the orderbook service directly
        # But for now, we'll maintain compatibility by using the API endpoint
        
        # Prepare orderbook request with just apikey
        orderbook_request = {'apikey': status_data.get('apikey')}
        
        # Make request to orderbook API
        orderbook_response = requests.post('http://127.0.0.1:5000/api/v1/orderbook', json=orderbook_request)
        
        if orderbook_response.status_code != 200:
            error_response = {
                'status': 'error',
                'message': 'Failed to fetch orderbook'
            }
            log_executor.submit(async_log_order, 'orderstatus', original_data, error_response)
            return False, error_response, orderbook_response.status_code

        orderbook_data = orderbook_response.json()
        if orderbook_data.get('status') != 'success':
            error_response = {
                'status': 'error',
                'message': orderbook_data.get('message', 'Error fetching orderbook')
            }
            log_executor.submit(async_log_order, 'orderstatus', original_data, error_response)
            return False, error_response, 500

        # Find the specific order in the orderbook
        order_found = None
        for order in orderbook_data['data']['orders']:
            if str(order.get('orderid')) == str(status_data['orderid']):
                order_found = order
                break

        if not order_found:
            error_response = {
                'status': 'error',
                'message': f'Order {status_data["orderid"]} not found'
            }
            log_executor.submit(async_log_order, 'orderstatus', original_data, error_response)
            return False, error_response, 404

        # Return the found order
        response_data = {
            'status': 'success',
            'data': order_found
        }
        log_executor.submit(async_log_order, 'orderstatus', request_data, response_data)

        return True, response_data, 200

    except Exception as e:
        logger.error(f"Error processing order status: {e}")
        traceback.print_exc()
        error_response = {
            'status': 'error',
            'message': str(e)
        }
        log_executor.submit(async_log_order, 'orderstatus', original_data, error_response)
        return False, error_response, 500

def get_order_status(
    status_data: Dict[str, Any],
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get status of a specific order.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        status_data: Status data containing orderid
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(status_data)
    if api_key:
        original_data['apikey'] = api_key
    
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Add API key to status data
        status_data['apikey'] = api_key
        
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }
            if not get_analyze_mode():
                log_executor.submit(async_log_order, 'orderstatus', original_data, error_response)
            return False, error_response, 403
        
        return get_order_status_with_auth(status_data, AUTH_TOKEN, broker_name, original_data)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_order_status_with_auth(status_data, auth_token, broker, original_data)
    
    # Case 3: Invalid parameters
    else:
        error_response = {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }
        return False, error_response, 400
