import json
import os

import httpx

from broker.mstock.mapping.transform_data import (
    get_mstock_symbol,
    map_product_type,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.auth_db import get_auth_token
from database.token_db import get_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="GET", payload=""):
    """
    Generic API request handler for mStock Type B APIs.

    Args:
        endpoint: API endpoint path
        auth: Authentication token
        method: HTTP method (GET, POST, PUT, DELETE)
        payload: Request payload

    Returns:
        dict: JSON response from API
    """
    auth_token = auth
    api_key = os.getenv("BROKER_API_SECRET")

    client = get_httpx_client()

    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {auth_token}",
        "X-PrivateKey": api_key,
        "Content-Type": "application/json",
    }

    url = f"https://api.mstock.trade/openapi/typeb{endpoint}"

    if method == "GET":
        response = client.get(url, headers=headers)
    elif method == "POST":
        response = client.post(url, headers=headers, content=payload)
    else:
        response = client.request(method, url, headers=headers, content=payload)

    # Add status attribute for compatibility with existing codebase
    response.status = response.status_code

    # Handle empty response
    if not response.text:
        return {}

    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from {endpoint}: {response.text}")
        return {}


def get_order_book(auth):
    """Fetch the order book from mStock Type B API."""
    return get_api_response("/orders", auth)


def get_trade_book(auth):
    """Fetch the trade book from mStock Type B API."""
    return get_api_response("/tradebook", auth)


def get_positions(auth):
    """Fetch positions from mStock Type B API."""
    return get_api_response("/portfolio/positions", auth)


def get_holdings(auth):
    """Fetch holdings from mStock Type B API."""
    return get_api_response("/portfolio/holdings", auth)


def get_open_position(tradingsymbol, exchange, producttype, auth):
    """
    Get open position for a specific symbol and product type.

    Args:
        tradingsymbol: OpenAlgo format symbol
        exchange: Exchange name
        producttype: Product type (mapped to broker format)
        auth: Authentication token

    Returns:
        str: Net quantity as string
    """
    # Get symboltoken for the tradingsymbol
    token = get_token(tradingsymbol, exchange)
    if not token:
        logger.warning(f"Token not found for {tradingsymbol} on {exchange}")
        return "0"

    positions_data = get_positions(auth)

    logger.info(
        f"Looking for position: symboltoken={token}, exchange={exchange}, producttype={producttype}"
    )
    logger.info(f"Positions data: {positions_data}")

    net_qty = "0"

    if positions_data and positions_data.get("status") and positions_data.get("data"):
        for position in positions_data["data"]:
            # Match using symboltoken instead of tradingsymbol (which is empty in mStock API)
            if (
                position.get("symboltoken") == token
                and position.get("exchange") == exchange
                and position.get("producttype") == producttype
            ):
                net_qty = position.get("netqty", "0")
                logger.info(f"Found matching position: netqty={net_qty}")
                break

    return net_qty


def place_order_api(data, auth):
    """
    Place a regular order on mStock Type B API.

    Args:
        data: OpenAlgo order data
        auth: Authentication token

    Returns:
        tuple: (response, response_data, orderid)
    """
    auth_token = auth
    api_key = os.getenv("BROKER_API_SECRET")

    # Get token and transform data
    token = get_token(data["symbol"], data["exchange"])
    transformed_data = transform_data(data, token)

    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {auth_token}",
        "X-PrivateKey": api_key,
        "Content-Type": "application/json",
    }

    payload = json.dumps(transformed_data)
    logger.info(f"Place order payload: {payload}")

    client = get_httpx_client()

    response = client.post(
        "https://api.mstock.trade/openapi/typeb/orders/regular", headers=headers, content=payload
    )

    # Add status attribute for compatibility
    response.status = response.status_code

    # Parse JSON response
    response_data = response.json()

    logger.debug(f"Place order response status code: {response.status_code}")
    logger.debug(f"Place order response data type: {type(response_data)}")
    logger.debug(f"Place order response data: {response_data}")

    # Handle both dict and list responses
    orderid = None

    # mStock Type B API returns a list with single dict element
    if isinstance(response_data, list) and len(response_data) > 0:
        logger.info("API returned list, extracting first element")
        response_dict = response_data[0]

        # Extract orderid from the dict
        if response_dict.get("status") in [True, "true"] and response_dict.get("data"):
            orderid = response_dict["data"].get("orderid")
            logger.debug(f"Extracted orderid: {orderid}")

        # Keep the dict format for response_data for compatibility
        response_data = response_dict

    elif isinstance(response_data, dict):
        # Standard dict response format
        if response_data.get("status") in [True, "true"] and response_data.get("data"):
            orderid = response_data["data"].get("orderid")
            logger.debug(f"Extracted orderid: {orderid}")

    return response, response_data, orderid


