#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Zerodha Broking Parameters https://kite.trade/docs/connect/v3/

from database.token_db import get_br_symbol

def transform_data(data):
    """
    Transforms the new API request structure to the current expected structure.
    """
    symbol = get_br_symbol(data['symbol'],data['exchange'])

    # Basic mapping
    transformed = {
        "tradingsymbol" : symbol,
        "exchange" : data['exchange'],
        "transaction_type": data['action'].upper(),
        "order_type": data["pricetype"],
        "quantity": data["quantity"],
        "product": data["product"],
        "price": data.get("price", "0"),
        "trigger_price": data.get("trigger_price", "0"),
        "disclosed_quantity": data.get("disclosed_quantity", "0"),  
        "validity":"DAY",
        "tag": "openalgo",
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

def reverse_map_product_type(exchange,product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    exchange_mapping_for_d = {
        "NSE": "CNC",
        "BSE": "CNC",
        "NFO": "NRML",
        "BFO": "NRML",
        "MCX": "NRML",
        "CDS": "NRML",
    }
    
    # Reverse mapping based on product type and exchange
    if product == 'D':
        return exchange_mapping_for_d.get(exchange)  # Removed default; will return None if not found
    elif product == 'I':
        return "MIS"