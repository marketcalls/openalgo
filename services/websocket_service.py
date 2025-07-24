"""
WebSocket service layer for internal use.
Provides a clean interface for Flask app components to interact with WebSocket functionality
without dealing with authentication or connection management.
"""

import os
from typing import Dict, List, Any, Optional, Tuple
from database.auth_db import verify_api_key, get_auth_token, get_broker_name
from utils.logging import get_logger
from .websocket_client import get_websocket_client, WebSocketClient

# Initialize logger
logger = get_logger(__name__)

# Get WebSocket configuration from environment
WS_HOST = os.getenv('WEBSOCKET_HOST', '127.0.0.1')  # Use 127.0.0.1 instead of localhost
WS_PORT = int(os.getenv('WEBSOCKET_PORT', '8765'))

def get_user_api_key(username: str) -> Optional[str]:
    """
    Get the API key for a user from the database
    
    Args:
        username: Username (the api_keys table uses username as user_id)
        
    Returns:
        API key string or None if not found
    """
    try:
        from database.auth_db import get_api_key_for_tradingview
        # The API key table stores username as user_id (it's a String column)
        api_key = get_api_key_for_tradingview(username)
        if not api_key:
            logger.warning(f"No API key found for user {username}. User needs to generate an API key first.")
        return api_key
    except Exception as e:
        logger.error(f"Error getting API key for user {username}: {e}")
        return None

def get_websocket_connection(username: str) -> Tuple[bool, Optional[WebSocketClient], Optional[str]]:
    """
    Get or create a WebSocket connection for a user
    
    Args:
        username: Username
        
    Returns:
        Tuple of (success, client, error_message)
    """
    try:
        # Get user's API key using username (api_keys table stores username as user_id)
        api_key = get_user_api_key(username)
        if not api_key:
            return False, None, "No API key found. Please generate an API key from the API Key page (/apikey) to use WebSocket features."
        
        # Get or create WebSocket client
        client = get_websocket_client(api_key, WS_HOST, WS_PORT)
        
        if not client.connected or not client.authenticated:
            return False, None, "WebSocket client not connected or authenticated"
            
        return True, client, None
        
    except ConnectionError as e:
        logger.error(f"Connection error for user {username}: {e}")
        return False, None, str(e)
    except Exception as e:
        logger.exception(f"Error getting WebSocket connection for user {username}: {e}")
        return False, None, f"Unexpected error: {str(e)}"

