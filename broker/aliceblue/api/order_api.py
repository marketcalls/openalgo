import json
import os

import httpx

from broker.aliceblue.mapping.order_data import (
    normalize_holding,
    normalize_order,
    normalize_position,
    normalize_trade,
)
from broker.aliceblue.mapping.transform_data import (
    map_product_type,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.token_db import get_br_symbol, get_oa_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


# AliceBlue V2 API base URL
BASE_URL = "https://a3.aliceblueonline.com"


# ─── API request helper ──────────────────────────────────────────────────────

def get_api_response(endpoint, auth, method="GET", payload=None):
    """Make API requests to AliceBlue V2 API using shared connection pooling."""
    try:
        client = get_httpx_client()
        url = f"{BASE_URL}{endpoint}"

        headers = {
            "Authorization": f"Bearer {auth}",
            "Content-Type": "application/json",
        }

        logger.debug(f"Making {method} request to AliceBlue API: {url}")

        if method.upper() == "GET":
            response = client.get(url, headers=headers)
        elif method.upper() == "POST":
            response = client.post(
                url,
                json=json.loads(payload) if isinstance(payload, str) and payload else payload,
                headers=headers,
            )
        elif method.upper() == "PUT":
            response = client.put(
                url,
                json=json.loads(payload) if isinstance(payload, str) and payload else payload,
                headers=headers,
            )
        elif method.upper() == "DELETE":
            response = client.delete(url, headers=headers)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        response_data = response.json()
        logger.debug(f"API response: {json.dumps(response_data, indent=2)}")
        return response_data

    except httpx.HTTPError as e:
        logger.error(f"HTTP error during API request: {str(e)}")
        return {"status": "Error", "message": f"HTTP error: {str(e)}"}
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {str(e)}")
        return {"status": "Error", "message": f"Invalid JSON response: {str(e)}"}
    except Exception as e:
        logger.error(f"Error during API request: {str(e)}")
        return {"status": "Error", "message": f"General error: {str(e)}"}


def _extract_result(response_data):
    """Extract result list from V2 API response, handling errors."""
    if isinstance(response_data, dict):
        if response_data.get("status") == "Ok":
            return response_data.get("result", [])
        else:
            msg = response_data.get("message", "Unknown error")
            logger.error(f"API error: {msg}")
            return None
    return response_data  # fallback: return as-is if not a dict


# ─── Order book / Trade book / Positions / Holdings ──────────────────────────

def get_order_book(auth):
    """Fetch order book from V2 API and normalize to old field names."""
    response = get_api_response("/open-api/od/v1/orders/book", auth)
    result = _extract_result(response)

    if result is None:
        # V2 API returns error message when there are no orders
        # Treat "Failed to retrieve" as empty, not an error
        msg = response.get("message", "")
        if "Failed to retrieve" in msg or "No orders" in msg.lower():
            logger.info(f"No orders found: {msg}")
            return []
        return {"stat": "Not_Ok", "emsg": msg or "Failed to fetch order book"}

    if not result:
        return []

    # Normalize each order to old field names
    return [normalize_order(order) for order in result]


def get_trade_book(auth):
    """Fetch trade book from V2 API and normalize to old field names."""
    response = get_api_response("/open-api/od/v1/orders/trades", auth)
    result = _extract_result(response)

    logger.info(f"AliceBlue tradebook API response type: {type(response)}")

    if result is None:
        # V2 API returns error message when there are no trades
        # Treat "No trades found" as empty, not an error
        msg = response.get("message", "")
        if "No trades" in msg or "not found" in msg.lower():
            logger.info(f"No trades found: {msg}")
            return []
        return {"stat": "Not_Ok", "emsg": msg or "Failed to fetch trade book"}

    if not result:
        return []

    # Normalize each trade to old field names
    return [normalize_trade(trade) for trade in result]


def get_positions(auth):
    """Fetch positions from V2 API and normalize to old field names."""
    response = get_api_response("/open-api/od/v1/positions", auth)
    result = _extract_result(response)

    if result is None:
        # V2 API returns error message when there are no positions
        msg = response.get("message", "")
        if "No position" in msg or "not found" in msg.lower() or "Failed to retrieve" in msg:
            logger.info(f"No positions found: {msg}")
            return []
        return {"stat": "Not_Ok", "emsg": msg or "Failed to fetch positions"}

    if not result:
        return []

    # Normalize each position to old field names
    return [normalize_position(pos) for pos in result]


def get_holdings(auth):
    """Fetch holdings from V2 API and normalize to old field names."""
    response = get_api_response("/open-api/od/v1/holdings/CNC", auth)
    result = _extract_result(response)

    if result is None:
        # V2 API returns error message when there are no holdings
        msg = response.get("message", "")
        if "No holding" in msg or "not found" in msg.lower() or "Failed to retrieve" in msg:
            logger.info(f"No holdings found: {msg}")
            return []
        return {"stat": "Not_Ok", "emsg": msg or "Failed to fetch holdings"}

    if not result:
        return []

    return [normalize_holding(h) for h in result]


# ─── Open position lookup ────────────────────────────────────────────────────

def get_open_position(tradingsymbol, exchange, product, auth):
    """Get net quantity for a specific symbol/exchange/product."""
    # Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)

    position_data = get_positions(auth)

    if isinstance(position_data, dict):
        if position_data.get("stat") == "Not_Ok":
            logger.info(f"Error fetching position data: {position_data.get('emsg')}")
            position_data = {}

    net_qty = "0"

    if position_data:
        for position in position_data:
            if (
                position.get("Tsym") == tradingsymbol
                and position.get("Exchange") == exchange
                and position.get("Pcode") == product
            ):
                net_qty = position.get("Netqty", "0")
                logger.info(f"Net Quantity {net_qty}")
                break

    return net_qty


# ─── Place order ──────────────────────────────────────────────────────────────

def place_order_api(data, auth):
    """Place an order using the AliceBlue V2 API."""
    try:
        client = get_httpx_client()

        # Build V2 API payload via transform_data
        payload_item = transform_data(data)
        payload = [payload_item]

        headers = {
            "Authorization": f"Bearer {auth}",
            "Content-Type": "application/json",
        }

        logger.debug(f"Place order payload: {json.dumps(payload, indent=2)}")

        url = f"{BASE_URL}/open-api/od/v1/orders/placeorder"
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()

        response_data = response.json()
        logger.debug(f"Place order response: {json.dumps(response_data, indent=2)}")

        # Process the V2 API response
        orderid = None
        if response_data.get("status") == "Ok":
            results = response_data.get("result", [])
            if results and len(results) > 0:
                result_item = results[0]
                # Check for per-result error (AliceBlue may return top-level Ok but result-level error)
                result_status = result_item.get("status", "")
                if result_status and result_status != "Ok" and result_item.get("brokerOrderId", "") == "":
                    error_msg = result_item.get("message", "Unknown error in result")
                    logger.error(f"Order placement failed (result error {result_status}): {error_msg}")
                else:
                    orderid = result_item.get("brokerOrderId")
                    logger.info(f"Order placed successfully: {orderid}")
        else:
            error_msg = response_data.get("message", "No error message provided by API")
            logger.error(f"Order placement failed: {error_msg}")

        # Add status attribute for compatibility
        response.status = response.status_code

        return response, response_data, orderid

    except httpx.HTTPError as e:
        logger.error(f"HTTP error during place order: {str(e)}")
        response_data = {"status": "Error", "message": f"HTTP error: {str(e)}"}
        response = type("", (), {"status": 500, "status_code": 500})()
        return response, response_data, None
    except Exception as e:
        logger.error(f"Error during place order: {str(e)}")
        response_data = {"status": "Error", "message": f"General error: {str(e)}"}
        response = type("", (), {"status": 500, "status_code": 500})()
        return response, response_data, None


# ─── Smart order ──────────────────────────────────────────────────────────────

def place_smartorder_api(data, auth):
    AUTH_TOKEN = auth

    # If no API call is made in this function then res will return None
    res = None

    # Extract necessary info from data
    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")
    position_size = int(data.get("position_size", "0"))

    # Get current open position for the symbol
    current_position = int(
        get_open_position(symbol, exchange, reverse_map_product_type(map_product_type(product)), AUTH_TOKEN)
    )

    logger.info(f"position_size : {position_size}")
    logger.info(f"Open Position : {current_position}")

    # Determine action based on position_size and current_position
    action = None
    quantity = 0

    # If both position_size and current_position are 0, do nothing
    if position_size == 0 and current_position == 0 and int(data["quantity"]) != 0:
        action = data["action"]
        quantity = data["quantity"]
        res, response, orderid = place_order_api(data, AUTH_TOKEN)
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
        return res, response, orderid

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

        return res, response, orderid


# ─── Close all positions ──────────────────────────────────────────────────────

def close_all_positions(current_api_key, auth):
    AUTH_TOKEN = auth
    # Fetch the current open positions
    positions_response = get_positions(AUTH_TOKEN)

    if isinstance(positions_response, dict):
        if positions_response.get("stat") == "Not_Ok":
            logger.info(f"Error fetching position data: {positions_response.get('emsg')}")
            positions_response = {}

    # Check if the positions data is null or empty
    if positions_response is None or not positions_response:
        return {"message": "No Open Positions Found"}, 200

    if positions_response:
        # Loop through each position to close
        for position in positions_response:
            # Skip if net quantity is zero
            if int(position["Netqty"]) == 0:
                continue

            # Determine action based on net quantity
            action = "SELL" if int(position["Netqty"]) > 0 else "BUY"
            quantity = abs(int(position["Netqty"]))

            # Get OA Symbol before sending to Place Order
            symbol = get_oa_symbol(position["Tsym"], position["Exchange"])
            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position["Exchange"],
                "pricetype": "MARKET",
                "product": position["Pcode"],
                "quantity": str(quantity),
            }

            logger.info(f"{place_order_payload}")

            # Place the order to close the position
            _, api_response, _ = place_order_api(place_order_payload, AUTH_TOKEN)

            logger.info(f"{api_response}")

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


