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

def format_order_data(order_data):
    """Format all numeric values in order data to 2 decimal places and adjust price for market orders"""
    if isinstance(order_data, list):
        formatted_orders = []
        for item in order_data:
            formatted_item = {}
            for key, value in item.items():
                if isinstance(value, (int, float)):
                    formatted_item[key] = format_decimal(value)
                else:
                    formatted_item[key] = value
            
            # Set price to 0 for market orders, keep actual price for limit orders
            pricetype = formatted_item.get('pricetype', '').upper()
            if pricetype == 'MARKET':
                formatted_item['price'] = 0.0
            
            formatted_orders.append(formatted_item)
        return formatted_orders
    return order_data

def format_statistics(stats):
    """Format numeric values in statistics - keep counts as integers, prices as decimals"""
    if isinstance(stats, dict):
        formatted = {}
        for key, value in stats.items():
            # Keep order counts as integers
            if any(count_type in key for count_type in ['total_', 'orders', 'completed', 'open', 'rejected']):
                formatted[key] = int(value) if isinstance(value, (int, float)) else value
            # Format other numeric values to 2 decimal places
            elif isinstance(value, (int, float)):
                formatted[key] = format_decimal(value)
            else:
                formatted[key] = value
        return formatted
    return stats

def import_broker_module(broker_name: str) -> Optional[Dict[str, Any]]:
    """
    Dynamically import the broker-specific order modules.
    
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
            'get_order_book': getattr(api_module, 'get_order_book'),
            'map_order_data': getattr(mapping_module, 'map_order_data'),
            'calculate_order_statistics': getattr(mapping_module, 'calculate_order_statistics'),
            'transform_order_data': getattr(mapping_module, 'transform_order_data')
        }
    except (ImportError, AttributeError) as error:
        logger.error(f"Error importing broker modules: {error}")
        return None

def get_orderbook_with_auth(auth_token: str, broker: str) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get order book details using provided auth token.
    
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
        # Get orderbook data using broker's implementation
        order_data = broker_funcs['get_order_book'](auth_token)
        
        if 'status' in order_data and order_data['status'] == 'error':
            return False, {
                'status': 'error',
                'message': order_data.get('message', 'Error fetching order data')
            }, 500

        # Transform data using mapping functions
        order_data = broker_funcs['map_order_data'](order_data=order_data)
        order_stats = broker_funcs['calculate_order_statistics'](order_data)
        order_data = broker_funcs['transform_order_data'](order_data)
        
        # Format numeric values to 2 decimal places
        formatted_orders = format_order_data(order_data)
        formatted_stats = format_statistics(order_stats)
        
        return True, {
            'status': 'success',
            'data': {
                'orders': formatted_orders,
                'statistics': formatted_stats
            }
        }, 200
    except Exception as e:
        logger.error(f"Error processing order data: {e}")
        traceback.print_exc()
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500

def get_orderbook(
    api_key: Optional[str] = None, 
    auth_token: Optional[str] = None, 
    broker: Optional[str] = None
) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get order book details.
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
        return get_orderbook_with_auth(AUTH_TOKEN, broker_name)
    
    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_orderbook_with_auth(auth_token, broker)
    
    # Case 3: Invalid parameters
    else:
        return False, {
            'status': 'error',
            'message': 'Either api_key or both auth_token and broker must be provided'
        }, 400
