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

    # OpenAlgo mode → Delta WS channels.
    #
    # Depth mode subscribes to ob_l2 *and* ticker: ob_l2 carries price/size
    # levels only, so without the ticker a depth subscriber would publish
    # ltp/oi/ohlc as zero and blank out those columns wherever a depth
    # subscription is the only one for the symbol (the option chain does
    # exactly this).
    MODE_CHANNELS = {
        1: ("ticker",),            # LTP mode
        2: ("ticker",),            # Quote mode (ticker carries bid/ask + sizes + OI)
        3: ("ob_l2", "ticker"),    # Depth mode
    }

    @staticmethod
    def get_channels(mode: int) -> tuple[str, ...]:
        """Return every Delta channel a subscription mode needs."""
        return DeltaModeMapper.MODE_CHANNELS.get(mode, ("ticker",))

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
        "CRYPTO": [1, 5],  # ob_l2 publishes 15 levels; OpenAlgo consumes the top 5
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
