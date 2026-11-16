"""OpenAlgo order fields -> Nuvama's order bodies (POST/PUT /eq/trade/...).

Body shapes follow the official SDK (APIConnect.PlaceTrade, ModifyTrade,
CancelTrade), which is what the server accepts:

- ``trdSym``: the contract file `tradingsymbol` (the ISIN for equity), stored
  as brsymbol
- ``sym``: the contract file `exchangetoken` (``2885_NSE``), stored as token
- ``exc``: NSE/BSE/NFO/BFO/CDS/MCX/NCDEX
- ``ordTyp``: LIMIT/MARKET/STOP_LIMIT/STOP_MARKET
- ``prdCode``: CNC/MIS/NRML (the SDK maps its product enum to the value the
  login lists per exchange, which for these three is the same text)
- numbers are sent as strings, as the SDK sends them

MARKET and SL-M go out as LIMIT and STOP_LIMIT priced with Market Price
Protection (the shared slabs in utils/mpp_slab.py, rounded to the tick):
MARKET off the LTP, the way broker/flattrade does it, and SL-M off its own
trigger, so the stop's limit is always on the right side of the trigger. A
MARKET without a usable quote has no reference price and goes out as MARKET,
for Nuvama to accept or refuse.
"""

from broker.nuvama.mapping.exchange import nuvama_exchange
from database.token_db import get_br_symbol, get_symbol_info, get_token
from utils.logging import get_logger
from utils.mpp_slab import calculate_protected_price, get_instrument_type_from_symbol

logger = get_logger(__name__)

_ORDER_TYPE = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "STOP_LIMIT",
    "SL-M": "STOP_MARKET",
}

_ORDER_TYPE_REVERSE = {
    "MARKET": "MARKET",
    "MKT": "MARKET",
    "LIMIT": "LIMIT",
    "LMT": "LIMIT",
    "STOP_LIMIT": "SL",
    "SL": "SL",
    "SL-L": "SL",
    "STOP_MARKET": "SL-M",
    "SL-M": "SL-M",
    "SL_M": "SL-M",
}

_PRODUCT = {"CNC": "CNC", "MIS": "MIS", "NRML": "NRML"}

# The SDK's own map of the single-letter codes some exchanges list (api_utils.py).
_PRODUCT_REVERSE = {
    "CNC": "CNC",
    "C": "CNC",
    "MIS": "MIS",
    "I": "MIS",
    "NRML": "NRML",
    "M": "NRML",
}

_SIDE_REVERSE = {"BUY": "BUY", "B": "BUY", "SELL": "SELL", "S": "SELL"}


def map_order_type(pricetype):
    return _ORDER_TYPE.get((pricetype or "").upper())


def reverse_map_order_type(order_type):
    return _ORDER_TYPE_REVERSE.get((order_type or "").upper(), order_type or "")


def map_product_type(product):
    return _PRODUCT.get((product or "").upper())


def reverse_map_product_type(product):
    """Nuvama product -> OpenAlgo, or the broker's value when it has no OpenAlgo twin (MTF, CO, BO)."""
    return _PRODUCT_REVERSE.get((product or "").upper(), product or "")


def reverse_map_side(side):
    return _SIDE_REVERSE.get((side or "").upper(), (side or "").upper())


def _num(value, default="0"):
    if value in (None, ""):
        return default
    return str(value)


class OrderFieldError(ValueError):
    """An order field OpenAlgo cannot express in Nuvama's terms."""


def instrument_keys(symbol, exchange):
    """(trdSym, sym) for an OpenAlgo symbol, from the master contract."""
    trd_sym = get_br_symbol(symbol, exchange)
    stream_sym = get_token(symbol, exchange)
    if not trd_sym or not stream_sym:
        raise OrderFieldError(
            f"{symbol} is not in the Nuvama master contract for {exchange}. "
            "Download the master contract again and check the symbol."
        )
    return trd_sym, stream_sym


def _tick_size(symbol, exchange):
    try:
        info = get_symbol_info(symbol, exchange)
        return getattr(info, "tick_size", None) or None
    except Exception:
        return None


