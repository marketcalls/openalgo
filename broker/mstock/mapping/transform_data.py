from database.token_db import get_br_symbol

def transform_data(data):
    """
    Transforms the OpenAlgo API request to the mstock API format.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    transformed = {
        "variety": "NORMAL",  # mstock only supports NORMAL variety
        "tradingsymbol": symbol,
        "transactiontype": data["action"].upper(),
        "exchange": data["exchange"],
        "ordertype": map_order_type(data["pricetype"]),
        "producttype": data["product"],
        "duration": "DAY",
        "price": data.get("price", "0"),
        "triggerprice": data.get("trigger_price", "0"),
        "quantity": data["quantity"]
    }
    return transformed

def transform_modify_order_data(data):
    """
    Transforms the OpenAlgo API request to the mstock API format for modifying an order.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    return {
        "orderId": data["orderid"],
        "variety": "NORMAL",
        "tradingsymbol": symbol,
        "transactiontype": data["action"].upper(),
        "exchange": data["exchange"],
        "ordertype": map_order_type(data["pricetype"]),
        "producttype": data["product"],
        "duration": "DAY",
        "price": data["price"],
        "quantity": data["quantity"],
        "triggerprice": data.get("trigger_price", "0"),
    }

def map_order_type(pricetype):
    """
    Maps the OpenAlgo pricetype to the mstock order type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SL-M": "SL-M"
    }
    return order_type_mapping.get(pricetype, "MARKET")
