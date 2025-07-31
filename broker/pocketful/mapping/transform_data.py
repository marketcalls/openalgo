#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Pocketful API Parameters https://api.pocketful.in/docs/

from database.token_db import get_br_symbol, get_token

def transform_data(data, client_id=None):
    """
    Transforms OpenAlgo order format to Pocketful order format.
    
    Args:
        data: OpenAlgo order data dictionary
        client_id: Client ID to use for the order, if available
    """
    # Get broker symbol for the order
    symbol = get_br_symbol(data['symbol'], data['exchange'])
    
    # Get the numeric token for the symbol
    token = get_token(data['symbol'], data['exchange'])
    
    # Map order type
    order_type = map_order_type(data['pricetype'])
    
    # Map order side (BUY/SELL)
    order_side = data['action'].upper()
    
    # Map product type
    product = map_product_type(data['product'])
    
    # Basic mapping
    transformed = {
        "exchange": data['exchange'],
        "instrument_token": token,  # Pocketful uses numeric instrument_token
        "client_id": client_id,  # Use the provided client_id
        "order_type": order_type,
        "amo": False,  # Default to regular order
        "price": float(data.get("price", "0")),
        "quantity": int(data["quantity"]),
        "disclosed_quantity": int(data.get("disclosed_quantity", "0")),
        "validity": "DAY",
        "product": product,
        "order_side": order_side,
        "device": "WEB",  # Default to WEB
        "user_order_id": 1,  # Default value
        "trigger_price": float(data.get("trigger_price", "0")),
        "execution_type": "REGULAR"  # Default to regular order
    }


    # Extended mapping for fields that might need conditional logic or additional processing
    transformed["disclosed_quantity"] = int(data.get("disclosed_quantity", "0"))
    transformed["trigger_price"] = float(data.get("trigger_price", "0"))
    
    return transformed


def transform_modify_order_data(data, client_id=None):
    """
    Transforms OpenAlgo order modification format to Pocketful order format.
    
    Args:
        data: OpenAlgo order data dictionary
        client_id: Client ID to use for the order, if available
    """
    # Get broker symbol for the order
    symbol = get_br_symbol(data['symbol'], data['exchange'])
    
    # Get the numeric token for the symbol
    token = get_token(data['symbol'], data['exchange'])
    
    # Map order type
    order_type = map_order_type(data['pricetype'])
    
    # Map order side (BUY/SELL)
    order_side = data['action'].upper()
    
    # Map product type
    product = map_product_type(data['product'])
    
    # Create the transformed data dictionary with all required fields for Pocketful API
    return {
        "exchange": data['exchange'],
        "instrument_token": token,
        "client_id": client_id,
        "order_type": order_type,
        "price": float(data.get("price", "0")),
        "quantity": int(data["quantity"]),
        "disclosed_quantity": int(data.get("disclosed_quantity", "0")),
        "validity": "DAY",
        "product": product,
        "order_side": order_side,
        "device": "WEB",
        "user_order_id": 1,
        "trigger_price": float(data.get("trigger_price", "0")),
        "oms_order_id": data.get("orderid", ""),  # This is the ID needed to identify which order to modify
        "execution_type": "REGULAR"
    }


def map_order_type(pricetype):
    """
    Maps OpenAlgo pricetype to Pocketful order type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SL-M": "SLM"  # Pocketful uses SLM instead of SL-M
    }
    return order_type_mapping.get(pricetype.upper(), "MARKET")  # Default to MARKET if not found

def map_product_type(product):
    """
    Maps OpenAlgo product type to Pocketful product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS"
    }
    return product_type_mapping.get(product.upper(), "MIS")  # Default to MIS if not found

def reverse_map_product_type(exchange,product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    exchange_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
   
    return exchange_mapping.get(product)
    