# websocket_proxy/__init__.py

import logging

from .server import WebSocketProxy, main as websocket_main
from .broker_factory import register_adapter, create_broker_adapter

# Set up logger
logger = logging.getLogger(__name__)

# Import the angel_adapter directly from the broker directory
from broker.angel.streaming.angel_adapter import AngelWebSocketAdapter

# Import the zerodha_adapter
from broker.zerodha.streaming.zerodha_adapter import ZerodhaWebSocketAdapter

# Import the dhan_adapter
from broker.dhan.streaming.dhan_adapter import DhanWebSocketAdapter

# Register adapters
register_adapter("angel", AngelWebSocketAdapter)
register_adapter("zerodha", ZerodhaWebSocketAdapter)

register_adapter("dhan", DhanWebSocketAdapter)

__all__ = [
    'WebSocketProxy',
    'websocket_main',
    'register_adapter',
    'create_broker_adapter',
    'AngelWebSocketAdapter',
    'ZerodhaWebSocketAdapter',
    'DhanWebSocketAdapter'
]