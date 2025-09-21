#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Shoonya Broking Parameters https://shoonya.com/api-documentation

from database.token_db import get_br_symbol

def transform_data(data,token):
    """
    Transforms the new API request structure to the current expected structure.
    """
    userid = data["apikey"]
    userid = userid[:-2] 
    symbol = get_br_symbol(data["symbol"],data["exchange"])
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
        "trantype": 'B' if data["action"] == "BUY" else 'S',
        "prctyp": map_order_type(data["pricetype"]),
        "mkt_protection": "0", 
        "ret": "DAY",
        "ordersource": "API"
        
    }


    
    
    return transformed


def transform_modify_order_data(data, token):
    return {
        "exch": data["exchange"],
        "norenordno": data["orderid"],
        "prctyp": map_order_type(data["pricetype"]),
        "prc": str(data["price"]),  # Ensure price is string
        "qty": str(data["quantity"]),  # Ensure quantity is string
        "tsym": data["symbol"],
        "ret": "DAY",
        "mkt_protection": "0",
        "trdprc": str(data.get("trigger_price", "0")),  # Ensure trigger_price is string
        "dscqty": str(data.get("disclosed_quantity", "0")),  # Ensure disclosed_quantity is string
        "uid": data["apikey"]
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

