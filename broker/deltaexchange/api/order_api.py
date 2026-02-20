import json
import os
import random
import time

from broker.deltaexchange.api.baseurl import get_auth_headers, get_url
from broker.deltaexchange.mapping.transform_data import (
    map_exchange_type,
    map_product_type,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_br_symbol, get_oa_symbol, get_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="GET", payload="", params=None):
    """
    Make a signed API request to Delta Exchange.

    Args:
        endpoint: API path, e.g. "/v2/orders"
        auth:     api_key (BROKER_API_KEY stored in OpenAlgo DB after login)
        method:   HTTP method (GET, POST, PUT, DELETE)
        payload:  JSON body string for POST/PUT/DELETE requests (pass "" for GET)
        params:   Dict of query parameters (GET only)

    Returns:
        Parsed JSON dict from Delta Exchange.
        On error returns {"success": False, "error": {"code": ..., "message": ...}}
    """
    api_secret = os.getenv("BROKER_API_SECRET", "")

    # Build query string manually so the signature and the URL are always in sync.
    # Delta Exchange signature formula: METHOD + timestamp + path + query_string + body
    # query_string must include the leading '?' when present.
    query_string = ""
    if params:
        query_string = "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))

    body = payload if payload else ""

    headers = get_auth_headers(
        method=method.upper(),
        path=endpoint,
        query_string=query_string,
        payload=body,
        api_key=auth,
        api_secret=api_secret,
    )

    # Build full URL (include query string inline so the signed string matches exactly)
    url = get_url(endpoint)
    full_url = url + query_string if query_string else url

    client = get_httpx_client()
    logger.debug(f"[DeltaExchange] {method.upper()} {full_url}")

    # Retry up to 3 times on HTTP 429 (rate limit) with exponential backoff + jitter.
    # The Retry-After header is honoured when present.  On each retry the HMAC
    # signature is rebuilt with a fresh timestamp.
    _MAX_RETRIES = 3
    _RETRY_BASE  = 1.0  # seconds; doubles each attempt
    response = None

    for _attempt in range(_MAX_RETRIES + 1):
        try:
            m = method.upper()
            if m == "GET":
                response = client.get(full_url, headers=headers)
            elif m == "POST":
                response = client.post(url, headers=headers, content=body)
            elif m == "PUT":
                response = client.put(url, headers=headers, content=body)
            elif m == "DELETE":
                response = client.request("DELETE", url, headers=headers, content=body)
            else:
                response = client.request(m, url, headers=headers, content=body)
        except Exception as e:
            logger.error(f"[DeltaExchange] Request error: {e}")
            return {"success": False, "error": {"code": "request_error", "message": str(e)}}

        if response.status_code == 429 and _attempt < _MAX_RETRIES:
            retry_after = response.headers.get("Retry-After")
            wait = (
                float(retry_after) if retry_after
                else (_RETRY_BASE * (2 ** _attempt)) + random.uniform(0.0, 0.5)
            )
            logger.warning(
                f"[DeltaExchange] HTTP 429 rate-limit on {endpoint} "
                f"(attempt {_attempt + 1}/{_MAX_RETRIES}). Retrying in {wait:.1f}s ..."
            )
            time.sleep(wait)
            # Re-sign with a fresh timestamp before the next attempt
            headers = get_auth_headers(
                method=method.upper(),
                path=endpoint,
                query_string=query_string,
                payload=body,
                api_key=auth,
                api_secret=api_secret,
            )
            continue
        break  # success, non-429, or retries exhausted

    if response is None:
        return {"success": False, "error": {"code": "no_response"}}

    logger.debug(f"[DeltaExchange] HTTP {response.status_code} from {endpoint}")

    if not response.text.strip():
        logger.error(f"[DeltaExchange] Empty response from {endpoint}")
        return {"success": False, "error": {"code": "empty_response"}}

    try:
        data = response.json()
    except Exception as e:
        logger.error(f"[DeltaExchange] JSON parse error: {e} — body: {response.text[:300]}")
        return {"success": False, "error": {"code": "json_parse_error", "message": str(e)}}

    if response.status_code not in (200, 201):
        logger.error(
            f"[DeltaExchange] HTTP {response.status_code}: {response.text[:300]}"
        )

    return data


