# broker/hdfcsecurities/api/order_api.py
#
# HDFC Securities InvestRight order management.
#
#   POST   /oapi/v1/orders/regular            place order
#   PUT    /oapi/v1/orders/regular/<order_id> modify order
#   DELETE /oapi/v1/orders/regular/<order_id> cancel order
#   GET    /oapi/v1/orders                    order book
#   GET    /oapi/v1/trades                    trade book
#   GET    /oapi/v1/portfolio/cumulative-positions   positions
#   GET    /oapi/v1/portfolio/holdings        demat holdings
#
# Every call needs `api_key` as a QUERY param plus the mandatory Authorization /
# User-Agent headers -- see api/baseurl.py.
#
# The positions endpoint is documented twice with two different paths
# (`cumulative-positions` in the endpoint block, `overall_positions` in the curl
# sample). Unauthenticated route probing shows only `cumulative-positions`
# exists; `overall_positions` 404s. The same probing showed the profile endpoint
# answers GET, not the documented POST.

import threading
import time

from broker.hdfcsecurities.api.baseurl import (
    base_params,
    get_hdfcsecurities_headers,
    get_root_url,
)
from broker.hdfcsecurities.mapping.order_data import is_cancellable
from broker.hdfcsecurities.mapping.transform_data import (
    reverse_map_product_type,
    to_ltp_exchange,
    to_oa_exchange,
    transform_data,
    transform_modify_order_data,
)
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def _request(method, endpoint, auth, params=None, payload=None):
    """Issue an authenticated InvestRight request and return the parsed JSON."""
    client = get_httpx_client()
    headers = get_hdfcsecurities_headers(auth, with_json=payload is not None)
    url = f"{get_root_url()}{endpoint}"

    query = base_params()
    if params:
        query.update(params)

    method = method.upper()
    if method == "GET":
        response = client.get(url, headers=headers, params=query)
    elif method == "POST":
        response = client.post(url, headers=headers, params=query, json=payload)
    elif method == "PUT":
        response = client.put(url, headers=headers, params=query, json=payload)
    elif method == "DELETE":
        response = client.delete(url, headers=headers, params=query)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    try:
        return response.json()
    except ValueError:
        raise ValueError(
            f"HDFC Securities returned a non-JSON response (HTTP {response.status_code}) "
            f"for {endpoint}: {response.text[:200]}"
        ) from None


def get_order_book(auth):
    return _request("GET", "/oapi/v1/orders", auth)


def get_trade_book(auth):
    return _request("GET", "/oapi/v1/trades", auth)


def _enrich_with_ltp(auth, rows):
    """Add an `ltp` key to raw position / holding rows from one batched call.

    InvestRight's position and holding payloads carry no live price at all
    (positions have no LTP field, holdings only a previous close), so
    mark-to-market has to come from /fetch-ltp. This runs on the RAW rows
    because the mapping layer -- the only other hook before the P&L maths --
    never sees the auth token.

    Rows are resolved by `security_id`, which is the master contract's
    brsymbol. Anything unresolvable, and any failure of the batch itself,
    simply leaves `ltp` absent rather than sinking the whole book.
    """
    from broker.hdfcsecurities.api.data import BrokerData
    from broker.hdfcsecurities.database.master_contract_db import SymToken, db_session

    if not rows:
        return rows

    wanted = {}
    try:
        with db_session() as session:
            for index, row in enumerate(rows):
                security_id = str(row.get("security_id") or "").strip()
                if not security_id:
                    continue
                exchange = to_oa_exchange(row.get("exchange"), row.get("instrument_segment"))
                match = (
                    session.query(SymToken)
                    .filter(SymToken.exchange == exchange, SymToken.brsymbol == security_id)
                    .first()
                )
                if match:
                    wanted[index] = (to_ltp_exchange(match.exchange), str(match.token))
    except Exception as e:
        logger.warning(f"Could not resolve instruments for LTP enrichment: {e}")
        return rows

    if not wanted:
        return rows

    try:
        data = BrokerData(auth)
        quotes = {}
        instruments = [
            {"exchange": exchange, "token": token}
            for exchange, token in dict.fromkeys(wanted.values())
        ]
        chunk = data._MULTIQUOTE_MAX_PER_REQUEST
        for start in range(0, len(instruments), chunk):
            quotes.update(data._fetch_ltp(instruments[start : start + chunk]))
    except Exception as e:
        logger.warning(f"Could not fetch LTPs for the position/holding book: {e}")
        return rows

    for index, key in wanted.items():
        quote = quotes.get(key)
        if quote:
            rows[index]["ltp"] = quote["ltp"]
    return rows


