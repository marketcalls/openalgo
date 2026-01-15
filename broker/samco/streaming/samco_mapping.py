import logging


class SamcoExchangeMapper:
    """Maps OpenAlgo exchange codes to Samco-specific exchange types"""

    # Exchange type mapping for Samco broker
    EXCHANGE_TYPES = {
        'NSE': 'NSE',      # NSE Cash Market
        'NFO': 'NFO',      # NSE Futures & Options
        'BSE': 'BSE',      # BSE Cash Market
        'BFO': 'BFO',      # BSE F&O
        'MCX': 'MCX',      # MCX
        'CDS': 'CDS',      # Currency derivatives
        'NSE_INDEX': 'NSE',  # NSE Index
        'BSE_INDEX': 'BSE'   # BSE Index
    }

    @staticmethod
    def get_exchange_type(exchange):
        """
        Convert exchange code to Samco-specific exchange type

        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE', 'NFO')

        Returns:
            str: Samco-specific exchange type
        """
        return SamcoExchangeMapper.EXCHANGE_TYPES.get(exchange, 'NSE')  # Default to NSE


class SamcoCapabilityRegistry:
    """
    Registry of Samco broker's capabilities including supported exchanges,
    subscription modes, and market depth levels
    """

    # Samco broker capabilities
    exchanges = ['NSE', 'BSE', 'NFO', 'BFO', 'MCX', 'CDS']
    subscription_modes = [1, 2, 3]  # 1: LTP, 2: Quote, 3: Snap Quote (Depth)

    # Depth support per exchange
    depth_support = {
        'NSE': [5],   # NSE supports 5 levels
        'BSE': [5],   # BSE supports 5 levels
        'NFO': [5],   # NFO supports 5 levels
        'BFO': [5],   # BFO supports 5 levels
        'MCX': [5],   # MCX supports 5 levels
        'CDS': [5]    # CDS supports 5 levels
    }

    @classmethod
    def get_supported_depth_levels(cls, exchange):
        """
        Get supported depth levels for an exchange

        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')

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
            int: Highest supported depth level that is <= requested depth
        """
        supported_depths = cls.get_supported_depth_levels(exchange)
        # Find the highest supported depth that's less than or equal to requested depth
        fallbacks = [d for d in supported_depths if d <= requested_depth]
        if fallbacks:
            return max(fallbacks)
        return 5  # Default to basic depth
