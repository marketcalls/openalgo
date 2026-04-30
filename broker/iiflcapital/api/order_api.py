from types import SimpleNamespace
from typing import Any

from broker.iiflcapital.baseurl import BASE_URL
from broker.iiflcapital.mapping.transform_data import (
    map_exchange,
    map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_br_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

_DIRECT_ORDER_KEYS = {"instrumentId", "exchange", "transactionType", "quantity"}
_SUCCESS_STATUSES = {"success", "ok"}

_OPEN_STATUSES = {
    "OPEN",
    "PENDING",
    "TRIGGER_PENDING",
    "PARTIALLY_FILLED",
    "NEW",
    "PUT ORDER REQ RECEIVED",
}


def _log_rejected_orders(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        if str(row.get("orderStatus", "")).upper() != "REJECTED":
            continue

        broker_order_id = row.get("brokerOrderId") or row.get("exchangeOrderId") or "unknown"
        symbol = row.get("tradingSymbol") or row.get("formattedInstrumentName") or "unknown"
        rejection_reason = row.get("rejectionReason") or "No rejection reason provided by broker"
        logger.warning(
            "IIFL Capital rejected order %s for %s: %s",
            broker_order_id,
            symbol,
            rejection_reason,
        )


def _headers(auth: str) -> dict:
    return {
        "Authorization": f"Bearer {auth}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request(endpoint: str, auth: str, method: str = "GET", payload=None, params=None):
    client = get_httpx_client()
    url = f"{BASE_URL}{endpoint}"

    if method == "GET":
        response = client.get(url, headers=_headers(auth), params=params)
    elif method == "POST":
        response = client.post(url, headers=_headers(auth), json=payload)
    elif method == "PUT":
        response = client.put(url, headers=_headers(auth), json=payload)
    elif method == "DELETE":
        response = client.delete(url, headers=_headers(auth), params=params)
    else:
        response = client.request(method, url, headers=_headers(auth), json=payload, params=params)

    try:
        data = response.json()
    except Exception:
        data = {"status": "error", "message": response.text}

    return response, data


def _extract_rows(payload):
    if isinstance(payload, list):
        return payload

    if not isinstance(payload, dict):
        return []

    result = payload.get("result")
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("orders", "trades", "positions", "holdings", "data", "positionList"):
            value = result.get(key)
            if isinstance(value, list):
                return value
        return [result]

    for key in ("data", "orders", "trades", "positions", "holdings"):
        value = payload.get(key)
        if isinstance(value, list):
            return value

    return []


def _ok(payload: dict) -> bool:
    status = str(payload.get("status", "")).lower()
    if status in _SUCCESS_STATUSES:
        return True

    result = payload.get("result")
    if isinstance(result, dict):
        nested_status = str(result.get("status", "")).lower()
        if nested_status in _SUCCESS_STATUSES:
            return True
    if isinstance(result, list) and result:
        nested_status = str(result[0].get("status", "")).lower()
        if nested_status in _SUCCESS_STATUSES:
            return True

    return False


def _status_wrapper(status_code: int):
    return SimpleNamespace(status=status_code)


def _first_result(payload: Any) -> dict:
    result = payload.get("result") if isinstance(payload, dict) else None
    if isinstance(result, list) and result:
        return result[0] if isinstance(result[0], dict) else {}
    if isinstance(result, dict):
        return result
    return {}


def _is_direct_order_payload(data: Any) -> bool:
    if isinstance(data, list):
        return bool(data) and all(isinstance(item, dict) and _DIRECT_ORDER_KEYS.issubset(item) for item in data)
    return isinstance(data, dict) and _DIRECT_ORDER_KEYS.issubset(data)


def _extract_message(payload: Any, default: str) -> str:
    if isinstance(payload, dict):
        for key in ("message", "error", "description"):
            value = payload.get(key)
            if value not in (None, ""):
                return str(value)

        result = payload.get("result")
        if isinstance(result, list) and result and isinstance(result[0], dict):
            for key in ("message", "error", "description"):
                value = result[0].get(key)
                if value not in (None, ""):
                    return str(value)
        elif isinstance(result, dict):
            for key in ("message", "error", "description"):
                value = result.get(key)
                if value not in (None, ""):
                    return str(value)

    return default


def _is_success_result(result: dict) -> bool:
    if not isinstance(result, dict):
        return False

    status = str(result.get("status", "")).lower()
    broker_order_id = result.get("brokerOrderId")
    return status in _SUCCESS_STATUSES and bool(broker_order_id)


def get_order_book(auth):
    response, data = _request("/orders", auth)

    if response.status_code == 200:
        rows = data if isinstance(data, list) else _extract_rows(data)
        if rows:
            _log_rejected_orders(rows)
        if isinstance(data, list):
            return data
        if rows or _ok(data):
            return data

    return {
        "status": "error",
        "message": _extract_message(data, "Failed to fetch order book"),
    }


def get_trade_book(auth):
    response, data = _request("/trades", auth)

    if response.status_code == 200:
        if isinstance(data, list):
            return data
        if _extract_rows(data) or _ok(data):
            return data

    return {
        "status": "error",
        "message": _extract_message(data, "Failed to fetch trade book"),
    }


def get_positions(auth):
    _, data = _request("/positions", auth)
    return data


def get_holdings(auth):
    _, data = _request("/holdings", auth)
    return data


def get_open_position(tradingsymbol, exchange, producttype, auth):
    positions_data = get_positions(auth)
    rows = _extract_rows(positions_data)

    br_symbol = get_br_symbol(tradingsymbol, exchange) or tradingsymbol
    broker_exchange = map_exchange(exchange)
    broker_product = map_product_type(producttype)

    for row in rows:
        row_symbol = row.get("tradingSymbol") or row.get("symbol")
        row_exchange = row.get("exchange")
        row_product = row.get("product")

        symbol_matches = row_symbol in (br_symbol, tradingsymbol)
        exchange_matches = row_exchange in (broker_exchange, None, "")
        product_matches = row_product in (broker_product, None, "")

        if symbol_matches and exchange_matches and product_matches:
            quantity = row.get("netQuantity", row.get("quantity", 0))
            return str(quantity)

    return "0"


def place_order_api(data, auth):
    if _is_direct_order_payload(data):
        order_payload = data
    elif isinstance(data, dict):
        token = get_token(data.get("symbol"), data.get("exchange"))
        if not token:
            wrapper = _status_wrapper(400)
            return wrapper, {"status": "error", "message": "Symbol token not found"}, None
        order_payload = transform_data(data, token)
    else:
        wrapper = _status_wrapper(400)
        return wrapper, {"status": "error", "message": "Invalid order payload"}, None

    payload = order_payload if isinstance(order_payload, list) else [order_payload]
    logger.debug(f"IIFL Capital place order payload: {payload}")
    response, response_data = _request("/orders", auth, method="POST", payload=payload)
    logger.info(f"IIFL Capital place order response status: {response.status_code}")
    logger.info(f"IIFL Capital place order raw response: {response_data}")

    result = _first_result(response_data)
    order_id = result.get("brokerOrderId")

    if response.status_code == 200 and _ok(response_data) and _is_success_result(result):
        return _status_wrapper(200), response_data, order_id

    error_status = response.status_code if response.status_code != 200 else 400
    error_message = _extract_message(response_data, "Failed to place order")
    logger.warning(f"IIFL Capital place order failed: {error_message}")
    error_response = {
        "status": "error",
        "message": error_message,
    }
    return _status_wrapper(error_status), error_response, None


def place_smartorder_api(data, auth):
    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")

    position_size = int(float(data.get("position_size", 0) or 0))
    current_position = int(float(get_open_position(symbol, exchange, product, auth) or 0))

    if position_size == current_position:
        if int(float(data.get("quantity", 0) or 0)) == 0:
            message = "No OpenPosition Found. Not placing Exit order."
        else:
            message = "No action needed. Position size matches current position"
        return None, {"status": "success", "message": message}, None

    action = None
    quantity = 0

    if position_size == 0 and current_position > 0:
        action = "SELL"
        quantity = abs(current_position)
    elif position_size == 0 and current_position < 0:
        action = "BUY"
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

    if not action or quantity <= 0:
        return None, {"status": "success", "message": "No action needed. Position already aligned"}, None

    order_data = data.copy()
    order_data["action"] = action
    order_data["quantity"] = str(quantity)

    return place_order_api(order_data, auth)


def close_all_positions(current_api_key, auth):
    positions_response = get_positions(auth)
    rows = _extract_rows(positions_response)

    if not rows:
        return {"message": "No Open Positions Found"}, 200

    attempted = 0
    failures = 0

    for row in rows:
        net_qty = int(float(row.get("netQuantity", 0) or 0))
        if net_qty == 0:
            continue

        attempted += 1

        order_payload = {
            "instrumentId": str(row.get("instrumentId")),
            "exchange": row.get("exchange"),
            "transactionType": "SELL" if net_qty > 0 else "BUY",
            "quantity": str(abs(net_qty)),
            "orderComplexity": "REGULAR",
            "product": row.get("product", "NORMAL"),
            "orderType": "MARKET",
            "validity": "DAY",
            "apiOrderSource": "openalgo",
            "orderTag": "close_all_positions",
        }

        response, response_data, orderid = place_order_api(order_payload, auth)
        if response.status != 200 or not orderid:
            failures += 1

    if attempted == 0:
        return {"message": "No Open Positions Found"}, 200

    if failures:
        return {
            "status": "partial_success",
            "message": f"Closed positions attempted: {attempted}, failed: {failures}",
        }, 207

    return {"status": "success", "message": "All Open Positions Squared Off"}, 200


def cancel_order(orderid, auth):
    logger.debug(f"IIFL Capital cancel order request for {orderid}")
    response, response_data = _request(f"/orders/{orderid}", auth, method="DELETE")
    logger.debug(f"IIFL Capital cancel order response for {orderid}: {response_data}")

    if response.status_code == 200 and _ok(response_data):
        return {"status": "success", "orderid": str(orderid)}, 200

    return {
        "status": "error",
        "message": _extract_message(response_data, "Failed to cancel order"),
    }, response.status_code


def modify_order(data, auth):
    order_id = data.get("orderid")
    payload = transform_modify_order_data(data)

    logger.debug(f"IIFL Capital modify order payload for {order_id}: {payload}")
    response, response_data = _request(f"/orders/{order_id}", auth, method="PUT", payload=payload)
    logger.debug(f"IIFL Capital modify order response for {order_id}: {response_data}")

    if response.status_code == 200 and _ok(response_data):
        return {"status": "success", "orderid": str(order_id)}, 200

    return {
        "status": "error",
        "message": _extract_message(response_data, "Failed to modify order"),
    }, response.status_code


def cancel_all_orders_api(data, auth):
    order_book = get_order_book(auth)
    rows = _extract_rows(order_book)

    orders_to_cancel = []
    for row in rows:
        status = str(row.get("orderStatus", "")).upper()
        if status in _OPEN_STATUSES:
            broker_order_id = row.get("brokerOrderId")
            if broker_order_id:
                orders_to_cancel.append(broker_order_id)

    canceled_orders = []
    failed_cancellations = []

    for order_id in orders_to_cancel:
        cancel_response, status_code = cancel_order(order_id, auth)
        if status_code == 200:
            canceled_orders.append(order_id)
        else:
            failed_cancellations.append(order_id)
            logger.error(f"Failed to cancel order {order_id}: {cancel_response}")

    return canceled_orders, failed_cancellations