def get_positions(auth):
    """Overall (carry-forward aware) positions, marked to the live price.

    The docs' endpoint block and its own curl sample disagree on the path; only
    `cumulative-positions` exists.
    """
    payload = _request("GET", "/oapi/v1/portfolio/cumulative-positions", auth)
    try:
        _enrich_with_ltp(auth, _position_rows(payload))
    except Exception as e:
        logger.warning(f"Position LTP enrichment failed: {e}")
    return payload


def get_holdings(auth):
    payload = _request("GET", "/oapi/v1/portfolio/holdings", auth)
    try:
        rows = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(rows, list):
            _enrich_with_ltp(auth, rows)
    except Exception as e:
        logger.warning(f"Holdings LTP enrichment failed: {e}")
    return payload


# --- Per-Symbol Smart Order Lock ---
# Mirrors the Zerodha adapter: only one smart order per symbol executes at a
# time; others queue and each gets a fresh position book.
_symbol_locks = {}
_symbol_locks_lock = threading.Lock()

# --- Position Book Cache (1s TTL) ---
_position_cache = {}
_position_cache_lock = threading.Lock()
_POSITION_CACHE_TTL = 1.0


def _get_symbol_lock(symbol, exchange, product):
    key = f"{symbol}:{exchange}:{product}"
    with _symbol_locks_lock:
        if key not in _symbol_locks:
            _symbol_locks[key] = threading.Lock()
        return _symbol_locks[key]


def _get_cached_positions(auth):
    with _position_cache_lock:
        cached = _position_cache.get(auth)
        if cached and (time.monotonic() - cached["timestamp"]) < _POSITION_CACHE_TTL:
            logger.debug("Position book served from cache")
            return cached["data"]

    positions_data = get_positions(auth)

    with _position_cache_lock:
        _position_cache[auth] = {"data": positions_data, "timestamp": time.monotonic()}
    return positions_data


def _invalidate_position_cache(auth):
    with _position_cache_lock:
        _position_cache.pop(auth, None)


def _position_rows(positions_data):
    """InvestRight nests positions under data.net, not as a bare list."""
    if not positions_data:
        return []
    data = positions_data.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get("net")
        if isinstance(rows, list):
            return rows
        return next((v for v in data.values() if isinstance(v, list)), [])
    return []


def _position_symbol(position):
    """(OpenAlgo exchange, OpenAlgo symbol) for a raw position row."""
    from broker.hdfcsecurities.mapping.order_data import _oa_symbol

    exchange = to_oa_exchange(position.get("exchange"), position.get("instrument_segment"))
    return exchange, _oa_symbol(position, exchange)


def get_open_position(tradingsymbol, exchange, product, auth):
    """Net quantity (as str) for a symbol/exchange/product.

    `product` arrives as the InvestRight product code (DELIVERY / OVERNIGHT /
    INTRADAY), mapped by the smart-order flow via map_product_type().
    """
    net_qty = "0"

    for position in _position_rows(_get_cached_positions(auth)):
        position_exchange, position_symbol = _position_symbol(position)
        if (
            position_symbol == tradingsymbol
            and position_exchange == exchange
            and str(position.get("product", "")).upper() == str(product).upper()
        ):
            net_qty = str(position.get("net_qty", "0"))
            logger.debug(f"Net Quantity {net_qty}")
            break

    return net_qty


