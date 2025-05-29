from .server import WebSocketProxy, main as websocket_main
from .broker_factory import register_adapter, create_broker_adapter

# Import the angel_adapter directly from the broker directory
from broker.angel.streaming.angel_adapter import AngelWebSocketAdapter

# Register Angel adapter
register_adapter("angel", AngelWebSocketAdapter)

__all__ = [
    'WebSocketProxy',
    'websocket_main',
    'register_adapter',
    'create_broker_adapter',
    'AngelWebSocketAdapter'
]
