import json
import os

import httpx

from broker.nubra.mapping.transform_data import (
    map_product_type,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Nubra API Base URL
NUBRA_BASE_URL = "https://api.nubra.io"


def get_api_response(endpoint, auth, method="GET", payload=""):
    AUTH_TOKEN = auth
    device_id = "OPENALGO"  # Fixed device ID, same as auth_api.py

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-device-id": device_id,
    }

    url = f"{NUBRA_BASE_URL}{endpoint}"

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
        return {}

    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from {endpoint}: {response.text}")
        return {}


def get_order_book(auth):
    """
    Fetch all orders for the day from Nubra API.
    
    Nubra API: GET /orders/v2
    Returns list of orders with their current status.
    """
    return get_api_response("/orders/v2", auth)


def get_trade_book(auth):
    """
    Fetch trade book from Nubra's API.
    
    Nubra doesn't have a separate tradebook endpoint.
    Trades are derived from the orders endpoint (filled orders).
    
    Nubra API: GET /orders/v2
    """
    return get_api_response("/orders/v2", auth)


def get_positions(auth):
    """
    Fetch positions from Nubra's API.
    
    Nubra API: GET /portfolio/positions
    Returns list of positions with fields like ref_id, ref_data, quantity, etc.
    """
    response = get_api_response("/portfolio/positions", auth)
    logger.info(f"Nubra Raw position book response: {response}")
    return response


def get_holdings(auth):
    """
    Fetch portfolio holdings from Nubra's API.
    
    Nubra API: GET /portfolio/holdings
    Returns portfolio with holdings list and holding_stats.
    Prices are in paise (divide by 100 for rupees).
    """
    return get_api_response("/portfolio/holdings", auth)


def get_open_position(tradingsymbol, exchange, producttype, auth):
    """
    Get the net quantity for a specific position.
    Uses Nubra's position data format with portfolio.stock_positions, fut_positions, opt_positions.
    """
    # Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    positions_data = get_positions(auth)

    logger.debug(f"Nubra positions data: {positions_data}")

    net_qty = "0"

    # Nubra returns positions in portfolio.stock_positions, portfolio.fut_positions, portfolio.opt_positions
    positions = []
    if isinstance(positions_data, dict):
        portfolio = positions_data.get("portfolio", positions_data)
        
        stock_positions = portfolio.get("stock_positions") or []
        fut_positions = portfolio.get("fut_positions") or []
        opt_positions = portfolio.get("opt_positions") or []
        
        positions = stock_positions + fut_positions + opt_positions
    elif isinstance(positions_data, list):
        positions = positions_data

    for position in positions:
        pos_exchange = position.get("exchange", "")
        pos_symbol = position.get("symbol", position.get("display_name", ""))
        ref_id = str(position.get("ref_id", ""))
        
        # Map product type from Nubra format
        product = position.get("product", "")
        if product == "ORDER_DELIVERY_TYPE_CNC":
            pos_producttype = "CNC"
        elif product == "ORDER_DELIVERY_TYPE_IDAY":
            pos_producttype = "MIS"
        elif product == "ORDER_DELIVERY_TYPE_NRML":
            pos_producttype = "NRML"
        else:
            pos_producttype = product
        
        # Check for matching position
        if pos_exchange == exchange and pos_producttype == producttype:
            # Match by symbol or ref_id
            symbol_from_db = get_symbol(ref_id, pos_exchange)
            
            if symbol_from_db == tradingsymbol or pos_symbol == tradingsymbol:
                # Nubra uses 'qty' for position quantity
                qty = position.get("qty", position.get("quantity", 0)) or 0
                order_side = position.get("order_side", "BUY")
                # For sell positions, return negative quantity
                net_qty = str(qty) if order_side == "BUY" else str(-qty)
                break

    return net_qty


