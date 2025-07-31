#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Fyers Broking Parameters

from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)

def transform_data(data):
    """
    Transforms the OpenAlgo Platform API request structure to the format expected by the Fyers API.
    """
    symbol = get_br_symbol(data['symbol'], data['exchange'])

    quantity = int(data["quantity"])
    price = float(data.get("price", 0))
    trigger_price = float(data.get("trigger_price", 0))
    disclosed_quantity = int(data.get("disclosed_quantity", 0))

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
    """
    Transforms the order modification data to the format expected by Fyers API.
    Handles empty strings and None values for price and trigger_price.
    """
    order_id = data.get("orderid", "N/A")
    try:
        quantity = int(data.get("quantity", 0))
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse quantity for order modification {order_id}. Defaulting to 0. Error: {e}")
        quantity = 0
    
    try:
        price = float(data.get("price", 0)) if data.get("price") else 0.0
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse price for order modification {order_id}. Defaulting to 0.0. Error: {e}")
        price = 0.0
    
    try:
        trigger_price = float(data.get("trigger_price", 0)) if data.get("trigger_price") else 0.0
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse trigger_price for order modification {order_id}. Defaulting to 0.0. Error: {e}")
        trigger_price = 0.0
    
    return {
        "id": data["orderid"],
        "qty": quantity,
        "type": map_order_type(data.get("pricetype", "")),
        "limitPrice": price,
        "stopPrice": trigger_price
    }

def map_order_type(pricetype):
    """
    Maps the OpenAlgo pricetype to the Fyers order type.
    """
    order_type_mapping = {
        "MARKET": 2,
        "LIMIT": 1,
        "SL": 4,
        "SL-M": 3
    }
    order_type = order_type_mapping.get(pricetype)
    if order_type is None:
        logger.warning(f"Unknown pricetype '{pricetype}' received. Defaulting to MARKET (2).")
        return 2  # Default to MARKET
    return order_type

def map_action(action):
    """
    Maps the OpenAlgo action to the Fyers side.
    """
    action_mapping = {
        "BUY": 1,
        "SELL": -1
    }
    side = action_mapping.get(action)
    if side is None:
        logger.warning(f"Unknown action '{action}' received. Cannot map to a side.")
    return side

def map_product_type(product):
    """
    Maps the OpenAlgo product type to the Fyers product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "MARGIN",
        "MIS": "INTRADAY",
        "CO": "CO",
        "BO": "BO"
    }
    fyers_product = product_type_mapping.get(product)
    if fyers_product is None:
        logger.warning(f"Unknown product type '{product}' received. Defaulting to INTRADAY.")
        return "INTRADAY"  # Default to INTRADAY
    return fyers_product

def reverse_map_product_type(product):
    """
    Reverse maps the Fyers product type to the OpenAlgo product type.
    """
    reverse_product_mapping = {
        "CNC": "CNC",
        "MARGIN": "NRML",
        "INTRADAY": "MIS",
        "CO": "CO",
        "BO": "BO"
    }
    oa_product = reverse_product_mapping.get(product)
    if oa_product is None:
        logger.warning(f"Unknown Fyers product type '{product}' received. Cannot map to OpenAlgo product type.")
    return oa_product
    