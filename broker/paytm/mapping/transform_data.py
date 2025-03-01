#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Paytm Broking Parameters https://developer.paytmmoney.com/docs/api/login

from database.token_db import get_br_symbol

def transform_data(data):
    """
    Transforms the OpenAlgo API request structure to Paytm v2 API structure.
    """
    symbol = get_br_symbol(data['symbol'],data['exchange'])

    # Basic mapping
    transformed = {
        "security_id" : symbol,
        "exchange" : data['exchange'],
        "txn_type": data['action'].upper(),
        "order_type": data["pricetype"],
        "quantity": data["quantity"],
        "product": data["product"],
        "price": data.get("price", "0"),
        "trigger_price": data.get("trigger_price", "0"),
        #"disclosed_quantity": data.get("disclosed_quantity", "0"),  
        "validity":"DAY",
        "tag": "openalgo",
    }


    # Extended mapping for fields that might need conditional logic or additional processing
    transformed["disclosed_quantity"] = data.get("disclosed_quantity", "0")
    transformed["trigger_price"] = data.get("trigger_price", "0")
    
    return transformed


def transform_modify_order_data(data):
    return {
        "order_type": map_order_type(data["pricetype"]),
        "quantity": data["quantity"],
        "price": data["price"],
        "trigger_price": data.get("trigger_price", "0"),
        "disclosed_quantity": data.get("disclosed_quantity", "0"),
        "validity": "DAY"      
    }



def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MKT": "MARKET",
        "LMT": "LIMIT",
        "SL": "STOP_LOSS",
        "SLM": "STOP_LOSS_MARKET"
    }
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found

def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "C": "CNC",
        "M": "MARGIN",
        "I": "MIS",
    }
    return product_type_mapping.get(product, "MIS")  # Default to INTRADAY if not found

def reverse_map_product_type(exchange,product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    exchange_mapping = {
        "CNC": "C",
        "MARGIN": "M",
        "MIS": "I"
    }
   
    return exchange_mapping.get(product)
    