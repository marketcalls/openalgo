import importlib
import traceback
from typing import Tuple, Dict, Any, Optional, List, Union
from database.auth_db import get_auth_token_broker
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

def format_decimal(value):
    """Format numeric value to 2 decimal places"""
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return value

def format_holdings_data(holdings_data):
    """Format all numeric values in holdings data to 2 decimal places"""
    if isinstance(holdings_data, list):
        return [
            {
                key: format_decimal(value) if key in ['pnl', 'pnlpercent'] else value
                for key, value in item.items()
            }
            for item in holdings_data
        ]
    return holdings_data

def format_statistics(stats):
    """Format all numeric values in statistics to 2 decimal places"""
    if isinstance(stats, dict):
        return {
            key: format_decimal(value)
            for key, value in stats.items()
        }
    return stats

def import_broker_module(broker_name: str) -> Optional[Dict[str, Any]]:
    """
    Dynamically import the broker-specific holdings modules.
    
    Args:
        broker_name: Name of the broker
        
    Returns:
        Dictionary of broker functions or None if import fails
    """
    try:
        # Import API module
        api_module = importlib.import_module(f'broker.{broker_name}.api.order_api')
        # Import mapping module
        mapping_module = importlib.import_module(f'broker.{broker_name}.mapping.order_data')
        return {
            'get_holdings': getattr(api_module, 'get_holdings'),
            'map_portfolio_data': getattr(mapping_module, 'map_portfolio_data'),
            'calculate_portfolio_statistics': getattr(mapping_module, 'calculate_portfolio_statistics'),
            'transform_holdings_data': getattr(mapping_module, 'transform_holdings_data')
        }
    except (ImportError, AttributeError) as error:
        logger.error(f"Error importing broker modules: {error}")
        return None

def get_holdings_with_auth(auth_token: str, broker: str) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get holdings details using provided auth token.
    
    Args:
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        
    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    broker_funcs = import_broker_module(broker)
    if broker_funcs is None:
        return False, {
            'status': 'error',
            'message': 'Broker-specific module not found'
        }, 404

    try:
        # Get holdings using broker functions
        holdings = broker_funcs['get_holdings'](auth_token)
        
        if 'status' in holdings and holdings['status'] == 'error':
            return False, {
                'status': 'error',
                'message': holdings.get('message', 'Error fetching holdings data')
            }, 500

        # Transform data using mapping functions
        holdings = broker_funcs['map_portfolio_data'](holdings)
        portfolio_stats = broker_funcs['calculate_portfolio_statistics'](holdings)
        holdings = broker_funcs['transform_holdings_data'](holdings)
        
        # Format numeric values to 2 decimal places
        formatted_holdings = format_holdings_data(holdings)
        formatted_stats = format_statistics(portfolio_stats)
        
        return True, {
            'status': 'success',
            'data': {
                'holdings': formatted_holdings,
                'statistics': formatted_stats
            }
        }, 200
    except Exception as e:
        logger.error(f"Error processing holdings data: {e}")
        traceback.print_exc()
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500

def get_holdings(
    api_key: Optional[str] = None, 
    auth_token: Optional[str] = None, 
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get holdings details.
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
        return get_holdings_with_auth(AUTH_TOKEN, broker_name)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_holdings_with_auth(auth_token, broker)
    
    # Case 3: Invalid parameters
    else:
        return False, {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }, 400
