# websocket_proxy/__init__.py

import logging

from .base_adapter import (
    BaseBrokerWebSocketAdapter,
    ENABLE_CONNECTION_POOLING,
    MAX_SYMBOLS_PER_WEBSOCKET,
    MAX_WEBSOCKET_CONNECTIONS,
)
from .broker_factory import (
    cleanup_all_pools,
    create_broker_adapter,
    get_pool_stats,
    get_resource_health,
    register_adapter,
)
from .connection_manager import (
    ConnectionPool,
    SharedZmqPublisher,
    get_max_symbols_per_websocket,
    get_max_websocket_connections,
)
from .server import WebSocketProxy
from .server import main as websocket_main

# Set up logger
logger = logging.getLogger(__name__)

# Import the angel_adapter directly from the broker directory
from broker.angel.streaming.angel_adapter import AngelWebSocketAdapter

# Import the compositedge_adapter
from broker.compositedge.streaming.compositedge_adapter import CompositedgeWebSocketAdapter

# Import the definedge_adapter
from broker.definedge.streaming.definedge_adapter import DefinedgeWebSocketAdapter

# Import the dhan_adapter
from broker.dhan.streaming.dhan_adapter import DhanWebSocketAdapter

# Import the fivepaisa_adapter
from broker.fivepaisa.streaming.fivepaisa_adapter import FivepaisaWebSocketAdapter

# Import the fivepaisaxts_adapter
from broker.fivepaisaxts.streaming.fivepaisaxts_adapter import FivepaisaXTSWebSocketAdapter

# Import the flattrade_adapter
from broker.flattrade.streaming.flattrade_adapter import FlattradeWebSocketAdapter

# Import the fyers_adapter
from broker.fyers.streaming.fyers_websocket_adapter import FyersWebSocketAdapter

# Import the ibulls_adapter
from broker.ibulls.streaming.ibulls_adapter import IbullsWebSocketAdapter

# Import the iifl_adapter
from broker.iifl.streaming.iifl_adapter import IiflWebSocketAdapter

# Import the indmoney_adapter
from broker.indmoney.streaming.indmoney_adapter import IndmoneyWebSocketAdapter

# Import the fivepaisaxts_adapter
from broker.jainamxts.streaming.jainamxts_adapter import JainamXTSWebSocketAdapter

# Import the kotak_adapter
from broker.kotak.streaming.kotak_adapter import KotakWebSocketAdapter

# Import the motilal_adapter
from broker.motilal.streaming.motilal_adapter import MotilalWebSocketAdapter

# Import the mstock_adapter
from broker.mstock.streaming.mstock_adapter import MstockWebSocketAdapter

# Import the paytm_adapter
from broker.paytm.streaming.paytm_adapter import PaytmWebSocketAdapter

# Import the pocketful_adapter
from broker.pocketful.streaming.pocketful_adapter import PocketfulWebSocketAdapter

# Import the samco_adapter
from broker.samco.streaming.samco_adapter import SamcoWebSocketAdapter

# Import the shoonya_adapter
from broker.shoonya.streaming.shoonya_adapter import ShoonyaWebSocketAdapter

# Import the upstox_adapter
from broker.upstox.streaming.upstox_adapter import UpstoxWebSocketAdapter

# Import the wisdom_adapter
from broker.wisdom.streaming.wisdom_adapter import WisdomWebSocketAdapter

# Import the zerodha_adapter
from broker.zerodha.streaming.zerodha_adapter import ZerodhaWebSocketAdapter

# AliceBlue adapter will be loaded dynamically

# Register adapters
register_adapter("angel", AngelWebSocketAdapter)
register_adapter("zerodha", ZerodhaWebSocketAdapter)
register_adapter("dhan", DhanWebSocketAdapter)
register_adapter("flattrade", FlattradeWebSocketAdapter)
register_adapter("shoonya", ShoonyaWebSocketAdapter)
register_adapter("ibulls", IbullsWebSocketAdapter)
register_adapter("compositedge", CompositedgeWebSocketAdapter)
register_adapter("fivepaisa", FivepaisaWebSocketAdapter)
register_adapter("fivepaisaxts", FivepaisaXTSWebSocketAdapter)
register_adapter("iifl", IiflWebSocketAdapter)
register_adapter("wisdom", WisdomWebSocketAdapter)
register_adapter("upstox", UpstoxWebSocketAdapter)
register_adapter("kotak", KotakWebSocketAdapter)
register_adapter("fyers", FyersWebSocketAdapter)
register_adapter("definedge", DefinedgeWebSocketAdapter)
register_adapter("paytm", PaytmWebSocketAdapter)
register_adapter("indmoney", IndmoneyWebSocketAdapter)
register_adapter("mstock", MstockWebSocketAdapter)
register_adapter("motilal", MotilalWebSocketAdapter)
register_adapter("jainamxts", JainamXTSWebSocketAdapter)
register_adapter("samco", SamcoWebSocketAdapter)
register_adapter("pocketful", PocketfulWebSocketAdapter)

# AliceBlue adapter will be registered dynamically when first used

__all__ = [
    # Core classes
    "WebSocketProxy",
    "websocket_main",
    "register_adapter",
    "create_broker_adapter",
    # Base adapter (for cleanup utilities)
    "BaseBrokerWebSocketAdapter",
    # Connection pooling (multi-websocket support)
    "ConnectionPool",
    "SharedZmqPublisher",
    "get_pool_stats",
    "get_resource_health",
    "cleanup_all_pools",
    "get_max_symbols_per_websocket",
    "get_max_websocket_connections",
    # Configuration constants
    "MAX_SYMBOLS_PER_WEBSOCKET",
    "MAX_WEBSOCKET_CONNECTIONS",
    "ENABLE_CONNECTION_POOLING",
    # Broker adapters
    "AngelWebSocketAdapter",
    "ZerodhaWebSocketAdapter",
    "DhanWebSocketAdapter",
    "FlattradeWebSocketAdapter",
    "ShoonyaWebSocketAdapter",
    "IbullsWebSocketAdapter",
    "CompositedgeWebSocketAdapter",
    "FivepaisaWebSocketAdapter",
    "FivepaisaXTSWebSocketAdapter",
    "IiflWebSocketAdapter",
    "JainamWebSocketAdapter",
    "TrustlineWebSocketAdapter",
    "WisdomWebSocketAdapter",
    "UpstoxWebSocketAdapter",
    "KotakWebSocketAdapter",
    "FyersWebSocketAdapter",
    "DefinedgeWebSocketAdapter",
    "PaytmWebSocketAdapter",
    "IndmoneyWebSocketAdapter",
    "MstockWebSocketAdapter",
    "MotilalWebSocketAdapter",
    "JainamXTSWebSocketAdapter",
    "SamcoWebSocketAdapter",
    "PocketfulWebSocketAdapter",
]
