import logging


class PocketfulExchangeMapper:
    """Maps OpenAlgo exchange codes to Pocketful-specific exchange types"""

    # Exchange type mapping for Pocketful broker
    # Based on Pocketful WebSocket API (matching data.py)
    EXCHANGE_TYPES = {
        "NSE": 1,  # NSE Cash Market
        "NFO": 2,  # NSE Futures & Options
        "CDS": 3,  # Currency Derivatives
        "MCX": 4,  # MCX
        "BSE": 6,  # BSE Cash Market
        "BFO": 7,  # BSE F&O
        "NSE_INDEX": 1,  # NSE Index
        "BSE_INDEX": 6,  # BSE Index
    }

    @staticmethod
    def get_exchange_code(exchange):
        """
        Convert exchange code to Pocketful-specific exchange type

        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')

        Returns:
            int: Pocketful-specific exchange type
        """
        return PocketfulExchangeMapper.EXCHANGE_TYPES.get(
            exchange, 1
        )  # Default to NSE if not found


class PocketfulCapabilityRegistry:
    """
    Registry of Pocketful broker's capabilities including supported exchanges,
    subscription modes, and market depth levels
    """

    # Pocketful broker capabilities
    exchanges = ["NSE", "BSE", "NFO", "BFO", "MCX", "CDS"]

    # Subscription modes:
    # 1 - Detailed market data (full OHLC, OI, depth)
    # 2 - Compact market data (LTP, change, OI)
    # 4 - Snapquote data (depth with 5 levels)
    subscription_modes = [1, 2, 4]

    depth_support = {
        "NSE": [5],  # NSE supports 5 levels
        "BSE": [5],  # BSE supports 5 levels
        "BFO": [5],  # BFO supports 5 levels
        "NFO": [5],  # NFO supports 5 levels
        "MCX": [5],  # MCX supports 5 levels
        "CDS": [5],  # CDS supports 5 levels
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
