from utils.logging import get_logger

logger = get_logger(__name__)


class MstockExchangeMapper:
    """Maps OpenAlgo exchange codes to mstock-specific exchange types"""

    # Exchange type mapping for mstock broker WebSocket
    # The mStock Market Data WebSocket docs list only 1=NSECM, 2=NSEFO,
    # 3=BSECM, 4=BSEFO and 13=NSECD. MCX is not documented; 5 is an unverified
    # guess and is tracked in UNVERIFIED_EXCHANGES below.
    EXCHANGE_TYPES = {
        "NSE": 1,  # NSE Cash Market
        "NFO": 2,  # NSE Futures & Options
        "BSE": 3,  # BSE Cash Market
        "BFO": 4,  # BSE F&O
        "CDS": 13,  # Currency derivatives
        "MCX": 5,  # MCX - NOT documented by mStock, unverified
        "NSE_INDEX": 1,  # NSE Index
        "BSE_INDEX": 3,  # BSE Index
    }

    # Exchanges whose wire exchangeType is not confirmed by the mStock docs
    UNVERIFIED_EXCHANGES = {"MCX"}

    @staticmethod
    def get_exchange_type(exchange):
        """
        Convert exchange code to mstock-specific exchange type

        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')

        Returns:
            int: mstock-specific exchange type, defaulting to NSE Cash Market
        """
        exchange_type = MstockExchangeMapper.EXCHANGE_TYPES.get(exchange)

        if exchange_type is None:
            # Falling back to NSE would silently return the wrong instrument's
            # data, so make it visible rather than failing quietly.
            logger.warning(
                f"Exchange '{exchange}' is not mapped for mStock streaming; "
                f"falling back to NSE Cash Market (1)"
            )
            return 1

        if exchange in MstockExchangeMapper.UNVERIFIED_EXCHANGES:
            logger.warning(
                f"Exchange '{exchange}' uses exchangeType {exchange_type}, which is "
                f"not documented by mStock; streaming data may be incorrect"
            )

        return exchange_type


class MstockCapabilityRegistry:
    """
    Registry of mstock broker's capabilities including supported exchanges,
    subscription modes, and market depth levels
    """

    # mstock broker capabilities
    exchanges = ["NSE", "BSE", "BFO", "NFO", "MCX", "CDS"]

    # Available subscription modes for mstock
    # 1: LTP only
    # 2: Quote (OHLC + LTP + Volume)
    # 3: Snap Quote (Full data with market depth)
    subscription_modes = [1, 2, 3]

    # Market depth support - mstock provides 5 levels for all exchanges
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
            list: List of supported depth levels (always [5] for mstock)
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
        Get fallback depth level if requested depth is not supported

        Args:
            exchange (str): Exchange code
            requested_depth (int): Requested depth level

        Returns:
            int: Fallback depth level (always 5 for mstock)
        """
        supported_depths = cls.get_supported_depth_levels(exchange)
        if not supported_depths:
            return 5

        # For mstock, always return 5 as it only supports 5 levels
        return 5

    @classmethod
    def is_exchange_supported(cls, exchange):
        """
        Check if an exchange is supported

        Args:
            exchange (str): Exchange code

        Returns:
            bool: True if supported, False otherwise
        """
        return exchange in cls.exchanges

    @classmethod
    def is_mode_supported(cls, mode):
        """
        Check if a subscription mode is supported

        Args:
            mode (int): Subscription mode (1, 2, or 3)

        Returns:
            bool: True if supported, False otherwise
        """
        return mode in cls.subscription_modes
