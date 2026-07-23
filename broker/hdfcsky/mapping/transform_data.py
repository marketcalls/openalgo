# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping HDFC Sky Trading Parameters (developer.hdfcsky.com)
#
# HDFC Sky's vocabulary is very close to OpenAlgo's -- the only real
# translation is the stop-loss-market order type:
#   product   : CNC / MIS / NRML     -> identical
#   side      : BUY / SELL           -> order_side, identical
#   pricetype : MARKET/LIMIT/SL/SL-M -> MARKET / LIMIT / SL / SLM
#
# Instruments are addressed by `instrument_token` (the Security Master's
# exchange_token), NOT by trading symbol.

import time

from broker.hdfcsky.api.baseurl import get_client_id
from broker.hdfcsky.mapping.exchange import to_rest_exchange
from database.token_db import get_token

# OpenAlgo pricetype -> HDFC Sky `order_type`.
_ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "SL",
    "SL-M": "SLM",
}

# HDFC Sky `order_type` -> OpenAlgo pricetype (normalizing responses).
_REVERSE_ORDER_TYPE_MAP = {
    "MARKET": "MARKET",
    "LIMIT": "LIMIT",
    "SL": "SL",
    "SLM": "SL-M",
    "SL-M": "SL-M",
}

# Products are identical in both vocabularies; the maps exist so callers have
# one place to look and unknown values degrade predictably.
_PRODUCT_MAP = {"CNC": "CNC", "NRML": "NRML", "MIS": "MIS"}
_REVERSE_PRODUCT_MAP = {"CNC": "CNC", "NRML": "NRML", "MIS": "MIS", "MTF": "CNC"}

# Numeric product codes used by the margin calculator, from the GenericDTO
# proto's ProdType enum (NRML = 0, CNC = 1, MIS = 2).
PRODUCT_NUMERIC_CODES = {"NRML": "0", "CNC": "1", "MIS": "2"}


def map_order_type(pricetype):
    """OpenAlgo pricetype -> HDFC Sky order_type. Defaults to MARKET."""
    return _ORDER_TYPE_MAP.get(str(pricetype).upper(), "MARKET")


def reverse_map_order_type(order_type):
    return _REVERSE_ORDER_TYPE_MAP.get(str(order_type).upper(), order_type)


def map_product_type(product):
    """OpenAlgo product -> HDFC Sky product. Defaults to MIS."""
    return _PRODUCT_MAP.get(str(product).upper(), "MIS")


def reverse_map_product_type(exchange, product):
    """HDFC Sky product -> OpenAlgo product. `exchange` is accepted for
    signature parity with the other brokers (HDFC Sky's codes are
    exchange-independent)."""
    return _REVERSE_PRODUCT_MAP.get(str(product).upper())


def map_transaction_type(action):
    return "BUY" if str(action).upper() == "BUY" else "SELL"


def _user_order_id():
    """HDFC Sky wants a caller-generated numeric `user_order_id`. Millisecond
    epoch truncated to 9 digits keeps it unique within a trading day and well
    inside the field's numeric range."""
    return int(time.time() * 1000) % 1_000_000_000


def _resolve_token(symbol, exchange):
    token = get_token(symbol, exchange)
    if token is None:
        raise ValueError(f"No HDFC Sky instrument token found for {exchange}:{symbol}")
    return str(token)


def transform_data(data, auth_token):
    """OpenAlgo order dict -> HDFC Sky place-order payload.

    OpenAlgo order fields: symbol, exchange, action, pricetype, quantity,
    product, price, trigger_price, disclosed_quantity, strategy.
    """
    exchange = data["exchange"]
    order_type = map_order_type(data.get("pricetype", "MARKET"))

    payload = {
        "exchange": to_rest_exchange(exchange),
        "instrument_token": _resolve_token(data["symbol"], exchange),
        "client_id": get_client_id(auth_token),
        "order_type": order_type,
        "order_side": map_transaction_type(data["action"]),
        "product": map_product_type(data.get("product", "MIS")),
        "quantity": int(data.get("quantity", 0)),
        "price": float(data.get("price", 0) or 0),
        "trigger_price": float(data.get("trigger_price", 0) or 0),
        "disclosed_quantity": int(data.get("disclosed_quantity", 0) or 0),
        "validity": "DAY",
        "device": "WEB",
        "execution_type": "REGULAR",
        "amo": False,
        "user_order_id": _user_order_id(),
    }

    strategy = str(data.get("strategy", "") or "").strip()
    if strategy:
        # Optional order tagging; HDFC Sky expects an array of strings.
        payload["tags"] = [strategy[:32]]

    return payload


def transform_modify_order_data(data, auth_token):
    """OpenAlgo modify-order dict -> HDFC Sky modify payload.

    HDFC Sky modifies via PUT /oapi/v1/orders with the SAME body shape as
    placement plus `oms_order_id`. The product cannot be changed, but the
    field is still required by the validator.
    """
    exchange = data["exchange"]
    order_type = map_order_type(data.get("pricetype", "MARKET"))

    return {
        "exchange": to_rest_exchange(exchange),
        "instrument_token": _resolve_token(data["symbol"], exchange),
        "client_id": get_client_id(auth_token),
        "oms_order_id": str(data["orderid"]),
        "order_type": order_type,
        "product": map_product_type(data.get("product", "MIS")),
        "quantity": int(data.get("quantity", 0)),
        "price": float(data.get("price", 0) or 0),
        "trigger_price": float(data.get("trigger_price", 0) or 0),
        "disclosed_quantity": int(data.get("disclosed_quantity", 0) or 0),
        "validity": "DAY",
        "execution_type": "REGULAR",
    }
