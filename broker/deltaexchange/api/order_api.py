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

def _get_all_open_orders(auth):
    """Internal: Fetch all open orders regardless of creation date (for cancel all operations)."""
    try:
        result = get_api_response("/v2/orders", auth, method="GET", params={"state": "open"})
        if result.get("success"):
            return result.get("result", [])
        logger.warning(f"[DeltaExchange] _get_all_open_orders unexpected response: {result}")
        return []
    except Exception as e:
        logger.error(f"[DeltaExchange] Exception in _get_all_open_orders: {e}")
        return []


def get_order_book(auth):
    """Fetch all orders for today (open + history) for UI display."""
    try:
        from datetime import datetime
        import pytz
        
        # Get today's date in IST
        ist = pytz.timezone("Asia/Kolkata")
        today_date = datetime.now(ist).date()
        
        all_orders = []
        
        # 1. Fetch open orders
        open_result = get_api_response("/v2/orders", auth, method="GET", params={"state": "open"})
        logger.debug(f"[DeltaExchange] /v2/orders (open) count={len(open_result.get('result', []))}")
        if open_result.get("success"):
            all_orders.extend(open_result.get("result", []))

        # 2. Fetch historical orders
        hist_result = get_api_response("/v2/orders/history", auth, method="GET")
        logger.debug(f"[DeltaExchange] /v2/orders/history count={len(hist_result.get('result', []))}")
        if hist_result.get("success"):
            all_orders.extend(hist_result.get("result", []))
            
        # Filter for today's orders only
        today_orders = []
        for order in all_orders:
            created_at = order.get("created_at")
            if created_at:
                try:
                    # Parse UTC timestamp and convert to IST
                    dt_utc = datetime.strptime(created_at[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=pytz.UTC)
                    dt_ist = dt_utc.astimezone(ist)
                    if dt_ist.date() == today_date:
                        today_orders.append(order)
                except Exception as e:
                    logger.warning(f"Error parsing date {created_at}: {e}")
                    
        return today_orders
    except Exception as e:
        logger.error(f"[DeltaExchange] Exception in get_order_book: {e}")
        return []


def get_trade_book(auth):
    """Fetch closed / filled orders (fills) for today only."""
    try:
        from datetime import datetime
        import pytz
        
        # Get today's date in IST
        ist = pytz.timezone("Asia/Kolkata")
        today_date = datetime.now(ist).date()
        
        result = get_api_response("/v2/fills", auth, method="GET")
        logger.debug(f"[DeltaExchange] /v2/fills count={len(result.get('result', []))}")
        if result.get("success"):
            all_trades = result.get("result", [])
            today_trades = []
            for trade in all_trades:
                created_at = trade.get("created_at")
                if created_at:
                    try:
                        # Parse UTC timestamp and convert to IST
                        dt_utc = datetime.strptime(created_at[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=pytz.UTC)
                        dt_ist = dt_utc.astimezone(ist)
                        if dt_ist.date() == today_date:
                            today_trades.append(trade)
                    except Exception as e:
                        logger.warning(f"Error parsing date {created_at}: {e}")
            return today_trades
            
        logger.warning(f"[DeltaExchange] get_trade_book unexpected response: {result}")
        return []
    except Exception as e:
        logger.error(f"[DeltaExchange] Exception in get_trade_book: {e}")
        return []


# ---------------------------------------------------------------------------
# Positions / holdings
# ---------------------------------------------------------------------------

def get_positions(auth):
    """
    Fetch all open positions — both derivatives (margined) and spot (wallet).

    Derivatives come from GET /v2/positions/margined.
    Spot holdings come from GET /v2/wallet/balances — non-INR assets with
    a non-zero balance are synthesised into position-like dicts so they
    appear in the OpenAlgo position book alongside derivative positions.
    """
    positions = []

    # 1. Derivative positions (perpetual futures, options)
    try:
        result = get_api_response("/v2/positions/margined", auth, method="GET")
        logger.debug(f"[DeltaExchange] /v2/positions/margined count={len(result.get('result', []))}")
        if result.get("success"):
            positions.extend(result.get("result", []))
        else:
            logger.warning(f"[DeltaExchange] get_positions/margined unexpected: {result}")
    except Exception as e:
        logger.error(f"[DeltaExchange] Exception in get_positions/margined: {e}")

    # 2. Spot holdings from wallet balances
    try:
        wallet_result = get_api_response("/v2/wallet/balances", auth, method="GET")
        logger.debug(f"[DeltaExchange] /v2/wallet/balances count={len(wallet_result.get('result', []))}")
        if wallet_result.get("success"):
            for asset in wallet_result.get("result", []):
                if not isinstance(asset, dict):
                    continue
                symbol = asset.get("asset_symbol", "") or asset.get("symbol", "")
                # Skip INR (settlement currency) and zero-balance assets
                if symbol in ("INR", "USD", "") or not symbol:
                    continue
                balance = float(asset.get("balance", 0) or 0)
                blocked = float(asset.get("blocked_margin", 0) or 0)
                size = balance - blocked  # available spot holding
                if size <= 0:
                    continue
                # Synthesise a position-like dict matching /v2/positions/margined structure
                spot_symbol = f"{symbol}_INR"
                positions.append({
                    "product_id": asset.get("asset_id", ""),
                    "product_symbol": spot_symbol,
                    "size": size,
                    "entry_price": "0",  # Wallet doesn't track entry price
                    "realized_pnl": "0",
                    "unrealized_pnl": "0",
                    "_is_spot": True,  # Internal flag for downstream mapping
                })
    except Exception as e:
        logger.error(f"[DeltaExchange] Exception fetching spot wallet positions: {e}")

    return positions


def get_holdings(auth):
    """Delta Exchange has no equity holdings concept; spot is shown in positions."""
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

    if not token:
        msg = f"[DeltaExchange] Symbol '{data['symbol']}' not found in master contract DB for exchange '{data['exchange']}'. Run master contract sync first."
        logger.error(msg)
        class _ErrResp:
            status_code = 400
            status = 400
        return _ErrResp(), {"status": "error", "message": msg}, None

    # Set leverage if requested (Delta Exchange requires a separate pre-order call)
    # Priority: order payload > leverage_config DB > env var fallback
    leverage = str(data.get("leverage", "")).strip()
    if not leverage:
        try:
            from database.leverage_db import get_leverage
            db_leverage = get_leverage()
            if db_leverage and int(db_leverage) > 0:
                leverage = str(int(db_leverage))
        except Exception as e:
            logger.warning(f"[DeltaExchange] Could not read leverage config: {e}")
    if not leverage:
        leverage = os.getenv("DELTA_DEFAULT_LEVERAGE", "")
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
    position_size = float(data.get("position_size", "0"))

    current_position = float(
        get_open_position(symbol, exchange, map_product_type(product), auth)
    )
    logger.info(
        f"[DeltaExchange] SmartOrder: target={position_size} current={current_position}"
    )

    if position_size == 0 and current_position == 0 and float(data["quantity"]) != 0:
        return place_order_api(data, auth)

    if position_size == current_position:
        msg = (
            "No OpenPosition Found. Not placing Exit order."
            if float(data["quantity"]) == 0
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
    """
    Cancel all currently open orders via DELETE /v2/orders/all.

    Uses the bulk cancel endpoint instead of cancelling orders one by one.
    Falls back to individual cancellation if bulk endpoint fails.
    """
    # Try bulk cancel first (single API call)
    body = {
        "cancel_limit_orders": True,
        "cancel_stop_orders": True,
        "cancel_reduce_only_orders": True,
    }
    result = get_api_response("/v2/orders/all", auth, method="DELETE", payload=json.dumps(body))
    if result.get("success"):
        logger.info("[DeltaExchange] All open orders cancelled via /v2/orders/all")
        return ["all"], []

    # Fallback: cancel individually
    logger.warning("[DeltaExchange] Bulk cancel failed, falling back to individual cancellation")
    order_book = _get_all_open_orders(auth)
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
    """Square off all open positions (derivatives + spot) using market orders."""
    positions = get_positions(auth)
    if not positions:
        return {"message": "No Open Positions Found"}, 200

    for pos in positions:
        if not isinstance(pos, dict):
            continue
        is_spot = pos.get("_is_spot", False)

        # Use float() to handle fractional spot sizes (e.g. 0.0001 BTC)
        try:
            size = float(pos.get("size", 0))
        except (ValueError, TypeError):
            size = 0
        if size == 0:
            continue

        product_symbol = pos.get("product_symbol", "")
        product_id = pos.get("product_id", "")
        action = "SELL" if size > 0 else "BUY"
        quantity = abs(size)

        # Resolve OpenAlgo symbol from DB.
        # For spot wallet entries, product_id is asset_id (not product token),
        # so look up by brsymbol instead.
        if is_spot:
            symbol = get_oa_symbol(product_symbol, "CRYPTO") or product_symbol
        else:
            symbol = get_symbol(str(product_id), "CRYPTO") or product_symbol
        logger.info(f"[DeltaExchange] Close: {action} {quantity} {symbol}")

        order_payload = {
            "apikey": current_api_key,
            "strategy": "Squareoff",
            "symbol": symbol,
            "action": action,
            "exchange": "CRYPTO",
            "pricetype": "MARKET",
            "product": "CNC" if is_spot else "NRML",
            "quantity": str(quantity),
        }
        _, api_response, _ = place_order_api(order_payload, auth)
        logger.debug(f"[DeltaExchange] Close response: {api_response}")

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200
