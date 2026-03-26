"""
Mapping OpenAlgo API request parameters to Mudrex API format.

Mudrex place-order endpoint: POST /futures/{asset_id}/order
    order_type   : "LONG" | "SHORT"   (position direction)
    trigger_type : "MARKET" | "LIMIT"
    quantity     : decimal number
    order_price  : decimal number (for LIMIT orders)
    leverage     : decimal number
    reduce_only  : bool

Mudrex does NOT support SL or SL-M order types at the order level.
Position-level SL/TP is available via POST /futures/positions/{id}/riskorder.
"""

from database.token_db import get_br_symbol, get_token
from utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Order type mapping
# ---------------------------------------------------------------------------

UNSUPPORTED_PRICE_TYPES = {"SL", "SL-M"}
SL_ERROR_MESSAGE = (
    "Conditional orders (SL/SL-M) not supported on Mudrex at the order level. "
    "Use position-level SL/TP via the set_sl_tp endpoint."
)


def map_order_type(pricetype: str) -> str:
    """Map OpenAlgo pricetype to Mudrex trigger_type.

    Raises ValueError for unsupported conditional order types.
    """
    upper = pricetype.upper()
    if upper in UNSUPPORTED_PRICE_TYPES:
        raise ValueError(SL_ERROR_MESSAGE)
    mapping = {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
    }
    return mapping.get(upper, "MARKET")


# ---------------------------------------------------------------------------
# Product / exchange mapping
# ---------------------------------------------------------------------------

def map_product_type(product: str) -> str:
    """Map OpenAlgo product type to Mudrex margin mode.

    Mudrex only supports isolated margin.
    """
    return "isolated"


def reverse_map_product_type(br_product: str) -> str:
    """Map Mudrex margin mode back to OpenAlgo product type."""
    return "NRML"


def map_exchange_type(exchange: str) -> str:
    """Map OpenAlgo exchange code to Mudrex context."""
    return "CRYPTO_FUT"


def map_exchange(br_exchange: str) -> str:
    """Map Mudrex brexchange back to OpenAlgo exchange code."""
    return "CRYPTO_FUT"


# ---------------------------------------------------------------------------
# Action mapping
# ---------------------------------------------------------------------------

def map_action(action: str) -> str:
    """Map OpenAlgo action (BUY/SELL) to Mudrex order_type (LONG/SHORT)."""
    return "LONG" if action.upper() == "BUY" else "SHORT"


def reverse_map_action(order_type: str) -> str:
    """Map Mudrex order_type (LONG/SHORT) back to OpenAlgo action."""
    return "BUY" if order_type.upper() == "LONG" else "SELL"


# ---------------------------------------------------------------------------
# Transform order data
# ---------------------------------------------------------------------------

def transform_data(data: dict, token: str) -> dict:
    """Transform OpenAlgo order request to Mudrex POST /futures/{asset_id}/order payload.

    The ``token`` is the Mudrex ``asset_id`` (UUID) from the master contract DB.
    """
    trigger_type = map_order_type(data["pricetype"])
    order_type = map_action(data["action"])

    payload: dict = {
        "leverage": float(data.get("leverage", 1)),
        "quantity": float(data["quantity"]),
        "order_type": order_type,
        "trigger_type": trigger_type,
    }

    if trigger_type == "LIMIT":
        payload["order_price"] = float(data.get("price", 0))

    if data.get("reduce_only") is True:
        payload["reduce_only"] = True

    return payload


def transform_modify_order_data(data: dict) -> dict:
    """Transform OpenAlgo modify-order request to Mudrex PATCH /futures/orders/{order_id} payload.

    Only fields that are modifiable (quantity, order_price, trigger_type) are included.
    """
    pricetype = str(data.get("pricetype", "")).upper()
    if pricetype in UNSUPPORTED_PRICE_TYPES:
        raise ValueError(SL_ERROR_MESSAGE)

    payload: dict = {}

    quantity = data.get("quantity")
    if quantity is not None:
        payload["quantity"] = float(quantity)

    price = data.get("price")
    if price is not None:
        payload["order_price"] = float(price)

    if pricetype:
        payload["trigger_type"] = map_order_type(pricetype)

    return payload
