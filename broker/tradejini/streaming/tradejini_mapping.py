"""
Tradejini-specific exchange and capability mappings for WebSocket streaming
"""

class TradejiniExchangeMapper:
    """Maps exchange codes between OpenAlgo and Tradejini formats"""

    # Exchange mappings based on Tradejini's SEG_INFO
    EXCHANGE_MAP = {
        'NSE': 'NSE',
        'BSE': 'BSE',
        'NFO': 'NFO',
        'BFO': 'BFO',
        'CDS': 'CDS',
        'BCD': 'BCD',
        'MCD': 'MCD',
        'MCX': 'MCX',
        'NCO': 'NCO',
        'BCO': 'BCO'
    }

    # Exchange segment IDs used in Tradejini WebSocket
    EXCHANGE_SEGMENTS = {
        1: 'NSE',
        2: 'BSE',
        3: 'NFO',
        4: 'BFO',
        5: 'CDS',
        6: 'BCD',
        7: 'MCD',
        8: 'MCX',
        9: 'NCO',
        10: 'BCO'
    }

    # Reverse mapping
    SEGMENT_TO_ID = {v: k for k, v in EXCHANGE_SEGMENTS.items()}

    @classmethod
    def get_exchange_segment(cls, exchange_code: str) -> int:
        """
        Get Tradejini exchange segment ID from exchange code

        Args:
            exchange_code: Exchange code (e.g., 'NSE', 'BSE')

        Returns:
            int: Exchange segment ID for Tradejini
        """
        return cls.SEGMENT_TO_ID.get(exchange_code.upper(), 1)  # Default to NSE

    @classmethod
    def get_exchange_from_segment(cls, segment_id: int) -> str:
        """
        Get exchange code from Tradejini segment ID

        Args:
            segment_id: Tradejini exchange segment ID

        Returns:
            str: Exchange code
        """
        return cls.EXCHANGE_SEGMENTS.get(segment_id, 'NSE')


class TradejiniCapabilityRegistry:
    """Registry for Tradejini-specific capabilities and limitations"""

    # Depth level support by exchange
    # Tradejini supports 5-level depth for all exchanges
    DEPTH_CAPABILITIES = {
        'NSE': {
            'supported_levels': [5],
            'default_level': 5,
            'max_level': 5
        },
        'BSE': {
            'supported_levels': [5],
            'default_level': 5,
            'max_level': 5
        },
        'NFO': {
            'supported_levels': [5],
            'default_level': 5,
            'max_level': 5
        },
        'BFO': {
            'supported_levels': [5],
            'default_level': 5,
            'max_level': 5
        },
        'MCX': {
            'supported_levels': [5],
            'default_level': 5,
            'max_level': 5
        },
        'CDS': {
            'supported_levels': [5],
            'default_level': 5,
            'max_level': 5
        },
        'BCD': {
            'supported_levels': [5],
            'default_level': 5,
            'max_level': 5
        },
        'MCD': {
            'supported_levels': [5],
            'default_level': 5,
            'max_level': 5
        },
        'NCO': {
            'supported_levels': [5],
            'default_level': 5,
            'max_level': 5
        },
        'BCO': {
            'supported_levels': [5],
            'default_level': 5,
            'max_level': 5
        }
    }

    # Mode capabilities
    MODE_CAPABILITIES = {
        'LTP': 1,      # Last Traded Price only
        'QUOTE': 2,    # Full quote with OHLC
        'DEPTH': 3     # Market depth (5 levels)
    }

    @classmethod
    def is_depth_level_supported(cls, exchange: str, depth_level: int) -> bool:
        """
        Check if a specific depth level is supported for an exchange

        Args:
            exchange: Exchange code
            depth_level: Requested depth level

        Returns:
            bool: True if supported, False otherwise
        """
        exchange = exchange.upper()
        if exchange not in cls.DEPTH_CAPABILITIES:
            return False

        return depth_level in cls.DEPTH_CAPABILITIES[exchange]['supported_levels']

    @classmethod
    def get_fallback_depth_level(cls, exchange: str, requested_level: int) -> int:
        """
        Get the appropriate fallback depth level if requested level is not supported

        Args:
            exchange: Exchange code
            requested_level: Originally requested depth level

        Returns:
            int: The fallback depth level to use
        """
        exchange = exchange.upper()

        # If exchange not found, default to 5
        if exchange not in cls.DEPTH_CAPABILITIES:
            return 5

        capabilities = cls.DEPTH_CAPABILITIES[exchange]

        # If requested level is supported, return it
        if requested_level in capabilities['supported_levels']:
            return requested_level

        # Return the default level for this exchange
        return capabilities['default_level']

    @classmethod
    def get_max_depth_level(cls, exchange: str) -> int:
        """
        Get the maximum supported depth level for an exchange

        Args:
            exchange: Exchange code

        Returns:
            int: Maximum depth level
        """
        exchange = exchange.upper()

        if exchange not in cls.DEPTH_CAPABILITIES:
            return 5

        return cls.DEPTH_CAPABILITIES[exchange]['max_level']

    @classmethod
    def is_mode_supported(cls, mode_name: str) -> bool:
        """
        Check if a mode is supported

        Args:
            mode_name: Mode name (e.g., 'LTP', 'QUOTE', 'DEPTH')

        Returns:
            bool: True if supported
        """
        return mode_name.upper() in cls.MODE_CAPABILITIES

    @classmethod
    def get_mode_value(cls, mode_name: str) -> int:
        """
        Get the numeric value for a mode

        Args:
            mode_name: Mode name

        Returns:
            int: Mode value or None if not supported
        """
        return cls.MODE_CAPABILITIES.get(mode_name.upper())