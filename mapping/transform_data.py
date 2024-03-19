#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Upstox Broking Parameters https://upstox.com/developer/api-documentation/orders

def transform_data(data,token):
    """
    Transforms the new API request structure to the current expected structure.
    """
    # Basic mapping
    transformed = {
        "quantity": data["quantity"],
        "product": map_product_type(data["product"]),
        "validity":"DAY",
        "price": data.get("price", "0"),
        "tag": "string",
        "instrument_token": token,
        "order_type": map_order_type(data["pricetype"]),
        "transaction_type": data['action'].upper(),
        "disclosed_quantity": data.get("disclosed_quantity", "0"),  
        "trigger_price": data.get("trigger_price", "0"),
        "is_amo": "false"  # Assuming false as default; you might need logic to handle this if it can vary
    }


    # Extended mapping for fields that might need conditional logic or additional processing
    transformed["disclosed_quantity"] = data.get("disclosed_quantity", "0")
    transformed["trigger_price"] = data.get("trigger_price", "0")
    
    return transformed


def transform_modify_order_data(data):
    return {
        "quantity": data["quantity"],
        "validity": "DAY",
        "price": data["price"],
        "order_id": data["orderid"],
        "order_type": map_order_type(data["pricetype"]),
        "disclosed_quantity": data.get("disclosed_quantity", "0"),
        "trigger_price": data.get("trigger_price", "0")
    }



def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SL-M": "SL-M"
    }
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found

def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "D",
        "NRML": "D",
        "MIS": "I",
    }
    return product_type_mapping.get(product, "I")  # Default to INTRADAY if not found


