import logging


class IndmoneyExchangeMapper:
    """Maps OpenAlgo exchange codes to INDmoney-specific segment codes"""

    # Exchange segment mapping for INDmoney broker.
    # Format: SEGMENT:TOKEN (e.g., NSE:2885, BSE:500325).
    # These six prefixes are the complete set the INDstocks WebSocket defines
    # (docs 08-websockets / 16-glossary). MCX, NCDEX and currency are NOT
    # supported by this broker - mapping them to invented prefixes only defers
    # the failure to the server.
    EXCHANGE_SEGMENTS = {
        "NSE": "NSE",  # NSE Cash Market
        "NFO": "NFO",  # NSE Futures & Options
        "BSE": "BSE",  # BSE Cash Market
        "BFO": "BFO",  # BSE F&O
        "NSE_INDEX": "NIDX",  # NSE Index
        "BSE_INDEX": "BIDX",  # BSE Index
    }

    @staticmethod
    def get_segment(exchange):
        """
        Convert exchange code to INDmoney-specific segment

        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')

        Returns:
            str | None: INDmoney segment code, or None if unsupported.
        """
        return IndmoneyExchangeMapper.EXCHANGE_SEGMENTS.get(exchange)

    @staticmethod
    def create_instrument_token(exchange, token):
        """
        Create INDmoney instrument token in SEGMENT:TOKEN format

        Args:
            exchange (str): Exchange code
            token (str): Token/symbol ID

        Returns:
            str | None: Formatted instrument token (e.g., "NSE:2885"), or None
            if the exchange is not supported by INDmoney.
        """
        segment = IndmoneyExchangeMapper.get_segment(exchange)
        if not segment:
            return None
        return f"{segment}:{token}"


class IndmoneyModeMapper:
    """Maps subscription mode integers to INDmoney mode strings"""

    # Mode mapping: OpenAlgo mode number -> INDmoney mode string
    MODE_MAP = {
        1: "ltp",  # LTP (Last Traded Price)
        2: "quote",  # Quote (Full quote data)
    }

    # Reverse mapping for mode validation
    REVERSE_MODE_MAP = {"ltp": 1, "quote": 2}

    @staticmethod
    def get_indmoney_mode(mode):
        """
        Convert OpenAlgo mode number to INDmoney mode string

        Args:
            mode (int): OpenAlgo mode (1: LTP, 2: Quote)

        Returns:
            str: INDmoney mode string ('ltp' or 'quote')
        """
        return IndmoneyModeMapper.MODE_MAP.get(mode, "ltp")

    @staticmethod
    def get_openalgo_mode(indmoney_mode):
        """
        Convert INDmoney mode string to OpenAlgo mode number

        Args:
            indmoney_mode (str): INDmoney mode ('ltp' or 'quote')

        Returns:
            int: OpenAlgo mode number
        """
        return IndmoneyModeMapper.REVERSE_MODE_MAP.get(indmoney_mode, 1)


class IndmoneyCapabilityRegistry:
    """
    Registry of INDmoney broker's capabilities including supported exchanges,
    subscription modes, and market depth levels
    """

    # INDmoney broker capabilities. Matches plugin.json and the six WebSocket
    # prefixes the INDstocks docs define - the broker trades NSE/BSE cash and
    # F&O only, with no commodity or currency segment.
    exchanges = ["NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"]

    # INDmoney supports only 2 modes: ltp and quote
    # Mode 1: LTP, Mode 2: Quote
    subscription_modes = [1, 2]

    # INDmoney does not provide explicit market depth data
    # The quote mode provides best bid/ask but not full depth
    depth_support = {
        "NSE": [1],  # Basic depth only (best bid/ask)
        "BSE": [1],
        "NFO": [1],
        "BFO": [1],
        "NSE_INDEX": [1],
        "BSE_INDEX": [1],
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
        return cls.depth_support.get(exchange, [1])

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
        # INDmoney doesn't support market depth beyond basic bid/ask
        # So we only support depth level 1
        return depth_level == 1

    @classmethod
    def get_fallback_depth_level(cls, exchange, requested_depth):
        """
        Get the best available depth level as a fallback

        Args:
            exchange (str): Exchange code
            requested_depth (int): Requested depth level

        Returns:
            int: Highest supported depth level (always 1 for INDmoney)
        """
        # INDmoney only supports basic depth
        return 1

    @classmethod
    def supports_mode(cls, mode):
        """
        Check if a subscription mode is supported

        Args:
            mode (int): Subscription mode (1: LTP, 2: Quote)

        Returns:
            bool: True if supported, False otherwise
        """
        return mode in cls.subscription_modes
