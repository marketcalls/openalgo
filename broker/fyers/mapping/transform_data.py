# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Fyers Broking Parameters

from database.token_db import get_br_symbol, get_symbol_info
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_data(data):
    """
    Transforms the OpenAlgo Platform API request structure to the format expected by the Fyers API.

    Raises:
        LotQuantityError: an MCX or CDS quantity that is not a whole number of lots.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    # Fyers counts MCX and CDS in lots (see to_fyers_qty below).
    quantity = to_fyers_qty(int(data["quantity"]), data["symbol"], data["exchange"])
    price = float(data.get("price", 0))
    trigger_price = float(data.get("trigger_price", 0))
    disclosed_quantity = to_fyers_qty(
        int(data.get("disclosed_quantity", 0)),
        data["symbol"],
        data["exchange"],
        field="Disclosed quantity",
    )

    transformed = {
        "symbol": symbol,
        "qty": quantity,
        "type": map_order_type(data["pricetype"]),
        "side": map_action(data["action"]),
        "productType": map_product_type(data["product"]),
        "limitPrice": price,
        "stopPrice": trigger_price,
        "validity": "DAY",
        "disclosedQty": disclosed_quantity,
        "offlineOrder": False,
        "stopLoss": 0,
        "takeProfit": 0,
        "orderTag": "openalgo",
    }

    return transformed


def transform_modify_order_data(data):
    """
    Transforms the order modification data to the format expected by Fyers API.
    Handles empty strings and None values for price and trigger_price.

    Raises:
        LotQuantityError: an MCX or CDS quantity that is not a whole number of lots.
    """
    order_id = data.get("orderid", "N/A")
    try:
        quantity = int(data.get("quantity", 0))
    except (ValueError, TypeError) as e:
        logger.warning(
            f"Could not parse quantity for order modification {order_id}. Defaulting to 0. Error: {e}"
        )
        quantity = 0
    # Fyers counts MCX and CDS in lots (see to_fyers_qty below).
    quantity = to_fyers_qty(quantity, data.get("symbol"), data.get("exchange"))

    try:
        price = float(data.get("price", 0)) if data.get("price") else 0.0
    except (ValueError, TypeError) as e:
        logger.warning(
            f"Could not parse price for order modification {order_id}. Defaulting to 0.0. Error: {e}"
        )
        price = 0.0

    try:
        trigger_price = float(data.get("trigger_price", 0)) if data.get("trigger_price") else 0.0
    except (ValueError, TypeError) as e:
        logger.warning(
            f"Could not parse trigger_price for order modification {order_id}. Defaulting to 0.0. Error: {e}"
        )
        trigger_price = 0.0

    return {
        "id": data["orderid"],
        "qty": quantity,
        "type": map_order_type(data.get("pricetype", "")),
        "limitPrice": price,
        "stopPrice": trigger_price,
    }


def map_order_type(pricetype):
    """
    Maps the OpenAlgo pricetype to the Fyers order type.
    """
    order_type_mapping = {"MARKET": 2, "LIMIT": 1, "SL": 4, "SL-M": 3}
    order_type = order_type_mapping.get(pricetype)
    if order_type is None:
        logger.warning(f"Unknown pricetype '{pricetype}' received. Defaulting to MARKET (2).")
        return 2  # Default to MARKET
    return order_type


def map_action(action):
    """
    Maps the OpenAlgo action to the Fyers side.
    """
    action_mapping = {"BUY": 1, "SELL": -1}
    side = action_mapping.get(action)
    if side is None:
        logger.warning(f"Unknown action '{action}' received. Cannot map to a side.")
    return side


def map_product_type(product):
    """
    Maps the OpenAlgo product type to the Fyers product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "MARGIN",
        "MIS": "INTRADAY",
        "CO": "CO",
        "BO": "BO",
    }
    fyers_product = product_type_mapping.get(product)
    if fyers_product is None:
        logger.warning(f"Unknown product type '{product}' received. Defaulting to INTRADAY.")
        return "INTRADAY"  # Default to INTRADAY
    return fyers_product


