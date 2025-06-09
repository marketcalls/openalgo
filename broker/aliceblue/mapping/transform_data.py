#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Zerodha Broking Parameters https://kite.trade/docs/connect/v3/

from database.token_db import get_br_symbol, get_token

def transform_data(data):
    """
    Transforms the new API request structure to the current expected structure.
    """
    symbol = get_br_symbol(data['symbol'],data['exchange'])
    token = get_token(data['symbol'],data['exchange'])

    # Basic mapping
    transformed = {
        "complexty": "regular",
        "discqty": data.get("disclosed_quantity", "0"),
        "exch": data['exchange'],
        "pCode": data["product"],
        "prctyp": map_order_type(data["pricetype"]),
        "price": data.get("price", "0"),
        "qty": data["quantity"],
        "ret": "DAY",
        "symbol_id": token,
        "trading_symbol": symbol,
        "transtype": data['action'].upper(),
        "trigPrice": data.get("trigger_price", "0"),
        "orderTag": "openalgo",
        
        }

    
    return transformed


def transform_modify_order_data(data):
    return {
        "discqty": int(data.get("disclosed_quantity", 0)),
        "exch": data.get("exchange"),
        "filledQuantity": 0,
        "nestOrderNumber": data.get("orderid"),
        "prctyp": map_order_type(data.get("pricetype")),
        "price": float(data.get("price")),
        "qty": int(data.get("quantity")),
        "trading_symbol": get_br_symbol(data.get("symbol"),data.get("exchange")),
        "trigPrice": data.get("trigger_price", "0"),
        "transtype": data.get("action").upper(),
        "pCode": data.get("product")
    }


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MARKET": "MKT",
        "LIMIT": "L",
        "SL": "SL",
        "SL-M": "SL-M"
    }
    return order_type_mapping.get(pricetype, "MKT")  # Default to MARKET if not found

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

def reverse_map_product_type(product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    exchange_mapping = {
        "MKT": "MARKET",
        "L": "LIMIT",
        "SL": "SL",
        "SL-M": "SL-M"
    }
   
    return exchange_mapping.get(product)
    