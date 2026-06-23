import json
import threading
import time

from broker.tradesmart.api.baseurl import post, resolve_uid
from broker.tradesmart.mapping.transform_data import (
    map_product_type,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_br_symbol, get_symbol, get_token
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth, payload=None):
    """POST a book/account endpoint and return parsed JSON.

    Defaults the body to ``{uid, actid}`` when no payload is supplied.
    """
    userid = resolve_uid(auth)
    if payload is None:
        payload = {"uid": userid, "actid": userid}
    else:
        payload.setdefault("uid", userid)
        payload.setdefault("actid", userid)

    response = post(endpoint, payload, auth)
    return json.loads(response.text)


def get_order_book(auth):
    response = get_api_response("/OrderBook", auth)
    logger.debug(f"TradeSmart OrderBook Response: {response}")
    # Surface rejection reasons for any rejected orders
    if isinstance(response, list):
        for order in response:
            if isinstance(order, dict) and str(order.get("status", "")).upper() == "REJECTED":
                logger.debug(
                    f"Rejected order {order.get('norenordno', '')} "
                    f"({order.get('tsym', '')}): {order.get('rejreason', 'no reason provided')}"
                )
    return response


def get_trade_book(auth):
    return get_api_response("/TradeBook", auth)


def get_positions(auth):
    return get_api_response("/PositionBook", auth)


def get_holdings(auth):
    # Holdings requires the product code (C = CNC)
    return get_api_response("/Holdings", auth, payload={"prd": "C"})


# --- Per-Symbol Smart Order Lock ---
# Ensures only one smart order per symbol executes at a time; others queue and
# execute sequentially, each getting a fresh position book.
_symbol_locks = {}
_symbol_locks_lock = threading.Lock()

# --- Position Book Cache (1s TTL, invalidated after each smart order) ---
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
            return cached["data"]

    positions_data = get_positions(auth)

    with _position_cache_lock:
        _position_cache[auth] = {"data": positions_data, "timestamp": time.monotonic()}

    return positions_data


def _invalidate_position_cache(auth):
    with _position_cache_lock:
        _position_cache.pop(auth, None)


def get_open_position(tradingsymbol, exchange, producttype, auth):
    """Return net qty (as str) for a symbol/exchange/product. Used by smart order."""
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    positions_data = _get_cached_positions(auth)

    net_qty = "0"
    if positions_data is None or (
        isinstance(positions_data, dict) and positions_data.get("stat") == "Not_Ok"
    ):
        return "0"

    if positions_data and isinstance(positions_data, list):
        for position in positions_data:
            if (
                position.get("tsym") == tradingsymbol
                and position.get("exch") == exchange
                and position.get("prd") == producttype
            ):
                net_qty = position.get("netqty", "0")
                break

    return net_qty


def place_order_api(data, auth):
    """Place an order. Returns ``(response, response_data, orderid)``."""
    token = get_token(data["symbol"], data["exchange"])
    newdata = transform_data(data, token, uid=resolve_uid(auth), auth_token=auth)

    res = post("/PlaceOrder", newdata, auth)
    response_data = res.json()
    logger.debug(f"TradeSmart PlaceOrder Response: {response_data}")

    # Services check ``res.status == 200``
    res.status = res.status_code

    if response_data.get("stat") == "Ok":
        orderid = response_data["norenordno"]
    else:
        orderid = None
        # Capture the broker's synchronous rejection reason
        logger.debug(
            f"PlaceOrder rejected ({data.get('symbol', '')}): "
            f"{response_data.get('emsg', 'no reason provided')}"
        )
    return res, response_data, orderid


def place_smartorder_api(data, auth):
    """Place a position-aware smart order (reconciles to target position_size)."""
    res = None

    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")
    symbol_lock = _get_symbol_lock(symbol, exchange, product)

    with symbol_lock:
        position_size = int(data.get("position_size", "0"))
        current_position = int(
            get_open_position(symbol, exchange, map_product_type(product), auth)
        )

        logger.debug(f"position_size : {position_size}")
        logger.debug(f"Open Position : {current_position}")

        action = None
        quantity = 0

        if position_size == 0 and current_position == 0 and int(data["quantity"]) != 0:
            res, response, orderid = place_order_api(data, auth)
            _invalidate_position_cache(auth)
            return res, response, orderid

        elif position_size == current_position:
            if int(data["quantity"]) == 0:
                response = {
                    "status": "success",
                    "message": "No OpenPosition Found. Not placing Exit order.",
                }
            else:
                response = {
                    "status": "success",
                    "message": "No action needed. Position size matches current position",
                }
            return res, response, None

        if position_size == 0 and current_position > 0:
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

        if action:
            order_data = data.copy()
            order_data["action"] = action
            order_data["quantity"] = str(quantity)

            res, response, orderid = place_order_api(order_data, auth)
            _invalidate_position_cache(auth)
            logger.debug(f"{response}")
            return res, response, orderid


def close_all_positions(current_api_key, auth):
    """Square off every open net position with market orders."""
    positions_response = get_positions(auth)

    if positions_response is None or (
        isinstance(positions_response, list)
        and positions_response
        and positions_response[0].get("stat") == "Not_Ok"
    ):
        return {"message": "No Open Positions Found"}, 200

    if positions_response and isinstance(positions_response, list):
        for position in positions_response:
            if int(position.get("netqty", 0)) == 0:
                continue

            action = "SELL" if int(position["netqty"]) > 0 else "BUY"
            quantity = abs(int(position["netqty"]))

            symbol = get_symbol(position["token"], position["exch"])
            logger.debug(f"Closing {symbol} qty {quantity} action {action}")

            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position["exch"],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position["prd"]),
                "quantity": str(quantity),
            }

            place_order_api(place_order_payload, auth)

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """Cancel a pending order by Noren order number."""
    data = {"uid": resolve_uid(auth), "norenordno": orderid}
    res = post("/CancelOrder", data, auth)
    response_data = res.json()
    logger.debug(f"{response_data}")

    if response_data.get("stat") == "Ok":
        return {"status": "success", "orderid": orderid}, 200
    return {
        "status": "error",
        "message": response_data.get("emsg", "Failed to cancel order"),
    }, res.status_code


def modify_order(data, auth):
    """Modify a pending order's price/qty/type."""
    token = get_token(data["symbol"], data["exchange"])
    data["symbol"] = get_br_symbol(data["symbol"], data["exchange"])

    transformed_data = transform_modify_order_data(data, token, uid=resolve_uid(auth))
    res = post("/ModifyOrder", transformed_data, auth)
    response = res.json()

    logger.debug(f"Modify Order Response: {response}")

    if response.get("stat") == "Ok":
        return {"status": "success", "orderid": data["orderid"]}, 200
    return {
        "status": "error",
        "message": response.get("emsg", "Failed to modify order"),
    }, res.status_code


def cancel_all_orders_api(data, auth):
    """Cancel every open / trigger-pending order. Returns ``(canceled[], failed[])``."""
    order_book_response = get_order_book(auth)
    if order_book_response is None or not isinstance(order_book_response, list):
        return [], []

    orders_to_cancel = [
        order
        for order in order_book_response
        if order.get("status") in ["OPEN", "TRIGGER_PENDING"]
    ]

    canceled_orders = []
    failed_cancellations = []
    for order in orders_to_cancel:
        orderid = order["norenordno"]
        _, status_code = cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
