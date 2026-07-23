# broker/hdfcsky/api/order_api.py
#
# HDFC Sky order management.
#
#   POST   /oapi/v1/orders                place regular / AMO order
#   PUT    /oapi/v1/orders                modify order
#   DELETE /oapi/v1/orders/<oms_order_id> cancel order
#   GET    /oapi/v1/orders?type=pending   order book (pending)
#   GET    /oapi/v1/orders?type=completed order book (completed)
#   GET    /oapi/v1/trades                trade book
#   GET    /oapi/v1/positions?type=live|historical   positions
#   GET    /oapi/v1/holdings              demat holdings
#
# Every call needs `api_key` (and usually `client_id`) as QUERY params plus the
# mandatory Authorization / User-Agent headers -- see api/baseurl.py.

import threading
import time

from broker.hdfcsky.api.baseurl import base_params, get_hdfcsky_headers, get_root_url
from broker.hdfcsky.mapping.exchange import to_oa_exchange
from broker.hdfcsky.mapping.order_data import CANCELLABLE_STATUSES
from broker.hdfcsky.mapping.transform_data import (
    map_product_type,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_oa_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _request(method, endpoint, auth, params=None, payload=None, with_client_id=True):
    """Issue an authenticated HDFC Sky request and return the parsed JSON."""
    client = get_httpx_client()
    headers = get_hdfcsky_headers(auth, with_json=payload is not None)
    url = f"{get_root_url()}{endpoint}"

    query = base_params(auth, client_id=with_client_id)
    if params:
        query.update(params)

    method = method.upper()
    if method == "GET":
        response = client.get(url, headers=headers, params=query)
    elif method == "POST":
        response = client.post(url, headers=headers, params=query, json=payload)
    elif method == "PUT":
        response = client.put(url, headers=headers, params=query, json=payload)
    elif method == "DELETE":
        response = client.delete(url, headers=headers, params=query)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    try:
        return response.json()
    except ValueError:
        raise ValueError(
            f"HDFC Sky returned a non-JSON response (HTTP {response.status_code}) "
            f"for {endpoint}: {response.text[:200]}"
        ) from None


def get_order_book(auth):
    """Combined pending + completed order book.

    HDFC Sky splits the book across two calls (`type=pending` and
    `type=completed`); OpenAlgo's orderbook is a single list, so both are
    fetched and merged. A failure on one half is logged and skipped rather
    than sinking the whole book.
    """
    orders = []
    for order_type in ("pending", "completed"):
        try:
            payload = _request("GET", "/oapi/v1/orders", auth, params={"type": order_type})
            if payload.get("status") == "error":
                logger.warning(
                    f"HDFC Sky {order_type} order book error: {payload.get('message')}"
                )
                continue
            rows = (payload.get("data") or {}).get("orders") or []
            orders.extend(rows)
        except Exception as e:
            logger.exception(f"Error fetching HDFC Sky {order_type} orders: {e}")
    return {"status": "success", "data": {"orders": orders}}


def get_trade_book(auth):
    return _request("GET", "/oapi/v1/trades", auth)


def get_positions(auth):
    """Net (carry-forward aware) positions -- `type=historical` is HDFC Sky's
    netwise view, which is what OpenAlgo's position book represents."""
    return _request("GET", "/oapi/v1/positions", auth, params={"type": "historical"})


def get_holdings(auth):
    return _request("GET", "/oapi/v1/holdings", auth)


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
        cached = _position_cache.get(auth)
        if cached and (time.monotonic() - cached["timestamp"]) < _POSITION_CACHE_TTL:
            logger.debug("Position book served from cache")
            return cached["data"]

    positions_data = get_positions(auth)

    with _position_cache_lock:
        _position_cache[auth] = {"data": positions_data, "timestamp": time.monotonic()}
    return positions_data


def _invalidate_position_cache(auth):
    with _position_cache_lock:
        _position_cache.pop(auth, None)


def _position_rows(positions_data):
    """HDFC Sky returns positions as a FLAT list under `data`."""
    if not positions_data:
        return []
    data = positions_data.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("positions") or []
    return []


def get_open_position(tradingsymbol, exchange, product, auth):
    """Net quantity (as str) for a symbol/exchange/product.

    `product` arrives as the HDFC Sky product code (CNC/NRML/MIS), mapped by
    the smart-order flow via map_product_type().
    """
    from database.token_db import get_br_symbol

    br_symbol = get_br_symbol(tradingsymbol, exchange)
    net_qty = "0"

    for position in _position_rows(_get_cached_positions(auth)):
        if (
            position.get("trading_symbol") == br_symbol
            and to_oa_exchange(position.get("exchange")) == exchange
            and str(position.get("product", "")).upper() == str(product).upper()
        ):
            net_qty = str(position.get("net_quantity", "0"))
            logger.debug(f"Net Quantity {net_qty}")
            break

    return net_qty


def place_order_api(data, auth):
    """Place a regular order.

    Returns (response, response_data, orderid). `response.status` is set so the
    service layer's `res.status == 200` success check works.
    """
    payload = transform_data(data, auth)
    # debug, not info: console writes from the order hot path cost real
    # milliseconds on Windows terminals; use LOG_LEVEL=DEBUG to see payloads
    logger.debug(f"Payload for HDFC Sky place_order_api: {payload}")

    client = get_httpx_client()
    response = client.post(
        f"{get_root_url()}/oapi/v1/orders",
        headers=get_hdfcsky_headers(auth, with_json=True),
        params=base_params(auth, client_id=False),
        json=payload,
    )
    logger.debug(f"HDFC Sky raw response: status={response.status_code}, body={response.text}")

    try:
        response_data = response.json()
    except ValueError:
        response_data = {
            "status": "error",
            "message": f"Non-JSON response (HTTP {response.status_code}): {response.text[:200]}",
        }

    if response_data.get("status") == "success":
        orderid = (response_data.get("data") or {}).get("oms_order_id")
    else:
        orderid = None
        # HDFC Sky can return an error payload with HTTP 200; make sure the
        # service layer's `status == 200` check does not read that as success.
        if response.status_code == 200:
            response.status_code = 400

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

        with _get_symbol_lock(symbol, exchange, product):
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
        return res, {"status": "error", "message": error_msg}, orderid


def close_all_positions(current_api_key, auth):
    """Square off every open position with market orders."""
    positions = _position_rows(get_positions(auth))
    if not positions:
        return {"message": "No Open Positions Found"}, 200

    for position in positions:
        net_qty = int(float(position.get("net_quantity", 0) or 0))
        if net_qty == 0:
            continue

        exchange = to_oa_exchange(position.get("exchange"))
        brsymbol = position.get("trading_symbol")
        symbol = get_oa_symbol(brsymbol=brsymbol, exchange=exchange) or brsymbol

        payload = {
            "apikey": current_api_key,
            "strategy": "Squareoff",
            "symbol": symbol,
            "action": "SELL" if net_qty > 0 else "BUY",
            "exchange": exchange,
            "pricetype": "MARKET",
            "product": reverse_map_product_type(exchange, position.get("product")) or "MIS",
            "quantity": str(abs(net_qty)),
        }
        logger.debug(f"Close position payload: {payload}")
        try:
            _, api_response, _ = place_order_api(payload, auth)
            logger.debug(f"Close position response: {api_response}")
        except Exception as e:
            logger.exception(f"Error squaring off {exchange}:{symbol}: {e}")

    _invalidate_position_cache(auth)
    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """Cancel an order via DELETE /oapi/v1/orders/<oms_order_id>."""
    try:
        response_data = _request(
            "DELETE",
            f"/oapi/v1/orders/{orderid}",
            auth,
            params={"execution_type": "REGULAR"},
        )
        logger.debug(f"HDFC Sky cancel order response: {response_data}")

        if response_data.get("status") == "success":
            return {"status": "success", "orderid": str(orderid)}, 200
        return {
            "status": "error",
            "message": response_data.get("message", "Failed to cancel order"),
        }, 400
    except Exception as e:
        logger.exception(f"Error canceling order {orderid}: {e}")
        return {"status": "error", "message": f"Failed to cancel order: {e}"}, 500


def modify_order(data, auth):
    """Modify an order via PUT /oapi/v1/orders."""
    try:
        payload = transform_modify_order_data(data, auth)
        logger.debug(f"HDFC Sky modify order payload: {payload}")

        response_data = _request(
            "PUT", "/oapi/v1/orders", auth, payload=payload, with_client_id=False
        )
        logger.debug(f"HDFC Sky modify order response: {response_data}")

        if response_data.get("status") == "success":
            orderid = (response_data.get("data") or {}).get("oms_order_id", data["orderid"])
            return {"status": "success", "orderid": str(orderid)}, 200
        return {
            "status": "error",
            "message": response_data.get("message", "Failed to modify order"),
        }, 400
    except Exception as e:
        logger.exception(f"Error modifying order {data.get('orderid')}: {e}")
        return {"status": "error", "message": f"Failed to modify order: {e}"}, 500


def cancel_all_orders_api(data, auth):
    """Cancel every open / trigger-pending order."""
    try:
        payload = _request("GET", "/oapi/v1/orders", auth, params={"type": "pending"})
    except Exception as e:
        logger.exception(f"Error fetching HDFC Sky order book for cancel-all: {e}")
        return [], []

    if payload.get("status") == "error":
        logger.error(f"HDFC Sky order book error: {payload.get('message')}")
        return [], []

    orders = (payload.get("data") or {}).get("orders") or []
    orders_to_cancel = [
        order
        for order in orders
        if str(order.get("order_status", "")).upper() in CANCELLABLE_STATUSES
    ]

    canceled_orders = []
    failed_cancellations = []
    for order in orders_to_cancel:
        orderid = order.get("oms_order_id")
        _, status_code = cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
