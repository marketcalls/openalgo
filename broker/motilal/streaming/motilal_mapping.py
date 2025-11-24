"""
Motilal Oswal exchange mapping and capability registry for WebSocket streaming.

This module handles:
- Exchange code to Motilal-specific exchange type mapping
- Capability registry for supported exchanges, modes, and depth levels
"""

import logging

logger = logging.getLogger(__name__)


class MotilalExchangeMapper:
    """Maps OpenAlgo exchange codes to Motilal-specific exchange types"""

    # Exchange type mapping for Motilal broker
    # Based on WebSocket documentation and API doc
    EXCHANGE_TYPES = {
        'NSE': 'NSE',        # NSE Cash Market
        'BSE': 'BSE',        # BSE Cash Market
        'NFO': 'NSEFO',      # NSE Futures & Options
        'BFO': 'BSEFO',      # BSE F&O
        'MCX': 'MCX',        # MCX Commodity
        'CDS': 'NSECD',      # NSE Currency Derivatives
        'NCX': 'NCDEX',      # NCDEX
    }

    # Exchange character mapping for binary protocol (as per motilal_websocket.py)
    EXCHANGE_CHAR_MAP = {
        'NSE': 'N',
        'BSE': 'B',
        'MCX': 'M',
        'NSECD': 'C',
        'NCDEX': 'D',
        'BSEFO': 'G',
        'NSEFO': 'N'  # NSEFO uses 'N' like NSE
    }

    # Reverse mapping for binary packets
    # Note: NSE and NSEFO both use 'N', differentiated by exchange type (CASH vs DERIVATIVES)
    # We default 'N' to 'NSE' in the reverse mapping
    CHAR_TO_EXCHANGE = {v: k for k, v in EXCHANGE_CHAR_MAP.items()}
    CHAR_TO_EXCHANGE['N'] = 'NSE'  # Ensure 'N' maps to NSE (not NSEFO)

    @staticmethod
    def get_exchange_type(exchange):
        """
        Convert exchange code to Motilal-specific exchange type

        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE', 'NFO')

        Returns:
            str: Motilal-specific exchange type
        """
        return MotilalExchangeMapper.EXCHANGE_TYPES.get(exchange, exchange)

    @staticmethod
    def get_exchange_char(exchange):
        """
        Get single character exchange code for binary protocol

        Args:
            exchange (str): Full exchange name (e.g., 'NSE', 'NSEFO')

        Returns:
            str: Single character exchange code
        """
        exchange_upper = exchange.upper()
        return MotilalExchangeMapper.EXCHANGE_CHAR_MAP.get(exchange_upper, exchange_upper[0] if exchange_upper else 'N')

    @staticmethod
    def get_exchange_from_char(char):
        """
        Get full exchange name from single character code

        Args:
            char (str): Single character exchange code

        Returns:
            str: Full exchange name
        """
        return MotilalExchangeMapper.CHAR_TO_EXCHANGE.get(char, char)


class MotilalCapabilityRegistry:
    """
    Registry of Motilal broker's capabilities including supported exchanges,
    subscription modes, and market depth levels.

    Based on Motilal API documentation:
    - WebSocket uses BINARY packets for market data subscriptions
    - Supports LTP, OHLC, Depth, OI, and Index data
    - Market depth is 5 levels for all exchanges
    """

    # Motilal broker capabilities
    exchanges = ['NSE', 'BSE', 'NFO', 'BFO', 'MCX', 'CDS', 'NCX']

    # Subscription modes:
    # 1: LTP only
    # 2: Quote (LTP + OHLC + Volume)
    # 3: Snap Quote/Depth (Full data including 5-level market depth)
    subscription_modes = [1, 2, 3]

    # Motilal supports 5-level market depth for all exchanges
    depth_support = {
        'NSE': [5],
        'BSE': [5],
        'NFO': [5],
        'BFO': [5],
        'MCX': [5],
        'CDS': [5],
        'NCX': [5]
    }

    # Exchange types for subscription (CASH vs DERIVATIVES)
    exchange_segment_map = {
        'NSE': 'CASH',
        'BSE': 'CASH',
        'NFO': 'DERIVATIVES',
        'BFO': 'DERIVATIVES',
        'MCX': 'DERIVATIVES',
        'CDS': 'DERIVATIVES',
        'NCX': 'DERIVATIVES'
    }

    @classmethod
    def get_supported_depth_levels(cls, exchange):
        """
        Get supported depth levels for an exchange

        Args:
            exchange (str): Exchange code (e.g., 'NSE', 'BSE')

        Returns:
            list: List of supported depth levels (default: [5])
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

    @classmethod
    def get_exchange_segment(cls, exchange):
        """
        Get the segment type for an exchange (CASH or DERIVATIVES)

        Args:
            exchange (str): Exchange code

        Returns:
            str: 'CASH' or 'DERIVATIVES'
        """
        return cls.exchange_segment_map.get(exchange, 'CASH')
