# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping ibullssecurities Broking Parameters https://symphonyfintech.com/xts-trading-front-end-api/
"""OpenAlgo order fields -> Ibulls (XTS) order bodies.

Ibulls' RMS may refuse a native MARKET or SL-M order from an API session, so
both go out already priced with Market Price Protection (the shared slabs in
utils/mpp_slab.py), as broker/fivepaisa and broker/nuvama send them:

- MARKET -> LIMIT at the LTP moved by the slab, in the direction the order
  fills (above for a BUY, below for a SELL), at least one tick past the LTP
  and on a tick. Without a tick size or an LTP there is no price to send, and
  the order goes out as MARKET, for Ibulls to accept or refuse.
- SL-M -> STOPLIMIT whose limit is the trigger moved by the slab: above it for
  a BUY, below it for a SELL, at least one tick past it and on a tick. It is
  priced off its own trigger, never the LTP, so the limit is always on the
  right side of the trigger. Without a tick size, or when a SELL trigger is
  too low to leave a positive limit, the order is refused before it is sent.

The LTP comes from the feed token stored with the Ibulls session, the one
/api/v1/quotes uses, whoever places the order: a browser, the API, a strategy.
"""

import math
from decimal import Decimal

from broker.ibulls.api.data import BrokerData
from database.token_db import get_symbol_info
from utils.logging import get_logger
from utils.mpp_slab import get_instrument_type_from_symbol, get_mpp_percentage

logger = get_logger(__name__)


class OrderFieldError(ValueError):
    """An order OpenAlgo will not send to Ibulls as it stands. The message is for the trader."""


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


def _stored_feed_token():
    """The market data token stored with the Ibulls session, or None.

    One user, one broker session per deployment: the unrevoked Ibulls row is
    the session the order's own token comes from. Never a fixed username, and
    never the browser session, which an API or strategy order does not have.
    """
    from database.auth_db import Auth, get_feed_token

    try:
        row = Auth.query.filter_by(broker="ibulls", is_revoked=False).first()
        return get_feed_token(row.name) if row else None
    except Exception:
        logger.exception("Could not read the stored Ibulls feed token")
        return None


def _ltp(symbol: str, exchange: str, auth_token) -> float:
    try:
        return float(BrokerData(auth_token, _stored_feed_token()).get_ltp(symbol, exchange) or 0)
    except Exception as e:
        logger.warning(f"MPP: no LTP for {exchange}:{symbol} ({e})")
        return 0.0


def protected_order_type(data, auth_token=None) -> tuple[str, str]:
    """(orderType, limitPrice) as sent to Ibulls, with MARKET and SL-M protected.

    ``data`` carries the OpenAlgo symbol, exchange, action and pricetype.
    Raises OrderFieldError for an SL-M OpenAlgo cannot price.
    """
    pricetype = (data.get("pricetype") or "").upper()
    if pricetype not in ("MARKET", "SL-M"):
        return map_order_type(pricetype), data.get("price", "0")

    symbol, exchange = data["symbol"], data["exchange"]
    action = data["action"].upper()
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
        logger.info(
            f"MPP: SL-M -> STOPLIMIT for {exchange}:{symbol}, trigger {trigger}, limit {limit}"
        )
        return "STOPLIMIT", str(limit)

    if tick is None:
        logger.warning(f"MPP: no tick size for {exchange}:{symbol}; sending MARKET unconverted")
        return "MARKET", "0"
    ltp = _ltp(symbol, exchange, auth_token)
    if ltp <= 0:
        logger.warning(f"MPP: no LTP for {exchange}:{symbol}; sending MARKET unconverted")
        return "MARKET", "0"
    pct = get_mpp_percentage(ltp, instrument_type) / 100
    # A SELL off the lowest-priced contracts can floor to zero: the smallest
    # price there is, one tick, is still at or below the LTP.
    limit = max(_beyond(ltp, action, pct, tick), tick)
    logger.info(f"MPP: MARKET -> LIMIT for {exchange}:{symbol}, LTP {ltp}, limit {limit}")
    return "LIMIT", str(limit)


def transform_data(data, token, auth_token=None):
    """
    Transforms the new API request structure to the current expected structure.

    MARKET and SL-M are priced with Market Price Protection (see the module
    docstring); raises OrderFieldError for an SL-M that cannot be priced.
    """
    order_type, limit_price = protected_order_type(data, auth_token)

    transformed = {
        "exchangeSegment": map_exchange(data["exchange"]),
        "exchangeInstrumentID": token,
        "productType": map_product_type(data["product"]),
        "orderType": order_type,
        "orderSide": data["action"].upper(),
        "timeInForce": "DAY",
        "disclosedQuantity": data.get("disclosed_quantity", "0"),
        "orderQuantity": data["quantity"],
        "limitPrice": limit_price,
        "stopPrice": data.get("trigger_price", "0"),
        "orderUniqueIdentifier": "openalgo",
    }
    logger.info(f"transformed data: {transformed}")
    return transformed


def transform_modify_order_data(data, token, auth_token=None):
    """Body for a modify. A modify to MARKET or SL-M is priced like a new order;
    ``data`` must still carry the OpenAlgo symbol."""
    order_type, limit_price = protected_order_type(data, auth_token)
    return {
        "appOrderID": data["orderid"],
        "modifiedProductType": map_product_type(data["product"]),
        "modifiedOrderType": order_type,
        "modifiedOrderQuantity": data["quantity"],
        "modifiedDisclosedQuantity": data.get("disclosed_quantity", "0"),
        "modifiedLimitPrice": limit_price,
        "modifiedStopPrice": data.get("trigger_price", "0"),
        "modifiedTimeInForce": "DAY",
        "orderUniqueIdentifier": "openalgo",
    }


def map_exchange(exchange):
    """
    Maps the new exchange to the existing exchange.
    """
    exchange_mapping = {
        "NSE": "NSECM",
        "BSE": "BSECM",
        "MCX": "MCXFO",
        "NFO": "NSEFO",
        "BFO": "BSEFO",
        "CDS": "NSECD",
        "EXCHANGE": "EXCHANGE",
    }
    return exchange_mapping.get(exchange, "EXCHANGE")


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOPLIMIT",
        "SL-M": "STOPMARKET",
    }
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found


def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return product_type_mapping.get(product, "MIS")  # Default to INTRADAY if not found


def reverse_map_product_type(exchange, product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    exchange_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }

    return exchange_mapping.get(product)