# ---------------------------------------------------------------------------
# Order book / trade book
# ---------------------------------------------------------------------------

def get_order_book(auth):
    """Fetch all open orders (state=open)."""
    try:
        result = get_api_response("/v2/orders", auth, method="GET", params={"state": "open"})
        if result.get("success"):
            return result.get("result", [])
        logger.warning(f"[DeltaExchange] get_order_book unexpected response: {result}")
        return []
    except Exception as e:
        logger.error(f"[DeltaExchange] Exception in get_order_book: {e}")
        return []


def get_trade_book(auth):
    """Fetch closed / filled orders from order history."""
    try:
        result = get_api_response("/v2/orders/history", auth, method="GET")
        if result.get("success"):
            return result.get("result", [])
        logger.warning(f"[DeltaExchange] get_trade_book unexpected response: {result}")
        return []
    except Exception as e:
        logger.error(f"[DeltaExchange] Exception in get_trade_book: {e}")
        return []


# ---------------------------------------------------------------------------
# Positions / holdings
# ---------------------------------------------------------------------------

def get_positions(auth):
    """Fetch all open margined positions."""
    try:
        result = get_api_response("/v2/positions/margined", auth, method="GET")
        if result.get("success"):
            return result.get("result", [])
        logger.warning(f"[DeltaExchange] get_positions unexpected response: {result}")
        return []
    except Exception as e:
        logger.error(f"[DeltaExchange] Exception in get_positions: {e}")
        return []


def get_holdings(auth):
    """Delta Exchange is a derivatives-only exchange; equity holdings are not applicable."""
    return []


def get_open_position(tradingsymbol, exchange, product, auth):
    """
    Return the net position size (as string) for a given symbol.
    Positive = long, negative = short, "0" = flat.
    """
    br_symbol = get_br_symbol(tradingsymbol, exchange) or tradingsymbol
    positions = get_positions(auth)

    if not isinstance(positions, list):
        logger.error(f"[DeltaExchange] Unexpected positions format for {tradingsymbol}")
        return "0"

    for pos in positions:
        if isinstance(pos, dict) and pos.get("product_symbol") == br_symbol:
            return str(pos.get("size", 0))

    return "0"


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------

def _set_leverage(product_id: int, leverage: str, auth: str) -> None:
    """
    Set leverage for a product before placing an order.

    Delta Exchange requires a separate API call to configure leverage:
        POST /v2/products/{product_id}/orders/leverage
    This must be called *before* POST /v2/orders when the caller wants
    non-default leverage.  The leverage value is a string (e.g. "10").

    When the environment variable DELTA_ABORT_ON_LEVERAGE_FAILURE=true the
    function raises RuntimeError on API failure so that the calling order is
    never submitted with an unexpected leverage level.  When the flag is false
    (the default) a warning is logged and the order proceeds at the broker's
    current leverage for that product.
    """
    abort = os.getenv("DELTA_ABORT_ON_LEVERAGE_FAILURE", "false").strip().lower() == "true"

    endpoint = f"/v2/products/{product_id}/orders/leverage"
    payload = json.dumps({"leverage": leverage})
    result = get_api_response(endpoint, auth, method="POST", payload=payload)
    if result.get("success"):
        logger.info(
            f"[DeltaExchange] Leverage set to {leverage}x for product_id={product_id}"
        )
    else:
        msg = (
            f"[DeltaExchange] Failed to set leverage for product_id={product_id}: "
            f"{result.get('error')}"
        )
        if abort:
            logger.error(msg)
            raise RuntimeError(msg)
        else:
            logger.warning(msg)


