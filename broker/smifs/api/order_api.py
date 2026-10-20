"""SMIFS God Quant order operations for OpenAlgo.

Every function receives the decrypted SMIFS access token as `auth` and puts
it in the `access-token` header. Symbol/token translation uses OpenAlgo's
shared master-contract helpers (get_token / get_symbol).
"""

import json
import time

from broker.smifs.api.baseurl import REQUEST_TIMEOUT, get_url
from broker.smifs.mapping.transform_data import (
    map_exchange,
    map_exchange_type,
    map_product_type,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from utils.position_read import read_position_book, refuse_smart_order_on_read_failure
from utils.smart_order_guard import PositionBookCache, SymbolLocks

logger = get_logger(__name__)

# Order states from which SMIFS still accepts a cancel.
_CANCELLABLE = ("TRANSIT", "PENDING", "PARTIALLY_FILLED")


def _headers(auth):
    return {"access-token": auth, "Content-Type": "application/json"}


def _error(r, body):
    """SMIFS errors carry errorCode/errorMessage; OpenAlgo expects status=error."""
    message = body.get("errorMessage") if isinstance(body, dict) else None
    code = body.get("errorCode") if isinstance(body, dict) else None
    if message and code:
        message = f"{code}: {message}"
    return {"status": "error", "message": message or f"HTTP {r.status_code}"}


# SMIFS answers 429 before it processes a call, so a retry can never place
# an order twice. Demo tokens allow 5 order calls a second and registered
# tokens 10, so a loop such as cancel-all or close-all can reach the limit.
_RETRIES_ON_429 = 2
_MAX_WAIT_SEC = 2.0


def _send(method, path, auth, payload=None):
    """One HTTP call to SMIFS, retried briefly when the rate limit answers 429."""
    client = get_httpx_client()
    kwargs = {"headers": _headers(auth), "timeout": REQUEST_TIMEOUT}
    if payload is not None:
        kwargs["content"] = json.dumps(payload)
    for attempt in range(_RETRIES_ON_429 + 1):
        r = client.request(method, get_url(path), **kwargs)
        if r.status_code != 429 or attempt == _RETRIES_ON_429:
            return r
        try:
            wait = float(r.headers.get("Retry-After", "1"))
        except ValueError:
            wait = 1.0
        time.sleep(min(max(wait, 0.2), _MAX_WAIT_SEC))
    return r


def _get(path, auth):
    """GET a list endpoint. Returns the list, or an OpenAlgo error dict."""
    r = _send("GET", path, auth)
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = {}
    if r.status_code != 200:
        return _error(r, body)
    return body


def _rows(data):
    """A list response, or an empty list when the call failed."""
    return data if isinstance(data, list) else []


def get_order_book(auth):
    return _get("/v1/orders", auth)


def get_trade_book(auth):
    return _get("/v1/trades", auth)


def get_positions(auth):
    return _get("/v1/positions", auth)


def get_holdings(auth):
    return _get("/v1/holdings", auth)


# --- Smart order guards ---
# Smart orders for one symbol are serialised, and the position book they read
# is cached for a second and invalidated after every placement, so two
# concurrent signals cannot both read the old position and double the order.
_SMART_ORDER_LOCKS = SymbolLocks()
_POSITION_BOOK = PositionBookCache()


def _get_symbol_lock(symbol, exchange, product):
    """Hold the smart order lock for one symbol, as a context manager.

    Yields True while holding it, and False when the wait ran out under the
    gthread worker, in which case the caller answers SymbolLocks.busy(symbol).
    """
    return _SMART_ORDER_LOCKS.hold(symbol, exchange, product)


def _position_book_ok(positions_data):
    """GET /v1/positions answers a JSON list, empty when there are no positions.

    A failed call comes back from _get as an error dict, which is a failed read.
    """
    return isinstance(positions_data, list)


def _get_cached_positions(auth):
    """The position book, from the cache when fresh, otherwise from the server."""
    return _POSITION_BOOK.get(
        auth,
        lambda: read_position_book("smifs", lambda: get_positions(auth), _position_book_ok),
    )


def _invalidate_position_cache(auth):
    """Drop the cached book so the next smart order reads the position afresh."""
    _POSITION_BOOK.invalidate(auth)


def get_open_position(tradingsymbol, exchange, product, auth):
    """Net quantity of one position, as a string. `product` is OpenAlgo's code (CNC/MIS/NRML)."""
    token = str(get_token(tradingsymbol, exchange))
    segment = map_exchange_type(exchange)
    wanted_product = map_product_type(product)
    for p in _rows(_get_cached_positions(auth)):
        if (
            str(p.get("securityId")) == token
            and p.get("exchangeSegment") == segment
            and p.get("productType") == wanted_product
        ):
            return str(p.get("netQty", 0))
    return "0"


def _post_order(payload, auth):
    r = _send("POST", "/v1/orders", auth, payload)
    r.status = r.status_code
    try:
        response = r.json()
    except Exception:  # noqa: BLE001
        response = {}
    orderid = response.get("orderId") if r.status_code == 200 else None
    if r.status_code != 200:
        response = _error(r, response)
    return r, response, orderid


def place_order_api(data, auth):
    if data.get("exchange") in ("NSE_INDEX", "BSE_INDEX"):
        return (
            None,
            {
                "status": "error",
                "message": "an index cannot be traded; trade its futures or options instead",
            },
            None,
        )
    token = get_token(data["symbol"], data["exchange"])
    if token is None:
        return (
            None,
            {
                "status": "error",
                "message": f"{data['symbol']} is not in the SMIFS master contract for {data['exchange']}",
            },
            None,
        )
    return _post_order(transform_data(data, token), auth)


@refuse_smart_order_on_read_failure
def place_smartorder_api(data, auth):
    """Position-sizing order: move the net position to `position_size`.

    Follows OpenAlgo's convention: when both the target and the current
    position are zero, the request is a plain order for `quantity`; when the
    position already matches, nothing is placed and `res` is None. A failed
    position read refuses the order rather than guessing the position.
    """
    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product", "MIS")
    with _get_symbol_lock(symbol, exchange, product) as held:
        if not held:
            return SymbolLocks.busy(symbol)
        target = int(data.get("position_size", 0) or 0)
        quantity = int(data.get("quantity", 0) or 0)
        current = int(get_open_position(symbol, exchange, product, auth) or 0)
        if target == 0 and current == 0 and quantity != 0:
            result = place_order_api(data, auth)
            _invalidate_position_cache(auth)
            return result
        delta = target - current
        if delta == 0:
            message = (
                "No OpenPosition Found. Not placing Exit order."
                if quantity == 0
                else "No action needed. Position size matches current position"
            )
            return None, {"status": "success", "message": message}, None
        order = dict(data)
        order["action"] = "BUY" if delta > 0 else "SELL"
        order["quantity"] = str(abs(delta))
        result = place_order_api(order, auth)
        _invalidate_position_cache(auth)
        return result


def modify_order(data, auth):
    payload = transform_modify_order_data(data)
    orderid = data["orderid"]
    r = _send("PUT", f"/v1/orders/{orderid}", auth, payload)
    if r.status_code == 200:
        return {"status": "success", "orderid": orderid}, 200
    return {"status": "error", "message": _msg(r)}, r.status_code


def cancel_order(orderid, auth):
    r = _send("DELETE", f"/v1/orders/{orderid}", auth)
    if r.status_code == 200:
        return {"status": "success", "orderid": orderid}, 200
    return {"status": "error", "message": _msg(r)}, r.status_code


def cancel_all_orders_api(data, auth):
    canceled, failed = [], []
    for o in _rows(get_order_book(auth)):
        if str(o.get("orderStatus", "")).upper() in _CANCELLABLE:
            oid = o.get("orderId")
            _, code = cancel_order(oid, auth)
            (canceled if code == 200 else failed).append(oid)
    return canceled, failed


def close_all_positions(current_api_key, auth):
    """Square off every open position in the product it is held in.

    The order is built from the position's own securityId and segment, so it
    does not depend on the trading symbol round-tripping through the master
    contract (derivative symbols on the position record are not in OpenAlgo
    format).
    """
    positions = get_positions(auth)
    if not _position_book_ok(positions):
        # The book could not be read, so the open positions are unknown.
        # Reporting success here would claim a square-off that never happened.
        message = positions.get("message") if isinstance(positions, dict) else None
        return {
            "status": "error",
            "message": "could not read the position book, so nothing was squared off"
            + (f": {message}" if message else ""),
        }, 500
    failed = []
    for p in positions:
        net = int(p.get("netQty", 0) or 0)
        if net == 0:
            continue
        order = {
            "action": "SELL" if net > 0 else "BUY",
            "exchange": map_exchange(p.get("exchangeSegment")),
            "quantity": abs(net),
            "pricetype": "MARKET",
            # close in the SAME product the position is held in, else an
            # intraday offset is placed while the real position stays open
            "product": reverse_map_product_type(p.get("productType")),
        }
        r, response, _ = _post_order(transform_data(order, p.get("securityId")), auth)
        if r.status_code != 200:
            failed.append(f"{p.get('tradingSymbol')}: {response.get('message')}")
    if failed:
        return {"status": "error", "message": "could not square off " + "; ".join(failed)}, 500
    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def _msg(r):
    try:
        return r.json().get("errorMessage", f"HTTP {r.status_code}")
    except Exception:  # noqa: BLE001
        return f"HTTP {r.status_code}"
