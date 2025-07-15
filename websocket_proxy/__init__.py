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

# Import the flattrade_adapter
from broker.flattrade.streaming.flattrade_adapter import FlattradeWebSocketAdapter

# Import the shoonya_adapter
from broker.shoonya.streaming.shoonya_adapter import ShoonyaWebSocketAdapter

# Import the ibulls_adapter
from broker.ibulls.streaming.ibulls_adapter import IbullsWebSocketAdapter

# Import the compositedge_adapter
from broker.compositedge.streaming.compositedge_adapter import CompositedgeWebSocketAdapter

# Import the fivepaisaxts_adapter
from broker.fivepaisaxts.streaming.fivepaisaxts_adapter import FivepaisaXTSWebSocketAdapter

# Import the iifl_adapter
from broker.iifl.streaming.iifl_adapter import IiflWebSocketAdapter

# Import the jainam_adapter
from broker.jainam.streaming.jainam_adapter import JainamWebSocketAdapter

# Import the trustline_adapter
from broker.trustline.streaming.trustline_adapter import TrustlineWebSocketAdapter

# Import the wisdom_adapter
from broker.wisdom.streaming.wisdom_adapter import WisdomWebSocketAdapter

# Import the upstox_adapter
from broker.upstox.streaming.upstox_adapter import UpstoxWebSocketAdapter

# AliceBlue adapter will be loaded dynamically

# Register adapters
register_adapter("angel", AngelWebSocketAdapter)
register_adapter("zerodha", ZerodhaWebSocketAdapter)
register_adapter("dhan", DhanWebSocketAdapter)
register_adapter("flattrade", FlattradeWebSocketAdapter)
register_adapter("shoonya", ShoonyaWebSocketAdapter)
register_adapter("ibulls", IbullsWebSocketAdapter)
register_adapter("compositedge", CompositedgeWebSocketAdapter)
register_adapter("fivepaisaxts", FivepaisaXTSWebSocketAdapter)
register_adapter("iifl", IiflWebSocketAdapter)
register_adapter("jainam", JainamWebSocketAdapter)
register_adapter("trustline", TrustlineWebSocketAdapter)
register_adapter("wisdom", WisdomWebSocketAdapter)
register_adapter("wisdom", UpstoxWebSocketAdapter)

# AliceBlue adapter will be registered dynamically when first used

__all__ = [
    'WebSocketProxy',
    'websocket_main',
    'register_adapter',
    'create_broker_adapter',
    'AngelWebSocketAdapter',
    'ZerodhaWebSocketAdapter',
    'DhanWebSocketAdapter',
    'FlattradeWebSocketAdapter',
    'ShoonyaWebSocketAdapter',
    'IbullsWebSocketAdapter',
    'CompositedgeWebSocketAdapter',
    'FivepaisaXTSWebSocketAdapter',
    'IiflWebSocketAdapter',
    'JainamWebSocketAdapter',
    'TrustlineWebSocketAdapter',
    'WisdomWebSocketAdapter',
    'UpstoxWebSocketAdapter'
]