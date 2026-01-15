"""
Zebu-specific mapping utilities for the WebSocket adapter
"""
from typing import Dict, Set, Optional

class ZebuExchangeMapper:
    """Maps between OpenAlgo exchange names and Zebu exchange codes"""

    # OpenAlgo to Zebu exchange mapping (same as Flattrade/Noren)
    EXCHANGE_MAP = {
        'NSE': 'NSE',
        'BSE': 'BSE',
        'NFO': 'NFO',
        'BFO': 'BFO',
        'MCX': 'MCX',
        'CDS': 'CDS',
        'NSE_INDEX': 'NSE',  # Indices use base exchange
        'BSE_INDEX': 'BSE'
    }

    # Reverse mapping
    ZEBU_TO_OPENALGO = {v: k for k, v in EXCHANGE_MAP.items()}

    @classmethod
    def to_zebu_exchange(cls, oa_exchange: str) -> Optional[str]:
        """Convert OpenAlgo exchange to Zebu exchange format"""
        return cls.EXCHANGE_MAP.get(oa_exchange.upper())

    @classmethod
    def to_oa_exchange(cls, zebu_exchange: str) -> Optional[str]:
        """Convert Zebu exchange to OpenAlgo exchange format"""
        return cls.ZEBU_TO_OPENALGO.get(zebu_exchange.upper())


class ZebuCapabilityRegistry:
    """Registry for Zebu-specific capabilities and limits"""

    # Supported subscription modes
    SUPPORTED_MODES = {1, 2, 3}  # LTP, Quote, Depth

    # Depth level support (Zebu only supports 5-level depth)
    SUPPORTED_DEPTH_LEVELS = {5}

    # Maximum subscriptions per connection
    MAX_SUBSCRIPTIONS = 5000  # Conservative limit

    # Maximum instruments per request
    MAX_INSTRUMENTS_PER_REQUEST = 50

    @classmethod
    def is_mode_supported(cls, mode: int) -> bool:
        """Check if a subscription mode is supported"""
        return mode in cls.SUPPORTED_MODES

    @classmethod
    def is_depth_level_supported(cls, depth_level: int) -> bool:
        """Check if a depth level is supported"""
        return depth_level in cls.SUPPORTED_DEPTH_LEVELS

    @classmethod
    def get_fallback_depth_level(cls, requested_depth: int) -> int:
        """Get the fallback depth level (always 5 for Zebu)"""
        return 5

    @classmethod
    def get_capabilities(cls) -> Dict[str, any]:
        """Get all capabilities"""
        return {
            'supported_modes': list(cls.SUPPORTED_MODES),
            'supported_depth_levels': list(cls.SUPPORTED_DEPTH_LEVELS),
            'max_subscriptions': cls.MAX_SUBSCRIPTIONS,
            'max_instruments_per_request': cls.MAX_INSTRUMENTS_PER_REQUEST
        }