import json
import threading
import time

from broker.nubra.api.baseurl import (
    SESSION_EXPIRED_MESSAGE,
    SESSION_EXPIRED_STATUS,
    get_base_url,
    get_nubra_headers,
)
from broker.nubra.mapping.order_data import (
    extract_positions,
    flatten_order_buckets,
    position_net_qty,
    resolve_position,
)
from broker.nubra.mapping.transform_data import (
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Nubra documents 100 ops/sec on UAT for trading APIs and says to treat it as a
# validation baseline rather than a production throughput promise, so the
# sequential loops below pace themselves at 10 ops/sec.
_MAX_RETRIES = 3
_RATE_LIMIT_BASE_DELAY = 1.0  # Base delay for 429 retry (seconds)

# Nubra V3 lifecycle buckets returned by GET /sentinel/orders, mapped to the
# OpenAlgo status vocabulary. Orders arrive grouped by bucket rather than as a
# flat list, so the bucket name IS the status.
_WORKING_BUCKETS = ("open", "gtt")


class _StubResponse:
    """Minimal response stand-in for paths that fail before any HTTP call.

    The service layer only reads ``.status`` (and occasionally ``.text``), so we
    mimic an httpx response without performing a request.
    """

    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.status = status_code
        self.text = text

    def json(self):
        return {}


def _error_payload(status_code, data):
    """
    Standardize a failed Nubra response for OpenAlgo's service layer.

    The account services (orderbook, tradebook, positionbook, holdings) all
    check for ``{"status": "error", "message": ...}``. Returning the raw V3
    body instead means a 440 flattens to an empty bucket list and the user sees
    an empty order book rather than "session expired".
    """
    if not isinstance(data, dict):
        data = {}

    if status_code == SESSION_EXPIRED_STATUS:
        message = SESSION_EXPIRED_MESSAGE
    else:
        message = (
            data.get("error")
            or data.get("message")
            or f"Nubra request failed (HTTP {status_code})"
        )

    payload = dict(data)
    payload["status"] = "error"
    payload["message"] = str(message)
    return payload


def is_error_response(response):
    """
    True when a Nubra response represents a failure rather than data.

    Covers both shapes: the raw V3 body (``{"error": ...}``) and the
    standardized form _error_payload() produces (``{"status": "error"}``).
    Checking only ``error`` misses every 440, which carries no ``error`` key --
    and a missed failure reads downstream as "no open positions".
    """
    if not isinstance(response, dict):
        return False
    return bool(response.get("error")) or response.get("status") == "error"


def _promote_error_to_message(response_data):
    """
    Copy a V3 ``error`` string into ``message`` when only ``error`` is present.

    The V3 error shape is ``{"error": "...", "nubra_error_code": ""}`` and the
    docs say to surface the ``error`` string directly, but OpenAlgo's service
    layer reads ``message``. Leaves an existing ``message`` untouched.
    """
    if not isinstance(response_data, dict):
        return response_data
    if not response_data.get("message") and response_data.get("error"):
        response_data["message"] = str(response_data["error"])
    return response_data


def get_api_response(endpoint, auth, method="GET", payload=""):
    client = get_httpx_client()
    headers = get_nubra_headers(auth)
    url = f"{get_base_url()}{endpoint}"

    if isinstance(payload, (dict, list)):
        payload = json.dumps(payload)

    for attempt in range(_MAX_RETRIES):
        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, headers=headers, content=payload)
        else:
            response = client.request(method, url, headers=headers, content=payload)

        # Handle rate limiting with exponential backoff
        if response.status_code == 429:
            delay = _RATE_LIMIT_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"Rate limit hit (429) on {endpoint}, retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{_MAX_RETRIES})"
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(delay)
                continue
            else:
                logger.error(f"Rate limit exceeded after {_MAX_RETRIES} retries on {endpoint}")
                return {"error": "Rate limit exceeded. Please reduce request frequency."}

        break  # Non-429 response, proceed

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    if response.status_code == SESSION_EXPIRED_STATUS:
        logger.error(f"Nubra session expired (HTTP 440) on {endpoint}; re-authentication required")
        return _error_payload(response.status_code, {})

    # Handle empty response
    if not response.text:
        if response.status_code >= 400:
            return _error_payload(response.status_code, {})
        return {}

    try:
        data = json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from {endpoint}: {response.text}")
        return _error_payload(response.status_code, {}) if response.status_code >= 400 else {}

    if response.status_code >= 400:
        logger.error(f"Nubra request failed on {endpoint} (HTTP {response.status_code}): {data}")
        return _error_payload(response.status_code, data)

    return data


