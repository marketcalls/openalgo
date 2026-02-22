# Mapping OpenAlgo API Request to Delta Exchange API Parameters
# Delta Exchange API docs: https://docs.delta.exchange

from database.token_db import get_br_symbol, get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_data(data, token):
    """
    Transforms the OpenAlgo API request structure to Delta Exchange POST /v2/orders payload.

    Delta Exchange order parameters:
        product_id           (int)  - Contract identifier (= token from master contract DB)
        product_symbol       (str)  - Contract symbol e.g. "BTCUSD"
        size                 (int)  - Number of contracts
        side                 (str)  - "buy" or "sell"
        order_type           (str)  - "limit_order" or "market_order"
        limit_price          (str)  - Required for limit orders (string for full precision)
        time_in_force        (str)  - "gtc" (default) or "ioc"
        stop_order_type      (str)  - "stop_loss_order" (for SL/SL-M orders)
        stop_price           (str)  - Required for stop orders
        stop_trigger_method  (str)  - "last_traded_price" | "mark_price" | "index_price"
                                      (default: "last_traded_price" for stop orders)
        trail_amount         (str)  - Trailing offset for trailing stop orders
        post_only            (bool) - True = maker-only; rejected if would take liquidity
        reduce_only          (bool) - True if order must only reduce an existing position
        client_order_id      (str)  - Optional caller-supplied order reference
        bracket_stop_loss_price           (str) - Bracket stop-loss trigger price
        bracket_stop_loss_limit_price     (str) - Bracket stop-loss limit price
        bracket_trail_amount              (str) - Bracket trailing stop offset
        bracket_stop_trigger_method       (str) - Trigger method for bracket stop
        bracket_take_profit_price         (str) - Bracket take-profit trigger price
        bracket_take_profit_limit_price   (str) - Bracket take-profit limit price
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"]) or data["symbol"]
    order_type = map_order_type(data["pricetype"])
    side = data["action"].lower()  # "buy" or "sell"

    transformed = {
        "product_id": int(token),
        "product_symbol": symbol,
        "size": int(data["quantity"]),
        "side": side,
        "order_type": order_type,
        "time_in_force": "gtc",
    }

    # Add limit_price for limit orders
    if order_type == "limit_order":
        price = data.get("price", "0")
        transformed["limit_price"] = str(price) if price else "0"

    # Handle stop-loss orders
    if data["pricetype"] in ("SL", "SL-M"):
        transformed["stop_order_type"] = "stop_loss_order"
        trigger = data.get("trigger_price", "0")
        transformed["stop_price"] = str(trigger) if trigger else "0"
        # Default trigger method; caller can override via data["stop_trigger_method"]
        transformed["stop_trigger_method"] = data.get(
            "stop_trigger_method", "last_traded_price"
        )
        # Trailing stop: forward trail_amount if provided
        if data.get("trail_amount"):
            transformed["trail_amount"] = str(data["trail_amount"])

    # Handle IOC validity
    if data.get("validity") == "IOC":
        transformed["time_in_force"] = "ioc"

    # Post-only (maker-only limit orders)
    if data.get("post_only") is True:
        transformed["post_only"] = True

    # Reduce-only: forward if explicitly provided
    if data.get("reduce_only") is True:
        transformed["reduce_only"] = True

    # Client order ID (strategy/signal reference)
    if data.get("client_order_id"):
        transformed["client_order_id"] = str(data["client_order_id"])

    # Bracket order fields — forward any that are present
    bracket_fields = (
        "bracket_stop_loss_price",
        "bracket_stop_loss_limit_price",
        "bracket_trail_amount",
        "bracket_stop_trigger_method",
        "bracket_take_profit_price",
        "bracket_take_profit_limit_price",
    )
    for field in bracket_fields:
        if data.get(field):
            transformed[field] = str(data[field])

    logger.info(f"[DeltaExchange] Transformed order: {transformed}")
    return transformed


def transform_modify_order_data(data):
    """
    Transforms OpenAlgo modify order data to Delta Exchange PUT /v2/orders payload.

    Delta Exchange modify fields:
        id           (int) - Order ID (extracted from composite "{product_id}:{order_id}")
        product_id   (int) - Contract ID
        size         (int) - New order size
        limit_price  (str) - New limit price
    """
    orderid = data["orderid"]
    # Composite ID format: "{product_id}:{order_id}"
    if ":" in str(orderid):
        product_id_str, order_id_str = str(orderid).split(":", 1)
        product_id = int(product_id_str)
        order_id = int(order_id_str)
    else:
        order_id = int(orderid)
        product_id = int(get_token(data["symbol"], data["exchange"]) or 0)

    transformed = {
        "id": order_id,
        "product_id": product_id,
        "size": int(data["quantity"]),
        "limit_price": str(data.get("price", "0")),
    }
    return transformed


def map_order_type(pricetype):
    """Maps OpenAlgo pricetype to Delta Exchange order_type string."""
    mapping = {
        "MARKET": "market_order",
        "LIMIT": "limit_order",
        "SL": "limit_order",
        "SL-M": "market_order",
    }
    return mapping.get(pricetype, "market_order")


def map_product_type(product):
    """
    Delta Exchange does not use equity-style product types (CNC/NRML/MIS).
    Returns the value as-is for interface compatibility.
    """
    return product


def reverse_map_product_type(br_product):
    """
    Maps Delta Exchange position category back to OpenAlgo product type.
    All crypto futures/options map to NRML.
    """
    return "NRML"


def map_exchange(br_exchange):
    """
    Maps a Delta Exchange broker exchange field back to OpenAlgo exchange code.
    Delta Exchange is a single crypto derivatives exchange.
    """
    return "CRYPTO"


def map_exchange_type(exchange):
    """
    Maps an OpenAlgo exchange code to the Delta Exchange context.
    All contracts on Delta Exchange are under a single platform.
    """
    return "CRYPTO"