def apply_market_protection(data, auth_token):
    """(ordTyp, lmPrc) for an order, converting MARKET and SL-M with protection.

    - MARKET -> LIMIT at the LTP moved by the MPP slab (as broker/flattrade does).
    - SL-M -> STOP_LIMIT whose limit is the trigger moved by the slab: below
      the trigger for a sell, above it for a buy. It is never priced off the
      LTP: the exchange refuses a stop whose limit is on the wrong side of its
      trigger (16315 "The limit price is worse than the trigger price"), which
      an LTP-based limit is whenever the trigger is away from the market.

    Returns the Nuvama order type and the limit price as a string.
    """
    pricetype = (data.get("pricetype") or "").upper()
    order_type = map_order_type(pricetype)
    if pricetype not in ("MARKET", "SL-M"):
        return order_type, _num(data.get("price"))

    symbol, exchange = data["symbol"], data["exchange"]
    action = data["action"].upper()
    instrument_type = get_instrument_type_from_symbol(symbol, exchange)
    tick_size = _tick_size(symbol, exchange)

    if pricetype == "SL-M":
        trigger = float(data.get("trigger_price") or 0)
        if trigger <= 0:
            raise OrderFieldError("An SL-M order needs a trigger price.")
        # The trigger is on a tick already; without a tick size to round the
        # buffer to, the trigger itself is the limit (still a valid stop).
        price = trigger
        if tick_size:
            price = calculate_protected_price(
                price=trigger,
                action=action,
                symbol=symbol,
                instrument_type=instrument_type,
                tick_size=tick_size,
                exchange=exchange,
            )
        logger.info(
            f"MPP: SL-M -> STOP_LIMIT for {exchange}:{symbol}, trigger {trigger}, limit {price}"
        )
        return "STOP_LIMIT", str(price)

    ltp = 0.0
    if auth_token:
        try:
            from broker.nuvama.api.data import BrokerData

            ltp = float(BrokerData(auth_token).get_quotes(symbol, exchange).get("ltp") or 0)
        except Exception as e:
            logger.warning(f"MPP: no quote for {exchange}:{symbol} ({e})")

    if ltp > 0:
        price = calculate_protected_price(
            price=ltp,
            action=action,
            symbol=symbol,
            instrument_type=instrument_type,
            tick_size=tick_size,
            exchange=exchange,
        )
        logger.info(f"MPP: MARKET -> LIMIT for {exchange}:{symbol} at {price}")
        return "LIMIT", str(price)

    logger.warning(f"MPP: no LTP for {exchange}:{symbol}; sending MARKET unconverted")
    return order_type, "0"


def transform_data(data, auth_token=None):
    """Body for POST trade/placetrade/v1/{userid}/."""
    exchange = data["exchange"]
    order_type = map_order_type(data.get("pricetype"))
    if not order_type:
        raise OrderFieldError(f"Price type {data.get('pricetype')} is not supported.")
    product = map_product_type(data.get("product"))
    if not product:
        raise OrderFieldError(f"Product {data.get('product')} is not supported.")
    trd_sym, stream_sym = instrument_keys(data["symbol"], exchange)
    order_type, price = apply_market_protection(data, auth_token)

    return {
        "trdSym": trd_sym,
        "exc": nuvama_exchange(exchange),
        "action": data["action"].upper(),
        "dur": "DAY",
        "ordTyp": order_type,
        "qty": _num(data.get("quantity")),
        "dscQty": _num(data.get("disclosed_quantity")),
        "sym": stream_sym,
        "mktPro": "",
        "lmPrc": price,
        "trgPrc": _num(data.get("trigger_price")),
        "prdCode": product,
        "posSqr": "N",
        "minQty": "0",
        "ordSrc": "API",
        "vnCode": "",
        "rmk": "",
        "flQty": "0",
    }


def transform_modify_order_data(data, order, auth_token=None):
    """Body for PUT trade/modifytrade/v1/{userid}/.

    ``order`` is the order's row from the order book: it supplies the
    instrument keys and the current quantity the server asks for.
    """
    order_type = map_order_type(data.get("pricetype"))
    if not order_type:
        raise OrderFieldError(f"Price type {data.get('pricetype')} is not supported.")
    product = map_product_type(data.get("product")) or order.get("prdCode")
    side = reverse_map_side(order.get("trsTyp")) or data.get("action", "").upper()
    order_type, price = apply_market_protection({**data, "action": side}, auth_token)

    return {
        "trdSym": order.get("trdSym"),
        "exc": order.get("exc"),
        "action": side,
        "dur": order.get("dur") or "DAY",
        "flQty": "0",
        "ordTyp": order_type,
        "qty": _num(data.get("quantity")),
        "dscQty": _num(data.get("disclosed_quantity")),
        "sym": order.get("sym"),
        "mktPro": "",
        "lmPrc": price,
        "trgPrc": _num(data.get("trigger_price")),
        "prdCode": product,
        "dtDays": "",
        "nstOID": order.get("ordID"),
        "curQty": _num(order.get("ntQty") or order.get("reqQty")),
    }


def transform_cancel_order_data(order):
    """Body for PUT trade/canceltrade/v1/{userid}/, from the order's book row."""
    return {
        "trdSym": order.get("trdSym"),
        "sym": order.get("sym"),
        "action": reverse_map_side(order.get("trsTyp")),
        "nstOID": order.get("ordID"),
        "exc": order.get("exc"),
        "prdCode": order.get("prdCode"),
        "ordTyp": order.get("ordTyp"),
        "curQty": _num(order.get("ntQty") or order.get("reqQty")),
        "flQty": "0",
    }
