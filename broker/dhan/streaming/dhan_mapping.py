"""
Mapping utilities for Dhan broker WebSocket integration
"""
from typing import Dict, Any, List, Optional


class DhanExchangeMapper:
    """Map exchange codes between OpenAlgo format and Dhan formats"""
    
    # Mapping from OpenAlgo exchange code to Dhan exchange code
    OA_TO_DHAN: Dict[str, str] = {
        'NSE': 'NSE_EQ',
        'BSE': 'BSE_EQ',
        'NFO': 'NSE_FNO',
        'BFO': 'BSE_FNO',
        'CDS': 'NSE_CURRENCY',
        'BCD': 'BSE_CURRENCY',
        'MCX': 'MCX_COMM',  # MCX futures sometimes need special handling
        'MCX_FO': 'MCX_COMM',  # Alternate explicit code
        'NSE_INDEX': 'IDX_I',
        'BSE_INDEX': 'IDX_I',
    }
    
    # Mapping from Dhan exchange code to OpenAlgo exchange code
    DHAN_TO_OA: Dict[str, str] = {
        'NSE_EQ': 'NSE', 
        'BSE_EQ': 'BSE',
        'NSE_FNO': 'NFO',
        'BSE_FNO': 'BFO',
        'NSE_CURRENCY': 'CDS',
        'BSE_CURRENCY': 'BCD',
        'MCX_COMM': 'MCX',
        'IDX_I': 'NSE_INDEX',
        'IDX_I': 'BSE_INDEX',
    }
    
    @classmethod
    def to_dhan_exchange(cls, oa_exchange: str) -> str:
        """Convert OpenAlgo exchange code to Dhan exchange code"""
        return cls.OA_TO_DHAN.get(oa_exchange.upper(), oa_exchange.upper())
        
    @classmethod
    def to_oa_exchange(cls, dhan_exchange: str) -> str:
        """Convert Dhan exchange code to OpenAlgo exchange code"""
        return cls.DHAN_TO_OA.get(dhan_exchange.upper(), dhan_exchange.upper())


class DhanCapabilityRegistry:
    """Registry of capabilities for Dhan"""
    
    # Map subscription modes to capabilities
    MODE_CAPABILITIES: Dict[int, Dict[str, Any]] = {
        1: {  # LTP mode
            "name": "LTP",
            "description": "Real-time last traded price",
            "fields": ["ltp", "ltq", "ltt", "volume", "exchange_code", "token"],
            "sample_rate": "real-time"
        },
        2: {  # Quote mode
            "name": "QUOTE",
            "description": "Real-time quotes",
            "fields": ["ltp", "ltq", "ltt", "open", "high", "low", "close", "volume", 
                     "exchange_code", "token", "bid", "ask", "bid_qty", "ask_qty"],
            "sample_rate": "real-time"
        },
        4: {  # Depth mode
            "name": "DEPTH",
            "description": "Real-time market depth",
            "fields": ["ltp", "ltq", "ltt", "open", "high", "low", "close", "volume", 
                     "exchange_code", "token", "bids", "asks"],
            "sample_rate": "real-time",
            "depth_levels": 5
        }
    }
    
    @classmethod
    def get_capabilities(cls) -> Dict[str, Any]:
        """Get all capabilities"""
        return {
            "modes": list(cls.MODE_CAPABILITIES.keys()),
            "mode_details": cls.MODE_CAPABILITIES,
            "max_depth_level": 5,
            "exchanges": list(DhanExchangeMapper.OA_TO_DHAN.keys()),
            "timeframes": ["1m", "5m", "15m", "30m", "1h", "1d"]
        }
        
    @classmethod
    def is_mode_supported(cls, mode: int) -> bool:
        """Check if a mode is supported"""
        return mode in cls.MODE_CAPABILITIES
        
    @classmethod
    def get_mode_fields(cls, mode: int) -> List[str]:
        """Get the fields available for a specific mode"""
        if mode not in cls.MODE_CAPABILITIES:
            return []
        return cls.MODE_CAPABILITIES[mode].get("fields", [])
