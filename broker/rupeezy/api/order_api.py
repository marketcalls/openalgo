# broker/rupeezy/api/order_api.py
#
# Orders and books over the Vortex trading API
# (https://vortex.rupeezy.in/docs/latest/regular-order/).

from broker.rupeezy.api.client import RupeezyAPIError, request, request_json
from broker.rupeezy.mapping.exchange import (
    from_vortex_quantity,
    oa_exchange_for,
    split_ticker,
)
from broker.rupeezy.mapping.order_data import OPEN_STATUSES, lot_size_for, map_status
from broker.rupeezy.mapping.transform_data import (
    map_product_type,
    resolve_instrument,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_oa_symbol
from utils.broker_backpressure import BrokerBusyError, busy_response
from utils.logging import get_logger
from utils.position_read import (
    PositionReadError,
    read_position_book,
    refuse_smart_order_on_read_failure,
)
from utils.smart_order_guard import PositionBookCache, SymbolLocks

logger = get_logger(__name__)

# Order book page size; the endpoint pages with limit/offset (offset starts at 1).
# TODO(rupeezy): the docs do not say whether offset counts records or pages.
# Treated as a 1-based record offset; only matters past 500 orders in a day.
_ORDER_PAGE_SIZE = 500
_MAX_ORDER_PAGES = 20


class _LocalResponse:
    """Response-like object for failures detected before any HTTP call."""

    def __init__(self, status_code):
        self.status_code = status_code
        self.status = status_code


def _f(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


# --- Books ------------------------------------------------------------------


def get_order_book(auth):
    """All of today's orders, paging through /trading/orders."""
    orders = []
    for page in range(_MAX_ORDER_PAGES):
        payload = request_json(
            "GET",
            "/trading/orders",
            auth,
            params={"limit": _ORDER_PAGE_SIZE, "offset": page * _ORDER_PAGE_SIZE + 1},
        )
        if payload.get("status") != "success":
            return payload
        batch = payload.get("orders") or []
        orders.extend(batch)
        if len(batch) < _ORDER_PAGE_SIZE:
            break
    return {"status": "success", "orders": orders}


# Order-book fields copied onto trades that lack them (see get_trade_book).
_TRADE_FIELDS_FROM_ORDER = (
    "ticker",
    "exchange",
    "transaction_type",
    "product",
    "variety",
    "lot_size",
)


def get_trade_book(auth):
    """Today's trades (https://vortex.rupeezy.in/docs/latest/trades/).

    Trade rows can arrive with only order_id, trade_no, trade_price,
    trade_quantity and traded_at. Rows without a ticker are completed from the
    order book by order_id, at the cost of one extra call.
    """
    payload = request_json("GET", "/trading/trades", auth)
    trades = payload.get("trades") if isinstance(payload, dict) else None
    if not trades or all(t.get("ticker") for t in trades):
        return payload

    book = get_order_book(auth)
    if book.get("status") != "success":
        logger.warning(f"Rupeezy trade book: order book unavailable ({book.get('message')})")
        return payload
    orders = {o.get("order_id"): o for o in book.get("orders") or []}
    for trade in trades:
        order = orders.get(trade.get("order_id"))
        if not order:
            continue
        for field in _TRADE_FIELDS_FROM_ORDER:
            if not trade.get(field) and order.get(field) is not None:
                trade[field] = order[field]
    return payload


def get_positions(auth):
    """Position book. Vortex returns no LTP here, and quotes are outside this
    plugin's scope, so open positions carry no live P&L."""
    return request_json("GET", "/trading/portfolio/positions", auth)


def get_holdings(auth):
    """Holdings. Each row carries Vortex's own `last_price`."""
    return request_json("GET", "/trading/portfolio/holdings", auth)


# --- Smart-order position cache and per-symbol lock --------------------------

_SMART_ORDER_LOCKS = SymbolLocks(name="rupeezy smart orders")
_position_cache = PositionBookCache()


def _position_book_ok(payload):
    return isinstance(payload, dict) and payload.get("status") == "success"


def _get_cached_positions(auth):
    return _position_cache.get(
        auth,
        lambda: read_position_book("rupeezy", lambda: get_positions(auth), _position_book_ok),
    )


def _get_symbol_lock(symbol, exchange, product):
    """Per-symbol smart-order lock. Yields False when the bounded gthread wait
    ran out; the caller then returns SymbolLocks.busy(symbol)."""
    return _SMART_ORDER_LOCKS.hold(symbol, exchange, product)


def _invalidate_position_cache(auth):
    """Drop the cached book so the next queued smart order reads a fresh one."""
    _position_cache.invalidate(auth)


def _net_positions(payload):
    data = (payload or {}).get("data") or {}
    return data.get("net") or [] if isinstance(data, dict) else []


def get_open_position(tradingsymbol, exchange, product, auth):
    """Net quantity (OpenAlgo units, as str) for symbol/exchange/Vortex product."""
    ticker, brexchange, lotsize = resolve_instrument(tradingsymbol, exchange)
    for position in _net_positions(_get_cached_positions(auth)):
        if position.get("ticker") == ticker and position.get("product") == product:
            return str(from_vortex_quantity(position.get("quantity"), brexchange, lotsize))
    return "0"


# --- Orders -----------------------------------------------------------------


def place_order_api(data, auth):
    """Place a regular order. Returns (response, response_data, orderid)."""
    try:
        payload = transform_data(data)
    except ValueError as e:
        return _LocalResponse(400), {"status": "error", "message": str(e)}, None

    logger.debug(f"Rupeezy place order payload: {payload}")
    response = request("POST", "/trading/orders/regular", auth, payload=payload)
    try:
        response_data = response.json()
    except ValueError:
        response_data = {"status": "error", "message": "Rupeezy returned an unexpected response."}
    logger.debug(f"Rupeezy place order response: {response.status_code} {response_data}")

    orderid = None
    if response_data.get("status") == "success":
        orderid = (response_data.get("data") or {}).get("order_id")
    elif response.status_code == 200:
        # Error envelope with HTTP 200: make the service see a failure.
        response.status_code = 400

    response.status = response.status_code
    return response, response_data, orderid


@refuse_smart_order_on_read_failure
def place_smartorder_api(data, auth):
    """Reconcile the live position to data['position_size'] and place the difference."""
    res = None
    response_data = {"status": "error", "message": "No action required or invalid parameters"}
    orderid = None

    try:
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        product = data.get("product")
        if not all([symbol, exchange, product]):
            return res, response_data, orderid

        with _get_symbol_lock(symbol, exchange, product) as acquired:
            if not acquired:
                return SymbolLocks.busy(symbol)

            position_size = int(data.get("position_size", "0"))
            current_position = int(
                get_open_position(symbol, exchange, map_product_type(product), auth)
            )

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
                _invalidate_position_cache(auth)
                return res, response, orderid

            return (
                res,
                {"status": "success", "message": "No action needed. Position already matched."},
                orderid,
            )

    except PositionReadError:
        raise
    except BrokerBusyError as busy:
        # Refused by the rate-limit pacer before anything was sent (gthread
        # worker only). Keep the busy answer rather than a generic error.
        return busy_response(str(busy))
    except Exception as e:
        logger.exception("Error in Rupeezy place_smartorder_api")
        return res, {"status": "error", "message": f"Error in place_smartorder_api: {e}"}, orderid


def close_all_positions(current_api_key, auth):
    """Square off every open net position at market.

    Reports what actually happened: a position book that could not be read is
    an error (not "no positions"), and any square-off Vortex refuses (for
    example the static-IP check) is listed with its reason.
    """
    payload = get_positions(auth)
    if not _position_book_ok(payload):
        message = payload.get("message") if isinstance(payload, dict) else None
        return {
            "status": "error",
            "message": f"Could not read positions from Rupeezy: {message or 'unknown error'}",
        }, 502

    positions = [p for p in _net_positions(payload) if int(_f(p.get("quantity"))) != 0]
    if not positions:
        return {"message": "No Open Positions Found"}, 200

    failed = []
    for position in positions:
        ticker = position.get("ticker")
        oa_exchange = oa_exchange_for(position.get("exchange"))
        symbol = get_oa_symbol(brsymbol=split_ticker(ticker), exchange=oa_exchange)
        if not symbol:
            logger.error(f"Square-off skipped, symbol not in master contract: {ticker}")
            failed.append(f"{ticker}: not in the master contract")
            continue
        quantity = from_vortex_quantity(
            position.get("quantity"),
            position.get("exchange"),
            lot_size_for(position, symbol, oa_exchange),
        )
        order = {
            "apikey": current_api_key,
            "strategy": "Squareoff",
            "symbol": symbol,
            "action": "SELL" if quantity > 0 else "BUY",
            "exchange": oa_exchange,
            "pricetype": "MARKET",
            "product": reverse_map_product_type(oa_exchange, position.get("product")),
            "quantity": str(abs(quantity)),
        }
        _, api_response, orderid = place_order_api(order, auth)
        logger.debug(f"Rupeezy square-off response: {api_response}")
        if not orderid:
            failed.append(f"{symbol}: {api_response.get('message', 'order rejected')}")

    _invalidate_position_cache(auth)
    if failed:
        closed = len(positions) - len(failed)
        return {
            "status": "error",
            "message": f"Squared off {closed} of {len(positions)} positions. Failed: "
            + "; ".join(failed),
        }, 400
    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    try:
        payload = request_json("DELETE", f"/trading/orders/regular/{orderid}", auth)
        if payload.get("status") == "success":
            return {"status": "success", "orderid": orderid}, 200
        return {"status": "error", "message": payload.get("message", "Failed to cancel order")}, 400
    except Exception as e:
        logger.exception(f"Error cancelling Rupeezy order {orderid}")
        return {"status": "error", "message": f"Failed to cancel order: {e}"}, 500


def _latest_order_state(orderid, auth):
    """Most recent history row for an order (history is newest first).

    Returns None when Vortex answers but has no such order. Raises
    RupeezyAPIError when the history could not be read at all, so a session
    or server error is not reported as a missing order.
    """
    payload = request_json("GET", f"/trading/orders/{orderid}", auth)
    if payload.get("status") != "success":
        raise RupeezyAPIError(payload.get("message") or "Could not read the order from Rupeezy.")
    rows = payload.get("data") or []
    return rows[0] if rows else None


def modify_order(data, auth):
    """Modify an open order. Vortex needs the latest traded_quantity, so the
    order's current state is read first."""
    orderid = data["orderid"]
    try:
        _, brexchange, lotsize = resolve_instrument(data["symbol"], data["exchange"])
        state = _latest_order_state(orderid, auth)
        if state is None:
            return {"status": "error", "message": f"Order {orderid} was not found."}, 404
        payload = transform_modify_order_data(
            data, state.get("traded_quantity"), brexchange, lotsize
        )
    except ValueError as e:
        return {"status": "error", "message": str(e)}, 400
    except BrokerBusyError:
        raise  # the modify service answers it as busy
    except RupeezyAPIError as e:
        logger.exception(f"Could not read Rupeezy order {orderid} before modifying it")
        return {"status": "error", "message": str(e)}, 502
    except Exception as e:
        logger.exception(f"Error preparing Rupeezy modify for {orderid}")
        return {"status": "error", "message": f"Failed to modify order: {e}"}, 500

    logger.debug(f"Rupeezy modify order payload: {payload}")
    response_data = request_json("PUT", f"/trading/orders/regular/{orderid}", auth, payload=payload)
    if response_data.get("status") == "success":
        return {
            "status": "success",
            "orderid": (response_data.get("data") or {}).get("order_id", orderid),
        }, 200
    return {
        "status": "error",
        "message": response_data.get("message", "Failed to modify order"),
    }, 400


def cancel_all_orders_api(data, auth):
    """Cancel every open / trigger-pending order."""
    book = get_order_book(auth)
    if book.get("status") != "success":
        # Not "nothing to cancel": nothing was checked. The service turns this
        # into an error for the caller.
        raise RupeezyAPIError(book.get("message") or "Could not read the order book from Rupeezy.")

    canceled, failed = [], []
    for order in book.get("orders", []):
        if map_status(order.get("status")) not in OPEN_STATUSES:
            continue
        orderid = order.get("order_id")
        _, status_code = cancel_order(orderid, auth)
        (canceled if status_code == 200 else failed).append(orderid)
    return canceled, failed