# ─── Cancel order ─────────────────────────────────────────────────────────────

def cancel_order(orderid, auth):
    """Cancel an order using the AliceBlue V2 API."""
    try:
        client = get_httpx_client()

        headers = {
            "Authorization": f"Bearer {auth}",
            "Content-Type": "application/json",
        }

        # V2 API only needs brokerOrderId to cancel
        payload = {"brokerOrderId": str(orderid)}

        logger.debug(f"Cancel order payload: {json.dumps(payload, indent=2)}")

        url = f"{BASE_URL}/open-api/od/v1/orders/cancel"
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()

        response_data = response.json()
        logger.debug(f"Cancel order response: {json.dumps(response_data, indent=2)}")

        # Check V2 API response
        if response_data.get("status") == "Ok":
            results = response_data.get("result", [])
            cancelled_id = orderid
            if results and len(results) > 0:
                cancelled_id = results[0].get("brokerOrderId", orderid)
            return {"status": "success", "orderid": cancelled_id}, 200
        else:
            return {
                "status": "error",
                "message": response_data.get("message", "Failed to cancel order"),
            }, response.status_code

    except httpx.HTTPError as e:
        logger.error(f"HTTP error during cancel order: {str(e)}")
        return {"status": "error", "message": f"HTTP error: {str(e)}"}, 500
    except Exception as e:
        logger.error(f"Error during cancel order: {str(e)}")
        return {"status": "error", "message": f"General error: {str(e)}"}, 500


