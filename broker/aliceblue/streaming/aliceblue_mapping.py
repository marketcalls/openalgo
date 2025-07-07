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
            # Get message type to handle different formats
            msg_type = message.get("t", "")
            
            # Common fields that should always be present
            parsed = {
                "type": "tick_data",
                "message_type": msg_type,
                "exchange": message.get("e", ""),
                "token": message.get("tk", ""),
            }
            
            # For 'tk' (token acknowledgment) messages, we get full data
            if msg_type == "tk":
                # Extract symbol and clean it (remove suffixes like -EQ for OpenAlgo format)
                raw_symbol = message.get("ts", "")
                # Log the raw symbol for debugging
                import logging
                logger = logging.getLogger("aliceblue_mapping")
                logger.info(f"Raw symbol from AliceBlue: '{raw_symbol}'")
                clean_symbol = raw_symbol.split("-")[0] if raw_symbol else ""
                logger.info(f"Cleaned symbol: '{clean_symbol}'")
                parsed.update({
                    "symbol": clean_symbol,
                    "ltp": float(message.get("lp", 0)) if message.get("lp") else 0.0,
                    "volume": int(message.get("v", 0)) if message.get("v") else 0,
                    "open": float(message.get("o", 0)) if message.get("o") else 0.0,
                    "high": float(message.get("h", 0)) if message.get("h") else 0.0,
                    "low": float(message.get("l", 0)) if message.get("l") else 0.0,
                    "close": float(message.get("c", 0)) if message.get("c") else 0.0,
                    "change_percent": float(message.get("pc", 0)) if message.get("pc") else 0.0,
                    "change_value": float(message.get("cv", 0)) if message.get("cv") else 0.0,
                    "average_price": float(message.get("ap", 0)) if message.get("ap") else 0.0,
                    "timestamp": message.get("ft", ""),
                    "total_oi": int(message.get("toi", 0)) if message.get("toi") else 0,
                    "tick_size": float(message.get("ti", 0)) if message.get("ti") else 0.0,
                    "lot_size": int(message.get("ls", 0)) if message.get("ls") else 0,
                    "market_lot": int(message.get("ml", 0)) if message.get("ml") else 0,
                    "price_precision": int(message.get("pp", 0)) if message.get("pp") else 0,
                })
            
            # For 'tf' (tick feed) messages, only include fields that are present
            elif msg_type == "tf":
                # Only add fields that exist in the message
                if "lp" in message:
                    parsed["ltp"] = float(message["lp"])
                if "pc" in message:
                    parsed["change_percent"] = float(message["pc"])
                if "ft" in message:
                    parsed["timestamp"] = message["ft"]
                if "v" in message:
                    parsed["volume"] = int(message["v"])
                if "toi" in message:
                    parsed["total_oi"] = int(message["toi"])
                # Add any other fields that might be present
                for key in ["o", "h", "l", "c", "cv", "ap"]:
                    if key in message:
                        mapped_key = {
                            "o": "open", "h": "high", "l": "low", "c": "close",
                            "cv": "change_value", "ap": "average_price"
                        }.get(key, key)
                        parsed[mapped_key] = float(message[key])
                        
            # For other message types, parse whatever is available
            else:
                # Parse all available fields
                field_mappings = {
                    "lp": ("ltp", float),
                    "v": ("volume", int),
                    "o": ("open", float),
                    "h": ("high", float),
                    "l": ("low", float),
                    "c": ("close", float),
                    "pc": ("change_percent", float),
                    "cv": ("change_value", float),
                    "ap": ("average_price", float),
                    "ft": ("timestamp", str),
                    "toi": ("total_oi", int),
                    "ts": ("symbol", str)
                }
                
                for src_key, (dest_key, converter) in field_mappings.items():
                    if src_key in message:
                        try:
                            if dest_key == "symbol" and src_key == "ts":
                                # Clean symbol for OpenAlgo format (remove -EQ suffix)
                                raw_symbol = message[src_key]
                                clean_symbol = raw_symbol.split("-")[0] if raw_symbol else ""
                                parsed[dest_key] = clean_symbol
                            else:
                                parsed[dest_key] = converter(message[src_key])
                        except (ValueError, TypeError):
                            pass  # Skip fields that can't be converted
            
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
                bid_price = message.get(f"bp{i+1}", "0")
                bid_qty = message.get(f"bq{i+1}", "0")
                ask_price = message.get(f"sp{i+1}", "0")
                ask_qty = message.get(f"sq{i+1}", "0")
                
                try:
                    bid_price_float = float(bid_price)
                    bid_qty_int = int(bid_qty)
                    if bid_price_float > 0:
                        bids.append({"price": bid_price_float, "quantity": bid_qty_int})
                except (ValueError, TypeError):
                    pass
                    
                try:
                    ask_price_float = float(ask_price)
                    ask_qty_int = int(ask_qty)
                    if ask_price_float > 0:
                        asks.append({"price": ask_price_float, "quantity": ask_qty_int})
                except (ValueError, TypeError):
                    pass
            
            parsed = {
                "type": "market_depth",
                "exchange": message.get("e"),
                "token": message.get("tk"),
                "symbol": message.get("ts"),
                "bids": bids,
                "asks": asks,
                "timestamp": message.get("ft", ""),
                "ltp": float(message.get("lp", 0)) if message.get("lp") else 0.0
            }
            return parsed
        except (ValueError, KeyError) as e:
            return {"type": "error", "message": f"Failed to parse depth data: {e}"}
    
    @staticmethod
    def create_subscription_message(exchange: str, token: str, feed_type: str = "t") -> Dict:
        """Create subscription message in AliceBlue format"""
        # AliceBlue expects the subscription key in the format "EXCHANGE|TOKEN"
        # For multiple subscriptions, they should be separated by # in a single message
        return {
            "k": f"{exchange}|{token}",
            "t": feed_type  # "t" for tick data, "d" for depth data
        }
    
    @staticmethod
    def create_unsubsciption_message(exchange: str, token: str) -> Dict:
        """Create unsubscription message in AliceBlue format"""
        return {
            "k": f"{exchange}|{token}",
            "t": "u"
        }