def get_order_book(auth):
    """
    Fetch all orders for the day from Nubra.

    Nubra API: GET /sentinel/orders
    Returns the raw bucketed response; use flatten_order_buckets() to iterate.
    """
    return get_api_response("/sentinel/orders", auth)


def get_trade_book(auth):
    """
    Fetch the trade book from Nubra.

    Nubra has no separate tradebook endpoint -- trades are derived from filled
    orders in the same bucketed order response.

    Nubra API: GET /sentinel/orders
    """
    return get_api_response("/sentinel/orders", auth)


def get_positions(auth):
    """
    Fetch positions from Nubra.

    Nubra API: GET /sentinel/portfolio/positions
    Returns {"portfolio": {"positions": [...], "positionStats": {...}}} with a
    flat positions list (V2's stock/fut/opt split is gone in V3).
    """
    response = get_api_response("/sentinel/portfolio/positions", auth)
    logger.debug(f"Nubra Raw position book response: {response}")
    return response


def get_holdings(auth):
    """
    Fetch portfolio holdings from Nubra.

    Nubra API: GET /sentinel/portfolio/holdings
    Returns {"portfolio": {"holdings": [...], "holdingStats": {...}}}.
    Prices are in paise (divide by 100 for rupees).
    """
    return get_api_response("/sentinel/portfolio/holdings", auth)


# --- Per-Symbol Smart Order Lock ---
# Ensures only one smart order per symbol executes at a time.
# Others queue and execute sequentially, each getting a fresh position book.
_symbol_locks = {}          # {symbol_key: threading.Lock}
_symbol_locks_lock = threading.Lock()

# --- Position Book Cache ---
# Caches get_positions() for 1 second. Invalidated after each smart order placement.
_position_cache = {}        # {auth_token: {"data": ..., "timestamp": ...}}
_position_cache_lock = threading.Lock()
_POSITION_CACHE_TTL = 1.0   # seconds


def _get_symbol_lock(symbol, exchange, product):
    """Get or create a per-symbol lock for serializing smart orders."""
    key = f"{symbol}:{exchange}:{product}"
    with _symbol_locks_lock:
        if key not in _symbol_locks:
            _symbol_locks[key] = threading.Lock()
        return _symbol_locks[key]


def _get_cached_positions(auth):
    """Get positions from cache if fresh, otherwise fetch from broker API."""
    with _position_cache_lock:
        now = time.monotonic()
        cached = _position_cache.get(auth)
        if cached and (now - cached["timestamp"]) < _POSITION_CACHE_TTL:
            return cached["data"]

    # Cache miss or expired - fetch from broker
    positions_data = get_positions(auth)

    with _position_cache_lock:
        _position_cache[auth] = {"data": positions_data, "timestamp": time.monotonic()}

    return positions_data


def _invalidate_position_cache(auth):
    """Invalidate the position cache so the next queued order fetches fresh data."""
    with _position_cache_lock:
        _position_cache.pop(auth, None)


