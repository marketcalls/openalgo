# broker/arrow/api/order_api.py

import threading
import time

from broker.arrow.api.baseurl import ROOT_URL, get_arrow_headers
from broker.arrow.mapping.transform_data import (
    map_product_type,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_br_symbol, get_oa_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Arrow supports only the "regular" order variety.
_ORDER_VARIETY = "regular"


def get_api_response(endpoint, auth, method="GET", payload=None):
    """Make a request to the Arrow API using the shared pooled httpx client.

    Args:
        endpoint: API path (e.g. '/user/orders').
        auth: the JWT access token.
        method: HTTP verb.
        payload: dict body for POST/PATCH (sent as JSON).

    Returns:
        Parsed JSON response (dict).
    """
    client = get_httpx_client()
    headers = get_arrow_headers(auth, with_json=payload is not None)
    url = f"{ROOT_URL}{endpoint}"

    try:
        method = method.upper()
        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, headers=headers, json=payload)
        elif method == "PATCH":
            response = client.patch(url, headers=headers, json=payload)
        elif method == "DELETE":
            response = client.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        return response.json()
    except Exception as e:
        error_msg = str(e)
        try:
            if hasattr(e, "response") and e.response is not None:
                error_msg = e.response.json().get("message", error_msg)
        except Exception:
            pass
        logger.exception(f"Arrow API request failed: {error_msg}")
        raise


def get_order_book(auth):
    return get_api_response("/user/orders", auth)


def get_trade_book(auth):
    return get_api_response("/user/trades", auth)


def get_positions(auth):
    return get_api_response("/user/positions", auth)


def get_holdings(auth):
    return get_api_response("/user/holdings", auth)


# --- Per-Symbol Smart Order Lock ---
# Mirrors the Zerodha adapter: only one smart order per symbol executes at a
# time; others queue and each gets a fresh position book.
_symbol_locks = {}
_symbol_locks_lock = threading.Lock()

# --- Position Book Cache (1s TTL) ---
_position_cache = {}
_position_cache_lock = threading.Lock()
_POSITION_CACHE_TTL = 1.0


def _get_symbol_lock(symbol, exchange, product):
    key = f"{symbol}:{exchange}:{product}"
    with _symbol_locks_lock:
        if key not in _symbol_locks:
            _symbol_locks[key] = threading.Lock()
        return _symbol_locks[key]


def _get_cached_positions(auth):
    with _position_cache_lock:
        now = time.monotonic()
        cached = _position_cache.get(auth)
        if cached and (now - cached["timestamp"]) < _POSITION_CACHE_TTL:
            logger.debug("Position book served from cache")
            return cached["data"]

    positions_data = get_positions(auth)

    with _position_cache_lock:
        _position_cache[auth] = {"data": positions_data, "timestamp": time.monotonic()}
    return positions_data


def _invalidate_position_cache(auth):
    with _position_cache_lock:
        _position_cache.pop(auth, None)


def get_open_position(tradingsymbol, exchange, product, auth):
    """Return net quantity (as str) for a symbol/exchange/product.

    `product` is the Arrow product code (I/C/M), as passed by the smart-order
    flow via map_product_type().
    """
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    positions_data = _get_cached_positions(auth)
    net_qty = "0"

    # Arrow returns a FLAT list of positions under `data` (unlike Zerodha's
    # data.net nesting).
    if positions_data and positions_data.get("data"):
        for position in positions_data["data"]:
            if (
                position.get("symbol") == tradingsymbol
                and position.get("exchange") == exchange
                and position.get("product") == product
            ):
                net_qty = str(position.get("qty", "0"))
                logger.debug(f"Net Quantity {net_qty}")
                break

    return net_qty


def place_order_api(data, auth):
    """Place a regular order on Arrow.

    Returns (response, response_data, orderid). `response.status` is set so the
    service layer's `res.status == 200` success check works.
    """
    payload = transform_data(data)
    # debug, not info: console writes from the order hot path cost real
    # milliseconds on Windows terminals; use LOG_LEVEL=DEBUG to see payloads
    logger.debug(f"Payload for Arrow place_order_api: {payload}")

    client = get_httpx_client()
    headers = get_arrow_headers(auth, with_json=True)

    response = client.post(
        f"{ROOT_URL}/order/{_ORDER_VARIETY}", headers=headers, json=payload
    )
    logger.debug(f"Arrow raw response: status={response.status_code}, body={response.text}")

    response_data = response.json()

    if response_data.get("status") == "success":
        # Place-order success returns data.orderNo.
        orderid = response_data.get("data", {}).get("orderNo")
    else:
        orderid = None

    # Backward-compat: services check `res.status == 200`.
    response.status = response.status_code
    return response, response_data, orderid


