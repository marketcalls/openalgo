"""
delta_mapping.py
Exchange / mode / capability mappings for Delta Exchange WebSocket adapter.
"""

import logging


class DeltaExchangeMapper:
    """Maps OpenAlgo exchange codes to Delta Exchange equivalents.

    Delta Exchange uses plain symbol strings (e.g. "BTCUSD").
    All products trade on a single exchange named "CRYPTO" in OpenAlgo.
    """

    # OpenAlgo exchange code → Delta Exchange exchange code
    EXCHANGE_SEGMENTS = {
        "CRYPTO": "CRYPTO",
        "NSE":    "CRYPTO",   # safety alias if misconfigured
        "BSE":    "CRYPTO",
        "MCX":    "CRYPTO",
    }

    @staticmethod
    def get_segment(exchange: str) -> str:
        return DeltaExchangeMapper.EXCHANGE_SEGMENTS.get(exchange, "CRYPTO")

    @staticmethod
    def get_channel_symbol(br_symbol: str) -> str:
        """Return the symbol string used in Delta WS channel subscriptions."""
        return br_symbol  # Delta uses the contract symbol directly, e.g. "BTCUSD"


class DeltaModeMapper:
    """Maps OpenAlgo subscription mode integers to Delta Exchange channel names."""

    # OpenAlgo mode → Delta WS channel name
    MODE_CHANNELS = {
        1: "v2/ticker",    # LTP mode
        2: "v2/ticker",    # Quote mode (also uses ticker; provides bid/ask/OI)
        3: "l2_orderbook", # Depth mode
    }

    @staticmethod
    def get_channel(mode: int) -> str:
        return DeltaModeMapper.MODE_CHANNELS.get(mode, "v2/ticker")

    @staticmethod
    def get_mode_str(mode: int) -> str:
        return {1: "LTP", 2: "QUOTE", 3: "DEPTH"}.get(mode, "LTP")


class DeltaCapabilityRegistry:
    """
    Registry of Delta Exchange broker capabilities:
    supported exchanges, subscription modes, and market depth.
    """

    exchanges = ["CRYPTO"]

    # Modes: 1 = LTP, 2 = Quote (ticker with bid/ask/OI)
    subscription_modes = [1, 2, 3]

    depth_support = {
        "CRYPTO": [1, 5],  # up to 5-level depth via l2_orderbook channel
    }

    @classmethod
    def get_supported_depth_levels(cls, exchange: str) -> list:
        return cls.depth_support.get(exchange, [1])

    @classmethod
    def is_depth_level_supported(cls, exchange: str, depth_level: int) -> bool:
        return depth_level in cls.get_supported_depth_levels(exchange)

    @classmethod
    def get_fallback_depth_level(cls, exchange: str, requested_depth: int) -> int:
        supported = cls.get_supported_depth_levels(exchange)
        if requested_depth in supported:
            return requested_depth
        return max(supported)

    @classmethod
    def supports_mode(cls, mode: int) -> bool:
        return mode in cls.subscription_modes
