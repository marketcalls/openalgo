#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Angel Broking Parameters https://smartapi.angelbroking.com/docs/Orders

from database.token_db import get_br_symbol

def transform_data(data,token):
    """
    Transforms the new API request structure to the current expected structure.
    """
    symbol = get_br_symbol(data["symbol"],data["exchange"])

    # For MARKET orders, price should be "0"
    price = "0" if data["pricetype"] == "MARKET" else str(data.get("price", "0"))

    # Basic mapping
    transformed = {
        "uid": data["apikey"],
        "actid": data["apikey"],
        "exch": data["exchange"],
        "tsym": symbol,
        "qty": str(data["quantity"]),
        "prc": price,
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
    # For MARKET orders, price should be "0"
    price = "0" if data["pricetype"] == "MARKET" else str(data.get("price", "0"))

    # Build the modify order payload according to Zebu API spec
    modify_payload = {
        "uid": data["apikey"],
        "exch": data["exchange"],
        "norenordno": data["orderid"],
        "tsym": data["symbol"],  # Symbol is required and can't be modified
        "qty": str(data["quantity"]),  # Total quantity (not just pending)
        "prc": price,  # Price (0 for market orders)
        "prctyp": map_order_type(data["pricetype"]),
        "ret": "DAY",  # Retention type
        "dscqty": str(data.get("disclosed_quantity", "0"))
    }

    # Add trigger price only for SL orders
    if data["pricetype"] in ["SL", "SL-M"]:
        modify_payload["trgprc"] = str(data.get("trigger_price", "0"))

    # Add market protection only for market orders
    if data["pricetype"] in ["MARKET", "SL-M"]:
        modify_payload["mkt_protection"] = "0"

    return modify_payload



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