def place_smartorder_api(data, auth):
    """Reconcile the live position to data['position_size'] and place the
    difference order. Same algorithm as the Zerodha reference."""
    res = None
    response_data = {"status": "error", "message": "No action required or invalid parameters"}
    orderid = None

    try:
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        product = data.get("product")

        if not all([symbol, exchange, product]):
            logger.debug("Missing required parameters in place_smartorder_api")
            return res, response_data, orderid

        symbol_lock = _get_symbol_lock(symbol, exchange, product)

        with symbol_lock:
            position_size = int(data.get("position_size", "0"))
            current_position = int(
                get_open_position(symbol, exchange, map_product_type(product), auth)
            )

            logger.debug(f"position_size: {position_size}")
            logger.debug(f"Open Position: {current_position}")

            action = None
            quantity = 0

            if position_size == 0 and current_position == 0:
                action = data.get("action", "BUY").upper()
                quantity = int(data.get("quantity", "0"))
            elif position_size == 0 and current_position > 0:
                action = "SELL"
                quantity = abs(current_position)
            elif position_size == 0 and current_position < 0:
                action = "BUY"
                quantity = abs(current_position)
            elif current_position == 0:
                action = "BUY" if position_size > 0 else "SELL"
                quantity = abs(position_size)
            else:
                if position_size > current_position:
                    action = "BUY"
                    quantity = position_size - current_position
                elif position_size < current_position:
                    action = "SELL"
                    quantity = current_position - position_size

            if action and quantity > 0:
                order_data = data.copy()
                order_data["action"] = action
                order_data["quantity"] = str(quantity)

                res, response, orderid = place_order_api(order_data, auth)
                _invalidate_position_cache(auth)
                return res, response, orderid

            logger.debug("No action required or invalid quantity")
            response_data = {
                "status": "success",
                "message": "No action needed. Position already matched.",
            }
            return res, response_data, orderid

    except Exception as e:
        error_msg = f"Error in place_smartorder_api: {e}"
        logger.exception(error_msg)
        response_data = {"status": "error", "message": error_msg}
        return res, response_data, orderid


def close_all_positions(current_api_key, auth):
    """Square off all open positions by firing market orders."""
    positions_response = get_positions(auth)

    if not positions_response or not positions_response.get("data"):
        return {"message": "No Open Positions Found"}, 200

    for position in positions_response["data"]:
        qty = int(position.get("qty", 0))
        if qty == 0:
            continue

        action = "SELL" if qty > 0 else "BUY"
        quantity = abs(qty)

        symbol = get_oa_symbol(position["symbol"], position["exchange"])
        place_order_payload = {
            "apikey": current_api_key,
            "strategy": "Squareoff",
            "symbol": symbol,
            "action": action,
            "exchange": position["exchange"],
            "pricetype": "MARKET",
            "product": reverse_map_product_type(position["exchange"], position.get("product")),
            "quantity": str(quantity),
        }
        logger.debug(f"Close position payload: {place_order_payload}")
        _, api_response, _ = place_order_api(place_order_payload, auth)
        logger.debug(f"Close position response: {api_response}")

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """Cancel an order. Arrow returns a plain-string ack on success."""
    try:
        client = get_httpx_client()
        headers = get_arrow_headers(auth)
        response = client.delete(
            f"{ROOT_URL}/order/{_ORDER_VARIETY}/{orderid}", headers=headers
        )
        response.raise_for_status()
        logger.debug(f"Arrow cancel order response: {response.text}")

        # Cancel returns a plain string ("order cancellation request accepted"),
        # so success is signalled by the 200 status, not a JSON body.
        return {"status": "success", "orderid": orderid}, 200
    except Exception as e:
        error_msg = str(e)
        try:
            if hasattr(e, "response") and e.response is not None:
                error_msg = e.response.json().get("message", error_msg)
        except Exception:
            pass
        logger.exception(f"Error canceling order {orderid}: {error_msg}")
        return {"status": "error", "message": f"Failed to cancel order: {error_msg}"}, 500


def modify_order(data, auth):
    """Modify an order via PATCH /order/regular/{orderid}."""
    payload = transform_modify_order_data(data)
    logger.debug(f"Arrow modify order payload: {payload}")

    client = get_httpx_client()
    headers = get_arrow_headers(auth, with_json=True)

    response = client.patch(
        f"{ROOT_URL}/order/{_ORDER_VARIETY}/{data['orderid']}",
        headers=headers,
        json=payload,
    )
    response_data = response.json()
    logger.debug(f"Arrow modify order response: {response_data}")

    response.status = response.status_code

    if response_data.get("status") == "success":
        orderid = response_data.get("data", {}).get("orderNo", data["orderid"])
        return {"status": "success", "orderid": orderid}, 200
    return {
        "status": "error",
        "message": response_data.get("message", "Failed to modify order"),
    }, response.status_code


def cancel_all_orders_api(data, auth):
    """Cancel every open / trigger-pending order."""
    order_book_response = get_order_book(auth)
    if not order_book_response or order_book_response.get("status") != "success":
        return [], []

    orders = order_book_response.get("data", []) or []
    # Arrow order statuses: PENDING, OPEN, COMPLETE, CANCELLED, REJECTED,
    # TRIGGER_PENDING. Cancel the still-cancellable ones.
    cancellable = {"OPEN", "PENDING", "TRIGGER_PENDING"}
    orders_to_cancel = [o for o in orders if o.get("orderStatus") in cancellable]

    canceled_orders = []
    failed_cancellations = []
    for order in orders_to_cancel:
        # TODO(arrow): confirm the order-id field name in /user/orders
        # (place returns `orderNo`; the order book may use `id` or `orderNo`).
        orderid = order.get("orderNo") or order.get("id")
        _, status_code = cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
