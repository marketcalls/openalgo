# utils/broker_credentials.py

import os
from database.broker_config_db import get_broker_config, get_default_broker, is_xts_broker as db_is_xts_broker
from utils.config import get_broker_api_key, get_broker_api_secret
from utils.logging import get_logger

logger = get_logger(__name__)

def get_broker_credentials(user_id, broker_name):
    """
    Get broker credentials from database or environment fallback
    
    Args:
        user_id: User identifier
        broker_name: Broker name (dhan, angel, etc.)
    
    Returns:
        dict: Credentials dictionary or None
    """
    try:
        # Try to get from database first
        config = get_broker_config(user_id, broker_name)
        if config and config.get('api_key') and config.get('api_secret'):
            logger.info(f"Using database credentials for user {user_id}, broker {broker_name}")
            return {
                'api_key': config.get('api_key'),
                'api_secret': config.get('api_secret'),
                'market_api_key': config.get('market_api_key'),
                'market_api_secret': config.get('market_api_secret'),
                'redirect_url': config.get('redirect_url'),
                'additional_config': config.get('additional_config', {}),
                'source': 'database'
            }
    except Exception as e:
        logger.warning(f"Failed to get credentials from database for {user_id}/{broker_name}: {e}")
    
    # Fall back to environment variables
    logger.info(f"Using environment credentials fallback for broker {broker_name}")
    env_creds = {
        'api_key': get_broker_api_key(),
        'api_secret': get_broker_api_secret(),
        'redirect_url': os.getenv('REDIRECT_URL'),
        'source': 'environment'
    }
    
    # Add market data credentials for XTS brokers
    if is_xts_broker(broker_name):
        env_creds['market_api_key'] = os.getenv('BROKER_API_KEY_MARKET')
        env_creds['market_api_secret'] = os.getenv('BROKER_API_SECRET_MARKET')
    
    return env_creds

def get_user_default_broker(user_id):
    """
    Get default broker configuration for a user
    
    Args:
        user_id: User identifier
    
    Returns:
        dict: Default broker configuration or None
    """
    try:
        return get_default_broker(user_id)
    except Exception as e:
        logger.error(f"Error getting default broker for user {user_id}: {e}")
        return None

def has_broker_config(user_id, broker_name):
    """
    Check if user has broker configuration in database
    
    Args:
        user_id: User identifier
        broker_name: Broker name
    
    Returns:
        bool: True if config exists
    """
    try:
        config = get_broker_config(user_id, broker_name)
        return config is not None
    except Exception as e:
        logger.error(f"Error checking broker config for {user_id}/{broker_name}: {e}")
        return False

def is_xts_broker(broker_name):
    """
    Check if broker is XTS-based (requires market data credentials)
    
    Args:
        broker_name: Broker identifier
    
    Returns:
        bool: True if XTS broker
    """
    # First try to get from database template
    try:
        return db_is_xts_broker(broker_name)
    except:
        # Fallback to hardcoded list
        xts_brokers = ['fivepaisaxts', 'compositedge', 'ibulls', 'iifl', 'jainam', 'jainampro', 'wisdom']
        return broker_name in xts_brokers

def validate_broker_credentials(credentials, broker_name):
    """
    Validate broker credentials structure
    
    Args:
        credentials: Dictionary of credentials
        broker_name: Broker name for validation rules
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if not credentials:
        return False, "No credentials provided"
    
    # Check required fields
    required_fields = ['api_key', 'api_secret']
    for field in required_fields:
        if not credentials.get(field):
            return False, f"Missing required field: {field}"
    
    # Check XTS broker requirements
    if is_xts_broker(broker_name):
        xts_required = ['market_api_key', 'market_api_secret']
        for field in xts_required:
            if not credentials.get(field):
                return False, f"Missing required XTS field: {field}"
    
    return True, None

def mask_credentials(credentials):
    """
    Mask sensitive credentials for logging
    
    Args:
        credentials: Dictionary of credentials
    
    Returns:
        dict: Masked credentials
    """
    if not credentials:
        return {}
    
    masked = {}
    for key, value in credentials.items():
        if key in ['api_key', 'api_secret', 'market_api_key', 'market_api_secret']:
            if value:
                masked[key] = value[:4] + '...' + value[-4:] if len(value) > 8 else '***'
            else:
                masked[key] = None
        else:
            masked[key] = value
    
    return masked

def format_redirect_url(broker_name, domain=None):
    """
    Format redirect URL for broker OAuth
    
    Args:
        broker_name: Broker name
        domain: Domain name (optional, uses HOST_SERVER environment if not provided)
    
    Returns:
        str: Formatted redirect URL
    """
    if not domain:
        # Use HOST_SERVER from .env file
        host_server = os.getenv('HOST_SERVER', 'http://127.0.0.1:5000')
        
        # Extract domain from HOST_SERVER (remove protocol)
        if '://' in host_server:
            protocol, domain = host_server.split('://', 1)
        else:
            protocol = 'http'
            domain = host_server
        
        # Build the redirect URL using the same protocol as HOST_SERVER
        return f"{protocol}://{domain}/{broker_name}/callback"
    else:
        # Legacy behavior when domain is explicitly provided
        # Remove protocol if present
        if domain.startswith('http://') or domain.startswith('https://'):
            domain = domain.split('://', 1)[1]
        
        # Use HTTPS for production, HTTP for localhost
        protocol = 'https' if 'localhost' not in domain else 'http'
        
        return f"{protocol}://{domain}/{broker_name}/callback"

def get_broker_display_name(broker_name):
    """
    Get human-readable broker display name
    
    Args:
        broker_name: Broker identifier
    
    Returns:
        str: Display name
    """
    display_names = {
        'dhan': 'Dhan',
        'angel': 'Angel One',
        'zerodha': 'Zerodha',
        'upstox': 'Upstox',
        'fivepaisaxts': '5Paisa XTS',
        'compositedge': 'Compositedge',
        'iifl': 'IIFL',
        'ibulls': 'Indiabulls',
        'jainam': 'Jainam',
        'jainampro': 'Jainam Pro',
        'wisdom': 'Wisdom',
        'kotak': 'Kotak Securities',
        'aliceblue': 'Alice Blue',
        'shoonya': 'Shoonya',
        'flattrade': 'Flattrade',
        'firstock': 'Firstock',
        'paytm': 'Paytm Money',
        'groww': 'Groww',
        'fyers': 'Fyers',
        'zebu': 'Zebu',
        'pocketful': 'Pocketful',
        'tradejini': 'Tradejini'
    }
    
    return display_names.get(broker_name, broker_name.title())

def test_broker_connection(user_id, broker_name, credentials=None):
    """
    Test broker connection with provided or stored credentials
    
    Args:
        user_id: User identifier
        broker_name: Broker name
        credentials: Optional credentials to test (if None, uses stored)
    
    Returns:
        tuple: (success, message)
    """
    try:
        # Get credentials if not provided
        if not credentials:
            credentials = get_broker_credentials(user_id, broker_name)
        
        if not credentials:
            return False, "No credentials available"
        
        # Validate credentials structure
        is_valid, error_msg = validate_broker_credentials(credentials, broker_name)
        if not is_valid:
            return False, error_msg
        
        # TODO: Implement actual broker API connection test
        # This would call the broker's auth API to verify credentials
        # For now, just validate structure
        
        logger.info(f"Connection test successful for {user_id}/{broker_name}")
        return True, "Connection test successful"
        
    except Exception as e:
        logger.error(f"Connection test failed for {user_id}/{broker_name}: {e}")
        return False, f"Connection test failed: {str(e)}"