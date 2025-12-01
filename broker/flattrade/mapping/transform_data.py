#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Angel Broking Parameters https://smartapi.angelbroking.com/docs/Orders

from database.token_db import get_br_symbol

def transform_data(data,token):
    """
    Transforms the new API request structure to the current expected structure.
    """
    symbol = get_br_symbol(data["symbol"],data["exchange"])
    # Handle special characters in symbol
    if symbol and '&' in symbol:
        symbol = symbol.replace('&', '%26')

    # Basic mapping - ensure all numeric values are strings
    transformed = {
        "uid": data["apikey"],
        "actid": data["apikey"],
        "exch": data["exchange"],
        "tsym": symbol,
        "qty": str(data["quantity"]),
        "prc": str(data.get("price", "0")),
        "trgprc": str(data.get("trigger_price", "0")),
        "dscqty": str(data.get("disclosed_quantity", "0")),
        "prd": map_product_type(data["product"]),
        "trantype": 'B' if data["action"] == "BUY" else 'S',
        "prctyp": map_order_type(data["pricetype"]),
        "mkt_protection": "0",
        "ret": "DAY",
        "ordersource": "API"

    }




    return transformed


def transform_modify_order_data(data, token):
    # Handle special characters in symbol
    symbol = data["symbol"]
    if symbol and '&' in symbol:
        symbol = symbol.replace('&', '%26')

    return {
        "uid": data["apikey"],
        "exch": data["exchange"],
        "norenordno": data["orderid"],
        "prctyp": map_order_type(data["pricetype"]),
        "prc": str(data["price"]),
        "qty": str(data["quantity"]),
        "tsym": symbol,
        "ret": "DAY"
    }



def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "MKT",
        "LIMIT": "LMT",
        "SL": "SL-LMT",
        "SL-M": "SL-MKT"
    }
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found

def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "C",
        "NRML": "M",
        "MIS": "I",
    }
    return product_type_mapping.get(product, "I")  # Default to DELIVERY if not found



def reverse_map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    reverse_product_type_mapping = {
        "C": "CNC",
        "M": "NRML",
        "I": "MIS",
    }
    return reverse_product_type_mapping.get(product)  
