import copy
from typing import Tuple, Dict, Any, Optional

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode, set_analyze_mode
from database.analyzer_db import AnalyzerLog, db_session
from database.apilog_db import async_log_order, executor as log_executor
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

def get_analyzer_status_with_auth(
    analyzer_data: Dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get analyzer mode status and statistics.
    
    Args:
        analyzer_data: Analyzer data (currently just apikey)
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
    
    try:
        # Get current analyzer mode
        current_mode = get_analyze_mode()
        
        # Get analyzer logs count
        logs_count = db_session.query(AnalyzerLog).count()
        
        response_data = {
            'status': 'success',
            'data': {
                'mode': 'analyze' if current_mode else 'live',
                'analyze_mode': current_mode,
                'total_logs': logs_count
            }
        }
        
        log_executor.submit(async_log_order, 'analyzer_status', request_data, response_data)
        return True, response_data, 200
        
    except Exception as e:
        logger.error(f"Error getting analyzer status: {e}")
        error_response = {
            'status': 'error',
            'message': str(e)
        }
        log_executor.submit(async_log_order, 'analyzer_status', original_data, error_response)
        return False, error_response, 500

def toggle_analyzer_mode_with_auth(
    analyzer_data: Dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: Dict[str, Any]
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Toggle analyzer mode on/off.
    
    Args:
        analyzer_data: Analyzer data containing mode
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
    
    try:
        # Get the requested mode
        new_mode = analyzer_data.get('mode', False)
        
        # Set the analyzer mode
        set_analyze_mode(new_mode)
        
        # Get logs count for response
        logs_count = db_session.query(AnalyzerLog).count()
        
        response_data = {
            'status': 'success',
            'data': {
                'mode': 'analyze' if new_mode else 'live',
                'analyze_mode': new_mode,
                'total_logs': logs_count,
                'message': f'Analyzer mode switched to {"analyze" if new_mode else "live"}'
            }
        }
        
        log_executor.submit(async_log_order, 'analyzer_toggle', request_data, response_data)
        return True, response_data, 200
        
    except Exception as e:
        logger.error(f"Error toggling analyzer mode: {e}")
        error_response = {
            'status': 'error',
            'message': str(e)
        }
        log_executor.submit(async_log_order, 'analyzer_toggle', original_data, error_response)
        return False, error_response, 500

def get_analyzer_status(
    analyzer_data: Dict[str, Any],
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get analyzer mode status and statistics.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        analyzer_data: Analyzer data (currently just apikey)
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(analyzer_data)
    if api_key:
        original_data['apikey'] = api_key
    
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Add API key to analyzer data
        analyzer_data['apikey'] = api_key
        
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403
        
        return get_analyzer_status_with_auth(analyzer_data, AUTH_TOKEN, broker_name, original_data)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_analyzer_status_with_auth(analyzer_data, auth_token, broker, original_data)
    
    # Case 3: Invalid parameters
    else:
        error_response = {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }
        return False, error_response, 400

def toggle_analyzer_mode(
    analyzer_data: Dict[str, Any],
    api_key: Optional[str] = None,
    auth_token: Optional[str] = None,
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Toggle analyzer mode on/off.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        analyzer_data: Analyzer data containing mode
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(analyzer_data)
    if api_key:
        original_data['apikey'] = api_key
    
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Add API key to analyzer data
        analyzer_data['apikey'] = api_key
        
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403
        
        return toggle_analyzer_mode_with_auth(analyzer_data, AUTH_TOKEN, broker_name, original_data)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return toggle_analyzer_mode_with_auth(analyzer_data, auth_token, broker, original_data)
    
    # Case 3: Invalid parameters
    else:
        error_response = {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }
        return False, error_response, 400