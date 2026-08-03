# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Nubra Trading API V3 (OMS V3 intent orders)
#
# V3 replaces the old snake_case /orders/v2 payload with a camelCase "intent
# order" model posted to /sentinel/orders/*. Every request -- create, modify,
# cancel and margin -- wraps its items in a top-level ``orders`` array, even
# when there is exactly one item.
#
# Docs: broker-api-docs/nubra-api-rest-api-v3-llm-builder.md
#       "Place Single Order" / "Modify Order" / "Cancel Order"

import re


def _paise(value):
    """Rupees -> integer paise. Nubra V3 carries every price as int paise."""
    try:
        price = float(value or 0)
    except (TypeError, ValueError):
        return 0
    return int(round(price * 100))


def sanitize_strat_tag(tag):
    """
    Normalize an OpenAlgo strategy name into a Nubra V3 ``stratTags`` entry.

    Nubra's rules (place-order "Important Rules"): pass exactly one tag and do
    not use underscores -- use a hyphenated or plain tag such as ``abc-def``.
    Anything outside [A-Za-z0-9-] is collapsed to a hyphen so an arbitrary
    OpenAlgo strategy name ("My Strategy_v2") becomes a legal tag
    ("my-strategy-v2").
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(tag or "openalgo")).strip("-").lower()
    return slug or "openalgo"


def map_order_side(action):
    """OpenAlgo action -> Nubra V3 ``side``. V3 uses bare BUY/SELL."""
    return "SELL" if str(action).upper() == "SELL" else "BUY"


def map_order_delivery_type(product):
    """
    OpenAlgo product -> Nubra V3 ``deliveryType``.

    V3 exposes only IDAY (intraday) and CNC. NRML has no distinct V3 value, so
    carry-forward F&O maps to CNC -- the same collapse the V2 mapping used.
    """
    return {
        "CNC": "CNC",
        "MIS": "IDAY",
        "NRML": "CNC",
    }.get(str(product).upper(), "IDAY")


def reverse_map_product_type(delivery_type):
    """Nubra V3 ``deliveryType`` -> OpenAlgo product."""
    return {"CNC": "CNC", "IDAY": "MIS"}.get(str(delivery_type).upper(), "MIS")


def map_price_type(pricetype):
    """
    OpenAlgo pricetype -> Nubra V3 ``priceType``.

    V3 supports a native MARKET price type (V2 did not, which is why the old
    integration emulated market orders with a protection-band limit). SL is a
    triggered LIMIT and SL-M a triggered MARKET -- the trigger itself lives in
    ``entryConfig``, not in the price type.
    """
    return {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "LIMIT",
        "SL-M": "MARKET",
    }.get(str(pricetype).upper(), "MARKET")


def map_validity_type(pricetype):
    """
    Nubra validated MARKET orders only with ``validityType: "IOC"`` and no
    ``entryPrice`` (place-order "Important Rules"). LIMIT families rest as DAY.
    """
    return "IOC" if map_price_type(pricetype) == "MARKET" else "DAY"


def build_entry_trigger(pricetype, trigger_price, action):
    """
    Build the V3 ``entryConfig`` for a stop order, or None when not a stop.

    OpenAlgo SL/SL-M carry a trigger_price; V3 expresses that as an LTP entry
    trigger. Stop semantics set the direction: a BUY stop arms above the
    trigger, a SELL stop arms below it.
    """
    if str(pricetype).upper() not in ("SL", "SL-M"):
        return None

    trigger_paise = _paise(trigger_price)
    if not trigger_paise:
        return None

    bound = "atOrAbove" if map_order_side(action) == "BUY" else "atOrBelow"
    return {"triggers": {"ltp": {bound: {"value": trigger_paise}}}}


def transform_data(data, token):
    """
    Transform an OpenAlgo place-order request into ONE Nubra V3 order item.

    The caller wraps the result as ``{"orders": [item]}`` before POSTing it to
    /sentinel/orders/create.

    OpenAlgo in:  action, product, pricetype, price, trigger_price, quantity
    Nubra V3 out: refId, qty, side, deliveryType, priceType, validityType,
                  isMultiLeg, executionMode, entryPrice, entryConfig, stratTags

    Note there is no order_type/ORDER_TYPE_STOPLOSS field in V3 -- a stop order
    is an ordinary order carrying an ``entryConfig`` trigger, and Nubra
    normalizes it back as ``intentOrderType: "TRIGGER"``.
    """
    pricetype = str(data.get("pricetype", "MARKET")).upper()

    item = {
        "refId": int(token),
        "qty": int(data["quantity"]),
        "side": map_order_side(data["action"]),
        "deliveryType": map_order_delivery_type(data["product"]),
        "priceType": map_price_type(pricetype),
        "validityType": map_validity_type(pricetype),
        "isMultiLeg": False,
        "executionMode": "ENTRY",
        "stratTags": [sanitize_strat_tag(data.get("strategy"))],
    }

    # entryPrice is required for LIMIT and must be omitted for MARKET.
    if item["priceType"] == "LIMIT":
        item["entryPrice"] = _paise(data.get("price"))

    entry_config = build_entry_trigger(pricetype, data.get("trigger_price"), data["action"])
    if entry_config:
        item["entryConfig"] = entry_config

    return item


def transform_modify_order_data(data, orderid):
    """
    Transform an OpenAlgo modify request into ONE Nubra V3 modify item.

    The caller wraps the result as ``{"orders": [item]}`` for
    /sentinel/orders/modify. V3 modify is an order-level patch keyed by
    ``orderId`` (the intentOrderId) -- field names stay aligned to the
    create-order shape, and ``legs``/``isMultiLeg`` are never resent.
    """
    pricetype = str(data.get("pricetype", "MARKET")).upper()

    item = {
        "orderId": int(orderid),
        "qty": int(data["quantity"]),
        "deliveryType": map_order_delivery_type(data.get("product", "MIS")),
        "priceType": map_price_type(pricetype),
        "validityType": map_validity_type(pricetype),
        "executionMode": "ENTRY",
    }

    if item["priceType"] == "LIMIT":
        item["entryPrice"] = _paise(data.get("price"))

    entry_config = build_entry_trigger(
        pricetype, data.get("trigger_price"), data.get("action", "BUY")
    )
    if entry_config:
        item["entryConfig"] = entry_config

    return item


def map_product_type(product):
    """OpenAlgo product -> V3 deliveryType, for position lookups."""
    return map_order_delivery_type(product)
