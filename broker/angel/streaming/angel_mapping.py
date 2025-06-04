import logging

class AngelExchangeMapper:
    """Maps OpenAlgo exchange codes to Angel-specific exchange types"""
    
    # Exchange type mapping for Angel broker
    EXCHANGE_TYPES = {
        'NSE': 1,  # NSE Cash Market
        'NFO': 2,  # NSE Futures & Options
        'BSE': 3,  # BSE Cash Market
        'BFO': 4,  # BSE F&O
        'MCX': 5,  # MCX
        'NCX': 7,  # NCDEX
        'CDS': 13,  # Currency derivatives
        'NSE_INDEX': 1,  # NSE Index
        'BSE_INDEX': 3  # BSE Index
    }
    
    @staticmethod
    def get_exchange_type(exchange):
        """
        Convert exchange code to Angel-specific exchange type
        
        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')
            
        Returns:
            int: Angel-specific exchange type
        """
        return AngelExchangeMapper.EXCHANGE_TYPES.get(exchange, 1)  # Default to NSE if not found


class AngelCapabilityRegistry:
    """
    Registry of Angel broker's capabilities including supported exchanges, 
    subscription modes, and market depth levels
    """
    
    # Angel broker capabilities
    exchanges = ['NSE', 'BSE', 'BFO','NFO', 'MCX', 'CDS']
    subscription_modes = [1, 2, 3]  # 1: LTP, 2: Quote, 3: Snap Quote (Depth)
    depth_support = {
        'NSE': [5],   # NSE supports only 5 levels
        'BSE': [5],           # BSE supports only 5 levels
        'BFO': [5],           # BFO supports only 5 levels
        'NFO': [5],       # NFO supports only 5 levels
        'MCX': [5],           # MCX supports only 5 levels
        'CDS': [5]            # CDS supports only 5 levels
    }
    
    @classmethod
    def get_supported_depth_levels(cls, exchange):
        """
        Get supported depth levels for an exchange
        
        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')
            
        Returns:
            list: List of supported depth levels (e.g., [5, 20, 30])
        """
        return cls.depth_support.get(exchange, [5])
    
    @classmethod
    def is_depth_level_supported(cls, exchange, depth_level):
        """
        Check if a depth level is supported for the given exchange
        
        Args:
            exchange (str): Exchange code
            depth_level (int): Requested depth level
            
        Returns:
            bool: True if supported, False otherwise
        """
        supported_depths = cls.get_supported_depth_levels(exchange)
        return depth_level in supported_depths
    
    @classmethod
    def get_fallback_depth_level(cls, exchange, requested_depth):
        """
        Get the best available depth level as a fallback
        
        Args:
            exchange (str): Exchange code
            requested_depth (int): Requested depth level
            
        Returns:
            int: Highest supported depth level that is ≤ requested depth
        """
        supported_depths = cls.get_supported_depth_levels(exchange)
        # Find the highest supported depth that's less than or equal to requested depth
        fallbacks = [d for d in supported_depths if d <= requested_depth]
        if fallbacks:
            return max(fallbacks)
        return 5  # Default to basic depth
