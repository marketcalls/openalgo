"""OpenAlgo order fields -> Pocketful order bodies, and Pocketful codes -> OpenAlgo.

Sources: Pocketful's API documentation (offline copy of 2026-11-17):
place-regular-order.md, modify-regular-order.md and annexure.md.

Order types. The annexure says "Only LIMIT and SL (Stop Loss) orders are
allowed for API trading. MARKET and SL-M (Stop Loss Market) orders are
restricted / not allowed", and the order pages list `LIMIT` and `SL` as the
only `order_type` values. So OpenAlgo never sends MARKET or SLM: it prices both
itself with Market Price Protection, from the shared slabs in utils/mpp_slab.py.

- MARKET -> LIMIT at the LTP moved by the slab, in the direction the order
  fills (above for a BUY, below for a SELL), at least one tick past the LTP and
  on a tick.
- SL-M -> SL whose limit is the trigger moved by the slab: above it for a BUY,
  below it for a SELL, at least one tick past it and on a tick. It is priced
  off its own trigger, never the LTP, so the limit is always on the side of the
  trigger the order fills from.

An order OpenAlgo cannot price (no tick size in the master contract, no LTP, a
SELL trigger too low to leave a positive limit) is refused before it is sent,
with OrderFieldError: Pocketful would refuse the native MARKET or SLM anyway.

Products. The order pages list `CNC`, `MIS` and `NRML`, which is what is sent.
The annexure's product table lists `CNC`, `INTRADAY`, `MARGIN`, `CO` and `BO`
instead; the books in the docs all carry `CNC`, `MIS` and `NRML`. Both
spellings are read back (INTRADAY as MIS, MARGIN as NRML).
"""

import math
from decimal import Decimal

from database.token_db import get_symbol_info, get_token
from utils.logging import get_logger
from utils.mpp_slab import get_instrument_type_from_symbol, get_mpp_percentage

logger = get_logger(__name__)


class OrderFieldError(ValueError):
    """An order OpenAlgo will not send to Pocketful as it stands. The message is for the trader."""


# OpenAlgo pricetype -> the Pocketful order_type it goes out as. MARKET and
# SL-M are priced first (protected_order_type); these are their sent types.
_ORDER_TYPES = {"MARKET": "LIMIT", "LIMIT": "LIMIT", "SL": "SL", "SL-M": "SL"}

# Pocketful order_type -> OpenAlgo pricetype, for the books. "SLM" and
# "MARKET" are the spellings the order book pages use for orders placed
# elsewhere (fetch-completed-orders.md: "LIMIT", "SLM"; order-updates.md:
# LIMIT, MARKET).
_REVERSE_ORDER_TYPES = {
    "LIMIT": "LIMIT",
    "SL": "SL",
    "SLM": "SL-M",
    "SL-M": "SL-M",
    "MARKET": "MARKET",
}

# OpenAlgo product -> Pocketful product (place-regular-order.md).
_PRODUCTS = {"CNC": "CNC", "NRML": "NRML", "MIS": "MIS"}

# Pocketful product -> OpenAlgo product. INTRADAY and MARGIN are the
# annexure's names for the same two products.
_REVERSE_PRODUCTS = {
    "CNC": "CNC",
    "NRML": "NRML",
    "MIS": "MIS",
    "INTRADAY": "MIS",
    "MARGIN": "NRML",
}


def _tick_decimals(tick: float) -> int:
    """Decimal places implied by a tick size (0.05 -> 2, 0.0025 -> 4)."""
    return max(0, -Decimal(str(tick)).as_tuple().exponent)


def _snap_to_tick(value: float, tick: float, direction: str) -> float:
    """Snap ``value`` to a multiple of ``tick``: "floor" rounds down, "ceil" up.

    Snapping away from the reference price keeps the limit on the side the
    order fills from; rounding to the nearest tick could put it back on the
    reference.
    """
    ratio = round(value / tick, 6)  # tame float noise before the floor/ceil
    k = math.floor(ratio) if direction == "floor" else math.ceil(ratio)
    return round(k * tick, _tick_decimals(tick))


