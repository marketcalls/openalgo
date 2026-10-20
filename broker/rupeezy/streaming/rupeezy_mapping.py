"""Rupeezy Vortex websocket capabilities: subscription modes and depth levels.

Vortex streams three modes (https://vortex.rupeezy.in/docs/latest/feed/):
ltp (22-byte packet), ohlcv (62) and full (266, with 5-level depth).
"""


class RupeezyCapabilityRegistry:
    # OpenAlgo numeric mode (1=LTP, 2=Quote, 3=Depth) -> Vortex mode.
    MODE_MAP = {1: "ltp", 2: "ohlcv", 3: "full"}

    # Rank so a symbol wanted in several modes is subscribed at the richest.
    MODE_RANK = {"ltp": 1, "ohlcv": 2, "full": 3}

    SUPPORTED_DEPTH_LEVELS = [5]
    DEFAULT_DEPTH_LEVEL = 5

    @classmethod
    def get_vortex_mode(cls, mode):
        return cls.MODE_MAP.get(mode, "ohlcv")

    @classmethod
    def get_supported_depth_levels(cls, exchange=None):
        return cls.SUPPORTED_DEPTH_LEVELS

    @classmethod
    def is_depth_level_supported(cls, depth_level, exchange=None):
        return depth_level in cls.SUPPORTED_DEPTH_LEVELS

    @classmethod
    def get_fallback_depth_level(cls, requested_depth_level, exchange=None):
        return cls.DEFAULT_DEPTH_LEVEL
