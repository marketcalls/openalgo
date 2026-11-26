"""Pocketful orders, order and trade books, positions and holdings.

Sources: Pocketful's API documentation (offline copy of 2026-11-17) and the
routes of the official Python SDK ``pocketful`` 0.1.2:

  POST   /api/v1/orders                     place-regular-order.md
  PUT    /api/v1/orders                     modify-regular-order.md
  DELETE /api/v1/orders/<oms_order_id>      cancel-regular-order.md
  GET    /api/v1/orders?type=pending        fetch-pending-orders.md
  GET    /api/v1/orders?type=completed      fetch-completed-orders.md
  GET    /api/v1/trades                     trade-book.md
  GET    /api/v1/positions?type=historical  fetch-position-netwise.md
  GET    /api/v1/holdings                   fetch-demat-holdings.md

Every call goes through baseurl.pocketful_request, and the trading client id
every call carries comes from the stored token (baseurl.client_id), so an
order placed by the API or a strategy, with no browser session, carries it too.

Positions are read netwise (type=historical), not daywise (type=live).
OpenAlgo's position book and the smart order work on the net position: a
carry-forward NRML or CNC position from an earlier day is a position a smart
order must see, or an exit reads as flat and an entry doubles it. The daywise
page describes "your trading positions for the current day"; the netwise page
"all net positions", and its example carries the day's own buys and sells.
"""

# threading and time: test/test_smartorder_logic.py checks that every plugin's
# order_api imports both.
import threading
import time
from urllib.parse import quote

import httpx

