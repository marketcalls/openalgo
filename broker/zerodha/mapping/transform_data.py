"""Zerodha (Kite) broker order data transformation module.

Maps OpenAlgo API request parameters to Zerodha's Kite Connect API format
for order placement and modification. Handles symbol resolution, order type
mapping, and product type mapping.

See:
    - OpenAlgo API docs: https://openalgo.in/docs
    - Kite Connect docs: https://kite.trade/docs/connect/v3/
"""

from database.token_db import get_br_symbol


def transform_data(data: dict) -> dict:
    """
    Transforms the OpenAlgo API request structure to the Zerodha expected structure.

    Args:
        data (dict): The OpenAlgo order data dictionary.

    Returns:
        dict: The mapped Zerodha order parameters.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    # Basic mapping
    transformed = {
        "tradingsymbol": symbol,
        "exchange": data["exchange"],
        "transaction_type": data["action"].upper(),
        "order_type": data["pricetype"],
        "quantity": data["quantity"],
        "product": data["product"],
        "price": data.get("price", "0"),
        "trigger_price": data.get("trigger_price", "0"),
        "disclosed_quantity": data.get("disclosed_quantity", "0"),
        "validity": "DAY",
        "market_protection": "-1",
        "tag": "openalgo",
    }

    # Extended mapping for fields that might need conditional logic or additional processing
    transformed["disclosed_quantity"] = data.get("disclosed_quantity", "0")
    transformed["trigger_price"] = data.get("trigger_price", "0")

    return transformed


def transform_modify_order_data(data: dict) -> dict:
    """Transforms modify order data to Zerodha format.

    Args:
        data (dict): The OpenAlgo modify order parameters.

    Returns:
        dict: The mapped Zerodha modify order parameters.
    """
    return {
        "order_type": map_order_type(data["pricetype"]),
        "quantity": data["quantity"],
        "price": data["price"],
        "trigger_price": data.get("trigger_price", "0"),
        "disclosed_quantity": data.get("disclosed_quantity", "0"),
        "validity": "DAY",
    }


def map_order_type(pricetype: str) -> str:
    """
    Maps the OpenAlgo pricetype to the Zerodha order type.

    Args:
        pricetype (str): The OpenAlgo order price type.

    Returns:
        str: The corresponding Zerodha order type.
    """
    order_type_mapping = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "SL", "SL-M": "SL-M"}
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found


def map_product_type(product: str) -> str:
    """
    Maps the OpenAlgo product type to the Zerodha product type.

    Args:
        product (str): The OpenAlgo product type.

    Returns:
        str: The corresponding Zerodha product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return product_type_mapping.get(product, "MIS")  # Default to INTRADAY if not found


def reverse_map_product_type(exchange: str, product: str) -> str:
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.

    Args:
        exchange (str): The exchange segment.
        product (str): The broker product type.

    Returns:
        str: The corresponding OpenAlgo product type.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    exchange_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }

    return exchange_mapping.get(product)
