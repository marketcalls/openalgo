# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Arrow Trading Parameters (edge.arrow.trade)
#
# Arrow uses short, single/short codes that differ from OpenAlgo's vocabulary:
#   side    : BUY/SELL          -> B / S
#   product : CNC/NRML/MIS      -> C / M / I
#   order   : MARKET/LIMIT/SL/SL-M -> MKT / LMT / SL-MKT / SL-LMT
#             (plain MKT is disabled on Arrow by default; a market order is
#              emulated by sending mpp=true, which routes a limit at the DPR /
#              upper-circuit price.)

from database.token_db import get_br_symbol

# --- Order / price type -------------------------------------------------
# OpenAlgo pricetype -> Arrow `order` value.
_ORDER_TYPE_MAP = {
    "MARKET": "MKT",
    "LIMIT": "LMT",
    "SL": "SL-LMT",
    "SL-M": "SL-MKT",
}

# --- Product type -------------------------------------------------------
# OpenAlgo product -> Arrow `product` value.
# TODO(arrow): confirm I=MIS (Intraday), C=CNC (Cash/Delivery), M=NRML (Margin/carry).
_PRODUCT_MAP = {
    "CNC": "C",
    "NRML": "M",
    "MIS": "I",
}

# Arrow `product` -> OpenAlgo product (used when normalizing broker responses).
_REVERSE_PRODUCT_MAP = {
    "C": "CNC",
    "M": "NRML",
    "I": "MIS",
}


def map_order_type(pricetype):
    """Map OpenAlgo pricetype to Arrow order type. Defaults to MKT."""
    return _ORDER_TYPE_MAP.get(pricetype, "MKT")


def map_product_type(product):
    """Map OpenAlgo product to Arrow product code. Defaults to I (intraday)."""
    return _PRODUCT_MAP.get(product, "I")


def reverse_map_product_type(exchange, product):
    """Map Arrow product code back to OpenAlgo product."""
    return _REVERSE_PRODUCT_MAP.get(product)


def map_transaction_type(action):
    """Map OpenAlgo BUY/SELL to Arrow B/S."""
    return "B" if str(action).upper() == "BUY" else "S"


def transform_data(data):
    """Transform an OpenAlgo order dict into the Arrow place-order payload.

    OpenAlgo order fields: symbol, exchange, action, pricetype, quantity,
    product, price, trigger_price, disclosed_quantity, strategy.
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])
    order_type = map_order_type(data["pricetype"])

    transformed = {
        "exchange": data["exchange"],
        "symbol": symbol,
        "quantity": str(data["quantity"]),
        "transactionType": map_transaction_type(data["action"]),
        "order": order_type,
        "product": map_product_type(data["product"]),
        "price": str(data.get("price", "0")),
        "validity": "DAY",
        "disclosedQty": str(data.get("disclosed_quantity", "0")),
        # remarks: max 16 chars; useful for idempotency / strategy tagging.
        "remarks": str(data.get("strategy", "openalgo"))[:16],
    }

    # Plain market orders are disabled on Arrow -> set mpp=true so MKT is
    # routed as a limit at the day-price-range / upper circuit.
    if order_type == "MKT":
        transformed["mpp"] = True

    # Stop-loss orders need a trigger price.
    # TODO(arrow): the order-placement docs do NOT list a trigger-price field
    # name. Confirm the literal key (triggerPrice? trigger_price?) before
    # SL/SL-M can be placed live. Sent here as `triggerPrice` provisionally.
    if order_type in ("SL-LMT", "SL-MKT"):
        transformed["triggerPrice"] = str(data.get("trigger_price", "0"))

    return transformed


def transform_modify_order_data(data):
    """Transform an OpenAlgo modify-order dict into the Arrow modify payload
    (Arrow modify reuses the place-order body shape)."""
    order_type = map_order_type(data["pricetype"])
    modified = {
        "exchange": data.get("exchange"),
        "symbol": get_br_symbol(data["symbol"], data["exchange"])
        if data.get("symbol")
        else None,
        "quantity": str(data["quantity"]),
        "order": order_type,
        "product": map_product_type(data["product"]),
        "price": str(data.get("price", "0")),
        "validity": "DAY",
        "disclosedQty": str(data.get("disclosed_quantity", "0")),
    }
    if order_type in ("SL-LMT", "SL-MKT"):
        modified["triggerPrice"] = str(data.get("trigger_price", "0"))
    return modified
