#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Angel Broking Parameters https://smartapi.angelbroking.com/docs/Orders

from database.token_db import get_br_symbol

def transform_data(data, token):
    """
    Transforms OpenAlgo order format to Tradejini API format.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    
    # Basic mapping
    transformed = {
        "symId": f"{symbol}",
        "qty": str(data["quantity"]),
        "side": "buy" if data["action"] == "BUY" else "sell",
        "type": map_order_type(data["pricetype"]),
        "product": map_product_type(data["product"]),
        "limitPrice": str(data.get("price", "0")),
        "trigPrice": str(data.get("trigger_price", "0")),
        "validity": map_validity(data.get("validity", "DAY")),
        "discQty": str(data.get("disclosed_quantity", "0")),
        "amo": data.get("amo", False),
        "mktProt": str(data.get("market_protection", "0")),
        "remarks": data.get("remarks", "")
    }
    
    # Remove optional fields if not set
    for key in ["limitPrice", "trigPrice", "discQty", "mktProt", "remarks"]:
        if transformed[key] == "0" or transformed[key] == "":
            del transformed[key]
    
    return transformed


def transform_modify_order_data(data, token):
    """
    Transforms OpenAlgo modify order format to Tradejini API format.
    
    Args:
        data (dict): OpenAlgo modify order data
        token (str): Broker symbol token
        
    Returns:
        dict: Transformed data for Tradejini API
    """
    # Calculate total quantity (filled + modified)
    filled_qty = int(data.get("filled_quantity", 0))
    modified_qty = int(data["quantity"])
    total_qty = filled_qty + modified_qty
    
    # Get the correct br_symbol from the database
    br_symbol = get_br_symbol(data["symbol"], data["exchange"])
    if not br_symbol:
        raise ValueError(f"Could not find br_symbol for {data['symbol']} on {data['exchange']}")
    
    transformed = {
        "symId": br_symbol,
        "orderId": data["orderid"],
        "qty": total_qty,
        "type": map_order_type(data["pricetype"]),
        "validity": map_validity(data.get("validity", "DAY")),
        "side": data["action"].lower(),
    }
    
    # Add optional fields based on order type
    if data["pricetype"] in ["LIMIT", "SL"]:
        transformed["limitPrice"] = float(data["price"])
    
    if data["pricetype"] in ["SL", "SL-M"]:
        transformed["trigPrice"] = float(data["trigger_price"])
    
    if data.get("disclosed_quantity"):
        transformed["discQty"] = int(data["disclosed_quantity"])
    
    if data.get("market_protection"):
        transformed["mktProt"] = float(data["market_protection"])
    
    return transformed


def map_order_type(pricetype):
    """
    Maps OpenAlgo order types to Tradejini order types.
    """
    order_type_mapping = {
        "MARKET": "market",
        "LIMIT": "limit",
        "SL": "stoplimit",
        "SL-M": "stopmarket"
    }
    return order_type_mapping.get(pricetype, "market")

def map_product_type(product):
    """
    Maps OpenAlgo product types to Tradejini product types.
    """
    product_type_mapping = {
        "CNC": "delivery",
        "NRML": "normal",
        "MIS": "intraday"
    }
    return product_type_mapping.get(product, "intraday")

def map_validity(validity):
    """
    Maps OpenAlgo validity types to Tradejini validity types.
    """
    validity_mapping = {
        "DAY": "day",
        "IOC": "ioc",
        "GTC": "gtc"
    }
    return validity_mapping.get(validity, "day")

def reverse_map_product_type(product):
    """
    Maps Tradejini product types back to OpenAlgo product types.
    """
    reverse_product_type_mapping = {
        "delivery": "CNC",
        "normal": "NRML",
        "intraday": "MIS"
    }
    return reverse_product_type_mapping.get(product)  
