import importlib
import traceback
from typing import Tuple, Dict, Any, Optional, List, Union
from database.auth_db import get_auth_token_broker, Auth, db_session, verify_api_key
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

def import_broker_module(broker_name: str) -> Optional[Any]:
    """
    Dynamically import the broker-specific data module.
    
    Args:
        broker_name: Name of the broker
        
    Returns:
        The imported module or None if import fails
    """
    try:
        module_path = f'broker.{broker_name}.api.data'
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None

def get_depth_with_auth(
    auth_token: str, 
    feed_token: Optional[str], 
    broker: str, 
    symbol: str, 
    exchange: str,
    user_id: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get market depth for a symbol using provided auth tokens.
    
    Args:
        auth_token: Authentication token for the broker API
        feed_token: Feed token for market data (if required by broker)
        broker: Name of the broker
        symbol: Trading symbol
        exchange: Exchange (e.g., NSE, BSE)
        user_id: User ID for broker-specific functionality
        
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
        # Initialize broker's data handler based on broker's requirements
        if hasattr(broker_module.BrokerData.__init__, '__code__'):
            # Check number of parameters the broker's __init__ accepts
            param_count = broker_module.BrokerData.__init__.__code__.co_argcount
            if param_count > 3:  # More than self, auth_token, and feed_token
                data_handler = broker_module.BrokerData(auth_token, feed_token, user_id)
            elif param_count > 2:  # More than self and auth_token
                data_handler = broker_module.BrokerData(auth_token, feed_token)
            else:
                data_handler = broker_module.BrokerData(auth_token)
        else:
            # Fallback to just auth token if we can't inspect
            data_handler = broker_module.BrokerData(auth_token)
            
        depth = data_handler.get_depth(symbol, exchange)
        
        if depth is None:
            return False, {
                'status': 'error',
                'message': 'Failed to fetch market depth'
            }, 500

        return True, {
            'status': 'success',
            'data': depth
        }, 200
    except Exception as e:
        logger.error(f"Error in broker_module.get_depth: {e}")
        traceback.print_exc()
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500

def get_depth(
    symbol: str, 
    exchange: str,
    api_key: Optional[str] = None, 
    auth_token: Optional[str] = None, 
    feed_token: Optional[str] = None, 
    broker: Optional[str] = None,
    user_id: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get market depth for a symbol.
    Supports both API-based authentication and direct internal calls.
    
    Args:
        symbol: Trading symbol
        exchange: Exchange (e.g., NSE, BSE)
        api_key: OpenAlgo API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        feed_token: Direct broker feed token (for internal calls)
        broker: Direct broker name (for internal calls)
        user_id: User ID for broker-specific functionality (for internal calls)
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        auth_info = get_auth_token_broker(api_key, include_feed_token=True)
        if len(auth_info) == 3:
            AUTH_TOKEN, FEED_TOKEN, broker_name = auth_info
        else:
            return False, {
                'status': 'error',
                'message': 'Invalid openalgo apikey'
            }, 403
            
        # Get user_id from auth database
        extracted_user_id = None
        try:
            extracted_user_id = verify_api_key(api_key)  # Get the actual user_id from API key
            if extracted_user_id:
                auth_obj = Auth.query.filter_by(name=extracted_user_id).first()  # Query using user_id instead of api_key
                if auth_obj and auth_obj.user_id:
                    extracted_user_id = auth_obj.user_id
        except Exception as e:
            logger.warning(f"Could not fetch user_id: {e}")
            
        return get_depth_with_auth(
            AUTH_TOKEN, 
            FEED_TOKEN, 
            broker_name, 
            symbol, 
            exchange,
            extracted_user_id
        )
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_depth_with_auth(
            auth_token, 
            feed_token, 
            broker, 
            symbol, 
            exchange,
            user_id
        )
    
    # Case 3: Invalid parameters
    else:
        return False, {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }, 400
