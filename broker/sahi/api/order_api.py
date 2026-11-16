"""Sahi orders, order book, trades, positions and holdings.

Endpoints (broker-api-docs/sahi-api-docs, Orders and Portfolio):

    POST   /v1/orders                     place        -> 201 {"order_ids": [...]}
    PUT    /v1/orders/{order_id}          modify       -> 200 {"order_id": ...}
    DELETE /v1/orders/{order_id}          cancel       -> 204
    GET    /v1/orders                     today's order book {"orders": [...]}
    GET    /v1/orders/{order_id}/trades   fills of one order {"trades": [...]}
    GET    /v1/positions                  {"positions": [...]}
    GET    /v1/holdings                   {"holdings": [...]}

Errors come back as {"code", "message"} with a non-2xx status. Sahi has no
day-wide trade book, so the trade book is assembled from the trades of every
order that has filled. Positions and holdings carry no last price, so it is
read once per call from /v1/marketdata/ltp (up to 100 instruments a request).

Order writes must come from the static IP registered in the Sahi API
Dashboard; anything else is refused with 403 IP_NOT_ALLOWED.
"""

from broker.sahi.api.baseurl import get_headers, get_url
from broker.sahi.api.rate_limiter import sahi_request
from broker.sahi.mapping.transform_data import (
    EXCHANGE_SEGMENT_MAP,
    OrderMappingError,
    from_paise,
    map_product_type,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_br_symbol, get_oa_symbol
from utils.broker_backpressure import BrokerBusyError
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from utils.position_read import (
    PositionReadError,
    read_position_book,
    refuse_smart_order_on_read_failure,
)
from utils.smart_order_guard import PositionBookCache, SymbolLocks

logger = get_logger(__name__)

LTP_BATCH_SIZE = 100

# Order statuses that can still be cancelled or modified.
WORKING_STATUSES = ("Open", "OpenPartial")


class _Response:
    """Stands in for an httpx response where the caller reads ``.status``."""

    def __init__(self, status):
        self.status = status
        self.status_code = status


def _error_message(status_code, body):
    """A Sahi error reply in words a trader can act on."""
    code = body.get("code") if isinstance(body, dict) else None
    message = body.get("message") if isinstance(body, dict) else None
    if code == "IP_NOT_ALLOWED":
        return (
            "Sahi refused the order because it did not come from your registered static IP. "
            "Check the IP in Sahi web, Profile, API Dashboard, and that OpenAlgo runs on that machine."
        )
    if status_code == 401 or code == "UNAUTHORIZED":
        return "Your Sahi session has expired. Log in to OpenAlgo again."
    if code == "FORBIDDEN":
        return (
            "Your Sahi API key does not have permission for this. Create a key with Full access "
            "in the Sahi API Dashboard and use it in OpenAlgo."
        )
    if code == "RATE_LIMITED" or status_code == 429:
        return "Sahi is limiting requests right now. Wait a few seconds and try again."
    if message:
        return message
    if status_code and status_code >= 500:
        return "Sahi is not responding right now. Try again in a moment."
    return "Sahi did not accept the request."


def _call(method, path, auth, category, json=None, params=None):
    """One Sahi API call. Returns (status_code, body); body is {} when empty."""
    client = get_httpx_client()
    response = sahi_request(
        client,
        method,
        get_url(path),
        category,
        headers=get_headers(auth, json_body=json is not None),
        json=json,
        params=params,
        timeout=30,
    )
    body = {}
    if response.content:
        try:
            body = response.json()
        except ValueError:
            body = {"message": response.text[:200]}
    return response.status_code, body


def _read(path, auth, category, key):
    """GET a book. Returns the raw dict on success, an error envelope otherwise."""
    try:
        status, body = _call("GET", path, auth, category)
    except BrokerBusyError:
        raise
    except Exception:
        logger.exception(f"Sahi request for {path} failed")
        return {"status": "error", "message": "Could not reach Sahi. Check your connection."}
    if status == 200 and isinstance(body, dict) and key in body:
        return body
    logger.error(f"Sahi {path} returned HTTP {status}: {body}")
    return {"status": "error", "message": _error_message(status, body)}


def get_ltp_map(instrument_ids, auth):
    """Last traded price in rupees per instrument id, read in batches of 100."""
    ids = sorted({int(i) for i in instrument_ids if i not in (None, "")})
    ltp = {}
    for start in range(0, len(ids), LTP_BATCH_SIZE):
        batch = ids[start : start + LTP_BATCH_SIZE]
        try:
            status, body = _call("GET", "/v1/marketdata/ltp", auth, "ltp", params={"i": batch})
        except BrokerBusyError:
            raise
        except Exception:
            logger.exception("Sahi LTP request failed")
            continue
        if status != 200:
            logger.warning(f"Sahi LTP returned HTTP {status}: {body}")
            continue
        for key, value in (body.get("data") or {}).items():
            if isinstance(value, dict) and value.get("last_trade_price") is not None:
                ltp[int(key)] = from_paise(value["last_trade_price"])
    return ltp


def get_order_book(auth):
    return _read("/v1/orders", auth, "order_read", "orders")


def get_trade_book(auth):
    """Every fill today, gathered from the trades of each order that filled."""
    book = get_order_book(auth)
    if book.get("status") == "error":
        return book
    trades = []
    for order in book.get("orders", []):
        if not order.get("filled_qty"):
            continue
        result = _read(f"/v1/orders/{order['order_id']}/trades", auth, "order_read", "trades")
        if result.get("status") == "error":
            return result
        trades.extend(result.get("trades", []))
    return {"trades": trades}


def get_positions(auth):
    """The position book, with each row's last price added as ``ltp`` (rupees)."""
    book = _read("/v1/positions", auth, "positions", "positions")
    if book.get("status") == "error":
        return book
    positions = book.get("positions") or []
    if positions:
        ltp = get_ltp_map([p.get("instrument_id") for p in positions], auth)
        for position in positions:
            position["ltp"] = ltp.get(int(position.get("instrument_id") or 0), 0.0)
    return book


def get_holdings(auth):
    """Demat holdings, with the last price of each ISIN's listing as ``ltp``."""
    book = _read("/v1/holdings", auth, "holdings", "holdings")
    if book.get("status") == "error":
        return book
    holdings = book.get("holdings") or []
    ids = [i for h in holdings for i in (h.get("instrument_ids") or [])]
    if ids:
        ltp = get_ltp_map(ids, auth)
        for holding in holdings:
            holding["ltp_by_id"] = {
                i: ltp[i] for i in holding.get("instrument_ids") or [] if i in ltp
            }
    return book


# --- Smart order: one per symbol at a time, against a 1 s position cache ---
_SMART_ORDER_LOCKS = SymbolLocks()
_POSITION_BOOK = PositionBookCache()


def _position_book_ok(book):
    return isinstance(book, dict) and isinstance(book.get("positions"), list)


def _fetch_position_book(auth):
    book = _read("/v1/positions", auth, "positions", "positions")
    if book.get("status") == "error":
        raise RuntimeError(book.get("message"))
    return book


def _get_cached_positions(auth):
    return _POSITION_BOOK.get(
        auth,
        lambda: read_position_book("sahi", lambda: _fetch_position_book(auth), _position_book_ok),
    )


def get_open_position(tradingsymbol, exchange, product, auth):
    """Net quantity (str) of one symbol and product in the position book.

    ``product`` is the Sahi product code (C, I, M).
    """
    brsymbol = get_br_symbol(tradingsymbol, exchange)
    segment = EXCHANGE_SEGMENT_MAP.get(exchange, exchange)
    book = _get_cached_positions(auth)
    for position in book.get("positions", []):
        if (
            position.get("symbol") == brsymbol
            and position.get("exchange_segment") == segment
            and position.get("product") == product
        ):
            return str(position.get("net_qty", 0))
    return "0"


def place_order_api(data, auth):
    """Place one order. Returns (response, response_data, orderid)."""
    try:
        payload = transform_data(data)
    except OrderMappingError as exc:
        logger.info(f"Rejected order before sending to Sahi: {exc}")
        return _Response(400), {"status": "error", "message": str(exc)}, None

    logger.debug(f"Sahi place order payload: {payload}")
    status, body = _call("POST", "/v1/orders", auth, "order_write", json=payload)
    logger.debug(f"Sahi place order response: HTTP {status} {body}")

    if status in (200, 201) and isinstance(body, dict) and body.get("order_ids"):
        order_ids = [str(i) for i in body["order_ids"]]
        if len(order_ids) > 1:
            logger.warning(f"Sahi returned several order ids for one order: {order_ids}")
        return _Response(200), {"status": "success", "orderid": order_ids[0]}, order_ids[0]

    message = _error_message(status, body)
    logger.error(f"Sahi refused order: HTTP {status} {body}")
    return (
        _Response(status if status >= 400 else 500),
        {"status": "error", "message": message},
        None,
    )


@refuse_smart_order_on_read_failure
def place_smartorder_api(data, auth):
    res = None
    response_data = {"status": "error", "message": "No action required or invalid parameters"}
    orderid = None

    try:
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        product = data.get("product")
        if not all([symbol, exchange, product]):
            return res, response_data, orderid

        with _SMART_ORDER_LOCKS.hold(symbol, exchange, product) as symbol_lock:
            if not symbol_lock:
                return SymbolLocks.busy(symbol)

            position_size = int(data.get("position_size", "0"))
            current_position = int(
                get_open_position(symbol, exchange, map_product_type(product), auth)
            )
            logger.debug(
                f"Smart order {symbol}: target {position_size}, current {current_position}"
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
                _POSITION_BOOK.invalidate(auth)
                return res, response, orderid

            return (
                res,
                {"status": "success", "message": "No action needed. Position already matched."},
                None,
            )

    except (PositionReadError, BrokerBusyError):
        raise
    except Exception as e:
        logger.exception("Error in Sahi place_smartorder_api")
        return res, {"status": "error", "message": f"Smart order failed: {e}"}, orderid


def close_all_positions(current_api_key, auth):
    book = _read("/v1/positions", auth, "positions", "positions")
    if book.get("status") == "error":
        return {"status": "error", "message": book.get("message")}, 500

    open_positions = [p for p in book.get("positions", []) if int(p.get("net_qty") or 0) != 0]
    if not open_positions:
        return {"message": "No Open Positions Found"}, 200

    failures = []
    for position in open_positions:
        net_qty = int(position["net_qty"])
        segment = position.get("exchange_segment")
        symbol = get_oa_symbol(position.get("symbol"), segment) or position.get("symbol")
        product = reverse_map_product_type(position.get("product"))
        if product not in ("CNC", "MIS", "NRML"):
            failures.append(
                f"{symbol} ({segment}): {product} positions must be closed in the Sahi app"
            )
            continue

        order = {
            "apikey": current_api_key,
            "strategy": "Squareoff",
            "symbol": symbol,
            "action": "SELL" if net_qty > 0 else "BUY",
            "exchange": segment,
            "pricetype": "MARKET",
            "product": product,
            "quantity": str(abs(net_qty)),
        }
        res, api_response, order_id = place_order_api(order, auth)
        if getattr(res, "status", None) != 200 or not order_id:
            reason = (
                api_response.get("message", "order was refused")
                if isinstance(api_response, dict)
                else "order was refused"
            )
            failures.append(f"{symbol} ({segment}): {reason}")
            logger.error(f"Square-off failed for {symbol}: {reason}")

    _POSITION_BOOK.invalidate(auth)
    if failures:
        return {
            "status": "error",
            "message": f"{len(failures)} position(s) could not be squared off and are still open: {'; '.join(failures)}",
        }, 500
    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    try:
        status, body = _call("DELETE", f"/v1/orders/{orderid}", auth, "order_write")
    except BrokerBusyError:
        raise
    except Exception:
        logger.exception(f"Error cancelling Sahi order {orderid}")
        return {"status": "error", "message": "Could not reach Sahi to cancel the order."}, 500

    if status in (200, 204):
        return {"status": "success", "orderid": str(orderid)}, 200
    logger.error(f"Sahi refused cancel of {orderid}: HTTP {status} {body}")
    return {
        "status": "error",
        "message": _error_message(status, body),
    }, status if status >= 400 else 500


def modify_order(data, auth):
    orderid = data.get("orderid")
    try:
        payload = transform_modify_order_data(data)
    except OrderMappingError as exc:
        return {"status": "error", "message": str(exc)}, 400

    try:
        status, body = _call("PUT", f"/v1/orders/{orderid}", auth, "order_write", json=payload)
    except BrokerBusyError:
        raise
    except Exception:
        logger.exception(f"Error modifying Sahi order {orderid}")
        return {"status": "error", "message": "Could not reach Sahi to modify the order."}, 500

    if status == 200:
        return {"status": "success", "orderid": str(body.get("order_id") or orderid)}, 200
    logger.error(f"Sahi refused modify of {orderid}: HTTP {status} {body}")
    return {
        "status": "error",
        "message": _error_message(status, body),
    }, status if status >= 400 else 500


def cancel_all_orders_api(data, auth):
    book = get_order_book(auth)
    if book.get("status") == "error":
        return [], []

    canceled, failed = [], []
    for order in book.get("orders", []):
        if order.get("status") not in WORKING_STATUSES:
            continue
        orderid = order["order_id"]
        _, status_code = cancel_order(orderid, auth)
        (canceled if status_code == 200 else failed).append(orderid)
    return canceled, failed
