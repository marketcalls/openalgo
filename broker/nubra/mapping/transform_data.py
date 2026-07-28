# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Nubra API Parameters https://api.nubra.io/docs

import os

from database.token_db import get_br_symbol


def _market_protection_pct():
    """
    Market-Protection-Price (MPP) band (fraction) for emulating MARKET / SL-M.

    Nubra does NOT support MARKET price_type (docs: "Do not send MARKET as
    price_type") and has no broker-side market-protection flag (unlike Zerodha's
    market_protection / Arrow's mpp). We therefore emulate a market order the way
    those brokers' MPP feature does: a DAY LIMIT priced at LTP +/- this band
    (BUY above, SELL below) so it is marketable but capped. The same band sets
    the marketable limit for SL-M stop orders. Configurable via
    NUBRA_MARKET_PROTECTION_PCT (percent, default 1.0).
    """
    try:
        return float(os.getenv("NUBRA_MARKET_PROTECTION_PCT", "1.0")) / 100.0
    except (TypeError, ValueError):
        return 0.01


def transform_data(data, token, market_price_paise=None):
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
    - price_type: LIMIT (Nubra is limit-only; MARKET is emulated as an MPP limit)
    - order_price: int (in paise)
    - validity_type: DAY (Nubra has no IOC routing; MPP limits rest as DAY)
    - algo_params.trigger_price: int (in paise, for stoploss orders)
    - order_qty: int

    Args:
        market_price_paise: Market-Protection-Price (in paise, LTP +/- band)
            computed by the caller, used to emulate a MARKET order as a DAY LIMIT.
            When None for a MARKET request, the caller is expected to have guarded
            against placement.
    """
    # Convert price from rupees to paise (multiply by 100)
    price = float(data.get("price", 0))
    price_in_paise = int(round(price * 100)) if price else 0

    trigger_price = float(data.get("trigger_price", 0))
    trigger_price_in_paise = int(round(trigger_price * 100)) if trigger_price else 0

    pricetype = data.get("pricetype", "MARKET").upper()
    side = data["action"].upper()

    # All orders use DAY validity. Nubra has no IOC routing, and the MPP-style
    # market emulation deliberately rests as a DAY limit (like Zerodha/Arrow MPP).
    validity_type = "DAY"

    # Build the transformed data structure for Nubra API
    transformed = {
        "ref_id": int(token),  # Instrument reference ID from token
        "order_side": map_order_side(side),
        "order_delivery_type": map_order_delivery_type(data["product"]),
        "order_type": map_order_type(pricetype),
        "price_type": map_price_type(pricetype),  # always LIMIT (Nubra is limit-only)
        "order_qty": int(data["quantity"]),
        "validity_type": validity_type,
        "order_price": price_in_paise,
        "tag": data.get("strategy", "openalgo"),
    }

    # MARKET emulation: Nubra rejects price_type=MARKET and has no market-protection
    # flag, so we send a DAY LIMIT at the Market-Protection-Price (LTP +/- band,
    # computed by the caller) -- the same idea as Zerodha market_protection / Arrow mpp.
    if pricetype == "MARKET":
        if market_price_paise:
            transformed["order_price"] = int(market_price_paise)
        # else: leave price_in_paise (the caller should have guarded placement)

    # Add algo_params for stoploss orders
    if pricetype in ("SL", "SL-M"):
        transformed["algo_params"] = {
            "trigger_price": trigger_price_in_paise
        }
        # SL-M is a stop-MARKET order, which Nubra has no native type for. Emulate
        # it as a stop-LIMIT whose limit is placed beyond the trigger by the
        # protection band so it is marketable the moment the trigger fires.
        # Nubra rule: BUY stop needs order_price >= trigger; SELL needs <= trigger.
        if pricetype == "SL-M" and trigger_price_in_paise:
            buf = _market_protection_pct()
            if side == "BUY":
                transformed["order_price"] = int(round(trigger_price_in_paise * (1 + buf)))
            else:
                transformed["order_price"] = int(round(trigger_price_in_paise * (1 - buf)))

    return transformed


def transform_modify_order_data(data, token, market_price_paise=None):
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

    pricetype = data.get("pricetype", "MARKET").upper()
    side = data.get("action", "BUY").upper()

    # Build payload per Nubra API requirements
    # order_id is passed in URL, not in payload
    transformed = {
        "order_qty": int(data["quantity"]),
        "order_price": price_in_paise,
        "exchange": data["exchange"],  # Compulsory field
        "order_type": map_order_type(pricetype),
    }

    # MARKET emulation on modify: aggressive limit from the live book (caller-supplied)
    if pricetype == "MARKET" and market_price_paise:
        transformed["order_price"] = int(market_price_paise)

    # Add algo_params for stoploss orders (trigger_price is compulsory for stoploss)
    if pricetype in ("SL", "SL-M"):
        transformed["algo_params"] = {
            "trigger_price": trigger_price_in_paise
        }
        # SL-M -> marketable stop-limit beyond the trigger (see transform_data)
        if pricetype == "SL-M" and trigger_price_in_paise:
            buf = _market_protection_pct()
            if side == "BUY":
                transformed["order_price"] = int(round(trigger_price_in_paise * (1 + buf)))
            else:
                transformed["order_price"] = int(round(trigger_price_in_paise * (1 - buf)))

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

    Nubra is LIMIT-only for order entry (docs: "Do not send MARKET as
    price_type"). Every OpenAlgo pricetype therefore maps to LIMIT; MARKET and
    SL-M are emulated with an aggressive/marketable limit price (see
    transform_data / _market_protection_pct).
    """
    price_type_mapping = {
        "MARKET": "LIMIT",  # emulated via MPP limit (LTP +/- band), DAY validity
        "LIMIT": "LIMIT",
        "SL": "LIMIT",      # Stoploss Limit
        "SL-M": "LIMIT",    # emulated stop-market via marketable limit
    }
    return price_type_mapping.get(pricetype.upper(), "LIMIT")


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