def place_order_api(data, auth):
    """Place a regular order.

    Returns (response, response_data, orderid). `response.status` is set so the
    service layer's `res.status == 200` success check works.
    """
    payload = transform_data(data)
    logger.info(f"Payload for HDFC Securities place_order_api: {payload}")

    client = get_httpx_client()
    response = client.post(
        f"{get_root_url()}/oapi/v1/orders/regular",
        headers=get_hdfcsecurities_headers(auth, with_json=True),
        params=base_params(),
        json=payload,
        timeout=30,
    )
    logger.info(
        f"HDFC Securities raw response: status={response.status_code}, body={response.text}"
    )

    try:
        response_data = response.json()
    except ValueError:
        response_data = {
            "status": "error",
            "message": f"Non-JSON response (HTTP {response.status_code}): {response.text[:200]}",
        }

    if response_data.get("status") == "success":
        orderid = (response_data.get("data") or {}).get("order_id")
    else:
        orderid = None
        # InvestRight can return an error payload with HTTP 200; make sure the
        # service layer's `status == 200` check does not read that as success.
        if response.status_code == 200:
            response.status_code = 400

    # Backward-compat: services check `res.status == 200`.
    response.status = response.status_code
    return response, response_data, orderid


def place_smartorder_api(data, auth):
    """Reconcile the live position to data['position_size'] and place the
    difference order. Same algorithm as the Zerodha reference."""
    from broker.hdfcsecurities.mapping.transform_data import map_product_type

    res = None
    response_data = {"status": "error", "message": "No action required or invalid parameters"}
    orderid = None

    try:
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        product = data.get("product")

        if not all([symbol, exchange, product]):
            logger.debug("Missing required parameters in place_smartorder_api")
            return res, response_data, orderid

        with _get_symbol_lock(symbol, exchange, product):
            position_size = int(data.get("position_size", "0"))
            current_position = int(
                float(
                    get_open_position(symbol, exchange, map_product_type(product, exchange), auth)
                    or 0
                )
            )

            logger.debug(f"position_size: {position_size}")
            logger.debug(f"Open Position: {current_position}")

            action = None
            quantity = 0

            if position_size == 0 and current_position == 0:
                action = data.get("action", "BUY").upper()
                quantity = int(data.get("quantity", "0"))
            elif position_size == 0 and current_position > 0:
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

            if action and quantity > 0:
                order_data = data.copy()
                order_data["action"] = action
                order_data["quantity"] = str(quantity)

                res, response, orderid = place_order_api(order_data, auth)
                _invalidate_position_cache(auth)
                return res, response, orderid

            logger.debug("No action required or invalid quantity")
            response_data = {
                "status": "success",
                "message": "No action needed. Position already matched.",
            }
            return res, response_data, orderid

    except Exception as e:
        error_msg = f"Error in place_smartorder_api: {e}"
        logger.exception(error_msg)
        return res, {"status": "error", "message": error_msg}, orderid


