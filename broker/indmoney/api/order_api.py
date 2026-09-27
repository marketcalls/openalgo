import json
import os
import threading
import time

from broker.indmoney.api.baseurl import get_url
from broker.indmoney.api.rate_limiter import rate_limited_request
from broker.indmoney.mapping.order_data import (
    OPEN_STATUSES,
    SMART_ORDER_TYPES,
    TRIGGER_PENDING_STATUSES,
    map_product_to_openalgo,
    resolve_exchange,
)
from broker.indmoney.mapping.transform_data import (
    map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_br_symbol, get_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)




def get_api_response(endpoint, auth, method="GET", payload="", params=None):
    AUTH_TOKEN = auth

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
            response = rate_limited_request(
                client, "GET", url, headers=headers, params=params
            )
        elif method == "POST":
            response = rate_limited_request(
                client, "POST", url, headers=headers, content=payload, params=params
            )
        else:
            response = rate_limited_request(
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
            # The Instruments, Market Quotes and Historical endpoints use a
            # different envelope: {"message": ..., "success": false} with no
            # `status` and no `error_type` (docs 14-errors). Without this branch
            # those failures fall through as success and degrade to empty data.
            if response_data.get("success") is False:
                error_message = response_data.get("message") or response_data.get(
                    "error", "Unknown error"
                )
                logger.error(f"API Error from {endpoint}: {error_message}")
                return {"status": "error", "message": error_message}

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
                        # The trade-book payload carries no exchange at all, so
                        # the matching order is the only place the real venue
                        # (NSE vs BSE) can come from.
                        "exchange": order.get("exchange", ""),
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
                    if order_info.get("exchange"):
                        trade["exchange"] = order_info["exchange"]
                    logger.debug(
                        f"Enriched trade {exch_order_id} with txn_type={order_info['txn_type']}, "
                        f"product={order_info['product']}, exchange={order_info.get('exchange', '')}"
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


# Scrip-code segment prefixes for the quote API, keyed by OpenAlgo exchange.
_QUOTE_SEGMENT_BY_EXCHANGE = {
    "NSE": "NSE",
    "BSE": "BSE",
    "NFO": "NFO",
    "BFO": "BFO",
}


def _enrich_positions_with_ltp(positions, auth):
    """
    Attach a live price to each open position.

    /portfolio/positions returns no last-traded price and no unrealized P&L -
    only `realized_profit`. Without this the position book shows LTP 0, market
    value 0, and reports realized P&L as though it were total P&L. One batched
    /market/quotes/ltp call fills that in.

    Failures are non-fatal: positions are still returned, just without LTP.
    """
    scrip_by_position = {}
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        # Closed rows have nothing to mark to market.
        try:
            if int(pos.get("net_qty", pos.get("net_quantity", 0)) or 0) == 0:
                continue
        except (TypeError, ValueError):
            pass

        token = str(pos.get("security_id") or "").strip()
        if not token:
            continue

        exchange = resolve_exchange(
            token,
            pos.get("exchange") or pos.get("exchange_segment", ""),
            pos.get("segment") or pos.get("query_segment", ""),
        )
        segment = _QUOTE_SEGMENT_BY_EXCHANGE.get(exchange)
        if not segment:
            continue

        scrip_by_position[id(pos)] = f"{segment}_{token}"

    if not scrip_by_position:
        return

    try:
        scrip_codes = sorted(set(scrip_by_position.values()))
        response = get_api_response(
            "/market/quotes/ltp",
            auth,
            "GET",
            params={"scrip-codes": ",".join(scrip_codes)},
        )
        # get_api_response unwraps `data` on the standard envelope; tolerate both.
        quotes = response if isinstance(response, dict) else {}
        if "data" in quotes and isinstance(quotes.get("data"), dict):
            quotes = quotes["data"]

        for pos in positions:
            scrip = scrip_by_position.get(id(pos))
            if not scrip:
                continue
            quote = quotes.get(scrip)
            if isinstance(quote, dict) and quote.get("live_price") is not None:
                pos["last_traded_price"] = quote["live_price"]

        logger.debug(f"Enriched {len(scrip_codes)} position(s) with LTP")

    except Exception as e:
        logger.warning(f"Could not enrich positions with LTP: {e}")



def get_positions(auth, include_ltp=True):
    """
    Fetch all positions for the current trading day.
    Fetches positions from all combinations of segment and product:
    - Derivative: MARGIN, INTRADAY
    - Equity: CNC, INTRADAY

    Args:
        auth: IndMoney access token.
        include_ltp: Attach live prices so the position book can show market
            value and MTM. Skipped on the smart-order path, which only needs
            net quantity and should not pay for an extra quote round trip.
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

            # /portfolio/positions returns `data` as a FLAT ARRAY. Collect the
            # rows first, then tag every row with the query it came from - the
            # payload itself does not always state the segment/product, and
            # map_position_data() relies on these tags. Tagging only one shape
            # of the response is what previously left every position untagged
            # and mapped to NSE.
            batch = []
            if result and isinstance(result, list):
                batch = result
            elif result and isinstance(result, dict):
                # Tolerate the older documented net/day grouping if it returns.
                net_positions = result.get("net_positions") or []
                day_positions = result.get("day_positions") or []
                if isinstance(net_positions, list):
                    batch.extend(net_positions)
                if isinstance(day_positions, list):
                    batch.extend(day_positions)

            if batch:
                logger.debug(
                    f"Sample position fields: "
                    f"{list(batch[0].keys()) if isinstance(batch[0], dict) else type(batch[0])}"
                )

            for pos in batch:
                if isinstance(pos, dict):
                    pos["query_segment"] = query["segment"]
                    pos["query_product"] = query["product"]
                    all_positions.append(pos)

        if include_ltp and all_positions:
            _enrich_positions_with_ltp(all_positions, auth)

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

    # Cache miss or expired - fetch from broker. The smart-order path only reads
    # net quantity, so skip the LTP round trip that the position book needs.
    positions_data = get_positions(auth, include_ltp=False)

    with _position_cache_lock:
        _position_cache[auth] = {"data": positions_data, "timestamp": time.monotonic()}

    return positions_data


def _invalidate_position_cache(auth):
    """Invalidate the position cache so the next queued order fetches fresh data."""
    with _position_cache_lock:
        _position_cache.pop(auth, None)



def _position_exchange(position):
    """Resolve the OpenAlgo exchange for one IndMoney position row."""
    return resolve_exchange(
        position.get("security_id"),
        position.get("exchange") or position.get("exchange_segment", ""),
        position.get("segment") or position.get("query_segment", ""),
    )


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
            position_symbol = position.get("symbol") or position.get("trading_symbol")
            position_qty = position.get("net_qty", position.get("net_quantity", 0))

            # Compare the exact OpenAlgo exchange. The old code collapsed NFO to
            # its NSE parent on both sides, which happened to work for NSE F&O
            # but matched a BFO position against a BSE request and vice versa.
            position_exchange = _position_exchange(position)

            # Prefer a reliable security_id match; fall back to symbol match
            token_match = target_token and position_token == target_token
            symbol_match = position_symbol == tradingsymbol
            if (token_match or symbol_match) and position_exchange == str(exchange).upper():
                net_qty = str(position_qty)
                break  # Return the first match

    return net_qty


def _is_smart_order(orderid, auth):
    """
    True if `orderid` belongs to the smart-order (GTT) book.

    A GTT- prefix is conclusive, but a smart-order PARENT is issued an
    EQ-/DRV- id exactly like a regular order, so the prefix alone cannot
    decide. Fall back to the order book and match on the order type.

    Confirmed live on 2026-08-06: a standalone TRIGGER order comes BACK from
    the order book as order_type "GTT_LIMIT", not "TRIGGER". Matching only the
    request-side vocabulary sent stop cancels/modifies to the regular endpoints.

    On any doubt this returns False, keeping the regular endpoint - the same
    behaviour as before this routing existed.
    """
    orderid = str(orderid or "")
    if orderid.startswith("GTT-"):
        return True

    try:
        for order in get_order_book(auth) or []:
            if isinstance(order, dict) and str(order.get("id", "")) == orderid:
                order_type = str(order.get("order_type", "")).upper()
                return order_type in SMART_ORDER_TYPES
    except Exception as e:
        logger.warning(f"Could not classify order {orderid} against the order book: {e}")
    return False


def _extract_order_id(response_data):
    """
    Pull the order id out of a placement response.

    /order        -> {"data": {"order_id": ...}}
    /smart/order  -> {"data": {"order_data": [{"order_id": ..., "child_order_details": {...}}]}}
    """
    data = response_data.get("data") or {}
    if not isinstance(data, dict):
        return None

    order_id = data.get("order_id")
    if order_id:
        return order_id

    order_data = data.get("order_data")
    if isinstance(order_data, list):
        for entry in order_data:
            if isinstance(entry, dict) and entry.get("order_id"):
                child = entry.get("child_order_details") or {}
                if isinstance(child, dict) and child.get("order_id"):
                    logger.info(
                        f"Smart order {entry['order_id']} created with child leg "
                        f"{child['order_id']} (cancel/modify each separately)"
                    )
                return entry["order_id"]
    return None


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

    # Never log `headers` - it carries the Authorization token.
    # A TRIGGER order is a stop order, and the trigger facility lives on
    # /smart/order - /order has no stop type and no trigger_price field.
    is_trigger_order = newdata.get("order_type") == "TRIGGER"
    endpoint = "/smart/order" if is_trigger_order else "/order"

    # Never log `headers` - it carries the Authorization token.
    logger.debug(f"Placing order at {get_url(endpoint)} with payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    url = get_url(endpoint)
    res = rate_limited_request(client, "POST", url, headers=headers, content=payload)

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
            # /order returns data.order_id; /smart/order returns
            # data.order_data[<n>].order_id (with the SL/target child, if any,
            # under child_order_details).
            orderid = _extract_order_id(response_data)
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
    # Fetch the current open positions. Squaring off only needs net quantity,
    # so skip the LTP enrichment round trip.
    positions_response = get_positions(AUTH_TOKEN, include_ltp=False)
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
            net_qty = position.get("net_qty", position.get("net_quantity", 0))
            if int(net_qty or 0) == 0:
                continue

            # Determine action based on net quantity
            action = "SELL" if int(net_qty) > 0 else "BUY"
            quantity = abs(int(net_qty))

            exchange = _position_exchange(position)

            # get openalgo symbol to send to placeorder function
            symbol = get_symbol(position["security_id"], exchange)
            if not symbol:
                logger.error(
                    f"Cannot square off token {position.get('security_id')} on {exchange}: "
                    "symbol not found in the master contract; skipping"
                )
                continue
            logger.debug(f"The Symbol is {symbol}")

            # Determine product type. get_positions() tags each item with the
            # query_product it was fetched under (cnc/intraday/margin); fall back
            # to any product field the API returns.
            product = map_product_to_openalgo(
                position.get("query_product") or position.get("product", ""), exchange
            )

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

    # A stop/GTT order must be cancelled on the smart-order endpoint;
    # /order/cancel does not know about it.
    endpoint = (
        "/smart/order/cancel" if _is_smart_order(orderid, AUTH_TOKEN) else "/order/cancel"
    )

    # Make the POST request to cancel order using httpx
    url = get_url(endpoint)
    res = rate_limited_request(client, "POST", url, headers=headers, content=json.dumps(payload))

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

    # A stop/GTT order lives on the smart-order endpoint, which additionally
    # requires algo_id and takes trigger_price rather than a plain limit.
    is_smart = _is_smart_order(orderid, AUTH_TOKEN)
    if is_smart:
        transformed_order_data["algo_id"] = "99999"  # smart orders are NSE-only
        trigger_price = data.get("trigger_price")
        if trigger_price:
            transformed_order_data["trigger_price"] = float(trigger_price)
            # Keep the trigger-limit aligned with the new limit price so the
            # modified stop still executes as a trigger-limit.
            transformed_order_data["trigger_limit_price"] = transformed_order_data.pop(
                "limit_price", None
            )
            transformed_order_data = {
                k: v for k, v in transformed_order_data.items() if v is not None
            }

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
    url = get_url("/smart/order/modify" if is_smart else "/order/modify")

    # Make the POST request using httpx
    res = rate_limited_request(client, "POST", url, headers=headers, content=payload)

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
