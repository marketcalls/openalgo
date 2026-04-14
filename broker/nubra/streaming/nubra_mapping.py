"""
Nubra exchange mapping and capability registry for WebSocket streaming.
"""


class NubraExchangeMapper:
    """Maps OpenAlgo exchange codes to Nubra-specific exchanges."""

    # OpenAlgo exchange -> Nubra WebSocket exchange
    EXCHANGE_MAP = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NSE",
        "BFO": "BSE",
        "NSE_INDEX": "NSE",
        "BSE_INDEX": "BSE",
    }

    @staticmethod
    def to_nubra_exchange(exchange: str) -> str:
        """Convert OpenAlgo exchange to Nubra exchange."""
        return NubraExchangeMapper.EXCHANGE_MAP.get(exchange, "NSE")

    @staticmethod
    def is_index_exchange(exchange: str) -> bool:
        """Check if the exchange is an index exchange."""
        return exchange in ("NSE_INDEX", "BSE_INDEX")


class NubraCapabilityRegistry:
    """Registry of Nubra broker's streaming capabilities."""

    exchanges = ["NSE", "BSE", "NFO", "BFO"]
    subscription_modes = [1, 2, 3]  # 1: LTP, 2: Quote, 3: Depth
    depth_support = {
        "NSE": [5],
        "BSE": [5],
        "NFO": [5],
        "BFO": [5],
    }

    @classmethod
    def get_supported_depth_levels(cls, exchange: str) -> list:
        return cls.depth_support.get(exchange, [5])

    @classmethod
    def is_depth_level_supported(cls, exchange: str, depth_level: int) -> bool:
        return depth_level in cls.get_supported_depth_levels(exchange)

    @classmethod
    def get_fallback_depth_level(cls, exchange: str, requested_depth: int) -> int:
        supported = cls.get_supported_depth_levels(exchange)
        fallbacks = [d for d in supported if d <= requested_depth]
        return max(fallbacks) if fallbacks else 5
