"""
AliceBlue-specific mapping and capability configurations for WebSocket streaming
"""

from typing import Dict, List, Set
from websocket_proxy.mapping import ExchangeMapper, BrokerCapabilityRegistry


class AliceBlueFeedType:
    """AliceBlue feed type constants"""
    MARKET_DATA = "t"  # Tick data (LTP, Change, OHLC, Volume)
    DEPTH = "d"        # Market depth data
    UNSUBSCRIBE = "u"  # Unsubscribe


class AliceBlueExchangeMapper(ExchangeMapper):
    """Maps standard exchange codes to AliceBlue-specific exchange codes"""
    
    def __init__(self):
        # Map from standard exchange codes to AliceBlue exchange codes
        self._exchange_mapping = {
            "NSE": "NSE",
            "NSE_INDEX": "NSE",  # NSE indices map to NSE
            "BSE": "BSE", 
            "NFO": "NFO",  # NSE F&O
            "BFO": "BFO",  # BSE F&O
            "CDS": "CDS",  # Currency Derivatives
            "BCD": "BCD",  # BSE Currency Derivatives
            "MCX": "MCX"   # Multi Commodity Exchange
        }
        
        # Reverse mapping for AliceBlue to standard
        self._reverse_mapping = {v: k for k, v in self._exchange_mapping.items()}
    
    def to_broker_exchange(self, standard_exchange: str) -> str:
        """Convert standard exchange code to AliceBlue exchange code"""
        return self._exchange_mapping.get(standard_exchange, standard_exchange)
    
    def from_broker_exchange(self, broker_exchange: str) -> str:
        """Convert AliceBlue exchange code to standard exchange code"""
        return self._reverse_mapping.get(broker_exchange, broker_exchange)
    
    def get_supported_exchanges(self) -> List[str]:
        """Get list of supported exchanges in standard format"""
        return list(self._exchange_mapping.keys())


class AliceBlueCapabilityRegistry(BrokerCapabilityRegistry):
    """Registry of AliceBlue WebSocket streaming capabilities"""
    
    def __init__(self):
        super().__init__()
        
        # Define supported data types
        self._supported_data_types = {
            "tick_data",      # LTP, change, OHLC, volume
            "market_depth",   # Order book depth
            "order_updates"   # Order status updates
        }
        
        # Define supported exchanges
        self._supported_exchanges = {
            "NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"
        }
        
        # Define supported instruments
        self._supported_instruments = {
            "equity", "futures", "options", "currency", "commodity"
        }
        
        # Define rate limits (approximate)
        self._rate_limits = {
            "subscriptions_per_second": 10,
            "max_concurrent_subscriptions": 1000,
            "reconnect_interval": 5
        }
    
    def supports_data_type(self, data_type: str) -> bool:
        """Check if a data type is supported"""
        return data_type in self._supported_data_types
    
    def supports_exchange(self, exchange: str) -> bool:
        """Check if an exchange is supported"""
        return exchange in self._supported_exchanges
    
    def supports_instrument_type(self, instrument_type: str) -> bool:
        """Check if an instrument type is supported"""
        return instrument_type in self._supported_instruments
    
    def get_rate_limit(self, limit_type: str) -> int:
        """Get rate limit for a specific operation"""
        return self._rate_limits.get(limit_type, 0)
    
    def get_supported_data_types(self) -> Set[str]:
        """Get all supported data types"""
        return self._supported_data_types.copy()
    
    def get_supported_exchanges(self) -> Set[str]:
        """Get all supported exchanges"""
        return self._supported_exchanges.copy()
    
    def get_supported_instrument_types(self) -> Set[str]:
        """Get all supported instrument types"""
        return self._supported_instruments.copy()


class AliceBlueMessageMapper:
    """Maps AliceBlue WebSocket messages to standardized format"""
    
    @staticmethod
    def parse_tick_data(message: Dict) -> Dict:
        """Parse tick data message from AliceBlue format to standard format"""
        try:
            parsed = {
                "type": "tick_data",
                "exchange": message.get("e"),
                "token": message.get("tk"),
                "symbol": message.get("ts"),
                "ltp": float(message.get("lp", 0)),
                "volume": int(message.get("v", 0)),
                "open": float(message.get("o", 0)),
                "high": float(message.get("h", 0)),
                "low": float(message.get("l", 0)),
                "close": float(message.get("c", 0)),
                "change": float(message.get("ch", 0)),
                "change_percent": float(message.get("chp", 0)),
                "timestamp": message.get("ft", "")
            }
            return parsed
        except (ValueError, KeyError) as e:
            return {"type": "error", "message": f"Failed to parse tick data: {e}"}
    
    @staticmethod
    def parse_depth_data(message: Dict) -> Dict:
        """Parse market depth message from AliceBlue format to standard format"""
        try:
            # Parse bid/ask data
            bids = []
            asks = []
            
            # AliceBlue depth data structure parsing
            for i in range(5):  # Assuming 5 levels of depth
                bid_price = message.get(f"bp{i+1}", 0)
                bid_qty = message.get(f"bq{i+1}", 0)
                ask_price = message.get(f"sp{i+1}", 0)
                ask_qty = message.get(f"sq{i+1}", 0)
                
                if bid_price > 0:
                    bids.append({"price": float(bid_price), "quantity": int(bid_qty)})
                if ask_price > 0:
                    asks.append({"price": float(ask_price), "quantity": int(ask_qty)})
            
            parsed = {
                "type": "market_depth",
                "exchange": message.get("e"),
                "token": message.get("tk"),
                "symbol": message.get("ts"),
                "bids": bids,
                "asks": asks,
                "timestamp": message.get("ft", "")
            }
            return parsed
        except (ValueError, KeyError) as e:
            return {"type": "error", "message": f"Failed to parse depth data: {e}"}
    
    @staticmethod
    def create_subscription_message(exchange: str, token: str, feed_type: str = "t") -> Dict:
        """Create subscription message in AliceBlue format"""
        return {
            "k": f"{exchange}|{token}",
            "t": feed_type
        }
    
    @staticmethod
    def create_unsubsciption_message(exchange: str, token: str) -> Dict:
        """Create unsubscription message in AliceBlue format"""
        return {
            "k": f"{exchange}|{token}",
            "t": "u"
        }
