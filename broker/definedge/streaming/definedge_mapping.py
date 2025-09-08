import logging

class DefinedgeExchangeMapper:
    """Maps OpenAlgo exchange codes to DefinEdge-specific exchange types"""
    
    # Exchange mapping for DefinEdge broker (as per API docs)
    EXCHANGE_MAP = {
        'NSE': 'NSE',
        'BSE': 'BSE', 
        'NFO': 'NFO',
        'BFO': 'BFO',
        'CDS': 'CDS',
        'MCX': 'MCX',
        'NSE_INDEX': 'NSE',
        'BSE_INDEX': 'BSE'
    }
    
    @staticmethod
    def get_exchange_code(exchange):
        """
        Convert OpenAlgo exchange code to DefinEdge exchange code
        
        Args:
            exchange (str): OpenAlgo exchange code
            
        Returns:
            str: DefinEdge exchange code
        """
        return DefinedgeExchangeMapper.EXCHANGE_MAP.get(exchange, exchange)


class DefinedgeCapabilityRegistry:
    """
    Registry of DefinEdge broker's capabilities including supported exchanges, 
    subscription modes, and market depth levels
    """
    
    # DefinEdge broker capabilities
    exchanges = ['NSE', 'BSE', 'NFO', 'BFO', 'MCX', 'CDS']
    subscription_modes = ['t', 'd']  # 't': touchline (LTP+Quote), 'd': depth
    
    # Depth support - DefinEdge supports 5 level depth for all exchanges
    depth_support = {
        'NSE': [5],
        'BSE': [5],
        'NFO': [5],
        'BFO': [5],
        'MCX': [5],
        'CDS': [5]
    }
    
    @classmethod
    def get_supported_depth_levels(cls, exchange):
        """
        Get supported depth levels for an exchange
        
        Args:
            exchange (str): Exchange code
            
        Returns:
            list: List of supported depth levels
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
        return 5  # Default to 5-level depth