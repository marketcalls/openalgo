"""
Sahi market-data mapping: exchanges, modes, capabilities and tick normalization.

Sahi streams prices as integer paise; OpenAlgo publishes rupees. The stream
carries no open/high/low/close, last traded quantity, average price or total
buy/sell quantity, so those keys are left out of the payload rather than sent
as 0; nothing is derived or invented. last_trade_time is absent for indices,
and then ltt / last_trade_time are left out too.
"""

from . import sahi_proto as pb

# OpenAlgo mode ints
OA_MODE_LTP = 1
OA_MODE_QUOTE = 2
OA_MODE_DEPTH = 3

# OpenAlgo mode -> Sahi Mode enum
OA_TO_SAHI_MODE = {
    OA_MODE_LTP: pb.MODE_LTP,
    OA_MODE_QUOTE: pb.MODE_QUOTE,
    OA_MODE_DEPTH: pb.MODE_DEPTH,
}

# OpenAlgo mode -> internal ZMQ topic suffix
MODE_TOPIC = {OA_MODE_LTP: "LTP", OA_MODE_QUOTE: "QUOTE", OA_MODE_DEPTH: "DEPTH"}

# Decoded tick kind -> the highest OpenAlgo mode that tick can serve
TICK_KIND_LEVEL = {
    pb.KIND_LTP: OA_MODE_LTP,
    pb.KIND_QUOTE: OA_MODE_QUOTE,
    pb.KIND_DEPTH: OA_MODE_DEPTH,
}

DEPTH_LEVELS = 5


class SahiExchangeMapper:
    """OpenAlgo exchange <-> Sahi ExchangeSegment enum."""

    EXCHANGE_SEGMENTS = {
        "NSE": pb.SEGMENT_NSE,
        "BSE": pb.SEGMENT_BSE,
        "NFO": pb.SEGMENT_NFO,
        "BFO": pb.SEGMENT_BFO,
        "NSE_INDEX": pb.SEGMENT_NSE,
        "BSE_INDEX": pb.SEGMENT_BSE,
    }

    @classmethod
    def get_exchange_segment(cls, exchange: str) -> int | None:
        return cls.EXCHANGE_SEGMENTS.get(exchange)

    @classmethod
    def is_supported(cls, exchange: str) -> bool:
        return exchange in cls.EXCHANGE_SEGMENTS


class SahiCapabilityRegistry:
    """What the Sahi stream supports."""

    exchanges = ["NSE", "BSE", "NFO", "BFO", "NSE_INDEX", "BSE_INDEX"]
    subscription_modes = [OA_MODE_LTP, OA_MODE_QUOTE, OA_MODE_DEPTH]
    # The stream sends up to 5 or 20 levels, but OpenAlgo's depth contract is 5.
    depth_support = {exchange: [DEPTH_LEVELS] for exchange in exchanges}

    # Per Sahi docs
    MAX_INSTRUMENTS_PER_CONNECTION = 1000
    MAX_CONNECTIONS_PER_TOKEN = 5

    @classmethod
    def get_supported_depth_levels(cls, exchange: str | None = None) -> list[int]:
        return list(cls.depth_support.get(exchange, [DEPTH_LEVELS]))

    @classmethod
    def is_depth_level_supported(cls, exchange: str, depth_level: int) -> bool:
        return depth_level in cls.get_supported_depth_levels(exchange)

    @classmethod
    def get_fallback_depth_level(cls, exchange: str, requested_depth: int) -> int:
        fallbacks = [d for d in cls.get_supported_depth_levels(exchange) if d <= requested_depth]
        return max(fallbacks) if fallbacks else DEPTH_LEVELS


# ---------------------------------------------------------------------------
# Tick normalization
# ---------------------------------------------------------------------------


def _rupees(paise: int) -> float:
    return paise / 100.0


def _depth_side(levels: list) -> list[dict]:
    side = [
        {"price": _rupees(price), "quantity": qty, "orders": orders}
        for price, qty, orders in levels[:DEPTH_LEVELS]
    ]
    # Sahi sends only levels holding orders; OpenAlgo depth is always 5 rows.
    while len(side) < DEPTH_LEVELS:
        side.append({"price": 0.0, "quantity": 0, "orders": 0})
    return side


def build_ltp_payload(tick: dict, symbol: str, exchange: str, now_ms: int) -> dict:
    payload = {
        "symbol": symbol,
        "exchange": exchange,
        "mode": "ltp",
        "ltp": _rupees(tick["last_trade_price"]),
        "timestamp": now_ms,
    }
    ltt = tick.get("last_trade_time")
    if ltt is not None:  # absent for indices: no trade time to publish
        payload["ltt"] = ltt
        payload["last_trade_time"] = ltt
    return payload


def build_quote_payload(tick: dict, symbol: str, exchange: str, now_ms: int) -> dict:
    payload = build_ltp_payload(tick, symbol, exchange, now_ms)
    oi = tick.get("open_interest")
    # open/high/low/close, last_quantity, average_price and total buy/sell
    # quantity are not carried by the Sahi stream, so they are not published.
    payload.update(
        {
            "mode": "quote",
            "volume": tick.get("volume_today", 0),
            "oi": oi if oi is not None else 0,
            "open_interest": oi if oi is not None else 0,
            "upper_circuit": _rupees(tick.get("dpr_upper", 0)),
            "lower_circuit": _rupees(tick.get("dpr_lower", 0)),
        }
    )
    return payload


def build_depth_payload(tick: dict, symbol: str, exchange: str, now_ms: int) -> dict:
    payload = build_quote_payload(tick, symbol, exchange, now_ms)
    payload["mode"] = "full"
    payload["depth"] = {
        "buy": _depth_side(tick.get("best_buys", [])),
        "sell": _depth_side(tick.get("best_sells", [])),
    }
    return payload


_BUILDERS = {
    OA_MODE_LTP: build_ltp_payload,
    OA_MODE_QUOTE: build_quote_payload,
    OA_MODE_DEPTH: build_depth_payload,
}


def build_payloads(
    kind: str, tick: dict, symbol: str, exchange: str, modes, now_ms: int
) -> list[tuple[str, dict]]:
    """Fan one decoded tick out to every subscribed OpenAlgo mode it can serve.

    A DepthTick serves DEPTH, QUOTE and LTP; a QuoteTick serves QUOTE and LTP;
    an LtpTick serves LTP only. A mode higher than the tick (for example a
    QuoteTick that arrives before a pending upgrade to DEPTH lands) is skipped
    rather than published with empty fields.

    Returns a list of (topic, payload).
    """
    level = TICK_KIND_LEVEL.get(kind)
    if level is None:
        return []
    out = []
    for mode in sorted(modes):
        if mode <= level:
            topic = f"{exchange}_{symbol}_{MODE_TOPIC[mode]}"
            out.append((topic, _BUILDERS[mode](tick, symbol, exchange, now_ms)))
    return out