def place_smartorder_api(data, auth):
    """
    Place a smart order that adjusts based on current position.

    Args:
        data: OpenAlgo order data with position_size
        auth: Authentication token

    Returns:
        tuple: (response, response_data, orderid)
    """
    auth_token = auth
    res = None

    # Extract necessary info from data
    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")
    position_size = int(data.get("position_size", "0"))

    # Get current open position for the symbol
    current_position = int(
        get_open_position(symbol, exchange, map_product_type(product), auth_token)
    )

    logger.info(f"position_size: {position_size}")
    logger.info(f"Open Position: {current_position}")

    action = None
    quantity = 0

    # If both position_size and current_position are 0, do nothing
    if position_size == 0 and current_position == 0 and int(data["quantity"]) != 0:
        action = data["action"]
        quantity = data["quantity"]
        res, response, orderid = place_order_api(data, auth_token)
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
        res, response, orderid = place_order_api(order_data, auth)
        logger.debug(f"Smart order response: {response}")
        logger.debug(f"Smart order ID: {orderid}")

        return res, response, orderid


def close_all_positions(current_api_key, auth):
    """
    Close all open positions.

    Args:
        current_api_key: API key
        auth: Authentication token

    Returns:
        tuple: (response_dict, status_code)
    """
    auth_token = auth

    positions_response = get_positions(auth_token)

    # Check if the positions data is null or empty
    if positions_response.get("data") is None or not positions_response.get("data"):
        logger.info("No open positions to close")
        return {"message": "No Open Positions Found"}, 200

    # Check status explicitly (mStock Type B returns "true" string or True boolean)
    if positions_response.get("status") in [True, "true"]:
        logger.info(f"Closing {len(positions_response['data'])} positions")

        # Loop through each position to close
        for position in positions_response["data"]:
            # Convert netqty to int (API returns string like "-500")
            try:
                netqty = int(position.get("netqty", 0))
            except (ValueError, TypeError):
                logger.warning(f"Invalid netqty for position: {position.get('symboltoken')}")
                continue

            # Skip if net quantity is zero
            if netqty == 0:
                continue

            # Determine action based on net quantity
            action = "SELL" if netqty > 0 else "BUY"
            quantity = abs(netqty)

            # Determine correct exchange for symbol lookup
            exchange = position["exchange"]
            instrumenttype = position.get("instrumenttype", "")
            lookup_exchange = exchange

            # For derivatives, use NFO/BFO instead of NSE/BSE for symbol lookup
            if instrumenttype in ["OPTIDX", "OPTSTK", "FUTIDX", "FUTSTK"]:
                if exchange == "NSE":
                    lookup_exchange = "NFO"
                elif exchange == "BSE":
                    lookup_exchange = "BFO"

            # Get OpenAlgo symbol to send to placeorder function
            symbol = get_symbol(position["symboltoken"], lookup_exchange)

            # Skip if symbol not found
            if not symbol:
                logger.warning(
                    f"Symbol not found for token {position['symboltoken']}, exchange {lookup_exchange} (original: {exchange}). Skipping position."
                )
                continue

            logger.info(
                f"Closing position for symbol: {symbol}, quantity: {quantity}, action: {action}"
            )

            # Prepare the order payload
            # Use lookup_exchange (NFO/BFO for derivatives) instead of position exchange (NSE/BSE)
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": lookup_exchange,  # Use NFO/BFO for derivatives, not NSE/BSE
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position["producttype"]),
                "quantity": str(quantity),
            }

            logger.info(f"Square off payload: {place_order_payload}")

            # Place the order to close the position
            try:
                res, response, orderid = place_order_api(place_order_payload, auth)
                logger.info(f"Position closed - OrderID: {orderid}, Response: {response}")
            except Exception as e:
                logger.error(f"Error closing position for {symbol}: {e}")
                continue

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """
    Cancel a pending order on mStock Type B API.

    Args:
        orderid: Order ID to cancel
        auth: Authentication token

    Returns:
        tuple: (response_dict, status_code)
    """
    auth_token = auth
    api_key = os.getenv("BROKER_API_SECRET")

    client = get_httpx_client()

    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {auth_token}",
        "X-PrivateKey": api_key,
        "Content-Type": "application/json",
    }

    # Prepare payload for Type B (variety and orderid in body)
    payload_data = {"variety": "NORMAL", "orderid": orderid}

    logger.info(f"Cancelling order {orderid}")
    logger.info(f"Cancel order payload: {json.dumps(payload_data)}")

    # DELETE request with orderid in both URL path and body
    # Using json parameter instead of content/data for httpx compatibility
    response = client.request(
        method="DELETE",
        url=f"https://api.mstock.trade/openapi/typeb/orders/regular/{orderid}",
        headers=headers,
        json=payload_data,
    )

    # Add status attribute for compatibility
    response.status = response.status_code

    logger.info(f"Cancel order response status code: {response.status_code}")
    logger.info(f"Cancel order response: {response.text}")

    try:
        data = json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse cancel order response: {response.text}")
        return {"status": "error", "message": "Invalid response from broker"}, 500

    # Handle list response (like place order)
    if isinstance(data, list) and len(data) > 0:
        logger.info("API returned list, extracting first element")
        data = data[0]

    # Check if the request was successful
    if data.get("status") in [True, "true"] or data.get("message") == "SUCCESS":
        logger.info(f"Order {orderid} cancelled successfully")
        return {"status": "success", "orderid": orderid}, 200
    else:
        error_message = data.get("message", "Failed to cancel order")
        logger.error(f"Failed to cancel order {orderid}: {error_message}")
        return {"status": "error", "message": error_message}, response.status