def get_open_position(tradingsymbol, exchange, producttype, auth):
    """
    Get the net quantity for a specific position.

    V3 positions are a flat list carrying a signed net quantity, so there is no
    need to reconstruct direction from a separate order side.
    """
    positions_data = _get_cached_positions(auth)

    logger.debug(f"Nubra positions data: {positions_data}")

    net_qty = "0"

    for position in extract_positions(positions_data):
        # resolve_position() returns the master-contract symbol and exchange, so
        # both sides of these comparisons are in OpenAlgo terms. Comparing the
        # raw Nubra fields cannot work for F&O: Nubra reports an NFO option as
        # exchange "NSE" under its own brsymbol.
        pos_symbol, pos_exchange = resolve_position(position)
        pos_producttype = reverse_map_product_type(position.get("deliveryType", ""))

        if (
            pos_exchange == exchange
            and pos_producttype == producttype
            and pos_symbol == tradingsymbol
        ):
            net_qty = str(position_net_qty(position))
            break

    return net_qty


def place_order_api(data, auth):
    """
    Place a single order using Nubra's Trading API V3.

    Nubra API: POST /sentinel/orders/create
    The body wraps exactly one intent-order item in an ``orders`` array.
    """
    AUTH_TOKEN = auth

    # Get token (ref_id) for the symbol
    token = get_token(data["symbol"], data["exchange"])

    logger.info(f"Nubra order - Symbol: {data['symbol']}, Exchange: {data['exchange']}, Token: {token}")

    if not token or not str(token).isdigit():
        msg = f"No numeric Nubra ref_id found for {data['symbol']} on {data['exchange']}."
        logger.error(msg)
        return _StubResponse(400), {"status": False, "error": msg}, None

    pricetype = str(data.get("pricetype", "MARKET")).upper()

    # Stop orders (SL / SL-M) become an LTP entry trigger in V3, which is
    # impossible without a trigger price. Fail fast with a clear message.
    if pricetype in ("SL", "SL-M"):
        try:
            trigger = float(data.get("trigger_price", 0) or 0)
        except (TypeError, ValueError):
            trigger = 0
        if not trigger:
            msg = f"{pricetype} order requires a non-zero trigger_price for {data['symbol']} on {data['exchange']}."
            logger.error(msg)
            return _StubResponse(400), {"status": False, "error": msg}, None

    # Transform OpenAlgo data to the Nubra V3 intent-order payload
    payload = json.dumps({"orders": [transform_data(data, token)]})

    logger.info(f"Nubra place order payload: {payload}")

    client = get_httpx_client()

    # Make the request with 429 retry
    response = None
    for attempt in range(_MAX_RETRIES):
        response = client.post(
            f"{get_base_url()}/sentinel/orders/create",
            headers=get_nubra_headers(AUTH_TOKEN),
            content=payload,
        )
        if response.status_code == 429:
            delay = _RATE_LIMIT_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"Rate limit hit (429) placing order, retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{_MAX_RETRIES})"
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(delay)
                continue
            else:
                logger.error("Rate limit exceeded placing order after retries")
                response_data = {"error": "Rate limit exceeded", "status": False}
                response.status = 429
                return response, response_data, None
        break

    # Parse the JSON response
    try:
        response_data = response.json()
    except json.JSONDecodeError:
        logger.error(f"Failed to parse order response: {response.text}")
        response_data = {"error": "Failed to parse response"}
        return response, response_data, None

    logger.info(f"Nubra place order response (status={response.status_code}): {response_data}")

    # V3 returns 201 Created with the accepted order(s) under "orders"
    orders = response_data.get("orders") if isinstance(response_data, dict) else None
    intent_order_id = None
    if isinstance(orders, list) and orders and isinstance(orders[0], dict):
        intent_order_id = orders[0].get("intentOrderId")

    if response.status_code in (200, 201) and intent_order_id:
        orderid = str(intent_order_id)
        # Normalize response format for OpenAlgo compatibility
        response_data["status"] = True
        response_data["data"] = {"orderid": orderid}
        # OpenAlgo service layer expects status 200 for success
        response.status = 200
    else:
        orderid = None
        response_data["status"] = False
        if response.status_code == SESSION_EXPIRED_STATUS:
            logger.error("Nubra session expired (HTTP 440) placing order; re-authentication required")
            response_data["message"] = SESSION_EXPIRED_MESSAGE
        else:
            # V3 puts the human-readable reason in "error"
            # ({"error": "...", "nubra_error_code": ""}), but the service layer
            # reads "message". Without this copy every rejection -- wrong
            # strike, insufficient funds, unregistered static IP -- reaches the
            # user as the generic "Failed to place order" and the real cause
            # only exists in the log line above.
            _promote_error_to_message(response_data)
        response.status = response.status_code

    return response, response_data, orderid


