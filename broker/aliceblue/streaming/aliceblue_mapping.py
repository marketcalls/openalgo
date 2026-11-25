"""
AliceBlue-specific mapping and capability configurations for WebSocket streaming
"""

from typing import Dict, List, Set

from websocket_proxy.mapping import BrokerCapabilityRegistry, ExchangeMapper


class AliceBlueFeedType:
    """AliceBlue feed type constants"""

    MARKET_DATA = "t"  # Tick data (LTP, Change, OHLC, Volume)
    DEPTH = "d"  # Market depth data
    UNSUBSCRIBE = "u"  # Unsubscribe


class AliceBlueExchangeMapper(ExchangeMapper):
    """Maps standard exchange codes to AliceBlue-specific exchange codes"""

    def __init__(self):
        # Map from standard exchange codes to AliceBlue exchange codes
        self._exchange_mapping = {
            "NSE": "NSE",
            "NSE_INDEX": "NSE",  # NSE indices map to NSE
            "BSE": "BSE",
            "BSE_INDEX": "BSE",  # BSE indices map to BSE
            "NFO": "NFO",  # NSE F&O
            "BFO": "BFO",  # BSE F&O
            "CDS": "CDS",  # Currency Derivatives
            "BCD": "BCD",  # BSE Currency Derivatives
            "MCX": "MCX",  # Multi Commodity Exchange
            "MCX_INDEX": "MCX",  # MCX indices map to MCX
        }

        # Reverse mapping for AliceBlue to standard
        self._reverse_mapping = {v: k for k, v in self._exchange_mapping.items()}

    def to_broker_exchange(self, standard_exchange: str) -> str:
        """Convert standard exchange code to AliceBlue exchange code"""
        return self._exchange_mapping.get(standard_exchange, standard_exchange)

    def from_broker_exchange(self, broker_exchange: str) -> str:
        """Convert AliceBlue exchange code to standard exchange code"""
        return self._reverse_mapping.get(broker_exchange, broker_exchange)

    def get_supported_exchanges(self) -> list[str]:
        """Get list of supported exchanges in standard format"""
        return list(self._exchange_mapping.keys())