def place_order_api(data, auth):
    """
    Place a new order on Delta Exchange via POST /v2/orders.

    Returns:
        (response_shim, response_dict, orderid)

        orderid is formatted as "{product_id}:{order_id}" so that cancel_order
        can recover the product_id without an additional API call.
    """
    token = get_token(data["symbol"], data["exchange"])
    logger.info(f"[DeltaExchange] place_order: symbol={data['symbol']} token={token}")

    # Set leverage if requested (Delta Exchange requires a separate pre-order call)
    leverage = str(data.get("leverage", "")).strip() or os.getenv("DELTA_DEFAULT_LEVERAGE", "")
    if leverage and leverage != "0":
        _set_leverage(int(token), leverage, auth)

    newdata = transform_data(data, token)
    payload = json.dumps(newdata)
    logger.info(f"[DeltaExchange] POST /v2/orders payload: {payload}")

    result = get_api_response("/v2/orders", auth, method="POST", payload=payload)
    logger.debug(f"[DeltaExchange] place_order response: {result}")

    orderid = None
    if result.get("success"):
        order = result.get("result", {})
        raw_id = order.get("id")
        product_id = order.get("product_id", newdata.get("product_id", ""))
        orderid = f"{product_id}:{raw_id}"
        logger.info(f"[DeltaExchange] Order placed. composite orderid={orderid}")
        response_dict = {"orderid": orderid, "status": "success"}
    else:
        error = result.get("error", {})
        msg = error.get("message") or error.get("code") or str(error)
        logger.error(f"[DeltaExchange] Order placement failed: {msg}")
        response_dict = {"status": "error", "message": msg}

    # Minimal response shim for callers that check .status_code
    class _Resp:
        status_code = 200 if result.get("success") else 400
        status = status_code

    return _Resp(), response_dict, orderid


def place_bracket_order_api(data, auth):
    """
    Convenience wrapper: place a bracket order on Delta Exchange.

    A bracket order is a standard POST /v2/orders that additionally carries
    server-side stop-loss and/or take-profit legs managed by the exchange.
    The bracket parameters are forwarded through transform_data via the same
    broker fields that are already supported:

        data["bracket_stop_loss_price"]         – SL trigger price
        data["bracket_stop_loss_limit_price"]   – SL limit price (omit for market SL)
        data["bracket_trail_amount"]            – trailing offset (optional)
        data["bracket_take_profit_price"]       – TP trigger price
        data["bracket_take_profit_limit_price"] – TP limit price (omit for market TP)

    At least one of bracket_stop_loss_price or bracket_take_profit_price must
    be present; Delta Exchange rejects the order otherwise.

    Returns the same (response_shim, response_dict, orderid) tuple as
    place_order_api so callers can be interchanged freely.
    """
    has_bracket = any(
        data.get(k)
        for k in (
            "bracket_stop_loss_price",
            "bracket_take_profit_price",
            "bracket_trail_amount",
        )
    )
    if not has_bracket:
        logger.warning(
            "[DeltaExchange] place_bracket_order_api called without any bracket fields — "
            "falling back to place_order_api"
        )
    return place_order_api(data, auth)


def place_smartorder_api(data, auth):
    """
    Smart order: adjusts position to reach the desired position_size.
    If position_size == 0  → exit full position.
    If position_size != 0  → enter / adjust towards target.
    """
    res = None
    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")
    position_size = int(data.get("position_size", "0"))

    current_position = int(
        get_open_position(symbol, exchange, map_product_type(product), auth)
    )
    logger.info(
        f"[DeltaExchange] SmartOrder: target={position_size} current={current_position}"
    )

    if position_size == 0 and current_position == 0 and int(data["quantity"]) != 0:
        return place_order_api(data, auth)

    if position_size == current_position:
        msg = (
            "No OpenPosition Found. Not placing Exit order."
            if int(data["quantity"]) == 0
            else "No action needed. Position size matches current position"
        )
        return res, {"status": "success", "message": msg}, None

    action = None
    quantity = 0

    if position_size == 0 and current_position > 0:
        action, quantity = "SELL", abs(current_position)
    elif position_size == 0 and current_position < 0:
        action, quantity = "BUY", abs(current_position)
    elif current_position == 0:
        action = "BUY" if position_size > 0 else "SELL"
        quantity = abs(position_size)
    elif position_size > current_position:
        action, quantity = "BUY", position_size - current_position
    elif position_size < current_position:
        action, quantity = "SELL", current_position - position_size

    if action:
        order_data = data.copy()
        order_data["action"] = action
        order_data["quantity"] = str(quantity)
        return place_order_api(order_data, auth)

    return res, {"status": "success", "message": "No action needed"}, None


