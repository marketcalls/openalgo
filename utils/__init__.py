# WebSocket SSL utilities - only export what's currently used
from .websocket_ssl import get_ssl_context_for_websockets

__all__ = [
    'get_ssl_context_for_websockets'
]