class AliceBlueCapabilityRegistry(BrokerCapabilityRegistry):
    """Registry of AliceBlue WebSocket streaming capabilities"""

    def __init__(self):
        super().__init__()

        # Define supported data types
        self._supported_data_types = {
            "tick_data",  # LTP, change, OHLC, volume
            "market_depth",  # Order book depth
            "order_updates",  # Order status updates
        }

        # Define supported exchanges
        self._supported_exchanges = {"NSE", "BSE", "NFO", "BFO", "CDS", "BCD", "MCX"}

        # Define supported instruments
        self._supported_instruments = {"equity", "futures", "options", "currency", "commodity"}

        # Define rate limits (approximate)
        self._rate_limits = {
            "subscriptions_per_second": 10,
            "max_concurrent_subscriptions": 1000,
            "reconnect_interval": 5,
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

    def get_supported_data_types(self) -> set[str]:
        """Get all supported data types"""
        return self._supported_data_types.copy()

    def get_supported_exchanges(self) -> set[str]:
        """Get all supported exchanges"""
        return self._supported_exchanges.copy()

    def get_supported_instrument_types(self) -> set[str]:
        """Get all supported instrument types"""
        return self._supported_instruments.copy()


def _to_float(value):
    return float(value)


def _to_int(value):
    # Quantities arrive as strings such as "125888500"; some feeds send "50.0".
    return int(float(value))


# Quote fields of the tick (t) and depth (d) feeds. 11-websocket.md lists
# lp, pc, cv, v, o, h, l, c, ap; the dk/df samples add oi, ltq, tbq, tsq,
# uc, lc, ft (feed time, epoch seconds) and ltt (last traded time, HH:MM:SS).
# A field is parsed only when the message carries it: tf/df are incremental.
QUOTE_FIELD_MAP = {
    "lp": ("ltp", _to_float),
    "o": ("open", _to_float),
    "h": ("high", _to_float),
    "l": ("low", _to_float),
    "c": ("close", _to_float),
    "pc": ("change_percent", _to_float),
    "cv": ("change_value", _to_float),
    "ap": ("average_price", _to_float),
    "v": ("volume", _to_int),
    "oi": ("total_oi", _to_int),
    # Not in the docs, but the earlier parser read it; kept so a feed that
    # sends toi still reports OI. A message carrying oi sets the same key.
    "toi": ("total_oi", _to_int),
    "ltq": ("last_quantity", _to_int),
    "tbq": ("total_buy_quantity", _to_int),
    "tsq": ("total_sell_quantity", _to_int),
    "uc": ("upper_circuit", _to_float),
    "lc": ("lower_circuit", _to_float),
    "ft": ("timestamp", str),
    "ltt": ("last_trade_time", str),
}

# Depth level fields: bp/bq/bo (buy price, quantity, orders), sp/sq/so (sell).
DEPTH_LEVEL_FIELDS = (
    ("bid_levels", "bp", "price", _to_float),
    ("bid_levels", "bq", "quantity", _to_int),
    ("bid_levels", "bo", "orders", _to_int),
    ("ask_levels", "sp", "price", _to_float),
    ("ask_levels", "sq", "quantity", _to_int),
    ("ask_levels", "so", "orders", _to_int),
)


def _clean_symbol(raw_symbol) -> str:
    return raw_symbol.split("-")[0] if raw_symbol else ""


def _parse_quote_fields(message: dict, parsed: dict) -> None:
    """Copy the quote fields the message carries into parsed; skip absent or bad ones."""
    for src_key, (dest_key, converter) in QUOTE_FIELD_MAP.items():
        value = message.get(src_key)
        if value is None or value == "":
            continue
        try:
            parsed[dest_key] = converter(value)
        except (ValueError, TypeError):
            continue


class AliceBlueMessageMapper:
    """Maps AliceBlue WebSocket messages to standardized format"""

    @staticmethod
    def parse_tick_data(message: dict) -> dict:
        """Parse a tick (tk/tf) message; only fields present in the message are returned."""
        try:
            parsed = {
                "type": "tick_data",
                "message_type": message.get("t", ""),
                "exchange": message.get("e", ""),
                "token": message.get("tk", ""),
            }
            if "ts" in message:
                parsed["symbol"] = _clean_symbol(message.get("ts"))
            _parse_quote_fields(message, parsed)
            return parsed
        except (ValueError, KeyError) as e:
            return {"type": "error", "message": f"Failed to parse tick data: {e}"}

    @staticmethod
    def parse_depth_data(message: dict) -> dict:
        """Parse a depth (dk/df) message.

        Returns the quote fields the message carries plus ``bid_levels`` and
        ``ask_levels``: {level_number: {price, quantity, orders}} holding only
        the level fields present, so a df diff can be merged per level and field.
        """
        try:
            parsed = {
                "type": "market_depth",
                "exchange": message.get("e"),
                "token": message.get("tk"),
                "bid_levels": {},
                "ask_levels": {},
            }
            if "ts" in message:
                parsed["symbol"] = message.get("ts")
            _parse_quote_fields(message, parsed)

            for level in range(1, 6):
                for side, prefix, field, converter in DEPTH_LEVEL_FIELDS:
                    value = message.get(f"{prefix}{level}")
                    if value is None or value == "":
                        continue
                    try:
                        parsed[side].setdefault(level, {})[field] = converter(value)
                    except (ValueError, TypeError):
                        continue
            return parsed
        except (ValueError, KeyError) as e:
            return {"type": "error", "message": f"Failed to parse depth data: {e}"}

    @staticmethod
    def create_subscription_message(exchange: str, token: str, feed_type: str = "t") -> dict:
        """Create subscription message in AliceBlue format"""
        # AliceBlue expects the subscription key in the format "EXCHANGE|TOKEN"
        # For multiple subscriptions, they should be separated by # in a single message
        return {
            "k": f"{exchange}|{token}",
            "t": feed_type,  # "t" for tick data, "d" for depth data
        }

    @staticmethod
    def create_unsubsciption_message(exchange: str, token: str) -> dict:
        """Create unsubscription message in AliceBlue format"""
        return {"k": f"{exchange}|{token}", "t": "u"}