def _tick_size(symbol: str, exchange: str) -> float | None:
    """The instrument's tick size from the master contract, or None when it is
    missing or not a positive number (a master contract row can hold NaN)."""
    try:
        info = get_symbol_info(symbol, exchange)
    except Exception:
        logger.exception(f"Could not read the tick size of {exchange}:{symbol}")
        return None
    try:
        tick = float(getattr(info, "tick_size", None)) if info else None
    except (TypeError, ValueError):
        return None
    if tick is None or not math.isfinite(tick) or tick <= 0:
        return None
    return tick


def _beyond(reference: float, action: str, pct: float, tick: float) -> float:
    """A limit ``pct`` past ``reference`` in the fill direction, at least one
    tick past it and on a tick: above for a BUY, below for a SELL."""
    if action == "BUY":
        return _snap_to_tick(max(reference * (1 + pct), reference + tick), tick, "ceil")
    return _snap_to_tick(min(reference * (1 - pct), reference - tick), tick, "floor")


def _ltp(symbol: str, exchange: str, auth_token) -> float:
    """The last traded price from Pocketful's market data, or 0.0 without one.

    BrokerData is imported here, not at the top: broker/pocketful/api/data.py
    pulls in the market data feed, which an order module must not load just
    to be imported.
    """
    try:
        from broker.pocketful.api.data import BrokerData

        ltp = float(BrokerData(auth_token).get_ltp(symbol, exchange) or 0)
    except Exception:
        logger.exception(f"MPP: could not read the LTP of {exchange}:{symbol}")
        return 0.0
    return ltp if math.isfinite(ltp) and ltp > 0 else 0.0


def protected_order_type(data, auth_token=None) -> tuple[str, float]:
    """(order_type, price) as sent to Pocketful, with MARKET and SL-M priced.

    ``data`` carries the OpenAlgo symbol, exchange, action, pricetype, price
    and trigger_price. Raises OrderFieldError for an order OpenAlgo cannot
    price or does not know.
    """
    pricetype = str(data.get("pricetype") or "").upper()
    if pricetype not in _ORDER_TYPES:
        raise OrderFieldError(
            f"OpenAlgo does not know the price type {data.get('pricetype')!r}. "
            "Use MARKET, LIMIT, SL or SL-M."
        )
    if pricetype in ("LIMIT", "SL"):
        return _ORDER_TYPES[pricetype], float(data.get("price") or 0)

    symbol, exchange = data["symbol"], data["exchange"]
    action = str(data["action"]).upper()
    instrument_type = get_instrument_type_from_symbol(symbol, exchange)
    tick = _tick_size(symbol, exchange)

    if pricetype == "SL-M":
        trigger = float(data.get("trigger_price") or 0)
        if trigger <= 0:
            raise OrderFieldError("An SL-M order needs a trigger price above zero.")
        if tick is None:
            raise OrderFieldError(
                f"OpenAlgo cannot price the SL-M order: the tick size of {symbol} on "
                f"{exchange} is missing from the master contract. Download the master "
                "contract again, or place an SL order with your own limit price."
            )
        pct = get_mpp_percentage(trigger, instrument_type) / 100
        limit = _beyond(trigger, action, pct, tick)
        if limit <= 0:
            raise OrderFieldError(
                f"The trigger price {trigger} is too low for an SL-M sell on {symbol}: "
                "there is no limit price below it. Place an SL order with your own "
                "limit price instead."
            )
        logger.info(f"MPP: SL-M -> SL for {exchange}:{symbol}, trigger {trigger}, limit {limit}")
        return "SL", limit

    # MARKET
    if tick is None:
        raise OrderFieldError(
            f"OpenAlgo cannot price the market order: the tick size of {symbol} on "
            f"{exchange} is missing from the master contract, and Pocketful takes only "
            "priced orders from the API. Download the master contract again, or place a "
            "LIMIT order."
        )
    ltp = _ltp(symbol, exchange, auth_token)
    if ltp <= 0:
        raise OrderFieldError(
            f"OpenAlgo could not get a live price for {symbol} on {exchange}, so the "
            "market order was not sent: Pocketful takes only priced orders from the API. "
            "Try again in a moment, or place a LIMIT order."
        )
    pct = get_mpp_percentage(ltp, instrument_type) / 100
    # A SELL off the lowest-priced contracts can floor to zero: the smallest
    # price there is, one tick, is still at or below the LTP.
    limit = max(_beyond(ltp, action, pct, tick), tick)
    logger.info(f"MPP: MARKET -> LIMIT for {exchange}:{symbol}, LTP {ltp}, limit {limit}")
    return "LIMIT", limit


