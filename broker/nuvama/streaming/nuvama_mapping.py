"""Nuvama streaming capabilities: modes 1/2/3, five depth levels."""

_TOPIC_MODE = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}


def topic_mode(mode):
    return _TOPIC_MODE.get(int(mode), "QUOTE")


class NuvamaCapabilityRegistry:
    exchanges = ["NSE", "BSE", "NFO", "BFO", "CDS", "MCX", "NCDEX", "NSE_INDEX", "BSE_INDEX"]
    subscription_modes = [1, 2, 3]
    depth_support = {exchange: [5] for exchange in exchanges}

    @classmethod
    def get_supported_depth_levels(cls, exchange):
        return cls.depth_support.get(exchange, [5])

    @classmethod
    def is_depth_level_supported(cls, exchange, depth_level):
        return depth_level in cls.get_supported_depth_levels(exchange)

    @classmethod
    def get_fallback_depth_level(cls, exchange, requested_depth):
        return 5
