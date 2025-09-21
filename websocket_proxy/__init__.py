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

# Import the wisdom_adapter
from broker.wisdom.streaming.wisdom_adapter import WisdomWebSocketAdapter

# Import the upstox_adapter
from broker.upstox.streaming.upstox_adapter import UpstoxWebSocketAdapter

# Import the kotak_adapter
from broker.kotak.streaming.kotak_adapter import KotakWebSocketAdapter

# Import the fyers_adapter
from broker.fyers.streaming.fyers_websocket_adapter import FyersWebSocketAdapter

# Import the definedge_adapter
from broker.definedge.streaming.definedge_adapter import DefinedgeWebSocketAdapter

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
register_adapter("wisdom", WisdomWebSocketAdapter)
register_adapter("upstox", UpstoxWebSocketAdapter)
register_adapter("kotak", KotakWebSocketAdapter)
register_adapter("fyers", FyersWebSocketAdapter)
register_adapter("definedge", DefinedgeWebSocketAdapter)

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
    'UpstoxWebSocketAdapter',
    'KotakWebSocketAdapter',
    'FyersWebSocketAdapter',
    'DefinedgeWebSocketAdapter'
]
