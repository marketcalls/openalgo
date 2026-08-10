"""Map OpenAlgo order requests to the SMIFS God Quant payload and back.

SMIFS uses conventions common to mainstream Indian broker APIs. STOP_LOSS_MARKET
is supported natively, so SL-M maps straight through with a trigger price.
"""


def transform_data(data, token):
    """OpenAlgo order dict + resolved securityId token -> SMIFS /v1/orders body."""
    return {
        "correlationId": data.get("strategy", "")[:25] or None,
        "transactionType": data["action"].upper(),          # BUY | SELL
        "exchangeSegment": map_exchange_type(data["exchange"]),
        "productType": map_product_type(data.get("product", "MIS")),
        "orderType": map_order_type(data.get("pricetype", "MARKET")),
        "validity": "DAY",
        "securityId": str(token),
        "quantity": int(data["quantity"]),
        "disclosedQuantity": int(data.get("disclosed_quantity", 0) or 0),
        "price": float(data.get("price", 0) or 0),
        "triggerPrice": float(data.get("trigger_price", 0) or 0),
    }


def transform_modify_order_data(data):
    return {
        "orderType": map_order_type(data.get("pricetype", "MARKET")),
        "validity": "DAY",
        "quantity": int(data["quantity"]),
        "disclosedQuantity": int(data.get("disclosed_quantity", 0) or 0),
        "price": float(data.get("price", 0) or 0),
        "triggerPrice": float(data.get("trigger_price", 0) or 0),
    }


def map_order_type(pricetype):
    return {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOP_LOSS",
        "SL-M": "STOP_LOSS_MARKET",
    }.get((pricetype or "MARKET").upper(), "MARKET")


def map_exchange_type(exchange):
    return {
        "NSE": "NSE_EQ",
        "NFO": "NSE_FNO",
        "CDS": "NSE_CURRENCY",
        "BSE": "BSE_EQ",
        "BFO": "BSE_FNO",
        "BCD": "BSE_CURRENCY",
        "MCX": "MCX_COMM",
    }.get((exchange or "NSE").upper(), "NSE_EQ")


def map_exchange(brexchange):
    return {
        "NSE_EQ": "NSE",
        "NSE_FNO": "NFO",
        "NSE_CURRENCY": "CDS",
        "BSE_EQ": "BSE",
        "BSE_FNO": "BFO",
        "BSE_CURRENCY": "BCD",
        "MCX_COMM": "MCX",
    }.get(brexchange, "NSE")


def map_product_type(product):
    return {"CNC": "CNC", "MIS": "INTRADAY", "NRML": "MARGIN"}.get((product or "MIS").upper(), "INTRADAY")


def reverse_map_product_type(product):
    return {"CNC": "CNC", "INTRADAY": "MIS", "MARGIN": "NRML"}.get(product, "MIS")
