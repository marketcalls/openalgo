#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Compositedge Broking Parameters https://symphonyfintech.com/xts-trading-front-end-api/

from database.token_db import get_br_symbol,get_token

def transform_data(data,token):
    """
    Transforms the new API request structure to the current expected structure.
    """
    symbol = get_br_symbol(data['symbol'],data['exchange'])
    #token = get_token(data['symbol'], data['exchange'])
    #print(f"token: {token}")
    # Basic mapping
    transformed = {
        "exchangeSegment": map_exchange(data['exchange']),
        "exchangeInstrumentID": token,
        "productType": map_product_type(data["product"]),
        "orderType": map_order_type(data["pricetype"]),
        "orderSide": data['action'].upper(),
        "timeInForce": "DAY",
        "disclosedQuantity": data.get("disclosed_quantity", "0"),
        "orderQuantity": data["quantity"],
        "limitPrice": data.get("price", "0"),
        "stopPrice": data.get("trigger_price", "0"),
        "orderUniqueIdentifier": "openalgo"
    }
    print(f"transformed data: {transformed}")
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

def map_exchange(exchange):
    """
    Maps the new exchange to the existing exchange.
    """
    exchange_mapping = {
        "NSE": "NSECM",
        "BSE": "BSECM",
        "MCX": "MCXFO",
        "NFO": "NSEFO",
        "BFO": "BSEFO",
        "CDS": "NSECD",
        "EXCHANGE": "EXCHANGE"
    }
    return exchange_mapping.get(exchange, "EXCHANGE")



def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL-L",
        "SL-M": "SL-M"
    }
    return order_type_mapping.get(pricetype, "MARKET")  # Default to MARKET if not found

def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return product_type_mapping.get(product, "MIS")  # Default to INTRADAY if not found

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