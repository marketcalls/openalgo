"""
Mapping utilities and capability registry for Shoonya broker WebSocket integration
"""
from typing import Dict, Any, List, Optional

class ShoonyaExchangeMapper:
    """Map OpenAlgo exchange codes to Shoonya format and vice versa"""
    OA_TO_SHOONYA: Dict[str, str] = {
        'NSE': 'NSE',
        'BSE': 'BSE',
        'NFO': 'NFO',
        'CDS': 'CDS',
        'MCX': 'MCX',
        'NSE_INDEX': 'NSE',  # Indices mapped to base exchange
        'BSE_INDEX': 'BSE',
    }

    SHOONYA_TO_OA: Dict[str, str] = {v: k for k, v in OA_TO_SHOONYA.items()}

    @classmethod
    def to_shoonya_exchange(cls, oa_exchange: str) -> str:
        return cls.OA_TO_SHOONYA.get(oa_exchange.upper(), oa_exchange.upper())

    @classmethod
    def to_oa_exchange(cls, shoonya_exchange: str) -> str:
        return cls.SHOONYA_TO_OA.get(shoonya_exchange.upper(), shoonya_exchange.upper())

class ShoonyaCapabilityRegistry:
    """Registry of Shoonya WebSocket capabilities"""
    MODES = {
        1: {  # LTP/Touchline
            "name": "LTP",
            "fields": ["lp", "pc", "v", "o", "h", "l", "c", "ap"],
            "description": "Last traded price and basic quote"
        },
        2: {  # Quote (same as LTP for Shoonya)
            "name": "QUOTE",
            "fields": ["lp", "pc", "v", "o", "h", "l", "c", "ap"],
            "description": "Quote (same as LTP for Shoonya)"
        },
        3: {  # Depth
            "name": "DEPTH",
            "fields": ["lp", "pc", "v", "o", "h", "l", "c", "ap", "tbq", "tsq", "bq1", "bp1", "sq1", "sp1", "bq2", "bp2", "sq2", "sp2", "bq3", "bp3", "sq3", "sp3", "bq4", "bp4", "sq4", "sp4", "bq5", "bp5", "sq5", "sp5"],
            "description": "Market depth (5 levels)"
        }
    }
    SUPPORTED_MODES = [1, 2, 3]
    SUPPORTED_DEPTH_LEVELS = [5]
    SUPPORTED_EXCHANGES = list(ShoonyaExchangeMapper.OA_TO_SHOONYA.keys())

    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        return {
            "modes": cls.SUPPORTED_MODES,
            "mode_details": cls.MODES,
            "max_depth_level": 5,
            "exchanges": cls.SUPPORTED_EXCHANGES
        }

    @classmethod
    def is_mode_supported(cls, mode: int) -> bool:
        return mode in cls.SUPPORTED_MODES

    @classmethod
    def is_depth_level_supported(cls, depth_level: int) -> bool:
        return depth_level in cls.SUPPORTED_DEPTH_LEVELS

    @classmethod
    def get_fallback_depth_level(cls, requested_depth: int) -> int:
        return 5