def modify_order(data, auth):
    """
    Modify an existing order on mStock Type B API.

    Args:
        data: OpenAlgo modify order data with fields:
            - orderid: Order ID to modify
            - symbol: OpenAlgo symbol
            - exchange: Exchange code
            - action: BUY/SELL
            - quantity: Order quantity
            - price: Order price
            - trigger_price: Trigger price (for SL orders)
            - pricetype: MARKET/LIMIT/SL/SL-M
            - product: CNC/MIS/NRML
        auth: Authentication token

    Returns:
        tuple: (response_dict, status_code)
    """
    auth_token = auth
    api_key = os.getenv("BROKER_API_SECRET")

    client = get_httpx_client()

    # Get token for the symbol
    try:
        token = get_token(data["symbol"], data["exchange"])
        if not token:
            logger.error(
                f"Token not found for symbol {data['symbol']}, exchange {data['exchange']}"
            )
            return {"status": "error", "message": "Symbol token not found in database"}, 400
    except Exception as e:
        logger.error(f"Error getting token: {e}")
        return {"status": "error", "message": f"Failed to get symbol token: {str(e)}"}, 400

    # Transform data to mStock Type B format
    transformed_data = transform_modify_order_data(data, token)

    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {auth_token}",
        "X-PrivateKey": api_key,
        "Content-Type": "application/json",
    }

    orderid = data["orderid"]

    logger.info(f"Modifying order {orderid} for symbol {data['symbol']}")
    logger.info(f"Modify order payload: {json.dumps(transformed_data)}")

    # PUT request with orderid in URL path
    # Using json parameter for httpx compatibility
    response = client.request(
        method="PUT",
        url=f"https://api.mstock.trade/openapi/typeb/orders/regular/{orderid}",
        headers=headers,
        json=transformed_data,
    )

    # Add status attribute for compatibility
    response.status = response.status_code

    logger.info(f"Modify order response status code: {response.status_code}")
    logger.info(f"Modify order response: {response.text}")

    try:
        response_data = json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse modify order response: {response.text}")
        return {"status": "error", "message": "Invalid response from broker"}, 500

    # Handle list response (like place order/cancel order)
    if isinstance(response_data, list) and len(response_data) > 0:
        logger.info("API returned list, extracting first element")
        response_data = response_data[0]

    # Check if the request was successful
    # mStock Type B returns status as boolean True or string "true"
    if response_data.get("status") in [True, "true"] or response_data.get("message") == "SUCCESS":
        # Extract orderid from response data
        if response_data.get("data") and isinstance(response_data["data"], dict):
            modified_orderid = response_data["data"].get("orderid", orderid).strip()
        else:
            modified_orderid = orderid

        logger.info(f"Order {orderid} modified successfully to {modified_orderid}")
        return {"status": "success", "orderid": modified_orderid}, 200
    else:
        error_message = response_data.get("message", "Failed to modify order")
        errorcode = response_data.get("errorcode", "")
        logger.error(f"Failed to modify order {orderid}: {error_message} (errorcode: {errorcode})")
        return {"status": "error", "message": error_message}, response.status


