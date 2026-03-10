# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping AliceBlue V2 API Parameters

from database.token_db import get_br_symbol, get_token


# ─── Product / Order type mappings (OpenAlgo ↔ AliceBlue V2) ──────────────────


def map_product_type(product):
    """Map OpenAlgo product type to AliceBlue V2 product type."""
    mapping = {
        "CNC": "LONGTERM",
        "NRML": "NRML",
        "MIS": "INTRADAY",
    }
    return mapping.get(product, "INTRADAY")


def reverse_map_product_type(product):
    """Map AliceBlue V2 product type back to OpenAlgo product type."""
    mapping = {
        "LONGTERM": "CNC",
        "NRML": "NRML",
        "INTRADAY": "MIS",
        "MTF": "CNC",
        "CNC": "CNC",
        "MIS": "MIS",
        "DELIVERY": "CNC",
    }
    return mapping.get(product, "MIS")


def map_order_type(pricetype):
    """Map OpenAlgo price type to AliceBlue V2 order type."""
    mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SL-M": "SLM",
    }
    return mapping.get(pricetype, "MARKET")


def reverse_map_order_type(order_type):
    """Map AliceBlue V2 order type back to OpenAlgo price type."""
    mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SLM": "SL-M",
    }
    return mapping.get(order_type, "MARKET")


# ─── Payload builders (OpenAlgo request → AliceBlue V2 API payload) ──────────


def transform_data(data):
    """
    Transform an OpenAlgo place-order request into an AliceBlue V2 API payload item.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    token = get_token(data["symbol"], data["exchange"])

    return {
        "exchange": data["exchange"],
        "instrumentId": str(int(float(token))),
        "transactionType": data["action"].upper(),
        "quantity": int(data["quantity"]),
        "product": map_product_type(data.get("product", "MIS")),
        "orderComplexity": "REGULAR",
        "orderType": map_order_type(data.get("pricetype", "MARKET")),
        "validity": "DAY",
        "price": str(data.get("price", "0")),
        "slLegPrice": "",
        "targetLegPrice": "",
        "slTriggerPrice": str(data.get("trigger_price", "0")),
        "disclosedQuantity": str(data.get("disclosed_quantity", "")),
        "marketProtectionPercent": "",
        "deviceId": "",
        "trailingSlAmount": "",
        "apiOrderSource": "",
        "algoId": "",
        "orderTag": "openalgo",
    }


def transform_modify_order_data(data):
    """
    Transform an OpenAlgo modify-order request into an AliceBlue V2 API modify payload.
    """
    return {
        "brokerOrderId": str(data.get("orderid")),
        "quantity": int(data.get("quantity", 0)),
        "orderType": map_order_type(data.get("pricetype", "LIMIT")),
        "slTriggerPrice": str(data.get("trigger_price", "0")),
        "price": str(data.get("price", "0")),
        "slLegPrice": "",
        "trailingSlAmount": "",
        "targetLegPrice": "",
        "validity": "DAY",
        "disclosedQuantity": str(data.get("disclosed_quantity", "0")),
        "marketProtection": "",
        "deviceId": "",
    }
