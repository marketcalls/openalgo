# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Upstox Broking Parameters https://upstox.com/developer/api-documentation/orders

from utils.logging import get_logger

logger = get_logger(__name__)


def transform_data(data, token):
    """
    Transforms the new API request structure to the current expected structure.
    """
    order_type = map_order_type(data["pricetype"])

    # Upstox rejects a non-zero price on MARKET/SL-M (UDAPI1040 "Price not
    # required") and a non-zero trigger_price on MARKET/LIMIT, so zero out the
    # field that does not apply to the order type instead of passing it through.
    price = data.get("price", "0") if order_type in ("LIMIT", "SL") else "0"
    trigger_price = data.get("trigger_price", "0") if order_type in ("SL", "SL-M") else "0"

    # Basic mapping
    transformed = {
        "quantity": data["quantity"],
        "product": map_product_type(data["product"]),
        "validity": "DAY",
        "price": price,
        "tag": "openalgo",
        "instrument_token": token,
        "order_type": order_type,
        "transaction_type": data["action"].upper(),
        "disclosed_quantity": data.get("disclosed_quantity", "0"),
        "trigger_price": trigger_price,
        "is_amo": "false",  # Assuming false as default; you might need logic to handle this if it can vary
    }

    # Only carried through when the caller sent a usable value, so Upstox keeps
    # applying its own -1 default for every order that does not ask for one.
    market_protection = map_market_protection(data.get("market_protection"))
    if market_protection is not None:
        transformed["market_protection"] = market_protection

    return transformed


def transform_modify_order_data(data):
    transformed = {
        "quantity": data["quantity"],
        "validity": "DAY",
        "price": data["price"],
        "order_id": data["orderid"],
        "order_type": map_order_type(data["pricetype"]),
        "disclosed_quantity": data.get("disclosed_quantity", "0"),
        "trigger_price": data.get("trigger_price", "0"),
    }

    market_protection = map_market_protection(data.get("market_protection"))
    if market_protection is not None:
        transformed["market_protection"] = market_protection

    return transformed


def map_market_protection(value):
    """
    Validates the optional market_protection percentage for the v3 order APIs.

    Returns None when nothing should be sent: Upstox honours only -1 (automatic)
    or 1..25, the exchange rejects 0, and an absent key is what selects the -1
    default, so an unusable value is dropped instead of failing the order.
    Upstox ignores the field for LIMIT/SL; it applies to MARKET and SL-M only.
    """
    if value is None or value == "":
        return None

    try:
        market_protection = int(value)
    except (TypeError, ValueError):
        logger.warning(f"Invalid market_protection '{value}' received. Omitting it from the order.")
        return None

    if market_protection != -1 and not 1 <= market_protection <= 25:
        logger.warning(
            f"market_protection '{market_protection}' outside -1 or 1..25. Omitting it from the order."
        )
        return None

    return market_protection


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "SL", "SL-M": "SL-M"}
    if pricetype not in order_type_mapping:
        logger.warning(f"Unknown pricetype '{pricetype}' received. Defaulting to 'MARKET'.")
        return "MARKET"
    return order_type_mapping[pricetype]


def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "D",
        "NRML": "D",
        "MIS": "I",
    }
    if product not in product_type_mapping:
        logger.warning(f"Unknown product type '{product}' received. Defaulting to 'I' (Intraday).")
        return "I"
    return product_type_mapping[product]


def reverse_map_product_type(exchange, product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    exchange_mapping_for_d = {
        "NSE": "CNC",
        "BSE": "CNC",
        "NFO": "NRML",
        "BFO": "NRML",
        "MCX": "NRML",
        "CDS": "NRML",
    }

    # Reverse mapping based on product type and exchange
    if product == "D":
        openalgo_product = exchange_mapping_for_d.get(exchange)
        if not openalgo_product:
            logger.warning(
                f"Could not reverse map product type 'D' for unknown exchange '{exchange}'."
            )
        return openalgo_product
    elif product == "I":
        return "MIS"
    else:
        logger.warning(f"Unknown product type '{product}' received for reverse mapping.")
        return None
