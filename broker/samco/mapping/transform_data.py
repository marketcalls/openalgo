#Mapping OpenAlgo API Request https://openalgo.in/docs
#Mapping Samco Parameters https://www.samco.in/stocknote-api-documentation

from database.token_db import get_br_symbol

def transform_data(data, token):
    """
    Transforms the OpenAlgo API request structure to Samco expected structure.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    # Basic mapping for Samco placeOrder API
    transformed = {
        "symbolName": symbol,
        "exchange": data["exchange"],
        "transactionType": data["action"].upper(),
        "orderType": map_order_type(data["pricetype"]),
        "quantity": str(data["quantity"]),
        "disclosedQuantity": str(data.get("disclosed_quantity", "0")),
        "orderValidity": "DAY",
        "productType": map_product_type(data["product"]),
        "afterMarketOrderFlag": "NO"
    }

    # Add price for LIMIT and SL orders
    if data["pricetype"] in ["LIMIT", "SL"]:
        transformed["price"] = str(data.get("price", "0"))

    # Add trigger price for SL and SL-M orders
    if data["pricetype"] in ["SL", "SL-M"]:
        transformed["triggerPrice"] = str(data.get("trigger_price", "0"))

    return transformed


def transform_modify_order_data(data):
    """
    Transforms the OpenAlgo modify order request to Samco expected structure.
    Only includes fields that can be modified (orderNumber goes in URL).
    """
    transformed = {
        "orderType": map_order_type(data["pricetype"]),
        "quantity": str(data["quantity"]),
        "orderValidity": "DAY"
    }

    # Only add disclosedQuantity if provided and > 0 (must be min 10% of quantity)
    disclosed_qty = data.get("disclosed_quantity")
    if disclosed_qty and int(disclosed_qty) > 0:
        transformed["disclosedQuantity"] = str(disclosed_qty)

    # Add price for LIMIT and SL orders
    if data["pricetype"] in ["LIMIT", "SL"]:
        transformed["price"] = str(data.get("price", "0"))

    # Add trigger price for SL and SL-M orders
    if data["pricetype"] in ["SL", "SL-M"]:
        transformed["triggerPrice"] = str(data.get("trigger_price", "0"))

    return transformed


def map_order_type(pricetype):
    """
    Maps OpenAlgo pricetype to Samco order type.
    """
    order_type_mapping = {
        "MARKET": "MKT",
        "LIMIT": "L",
        "SL": "SL",
        "SL-M": "SL-M"
    }
    return order_type_mapping.get(pricetype, "MKT")


def map_product_type(product):
    """
    Maps OpenAlgo product type to Samco product type.
    """
    product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return product_type_mapping.get(product, "MIS")


def reverse_map_product_type(product):
    """
    Maps Samco product type back to OpenAlgo product type.
    """
    reverse_product_type_mapping = {
        "CNC": "CNC",
        "NRML": "NRML",
        "MIS": "MIS",
    }
    return reverse_product_type_mapping.get(product, "MIS")