# ─── Modify order ─────────────────────────────────────────────────────────────

def modify_order(data, auth):
    """Modify an order using the AliceBlue V2 API."""
    try:
        client = get_httpx_client()

        # Build V2 API modify payload via transform_modify_order_data
        payload = transform_modify_order_data(data)

        headers = {
            "Authorization": f"Bearer {auth}",
            "Content-Type": "application/json",
        }

        logger.debug(f"Modify order payload: {json.dumps(payload, indent=2)}")

        url = f"{BASE_URL}/open-api/od/v1/orders/modify"
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()

        response_data = response.json()
        logger.debug(f"Modify order response: {json.dumps(response_data, indent=2)}")

        # Process V2 API response
        if response_data.get("status") == "Ok":
            results = response_data.get("result", [])
            modified_id = data.get("orderid")
            if results and len(results) > 0:
                modified_id = results[0].get("brokerOrderId", modified_id)
            return {"status": "success", "orderid": modified_id}, 200
        else:
            return {
                "status": "error",
                "message": response_data.get("message", "Failed to modify order"),
            }, response.status_code

    except httpx.HTTPError as e:
        logger.error(f"HTTP error during modify order: {str(e)}")
        return {"status": "error", "message": f"HTTP error: {str(e)}"}, 500
    except Exception as e:
        logger.error(f"Error during modify order: {str(e)}")
        return {"status": "error", "message": f"General error: {str(e)}"}, 500


# ─── Cancel all orders ────────────────────────────────────────────────────────

def cancel_all_orders_api(data, auth):
    AUTH_TOKEN = auth
    # Get the order book (already normalized to old field names)
    order_book_response = get_order_book(AUTH_TOKEN)

    if isinstance(order_book_response, dict):
        if order_book_response.get("stat") == "Not_Ok":
            return [], []

    # Filter orders that are in 'open' or 'trigger pending' state
    orders_to_cancel = [
        order for order in order_book_response if order.get("Status") in ["open", "trigger pending"]
    ]
    logger.info(f"{orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order["Nstordno"]
        cancel_response, status_code = cancel_order(orderid, AUTH_TOKEN)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