def cancel_all_orders_api(data, auth):
    """
    Cancel all pending orders using mStock Type B cancelall endpoint.

    Args:
        data: Request data (not used for mStock Type B)
        auth: Authentication token

    Returns:
        tuple: (canceled_orders_list, failed_cancellations_list)
    """
    auth_token = auth
    api_key = os.getenv("BROKER_API_SECRET")

    # First, get the list of pending orders to return their IDs
    logger.info("Fetching order book to identify pending orders")
    order_book_response = get_order_book(auth_token)

    pending_order_ids = []
    if order_book_response.get("status") in [True, "true"] and order_book_response.get("data"):
        # Filter orders that are in 'open', 'pending', 'o-pending' or 'trigger pending' state
        pending_orders = [
            order
            for order in order_book_response.get("data", [])
            if order.get("status", "").lower()
            in ["open", "pending", "o-pending", "trigger pending"]
        ]
        pending_order_ids = [
            order.get("orderid") for order in pending_orders if order.get("orderid")
        ]
        logger.info(f"Found {len(pending_order_ids)} pending orders to cancel: {pending_order_ids}")
    else:
        logger.warning("Failed to fetch order book or no data available")

    # If no pending orders, return early
    if not pending_order_ids:
        logger.info("No pending orders to cancel")
        return [], []

    # Now call the cancelall endpoint
    client = get_httpx_client()

    headers = {
        "X-Mirae-Version": "1",
        "Authorization": f"Bearer {auth_token}",
        "X-PrivateKey": api_key,
        "Content-Type": "application/json",
    }

    logger.info("Calling mStock Type B cancelall endpoint")

    # POST request to cancel all orders at once
    response = client.post(
        "https://api.mstock.trade/openapi/typeb/orders/cancelall", headers=headers
    )

    # Add status attribute for compatibility
    response.status = response.status_code

    logger.info(f"Cancel all response status code: {response.status_code}")
    logger.info(f"Cancel all response: {response.text}")

    try:
        response_data = json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse cancel all response: {response.text}")
        return [], pending_order_ids  # Return as failed

    # Handle list response (like place order)
    if isinstance(response_data, list) and len(response_data) > 0:
        logger.info("API returned list, extracting first element")
        response_data = response_data[0]

    # Check if the request was successful
    if (
        response_data.get("status") in [True, "true", "success"]
        or response_data.get("message") == "SUCCESS"
    ):
        logger.info(f"Cancel all orders successful - cancelled {len(pending_order_ids)} orders")
        return pending_order_ids, []
    else:
        error_message = response_data.get("message", "Failed to cancel all orders")
        logger.error(f"Cancel all failed: {error_message}")
        return [], pending_order_ids  # Return as failed
