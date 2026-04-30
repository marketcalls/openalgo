from typing import Any


def map_exchange(exchange: str) -> str:
    exchange_mapping = {
        "NSE": "NSEEQ",
        "BSE": "BSEEQ",
        "NFO": "NSEFO",
        "BFO": "BSEFO",
        "CDS": "NSECURR",
        "BCD": "BSECURR",
        "MCX": "MCXCOMM",
        "NCDEX": "NCDEXCOMM",
    }
    return exchange_mapping.get((exchange or "").upper(), (exchange or "").upper())


def map_order_type(pricetype: str) -> str:
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SL-M": "SLM",
    }
    return order_type_mapping.get((pricetype or "").upper(), "MARKET")


def reverse_map_order_type(order_type: str) -> str:
    order_type_mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "SL",
        "SLM": "SL-M",
    }
    return order_type_mapping.get((order_type or "").upper(), "MARKET")


def map_product_type(product: str) -> str:
    product_type_mapping = {
        "MIS": "INTRADAY",
        "CNC": "DELIVERY",
        "NRML": "NORMAL",
    }
    return product_type_mapping.get((product or "").upper(), "INTRADAY")


def reverse_map_product_type(product: str) -> str:
    product_mapping = {
        "INTRADAY": "MIS",
        "DELIVERY": "CNC",
        "NORMAL": "NRML",
        "BNPL": "CNC",
    }
    return product_mapping.get((product or "").upper(), "MIS")


def map_validity(validity: str) -> str:
    validity_mapping = {
        "DAY": "DAY",
        "IOC": "IOC",
    }
    return validity_mapping.get((validity or "").upper(), "DAY")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def transform_data(data: dict, token: str) -> dict:
    """Transform OpenAlgo order request to IIFL Capital format."""
    transformed = {
        "instrumentId": str(token),
        "exchange": map_exchange(data.get("exchange", "")),
        "transactionType": (data.get("action") or "").upper(),
        "quantity": str(int(float(data.get("quantity", 0)))),
        "orderComplexity": data.get("order_complexity", "REGULAR"),
        "product": map_product_type(data.get("product", "MIS")),
        "orderType": map_order_type(data.get("pricetype", "MARKET")),
        "validity": map_validity(data.get("validity", "DAY")),
        "apiOrderSource": "openalgo",
    }

    if transformed["orderType"] in ("LIMIT", "SL"):
        transformed["price"] = _to_float(data.get("price", 0.0))

    if transformed["orderType"] in ("SL", "SLM"):
        transformed["slTriggerPrice"] = _to_float(data.get("trigger_price", 0.0))

    disclosed_qty = int(float(data.get("disclosed_quantity", 0) or 0))
    if disclosed_qty > 0:
        transformed["disclosedQuantity"] = str(disclosed_qty)

    if data.get("strategy"):
        transformed["orderTag"] = str(data["strategy"])[:50]

    return transformed


def transform_modify_order_data(data: dict) -> dict:
    """Transform OpenAlgo modify request to IIFL Capital format."""
    transformed = {}

    quantity = data.get("quantity")
    if quantity is not None:
        transformed["quantity"] = str(int(float(data.get("quantity", 0))))

    pricetype = data.get("pricetype")
    if pricetype:
        order_type = map_order_type(pricetype)
        transformed["orderType"] = order_type

        if order_type in ("LIMIT", "SL"):
            transformed["price"] = _to_float(data.get("price", 0.0))

        if order_type in ("SL", "SLM"):
            transformed["slTriggerPrice"] = _to_float(data.get("trigger_price", 0.0))

    if "validity" in data:
        transformed["validity"] = map_validity(data.get("validity", "DAY"))

    disclosed_qty = data.get("disclosed_quantity")
    if disclosed_qty is not None:
        disclosed_qty = int(float(disclosed_qty or 0))
        if disclosed_qty > 0:
            transformed["disclosedQuantity"] = str(disclosed_qty)

    return transformed
