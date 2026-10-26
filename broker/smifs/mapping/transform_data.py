"""Map OpenAlgo order requests to the SMIFS God Quant payload and back.

SMIFS uses conventions common to mainstream Indian trading APIs. STOP_LOSS_MARKET
is supported natively, so SL-M maps straight through with a trigger price.
"""

# OpenAlgo exchange code -> SMIFS exchange segment.
_EXCHANGE_TO_SEGMENT = {
    "NSE": "NSE_EQ",
    "NFO": "NSE_FNO",
    "CDS": "NSE_CURRENCY",
    "BSE": "BSE_EQ",
    "BFO": "BSE_FNO",
    "BCD": "BSE_CURRENCY",
    "MCX": "MCX_COMM",
    "NSE_INDEX": "IDX_I",
    "BSE_INDEX": "IDX_I",
}

# SMIFS exchange segment -> OpenAlgo exchange code. IDX_I holds both NSE and
# BSE indices; positions and orders never carry it, so NSE_INDEX is only a
# display default here. The master contract download decides per row.
_SEGMENT_TO_EXCHANGE = {
    "NSE_EQ": "NSE",
    "NSE_FNO": "NFO",
    "NSE_CURRENCY": "CDS",
    "BSE_EQ": "BSE",
    "BSE_FNO": "BFO",
    "BSE_CURRENCY": "BCD",
    "MCX_COMM": "MCX",
    "IDX_I": "NSE_INDEX",
}

_ORDER_TYPE = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "STOP_LOSS", "SL-M": "STOP_LOSS_MARKET"}
_REVERSE_ORDER_TYPE = {v: k for k, v in _ORDER_TYPE.items()}

_PRODUCT = {"CNC": "CNC", "MIS": "INTRADAY", "NRML": "MARGIN"}
_REVERSE_PRODUCT = {"CNC": "CNC", "INTRADAY": "MIS", "MARGIN": "NRML"}


def transform_data(data, token):
    """OpenAlgo order dict + resolved securityId token -> SMIFS /v1/orders body.

    correlationId is deliberately left out. SMIFS treats a repeated
    correlationId as a retry and returns the original order instead of placing
    a new one, so sending the OpenAlgo strategy name there would turn every
    order after the first one from the same strategy into a silent duplicate.
    """
    return {
        "transactionType": data["action"].upper(),  # BUY | SELL
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
    return _ORDER_TYPE.get((pricetype or "MARKET").upper(), "MARKET")


def reverse_map_order_type(order_type):
    """SMIFS orderType -> OpenAlgo pricetype (STOP_LOSS -> SL, and so on)."""
    return _REVERSE_ORDER_TYPE.get(order_type, order_type)


def map_exchange_type(exchange):
    return _EXCHANGE_TO_SEGMENT.get((exchange or "NSE").upper(), "NSE_EQ")


def map_exchange(brexchange):
    return _SEGMENT_TO_EXCHANGE.get(brexchange, "NSE")


def map_product_type(product):
    return _PRODUCT.get((product or "MIS").upper(), "INTRADAY")


def reverse_map_product_type(product):
    return _REVERSE_PRODUCT.get(product, "MIS")