def place_smartorder_api(data, auth):
    AUTH_TOKEN = auth

    # If no API call is made in this function then res will return None
    res = None

    # Extract necessary info from data
    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")
    # Per-symbol lock: serialize smart orders per symbol
    symbol_lock = _get_symbol_lock(symbol, exchange, product)

    with symbol_lock:
        position_size = int(data.get("position_size", "0"))

        # Get current open position for the symbol
        current_position = int(
            get_open_position(symbol, exchange, product, AUTH_TOKEN)
        )

        logger.debug(f"position_size : {position_size}")
        logger.debug(f"Open Position : {current_position}")

        # Determine action based on position_size and current_position
        action = None
        quantity = 0

        # If both position_size and current_position are 0, do nothing
        if position_size == 0 and current_position == 0 and int(data["quantity"]) != 0:
            action = data["action"]
            quantity = data["quantity"]
            res, response, orderid = place_order_api(data, AUTH_TOKEN)
            _invalidate_position_cache(AUTH_TOKEN)

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
            orderid = None
            return res, response, orderid  # res remains None as no API call was mad

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
            # Prepare data for placing the order
            order_data = data.copy()
            order_data["action"] = action
            order_data["quantity"] = str(quantity)

            # Place the order
            res, response, orderid = place_order_api(order_data, auth)
            _invalidate_position_cache(AUTH_TOKEN)
            logger.debug(f"{response}")
            logger.debug(f"{orderid}")

            return res, response, orderid


