"""Exchange codes and capabilities of Pocketful's market-data feed."""


class PocketfulExchangeMapper:
    """Maps an OpenAlgo exchange to the code Pocketful's feed uses for it."""

    # The codes from the docs' detailed-marketdata.md and snapquote-data.md:
    # exchange_code = {"NSE": 1, "NFO": 2, "CDS": 3, "MCX": 4, "BSE": 6, "BFO": 7}.
    # Indices stream on their cash segment's code, as this plugin always sent
    # them; the docs do not list indices separately.
    EXCHANGE_TYPES = {
        "NSE": 1,
        "NFO": 2,
        "CDS": 3,
        "MCX": 4,
        "BSE": 6,
        "BFO": 7,
        "NSE_INDEX": 1,
        "BSE_INDEX": 6,
    }

    @staticmethod
    def get_exchange_code(exchange):
        """The feed's code for an exchange, or None when the feed has no such segment.

        An unknown exchange is refused rather than sent as NSE: a token on the
        wrong segment names another instrument or none.
        """
        if not isinstance(exchange, str):
            return None
        return PocketfulExchangeMapper.EXCHANGE_TYPES.get(exchange.strip().upper())


class PocketfulCapabilityRegistry:
    """What Pocketful's feed serves: the exchanges, the modes and five depth levels."""

    exchanges = ["NSE", "BSE", "NFO", "BFO", "MCX", "CDS", "NSE_INDEX", "BSE_INDEX"]

    # OpenAlgo modes: 1 LTP (compact packets), 2 Quote (detailed packets),
    # 3 Depth (snapquote packets, five levels each side).
    subscription_modes = [1, 2, 3]

    depth_support = {exchange: [5] for exchange in exchanges}

    @classmethod
    def get_supported_depth_levels(cls, exchange):
        """Depth levels the feed serves for an exchange: always five."""
        return cls.depth_support.get(exchange, [5])

    @classmethod
    def is_depth_level_supported(cls, exchange, depth_level):
        """True when the feed serves that many depth levels for the exchange."""
        return depth_level in cls.get_supported_depth_levels(exchange)

    @classmethod
    def get_fallback_depth_level(cls, exchange, requested_depth):
        """The deepest supported level not above the request, else five."""
        fallbacks = [d for d in cls.get_supported_depth_levels(exchange) if d <= requested_depth]
        return max(fallbacks) if fallbacks else 5