def _instrument_token(data) -> str:
    token = get_token(data["symbol"], data["exchange"])
    if not token:
        raise OrderFieldError(
            f"{data['symbol']} on {data['exchange']} is not in the Pocketful master "
            "contract. Check the symbol, or download the master contract again."
        )
    return str(token)


def _whole(value, default=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _order_body(data, client_id, auth_token) -> dict:
    """The fields place and modify share (place-regular-order.md,
    modify-regular-order.md)."""
    order_type, price = protected_order_type(data, auth_token)
    trigger = float(data.get("trigger_price") or 0) if order_type == "SL" else 0.0
    return {
        "exchange": data["exchange"],
        "instrument_token": _instrument_token(data),
        "client_id": client_id,
        "order_type": order_type,
        "price": price,
        "quantity": _whole(data["quantity"]),
        "disclosed_quantity": _whole(data.get("disclosed_quantity") or 0),
        "validity": "DAY",
        "product": map_product_type(data["product"]),
        "order_side": str(data["action"]).upper(),
        # The body table says "Web"; the request packet and the cURL example
        # both send "WEB", as the previous plugin did.
        "device": "WEB",
        # The docs' example value. The body table calls it "the unique order
        # ID generated by the user", but every example sends 1, as the
        # previous plugin did.
        "user_order_id": 1,
        "trigger_price": trigger,
        "execution_type": "REGULAR",
    }


def transform_data(data, client_id=None, auth_token=None):
    """Body for POST /api/v1/orders (place-regular-order.md).

    MARKET and SL-M are priced with Market Price Protection (see the module
    docstring); raises OrderFieldError for an order that cannot be sent.
    """
    body = _order_body(data, client_id, auth_token)
    body["amo"] = False
    logger.info(
        f"Pocketful order: {body['exchange']}:{data['symbol']} {body['order_side']} "
        f"{body['quantity']} {body['order_type']} price {body['price']} "
        f"trigger {body['trigger_price']} {body['product']}"
    )
    return body


def transform_modify_order_data(data, client_id=None, auth_token=None):
    """Body for PUT /api/v1/orders (modify-regular-order.md).

    A modify to MARKET or SL-M is priced like a new order, so ``data`` must
    still carry the OpenAlgo symbol. The modify page's packet has no ``amo``.
    """
    body = _order_body(data, client_id, auth_token)
    body["oms_order_id"] = str(data["orderid"])
    return body


def map_order_type(pricetype):
    """OpenAlgo pricetype -> the Pocketful order_type it is sent as."""
    return _ORDER_TYPES.get(str(pricetype).upper(), "LIMIT")


def reverse_map_order_type(order_type):
    """Pocketful order_type -> OpenAlgo pricetype; an unknown one is kept as it is."""
    return _REVERSE_ORDER_TYPES.get(str(order_type or "").upper(), order_type or "")


def map_product_type(product):
    """OpenAlgo product -> Pocketful product."""
    return _PRODUCTS.get(str(product).upper(), "MIS")


def reverse_map_product_type(exchange, product):
    """Pocketful product -> OpenAlgo product, or None for one OpenAlgo does not
    trade (CO, BO)."""
    return _REVERSE_PRODUCTS.get(str(product or "").upper())