def get_websocket_status(username: str, broker: Optional[str] = None) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get WebSocket connection status for a user
    
    Args:
        username: Username
        broker: Broker name (optional, will be fetched if not provided)
        
    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        success, client, error = get_websocket_connection(username)
        
        if not success:
            return False, {
                'status': 'error',
                'message': error,
                'connected': False,
                'authenticated': False
            }, 200  # Return 200 even for disconnected state
        
        # Get broker info if not provided
        if not broker:
            api_key = get_user_api_key(username)
            if api_key:
                broker = get_broker_name(api_key)
        
        # Get subscription info
        subscriptions = client.get_subscriptions()
        
        return True, {
            'status': 'success',
            'connected': client.connected,
            'authenticated': client.authenticated,
            'broker': broker,
            'websocket_url': client.ws_url,
            'active_subscriptions': subscriptions.get('count', 0),
            'subscriptions': subscriptions.get('subscriptions', [])
        }, 200
        
    except Exception as e:
        logger.exception(f"Error getting WebSocket status: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500


def get_websocket_subscriptions(username: str, broker: Optional[str] = None) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get current WebSocket subscriptions for a user
    
    Args:
        username: Username
        broker: Broker name (optional)
        
    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        success, client, error = get_websocket_connection(username)
        
        if not success:
            return False, {
                'status': 'error',
                'message': error,
                'subscriptions': []
            }, 200
        
        # Get subscriptions
        result = client.get_subscriptions()
        
        return True, {
            'status': result.get('status', 'success'),
            'subscriptions': result.get('subscriptions', []),
            'count': result.get('count', 0),
            'broker': broker
        }, 200
        
    except Exception as e:
        logger.exception(f"Error getting subscriptions: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500

def subscribe_to_symbols(username: str, broker: str, symbols: List[Dict[str, str]], mode: str = "Quote") -> Tuple[bool, Dict[str, Any], int]:
    """
    Subscribe to market data for symbols
    
    Args:
        username: Username
        broker: Broker name
        symbols: List of symbol dictionaries with 'symbol' and 'exchange' keys
        mode: Subscription mode ("LTP", "Quote", or "Depth")
        
    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Validate symbols
        if not symbols:
            return False, {
                'status': 'error',
                'message': 'No symbols provided'
            }, 400
        
        # Validate mode
        valid_modes = ["LTP", "Quote", "Depth"]
        if mode not in valid_modes:
            return False, {
                'status': 'error',
                'message': f'Invalid mode. Must be one of: {", ".join(valid_modes)}'
            }, 400
        
        # Get WebSocket connection
        success, client, error = get_websocket_connection(username)
        
        if not success:
            return False, {
                'status': 'error',
                'message': error
            }, 503  # Service Unavailable
        
        # Subscribe to symbols
        result = client.subscribe(symbols, mode)
        
        if result.get('status') == 'success':
            return True, {
                'status': 'success',
                'message': result.get('message'),
                'subscriptions': {
                    'symbols': result.get('symbols', symbols),
                    'mode': mode,
                    'count': len(symbols)
                },
                'broker': broker
            }, 200
        else:
            return False, {
                'status': 'error',
                'message': result.get('message', 'Subscription failed')
            }, 400
            
    except Exception as e:
        logger.exception(f"Error subscribing to symbols: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500

def unsubscribe_from_symbols(username: str, broker: str, symbols: List[Dict[str, str]], mode: str = "Quote") -> Tuple[bool, Dict[str, Any], int]:
    """
    Unsubscribe from market data for symbols
    
    Args:
        username: Username
        broker: Broker name
        symbols: List of symbol dictionaries with 'symbol' and 'exchange' keys
        mode: Subscription mode ("LTP", "Quote", or "Depth")
        
    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Validate symbols
        if not symbols:
            return False, {
                'status': 'error',
                'message': 'No symbols provided'
            }, 400
        
        # Get WebSocket connection
        success, client, error = get_websocket_connection(username)
        
        if not success:
            return False, {
                'status': 'error',
                'message': error
            }, 503  # Service Unavailable
        
        # Unsubscribe from symbols
        result = client.unsubscribe(symbols, mode)
        
        if result.get('status') == 'success':
            return True, {
                'status': 'success',
                'message': result.get('message'),
                'unsubscriptions': {
                    'symbols': result.get('symbols', symbols),
                    'mode': mode,
                    'count': len(symbols)
                },
                'broker': broker
            }, 200
        else:
            return False, {
                'status': 'error',
                'message': result.get('message', 'Unsubscription failed')
            }, 400
            
    except Exception as e:
        logger.exception(f"Error unsubscribing from symbols: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500

def unsubscribe_all(username: str, broker: str) -> Tuple[bool, Dict[str, Any], int]:
    """
    Unsubscribe from all market data
    
    Args:
        username: Username
        broker: Broker name
        
    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Get WebSocket connection
        success, client, error = get_websocket_connection(username)
        
        if not success:
            return False, {
                'status': 'error',
                'message': error
            }, 503  # Service Unavailable
        
        # Unsubscribe from all
        result = client.unsubscribe_all()
        
        if result.get('status') == 'success':
            return True, {
                'status': 'success',
                'message': 'Unsubscribed from all symbols',
                'broker': broker
            }, 200
        else:
            return False, {
                'status': 'error',
                'message': result.get('message', 'Unsubscription failed')
            }, 400
            
    except Exception as e:
        logger.exception(f"Error unsubscribing from all: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500

def get_supported_brokers_list() -> Tuple[bool, Dict[str, Any], int]:
    """
    Get list of brokers that support WebSocket streaming
    
    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Get supported brokers from environment
        valid_brokers = os.getenv('VALID_BROKERS', '').split(',')
        supported_brokers = [broker.strip() for broker in valid_brokers if broker.strip()]
        
        # Define brokers with WebSocket support
        websocket_enabled_brokers = [
            'zerodha', 'angel', 'fivepaisaxts', 'aliceblue', 'dhan', 
            'flattrade', 'shoonya', 'upstox', 'compositedge', 'iifl', 
            'ibulls', 'wisdom'
        ]
        
        # Filter only WebSocket enabled brokers
        ws_brokers = [broker for broker in supported_brokers if broker in websocket_enabled_brokers]
        
        return True, {
            'status': 'success',
            'brokers': ws_brokers,
            'count': len(ws_brokers),
            'message': 'List of brokers supporting WebSocket streaming'
        }, 200
        
    except Exception as e:
        logger.exception(f"Error getting supported brokers: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500

def get_market_data(username: str, symbol: Optional[str] = None, exchange: Optional[str] = None) -> Tuple[bool, Dict[str, Any], int]:
    """
    Get cached market data from WebSocket client
    
    Args:
        username: Username
        symbol: Symbol to get data for (optional)
        exchange: Exchange to get data for (optional)
        
    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Get WebSocket connection
        success, client, error = get_websocket_connection(username)
        
        if not success:
            return False, {
                'status': 'error',
                'message': error,
                'data': {}
            }, 200
        
        # Get market data
        market_data = client.get_market_data(symbol, exchange)
        
        return True, {
            'status': 'success',
            'data': market_data,
            'timestamp': int(time.time())
        }, 200
        
    except Exception as e:
        logger.exception(f"Error getting market data: {e}")
        return False, {
            'status': 'error',
            'message': str(e)
        }, 500

# Helper function to register callbacks for market data updates
def register_market_data_callback(username: str, callback) -> bool:
    """
    Register a callback function for market data updates
    
    Args:
        username: Username
        callback: Function to call when market data is received
        
    Returns:
        bool: Success status
    """
    try:
        success, client, error = get_websocket_connection(username)
        
        if success:
            client.register_callback('market_data', callback)
            return True
        else:
            logger.error(f"Failed to register callback: {error}")
            return False
            
    except Exception as e:
        logger.exception(f"Error registering callback: {e}")
        return False

# Import time for timestamp
import time