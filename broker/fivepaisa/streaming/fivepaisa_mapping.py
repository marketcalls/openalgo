import logging

class FivePaisaExchangeMapper:
    """Maps OpenAlgo exchange codes to 5Paisa-specific exchange codes"""

    # Exchange mapping for 5Paisa broker
    # N = NSE, B = BSE, M = MCX
    EXCHANGE_MAP = {
        'NSE': 'N',
        'BSE': 'B',
        'MCX': 'M',
        'NFO': 'N',  # NFO uses NSE exchange code
        'BFO': 'B',  # BFO uses BSE exchange code
        'CDS': 'N',  # Currency uses NSE
        'NSE_INDEX': 'N',  # NSE indices use NSE exchange code
        'BSE_INDEX': 'B',  # BSE indices use BSE exchange code
    }

    # Exchange Type mapping for 5Paisa
    # C = Cash, D = Derivatives, U = Currency
    EXCHANGE_TYPE_MAP = {
        'NSE': 'C',     # NSE Cash
        'BSE': 'C',     # BSE Cash
        'NFO': 'D',     # NSE F&O
        'BFO': 'D',     # BSE F&O
        'MCX': 'D',     # MCX Commodities
        'CDS': 'U',     # Currency Derivatives
        'NSE_INDEX': 'C',  # NSE indices use Cash type
        'BSE_INDEX': 'C',  # BSE indices use Cash type
    }

    @staticmethod
    def get_exchange_code(exchange: str) -> str:
        """
        Convert OpenAlgo exchange code to 5Paisa exchange code

        Args:
            exchange (str): OpenAlgo exchange code (e.g., 'NSE', 'BSE', 'NFO')

        Returns:
            str: 5Paisa exchange code ('N', 'B', 'M')
        """
        return FivePaisaExchangeMapper.EXCHANGE_MAP.get(exchange.upper(), 'N')

    @staticmethod
    def get_exchange_type(exchange: str) -> str:
        """
        Convert OpenAlgo exchange to 5Paisa exchange type

        Args:
            exchange (str): OpenAlgo exchange code (e.g., 'NSE', 'BSE', 'NFO')

        Returns:
            str: 5Paisa exchange type ('C', 'D', 'U')
        """
        return FivePaisaExchangeMapper.EXCHANGE_TYPE_MAP.get(exchange.upper(), 'C')


class FivePaisaCapabilityRegistry:
    """
    Registry of 5Paisa broker's capabilities including supported exchanges,
    subscription modes, and market depth levels
    """

    # 5Paisa broker capabilities
    exchanges = ['NSE', 'BSE', 'NFO', 'BFO', 'MCX', 'CDS']

    # Subscription modes:
    # 1: LTP (MarketFeedV3 with basic data)
    # 2: Quote (MarketFeedV3 with full quote)
    # 3: Depth (MarketDepthService)
    subscription_modes = [1, 2, 3]

    # Market depth support
    # 5Paisa supports only 5 levels of market depth for all exchanges
    depth_support = {
        'NSE': [5],
        'BSE': [5],
        'NFO': [5],
        'BFO': [5],
        'MCX': [5],
        'CDS': [5]
    }

    # Method mapping for different data types
    METHOD_MAP = {
        'market_feed': 'MarketFeedV3',
        'market_depth': 'MarketDepthService',
        'oi': 'GetScripInfoForFuture'
    }

    @classmethod
    def get_supported_depth_levels(cls, exchange: str) -> list:
        """
        Get supported depth levels for an exchange

        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')

        Returns:
            list: List of supported depth levels (always [5] for 5Paisa)
        """
        return cls.depth_support.get(exchange.upper(), [5])

    @classmethod
    def is_depth_level_supported(cls, exchange: str, depth_level: int) -> bool:
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
    def get_fallback_depth_level(cls, exchange: str, requested_depth: int) -> int:
        """
        Get the best available depth level as a fallback
        For 5Paisa, always returns 5 as it only supports 5 levels

        Args:
            exchange (str): Exchange code
            requested_depth (int): Requested depth level

        Returns:
            int: Fallback depth level (always 5 for 5Paisa)
        """
        return 5

    @classmethod
    def get_method_for_mode(cls, mode: int) -> str:
        """
        Get the appropriate subscription method for a given mode

        Args:
            mode (int): Subscription mode (1: LTP, 2: Quote, 3: Depth)

        Returns:
            str: Method name (MarketFeedV3, MarketDepthService)
        """
        if mode in [1, 2]:
            return cls.METHOD_MAP['market_feed']
        elif mode == 3:
            return cls.METHOD_MAP['market_depth']
        else:
            return cls.METHOD_MAP['market_feed']

    @classmethod
    def supports_oi(cls, exchange: str) -> bool:
        """
        Check if Open Interest data is supported for the exchange

        Args:
            exchange (str): Exchange code

        Returns:
            bool: True if OI is supported (for derivatives exchanges)
        """
        return exchange.upper() in ['NFO', 'BFO', 'MCX']