def place_order_api(data, auth):
    """
    Place a single order using Nubra's API.
    
    Nubra API: POST /orders/v2/single
    """
    AUTH_TOKEN = auth
    device_id = "OPENALGO"  # Fixed device ID, same as auth_api.py
    
    # Get token (ref_id) for the symbol
    token = get_token(data["symbol"], data["exchange"])
    
    logger.info(f"Nubra order - Symbol: {data['symbol']}, Exchange: {data['exchange']}, Token: {token}")
    
    # Transform OpenAlgo data to Nubra format
    nubra_data = transform_data(data, token)
    
    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-device-id": device_id,
    }
    
    payload = json.dumps(nubra_data)
    
    logger.info(f"Nubra place order payload: {payload}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Make the request using the shared client
    response = client.post(
        f"{NUBRA_BASE_URL}/orders/v2/single",
        headers=headers,
        content=payload,
    )

    # Parse the JSON response
    try:
        response_data = response.json()
    except json.JSONDecodeError:
        logger.error(f"Failed to parse order response: {response.text}")
        response_data = {"error": "Failed to parse response"}
        return response, response_data, None

    logger.info(f"Nubra place order response (status={response.status_code}): {response_data}")

    # Nubra returns 201 (Created) on success with order_id in response
    if response.status_code in [200, 201] and "order_id" in response_data:
        orderid = str(response_data["order_id"])
        # Normalize response format for OpenAlgo compatibility
        response_data["status"] = True
        response_data["data"] = {"orderid": orderid}
        # OpenAlgo service layer expects status 200 for success
        response.status = 200
    else:
        orderid = None
        response_data["status"] = False
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
    position_size = int(data.get("position_size", "0"))

    # Get current open position for the symbol
    current_position = int(
        get_open_position(symbol, exchange, product, AUTH_TOKEN)
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
        # logger.info(f"action : {action}")
        # logger.info(f"Quantity : {quantity}")
        res, response, orderid = place_order_api(data, AUTH_TOKEN)
        # logger.info(f"{res}")
        # logger.info(f"{response}")

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
            # logger.info(f"smart buy quantity : {quantity}")
        elif position_size < current_position:
            action = "SELL"
            quantity = current_position - position_size
            # logger.info(f"smart sell quantity : {quantity}")

    if action:
        # Prepare data for placing the order
        order_data = data.copy()
        order_data["action"] = action
        order_data["quantity"] = str(quantity)

        # logger.info(f"{order_data}")
        # Place the order
        res, response, orderid = place_order_api(order_data, auth)
        # logger.info(f"{res}")
        logger.info(f"{response}")
        logger.info(f"{orderid}")

        return res, response, orderid


def close_all_positions(current_api_key, auth):
    """
    Close all open positions using Nubra's API.
    
    Fetches positions from portfolio.stock_positions, portfolio.fut_positions,
    portfolio.opt_positions and places market orders to close each one.
    """
    AUTH_TOKEN = auth

    positions_response = get_positions(AUTH_TOKEN)
    
    logger.info(f"Nubra positions response: {positions_response}")

    # Handle Nubra's response format - portfolio contains stock_positions, fut_positions, opt_positions
    positions = []
    if isinstance(positions_response, dict):
        portfolio = positions_response.get("portfolio", positions_response)
        
        # Collect positions from all position types
        stock_positions = portfolio.get("stock_positions") or []
        fut_positions = portfolio.get("fut_positions") or []
        opt_positions = portfolio.get("opt_positions") or []
        
        positions = stock_positions + fut_positions + opt_positions
        
        if positions_response.get("error"):
            logger.warning(f"Nubra positions error: {positions_response}")
            return {"message": "Failed to fetch positions"}, 500
    elif isinstance(positions_response, list):
        positions = positions_response

    # Check if positions is empty
    if not positions:
        return {"message": "No Open Positions Found"}, 200

    # Loop through each position to close
    for position in positions:
        # Get quantity - Nubra uses 'qty' in position data
        qty = int(position.get("qty", position.get("quantity", 0)) or 0)
        
        # Skip if quantity is zero
        if qty == 0:
            continue

        # Determine action based on order_side (opposite to close)
        order_side = position.get("order_side", "BUY")
        # To close, we do the opposite action
        action = "SELL" if order_side == "BUY" else "BUY"
        quantity = abs(qty)

        # Get exchange from position
        exchange = position.get("exchange", "NSE")
        
        # Get symbol from position - use 'symbol' field
        symbol = position.get("symbol", position.get("display_name", ""))
        ref_id = str(position.get("ref_id", ""))
        
        # Try to get OpenAlgo symbol from database using ref_id
        oa_symbol = get_symbol(ref_id, exchange)
        if oa_symbol:
            symbol = oa_symbol
        
        logger.info(f"Closing position - Symbol: {symbol}, Exchange: {exchange}, Qty: {quantity}, Action: {action}")

        # Map product type - Nubra uses 'product' like ORDER_DELIVERY_TYPE_CNC
        product_type = position.get("product", "ORDER_DELIVERY_TYPE_IDAY")
        product = reverse_map_product_type(product_type)

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

        logger.info(f"Close position payload: {place_order_payload}")

        # Place the order to close the position
        res, response, orderid = place_order_api(place_order_payload, auth)
        
        logger.info(f"Close position response: {response}, orderid: {orderid}")

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """
    Cancel an order using Nubra's API.
    
    Nubra API: DELETE /orders/{order_id}
    """
    AUTH_TOKEN = auth
    device_id = "OPENALGO"  # Fixed device ID, same as auth_api.py

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Set up the request headers
    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-device-id": device_id,
    }

    # Make the DELETE request using the shared client
    response = client.delete(
        f"{NUBRA_BASE_URL}/orders/{orderid}",
        headers=headers,
    )

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    # Handle empty response
    if not response.text:
        if response.status_code in [200, 204]:
            return {"status": "success", "orderid": orderid}, 200
        else:
            return {"status": "error", "message": "Empty response from API"}, response.status_code

    try:
        data = json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse cancel order response: {response.text}")
        return {"status": "error", "message": "Failed to parse response"}, response.status_code

    logger.info(f"Nubra cancel order response (status={response.status_code}): {data}")

    # Check if the request was successful
    # Nubra returns {"message": "delete request pushed"} on success
    if response.status_code in [200, 204]:
        if data.get("message") == "delete request pushed":
            return {"status": "success", "orderid": orderid}, 200
        elif data.get("order_id") or data.get("status") == "cancelled":
            return {"status": "success", "orderid": orderid}, 200
        else:
            # Assume success if status code is 200/204
            return {"status": "success", "orderid": orderid}, 200
    else:
        # Return an error response
        return {
            "status": "error",
            "message": data.get("message", data.get("error", "Failed to cancel order")),
        }, response.status_code


def modify_order(data, auth):
    """
    Modify an order using Nubra's API.
    
    Nubra API: POST /orders/v2/modify/{order_id}
    
    Compulsory fields: order_price, order_qty, exchange, order_type
    For ORDER_TYPE_STOPLOSS: also requires trigger_price in algo_params
    """
    AUTH_TOKEN = auth
    device_id = "OPENALGO"  # Fixed device ID, same as auth_api.py

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Transform OpenAlgo data to Nubra modify order format
    # Note: token/ref_id is not needed for modify order
    transformed_data = transform_modify_order_data(data, None)
    
    # Get order_id from the data
    orderid = data.get("orderid", "")
    
    # Set up the request headers
    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "x-device-id": device_id,
    }
    payload = json.dumps(transformed_data)
    
    logger.info(f"Nubra modify order payload: {payload}")

    # Make the POST request using the shared client
    response = client.post(
        f"{NUBRA_BASE_URL}/orders/v2/modify/{orderid}",
        headers=headers,
        content=payload,
    )

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    # Handle empty response
    if not response.text:
        if response.status_code in [200, 204]:
            return {"status": "success", "orderid": orderid}, 200
        else:
            return {"status": "error", "message": "Empty response from API"}, response.status_code

    try:
        response_data = json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse modify order response: {response.text}")
        return {"status": "error", "message": "Failed to parse response"}, response.status_code

    logger.info(f"Nubra modify order response (status={response.status_code}): {response_data}")

    # Check if the request was successful
    # Nubra returns {"message": "update request pushed"} on success
    if response.status_code in [200, 201]:
        if response_data.get("message") == "update request pushed":
            return {"status": "success", "orderid": orderid}, 200
        elif response_data.get("order_id"):
            return {"status": "success", "orderid": str(response_data["order_id"])}, 200
        else:
            # Assume success if status code is 200/201
            return {"status": "success", "orderid": orderid}, 200
    else:
        return {
            "status": "error",
            "message": response_data.get("message", response_data.get("error", "Failed to modify order")),
        }, response.status_code


