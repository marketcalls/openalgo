# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Tradejini API Parameters https://api.tradejini.com/v2

from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_data(data, token):
    """
    Transforms OpenAlgo order format to Tradejini API format.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    # Basic mapping
    order_type = map_order_type(data["pricetype"])

    transformed = {
        "symId": f"{symbol}",
        "qty": str(data["quantity"]),
        "side": "buy" if data["action"] == "BUY" else "sell",
        "type": order_type,
        "product": map_product_type(data["product"]),
        "limitPrice": str(data.get("price", "0")),
        "trigPrice": str(data.get("trigger_price", "0")),
        "validity": map_validity(data.get("validity", "DAY"), data.get("exchange")),
        "discQty": str(data.get("disclosed_quantity", "0")),
        # Remarks are capped at 10 characters - anything longer is stripped out
        # by the broker, so truncate here to keep the tag readable.
        "remarks": str(data.get("remarks", ""))[:10],
    }

    # 'amo' is optional; only send it when the order really is an AMO
    if data.get("amo"):
        transformed["amo"] = "true"

    # Add market protection percentage for market and stopmarket orders
    if order_type in ("market", "stopmarket"):
        transformed["mktProt"] = "2"

    # Remove optional fields if not set
    for key in ["limitPrice", "trigPrice", "discQty", "remarks"]:
        if transformed.get(key, "") in ("0", ""):
            del transformed[key]

    return transformed


def transform_modify_order_data(data, token):
    """
    Transforms OpenAlgo modify order format to Tradejini API format.

    Args:
        data (dict): OpenAlgo modify order data
        token (str): Broker symbol token

    Returns:
        dict: Transformed data for Tradejini API
    """
    # Calculate total quantity (filled + modified)
    filled_qty = int(data.get("filled_quantity", 0))
    modified_qty = int(data["quantity"])
    total_qty = filled_qty + modified_qty

    # Get the correct br_symbol from the database
    br_symbol = get_br_symbol(data["symbol"], data["exchange"])
    if not br_symbol:
        raise ValueError(f"Could not find br_symbol for {data['symbol']} on {data['exchange']}")

    transformed = {
        "symId": br_symbol,
        "orderId": data["orderid"],
        "qty": total_qty,
        "type": map_order_type(data["pricetype"]),
        "validity": map_validity(data.get("validity", "DAY"), data.get("exchange")),
        "side": data["action"].lower(),
    }

    # Add optional fields based on order type
    if data["pricetype"] in ["LIMIT", "SL"]:
        transformed["limitPrice"] = float(data["price"])

    if data["pricetype"] in ["SL", "SL-M"]:
        transformed["trigPrice"] = float(data["trigger_price"])

    if data.get("disclosed_quantity"):
        transformed["discQty"] = int(data["disclosed_quantity"])

    if data.get("market_protection"):
        transformed["mktProt"] = float(data["market_protection"])

    return transformed


def map_order_type(pricetype):
    """
    Maps OpenAlgo order types to Tradejini order types.
    """
    order_type_mapping = {
        "MARKET": "market",
        "LIMIT": "limit",
        "SL": "stoplimit",
        "SL-M": "stopmarket",
    }
    return order_type_mapping.get(pricetype, "market")


def map_product_type(product):
    """
    Maps OpenAlgo product types to Tradejini product types.
    """
    product_type_mapping = {"CNC": "delivery", "NRML": "normal", "MIS": "intraday"}
    return product_type_mapping.get(product, "intraday")


# Exchanges on which the API accepts 'eos' (End-of-Session) validity.
BSE_EXCHANGES = {"BSE", "BFO", "BCD"}


def map_validity(validity, exchange=None):
    """
    Maps OpenAlgo validity types to Tradejini validity types.

    Args:
        validity: OpenAlgo validity - DAY, IOC, GTC or EOS.
        exchange: OpenAlgo exchange code. 'eos' (End-of-Session) is accepted for
            BSE scrips only, so it falls back to 'day' anywhere else rather than
            being sent and rejected by the exchange.
    """
    validity_mapping = {"DAY": "day", "IOC": "ioc", "GTC": "gtc", "EOS": "eos"}
    mapped = validity_mapping.get(str(validity).upper(), "day")

    if mapped == "eos" and str(exchange).upper() not in BSE_EXCHANGES:
        logger.warning(f"EOS validity is BSE-only; falling back to DAY for exchange {exchange}")
        return "day"

    return mapped


def reverse_map_product_type(product):
    """
    Maps Tradejini product types back to OpenAlgo product types.

    Tradejini products are 'delivery', 'intraday', 'normal', 'cover' and
    'bracket' (order book, trade book and position book all use this set).
    """
    reverse_product_type_mapping = {
        "delivery": "CNC",
        "normal": "NRML",
        "intraday": "MIS",
        "cover": "CO",
        "bracket": "BO",
        # Legacy / long-form spellings seen on some responses
        "margin": "NRML",
        "coverorder": "CO",
        "bracketorder": "BO",
    }
    return reverse_product_type_mapping.get(str(product).lower())


def reverse_map_order_type(order_type):
    """
    Maps Tradejini price types back to OpenAlgo price types.

    Tradejini uses 'limit', 'market', 'stoplimit' and 'stopmarket'.
    """
    reverse_order_type_mapping = {
        "market": "MARKET",
        "limit": "LIMIT",
        "stoplimit": "SL",
        "stopmarket": "SL-M",
    }
    return reverse_order_type_mapping.get(str(order_type).lower(), str(order_type).upper())
