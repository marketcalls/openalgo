"""OpenAlgo order fields to Sahi's order API, and Sahi's enums back.

Sahi's wire values (broker-api-docs/sahi-api-docs, Conventions, "Enum values"):

    txn_type    B, S
    order_type  LMT, MKT, SL-LMT, SL-MKT
    product     C (delivery), I (intraday), M (carry-forward F&O), F (MTF)
    validity    DAY, IOC

Prices travel as integer paise and quantities as units. MKT and SL-MKT are
accepted natively: Sahi converts them once into protected limit orders
(market_protection, auto when omitted), so no emulation is needed here.
"""

from decimal import ROUND_HALF_UP, Decimal

from database.token_db import get_br_symbol

PRODUCT_MAP = {"CNC": "C", "MIS": "I", "NRML": "M"}
REVERSE_PRODUCT_MAP = {"C": "CNC", "I": "MIS", "M": "NRML", "F": "MTF"}

PRICETYPE_MAP = {"MARKET": "MKT", "LIMIT": "LMT", "SL": "SL-LMT", "SL-M": "SL-MKT"}
REVERSE_PRICETYPE_MAP = {"MKT": "MARKET", "LMT": "LIMIT", "SL-LMT": "SL", "SL-MKT": "SL-M"}

ACTION_MAP = {"BUY": "B", "SELL": "S"}
REVERSE_ACTION_MAP = {"B": "BUY", "S": "SELL"}

# OpenAlgo exchange -> Sahi exchange_segment. Indices cannot be traded.
EXCHANGE_SEGMENT_MAP = {"NSE": "NSE", "BSE": "BSE", "NFO": "NFO", "BFO": "BFO"}


def to_paise(value):
    """Rupees (str or number) to integer paise, rounding half up."""
    if value in (None, ""):
        return 0
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_paise(value):
    """Integer paise to rupees as a float; None stays 0.0."""
    if value in (None, ""):
        return 0.0
    return round(float(value) / 100.0, 2)


def map_product_type(product):
    """OpenAlgo product to Sahi product code."""
    return PRODUCT_MAP.get(str(product or "").upper())


def reverse_map_product_type(product):
    """Sahi product code to OpenAlgo product."""
    return REVERSE_PRODUCT_MAP.get(product, product)


def map_order_type(pricetype):
    return PRICETYPE_MAP.get(str(pricetype or "").upper())


def reverse_map_order_type(order_type):
    return REVERSE_PRICETYPE_MAP.get(order_type, order_type)


def map_action(action):
    return ACTION_MAP.get(str(action or "").upper())


def reverse_map_action(txn_type):
    return REVERSE_ACTION_MAP.get(txn_type, txn_type)


class OrderMappingError(ValueError):
    """An OpenAlgo order Sahi cannot take, explained for a trader."""


def transform_data(data):
    """Build the POST /v1/orders body from an OpenAlgo place-order request."""
    exchange = str(data.get("exchange", "")).upper()
    segment = EXCHANGE_SEGMENT_MAP.get(exchange)
    if not segment:
        raise OrderMappingError(f"Sahi does not take orders on {exchange}.")

    symbol = data.get("symbol")
    brsymbol = get_br_symbol(symbol, exchange)
    if not brsymbol:
        raise OrderMappingError(
            f"{symbol} was not found on {exchange} in the Sahi master contract. "
            "Check the symbol, or download the master contract again."
        )

    product = map_product_type(data.get("product"))
    if not product:
        raise OrderMappingError(
            f"Product {data.get('product')} is not supported. Use CNC, MIS or NRML."
        )
    order_type = map_order_type(data.get("pricetype"))
    if not order_type:
        raise OrderMappingError(
            f"Price type {data.get('pricetype')} is not supported. Use MARKET, LIMIT, SL or SL-M."
        )
    txn_type = map_action(data.get("action"))
    if not txn_type:
        raise OrderMappingError(f"Action {data.get('action')} is not supported. Use BUY or SELL.")

    payload = {
        "exchange_segment": segment,
        "symbol": brsymbol,
        "txn_type": txn_type,
        "qty": int(float(data.get("quantity", 0))),
        "order_type": order_type,
        "product": product,
        "validity": "DAY",
        # MKT and SL-MKT take price 0; Sahi prices the protected limit itself.
        "price": 0 if order_type in ("MKT", "SL-MKT") else to_paise(data.get("price")),
    }

    if order_type in ("SL-LMT", "SL-MKT"):
        payload["trigger_price"] = to_paise(data.get("trigger_price"))

    disclosed = int(float(data.get("disclosed_quantity") or 0))
    if disclosed:
        payload["disclosed_qty"] = disclosed

    return payload


def transform_modify_order_data(data):
    """Build the PUT /v1/orders/{order_id} body from an OpenAlgo modify request.

    Sahi takes only the fields being changed, but sending the full set the
    trader submitted is accepted and keeps the order exactly as requested.
    """
    order_type = map_order_type(data.get("pricetype"))
    if not order_type:
        raise OrderMappingError(
            f"Price type {data.get('pricetype')} is not supported. Use MARKET, LIMIT, SL or SL-M."
        )

    payload = {
        "qty": int(float(data.get("quantity", 0))),
        "order_type": order_type,
        "validity": "DAY",
        "price": 0 if order_type in ("MKT", "SL-MKT") else to_paise(data.get("price")),
    }
    if order_type in ("SL-LMT", "SL-MKT"):
        payload["trigger_price"] = to_paise(data.get("trigger_price"))

    disclosed = data.get("disclosed_quantity")
    if disclosed not in (None, ""):
        payload["disclosed_qty"] = int(float(disclosed))
    return payload
