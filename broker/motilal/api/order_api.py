import json
import os
import threading
import time

import httpx

from broker.motilal.api.baseurl import get_base_url, get_common_headers, get_url
from broker.motilal.mapping.transform_data import (
    map_exchange,
    map_product_type,
    reverse_map_exchange,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_symbol, get_symbol_info, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Exchanges where a lot size other than 1 is the norm. A missing/invalid lot
# size for these must fail closed: silently assuming 1 turns a 75-share NIFTY
# option order into quantityinlot=75 (= 5625 shares) which Motilal will accept.
DERIVATIVE_EXCHANGES = {"NFO", "CDS", "MCX", "BFO", "NSEFO", "NSECD", "BSEFO"}


class ErrorResponse:
    """Minimal stand-in for an ``httpx.Response``.

    ``place_order_api`` must never return ``None`` as its first element:
    services/place_order_service.py reads ``res.status`` *outside* its
    try/except, so a ``None`` there raises AttributeError instead of surfacing
    the real validation message. This exposes the same attributes the callers
    touch (``.status``, ``.status_code``, ``.text``) with a 4xx status.
    """

    def __init__(self, status_code=400, text=""):
        self.status_code = status_code
        self.status = status_code
        self.text = text

    def json(self):
        try:
            return json.loads(self.text) if self.text else {}
        except json.JSONDecodeError:
            return {}

    def __repr__(self):
        return f"<ErrorResponse status={self.status_code}>"


def _error_result(message, errorcode, status_code=400):
    """Build the 3-tuple ``place_order_api`` returns on a validation failure."""
    body = {"status": "error", "message": message, "errorcode": errorcode}
    return ErrorResponse(status_code, json.dumps(body)), body, None


def _resolve_lotsize(symbol, exchange):
    """Return ``(lotsize, error_message)``.

    Cash equity legitimately has a lot size of 1, so a lookup miss there falls
    back to 1. For derivative exchanges a missing or invalid lot size is a hard
    error - guessing 1 silently multiplies the order size by the real lot.
    """
    symbol_info = get_symbol_info(symbol, exchange)
    raw_lotsize = getattr(symbol_info, "lotsize", None) if symbol_info else None

    try:
        lotsize = int(raw_lotsize) if raw_lotsize is not None else 0
    except (TypeError, ValueError):
        lotsize = 0

    if lotsize > 0:
        logger.debug(f"Lot size for {symbol}: {lotsize}")
        return lotsize, None

    if str(exchange).upper() in DERIVATIVE_EXCHANGES:
        return None, (
            f"Lot size not found for {symbol} on {exchange}. Refusing to place the order: "
            f"assuming a lot size of 1 for a derivative would multiply the order size by the "
            f"real lot size. Refresh the symbol master and retry."
        )

    # Cash segment: lot size 1 is correct.
    logger.debug(f"Lot size for {symbol} not found; using 1 (cash segment {exchange})")
    return 1, None


def _surface_broker_error(parsed, context):
    """Normalise a documented FAILURE envelope into OpenAlgo's error shape.

    Doc 04 defines ``status`` as SUCCESS/FAILURE, but the service layer tests
    for ``status == "error"`` - so a FAILURE (expired token, MO2012, ...) used
    to surface as "no orders"/"no positions". Message/errorcode/data from the
    broker are preserved.
    """
    if not isinstance(parsed, dict):
        return parsed

    status = str(parsed.get("status", "")).upper()
    if not status or status == "SUCCESS":
        return parsed

    errorcode = parsed.get("errorcode", "")
    message = parsed.get("message") or "Motilal API returned FAILURE"
    logger.error(f"Motilal {context} failed: status={parsed.get('status')}, "
                 f"message={message}, errorcode={errorcode}")

    result = dict(parsed)
    result["status"] = "error"
    result["message"] = f"{message} (errorcode: {errorcode})" if errorcode else message
    return result


def get_api_response(endpoint, auth, method="GET", payload=""):
    """Call a Motilal REST endpoint.

    ``endpoint`` is a baseurl.ENDPOINTS key (preferred). A raw path starting
    with "/" is still accepted for compatibility.
    """
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Documented common headers (05-header-parameters.md). Handles Authorization,
    # the optional accesstoken/apisecretkey and the mandatory vendorinfo.
    headers = get_common_headers(auth)

    url = f"{get_base_url()}{endpoint}" if str(endpoint).startswith("/") else get_url(endpoint)

    if method == "GET":
        response = client.get(url, headers=headers)
    elif method == "POST":
        response = client.post(url, headers=headers, content=payload)
    else:
        response = client.request(method, url, headers=headers, content=payload)

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    # Handle empty response
    if not response.text:
        logger.error(f"Empty response from {endpoint} (HTTP {response.status_code})")
        return {
            "status": "error",
            "message": f"Empty response from Motilal (HTTP {response.status_code})",
            "errorcode": "",
        }

    try:
        parsed = json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from {endpoint}: {response.text}")
        return {
            "status": "error",
            "message": f"Invalid JSON response from Motilal (HTTP {response.status_code})",
            "errorcode": "",
        }

    return _surface_broker_error(parsed, endpoint)


def get_order_book(auth):
    return get_api_response("getorderbook", auth, method="POST")


def get_trade_book(auth):
    response = get_api_response("gettradebook", auth, method="POST")

    # Raw-response diagnostics: the price scale of this book is decided by the
    # per-row `precision` field (doc 18), which live responses have been seen to
    # omit or report as 0. Log the untouched first row so the real shape is
    # visible instead of inferred.
    try:
        rows = response.get("data") if isinstance(response, dict) else None
        logger.info(
            "Motilal Trade Book raw response: status=%s, message=%s, errorcode=%s, rows=%s",
            response.get("status") if isinstance(response, dict) else type(response).__name__,
            response.get("message") if isinstance(response, dict) else "",
            response.get("errorcode") if isinstance(response, dict) else "",
            len(rows) if isinstance(rows, list) else 0,
        )
        if isinstance(rows, list) and rows:
            first = rows[0]
            logger.info("Motilal Trade Book raw row[0]: %s", json.dumps(first, default=str))
            if isinstance(first, dict):
                logger.info(
                    "Motilal Trade Book price fields: precision=%r (%s), tradeprice=%r (%s), "
                    "tradevalue=%r, tradeqty=%r",
                    first.get("precision"),
                    type(first.get("precision")).__name__,
                    first.get("tradeprice"),
                    type(first.get("tradeprice")).__name__,
                    first.get("tradevalue"),
                    first.get("tradeqty"),
                )
    except Exception as exc:  # diagnostics must never break the trade book
        logger.debug("Trade book diagnostics failed: %s", exc)

    return response


def get_positions(auth):
    return get_api_response("getposition", auth, method="POST")


def get_order_detail(orderid, auth):
    """Fetch a single order by uniqueorderid (doc 19-order-detail.md).

    NOTE: this endpoint reports some fields with a different shape than the
    order book does (``"ordertype": "C"`` + ``"booktype": "Market"`` vs the
    order book's ``"ordertype": "Market"``), so its rows must NOT be fed into
    the orderbook mapping. Read only the specific fields you need.
    """
    payload = json.dumps({"uniqueorderid": orderid})
    return get_api_response("getorderdetail", auth, method="POST", payload=payload)


def get_holdings(auth):
    """
    Fetch holdings/DP holdings from Motilal Oswal.
    Motilal API endpoint: /rest/report/v3/getdpholding (POST)
    Request body: {} (empty JSON for non-dealer accounts)
    """
    # Motilal requires POST with JSON body (empty for non-dealer accounts)
    payload = json.dumps({})

    logger.debug("Fetching holdings from Motilal API...")
    response = get_api_response("getdpholding", auth, method="POST", payload=payload)

    # Log the raw response for debugging
    logger.debug(
        f"Motilal Holdings API raw response: status={response.get('status')}, message={response.get('message')}, data_length={len(response.get('data', [])) if response.get('data') else 0}"
    )

    if response.get("status") == "SUCCESS" and response.get("data"):
        logger.debug(f"Successfully fetched {len(response.get('data', []))} holdings from Motilal")
    elif response.get("status") == "SUCCESS" and not response.get("data"):
        logger.warning(
            "Motilal API returned SUCCESS but data is null/empty. This might indicate no holdings or an API issue."
        )
    else:
        logger.error(
            f"Motilal Holdings API error: {response.get('message', 'Unknown error')}, errorcode: {response.get('errorcode', '')}"
        )

    return response


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
    # Match on symboltoken, not on the name. Motilal's brsymbol is the raw
    # scripname ("INFY EQ", "BANKNIFTY 03-Feb-2022 PE 32300") while the position
    # book (doc 22) returns "symbol": "INFY" with "series": "EQ" separate - the
    # name comparison could never match, so net_qty was always "0".
    token = get_token(tradingsymbol, exchange)
    if not token:
        logger.error(
            f"Failed to get token for symbol: {tradingsymbol}, exchange: {exchange}; "
            f"treating position as flat"
        )
        return "0"

    # Map exchange from OpenAlgo format to Motilal format for comparison
    motilal_exchange = map_exchange(exchange)
    positions_data = _get_cached_positions(auth)

    logger.debug(f"{positions_data}")

    net_qty = "0"

    # Motilal returns status as "SUCCESS" string, not boolean
    if positions_data and positions_data.get("status") == "SUCCESS" and positions_data.get("data"):
        for position in positions_data["data"]:
            # doc 22 returns symboltoken as an unquoted number while the token DB
            # stores strings - coerce both sides.
            # Motilal uses 'productname' not 'producttype'; since Motilal uses
            # DELIVERY for both CNC and MIS in the cash segment, positions are
            # matched on Motilal's product type (already mapped by the caller).
            if (
                str(position.get("symboltoken")) == str(token)
                and position.get("exchange") == motilal_exchange
                and position.get("productname") == producttype
            ):
                # Calculate net quantity from buy and sell quantities
                buyqty = int(position.get("buyquantity", 0))
                sellqty = int(position.get("sellquantity", 0))
                net_qty = str(buyqty - sellqty)
                break  # Assuming you need the first match

    return net_qty


def place_order_api(data, auth):
    AUTH_TOKEN = auth
    # Standard OpenAlgo credential convention (kept identical across brokers):
    #   BROKER_API_KEY    = App API Key -> "Api Key of App" (doc 05) and the
    #                       SHA-256(password + APIKey) login hash (doc 08)
    #   BROKER_API_SECRET = App API Secret -> apisecretkey (doc 09)
    # The Motilal client code is NOT an env var: it is the login ID entered on
    # the TOTP page, persisted at login and read via baseurl.get_client_code().
    # Keep this consistent with baseurl.get_common_headers(), auth_api.py and
    # data.py. `apikey` is not in doc 14's documented body but is carried
    # through transform_data(), so the value still has to be right.
    data["apikey"] = os.getenv("BROKER_API_KEY")
    token = get_token(data["symbol"], data["exchange"])

    logger.debug(
        f"Placing order for symbol: {data['symbol']}, exchange: {data['exchange']}, token: {token}"
    )

    if not token:
        logger.error(
            f"Failed to get token for symbol: {data['symbol']}, exchange: {data['exchange']}"
        )
        return _error_result("Invalid symbol or token not found", "TOKEN_NOT_FOUND")

    # Get lot size for the shares -> lots conversion. Fails closed on derivatives.
    lotsize, lotsize_error = _resolve_lotsize(data["symbol"], data["exchange"])
    if lotsize_error:
        logger.error(lotsize_error)
        return _error_result(lotsize_error, "LOTSIZE_NOT_FOUND")

    newdata = transform_data(data, token, auth_token=AUTH_TOKEN)

    # Motilal Oswal common header parameters (doc 05)
    headers = get_common_headers(AUTH_TOKEN)

    # Motilal Oswal Place Order Payload
    # Build payload with only non-empty optional fields
    # Convert quantity to lots (Motilal requires quantity in lots, not shares)
    actual_quantity = int(newdata["quantity"])

    # Validate that quantity is a multiple of lot size
    if actual_quantity % lotsize != 0:
        error_msg = (
            f"Invalid quantity: {actual_quantity} shares is not a multiple of lot size {lotsize}. "
            f"Valid quantities: {lotsize}, {lotsize * 2}, {lotsize * 3}, etc."
        )
        logger.error(error_msg)
        return _error_result(error_msg, "INVALID_QUANTITY")

    quantity_in_lots = actual_quantity // lotsize  # Integer division to get number of lots
    logger.debug(
        f"Quantity conversion: {actual_quantity} shares / {lotsize} lot size = {quantity_in_lots} lots"
    )

    payload_dict = {
        "exchange": newdata["exchange"],
        "symboltoken": int(newdata["symboltoken"]),  # Must be integer
        "buyorsell": newdata["buyorsell"],
        "ordertype": newdata.get("ordertype", "MARKET"),
        "producttype": newdata.get("producttype", "NORMAL"),
        "orderduration": newdata.get("orderduration", "DAY"),
        "price": float(newdata.get("price", "0")),
        "triggerprice": float(newdata.get("triggerprice", "0")),
        "quantityinlot": quantity_in_lots,  # Converted to lots
        "disclosedquantity": int(newdata.get("disclosedquantity", "0")),
        "amoorder": newdata.get("amoorder", "N"),
    }

    # Add optional fields only if they have values
    if newdata.get("algoid"):
        payload_dict["algoid"] = newdata["algoid"]
    if newdata.get("goodtilldate"):
        payload_dict["goodtilldate"] = newdata["goodtilldate"]
    if newdata.get("tag"):
        payload_dict["tag"] = newdata["tag"]
    if newdata.get("participantcode"):
        payload_dict["participantcode"] = newdata["participantcode"]

    payload = json.dumps(payload_dict)

    logger.debug(f"Motilal Place Order Request Payload: {payload_dict}")
    logger.debug(f"Payload JSON: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Make the request using the shared client (doc 14: /rest/trans/v2/placeorder)
    response = client.post(get_url("placeorder"), headers=headers, content=payload)

    # Add status attribute to make response compatible with http.client response
    # as the rest of the codebase expects .status instead of .status_code
    response.status = response.status_code

    # Parse the JSON response
    try:
        response_data = response.json()
    except (json.JSONDecodeError, ValueError):
        logger.error(
            f"Invalid JSON in place order response (HTTP {response.status_code}): {response.text}"
        )
        return (
            response,
            {
                "status": "error",
                "message": f"Invalid response from Motilal (HTTP {response.status_code})",
                "errorcode": "",
            },
            None,
        )

    # Log the full response for debugging
    logger.debug(f"Motilal Place Order Response: {response_data}")
    logger.debug(f"Response Status Code: {response.status_code}")

    # Motilal returns status as "SUCCESS" string, not boolean
    if response_data.get("status") == "SUCCESS":
        # doc 14: uniqueorderid is at the TOP LEVEL of the place order response
        orderid = response_data.get("uniqueorderid")
        logger.debug(f"Order placed successfully. Order ID: {orderid}")
    else:
        orderid = None
        logger.error(
            f"Order placement failed. Status: {response_data.get('status')}, Message: {response_data.get('message')}, Error Code: {response_data.get('errorcode')}"
        )

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

        # Get current open position for the symbol.
        # The exchange MUST be passed: placement uses the exchange-aware map,
        # where MIS -> NORMAL for NFO/MCX/CDS/BFO but MIS -> VALUEPLUS otherwise.
        # Without it F&O MIS positions never matched.
        current_position = int(
            get_open_position(symbol, exchange, map_product_type(product, exchange), AUTH_TOKEN)
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
            # logger.debug(f"action : {action}")
            # logger.debug(f"Quantity : {quantity}")
            res, response, orderid = place_order_api(data, AUTH_TOKEN)
            _invalidate_position_cache(AUTH_TOKEN)
            # logger.debug(f"{res}")
            # logger.debug(f"{response}")

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
                # logger.debug(f"smart buy quantity : {quantity}")
            elif position_size < current_position:
                action = "SELL"
                quantity = current_position - position_size
                # logger.debug(f"smart sell quantity : {quantity}")

        if action:
            # Prepare data for placing the order
            order_data = data.copy()
            order_data["action"] = action
            order_data["quantity"] = str(quantity)

            # logger.debug(f"{order_data}")
            # Place the order
            res, response, orderid = place_order_api(order_data, auth)
            _invalidate_position_cache(AUTH_TOKEN)
            # logger.debug(f"{res}")
            logger.debug(f"{response}")
            logger.debug(f"{orderid}")

            return res, response, orderid


def close_all_positions(current_api_key, auth):
    # Fetch the current open positions
    AUTH_TOKEN = auth

    positions_response = get_positions(AUTH_TOKEN)

    # Surface a broker-side failure (expired token, MO2012, ...) instead of
    # reporting it as "no positions".
    if positions_response.get("status") == "error":
        return {
            "status": "error",
            "message": positions_response.get("message", "Failed to fetch positions"),
        }, 500

    # Check if the positions data is null or empty - Motilal uses 'SUCCESS' string
    if (
        positions_response.get("status") != "SUCCESS"
        or positions_response.get("data") is None
        or not positions_response["data"]
    ):
        return {"message": "No Open Positions Found"}, 200

    if positions_response.get("status") == "SUCCESS":
        # Loop through each position to close
        for position in positions_response["data"]:
            # Calculate net quantity from buy and sell quantities
            buyqty = int(position.get("buyquantity", 0))
            sellqty = int(position.get("sellquantity", 0))
            net_qty = buyqty - sellqty

            # Skip if net quantity is zero
            if net_qty == 0:
                continue

            # Determine action based on net quantity
            action = "SELL" if net_qty > 0 else "BUY"
            quantity = abs(net_qty)

            # Convert Motilal exchange to OpenAlgo exchange for symbol lookup
            motilal_exchange = position["exchange"]
            openalgo_exchange = reverse_map_exchange(motilal_exchange)

            # Get openalgo symbol to send to placeorder function.
            # doc 22 returns symboltoken as a number; the token DB stores strings.
            symbol = get_symbol(str(position["symboltoken"]), openalgo_exchange)
            logger.debug(f"The Symbol is {symbol}")

            if not symbol:
                logger.error(
                    f"Symbol not found for token {position['symboltoken']} and exchange {openalgo_exchange}"
                )
                continue

            # Prepare the order payload - Motilal uses 'productname' instead of 'producttype'
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": openalgo_exchange,  # Use OpenAlgo exchange format
                "pricetype": "MARKET",
                # Exchange-aware reverse map: NORMAL means MIS on F&O, and
                # DELIVERY/VALUEPLUS mean CNC/MIS on cash.
                "product": reverse_map_product_type(position["productname"], openalgo_exchange),
                "quantity": str(quantity),
            }

            logger.debug(f"{place_order_payload}")

            # Place the order to close the position
            res, response, orderid = place_order_api(place_order_payload, auth)

            # logger.debug(f"{res}")
            # logger.debug(f"{response}")
            # logger.debug(f"{orderid}")

            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Motilal Oswal common header parameters (doc 05)
    headers = get_common_headers(AUTH_TOKEN)

    # Prepare the payload - Motilal uses uniqueorderid (doc 16)
    payload = json.dumps({"uniqueorderid": orderid})

    # Make the request using the shared client (doc 16: /rest/trans/v2/cancelorder)
    response = client.post(get_url("cancelorder"), headers=headers, content=payload)

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    try:
        data = json.loads(response.text) if response.text else {}
    except json.JSONDecodeError:
        logger.error(
            f"Invalid JSON in cancel order response (HTTP {response.status_code}): {response.text}"
        )
        data = {}

    # Motilal returns status as "SUCCESS" string
    if data.get("status") == "SUCCESS":
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200

    # Return an error response, including the documented errorcode (doc 31)
    message = data.get("message", "Failed to cancel order")
    errorcode = data.get("errorcode", "")
    return {
        "status": "error",
        "message": f"{message} (errorcode: {errorcode})" if errorcode else message,
    }, response.status


def _resolve_lastmodifiedtime(order_details):
    """Pick a usable ``lastmodifiedtime`` for the modify request.

    Doc 15 marks lastmodifiedtime mandatory in "dd-MMM-yyyy HH:mm:ss" format,
    but the order book returns "0" for a never-modified order while the same
    record carries a correctly formatted ``recordinserttime``. Sending "0"
    triggers MO1089 (Invalid Input ModifyOrder LastModifiedTimeStr).
    """
    def _clean(value):
        return str(value).strip() if value is not None else ""

    lastmodifiedtime = _clean(order_details.get("lastmodifiedtime"))
    if lastmodifiedtime and lastmodifiedtime != "0":
        return lastmodifiedtime

    for fallback_field in ("recordinserttime", "entrydatetime"):
        fallback = _clean(order_details.get(fallback_field))
        if fallback and fallback != "0":
            logger.warning(
                f"lastmodifiedtime is {lastmodifiedtime!r}; falling back to "
                f"{fallback_field}={fallback!r} for the modify request"
            )
            return fallback

    logger.warning(
        "No usable lastmodifiedtime/recordinserttime/entrydatetime found for the order; "
        "the modify request may be rejected with MO1089"
    )
    return lastmodifiedtime


def _fetch_order_details(orderid, auth):
    """Fetch the fields modify needs for one order.

    Prefers the by-id endpoint (doc 19), falling back to an order book scan
    (doc 17) if it errors. Only lastmodifiedtime / qtytradedtoday / the time
    fallbacks are read - doc 19 reports other fields in a different shape
    (``"ordertype": "C"`` + ``"booktype"``) and must not reach the mapping.
    """
    try:
        detail_response = get_order_detail(orderid, auth)
    except Exception as exc:  # network / client error - fall back to the book
        logger.warning(f"getorderdetailbyuniqueorderid failed ({exc}); falling back to order book")
        detail_response = None

    if detail_response and detail_response.get("status") == "SUCCESS":
        rows = detail_response.get("data") or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not row.get("uniqueorderid") or str(row.get("uniqueorderid")) == str(orderid):
                return row, None
        logger.warning(f"Order {orderid} not present in getorderdetail data; falling back to book")
    elif detail_response is not None:
        logger.warning(
            f"getorderdetailbyuniqueorderid returned "
            f"{detail_response.get('message', 'an error')}; falling back to order book"
        )

    # Fallback: scan the order book
    order_book_response = get_order_book(auth)
    if order_book_response.get("status") != "SUCCESS" or not order_book_response.get("data"):
        message = order_book_response.get("message") or "Failed to fetch order book"
        logger.error(f"Failed to fetch order book: {message}")
        return None, message

    for order in order_book_response.get("data", []):
        if order.get("uniqueorderid") == orderid:
            return order, None

    return None, f"Order {orderid} not found in order book"


def modify_order(data, auth):
    """
    Modifies an existing order for Motilal Oswal.

    Motilal API requires lastmodifiedtime and qtytradedtoday fields which must be
    fetched from the order detail endpoint (or the order book) before modifying.

    Args:
        data: Order modification data containing orderid, symbol, exchange, quantity, price, etc.
        auth: Authentication token

    Returns:
        Tuple of (response_dict, status_code)
    """
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # First, fetch the order details to get lastmodifiedtime and qtytradedtoday
    orderid = data.get("orderid")
    logger.debug(f"Fetching order details for orderid: {orderid}")

    order_details, fetch_error = _fetch_order_details(orderid, AUTH_TOKEN)

    if not order_details:
        logger.error(fetch_error)
        status_code = 404 if "not found" in str(fetch_error).lower() else 500
        return {"status": "error", "message": fetch_error}, status_code

    # Extract required fields
    lastmodifiedtime = _resolve_lastmodifiedtime(order_details)
    try:
        qtytradedtoday = int(order_details.get("qtytradedtoday", 0) or 0)
    except (TypeError, ValueError):
        qtytradedtoday = 0

    logger.debug(
        f"Order details: lastmodifiedtime={lastmodifiedtime}, qtytradedtoday={qtytradedtoday}"
    )

    token = get_token(data["symbol"], data["exchange"])

    # Get lot size for the shares -> lots conversion. Fails closed on derivatives.
    lotsize, lotsize_error = _resolve_lotsize(data["symbol"], data["exchange"])
    if lotsize_error:
        logger.error(lotsize_error)
        return {
            "status": "error",
            "message": lotsize_error,
            "errorcode": "LOTSIZE_NOT_FOUND",
        }, 400

    # Convert quantity to lots for modify order
    if "quantity" in data:
        actual_quantity = int(data["quantity"])

        # Validate that quantity is a multiple of lot size
        if actual_quantity % lotsize != 0:
            error_msg = (
                f"Invalid quantity for modify order: {actual_quantity} shares is not a multiple of lot size {lotsize}. "
                f"Valid quantities: {lotsize}, {lotsize * 2}, {lotsize * 3}, etc."
            )
            logger.error(error_msg)
            return {"status": "error", "message": error_msg, "errorcode": "INVALID_QUANTITY"}, 400

        quantity_in_lots = actual_quantity // lotsize
        data["quantity"] = str(quantity_in_lots)  # Convert to lots
        logger.debug(
            f"Modify quantity conversion: {actual_quantity} shares / {lotsize} lot size = {quantity_in_lots} lots"
        )

    data["symbol"] = get_br_symbol(data["symbol"], data["exchange"])

    # Pass the order details to the transformation function
    transformed_data = transform_modify_order_data(data, token, lastmodifiedtime, qtytradedtoday)

    # Motilal Oswal common header parameters (doc 05)
    headers = get_common_headers(AUTH_TOKEN)
    payload = json.dumps(transformed_data)

    logger.debug(f"Motilal Modify Order Request Payload: {transformed_data}")
    logger.debug(f"Payload JSON: {payload}")

    # Make the request using the shared client (doc 15: /rest/trans/v5/modifyorder)
    response = client.post(get_url("modifyorder"), headers=headers, content=payload)

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    try:
        response_data = json.loads(response.text) if response.text else {}
    except json.JSONDecodeError:
        logger.error(
            f"Invalid JSON in modify order response (HTTP {response.status_code}): {response.text}"
        )
        response_data = {}

    # Log the response for debugging
    logger.debug(f"Motilal Modify Order Response: {response_data}")
    logger.debug(f"Response Status Code: {response.status_code}")

    # Motilal returns status as "SUCCESS" string
    if response_data.get("status") == "SUCCESS":
        # doc 15's success body is status/message/errorcode only - it never
        # returns a uniqueorderid. Keep the key for compatibility, sourced from
        # the request's orderid.
        return {"status": "success", "orderid": orderid}, 200

    message = response_data.get("message", "Failed to modify order")
    errorcode = response_data.get("errorcode", "")
    return {
        "status": "error",
        "message": f"{message} (errorcode: {errorcode})" if errorcode else message,
    }, response.status


def cancel_all_orders_api(data, auth):
    # Get the order book

    AUTH_TOKEN = auth

    order_book_response = get_order_book(AUTH_TOKEN)
    # logger.debug(f"{order_book_response}")
    # Motilal returns status as "SUCCESS" string
    if order_book_response.get("status") != "SUCCESS":
        logger.error(
            f"Failed to fetch order book for cancel-all: "
            f"{order_book_response.get('message', 'unknown error')}"
        )
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are still live and therefore cancellable.
    # Motilal statuses (doc 32): Unknown, Sent, Confirm, Cancel, Partial,
    # Traded, Rejected, Error. "Partial" is partially filled and still open.
    orders_to_cancel = [
        order
        for order in order_book_response.get("data", [])
        if order.get("orderstatus", "").lower() in ["confirm", "sent", "open", "partial"]
    ]
    # logger.debug(f"{orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        # Motilal uses uniqueorderid
        orderid = order["uniqueorderid"]
        cancel_response, status_code = cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
