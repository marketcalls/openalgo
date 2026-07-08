import json
import os

import httpx
import threading
import time

from broker.indmoney.api.baseurl import get_url
from broker.indmoney.mapping.order_data import (
    OPEN_STATUSES,
    TRIGGER_PENDING_STATUSES,
)
from broker.indmoney.mapping.transform_data import (
    map_exchange,
    map_exchange_type,
    map_product_type,
    map_segment,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_oa_symbol, get_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# 429 (rate-limit) retry configuration. IndStocks enforces per-category rate
# limits (Order 10/s, Data/Quote 5/s, Non-Trading 15/s) and returns 429 on
# breach (docs 03-conventions / 14-errors), so requests retry with backoff.
_MAX_RETRIES = 3
_RATE_LIMIT_BASE_DELAY = 1.0  # seconds; doubled each attempt (1s, 2s, 4s)


def request_with_retry(client, method, url, **kwargs):
    """
    Perform an httpx request, retrying HTTP 429 with exponential backoff
    (honouring Retry-After when present). Sets ``.status`` for compatibility
    with the existing codebase.
    """
    response = None
    for attempt in range(_MAX_RETRIES):
        response = client.request(method.upper(), url, **kwargs)
        if response.status_code == 429 and attempt < _MAX_RETRIES - 1:
            retry_after = response.headers.get("Retry-After")
            try:
                delay = (
                    min(float(retry_after), 30.0)
                    if retry_after
                    else _RATE_LIMIT_BASE_DELAY * (2 ** attempt)
                )
            except (TypeError, ValueError):
                delay = _RATE_LIMIT_BASE_DELAY * (2 ** attempt)
            logger.warning(
                f"Rate limit hit (429) on {url}, retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{_MAX_RETRIES})"
            )
            time.sleep(delay)
            continue
        break
    if response is not None:
        response.status = response.status_code
    return response


def get_api_response(endpoint, auth, method="GET", payload="", params=None):
    AUTH_TOKEN = auth
    api_key = os.getenv("BROKER_API_KEY")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    url = get_url(endpoint)

    try:
        # request_with_retry handles HTTP 429 with backoff and sets .status
        if method == "GET":
            response = request_with_retry(
                client, "GET", url, headers=headers, params=params
            )
        elif method == "POST":
            response = request_with_retry(
                client, "POST", url, headers=headers, content=payload, params=params
            )
        else:
            response = request_with_retry(
                client, method, url, headers=headers, content=payload, params=params
            )

        # Check if response is successful
        if response.status_code not in [200, 201]:
            logger.error(f"HTTP Error {response.status_code} for {url}: {response.text}")
            return {"status": "error", "message": f"HTTP {response.status_code}: {response.text}"}

        # Check if response has content
        if not response.text.strip():
            logger.error(f"Empty response from {url}")
            return {"status": "error", "message": "Empty response from API"}

        # Parse the response JSON
        try:
            response_data = json.loads(response.text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response from {url}: {e}")
            logger.error(f"Raw response: {response.text[:500]}...")  # Log first 500 chars
            return {"status": "error", "message": f"Invalid JSON response: {str(e)}"}

        # Check for API errors in the response
        if isinstance(response_data, dict):
            # Indmoney API errors come in this format
            if response_data.get("status") in ["error", "failure"]:
                # Handle both 'error' and 'failure' status
                if response_data.get("status") == "failure" and "error" in response_data:
                    error_message = response_data.get("error", {}).get("msg", "Unknown error")
                else:
                    error_message = response_data.get("message", "Unknown error")
                logger.error(f"API Error: {error_message}")
                # Return the error response for further handling
                return response_data

            # For successful responses, return the data array directly for list endpoints
            if response_data.get("status") == "success" and "data" in response_data:
                logger.debug(f"Successfully fetched data from {endpoint}")
                return response_data["data"]

        logger.debug(f"Response data: {response_data}")
        return response_data

    except Exception as e:
        # Handle connection or parsing errors
        logger.exception(f"Error in API request to {url}: {e}")
        return {"status": "error", "message": str(e)}


def get_order_book(auth):
    try:
        result = get_api_response("/order-book", auth)
        # Ensure we never return None
        if result is None:
            logger.warning("get_api_response returned None, returning empty list")
            return []
        return result
    except Exception as e:
        logger.error(f"Exception in get_order_book: {e}")
        return []


def get_trade_book(auth):
    """
    Fetch all trades for the current trading day.
    Fetches trades from both EQUITY and DERIVATIVE segments.
    Enriches trade data with order book information (product type, transaction type).
    """
    try:
        all_trades = []

        # Fetch EQUITY trades
        equity_result = get_api_response("/trade-book", auth, params={"segment": "EQUITY"})
        if equity_result and isinstance(equity_result, list):
            # Tag each trade with segment info for later mapping
            for trade in equity_result:
                if isinstance(trade, dict):
                    trade["segment"] = "EQUITY"
            all_trades.extend(equity_result)
        elif (
            equity_result
            and isinstance(equity_result, dict)
            and equity_result.get("status") != "error"
        ):
            logger.warning(f"Unexpected EQUITY trade response format: {equity_result}")

        # Fetch DERIVATIVE trades
        derivative_result = get_api_response("/trade-book", auth, params={"segment": "DERIVATIVE"})
        if derivative_result and isinstance(derivative_result, list):
            # Tag each trade with segment info for later mapping
            for trade in derivative_result:
                if isinstance(trade, dict):
                    trade["segment"] = "DERIVATIVE"
            all_trades.extend(derivative_result)
        elif (
            derivative_result
            and isinstance(derivative_result, dict)
            and derivative_result.get("status") != "error"
        ):
            logger.warning(f"Unexpected DERIVATIVE trade response format: {derivative_result}")

        # Fetch order book to enrich trade data with product and transaction type
        order_book = get_order_book(auth)
        order_map = {}

        if order_book and isinstance(order_book, list):
            # Index each order under BOTH identifiers it may expose: the internal
            # id (EQ-/DRV-/GTT-...) and the exchange order id. Trades join on the
            # exchange order id (their exch_order_id), which the order book also
            # carries in exch_order_id once the order reaches the exchange.
            for order in order_book:
                if isinstance(order, dict):
                    order_info = {
                        "txn_type": order.get("txn_type", ""),
                        "product": order.get("product", ""),
                        "segment": order.get("segment", ""),
                    }
                    for key in (order.get("exch_order_id"), order.get("id")):
                        if key:
                            order_map[str(key)] = order_info

        # Enrich trades with order book data
        for trade in all_trades:
            if isinstance(trade, dict):
                # Trades carry the exchange order id in exch_order_id
                exch_order_id = trade.get("exch_order_id")
                order_info = order_map.get(str(exch_order_id)) if exch_order_id else None
                if order_info:
                    trade["txn_type"] = order_info["txn_type"]
                    trade["product"] = order_info["product"]
                    logger.debug(
                        f"Enriched trade {exch_order_id} with txn_type={order_info['txn_type']}, product={order_info['product']}"
                    )
                else:
                    logger.debug(
                        f"No matching order for trade exch_order_id={exch_order_id}; "
                        f"txn_type/product left unenriched"
                    )

        logger.debug(
            f"Fetched {len(all_trades)} total trades (EQUITY + DERIVATIVE), enriched with order book data"
        )
        return all_trades
    except Exception as e:
        logger.error(f"Exception in get_trade_book: {e}")
        return []


def get_positions(auth):
    """
    Fetch all positions for the current trading day.
    Fetches positions from all combinations of segment and product:
    - Derivative: MARGIN, INTRADAY
    - Equity: CNC, INTRADAY
    """
    try:
        all_positions = []

        # Define all combinations of segment and product
        position_queries = [
            {"segment": "derivative", "product": "margin"},
            {"segment": "derivative", "product": "intraday"},
            {"segment": "equity", "product": "cnc"},
            {"segment": "equity", "product": "intraday"},
        ]

        # Fetch positions for each combination
        for query in position_queries:
            result = get_api_response("/portfolio/positions", auth, params=query)

            # Debug: Log the actual API response to understand the structure
            logger.debug(f"Positions API response for {query}: {result}")

            if result and isinstance(result, dict):
                # Extract net_positions and day_positions from the response
                net_positions = result.get("net_positions", [])
                day_positions = result.get("day_positions", [])

                # Debug: Log sample position if available
                if net_positions:
                    logger.debug(
                        f"Sample net_position fields: {list(net_positions[0].keys()) if net_positions[0] else 'empty'}"
                    )
                if day_positions:
                    logger.debug(
                        f"Sample day_position fields: {list(day_positions[0].keys()) if day_positions[0] else 'empty'}"
                    )

                if net_positions and isinstance(net_positions, list):
                    # Tag positions with the query parameters for context
                    for pos in net_positions:
                        if isinstance(pos, dict):
                            pos["query_segment"] = query["segment"]
                            pos["query_product"] = query["product"]
                    all_positions.extend(net_positions)

                if day_positions and isinstance(day_positions, list):
                    # Tag positions with the query parameters for context
                    for pos in day_positions:
                        if isinstance(pos, dict):
                            pos["query_segment"] = query["segment"]
                            pos["query_product"] = query["product"]
                    all_positions.extend(day_positions)

            elif result and isinstance(result, list):
                # Fallback: if response is directly a list (legacy format)
                all_positions.extend(result)

        logger.debug(f"Fetched {len(all_positions)} total positions (all segments and products)")
        return all_positions

    except Exception as e:
        logger.error(f"Exception in get_positions: {e}")
        return []


def get_holdings(auth):
    try:
        result = get_api_response("/portfolio/holdings", auth)
        # Ensure we never return None
        if result is None:
            logger.warning("get_api_response returned None for holdings, returning empty list")
            return []
        return result
    except Exception as e:
        logger.error(f"Exception in get_holdings: {e}")
        return []


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



def _map_exchange_segment(exchange_segment):
    """
    Map an IndMoney position ``exchange_segment`` (e.g. NSE_EQ, NSE_FNO, BSE_EQ)
    or a legacy segment label (EQUITY, F&O, COMMODITY) to the OpenAlgo exchange code.
    """
    seg = str(exchange_segment or "").upper()
    mapping = {
        "NSE_EQ": "NSE",
        "NSE_FNO": "NFO",
        "NSE_FO": "NFO",
        "BSE_EQ": "BSE",
        "BSE_FNO": "BFO",
        "BSE_FO": "BFO",
        "MCX_FO": "MCX",
        "MCX_COMM": "MCX",
        # Legacy labels
        "EQUITY": "NSE",
        "F&O": "NFO",
        "FUTURES": "NFO",
        "COMMODITY": "MCX",
    }
    if seg in mapping:
        return mapping[seg]
    if seg.startswith("NSE"):
        return "NSE"
    if seg.startswith("BSE"):
        return "BSE"
    if seg.startswith("MCX"):
        return "MCX"
    return seg


def get_open_position(tradingsymbol, exchange, product, auth):
    # Resolve the reliable security_id (token) for the requested symbol before
    # converting to broker symbol format for the fallback name match.
    target_token = str(get_token(tradingsymbol, exchange) or "")
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    positions_response = _get_cached_positions(auth)
    net_qty = "0"
    # logger.debug(f"Positions response: {positions_response}")

    # Check if positions_response is an error response
    if isinstance(positions_response, dict) and positions_response.get("status") == "error":
        logger.error(
            f"Error getting positions for {tradingsymbol}: {positions_response.get('message', 'API Error')}"
        )
        return net_qty

    # Handle the actual flat array format from IndMoney API
    all_positions = []
    if isinstance(positions_response, list):
        # Direct flat list from actual API
        all_positions = positions_response
    elif isinstance(positions_response, dict) and "net_positions" in positions_response:
        # Fallback to documented format if it changes back
        net_positions = positions_response.get("net_positions", [])
        day_positions = positions_response.get("day_positions", [])
        all_positions = net_positions + day_positions

    # Only process if all_positions is valid and not empty
    if all_positions and isinstance(all_positions, list):
        for position in all_positions:
            if not isinstance(position, dict):
                continue

            # Read documented IndMoney position fields (with legacy fallbacks)
            position_token = str(position.get("security_id", "") or "")
            position_symbol = position.get("trading_symbol") or position.get("symbol")
            position_qty = position.get("net_quantity", position.get("net_qty", 0))

            # Map exchange_segment (e.g. NSE_EQ, NSE_FNO, BSE_EQ) to the
            # NSE/BSE/MCX root returned by map_exchange_type()
            mapped_exchange = map_exchange_type(
                _map_exchange_segment(
                    position.get("exchange_segment", position.get("segment", ""))
                )
            )

            # Prefer a reliable security_id match; fall back to symbol match
            token_match = target_token and position_token == target_token
            symbol_match = position_symbol == tradingsymbol
            if (token_match or symbol_match) and mapped_exchange == map_exchange_type(exchange):
                net_qty = str(position_qty)
                break  # Return the first match

    return net_qty


def place_order_api(data, auth):
    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv("BROKER_API_KEY")
    data["apikey"] = BROKER_API_KEY
    token = get_token(data["symbol"], data["exchange"])
    logger.debug(f"Original order data: {data}")
    logger.debug(f"Security token: {token}")
    newdata = transform_data(data, token)
    logger.debug(f"Transformed data: {newdata}")
    headers = {
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = json.dumps(newdata)

    logger.debug(f"Placing order with payload: {payload}")
    logger.debug(f"Indmoney API URL: {get_url('/order')}")
    logger.debug(f"Indmoney API Headers: {headers}")
    logger.debug(f"Indmoney API Payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    url = get_url("/order")
    res = request_with_retry(client, "POST", url, headers=headers, content=payload)

    try:
        response_data = json.loads(res.text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON response: {e}")
        return res, {"error": "Invalid JSON response"}, None

    logger.debug(f"Place order response: {response_data}")

    # Check if the API call was successful before accessing order ID
    orderid = None
    if res.status_code == 200 or res.status_code == 201:
        if response_data and response_data.get("status") == "success":
            # Indmoney returns order ID in data.order_id field
            orderid = response_data.get("data", {}).get("order_id")
            logger.debug(f"Order placed successfully with ID: {orderid}")
            # Format response to match OpenAlgo API standard
            response_data = {"orderid": orderid, "status": "success"}
        elif response_data and response_data.get("status") in ["error", "failure"]:
            # Handle API errors/failures - but check if order was actually placed
            if response_data.get("status") == "failure" and "error" in response_data:
                error_msg = response_data.get("error", {}).get("msg", "Unknown error")
                # Check if this is just a response parsing issue but order was placed
                if "no order number in rs response" in error_msg.lower():
                    logger.warning(f"Order likely placed successfully despite error: {error_msg}")
                    # Create a mock successful response since order appears in orderbook
                    response_data = {"orderid": "ORDER_PLACED", "status": "success"}
                    orderid = "ORDER_PLACED"  # Placeholder since actual ID not available
                else:
                    logger.error(f"Order placement failed: {error_msg}")
            else:
                error_msg = response_data.get("message", "Unknown error")
                logger.error(f"Order placement failed: {error_msg}")
        else:
            logger.error(f"Order placement failed: {response_data}")
    else:
        logger.error(f"API call failed with status {res.status_code}: {response_data}")

    return res, response_data, orderid


def place_smartorder_api(data, auth):
    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv("BROKER_API_KEY")
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
            get_open_position(symbol, exchange, map_product_type(product), AUTH_TOKEN)
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
            res, response, orderid = place_order_api(order_data, AUTH_TOKEN)
            _invalidate_position_cache(AUTH_TOKEN)

            return res, response, orderid
        else:
            # No action determined - should not happen with current logic
            response = {"status": "success", "message": "No action needed"}
            return res, response, None


def close_all_positions(current_api_key, auth):
    AUTH_TOKEN = auth
    # Fetch the current open positions
    positions_response = get_positions(AUTH_TOKEN)
    logger.debug(f"Positions response for closing all: {positions_response}")

    # Handle the actual flat array format from IndMoney API
    all_positions = []
    if isinstance(positions_response, list):
        # Direct flat list from actual API
        all_positions = positions_response
    elif isinstance(positions_response, dict):
        # Fallback to handle documented nested format if it changes back
        net_positions = positions_response.get("net_positions", [])
        day_positions = positions_response.get("day_positions", [])
        all_positions = net_positions + day_positions

    # Check if the positions data is null or empty
    if not all_positions:
        return {"message": "No Open Positions Found"}, 200

    if all_positions:
        # Loop through each position to close
        for position in all_positions:
            if not isinstance(position, dict):
                continue

            # Skip if net quantity is zero - documented field with legacy fallback
            net_qty = position.get("net_quantity", position.get("net_qty", 0))
            if int(net_qty) == 0:
                continue

            # Determine action based on net quantity
            action = "SELL" if int(net_qty) > 0 else "BUY"
            quantity = abs(int(net_qty))

            # Map exchange_segment (documented) to OpenAlgo exchange, legacy fallback
            exchange = _map_exchange_segment(
                position.get("exchange_segment", position.get("segment", ""))
            )

            # get openalgo symbol to send to placeorder function
            symbol = get_symbol(position["security_id"], exchange)
            logger.debug(f"The Symbol is {symbol}")

            # Determine product type. get_positions() tags each item with the
            # query_product it was fetched under (cnc/intraday/margin); fall back
            # to any product field the API returns.
            api_product = str(
                position.get("query_product", position.get("product", ""))
            ).upper()
            if api_product == "INTRADAY":
                product = "MIS"
            elif api_product in ("DELIVERY", "CNC"):
                product = "CNC"
            elif api_product == "MARGIN" or exchange in ["NFO", "MCX", "BFO", "CDS"]:
                product = "NRML"
            else:
                product = "MIS"

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
            _, api_response, _ = place_order_api(place_order_payload, AUTH_TOKEN)

            logger.debug(f"Close position response: {api_response}")

            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth

    # Set up the request headers
    headers = {
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Prepare the payload for Indmoney cancel order API
    payload = {
        "segment": "DERIVATIVE" if orderid.startswith("DRV-") else "EQUITY",
        "order_id": orderid,
    }

    # Make the POST request to cancel order using httpx
    url = get_url("/order/cancel")
    res = request_with_retry(client, "POST", url, headers=headers, content=json.dumps(payload))

    # Parse the response
    data = json.loads(res.text)

    # Check if the request was successful
    if res.status_code == 200 and data.get("status") == "success":
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Handle error response - check for both error message formats
        if data.get("status") == "failure" and "error" in data:
            error_msg = data.get("error", {}).get("msg", "Failed to cancel order")
        else:
            error_msg = data.get("message", "Failed to cancel order")
        # Return an error response
        return {"status": "error", "message": error_msg}, res.status


def modify_order(data, auth):
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv("BROKER_API_KEY")
    data["apikey"] = BROKER_API_KEY

    orderid = data["orderid"]
    transformed_order_data = transform_modify_order_data(
        data
    )  # You need to implement this function

    # Set up the request headers
    headers = {
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = json.dumps(transformed_order_data)

    logger.debug(f"Modify order payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Construct the URL for modifying the order
    url = get_url("/order/modify")

    # Make the POST request using httpx
    res = request_with_retry(client, "POST", url, headers=headers, content=payload)

    # Parse the response
    data = json.loads(res.text)
    logger.debug(f"Modify order response: {data}")
    # return {"status": "error", "message": data.get("message", "Failed to modify order")}, res.status

    if res.status_code == 200 and data.get("status") == "success":
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Handle error response - check for both error message formats
        if data.get("status") == "failure" and "error" in data:
            error_msg = data.get("error", {}).get("msg", "Failed to modify order")
        else:
            error_msg = data.get("message", "Failed to modify order")
        return {"status": "error", "message": error_msg}, res.status


def cancel_all_orders_api(data, auth):
    # Get the order book
    AUTH_TOKEN = auth
    order_book_response = get_order_book(AUTH_TOKEN)
    logger.debug(f"Order book for cancel all: {order_book_response}")
    if order_book_response is None:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are still open or trigger-pending (cancellable).
    # Covers all live-order statuses per Indmoney docs (QUEUED, O-PENDING,
    # PENDING, PROCESSING, INITIATED, MODIFIED, SL-PENDING, PARTIALLY FILLED).
    cancellable_statuses = OPEN_STATUSES | TRIGGER_PENDING_STATUSES
    orders_to_cancel = [
        order
        for order in order_book_response
        if str(order.get("status", "")).upper().strip() in cancellable_statuses
    ]
    logger.debug(f"Orders to cancel: {orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order["id"]
        cancel_response, status_code = cancel_order(orderid, AUTH_TOKEN)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