from broker.pocketful.api import baseurl
from broker.pocketful.api.baseurl import pocketful_request
from broker.pocketful.mapping.order_data import (
    BOOK_KEY,
    COMPLETED_BOOK,
    PENDING_BOOK,
    oa_symbol,
)
from broker.pocketful.mapping.transform_data import (
    OrderFieldError,
    map_product_type,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_br_symbol, get_token
from utils.httpx_client import UNANSWERED_ORDER_MESSAGE
from utils.logging import get_logger
from utils.position_read import (
    PositionReadError,
    position_read_failed_message,
    read_position_book,
    refuse_smart_order_on_read_failure,
)
from utils.smart_order_guard import PositionBookCache, SymbolLocks

logger = get_logger(__name__)

BROKER = "pocketful"
ORDERS_PATH = "/api/v1/orders"
TRADES_PATH = "/api/v1/trades"
POSITIONS_PATH = "/api/v1/positions"
HOLDINGS_PATH = "/api/v1/holdings"
# fetch-position-netwise.md (the SDK's api.portfolio.positions.netwise).
POSITIONS_TYPE = "historical"
# The execution types the regular cancel endpoint takes: cancel-regular-order.md
# and cancel-amo-order.md. CO and BO orders cancel through /api/v1/orders/kart.
_CANCELLABLE_EXECUTION_TYPES = ("REGULAR", "AMO")

NO_CLIENT_ID_MESSAGE = (
    "OpenAlgo could not find your Pocketful client ID in the stored session. "
    "Log in to Pocketful again from OpenAlgo, then try again."
)


class _OrderResponse:
    """Response-shaped result for place_order_api; the services read ``.status``."""

    def __init__(self, status):
        self.status = status
        self.status_code = status


class _ReadFailed(Exception):
    """A book Pocketful did not return. ``str()`` is the sentence for the trader."""


def _refusal(response, subject, after_write=False):
    """The sentence a trader reads when Pocketful did not do what was asked.

    401 and 403 are the annexure's "log in again" answers; 429 its rate limit.
    """
    if response.status_code in (401, 403):
        return (
            f"Pocketful did not accept your session for the {subject}. "
            "Log in to Pocketful again from OpenAlgo, then try again."
        )
    if response.status_code == 429:
        return (
            f"Pocketful refused the {subject} because too many requests were sent in a "
            "short time. Wait a moment and try again."
        )
    if not isinstance(response.data, dict):
        if after_write:
            return (
                f"Pocketful sent an answer to the {subject} that OpenAlgo could not read, "
                "so it may have gone through. Check the order book before trying again."
            )
        return (
            f"Pocketful sent an answer to the {subject} that OpenAlgo could not read. "
            "Try again in a moment."
        )
    message = response.message.strip()
    if message:
        return f"Pocketful refused the {subject}: {message}"
    return f"Pocketful refused the {subject} without giving a reason. Try again in a moment."


def _failed_status(response):
    """The HTTP status to report for a refusal: Pocketful's own when it is an
    error status, 400 for an error answered with a 2xx."""
    return response.status_code if response.status_code >= 400 else 400


def _list_of(payload, key, subject):
    """The rows under ``data`` (``key`` None) or ``data[key]``.

    No ``data``, an empty object or list, or a null list is an empty book. Any
    other shape raises _ReadFailed: a book OpenAlgo cannot read is not an empty
    one.
    """
    if payload is None or payload == {} or payload == []:
        return []
    if key is not None:
        if not isinstance(payload, dict):
            payload = None
        else:
            payload = payload.get(key)
            if payload is None:
                return []
    if not isinstance(payload, list):
        raise _ReadFailed(
            f"Pocketful sent the {subject} in a form OpenAlgo does not recognise. "
            "Try again in a moment."
        )
    return [row for row in payload if isinstance(row, dict)]


def _read_list(auth, path, params, key, subject):
    """GET a Pocketful book and return its rows, or raise _ReadFailed."""
    try:
        response = pocketful_request("GET", path, auth, params=params)
    except Exception as exc:
        logger.exception(f"Pocketful {subject} could not be read")
        raise _ReadFailed(
            f"OpenAlgo could not reach Pocketful for the {subject}. "
            "Check your connection and try again."
        ) from exc
    if not response.ok:
        logger.error(
            f"Pocketful {subject} read failed: HTTP {response.status_code}, {response.message!r}"
        )
        raise _ReadFailed(_refusal(response, subject))
    return _list_of(response.payload, key, subject)


def _book(auth, path, params, key, subject):
    """{"status": "success", "data": rows}, or {"status": "error", "message"}."""
    client_id = baseurl.client_id(auth)
    if not client_id:
        return {"status": "error", "message": NO_CLIENT_ID_MESSAGE}
    try:
        rows = _read_list(auth, path, {"client_id": client_id, **params}, key, subject)
    except _ReadFailed as exc:
        return {"status": "error", "message": str(exc)}
    return {"status": "success", "data": rows}


def get_order_book(auth):
    """Pending and completed orders in one list, each row tagged with its list.

    Pending is read first: an order that finishes between the two reads shows
    up in both, and the completed row, the newer one, is kept. A failure of
    either half fails the book, so a missing pending list never reads as "no
    open orders".
    """
    client_id = baseurl.client_id(auth)
    if not client_id:
        return {"status": "error", "message": NO_CLIENT_ID_MESSAGE}
    try:
        pending = _read_list(
            auth, ORDERS_PATH, {"type": "pending", "client_id": client_id}, "orders", "order book"
        )
        completed = _read_list(
            auth,
            ORDERS_PATH,
            {"type": "completed", "client_id": client_id},
            "orders",
            "order book",
        )
    except _ReadFailed as exc:
        return {"status": "error", "message": str(exc)}

    for row in pending:
        row[BOOK_KEY] = PENDING_BOOK
    for row in completed:
        row[BOOK_KEY] = COMPLETED_BOOK
    finished = {str(row.get("oms_order_id")) for row in completed if row.get("oms_order_id")}
    orders = [row for row in pending if str(row.get("oms_order_id")) not in finished]
    orders.extend(completed)
    return {"status": "success", "data": orders}


def get_trade_book(auth):
    """Executed trades. trade-book.md lists them under ``data.orders``."""
    return _book(auth, TRADES_PATH, {}, "orders", "trade book")


def get_positions(auth):
    """Net positions (see the module docstring), under ``data`` as a list."""
    return _book(auth, POSITIONS_PATH, {"type": POSITIONS_TYPE}, None, "position book")


def get_holdings(auth):
    """Demat holdings, under ``data.holdings``."""
    return _book(auth, HOLDINGS_PATH, {}, "holdings", "holdings")


# --- Per-Symbol Smart Order Lock ---
# Ensures only one smart order per symbol executes at a time.
# Others queue and execute sequentially, each getting a fresh position book.
# The registry forgets a symbol once nobody holds or waits on it, and under the
# gthread worker a wait is bounded (utils/smart_order_guard.py).
_SMART_ORDER_LOCKS = SymbolLocks()

# --- Position Book Cache ---
# Caches get_positions() for 1 second. Invalidated after each smart order placement.
# A fetch still in flight when an order invalidates the cache is returned to its
# own caller but never cached, so the next order cannot read the book from
# before the previous fill (utils/smart_order_guard.py).
_POSITION_BOOK = PositionBookCache()


def _get_symbol_lock(symbol, exchange, product):
    """Hold the smart order lock for one symbol, as a context manager.

    Yields True while holding it. Yields False when the wait ran out, which
    happens only under the gthread worker; the caller must then return
    ``SymbolLocks.busy(symbol)`` without placing an order.
    """
    return _SMART_ORDER_LOCKS.hold(symbol, exchange, product)


def _position_book_ok(positions_data):
    """get_positions says status "success" only for a book it read."""
    return isinstance(positions_data, dict) and positions_data.get("status") == "success"


def _get_cached_positions(auth):
    """Get positions from cache if fresh, otherwise fetch from broker API."""
    return _POSITION_BOOK.get(
        auth,
        lambda: read_position_book(BROKER, lambda: get_positions(auth), _position_book_ok),
    )


def _invalidate_position_cache(auth):
    """Invalidate the position cache so the next queued order fetches fresh data.

    Also stops a fetch that started before this order from caching the book
    it read.
    """
    _POSITION_BOOK.invalidate(auth)


def _same_instrument(position, br_symbol, token):
    """A position row is the instrument when its token or its trading symbol
    is the master contract's."""
    row_token = position.get("instrument_token")
    if row_token is None:
        row_token = position.get("token")
    if token and row_token is not None and str(row_token) == str(token):
        return True
    return bool(br_symbol) and position.get("trading_symbol") == br_symbol


def get_open_position(tradingsymbol, exchange, product, auth):
    """Net quantity, as a string, of one OpenAlgo symbol on one exchange and product.

    ``product`` is the Pocketful product (map_product_type). A row that
    matches but carries no readable net quantity raises PositionReadError: a
    position OpenAlgo cannot read must not size an order as flat.
    """
    br_symbol = get_br_symbol(tradingsymbol, exchange)
    token = get_token(tradingsymbol, exchange)
    wanted = reverse_map_product_type(exchange, product) or str(product)

    positions_data = _get_cached_positions(auth)
    for position in positions_data.get("data") or []:
        if str(position.get("exchange") or "").upper() != str(exchange).upper():
            continue
        if not _same_instrument(position, br_symbol, token):
            continue
        row_product = position.get("product")
        if (reverse_map_product_type(exchange, row_product) or str(row_product)) != wanted:
            continue
        try:
            net_qty = int(float(position["net_quantity"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise PositionReadError(
                BROKER, f"position row for {exchange}:{tradingsymbol} has no net_quantity"
            ) from exc
        logger.debug(f"Pocketful net quantity of {exchange}:{tradingsymbol} {product}: {net_qty}")
        return str(net_qty)
    return "0"


def place_order_api(data, auth):
    """Place a regular order. Returns (response, response_data, orderid).

    An order OpenAlgo cannot send (OrderFieldError) is refused as a 400 before
    anything reaches Pocketful. A transport error is raised to the caller: the
    order may have been sent, and the service says so.
    """
    client_id = baseurl.client_id(auth)
    if not client_id:
        return _OrderResponse(400), {"status": "error", "message": NO_CLIENT_ID_MESSAGE}, None
    try:
        payload = transform_data(data, client_id=client_id, auth_token=auth)
    except OrderFieldError as exc:
        logger.info(f"Order not sent to Pocketful: {exc}")
        return _OrderResponse(400), {"status": "error", "message": str(exc)}, None

    response = pocketful_request("POST", ORDERS_PATH, auth, payload=payload)

    if response.ok:
        orderid = (response.payload or {}).get("oms_order_id")
        if not orderid:
            logger.warning(f"Pocketful accepted an order without an order id: {response.text!r}")
        return _OrderResponse(200), response.data, str(orderid) if orderid else None

    message = _refusal(response, "order", after_write=True)
    logger.error(f"Pocketful refused an order: HTTP {response.status_code}, {response.message!r}")
    return _OrderResponse(_failed_status(response)), {"status": "error", "message": message}, None


@refuse_smart_order_on_read_failure
def place_smartorder_api(data, auth):
    """Take the position to ``position_size`` with one order, under the symbol's lock."""
    res = None

    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")
    # Per-symbol lock: serialize smart orders per symbol
    with _get_symbol_lock(symbol, exchange, product) as symbol_lock:
        if not symbol_lock:
            return SymbolLocks.busy(symbol)
        position_size = int(data.get("position_size", "0"))

        # Get current open position for the symbol
        current_position = int(get_open_position(symbol, exchange, map_product_type(product), auth))

        logger.debug(f"position_size : {position_size}")
        logger.debug(f"Open Position : {current_position}")

        action = None
        quantity = 0

        # If both position_size and current_position are 0, use action+qty from request
        if position_size == 0 and current_position == 0 and int(data["quantity"]) != 0:
            return _place_and_forget_the_book(data, auth)

        if position_size == current_position:
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
        elif position_size > current_position:
            action = "BUY"
            quantity = position_size - current_position
        else:
            action = "SELL"
            quantity = current_position - position_size

        order_data = data.copy()
        order_data["action"] = action
        order_data["quantity"] = str(quantity)
        return _place_and_forget_the_book(order_data, auth)


def _place_and_forget_the_book(order_data, auth):
    """Place a smart order's order, then drop the cached position book.

    The book is dropped even when the placement raises: a transport error can
    come after the order reached Pocketful, and the next smart order queued on
    the symbol must not size itself against the book from before it.
    """
    try:
        return place_order_api(order_data, auth)
    finally:
        _invalidate_position_cache(auth)


def _square_off(position, current_api_key, auth):
    """Close one position with a MARKET order, priced like any other.

    Returns (order id, None) when Pocketful accepted the order, or
    (None, reason) with the sentence for the trader. Never raises: one
    position that cannot be closed must not stop the others.
    """
    exchange = str(position.get("exchange") or "")
    label = position.get("trading_symbol") or position.get("symbol") or "a position"
    try:
        net_quantity = int(float(position.get("net_quantity")))
    except (TypeError, ValueError):
        return None, (
            f"OpenAlgo could not read the quantity of {label} from Pocketful. "
            "Close it at Pocketful."
        )
    try:
        symbol = oa_symbol(
            position.get("trading_symbol"), position.get("instrument_token"), exchange
        )
        product = reverse_map_product_type(exchange, position.get("product"))
        if product is None:
            return None, (
                f"{label} is held under the Pocketful product {position.get('product')}, "
                "which OpenAlgo does not close. Close it at Pocketful."
            )
        order = {
            "apikey": current_api_key,
            "strategy": "Squareoff",
            "symbol": symbol,
            "exchange": exchange,
            "action": "SELL" if net_quantity > 0 else "BUY",
            "pricetype": "MARKET",
            "product": product,
            "quantity": str(abs(net_quantity)),
            "price": "0",
            "trigger_price": "0",
            "disclosed_quantity": "0",
        }
        res, response, orderid = place_order_api(order, auth)
    except httpx.TransportError:
        logger.exception(f"The square-off of {exchange}:{label} got no answer from Pocketful")
        return None, UNANSWERED_ORDER_MESSAGE
    except Exception:
        logger.exception(f"Could not square off {exchange}:{label}")
        return None, "OpenAlgo could not send its square-off order. Close it at Pocketful."
    if getattr(res, "status", None) == 200:
        return orderid, None
    reason = response.get("message") if isinstance(response, dict) else None
    return None, reason or "Pocketful refused the square-off order."


def close_all_positions(current_api_key, auth):
    """Square off every open net position, each with a protected LIMIT order.

    A position that cannot be priced or is refused is reported and the others
    are still closed. Any failure answers 500 with the positions left open, so
    the trader is never told everything was closed when it was not.
    """
    positions = get_positions(auth)
    if positions.get("status") != "success":
        logger.error(f"Close all: Pocketful positions not read: {positions.get('message')}")
        return {"status": "error", "message": position_read_failed_message(BROKER)}, 500

    open_positions = [p for p in positions.get("data") or [] if _net(p) != 0]
    if not open_positions:
        return {"message": "No Open Positions Found"}, 200

    closed, failed = [], []
    for position in open_positions:
        orderid, reason = _square_off(position, current_api_key, auth)
        label = position.get("trading_symbol") or position.get("symbol") or "a position"
        if reason is None:
            closed.append({"symbol": label, "orderid": orderid})
        else:
            failed.append({"symbol": label, "message": reason})
    _invalidate_position_cache(auth)

    if failed:
        details = " ".join(f"{f['symbol']}: {f['message']}" for f in failed)
        return {
            "status": "error",
            "message": (
                f"{len(failed)} of {len(open_positions)} positions were not closed. {details} "
                "Check your positions."
            ),
            "data": closed,
            "failed": failed,
        }, 500
    return {"status": "success", "message": "All Open Positions SquaredOff", "data": closed}, 200


def _net(position):
    """Net quantity of a position row; a row without one counts as open (1) so
    the square-off reports it rather than skipping it."""
    try:
        return int(float(position.get("net_quantity")))
    except (TypeError, ValueError):
        return 1


def cancel_order(orderid, auth, execution_type="REGULAR"):
    """Cancel one order: DELETE /api/v1/orders/<oms_order_id>.

    The docs (cancel-regular-order.md) send oms_order_id, client_id and
    execution_type as a JSON body; the SDK sends client_id and execution_type
    as query parameters and no body. Both are sent, so the request carries
    every field in each source's form.
    """
    client_id = baseurl.client_id(auth)
    if not client_id:
        return {"status": "error", "message": NO_CLIENT_ID_MESSAGE}, 400
    orderid = str(orderid)
    try:
        response = pocketful_request(
            "DELETE",
            f"{ORDERS_PATH}/{quote(orderid, safe='')}",
            auth,
            params={"client_id": client_id, "execution_type": execution_type},
            payload={
                "oms_order_id": orderid,
                "client_id": client_id,
                "execution_type": execution_type,
            },
        )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        logger.exception(f"Could not reach Pocketful to cancel order {orderid}")
        return {
            "status": "error",
            "message": "OpenAlgo could not reach Pocketful, so the order was not cancelled. "
            "Check your connection and try again.",
        }, 502
    except httpx.TransportError:
        logger.exception(f"The cancel of order {orderid} got no answer from Pocketful")
        return {
            "status": "error",
            "message": "The connection to Pocketful dropped after the cancel was sent, so it "
            "may have gone through. Check the order book.",
        }, 502

    if response.ok:
        return {"status": "success", "orderid": orderid}, 200
    logger.error(
        f"Pocketful refused to cancel {orderid}: HTTP {response.status_code}, {response.message!r}"
    )
    return {
        "status": "error",
        "message": _refusal(response, "cancel", after_write=True),
    }, _failed_status(response)


def modify_order(data, auth):
    """Modify an order: PUT /api/v1/orders with the place body and oms_order_id.

    The body is priced while ``data`` still holds the OpenAlgo symbol: the
    tick size and the LTP are looked up by it.
    """
    client_id = baseurl.client_id(auth)
    if not client_id:
        return {"status": "error", "message": NO_CLIENT_ID_MESSAGE}, 400
    try:
        payload = transform_modify_order_data(data, client_id=client_id, auth_token=auth)
    except OrderFieldError as exc:
        logger.info(f"Modify not sent to Pocketful: {exc}")
        return {"status": "error", "message": str(exc)}, 400

    try:
        response = pocketful_request("PUT", ORDERS_PATH, auth, payload=payload)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        logger.exception(f"Could not reach Pocketful to modify order {data.get('orderid')}")
        return {
            "status": "error",
            "message": "OpenAlgo could not reach Pocketful, so the change was not sent. "
            "Check your connection and try again.",
        }, 502
    except httpx.TransportError:
        logger.exception(f"The modify of order {data.get('orderid')} got no answer from Pocketful")
        return {
            "status": "error",
            "message": "The connection to Pocketful dropped after the change was sent, so it "
            "may have gone through. Check the order book.",
        }, 502

    if response.ok:
        orderid = (response.payload or {}).get("oms_order_id") or payload["oms_order_id"]
        return {"status": "success", "orderid": str(orderid)}, 200
    logger.error(
        f"Pocketful refused to modify {payload['oms_order_id']}: "
        f"HTTP {response.status_code}, {response.message!r}"
    )
    return {
        "status": "error",
        "message": _refusal(response, "change to the order", after_write=True),
    }, _failed_status(response)


def cancel_all_orders_api(data, auth):
    """Cancel every order in Pocketful's pending list. Returns (cancelled, failed).

    A pending list that cannot be read raises, so the service reports a
    failure instead of "cancelled 0 orders" while orders are still working.
    An order the regular cancel endpoint does not take (a CO or BO leg) is
    counted as failed.
    """
    client_id = baseurl.client_id(auth)
    if not client_id:
        raise RuntimeError(NO_CLIENT_ID_MESSAGE)
    try:
        orders = _read_list(
            auth, ORDERS_PATH, {"type": "pending", "client_id": client_id}, "orders", "order book"
        )
    except _ReadFailed as exc:
        raise RuntimeError(str(exc)) from exc

    canceled_orders = []
    failed_cancellations = []
    for order in orders:
        orderid = order.get("oms_order_id")
        if not orderid:
            logger.error("Cancel all: a pending Pocketful order has no order id")
            failed_cancellations.append("unknown")
            continue
        orderid = str(orderid)
        execution_type = str(order.get("execution_type") or "REGULAR").upper()
        if execution_type not in _CANCELLABLE_EXECUTION_TYPES:
            logger.warning(f"Cancel all: {orderid} is a {execution_type} order, not cancelled")
            failed_cancellations.append(orderid)
            continue
        try:
            _, status_code = cancel_order(orderid, auth, execution_type=execution_type)
        except Exception:
            logger.exception(f"Cancel all: could not cancel {orderid}")
            status_code = None
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
