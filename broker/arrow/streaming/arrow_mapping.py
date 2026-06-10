"""Arrow WebSocket mapping utilities: exchange codes, subscription modes, and
depth-level capabilities.

Arrow's standard market-data stream (wss://ds.arrow.trade) is token-based and
supports 5-level depth only (modes: ltpc / ltp / quote / full). Higher depth
(e.g. 50-level) is NOT offered by Arrow, so DEPTH resolves to 5. If Arrow ever
adds a deeper feed, follow the fyers pattern (a separate websocket for the
deeper book, routed by requested depth_level) rather than overloading this one.
"""

from utils.logging import get_logger

logger = get_logger(__name__)


class ArrowExchangeMapper:
    """OpenAlgo <-> Arrow exchange codes. Indices collapse to Arrow 'INDEX' on
    the quote side, but the websocket is token-based so streaming does not need
    the exchange in the subscribe frame -- the token alone identifies the
    instrument. We retain the OpenAlgo exchange per token for topic routing."""

    _OA_TO_ARROW = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NFO",
        "BFO": "BFO",
        "MCX": "MCX",
        "CDS": "NCD",
        "BCD": "BCD",
        "NSE_INDEX": "INDEX",
        "BSE_INDEX": "INDEX",
    }
    _ARROW_TO_OA = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NFO",
        "BFO": "BFO",
        "MCX": "MCX",
        "NCD": "CDS",
        "BCD": "BCD",
    }

    @classmethod
    def to_arrow_exchange(cls, oa_exchange):
        return cls._OA_TO_ARROW.get(str(oa_exchange).upper(), str(oa_exchange).upper())

    @classmethod
    def to_oa_exchange(cls, arrow_exchange):
        return cls._ARROW_TO_OA.get(str(arrow_exchange).upper(), str(arrow_exchange).upper())


class ArrowCapabilityRegistry:
    """Arrow WebSocket capabilities."""

    # OpenAlgo capability -> Arrow subscription mode.
    # LTP -> ltpc so we also receive previous close (cheap, useful for change%).
    CAPABILITY_MAP = {
        "LTP": "ltpc",
        "QUOTE": "quote",
        "DEPTH": "full",
    }

    # OpenAlgo numeric mode (1/2/3) -> Arrow subscription mode.
    MODE_MAP = {
        1: "ltpc",
        2: "quote",
        3: "full",
    }

    SUPPORTED_CAPABILITIES = set(CAPABILITY_MAP.keys())

    # Arrow's standard stream provides 5-level depth only.
    SUPPORTED_DEPTH_LEVELS = [5]
    DEFAULT_DEPTH_LEVEL = 5

    @classmethod
    def get_arrow_mode(cls, capability):
        return cls.CAPABILITY_MAP.get(str(capability).upper(), "quote")

    @classmethod
    def get_arrow_mode_for_numeric(cls, mode):
        return cls.MODE_MAP.get(mode, "quote")

    @classmethod
    def is_supported(cls, capability):
        return str(capability).upper() in cls.SUPPORTED_CAPABILITIES

    @classmethod
    def get_supported_depth_levels(cls, exchange=None):
        return cls.SUPPORTED_DEPTH_LEVELS

    @classmethod
    def is_depth_level_supported(cls, depth_level, exchange=None):
        return depth_level in cls.SUPPORTED_DEPTH_LEVELS

    @classmethod
    def get_fallback_depth_level(cls, requested_depth_level, exchange=None):
        """Arrow only supports 5; any request falls back to 5."""
        return cls.DEFAULT_DEPTH_LEVEL
