import importlib
import traceback
from typing import Tuple, Dict, Any, Optional, Union
from database.auth_db import get_auth_token_broker
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

def import_broker_module(broker_name: str) -> Optional[Any]:
    """
    Dynamically import the broker-specific funds module.
    
    Args:
        broker_name: Name of the broker
        
    Returns:
        The imported module or None if import fails
    """
    try:
        module_path = f'broker.{broker_name}.api.funds'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

def get_funds_with_auth(auth_token: str, broker: str) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get account funds and margin details from the broker using provided auth token.
    
    Args:
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    broker_module = import_broker_module(broker)
    if broker_module is None:
        return False, {
            'status': 'error',
            'message': 'Broker-specific module not found'
        }, 404

    try:
        # Get funds data using broker's implementation
        funds = broker_module.get_margin_data(auth_token)
        
        return True, {
            'status': 'success',
            'data': funds
        }, 200
    except Exception as e:
        logger.error(f"Error in broker_module.get_margin_data: {e}")
        traceback.print_exc()
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500

def get_funds(api_key: Optional[str] = None, auth_token: Optional[str] = None, broker: Optional[str] = None) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get account funds and margin details from the broker.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            return False, {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }, 403
        return get_funds_with_auth(AUTH_TOKEN, broker_name)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_funds_with_auth(auth_token, broker)
    
    # Case 3: Invalid parameters
    else:
        return False, {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }, 400