def close_all_positions(current_api_key, auth):
    """
    Close all open positions using Nubra's API.

    Reads the flat V3 positions list and places an opposing market order for
    every non-zero net quantity.
    """
    AUTH_TOKEN = auth

    positions_response = get_positions(AUTH_TOKEN)

    logger.debug(f"Nubra positions response: {positions_response}")

    if is_error_response(positions_response):
        logger.warning(f"Nubra positions error: {positions_response}")
        return {
            "status": "error",
            "message": positions_response.get("message") or "Failed to fetch positions",
        }, 500

    positions = extract_positions(positions_response)

    # Check if positions is empty
    if not positions:
        return {"message": "No Open Positions Found"}, 200

    # Loop through each position to close (throttled to 10 ops/sec per Nubra rate limit)
    positions_closed = 0
    failed_to_close = []
    for position in positions:
        net_qty = position_net_qty(position)

        # Skip if quantity is zero
        if net_qty == 0:
            continue

        # To close, trade the opposite side of the net position
        action = "SELL" if net_qty > 0 else "BUY"
        quantity = abs(net_qty)

        # place_order_api() resolves the ref_id with get_token(symbol, exchange),
        # so both must already be in OpenAlgo terms -- passing Nubra's own
        # symbol and "NSE" for an F&O position makes that lookup fail and the
        # square-off order is rejected before it is ever sent.
        symbol, exchange = resolve_position(position)
        if not symbol or not exchange:
            logger.error(
                f"Nubra square-off skipped: cannot resolve position "
                f"refId={position.get('refId')!r} to an OpenAlgo symbol"
            )
            failed_to_close.append(str(position.get("refId", "")))
            continue

        logger.debug(f"Closing position - Symbol: {symbol}, Exchange: {exchange}, Qty: {quantity}, Action: {action}")

        product = reverse_map_product_type(position.get("deliveryType", ""))

        # Prepare the order payload
        place_order_payload = {
            "apikey": current_api_key,
            "strategy": "Squareoff",
            "symbol": symbol,
            "action": action,
            "exchange": exchange,
            "pricetype": "MARKET",
            "product": product,
            "quantity": str(quantity),
        }

        logger.debug(f"Close position payload: {place_order_payload}")

        # Place the order to close the position
        res, response, orderid = place_order_api(place_order_payload, auth)

        if orderid:
            positions_closed += 1
        else:
            failed_to_close.append(f"{symbol} ({exchange})")
            logger.error(f"Nubra square-off failed for {symbol} ({exchange}): {response}")

        logger.debug(f"Close position response: {response}, orderid: {orderid}")

        # Rate limit: 10 ops/sec = 100ms gap between requests
        time.sleep(0.1)

    # Report what actually happened rather than asserting success. A run where
    # every row had a zero net quantity, or where every square-off order was
    # rejected, must not come back as "SquaredOff" -- that reads as flat while
    # the exposure is still live.
    if failed_to_close:
        message = (
            f"Squared off {positions_closed} position(s); "
            f"failed to close: {', '.join(failed_to_close)}"
        )
        logger.error(f"Nubra square-off incomplete. {message}")
        return {"status": "error", "message": message}, 500

    if not positions_closed:
        logger.warning(
            f"Nubra square-off placed no orders: all {len(positions)} position(s) "
            f"reported a zero net quantity"
        )
        return {"message": "No Open Positions Found"}, 200

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """
    Cancel an order using Nubra's Trading API V3.

    Nubra API: POST /sentinel/orders/cancel
    Body is ``{"orders": [{"orderId": <intentOrderId>}]}``. Omitting
    ``exitTriggerKind`` cancels the full order (as opposed to one attached exit
    trigger).
    """
    AUTH_TOKEN = auth

    client = get_httpx_client()

    try:
        payload = json.dumps({"orders": [{"orderId": int(orderid)}]})
    except (TypeError, ValueError):
        logger.error(f"Nubra cancel: non-numeric order id {orderid!r}")
        return {"status": "error", "message": f"Invalid order id: {orderid}"}, 400

    # Make the request with 429 retry
    response = None
    for attempt in range(_MAX_RETRIES):
        response = client.post(
            f"{get_base_url()}/sentinel/orders/cancel",
            headers=get_nubra_headers(AUTH_TOKEN),
            content=payload,
        )
        if response.status_code == 429:
            delay = _RATE_LIMIT_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"Rate limit hit (429) cancelling order {orderid}, retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{_MAX_RETRIES})"
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(delay)
                continue
            else:
                logger.error(f"Rate limit exceeded cancelling order {orderid} after retries")
                return {"status": "error", "message": "Rate limit exceeded"}, 429
        break

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    if response.status_code == SESSION_EXPIRED_STATUS:
        logger.error(f"Nubra session expired (HTTP 440) cancelling order {orderid}")
        return {"status": "error", "message": SESSION_EXPIRED_MESSAGE}, response.status_code

    # Handle empty response
    if not response.text:
        if response.status_code in (200, 201, 204):
            return {"status": "success", "orderid": orderid}, 200
        return {"status": "error", "message": "Empty response from API"}, response.status_code

    try:
        data = json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse cancel order response: {response.text}")
        return {"status": "error", "message": "Failed to parse response"}, response.status_code

    logger.debug(f"Nubra cancel order response (status={response.status_code}): {data}")

    if response.status_code in (200, 201, 204):
        return {"status": "success", "orderid": orderid}, 200

    return {
        "status": "error",
        "message": data.get("message", data.get("error", "Failed to cancel order")),
    }, response.status_code


