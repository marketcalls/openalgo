"""
WebSocket SSL Configuration Utility

Provides centralized SSL/TLS configuration for WebSocket connections across all brokers.
Currently supports the websockets library (used by Zerodha, Upstox).

This utility ensures consistent SSL handling and allows configuration via environment variables.
"""

import os
import ssl
from typing import Optional

try:
    import certifi
    CERTIFI_AVAILABLE = True
except ImportError:
    CERTIFI_AVAILABLE = False


def get_ssl_verify_setting() -> bool:
    """
    Get SSL verification setting from environment variable.
    
    Returns:
        bool: True if SSL verification should be enabled, False otherwise
              Defaults to False for compatibility with environments that don't have
              proper CA certificates
    """
    verify_setting = os.getenv('WS_SSL_VERIFY', 'false').lower()
    return verify_setting in ('true', '1', 'yes', 'on')


def get_ssl_context_for_websockets(verify: Optional[bool] = None) -> ssl.SSLContext:
    """
    Get SSL context for websockets library (used by Zerodha, Upstox, etc.).
    
    Args:
        verify: Optional boolean to override environment variable setting.
                If None, uses WS_SSL_VERIFY environment variable.
                True enables certificate verification, False disables it.
    
    Returns:
        ssl.SSLContext: Configured SSL context for websockets library
    
    Example:
        >>> import websockets
        >>> ssl_context = get_ssl_context_for_websockets()
        >>> await websockets.connect(url, ssl=ssl_context)
    """
    if verify is None:
        verify = get_ssl_verify_setting()
    
    if verify:
        # Full SSL verification with system certificates
        context = ssl.create_default_context()
        if CERTIFI_AVAILABLE:
            # Use certifi for additional certificate bundles if available
            context.load_verify_locations(certifi.where())
        return context
    else:
        # Disable certificate verification (for environments without proper CA certs)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context