"""Nuvama orders, books, smart order and square-off.

Routes (official SDK constants/router.py, under BASE_EQ):

- POST trade/placetrade/v1/{userid}/
- PUT  trade/modifytrade/v1/{userid}/
- PUT  trade/canceltrade/v1/{userid}/
- GET  order/book/{userid}/v1/
- GET  tradebook/v1/{userid}/
- GET  positions/net/{userid}/
- GET  holdings/v1/rmsholdings/{userid}/

Modify and cancel need the order's instrument, side, product and quantity, so
both read the order's row from the order book first.
"""

from broker.nuvama.api.baseurl import BASE_EQ, account_path, nuvama_request
from broker.nuvama.mapping.order_data import normalize_status, oa_symbol_for
from broker.nuvama.mapping.transform_data import (
    OrderFieldError,
    map_product_type,
    reverse_map_product_type,
    transform_cancel_order_data,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_token
from utils.logging import get_logger
from utils.position_read import read_position_book, refuse_smart_order_on_read_failure
from utils.smart_order_guard import PositionBookCache, SymbolLocks

logger = get_logger(__name__)

# Nuvama's "nothing in this book" answers (HTTP 222 with an error object):
# ETRD0007 orders, ETRD0002 trades, ETRD0004 positions.
_EMPTY_BOOK_CODES = frozenset({"ETRD0002", "ETRD0004", "ETRD0007"})


class _OrderResponse:
    """Response-shaped result for the services, which read ``.status``."""

    def __init__(self, status):
        self.status = status
        self.status_code = status


def _book(route, key, auth):
    """GET a book; an empty book reads as no rows, a failure as an error dict."""
    try:
        response = nuvama_request(
            "GET", f"{BASE_EQ}{route.format(userid=account_path(auth))}", auth
        )
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    except Exception:
        logger.exception(f"Nuvama {key} book request failed")
        return {"status": "error", "message": "Nuvama could not be reached. Try again."}
    if response.ok:
        return response.data
    if response.error_code() in _EMPTY_BOOK_CODES:
        return {"data": {key: []}}
    logger.error(f"Nuvama {key} book answered {response.status_code}: {response.error_message()}")
    return {"status": "error", "message": response.error_message()}


def get_order_book(auth):
    return _book("order/book/{userid}/v1/", "ord", auth)


def get_trade_book(auth):
    return _book("tradebook/v1/{userid}/", "trade", auth)


def get_positions(auth):
    return _book("positions/net/{userid}/", "pos", auth)


def get_holdings(auth):
    return _book("holdings/v1/rmsholdings/{userid}/", "rmsHdg", auth)


# --- smart order --------------------------------------------------------------

_SMART_ORDER_LOCKS = SymbolLocks()
_POSITION_BOOK = PositionBookCache()


def _position_book_ok(book):
    return isinstance(book, dict) and isinstance(book.get("data"), dict)


def _get_cached_positions(auth):
    return _POSITION_BOOK.get(
        auth,
        lambda: read_position_book("nuvama", lambda: get_positions(auth), _position_book_ok),
    )


def get_open_position(tradingsymbol, exchange, product, auth):
    """Net quantity (as str) of one symbol and product, from the position book."""
    stream_sym = get_token(tradingsymbol, exchange)
    if not stream_sym:
        raise OrderFieldError(
            f"{tradingsymbol} is not in the Nuvama master contract for {exchange}. "
            "Download the master contract again and check the symbol."
        )
    book = _get_cached_positions(auth)
    for position in (book.get("data") or {}).get("pos") or []:
        if position.get("sym") != stream_sym:
            continue
        if reverse_map_product_type(position.get("prdCode")) != product:
            continue
        return str(int(float(position.get("ntQty") or 0)))
    return "0"


# --- place / modify / cancel ---------------------------------------------------


def _order_id_from(data):
    body = data.get("data") if isinstance(data, dict) else None
    if not isinstance(body, dict):
        return None
    if body.get("oid"):
        return str(body["oid"])
    # A sliced order answers one id per slice; the first identifies it.
    sliced = body.get("ord")
    if isinstance(sliced, list) and sliced and sliced[0].get("oid"):
        return str(sliced[0]["oid"])
    return None


def place_order_api(data, auth):
    try:
        payload = transform_data(data, auth)
        url = f"{BASE_EQ}trade/placetrade/v1/{account_path(auth)}/"
    except (OrderFieldError, ValueError) as exc:
        logger.info(f"Order not sent to Nuvama: {exc}")
        return _OrderResponse(400), {"status": "error", "message": str(exc)}, None

    logger.debug(f"Nuvama place order body: {payload}")
    response = nuvama_request("POST", url, auth, payload=payload)
    logger.debug(f"Nuvama place order answer: {response.status_code} {response.data}")

    order_id = _order_id_from(response.data) if response.ok else None
    if order_id:
        return _OrderResponse(200), response.data, order_id

    message = response.error_message("Nuvama did not accept the order")
    status = response.status_code if response.status_code not in (200, 222) else 400
    return _OrderResponse(status), {"status": "error", "message": message}, None


@refuse_smart_order_on_read_failure
def place_smartorder_api(data, auth):
    res = None
    response_data = {"status": "error", "message": "No action required or invalid parameters"}
    orderid = None

    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")
    if not all([symbol, exchange, product]):
        return res, response_data, orderid

    try:
        with _SMART_ORDER_LOCKS.hold(symbol, exchange, product) as held:
            if not held:
                return SymbolLocks.busy(symbol)
            position_size = int(data.get("position_size", "0"))
            current_position = int(get_open_position(symbol, exchange, product, auth))

            action = None
            quantity = 0
            if position_size == 0 and current_position == 0:
                action = data.get("action", "BUY").upper()
                quantity = int(data.get("quantity", "0"))
            elif position_size == 0:
                action = "SELL" if current_position > 0 else "BUY"
                quantity = abs(current_position)
            elif current_position == 0:
                action = "BUY" if position_size > 0 else "SELL"
                quantity = abs(position_size)
            elif position_size > current_position:
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
                _POSITION_BOOK.invalidate(auth)
                return res, response, orderid

            return (
                res,
                {"status": "success", "message": "No action needed. Position already matched."},
                orderid,
            )
    except OrderFieldError as exc:
        return _OrderResponse(400), {"status": "error", "message": str(exc)}, None


def _find_order(orderid, auth):
    """(row, error_message) for one order in the order book."""
    book = get_order_book(auth)
    if book.get("status") == "error":
        return None, book.get("message")
    for order in (book.get("data") or {}).get("ord") or []:
        if str(order.get("ordID")) == str(orderid):
            return order, None
    return None, f"Order {orderid} is not in today's Nuvama order book."


def modify_order(data, auth):
    order, error = _find_order(data.get("orderid"), auth)
    if not order:
        return {"status": "error", "message": error}, 404 if error and "not in" in error else 500
    try:
        payload = transform_modify_order_data(data, order, auth)
        url = f"{BASE_EQ}trade/modifytrade/v1/{account_path(auth)}/"
    except (OrderFieldError, ValueError) as exc:
        return {"status": "error", "message": str(exc)}, 400

    logger.debug(f"Nuvama modify order body: {payload}")
    try:
        response = nuvama_request("PUT", url, auth, payload=payload)
    except Exception:
        logger.exception("Nuvama modify order request failed")
        return {"status": "error", "message": "Nuvama could not be reached. Try again."}, 500
    if response.ok:
        return {"status": "success", "orderid": str(data.get("orderid"))}, 200
    status = response.status_code if response.status_code not in (200, 222) else 400
    return {
        "status": "error",
        "message": response.error_message("Nuvama did not modify the order"),
    }, status


def _cancel_row(order, auth):
    payload = transform_cancel_order_data(order)
    url = f"{BASE_EQ}trade/canceltrade/v1/{account_path(auth)}/"
    logger.debug(f"Nuvama cancel order body: {payload}")
    return nuvama_request("PUT", url, auth, payload=payload)


def cancel_order(orderid, auth):
    order, error = _find_order(orderid, auth)
    if not order:
        return {"status": "error", "message": error}, 404 if error and "not in" in error else 500
    try:
        response = _cancel_row(order, auth)
    except Exception:
        logger.exception(f"Nuvama cancel request for {orderid} failed")
        return {"status": "error", "message": "Nuvama could not be reached. Try again."}, 500
    if response.ok:
        return {"status": "success", "orderid": str(orderid)}, 200
    status = response.status_code if response.status_code not in (200, 222) else 400
    return {
        "status": "error",
        "message": response.error_message("Nuvama did not cancel the order"),
    }, status


def cancel_all_orders_api(data, auth):
    book = get_order_book(auth)
    if book.get("status") == "error":
        return [], []
    canceled, failed = [], []
    for order in (book.get("data") or {}).get("ord") or []:
        if normalize_status(order.get("sts")) not in ("open", "trigger pending"):
            continue
        orderid = str(order.get("ordID"))
        try:
            response = _cancel_row(order, auth)
            (canceled if response.ok else failed).append(orderid)
        except Exception:
            logger.exception(f"Nuvama cancel request for {orderid} failed")
            failed.append(orderid)
    return canceled, failed


def close_all_positions(current_api_key, auth):
    book = get_positions(auth)
    if book.get("status") == "error":
        return {"status": "error", "message": book.get("message")}, 500

    open_positions = [
        p for p in (book.get("data") or {}).get("pos") or [] if int(float(p.get("ntQty") or 0))
    ]
    if not open_positions:
        return {"message": "No Open Positions Found"}, 200

    failures = []
    for position in open_positions:
        net = int(float(position.get("ntQty") or 0))
        symbol = oa_symbol_for(position)
        exchange = (position.get("exc") or "").upper()
        product = reverse_map_product_type(position.get("prdCode"))
        if not map_product_type(product):
            failures.append(f"{symbol} ({exchange}): product {product} is not supported here")
            continue
        order = {
            "apikey": current_api_key,
            "strategy": "Squareoff",
            "symbol": symbol,
            "action": "SELL" if net > 0 else "BUY",
            "exchange": exchange,
            "pricetype": "MARKET",
            "product": product,
            "quantity": str(abs(net)),
        }
        res, api_response, order_id = place_order_api(order, auth)
        if getattr(res, "status", None) != 200 or not order_id:
            reason = (
                api_response.get("message", "order was refused")
                if isinstance(api_response, dict)
                else "order was refused"
            )
            failures.append(f"{symbol} ({exchange}): {reason}")
            logger.error(f"Square-off failed for {symbol}: {reason}")

    if failures:
        return {
            "status": "error",
            "message": (
                f"{len(failures)} position(s) could not be squared off and are still "
                f"open: {'; '.join(failures)}"
            ),
        }, 500
    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200