def cancel_all_orders_api(data, auth):
    """
    Cancel all open orders using Nubra's API.
    
    Nubra API returns orders as a list with order_id and order_status fields.
    """
    AUTH_TOKEN = auth

    order_book_response = get_order_book(AUTH_TOKEN)
    # logger.info(f"{order_book_response}")
    
    # Nubra returns a list directly, or could return error dict
    if isinstance(order_book_response, dict):
        if order_book_response.get("error"):
            return [], []  # Return empty lists indicating failure to retrieve the order book
        orders = order_book_response.get("data", []) if "data" in order_book_response else []
    elif isinstance(order_book_response, list):
        orders = order_book_response
    else:
        return [], []

    if not orders:
        return [], []

    # Filter orders that are in 'open' or 'pending' state
    # Nubra uses ORDER_STATUS_OPEN, ORDER_STATUS_PENDING
    open_statuses = [
        "ORDER_STATUS_OPEN", 
        "ORDER_STATUS_PENDING",
        "ORDER_STATUS_TRIGGER_PENDING",
    ]
    
    orders_to_cancel = [
        order
        for order in orders
        if order.get("order_status") in open_statuses
    ]
    # logger.info(f"{orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = str(order.get("order_id", ""))
        if orderid:
            cancel_response, status_code = cancel_order(orderid, auth)
            if status_code == 200:
                canceled_orders.append(orderid)
            else:
                failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