def modify_order(data, auth):
    """
    Modify an order using Nubra's Trading API V3.

    Nubra API: POST /sentinel/orders/modify
    Body is ``{"orders": [{"orderId": <intentOrderId>, ...changed fields}]}``.
    The order id travels in the body, not the URL.
    """
    AUTH_TOKEN = auth

    client = get_httpx_client()

    orderid = data.get("orderid", "")
    try:
        transformed_data = transform_modify_order_data(data, orderid)
    except (TypeError, ValueError):
        logger.error(f"Nubra modify: non-numeric order id {orderid!r}")
        return {"status": "error", "message": f"Invalid order id: {orderid}"}, 400

    payload = json.dumps({"orders": [transformed_data]})

    logger.debug(f"Nubra modify order payload: {payload}")

    # Make the POST request with 429 retry
    response = None
    for attempt in range(_MAX_RETRIES):
        response = client.post(
            f"{get_base_url()}/sentinel/orders/modify",
            headers=get_nubra_headers(AUTH_TOKEN),
            content=payload,
        )
        if response.status_code == 429:
            delay = _RATE_LIMIT_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"Rate limit hit (429) modifying order {orderid}, retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{_MAX_RETRIES})"
            )
            if attempt < _MAX_RETRIES - 1:
                time.sleep(delay)
                continue
            else:
                logger.error(f"Rate limit exceeded modifying order {orderid} after retries")
                return {"status": "error", "message": "Rate limit exceeded"}, 429
        break

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    if response.status_code == SESSION_EXPIRED_STATUS:
        logger.error(f"Nubra session expired (HTTP 440) modifying order {orderid}")
        return {"status": "error", "message": SESSION_EXPIRED_MESSAGE}, response.status_code

    # Handle empty response
    if not response.text:
        if response.status_code in (200, 201, 204):
            return {"status": "success", "orderid": orderid}, 200
        return {"status": "error", "message": "Empty response from API"}, response.status_code

    try:
        response_data = json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse modify order response: {response.text}")
        return {"status": "error", "message": "Failed to parse response"}, response.status_code

    logger.debug(f"Nubra modify order response (status={response.status_code}): {response_data}")

    if response.status_code in (200, 201):
        orders = response_data.get("orders")
        if isinstance(orders, list) and orders and isinstance(orders[0], dict):
            returned_id = orders[0].get("intentOrderId")
            if returned_id:
                return {"status": "success", "orderid": str(returned_id)}, 200
        return {"status": "success", "orderid": orderid}, 200

    return {
        "status": "error",
        "message": response_data.get("message", response_data.get("error", "Failed to modify order")),
    }, response.status_code


def cancel_all_orders_api(data, auth):
    """
    Cancel all working orders.

    Working orders are exactly the ``open`` and ``gtt`` buckets of the V3
    order response -- no status filtering is needed beyond bucket selection.
    """
    AUTH_TOKEN = auth

    order_book_response = get_order_book(AUTH_TOKEN)

    if is_error_response(order_book_response):
        # Raise rather than return ([], []). cancel_all_order_service turns any
        # returned tuple into HTTP 200 "Canceled 0 orders", so an unreadable
        # order book would tell the caller cancellation succeeded while their
        # working orders are still live. Its except branch turns this into a
        # 500 and logs the reason.
        # is_error_response() also matches on status alone, so neither key is
        # guaranteed to be present -- without the final fallback the raised
        # exception reads "... order book: None".
        message = (
            order_book_response.get("message")
            or order_book_response.get("error")
            or "Unknown error"
        )
        logger.error(f"Nubra order book unavailable, cannot cancel orders: {message}")
        raise Exception(f"Failed to fetch Nubra order book: {message}")

    orders_to_cancel = flatten_order_buckets(order_book_response, buckets=_WORKING_BUCKETS)

    if not orders_to_cancel:
        return [], []

    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders (throttled to 10 ops/sec per Nubra rate limit)
    for i, order in enumerate(orders_to_cancel):
        orderid = str(order.get("intentOrderId", ""))
        if orderid:
            cancel_response, status_code = cancel_order(orderid, auth)
            if status_code == 200:
                canceled_orders.append(orderid)
            else:
                failed_cancellations.append(orderid)
            # Rate limit: 10 ops/sec = 100ms gap between requests
            if i < len(orders_to_cancel) - 1:
                time.sleep(0.1)

    return canceled_orders, failed_cancellations
