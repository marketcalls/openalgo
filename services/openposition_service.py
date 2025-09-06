import traceback
import copy
import requests
from typing import Tuple, Dict, Any, Optional

from database.auth_db import get_auth_token_broker
from database.apilog_db import async_log_order, executor as log_executor
from database.settings_db import get_analyze_mode
from database.analyzer_db import async_log_analyzer
from extensions import socketio
from utils.logging import get_logger
from utils.config import get_host_server

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
    analyzer_request['api_type'] = 'openposition'
    
    # Log to analyzer database
    log_executor.submit(async_log_analyzer, analyzer_request, error_response, 'openposition')
    
    # Emit socket event
    socketio.emit('analyzer_update', {
        'request': analyzer_request,
        'response': error_response
    })
    
    return error_response

def get_open_position_with_auth(
    position_data: Dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get quantity of an open position using provided auth token.
    
    Args:
        position_data: Position data containing symbol, exchange, and product
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
            'quantity': 0,
            'status': 'success'
        }

        # Store complete request data without apikey
        analyzer_request = request_data.copy()
        analyzer_request['api_type'] = 'openposition'
        
        # Log to analyzer database
        log_executor.submit(async_log_analyzer, analyzer_request, response_data, 'openposition')
        
        # Emit socket event for toast notification
        socketio.emit('analyzer_update', {
            'request': analyzer_request,
            'response': response_data
        })
        
        return True, response_data, 200

    # Live mode - get position from positionbook
    try:
        # For internal service calls, we'll use the positionbook service directly
        # But for now, we'll maintain compatibility by using the API endpoint
        
        # Prepare positionbook request with just apikey
        positionbook_request = {'apikey': position_data.get('apikey')}
        
        # Make request to positionbook API using HOST_SERVER from config
        host_server = get_host_server()
        positionbook_response = requests.post(f'{host_server}/api/v1/positionbook', json=positionbook_request)
        
        if positionbook_response.status_code != 200:
            error_response = {
                'status': 'error',
                'message': 'Failed to fetch positionbook'
            }
            log_executor.submit(async_log_order, 'openposition', original_data, error_response)
            return False, error_response, positionbook_response.status_code

        positionbook_data = positionbook_response.json()
        if positionbook_data.get('status') != 'success':
            error_response = {
                'status': 'error',
                'message': positionbook_data.get('message', 'Error fetching positionbook')
            }
            log_executor.submit(async_log_order, 'openposition', original_data, error_response)
            return False, error_response, 500

        # Find the specific position
        position_found = None
        for position in positionbook_data['data']:
            if (position.get('symbol') == position_data['symbol'] and
                position.get('exchange') == position_data['exchange'] and
                position.get('product') == position_data['product']):
                position_found = position
                break

        # Return 0 quantity if position not found
        if not position_found:
            response_data = {
                'quantity': 0,
                'status': 'success'
            }
            log_executor.submit(async_log_order, 'openposition', request_data, response_data)
            return True, response_data, 200

        # Return the position quantity
        response_data = {
            'quantity': position_found['quantity'],
            'status': 'success'
        }
        log_executor.submit(async_log_order, 'openposition', request_data, response_data)

        return True, response_data, 200

    except Exception as e:
        logger.error(f"Error processing open position: {e}")
        traceback.print_exc()
        error_response = {
            'status': 'error',
            'message': str(e)
        }
        log_executor.submit(async_log_order, 'openposition', original_data, error_response)
        return False, error_response, 500

def get_open_position(
    position_data: Dict[str, Any],
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get quantity of an open position.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        position_data: Position data containing symbol, exchange, and product
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(position_data)
    if api_key:
        original_data['apikey'] = api_key
    
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Add API key to position data
        position_data['apikey'] = api_key
        
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403
        
        return get_open_position_with_auth(position_data, AUTH_TOKEN, broker_name, original_data)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_open_position_with_auth(position_data, auth_token, broker, original_data)
    
    # Case 3: Invalid parameters
    else:
        error_response = {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }
        return False, error_response, 400
