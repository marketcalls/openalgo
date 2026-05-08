# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Kotak Neo API Parameters

from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def _fmt_price(value):
    """Kotak rejects '0.0' on numeric fields — emit '0' for zero, otherwise stringified value."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value) if value is not None else "0"
    if f == 0:
        return "0"
    return str(value)


def transform_data(data, token):
    """
    Transforms the new API request structure to the current expected structure.
    ALL values must be strings for Kotak API.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    order_type = map_order_type(data["pricetype"])
    action = data["action"].upper()

    transformed = {
        "am": "NO",
        "dq": str(data.get("disclosed_quantity", "0")),
        "es": reverse_map_exchange(data["exchange"]),
        "mp": "0",
        "pc": data.get("product", "MIS"),
        "pf": "N",
        "pr": _fmt_price(data.get("price", 0)),
        "pt": order_type,
        "qt": str(data["quantity"]),
        "rt": "DAY",
        "tp": _fmt_price(data.get("trigger_price", 0)),
        "ts": symbol,
        "tt": "B" if action == "BUY" else ("S" if action == "SELL" else "None"),
    }

    logger.info(f"Transformed order data: {transformed}")
    return transformed


def transform_modify_order_data(data, token):
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    transformed = {
        "tk": str(token),
        "dq": str(data.get("disclosed_quantity", "0")),
        "es": reverse_map_exchange(data["exchange"]),
        "mp": "0",
        "dd": "NA",
        "vd": "DAY",
        "pc": data.get("product", "MIS"),
        "pr": _fmt_price(data.get("price", 0)),
        "pt": map_order_type(data["pricetype"]),
        "qt": str(data["quantity"]),
        "tp": _fmt_price(data.get("trigger_price", 0)),
        "ts": symbol,
        "no": str(data["orderid"]),
        "tt": "B" if data["action"] == "BUY" else ("S" if data["action"] == "SELL" else "None"),
    }
    return transformed


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {"MARKET": "MKT", "LIMIT": "L", "SL": "SL", "SL-M": "SL-M"}
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
    return product_type_mapping.get(product)  # Default to DELIVERY if not found


def map_variety(pricetype):
    """
    Maps the pricetype to the existing order variety.
    """
    variety_mapping = {"MARKET": "NORMAL", "LIMIT": "NORMAL", "SL": "STOPLOSS", "SL-M": "STOPLOSS"}
    return variety_mapping.get(pricetype, "NORMAL")  # Default to DELIVERY if not found


def map_exchange(brexchange):
    """
    Maps the Broker Exchange to the OpenAlgo Exchange.
    """

    exchange_mapping = {
        "nse_cm": "NSE",
        "bse_cm": "BSE",
        "cde_fo": "CDS",
        "nse_fo": "NFO",
        "bse_fo": "BFO",
        "bcs_fo": "BCD",
        "mcx_fo": "MCX",
    }
    return exchange_mapping.get(brexchange)


def reverse_map_exchange(exchange):
    """
    Maps the Broker Exchange to the OpenAlgo Exchange.
    """

    exchange_mapping = {
        "NSE": "nse_cm",
        "BSE": "bse_cm",
        "CDS": "cde_fo",
        "NFO": "nse_fo",
        "BFO": "bse_fo",
        "BCD": "bcs_fo",
        "MCX": "mcx_fo",
    }
    return exchange_mapping.get(exchange)


def reverse_map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    reverse_product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return reverse_product_type_mapping.get(product)
