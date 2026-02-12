# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Nubra API Parameters https://api.nubra.io/docs

from database.token_db import get_br_symbol


def transform_data(data, token):
    """
    Transforms the OpenAlgo API request structure to Nubra's expected structure.
    
    OpenAlgo format:
    - action: BUY/SELL
    - product: CNC/MIS/NRML
    - pricetype: MARKET/LIMIT/SL/SL-M
    - price: float (in rupees)
    - trigger_price: float (in rupees, for stoploss orders)
    - quantity: int
    
    Nubra format:
    - order_side: ORDER_SIDE_BUY/ORDER_SIDE_SELL
    - order_delivery_type: ORDER_DELIVERY_TYPE_CNC/ORDER_DELIVERY_TYPE_IDAY
    - order_type: ORDER_TYPE_REGULAR/ORDER_TYPE_STOPLOSS
    - price_type: MARKET/LIMIT
    - order_price: int (in paise)
    - algo_params.trigger_price: int (in paise, for stoploss orders)
    - order_qty: int
    """
    # Convert price from rupees to paise (multiply by 100)
    price = float(data.get("price", 0))
    price_in_paise = int(round(price * 100)) if price else 0
    
    trigger_price = float(data.get("trigger_price", 0))
    trigger_price_in_paise = int(round(trigger_price * 100)) if trigger_price else 0
    
    pricetype = data.get("pricetype", "MARKET")
    
    # Determine validity type based on price type
    # MARKET and SL-M orders require IOC (Immediate or Cancel)
    # LIMIT and SL orders use DAY validity
    if pricetype == "MARKET":
        validity_type = "IOC"
    else:
        validity_type = "DAY"
    
    # Build the transformed data structure for Nubra API
    transformed = {
        "ref_id": int(token),  # Instrument reference ID from token
        "order_side": map_order_side(data["action"]),
        "order_delivery_type": map_order_delivery_type(data["product"]),
        "order_type": map_order_type(pricetype),
        "price_type": map_price_type(pricetype),
        "order_qty": int(data["quantity"]),
        "validity_type": validity_type,
        "order_price": price_in_paise,
        "tag": data.get("strategy", "openalgo"),
    }
    
    # Add algo_params for stoploss orders
    if pricetype in ["SL", "SL-M"]:
        transformed["algo_params"] = {
            "trigger_price": trigger_price_in_paise
        }
        # For SL-M orders, Nubra requires order_price >= trigger_price
        # Set order_price = trigger_price to pass validation;
        # actual execution happens at market price since price_type is MARKET
        if pricetype == "SL-M" and not price_in_paise:
            transformed["order_price"] = trigger_price_in_paise
    
    return transformed


def transform_modify_order_data(data, token):
    """
    Transforms modify order data from OpenAlgo format to Nubra's format.
    
    Nubra Modify Order API: POST /orders/v2/modify/{order_id}
    
    Compulsory fields: order_price, order_qty, exchange, order_type
    For ORDER_TYPE_STOPLOSS: also requires trigger_price in algo_params
    
    Note: order_id goes in the URL, not in the payload
    """
    price = float(data.get("price", 0))
    price_in_paise = int(round(price * 100)) if price else 0
    
    trigger_price = float(data.get("trigger_price", 0))
    trigger_price_in_paise = int(round(trigger_price * 100)) if trigger_price else 0
    
    pricetype = data.get("pricetype", "MARKET")
    
    # Build payload per Nubra API requirements
    # order_id is passed in URL, not in payload
    transformed = {
        "order_qty": int(data["quantity"]),
        "order_price": price_in_paise,
        "exchange": data["exchange"],  # Compulsory field
        "order_type": map_order_type(pricetype),
    }
    
    # Add algo_params for stoploss orders (trigger_price is compulsory for stoploss)
    if pricetype in ["SL", "SL-M"]:
        transformed["algo_params"] = {
            "trigger_price": trigger_price_in_paise
        }
    
    return transformed


def map_order_side(action):
    """
    Maps OpenAlgo action (BUY/SELL) to Nubra order_side.
    """
    side_mapping = {
        "BUY": "ORDER_SIDE_BUY",
        "SELL": "ORDER_SIDE_SELL",
    }
    return side_mapping.get(action.upper(), "ORDER_SIDE_BUY")


def map_order_delivery_type(product):
    """
    Maps OpenAlgo product type to Nubra order_delivery_type.
    CNC -> ORDER_DELIVERY_TYPE_CNC (Cash & Carry / Delivery)
    MIS -> ORDER_DELIVERY_TYPE_IDAY (Intraday)
    NRML -> ORDER_DELIVERY_TYPE_CNC (Normal for F&O, treated as carry forward)
    """
    delivery_type_mapping = {
        "CNC": "ORDER_DELIVERY_TYPE_CNC",
        "MIS": "ORDER_DELIVERY_TYPE_IDAY",
        "NRML": "ORDER_DELIVERY_TYPE_CNC",  # NRML (normal) maps to CNC for F&O
    }
    return delivery_type_mapping.get(product.upper(), "ORDER_DELIVERY_TYPE_IDAY")


def map_order_type(pricetype):
    """
    Maps OpenAlgo pricetype to Nubra order_type.
    Regular orders for MARKET/LIMIT, Stoploss for SL/SL-M
    """
    order_type_mapping = {
        "MARKET": "ORDER_TYPE_REGULAR",
        "LIMIT": "ORDER_TYPE_REGULAR",
        "SL": "ORDER_TYPE_STOPLOSS",
        "SL-M": "ORDER_TYPE_STOPLOSS",
    }
    return order_type_mapping.get(pricetype.upper(), "ORDER_TYPE_REGULAR")


def map_price_type(pricetype):
    """
    Maps OpenAlgo pricetype to Nubra price_type.
    Only MARKET or LIMIT in Nubra.
    """
    price_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "LIMIT",      # Stoploss Limit
        "SL-M": "LIMIT",    # Nubra doesn't support stoploss+market; use LIMIT with price=trigger
    }
    return price_type_mapping.get(pricetype.upper(), "MARKET")


def map_product_type(product):
    """
    Maps OpenAlgo product type to Nubra's internal product type for position lookup.
    Used for get_open_position to match positions.
    """
    product_type_mapping = {
        "CNC": "ORDER_DELIVERY_TYPE_CNC",
        "NRML": "ORDER_DELIVERY_TYPE_CNC",
        "MIS": "ORDER_DELIVERY_TYPE_IDAY",
    }
    return product_type_mapping.get(product.upper(), "ORDER_DELIVERY_TYPE_IDAY")


def reverse_map_product_type(product):
    """
    Maps Nubra's order_delivery_type back to OpenAlgo product type.
    """
    reverse_product_type_mapping = {
        "ORDER_DELIVERY_TYPE_CNC": "CNC",
        "ORDER_DELIVERY_TYPE_IDAY": "MIS",
    }
    return reverse_product_type_mapping.get(product, "MIS")