def reverse_map_product_type(product):
    """
    Reverse maps the Fyers product type to the OpenAlgo product type.
    """
    reverse_product_mapping = {
        "CNC": "CNC",
        "MARGIN": "NRML",
        "INTRADAY": "MIS",
        "CO": "CO",
        "BO": "BO",
    }
    oa_product = reverse_product_mapping.get(product)
    if oa_product is None:
        logger.warning(
            f"Unknown Fyers product type '{product}' received. Cannot map to OpenAlgo product type."
        )
    return oa_product


# MCX and CDS quantities: OpenAlgo units in, Fyers lots out.
#
# Fyers counts MCX and CDS order quantity in lots: every row of its MCX and CDS
# symbol masters has minLotSize 1, with the units in one lot as qtyMultiplier
# (CRUDEOILM 10, CRUDEOIL 100, USDINR 1000). The master contract stores that
# qtyMultiplier as symtoken.lotsize, so OpenAlgo's quantity on these segments is
# units, as on NFO and on every other broker (broker/zerodha/mapping/
# mcx_contract_size.py does the same translation for Kite). One lot of CRUDEOILM
# is quantity 10, and Fyers must receive it as qty 1.
#
# The factor is the symtoken.lotsize of the exact contract, the number the
# quantity was built from. Every call site is a payload being built for Fyers or
# a value just read back from it: converting twice sends a 10x order or a zero one.

#: OpenAlgo exchanges whose Fyers ``qty`` counts lots rather than units.
LOT_DENOMINATED_EXCHANGES = frozenset({"MCX", "CDS"})


class LotQuantityError(ValueError):
    """A quantity that is not a whole number of lots, or a contract with no lot size."""


def is_lot_denominated(exchange):
    """
    True for the OpenAlgo exchanges whose Fyers quantity is lots. A book row whose
    symbol did not map keeps Fyers' numeric exchange code, which is not one of them.
    """
    return isinstance(exchange, str) and exchange.strip().upper() in LOT_DENOMINATED_EXCHANGES


def lot_size(symbol, exchange):
    """
    Returns symtoken.lotsize of the contract, or 0 when the master contract has none.
    """
    if not symbol or not isinstance(exchange, str):
        return 0
    try:
        info = get_symbol_info(symbol, exchange.strip().upper())
        size = int(float(getattr(info, "lotsize", 0) or 0))
    except Exception:
        # A failed lookup must not break a book; to_fyers_qty refuses on 0.
        logger.exception(f"Lot size lookup failed for {exchange}:{symbol}")
        return 0
    return max(size, 0)


def to_fyers_qty(quantity, symbol, exchange, field="Quantity"):
    """
    OpenAlgo units -> the quantity Fyers expects: lots on MCX and CDS, unchanged
    elsewhere. Outbound only.

    ``field`` names the value in an error, since an order carries more than one
    quantity.

    Raises:
        LotQuantityError: the quantity is not a whole number of lots, or the
            contract has no lot size. Refused rather than rounded: rounding 15
            CRUDEOILM down to one lot silently cuts the order, and up doubles it.
    """
    qty = int(quantity)
    if qty == 0 or not is_lot_denominated(exchange):
        return qty
    size = lot_size(symbol, exchange)
    if size == 0:
        raise LotQuantityError(
            f"Cannot size {symbol} on {exchange}: the master contract has no lot size "
            f"for it. Download the master contract again, then retry."
        )
    lots, remainder = divmod(abs(qty), size)
    if remainder:
        raise LotQuantityError(
            f"{field} must be in multiples of lot size {size} for {symbol}, got {abs(qty)}"
        )
    return -lots if qty < 0 else lots


def from_fyers_qty(quantity, symbol, exchange):
    """
    Fyers' quantity -> OpenAlgo units: lots times the lot size on MCX and CDS,
    unchanged elsewhere. Inbound only.

    A value that is not a number, or a contract with no lot size, is returned as
    Fyers sent it (and logged), so one odd row cannot break a book.
    """
    if not is_lot_denominated(exchange):
        return quantity
    size = lot_size(symbol, exchange)
    if size == 0:
        logger.warning(f"No lot size for {exchange}:{symbol}; its quantity is in Fyers' lots")
        return quantity
    try:
        return int(float(quantity)) * size
    except (TypeError, ValueError):
        return quantity