# ---------------------------------------------------------------------------
# Order cancellation
# ---------------------------------------------------------------------------

def cancel_order(orderid, auth):
    """
    Cancel an open order via DELETE /v2/orders.

    orderid must be in composite format "{product_id}:{order_id}" as produced
    by place_order_api.  If only a bare order_id is passed (legacy), the
    product_id is omitted and Delta Exchange may return an error.
    """
    orderid_str = str(orderid)
    if ":" in orderid_str:
        product_id_str, order_id_str = orderid_str.split(":", 1)
        body = {"id": int(order_id_str), "product_id": int(product_id_str)}
    else:
        logger.warning(
            f"[DeltaExchange] cancel_order called with non-composite id: {orderid_str}"
        )
        body = {"id": int(orderid_str)}

    result = get_api_response("/v2/orders", auth, method="DELETE", payload=json.dumps(body))

    if result.get("success"):
        logger.info(f"[DeltaExchange] Order {orderid} cancelled")
        return {"status": "success", "orderid": orderid}, 200
    else:
        error = result.get("error", {})
        msg = error.get("message") or error.get("code") or str(error)
        logger.error(f"[DeltaExchange] Cancel failed: {msg}")
        return {"status": "error", "message": msg}, 400


def cancel_all_orders_api(data, auth):
    """Cancel all currently open orders."""
    order_book = get_order_book(auth)
    if not order_book:
        return [], []

    orders_to_cancel = [
        o for o in order_book
        if isinstance(o, dict) and o.get("state") in ("open", "pending")
    ]

    cancelled, failed = [], []
    for order in orders_to_cancel:
        raw_id = order.get("id")
        product_id = order.get("product_id", "")
        composite_id = f"{product_id}:{raw_id}"
        _, status = cancel_order(composite_id, auth)
        (cancelled if status == 200 else failed).append(composite_id)

    return cancelled, failed


# ---------------------------------------------------------------------------
# Order modification
# ---------------------------------------------------------------------------

def modify_order(data, auth):
    """Modify an existing open order via PUT /v2/orders."""
    orderid = data["orderid"]
    transformed = transform_modify_order_data(data)
    payload = json.dumps(transformed)
    logger.info(f"[DeltaExchange] PUT /v2/orders payload: {payload}")

    result = get_api_response("/v2/orders", auth, method="PUT", payload=payload)

    if result.get("success"):
        return {"status": "success", "orderid": orderid}, 200
    else:
        error = result.get("error", {})
        msg = error.get("message") or error.get("code") or str(error)
        return {"status": "error", "message": msg}, 400


# ---------------------------------------------------------------------------
# Close all positions
# ---------------------------------------------------------------------------

def close_all_positions(current_api_key, auth):
    """Square off all open positions using market orders."""
    positions = get_positions(auth)
    if not positions:
        return {"message": "No Open Positions Found"}, 200

    for pos in positions:
        if not isinstance(pos, dict):
            continue
        size = int(pos.get("size", 0))
        if size == 0:
            continue

        product_symbol = pos.get("product_symbol", "")
        product_id = pos.get("product_id", "")
        action = "SELL" if size > 0 else "BUY"
        quantity = abs(size)

        # Resolve OpenAlgo symbol from DB; fall back to product_symbol
        symbol = get_symbol(str(product_id), "CRYPTO") or product_symbol
        logger.info(f"[DeltaExchange] Close: {action} {quantity} {symbol}")

        order_payload = {
            "apikey": current_api_key,
            "strategy": "Squareoff",
            "symbol": symbol,
            "action": action,
            "exchange": "CRYPTO",
            "pricetype": "MARKET",
            "product": "NRML",
            "quantity": str(quantity),
        }
        _, api_response, _ = place_order_api(order_payload, auth)
        logger.debug(f"[DeltaExchange] Close response: {api_response}")

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200
