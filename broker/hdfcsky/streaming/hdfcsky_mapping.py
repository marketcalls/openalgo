"""HDFC Sky WebSocket mapping utilities: subscription types and depth-level
capabilities.

HDFC Sky's feed (`/wsapi/v1/session`) subscribes by prefixed scripId
("NSE_2885", "NSE_INDEX_26000") and delivers protobuf GenericDTO frames. The
subscription `type` selects how much of the packet is populated:

    LTP    last traded price only
    ALL    full MBP packet -- OHLC, volume, 5-level depth, OI, circuit limits
    GREEK  option greeks (NSE_FO_GREEK / BSE_FO_GREEK packets)

Depth is 5 levels; HDFC Sky publishes no deeper book. If it ever adds one,
follow the fyers pattern (a second socket routed by `depth_level`) rather than
overloading this one.
"""

from utils.logging import get_logger

logger = get_logger(__name__)


class HDFCSkyCapabilityRegistry:
    """HDFC Sky WebSocket capabilities."""

    # OpenAlgo capability -> HDFC Sky subscription type.
    #
    # QUOTE and DEPTH both map to ALL: the feed has no intermediate tier, and
    # the full MBP packet is what carries OHLC / volume as well as the book.
    CAPABILITY_MAP = {
        "LTP": "LTP",
        "QUOTE": "ALL",
        "DEPTH": "ALL",
    }

    # OpenAlgo numeric mode (1=LTP, 2=Quote, 3=Depth) -> subscription type.
    MODE_MAP = {1: "LTP", 2: "ALL", 3: "ALL"}

    SUPPORTED_CAPABILITIES = set(CAPABILITY_MAP)

    SUPPORTED_DEPTH_LEVELS = [5]
    DEFAULT_DEPTH_LEVEL = 5

    # Documented feed limits: up to 300 instruments per connection and up to
    # three simultaneous connections per API key.
    MAX_INSTRUMENTS_PER_CONNECTION = 300
    MAX_CONNECTIONS_PER_API_KEY = 3

    @classmethod
    def get_subscription_type(cls, capability):
        return cls.CAPABILITY_MAP.get(str(capability).upper(), "ALL")

    @classmethod
    def get_subscription_type_for_numeric(cls, mode):
        return cls.MODE_MAP.get(mode, "ALL")

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
        """HDFC Sky only publishes 5 levels; any request falls back to 5."""
        return cls.DEFAULT_DEPTH_LEVEL
