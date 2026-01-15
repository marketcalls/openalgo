import logging

class PaytmExchangeMapper:
    """Maps OpenAlgo exchange codes to Paytm-specific exchange types"""

    # Exchange type mapping for Paytm broker
    # Based on Paytm API documentation
    EXCHANGE_TYPES = {
        'NSE': 'NSE',    # NSE Cash Market
        'NFO': 'NFO',    # NSE Futures & Options
        'BSE': 'BSE',    # BSE Cash Market
        'BFO': 'BFO',    # BSE F&O (not explicitly mentioned but following pattern)
        'MCX': 'MCX',    # MCX (not explicitly mentioned in docs)
        'CDS': 'CDS',    # Currency derivatives (not explicitly mentioned)
        'NSE_INDEX': 'NSE',  # NSE Index
        'BSE_INDEX': 'BSE'   # BSE Index
    }

    # ScripType mapping for Paytm
    SCRIP_TYPES = {
        'INDEX': 'INDEX',
        'EQUITY': 'EQUITY',
        'ETF': 'ETF',
        'FUTURE': 'FUTURE',
        'OPTION': 'OPTION'
    }

    @staticmethod
    def get_exchange_type(exchange):
        """
        Convert exchange code to Paytm-specific exchange type

        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')

        Returns:
            str: Paytm-specific exchange type
        """
        return PaytmExchangeMapper.EXCHANGE_TYPES.get(exchange, 'NSE')  # Default to NSE if not found

    @staticmethod
    def get_scrip_type(instrument_type):
        """
        Convert instrument type to Paytm scrip type

        Args:
            instrument_type (str): Instrument type (e.g., 'EQ', 'OPTIDX')

        Returns:
            str: Paytm scrip type
        """
        # Map common instrument types to Paytm scrip types
        type_mapping = {
            'EQ': 'EQUITY',
            'INDEX': 'INDEX',
            'ETF': 'ETF',
            'FUTIDX': 'FUTURE',
            'FUTSTK': 'FUTURE',
            'OPTIDX': 'OPTION',
            'OPTSTK': 'OPTION',
        }
        return type_mapping.get(instrument_type, 'EQUITY')


class PaytmCapabilityRegistry:
    """
    Registry of Paytm broker's capabilities including supported exchanges,
    subscription modes, and market depth levels
    """

    # Paytm broker capabilities based on API documentation
    exchanges = ['NSE', 'BSE', 'NFO', 'BFO']

    # Paytm supports 3 modes: LTP, QUOTE, FULL
    subscription_modes = [1, 2, 3]  # 1: LTP, 2: QUOTE, 3: FULL

    # Paytm provides 5 levels of market depth in FULL mode
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
            list: List of supported depth levels (e.g., [5])
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
