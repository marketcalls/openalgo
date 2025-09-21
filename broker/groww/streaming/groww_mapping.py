"""
Groww exchange mapping and capability registry for WebSocket streaming
"""

class GrowwExchangeMapper:
    """Maps OpenAlgo exchange codes to Groww exchange/segment format"""
    
    # Mapping from OpenAlgo exchange to Groww exchange and segment
    EXCHANGE_MAP = {
        'NSE': {'exchange': 'NSE', 'segment': 'CASH'},
        'BSE': {'exchange': 'BSE', 'segment': 'CASH'},
        'NFO': {'exchange': 'NSE', 'segment': 'FNO'},
        'BFO': {'exchange': 'BSE', 'segment': 'FNO'},
        'MCX': {'exchange': 'MCX', 'segment': 'COMM'},
        'CDS': {'exchange': 'NSE', 'segment': 'CDS'},
        'BCD': {'exchange': 'BSE', 'segment': 'CDS'},
        'NSE_INDEX': {'exchange': 'NSE', 'segment': 'CASH'},
        'BSE_INDEX': {'exchange': 'BSE', 'segment': 'CASH'}
    }
    
    @classmethod
    def get_exchange(cls, openalgo_exchange: str) -> str:
        """
        Get Groww exchange from OpenAlgo exchange code
        
        Args:
            openalgo_exchange: OpenAlgo exchange code (e.g., 'NSE', 'NFO')
            
        Returns:
            str: Groww exchange code
        """
        mapping = cls.EXCHANGE_MAP.get(openalgo_exchange, {})
        return mapping.get('exchange', openalgo_exchange)
    
    @classmethod
    def get_segment(cls, openalgo_exchange: str) -> str:
        """
        Get Groww segment from OpenAlgo exchange code
        
        Args:
            openalgo_exchange: OpenAlgo exchange code (e.g., 'NSE', 'NFO')
            
        Returns:
            str: Groww segment (CASH, FNO, COMM, CDS)
        """
        mapping = cls.EXCHANGE_MAP.get(openalgo_exchange, {})
        return mapping.get('segment', 'CASH')
    
    @classmethod
    def get_exchange_segment(cls, openalgo_exchange: str) -> tuple:
        """
        Get both exchange and segment from OpenAlgo exchange code
        
        Args:
            openalgo_exchange: OpenAlgo exchange code
            
        Returns:
            tuple: (exchange, segment)
        """
        mapping = cls.EXCHANGE_MAP.get(openalgo_exchange, {})
        return mapping.get('exchange', openalgo_exchange), mapping.get('segment', 'CASH')


class GrowwCapabilityRegistry:
    """
    Registry for Groww-specific capabilities and limitations
    """
    
    # Groww only supports depth level 5 for all exchanges
    SUPPORTED_DEPTH_LEVELS = {
        'NSE': [5],
        'BSE': [5],
        'NFO': [5],
        'BFO': [5],
        'MCX': [5],
        'CDS': [5],
        'BCD': [5],
        'NSE_INDEX': [5],
        'BSE_INDEX': [5]
    }
    
    # Subscription modes supported by Groww
    SUPPORTED_MODES = {
        1: 'LTP',      # Last Traded Price
        2: 'QUOTE',    # Quote (includes OHLC, volume)
        3: 'DEPTH'     # Market Depth (5 levels)
    }
    
    @classmethod
    def is_depth_level_supported(cls, exchange: str, depth_level: int) -> bool:
        """
        Check if a depth level is supported for an exchange
        
        Args:
            exchange: Exchange code
            depth_level: Requested depth level
            
        Returns:
            bool: True if supported, False otherwise
        """
        supported_levels = cls.SUPPORTED_DEPTH_LEVELS.get(exchange, [5])
        return depth_level in supported_levels
    
    @classmethod
    def get_fallback_depth_level(cls, exchange: str, requested_level: int) -> int:
        """
        Get fallback depth level if requested level is not supported
        
        Args:
            exchange: Exchange code
            requested_level: Requested depth level
            
        Returns:
            int: Fallback depth level (always 5 for Groww)
        """
        # Groww only supports depth level 5
        return 5
    
    @classmethod
    def is_mode_supported(cls, mode: int) -> bool:
        """
        Check if a subscription mode is supported
        
        Args:
            mode: Subscription mode
            
        Returns:
            bool: True if supported, False otherwise
        """
        return mode in cls.SUPPORTED_MODES
    
    @classmethod
    def get_mode_name(cls, mode: int) -> str:
        """
        Get the name of a subscription mode
        
        Args:
            mode: Subscription mode
            
        Returns:
            str: Mode name or 'UNKNOWN'
        """
        return cls.SUPPORTED_MODES.get(mode, 'UNKNOWN')
    
    @classmethod
    def get_supported_exchanges(cls) -> list:
        """
        Get list of supported exchanges
        
        Returns:
            list: List of supported exchange codes
        """
        return list(cls.SUPPORTED_DEPTH_LEVELS.keys())
    
    @classmethod
    def get_exchange_capabilities(cls, exchange: str) -> dict:
        """
        Get complete capabilities for an exchange
        
        Args:
            exchange: Exchange code
            
        Returns:
            dict: Dictionary with exchange capabilities
        """
        return {
            'exchange': exchange,
            'supported_modes': list(cls.SUPPORTED_MODES.keys()),
            'supported_depth_levels': cls.SUPPORTED_DEPTH_LEVELS.get(exchange, [5]),
            'default_depth_level': 5,
            'max_subscriptions': 1000  # Groww supports up to 1000 subscriptions
        }