# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Shoonya Broking Parameters https://shoonya.com/api-documentation

from database.token_db import get_br_symbol


def transform_data(data, token):
    """Transform the OpenAlgo API request to Shoonya's expected order structure.

    Args:
        data (dict): OpenAlgo order data including 'apikey', 'symbol',
            'exchange', 'quantity', 'price', 'product', 'action', etc.
        token (str): Security token for the symbol (unused in Shoonya's API).

    Returns:
        dict: Transformed payload for placing an order in Shoonya API.
    """
    userid = data["apikey"]
    userid = userid[:-2]
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    # Basic mapping
    transformed = {
        "uid": userid,
        "actid": userid,
        "exch": data["exchange"],
        "tsym": symbol,
        "qty": str(data["quantity"]),  # Convert to string for Shoonya API
        "prc": str(data.get("price", "0")),  # Ensure price is string
        "trgprc": str(data.get("trigger_price", "0")),  # Ensure trigger_price is string
        "dscqty": str(data.get("disclosed_quantity", "0")),  # Ensure disclosed_quantity is string
        "prd": map_product_type(data["product"]),
        "trantype": "B" if data["action"] == "BUY" else "S",
        "prctyp": map_order_type(data["pricetype"]),
        "mkt_protection": "0",
        "ret": "DAY",
        "ordersource": "API",
    }

    return transformed


def transform_modify_order_data(data, token):
    """Transform the OpenAlgo modify order request to Shoonya's expected structure.

    Args:
        data (dict): OpenAlgo modify order data including 'apikey',
            'orderid', 'symbol', 'exchange', 'quantity', 'price', etc.
        token (str): Security token for the symbol.

    Returns:
        dict: Transformed payload for modifying an order in Shoonya API.
    """
    return {
        "exch": data["exchange"],
        "norenordno": data["orderid"],
        "prctyp": map_order_type(data["pricetype"]),
        "prc": str(data["price"]),  # Ensure price is string
        "qty": str(data["quantity"]),  # Ensure quantity is string
        "tsym": data["symbol"],
        "ret": "DAY",
        "mkt_protection": "0",
        "trgprc": str(data.get("trigger_price") or 0),  # Fixed: was trdprc, should be trgprc
        "dscqty": str(data.get("disclosed_quantity") or 0),  # Ensure disclosed_quantity is string
        "uid": data["apikey"],
    }


def map_order_type(pricetype):
    """Map an OpenAlgo price type to Shoonya's order type code.

    Args:
        pricetype (str): OpenAlgo price type ('MARKET', 'LIMIT', 'SL', 'SL-M').

    Returns:
        str: Shoonya order type ('MKT', 'LMT', 'SL-LMT', 'SL-MKT'). Defaults to 'MKT'.
    """
    order_type_mapping = {"MARKET": "MKT", "LIMIT": "LMT", "SL": "SL-LMT", "SL-M": "SL-MKT"}
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found


def map_product_type(product):
    """Map an OpenAlgo product type to Shoonya's product type.

    Args:
        product (str): OpenAlgo product type ('CNC', 'NRML', 'MIS').

    Returns:
        str: Shoonya product type ('C', 'M', 'I'). Defaults to 'I' (Intraday).
    """
    product_type_mapping = {
        "CNC": "C",
        "NRML": "M",
        "MIS": "I",
    }
    return product_type_mapping.get(product, "I")  # Default to DELIVERY if not found


def reverse_map_product_type(product):
    """Map a Shoonya product type back to OpenAlgo's product type.

    Args:
        product (str): Shoonya product type ('C', 'M', 'I').

    Returns:
        str or None: OpenAlgo product type ('CNC', 'NRML', 'MIS').
    """
    reverse_product_type_mapping = {
        "C": "CNC",
        "M": "NRML",
        "I": "MIS",
    }
    return reverse_product_type_mapping.get(product)
