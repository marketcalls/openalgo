# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Paytm Broking Parameters https://developer.paytmmoney.com/docs/api/login

import math

from database.token_db import get_token

# OpenAlgo price type -> Paytm order_type (MKT, LMT, SL, SLM in Paytm's pyPMClient)
ORDER_TYPE_MAP = {
    "MARKET": "MKT",
    "LIMIT": "LMT",
    "SL": "SL",
    "SL-M": "SLM",
}

STOP_ORDER_TYPES = ("SL", "SLM")


class OrderRejected(ValueError):
    """An order OpenAlgo refuses before sending it to Paytm."""


def require_trigger_price(pricetype, trigger_price):
    """Raise OrderRejected unless an SL or SL-M trigger price is a finite number above 0."""
    try:
        trigger = float(trigger_price)
    except (TypeError, ValueError, OverflowError):
        trigger = 0.0
    if not (math.isfinite(trigger) and trigger > 0):
        raise OrderRejected(
            f"A trigger price is required for an {pricetype} order. "
            "Set the trigger price and place the order again."
        )


def transform_data(data):
    """
    Transforms the OpenAlgo API request structure to Paytm v2 API structure.

    Raises:
        OrderRejected: For a price type Paytm cannot take, or an SL or SL-M
            order without a trigger price.
    """
    symbol = get_token(data["symbol"], data["exchange"])
    txn_type = "B" if data["action"].upper() == "BUY" else "S"
    # Source from which the order is placed
    # Website - W, mWeb - M, Android - N, iOS - I, Exe - R, OperatorWorkStation - O
    source = "M"
    # This describes, to which segment the transaction belongs. (E→ Equity Cash / D→ Equity Derivative)
    segment = "E" if data["exchange"] in ["NSE", "BSE"] else "D"

    # Basic mapping
    transformed = {
        "security_id": symbol,
        "exchange": map_exchange(data["exchange"]),
        "txn_type": txn_type,
        "order_type": reverse_map_order_type(data["pricetype"]),
        "quantity": data["quantity"],
        "product": reverse_map_product_type(data["product"]),
        "price": data.get("price", "0"),
        # "disclosed_quantity": data.get("disclosed_quantity", "0"),
        "validity": "DAY",
        "segment": segment,
        "source": source,
    }

    if transformed["order_type"] in STOP_ORDER_TYPES:
        trigger_price = data.get("trigger_price")
        require_trigger_price(data["pricetype"], trigger_price)
        transformed["trigger_price"] = trigger_price
        if transformed["order_type"] == "SLM":
            # A stop-loss market order executes at market once triggered.
            transformed["price"] = "0"

    return transformed


# As long as an order is pending in the system, certain attributes of it can be modified.
# Price, quantity, validity, product are some of the variables that can be modified by the user.
# You have to pass "order_no", "serial_no" "group_id" as compulsory to modify the order.


def transform_modify_order_data(data):
    return {
        "product": reverse_map_product_type(data["product"]),
        "quantity": data["quantity"],
        "price": data["price"],
        "validity": "DAY",
    }


def map_order_type(pricetype):
    """
    Maps the new pricetype to the existing order type.
    """
    order_type_mapping = {
        "MKT": "MARKET",
        "LMT": "LIMIT",
        "SL": "STOP_LOSS",
        "SLM": "STOP_LOSS_MARKET",
    }
    # Default to MARKET if not found
    return order_type_mapping.get(pricetype, "MARKET")


def map_product_type(product):
    """
    Maps the new product type to the existing product type.
    """
    product_type_mapping = {
        "C": "CNC",
        "M": "MARGIN",
        "I": "MIS",
    }
    # Default to INTRADAY if not found
    return product_type_mapping.get(product, "MIS")


def reverse_map_product_type(product):
    """
    Reverse maps the broker product type to the OpenAlgo product type, considering the exchange.
    """
    # Exchange to OpenAlgo product type mapping for 'D'
    exchange_mapping = {"CNC": "C", "MARGIN": "M", "MIS": "I"}

    return exchange_mapping.get(product)


def reverse_map_order_type(order_type):
    """
    Maps an OpenAlgo price type (MARKET, LIMIT, SL, SL-M) to Paytm's order_type.

    Raises:
        OrderRejected: For a price type Paytm cannot take. It is never sent
            as a market order instead.
    """
    paytm_order_type = ORDER_TYPE_MAP.get((order_type or "").upper())
    if paytm_order_type is None:
        raise OrderRejected(
            f"Paytm does not accept the price type {order_type!r}. Use MARKET, LIMIT, SL or SL-M."
        )
    return paytm_order_type


def map_exchange(exchange):
    """
    Maps the new exchange to the existing exchange.
    """
    exchange_mapping = {
        "NSE": "NSE",
        "BSE": "BSE",
        "NFO": "NSE",
        "BFO": "BSE",
        "EXCHANGE": "EXCHANGE",
    }
    return exchange_mapping.get(exchange, "EXCHANGE")