def close_all_positions(current_api_key, auth):
    """Square off every open position with market orders.

    Every square-off is checked. A rejected or unresolvable leg leaves real
    open exposure behind, so it must never be reported as closed: any failure
    returns a non-200 status, which is what close_position_service turns into
    an error response for the caller.
    """
    positions = _position_rows(get_positions(auth))
    if not positions:
        return {"message": "No Open Positions Found"}, 200

    closed = []
    failed = []
    for position in positions:
        net_qty = int(float(position.get("net_qty", 0) or 0))
        if net_qty == 0:
            continue

        exchange, symbol = _position_symbol(position)
        if not symbol:
            security_id = position.get("security_id")
            logger.warning(f"Skipping unresolvable position: {security_id}")
            failed.append(f"{exchange}:{security_id} (symbol not resolvable)")
            continue

        payload = {
            "apikey": current_api_key,
            "strategy": "Squareoff",
            "symbol": symbol,
            "action": "SELL" if net_qty > 0 else "BUY",
            "exchange": exchange,
            "pricetype": "MARKET",
            "product": reverse_map_product_type(exchange, position.get("product")) or "MIS",
            "quantity": str(abs(net_qty)),
        }
        logger.debug(f"Close position payload: {payload}")
        try:
            response, api_response, orderid = place_order_api(payload, auth)
            logger.debug(f"Close position response: {api_response}")
            # place_order_api rewrites the status code when InvestRight returns
            # an error payload under HTTP 200, so both checks are meaningful.
            if getattr(response, "status_code", 0) == 200 and orderid:
                closed.append(f"{exchange}:{symbol}")
            else:
                reason = (api_response or {}).get("message") or "order rejected"
                logger.error(f"Square-off rejected for {exchange}:{symbol}: {reason}")
                failed.append(f"{exchange}:{symbol} ({reason})")
        except Exception as e:
            logger.exception(f"Error squaring off {exchange}:{symbol}: {e}")
            failed.append(f"{exchange}:{symbol} ({e})")

    _invalidate_position_cache(auth)

    if failed:
        message = (
            f"Squared off {len(closed)} of {len(closed) + len(failed)} positions. "
            f"Still open: {'; '.join(failed)}"
        )
        logger.error(message)
        return {"status": "error", "message": message}, 500

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """Cancel an order via DELETE /oapi/v1/orders/regular/<order_id>."""
    try:
        response_data = _request("DELETE", f"/oapi/v1/orders/regular/{orderid}", auth)
        logger.debug(f"HDFC Securities cancel order response: {response_data}")

        if response_data.get("status") == "success":
            returned = (response_data.get("data") or {}).get("order_id", orderid)
            return {"status": "success", "orderid": str(returned)}, 200
        return {
            "status": "error",
            "message": response_data.get("message", "Failed to cancel order"),
        }, 400
    except Exception as e:
        logger.exception(f"Error canceling order {orderid}: {e}")
        return {"status": "error", "message": f"Failed to cancel order: {e}"}, 500


def modify_order(data, auth):
    """Modify an order via PUT /oapi/v1/orders/regular/<order_id>."""
    try:
        payload = transform_modify_order_data(data)
        orderid = data["orderid"]
        logger.debug(f"HDFC Securities modify order payload: {payload}")

        response_data = _request("PUT", f"/oapi/v1/orders/regular/{orderid}", auth, payload=payload)
        logger.debug(f"HDFC Securities modify order response: {response_data}")

        if response_data.get("status") == "success":
            returned = (response_data.get("data") or {}).get("order_id", orderid)
            return {"status": "success", "orderid": str(returned)}, 200
        return {
            "status": "error",
            "message": response_data.get("message", "Failed to modify order"),
        }, 400
    except Exception as e:
        logger.exception(f"Error modifying order {data.get('orderid')}: {e}")
        return {"status": "error", "message": f"Failed to modify order: {e}"}, 500


def cancel_all_orders_api(data, auth):
    """Cancel every open / trigger-pending order."""
    try:
        payload = get_order_book(auth)
    except Exception as e:
        logger.exception(f"Error fetching HDFC Securities order book for cancel-all: {e}")
        return [], []

    if payload.get("status") == "error":
        logger.error(f"HDFC Securities order book error: {payload.get('message')}")
        return [], []

    orders = payload.get("data") or []
    if not isinstance(orders, list):
        logger.error(f"Unexpected HDFC Securities order book shape: {type(orders)}")
        return [], []

    canceled_orders = []
    failed_cancellations = []
    for order in orders:
        if not is_cancellable(order):
            continue
        orderid = order.get("order_id")
        _, status_code = cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
