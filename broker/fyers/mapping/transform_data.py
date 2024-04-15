#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Zerodha Broking Parameters https://kite.trade/docs/connect/v3/

from database.token_db import get_br_symbol

def transform_data(data):
    """
    Transforms the OpenAlgo Platform API request structure to the format expected by the Fyers API.
    """
    # Assuming get_br_symbol, map_order_type, map_action, and map_product_type are defined elsewhere correctly.
    symbol = get_br_symbol(data['symbol'], data['exchange'])

    # Convert fields to correct data types as required by Fyers API
    quantity = int(data["quantity"])  # Ensuring quantity is an integer
    price = float(data.get("price", 0))  # Ensuring price is a float
    trigger_price = float(data.get("trigger_price", 0))  # Ensuring trigger price is a float
    disclosed_quantity = int(data.get("disclosed_quantity", 0))  # Ensuring disclosed quantity is an integer

    # Map to Fyers API field names and structure
    transformed = {
        "symbol": symbol,
        "qty": quantity,
        "type": map_order_type(data["pricetype"]),
        "side": map_action(data["action"]),
        "productType": map_product_type(data["product"]),
        "limitPrice": price,
        "stopPrice": trigger_price,
        "validity": "DAY",
        "disclosedQty": disclosed_quantity,
        "offlineOrder": False,
        "stopLoss": 0,
        "takeProfit": 0,
        "orderTag": "openalgo",
    }

    return transformed



def transform_modify_order_data(data):
    return {
        "id" : data["orderid"],  
        "qty": int(data["quantity"]),  # Convert quantity to integer
        "type": map_order_type(data["pricetype"]),  # Assuming map_order_type returns an integer
        "side": map_action(data["action"]),  # Assuming map_action returns an integer
        "limitPrice": float(data["price"]),  # Convert price to float
        "stopPrice": float(data.get("trigger_price", 0))  # Convert trigger_price to float, default is 0
    }




def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": 2,
        "LIMIT": 1,
        "SL": 4,
        "SL-M": 3
    }
    return order_type_mapping.get(pricetype, 2)  # Default to MARKET if not found


def map_action(action):
    """
    Maps the new action to side
    """
    action_mapping = {
        "BUY": 1,
        "SELL": -1
    }
    return action_mapping.get(action) 


def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "MARGIN",
        "MIS": "INTRADAY",
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
    