"""
Dhan-specific mapping utilities for the WebSocket adapter
"""
from typing import Dict, Set, Optional

class DhanExchangeMapper:
    """Maps between OpenAlgo exchange names and Dhan exchange codes"""
    
    # OpenAlgo to Dhan exchange mapping
    EXCHANGE_MAP = {
        'NSE': 'NSE_EQ',
        'BSE': 'BSE_EQ',
        'NFO': 'NSE_FNO',
        'BFO': 'BSE_FNO',
        'MCX': 'MCX_COMM',          # Corrected from MCX_COM to MCX_COMM
        'CDS': 'NSE_CURRENCY',
        'BCD': 'BSE_CURRENCY',      # Added BSE Currency
        'NSE_INDEX': 'IDX_I',       # Added NSE Index
        'BSE_INDEX': 'IDX_I'        # Added BSE Index
    }
    
    # Dhan exchange segment codes (numeric) to OpenAlgo exchange mapping
    # Based on official Dhan documentation
    # Note: Both NSE_INDEX and BSE_INDEX use segment 0 (IDX_I), defaulting to NSE_INDEX
    SEGMENT_TO_EXCHANGE = {
        0: 'NSE_INDEX',   # IDX_I (Index) - Both NSE_INDEX and BSE_INDEX use this
        1: 'NSE',         # NSE_EQ (NSE Equity Cash)
        2: 'NFO',         # NSE_FNO (NSE Futures & Options)
        3: 'CDS',         # NSE_CURRENCY (NSE Currency)
        4: 'BSE',         # BSE_EQ (BSE Equity Cash)
        5: 'MCX',         # MCX_COMM (MCX Commodity)
        7: 'BCD',         # BSE_CURRENCY (BSE Currency)
        8: 'BFO'          # BSE_FNO (BSE Futures & Options)
    }
    
    # Reverse mappings
    DHAN_TO_OPENALGO = {v: k for k, v in EXCHANGE_MAP.items()}
    EXCHANGE_TO_SEGMENT = {v: k for k, v in SEGMENT_TO_EXCHANGE.items()}
    
    @classmethod
    def get_dhan_exchange(cls, openalgo_exchange: str) -> Optional[str]:
        """Convert OpenAlgo exchange to Dhan exchange format"""
        return cls.EXCHANGE_MAP.get(openalgo_exchange)
    
    @classmethod
    def get_openalgo_exchange(cls, dhan_exchange: str) -> Optional[str]:
        """Convert Dhan exchange to OpenAlgo exchange format"""
        return cls.DHAN_TO_OPENALGO.get(dhan_exchange)
    
    @classmethod
    def get_exchange_from_segment(cls, segment_code: int) -> Optional[str]:
        """Convert Dhan exchange segment code to OpenAlgo exchange"""
        # Note: Both NSE_INDEX and BSE_INDEX use segment 0 (IDX_I)
        # This method returns NSE_INDEX by default for segment 0
        # Use context from symbol/token to differentiate if needed
        return cls.SEGMENT_TO_EXCHANGE.get(segment_code)
    
    @classmethod 
    def get_segment_from_exchange(cls, exchange: str) -> Optional[int]:
        """Convert OpenAlgo exchange to Dhan exchange segment code"""
        # Special handling for BSE_INDEX - also maps to segment 0 like NSE_INDEX
        if exchange == 'BSE_INDEX':
            return 0  # Same as NSE_INDEX (IDX_I)
        return cls.EXCHANGE_TO_SEGMENT.get(exchange)


class DhanCapabilityRegistry:
    """Registry for Dhan-specific capabilities and limits"""
    
    # Exchange-wise depth level support
    DEPTH_SUPPORT = {
        'NSE': {5, 20},      # NSE Equity supports both 5 and 20 level depth
        'NFO': {5, 20},      # NSE F&O supports both 5 and 20 level depth
        'BSE': {5},          # BSE only supports 5 level depth
        'BFO': {5},          # BSE F&O only supports 5 level depth
        'MCX': {5},          # MCX only supports 5 level depth
        'CDS': {5},          # NSE Currency only supports 5 level depth
        'BCD': {5},          # BSE Currency only supports 5 level depth
        'NSE_INDEX': {5},    # NSE Index only supports 5 level depth
        'BSE_INDEX': {5}     # BSE Index only supports 5 level depth
    }
    
    # Maximum subscriptions per connection
    MAX_SUBSCRIPTIONS_5_DEPTH = 5000    # Max 5000 instruments for 5-level depth
    MAX_SUBSCRIPTIONS_20_DEPTH = 50     # Max 50 instruments for 20-level depth
    
    # Maximum instruments per request
    MAX_INSTRUMENTS_PER_REQUEST = 100   # Max 100 instruments per subscribe request
    
    @classmethod
    def is_depth_level_supported(cls, exchange: str, depth_level: int) -> bool:
        """Check if a specific depth level is supported for an exchange"""
        return depth_level in cls.DEPTH_SUPPORT.get(exchange, set())
    
    @classmethod
    def get_supported_depth_levels(cls, exchange: str) -> Set[int]:
        """Get all supported depth levels for an exchange"""
        return cls.DEPTH_SUPPORT.get(exchange, {5})  # Default to 5 if not found
    
    @classmethod
    def get_fallback_depth_level(cls, exchange: str, requested_depth: int) -> int:
        """Get the closest supported depth level for an exchange"""
        supported_levels = cls.get_supported_depth_levels(exchange)
        
        if requested_depth in supported_levels:
            return requested_depth
        
        # Return the highest available depth level that's less than requested
        # If no such level exists, return the lowest available
        lower_levels = [level for level in supported_levels if level < requested_depth]
        if lower_levels:
            return max(lower_levels)
        
        return min(supported_levels) if supported_levels else 5
    
    @classmethod
    def get_max_subscriptions(cls, depth_level: int) -> int:
        """Get maximum subscriptions allowed for a depth level"""
        if depth_level == 20:
            return cls.MAX_SUBSCRIPTIONS_20_DEPTH
        return cls.MAX_SUBSCRIPTIONS_5_DEPTH