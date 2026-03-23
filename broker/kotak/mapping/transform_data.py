# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Kotak Neo API Parameters

from database.token_db import get_br_symbol


def transform_data(data, token):
    """Transform an OpenAlgo order request to Kotak Neo API format.

    All values in the returned dict are strings, as required by the
    Kotak Neo API.

    Args:
        data: OpenAlgo order data with keys 'symbol', 'exchange',
            'action', 'quantity', 'pricetype', 'product', and optional
            'price', 'trigger_price', 'disclosed_quantity'.
        token: Instrument token (unused, kept for API consistency).

    Returns:
        dict: Transformed order payload for Kotak Neo API.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    # Basic mapping - ALL values must be strings for Kotak API
    transformed = {
        "am": "NO",
        "dq": str(data.get("disclosed_quantity", "0")),
        "bc": "1",
        "es": reverse_map_exchange(data["exchange"]),
        "mp": "0",
        "pc": data.get("product", "MIS"),
        "pf": "N",
        "pr": str(data.get("price", "0")),
        "pt": map_order_type(data["pricetype"]),
        "qt": str(data["quantity"]),
        "rt": "DAY",
        "tp": str(data.get("trigger_price", "0")),
        "ts": symbol,
        "tt": "B" if data["action"] == "BUY" else ("S" if data["action"] == "SELL" else "None"),
    }
    return transformed


def transform_modify_order_data(data, token):
    """Transform an OpenAlgo modify-order request to Kotak Neo format.

    Includes the order number ('no') field required for modification.
    All values are strings as required by the Kotak Neo API.

    Args:
        data: Modification data including 'orderid', 'symbol', 'exchange',
            'quantity', 'price', 'pricetype', 'product', and 'action'.
        token: Instrument token for the symbol.

    Returns:
        dict: Transformed modify-order payload for Kotak Neo API.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    # Basic mapping - ALL values must be strings for Kotak API
    transformed = {
        "tk": str(token),
        "dq": str(data.get("disclosed_quantity", "0")),
        "es": reverse_map_exchange(data["exchange"]),
        "mp": "0",
        "dd": "NA",
        "vd": "DAY",
        "pc": data.get("product", "MIS"),
        "pr": str(data.get("price", "0")),
        "pt": map_order_type(data["pricetype"]),
        "qt": str(data["quantity"]),
        "tp": str(data.get("trigger_price", "0")),
        "ts": symbol,
        "no": str(data["orderid"]),
        "tt": "B" if data["action"] == "BUY" else ("S" if data["action"] == "SELL" else "None"),
    }
    return transformed


def map_order_type(pricetype):
    """Map an OpenAlgo price type to the Kotak order type code.

    Args:
        pricetype: OpenAlgo price type ('MARKET', 'LIMIT', 'SL', 'SL-M').

    Returns:
        str: Kotak order type code ('MKT', 'L', 'SL', 'SL-M').
            Defaults to 'MARKET' if not found.
    """
    order_type_mapping = {"MARKET": "MKT", "LIMIT": "L", "SL": "SL", "SL-M": "SL-M"}
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found


def map_product_type(product):
    """Map an OpenAlgo product type to the Kotak product type.

    Args:
        product: OpenAlgo product type ('CNC', 'NRML', 'MIS').

    Returns:
        str or None: Corresponding Kotak product type, or None if
            not found.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return product_type_mapping.get(product)  # Default to DELIVERY if not found


def map_variety(pricetype):
    """Map an OpenAlgo price type to the Kotak order variety.

    Args:
        pricetype: OpenAlgo price type ('MARKET', 'LIMIT', 'SL', 'SL-M').

    Returns:
        str: Kotak order variety ('NORMAL' or 'STOPLOSS').
            Defaults to 'NORMAL'.
    """
    variety_mapping = {"MARKET": "NORMAL", "LIMIT": "NORMAL", "SL": "STOPLOSS", "SL-M": "STOPLOSS"}
    return variety_mapping.get(pricetype, "NORMAL")  # Default to DELIVERY if not found


def map_exchange(brexchange):
    """Map a Kotak broker exchange code to the OpenAlgo exchange name.

    Args:
        brexchange: Kotak exchange segment code (e.g., 'nse_cm', 'nse_fo').

    Returns:
        str or None: OpenAlgo exchange name (e.g., 'NSE', 'NFO'),
            or None if not found.
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
    """Map an OpenAlgo exchange name to the Kotak broker exchange code.

    Args:
        exchange: OpenAlgo exchange name (e.g., 'NSE', 'NFO').

    Returns:
        str or None: Kotak exchange segment code (e.g., 'nse_cm',
            'nse_fo'), or None if not found.
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
    """Map a Kotak product type to the OpenAlgo product type.

    Args:
        product: Kotak product type ('CNC', 'NRML', 'MIS').

    Returns:
        str or None: OpenAlgo product type, or None if not found.
    """
    reverse_product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return reverse_product_type_mapping.get(product)
