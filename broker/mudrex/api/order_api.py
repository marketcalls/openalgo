"""
Mudrex order management module.

Endpoints used:
    POST   /futures/{asset_id}/order?is_symbol     — place order (symbol-first)
    PATCH  /futures/orders/{order_id}               — amend order
    DELETE /futures/orders/{order_id}               — cancel order
    GET    /futures/orders                          — open orders
    GET    /futures/orders/history                  — order history
    GET    /futures/positions                       — open positions
    POST   /futures/positions/{position_id}/close   — close position

Limitations:
    - SL/SL-M at the order level is NOT supported; use position-level risk
      orders instead (POST /futures/positions/{id}/riskorder).
    - Isolated margin only.
    - Rate limit: 2 req/s (configurable via MUDREX_RATE_LIMIT env var).
"""

import os
import time

from broker.mudrex.api.mudrex_http import mudrex_request
from broker.mudrex.mapping.transform_data import (
    map_action,
    map_order_type,
    reverse_map_action,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_br_symbol, get_oa_symbol, get_symbol, get_token
from utils.logging import get_logger

logger = get_logger(__name__)

_CLOSE_DELAY_MS = int(os.getenv("MUDREX_CLOSE_POSITION_DELAY_MS", "500"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Resp:
    """Minimal response shim for callers that check ``.status_code``."""
    def __init__(self, code: int = 200):
        self.status_code = code
        self.status = code


def _auth_secret(auth: str) -> str:
    """Return the API secret to use for requests."""
    return auth or os.getenv("BROKER_API_SECRET", "")


# ---------------------------------------------------------------------------
# Order book / trade book
# ---------------------------------------------------------------------------

def get_order_book(auth: str) -> list:
    """Fetch open + historical orders for the order book UI."""
    secret = _auth_secret(auth)
    all_orders: list = []

    open_data = mudrex_request("/futures/orders", method="GET", params={"limit": "100"}, auth=secret)
    if open_data.get("success"):
        batch = open_data.get("data") or []
        if isinstance(batch, list):
            all_orders.extend(batch)

    hist_data = mudrex_request("/futures/orders/history", method="GET", params={"limit": "100"}, auth=secret)
    if hist_data.get("success"):
        batch = hist_data.get("data") or []
        if isinstance(batch, list):
            all_orders.extend(batch)

    return all_orders


def get_trade_book(auth: str) -> list:
    """Fetch filled orders as trades."""
    secret = _auth_secret(auth)
    hist = mudrex_request("/futures/orders/history", method="GET", params={"limit": "100"}, auth=secret)
    if hist.get("success"):
        orders = hist.get("data") or []
        return [o for o in orders if isinstance(o, dict) and o.get("status", "").upper() == "FILLED"]
    return []


# ---------------------------------------------------------------------------
# Positions / holdings
# ---------------------------------------------------------------------------

def get_positions(auth: str) -> list:
    """Fetch all open positions."""
    secret = _auth_secret(auth)
    data = mudrex_request("/futures/positions", method="GET", auth=secret)
    if data.get("success"):
        positions = data.get("data")
        if positions is None:
            return []
        if isinstance(positions, list):
            return positions
    return []


def get_holdings(auth: str) -> list:
    """Mudrex is futures-only; holdings are not applicable."""
    return []


def get_open_position(tradingsymbol: str, exchange: str, product: str, auth: str) -> str:
    """Return the net position size for a given symbol.

    Positive = long, negative = short, "0" = flat.
    """
    br_symbol = get_br_symbol(tradingsymbol, exchange) or tradingsymbol
    positions = get_positions(auth)

    for pos in positions:
        if not isinstance(pos, dict):
            continue
        if pos.get("symbol") == br_symbol:
            qty = float(pos.get("quantity", 0))
            ot = pos.get("order_type", "").upper()
            return str(qty if ot == "LONG" else -qty)

    return "0"


# ---------------------------------------------------------------------------
# Place order
# ---------------------------------------------------------------------------

def place_order_api(data: dict, auth: str):
    """Place a new order on Mudrex.

    Uses POST /futures/{symbol}/order?is_symbol to avoid a token→UUID lookup.

    Returns:
        ``(response_shim, response_dict, order_id)``
    """
    secret = _auth_secret(auth)

    symbol = data.get("symbol", "")
    br_symbol = get_br_symbol(symbol, data.get("exchange", "CRYPTO_FUT")) or symbol

    try:
        payload = transform_data(data, "")
    except ValueError as exc:
        return _Resp(400), {"status": "error", "message": str(exc)}, None

    # Resolve leverage from DB if not explicitly provided
    leverage = data.get("leverage")
    if not leverage:
        try:
            from database.leverage_db import get_leverage
            db_lev = get_leverage()
            if db_lev and float(db_lev) > 0:
                leverage = float(db_lev)
        except Exception:
            pass
    if leverage:
        payload["leverage"] = float(leverage)
    elif "leverage" not in payload or payload["leverage"] == 0:
        payload["leverage"] = 1

    endpoint = f"/futures/{br_symbol}/order?is_symbol"
    logger.info(f"[Mudrex] POST {endpoint} payload={payload}")
    result = mudrex_request(endpoint, method="POST", payload=payload, auth=secret)
    logger.debug(f"[Mudrex] place_order response: {result}")

    if result.get("success"):
        order_data = result.get("data", {})
        order_id = order_data.get("order_id", "")
        return _Resp(200), {"status": "success", "orderid": str(order_id)}, str(order_id)

    errors = result.get("errors", [])
    msg = errors[0].get("text", str(errors)) if errors else result.get("message", str(result))
    logger.error(f"[Mudrex] Order placement failed: {msg}")
    return _Resp(400), {"status": "error", "message": msg}, None


def place_smartorder_api(data: dict, auth: str):
    """Smart order: adjust position to target size, or place fresh order."""
    symbol = data.get("symbol", "")
    exchange = data.get("exchange", "CRYPTO_FUT")
    product = data.get("product", "NRML")
    position_size = float(data.get("position_size", 0))

    current_position = float(get_open_position(symbol, exchange, product, auth))
    logger.info(f"[Mudrex] SmartOrder: target={position_size} current={current_position}")

    if position_size == 0 and current_position == 0 and float(data.get("quantity", 0)) != 0:
        return place_order_api(data, auth)

    if position_size == current_position:
        msg = (
            "No OpenPosition Found. Not placing Exit order."
            if float(data.get("quantity", 0)) == 0
            else "No action needed. Position size matches current position"
        )
        return None, {"status": "success", "message": msg}, None

    action = None
    quantity = 0.0

    if position_size == 0 and current_position > 0:
        action, quantity = "SELL", abs(current_position)
    elif position_size == 0 and current_position < 0:
        action, quantity = "BUY", abs(current_position)
    elif current_position == 0:
        action = "BUY" if position_size > 0 else "SELL"
        quantity = abs(position_size)
    elif position_size > current_position:
        action, quantity = "BUY", position_size - current_position
    elif position_size < current_position:
        action, quantity = "SELL", current_position - position_size

    if action:
        order_data = data.copy()
        order_data["action"] = action
        order_data["quantity"] = str(quantity)
        return place_order_api(order_data, auth)

    return None, {"status": "success", "message": "No action needed"}, None


def place_bracket_order_api(data: dict, auth: str):
    """Bracket order: forward SL/TP params alongside the main order.

    Mudrex supports ``is_stoploss``, ``stoploss_price``, ``is_takeprofit``,
    ``takeprofit_price`` directly in the place-order payload.
    """
    return place_order_api(data, auth)


# ---------------------------------------------------------------------------
# Modify order  (native PATCH)
# ---------------------------------------------------------------------------

def modify_order(data: dict, auth: str):
    """Amend an existing order via PATCH /futures/orders/{order_id}.

    Returns ``(response_dict_or_message, status_code)`` matching the contract
    used by ``services/modify_order_service.py``.
    """
    secret = _auth_secret(auth)
    order_id = data.get("orderid", "")

    try:
        payload = transform_modify_order_data(data)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}, 400

    endpoint = f"/futures/orders/{order_id}"
    logger.info(f"[Mudrex] PATCH {endpoint} payload={payload}")
    result = mudrex_request(endpoint, method="PATCH", payload=payload, auth=secret)

    if result.get("success"):
        return {"status": "success", "message": "Order modified"}, 200

    errors = result.get("errors", [])
    msg = errors[0].get("text", str(errors)) if errors else result.get("message", str(result))
    logger.error(f"[Mudrex] Order modify failed: {msg}")
    return {"status": "error", "message": msg}, 400


# ---------------------------------------------------------------------------
# Cancel order
# ---------------------------------------------------------------------------

def cancel_order(orderid, auth: str):
    """Cancel an order via DELETE /futures/orders/{order_id}.

    Returns ``(response_dict_or_message, status_code)``.
    """
    secret = _auth_secret(auth)
    order_id = str(orderid)
    endpoint = f"/futures/orders/{order_id}"
    logger.info(f"[Mudrex] DELETE {endpoint}")
    result = mudrex_request(endpoint, method="DELETE", auth=secret)

    if result.get("success"):
        return {"status": "success", "message": "Order cancelled"}, 200

    errors = result.get("errors", [])
    msg = errors[0].get("text", str(errors)) if errors else result.get("message", str(result))
    logger.error(f"[Mudrex] Cancel failed for {order_id}: {msg}")
    return {"status": "error", "message": msg}, 400


# ---------------------------------------------------------------------------
# Cancel all orders
# ---------------------------------------------------------------------------

def cancel_all_orders_api(data: dict, auth: str):
    """Cancel all open orders.

    Returns ``(cancelled_list, failed_list)``.
    """
    secret = _auth_secret(auth)
    open_data = mudrex_request("/futures/orders", method="GET", params={"limit": "200"}, auth=secret)
    orders = []
    if open_data.get("success"):
        orders = open_data.get("data") or []

    if not orders:
        return [], []

    cancelled = []
    failed = []
    for order in orders:
        oid = order.get("id", "")
        result = mudrex_request(f"/futures/orders/{oid}", method="DELETE", auth=secret)
        if result.get("success"):
            cancelled.append(oid)
        else:
            failed.append(oid)

    return cancelled, failed


# ---------------------------------------------------------------------------
# Close all positions
# ---------------------------------------------------------------------------

def close_all_positions(current_api_key: str, auth: str):
    """Close all open positions via POST /futures/positions/{id}/close.

    Respects rate limit by sleeping ``MUDREX_CLOSE_POSITION_DELAY_MS`` between
    calls.
    """
    positions = get_positions(auth)
    if not positions:
        return {"message": "No Open Positions Found"}, 200

    secret = _auth_secret(auth)
    delay_s = _CLOSE_DELAY_MS / 1000.0
    failed: list[dict[str, str]] = []
    attempted = 0

    for pos in positions:
        if not isinstance(pos, dict):
            continue
        position_id = pos.get("id", "")
        if not position_id:
            continue

        attempted += 1
        endpoint = f"/futures/positions/{position_id}/close"
        logger.info(f"[Mudrex] POST {endpoint}")
        result = mudrex_request(endpoint, method="POST", auth=secret)

        if not result.get("success"):
            errors = result.get("errors", [])
            err_text = errors[0].get("text", str(errors)) if errors else str(result)
            logger.error(f"[Mudrex] Failed to close position {position_id}: {err_text}")
            failed.append({"position_id": position_id, "error": err_text})

        if delay_s > 0:
            time.sleep(delay_s)

    if failed:
        closed_ok = attempted - len(failed)
        return (
            {
                "status": "error",
                "message": (
                    f"{len(failed)} of {attempted} close request(s) failed "
                    f"({closed_ok} succeeded)"
                ),
                "failed": failed,
            },
            500,
        )

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200
