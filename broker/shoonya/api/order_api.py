import json
import os

import httpx

from broker.shoonya.mapping.transform_data import (
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


def get_api_response(endpoint, auth, method="GET", payload=""):
    """Make an authenticated API request to the Shoonya API.

    Handles setting the `UID` and `ACTID` using the configured API key,
    and formats the payload as `jData={data}&jKey={token}`.

    Args:
        endpoint: API endpoint path (e.g., '/NorenWClientTP/OrderBook').
        auth: Shoonya authentication token (jKey).
        method: HTTP method to use. Defaults to 'GET'.
        payload: Optional payload string. Defaults to ''.

    Returns:
        dict: Parsed JSON response from the Shoonya API.
    """
    AUTH_TOKEN = auth

    api_key = os.getenv("BROKER_API_KEY")
    api_key = api_key[:-2]

    data = f'{{"uid": "{api_key}", "actid": "{api_key}"}}'

    if endpoint == "/NorenWClientTP/Holdings":
        data = f'{{"uid": "{api_key}", "actid": "{api_key}", "prd": "C"}}'

    payload_str = "jData=" + data + "&jKey=" + AUTH_TOKEN

    # Get the shared httpx client
    client = get_httpx_client()

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    url = f"https://api.shoonya.com{endpoint}"

    response = client.request(method, url, content=payload_str, headers=headers)
    data = response.text

    try:
        return json.loads(data)
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON: {e}")
        logger.info(f"Response data: {data}")
        raise


def get_order_book(auth):
    """Retrieve the order book for the authenticated user.

    Args:
        auth: Shoonya authentication token.

    Returns:
        dict: Order book data containing all orders for the session.
    """
    return get_api_response("/NorenWClientTP/OrderBook", auth, method="POST")


def get_trade_book(auth):
    """Retrieve the trade book for the authenticated user.

    Args:
        auth: Shoonya authentication token.

    Returns:
        dict: Trade book data containing all executed trades.
    """
    return get_api_response("/NorenWClientTP/TradeBook", auth, method="POST")


def get_positions(auth):
    """Retrieve current positions for the authenticated user.

    Args:
        auth: Shoonya authentication token.

    Returns:
        dict: Position data including net quantities and prices.
    """
    return get_api_response("/NorenWClientTP/PositionBook", auth, method="POST")


def get_holdings(auth):
    """Retrieve portfolio holdings for the authenticated user.

    Args:
        auth: Shoonya authentication token.

    Returns:
        dict: Holdings data with instrument valuations and quantities.
    """
    return get_api_response("/NorenWClientTP/Holdings", auth, method="POST")


def get_open_position(tradingsymbol, exchange, producttype, auth):
    """Get the net open position quantity for a specific symbol.

    Args:
        tradingsymbol: Trading symbol in OpenAlgo format.
        exchange: Exchange in OpenAlgo format (e.g., 'NSE', 'NFO').
        producttype: Product type in Shoonya format (e.g., 'C', 'I').
        auth: Shoonya authentication token.

    Returns:
        str: Net quantity of the open position as a string. Positive for long,
            negative for short, '0' if no position found.
    """
    # Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    positions_data = get_positions(auth)

    logger.info(f"{positions_data}")

    net_qty = "0"

    if positions_data is None or (
        isinstance(positions_data, dict) and (positions_data["stat"] == "Not_Ok")
    ):
        # Handle the case where there is no data
        logger.info("No data available.")
        net_qty = "0"

    if positions_data and isinstance(positions_data, list):
        for position in positions_data:
            if (
                position.get("tsym") == tradingsymbol
                and position.get("exch") == exchange
                and position.get("prd") == producttype
            ):
                net_qty = position.get("netqty", "0")
                break  # Assuming you need the first match

    return net_qty


def place_order_api(data, auth):
    """Place a new order through the Shoonya API.

    Args:
        data: Order parameters including 'symbol', 'exchange', 'action',
            'quantity', 'pricetype', 'product', and optional 'price'
            and 'trigger_price'.
        auth: Shoonya authentication token.

    Returns:
        tuple: (response, response_data, orderid) where response is the
            httpx Response object, response_data is the parsed JSON dict,
            and orderid is the order number string or None on failure.
    """
    AUTH_TOKEN = auth
    BROKER_API_KEY = os.getenv("BROKER_API_KEY")
    data["apikey"] = BROKER_API_KEY
    token = get_token(data["symbol"], data["exchange"])
    newdata = transform_data(data, token)
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    payload_str = "jData=" + json.dumps(newdata) + "&jKey=" + AUTH_TOKEN

    logger.info(f"{payload_str}")

    # Get the shared httpx client
    client = get_httpx_client()
    url = "https://api.shoonya.com/NorenWClientTP/PlaceOrder"

    response = client.post(url, content=payload_str, headers=headers)
    response_data = json.loads(response.text)

    # Add compatibility for service layer that expects .status attribute
    response.status = response.status_code

    if response_data["stat"] == "Ok":
        orderid = response_data["norenordno"]
    else:
        orderid = None
    return response, response_data, orderid



def place_smartorder_api(data, auth):
    """Place a smart order that automatically manages position sizing.

    Args:
        data: Order parameters including 'symbol', 'exchange', 'product',
            'action', 'quantity', and 'position_size'.
        auth: Shoonya authentication token.

    Returns:
        tuple: (response, response_data, orderid). Returns None for
            response if no API call was needed.
    """
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
        get_open_position(symbol, exchange, map_product_type(product), AUTH_TOKEN)
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
        return res, response, orderid  # res remains None as no API call was made

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
    # Fetch the current open positions
    AUTH_TOKEN = auth

    positions_response = get_positions(AUTH_TOKEN)

    # Check if the positions data is null or empty
    if positions_response is None or positions_response[0]["stat"] == "Not_Ok":
        return {"message": "No Open Positions Found"}, 200

    if positions_response:
        # Loop through each position to close
        for position in positions_response:
            # Skip if net quantity is zero
            if int(position["netqty"]) == 0:
                continue

            # Determine action based on net quantity
            action = "SELL" if int(position["netqty"]) > 0 else "BUY"
            quantity = abs(int(position["netqty"]))

            # get openalgo symbol to send to placeorder function
            symbol = get_symbol(position["token"], position["exch"])
            logger.info(f"The Symbol is {symbol}")

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position["exch"],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position["prd"]),
                "quantity": str(quantity),
            }

            logger.info(f"{place_order_payload}")

            # Place the order to close the position
            res, response, orderid = place_order_api(place_order_payload, auth)

            # logger.info(f"{res}")
            # logger.info(f"{response}")
            # logger.info(f"{orderid}")

            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """Cancel an existing order by its order number.

    Args:
        orderid: The Shoonya order number (norenordno) to cancel.
        auth: Shoonya authentication token.

    Returns:
        tuple: (response_dict, status_code). On success, returns the
            cancelled order ID with status 200.
    """
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    api_key = os.getenv("BROKER_API_KEY")
    api_key = api_key[:-2]
    data = {"uid": api_key, "norenordno": orderid}

    payload_str = "jData=" + json.dumps(data) + "&jKey=" + AUTH_TOKEN
    # Set up the request headers
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    # Get the shared httpx client
    client = get_httpx_client()
    url = "https://api.shoonya.com/NorenWClientTP/CancelOrder"

    response = client.post(url, content=payload_str, headers=headers)
    data = json.loads(response.text)
    logger.info(f"{data}")

    # Add compatibility for service layer that expects .status attribute
    response.status = response.status_code

    # Check if the request was successful
    if data.get("stat") == "Ok":
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Return an error response
        return {
            "status": "error",
            "message": data.get("message", "Failed to cancel order"),
        }, response.status


def modify_order(data, auth):
    """Modify an existing order's parameters in Shoonya.

    Args:
        data: Modification parameters including 'orderid', 'symbol',
            'exchange', 'quantity', 'price', 'pricetype', 'product',
            and 'action'.
        auth: Shoonya authentication token.

    Returns:
        tuple: (response_dict, status_code). On success, returns the
            modified order ID with status 200.
    """
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    api_key = os.getenv("BROKER_API_KEY")
    api_key = api_key[:-2]

    token = get_token(data["symbol"], data["exchange"])
    data["symbol"] = get_br_symbol(data["symbol"], data["exchange"])
    data["apikey"] = api_key

    transformed_data = transform_modify_order_data(data, token)
    # Set up the request headers
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    payload_str = "jData=" + json.dumps(transformed_data) + "&jKey=" + AUTH_TOKEN

    logger.debug("=== SHOONYA MODIFY ORDER ===")
    # Redact sensitive fields for logging
    safe_log_data = {k: v for k, v in transformed_data.items() if k != "uid"}
    logger.debug(f"jData={json.dumps(safe_log_data)}")

    # Get the shared httpx client
    client = get_httpx_client()
    url = "https://api.shoonya.com/NorenWClientTP/ModifyOrder"

    response = client.post(url, content=payload_str, headers=headers)
    response_data = json.loads(response.text)
    logger.info(f"Modify order response: {response_data}")

    # Add compatibility for service layer that expects .status attribute
    response.status = response.status_code

    if response_data.get("stat") == "Ok":
        return {"status": "success", "orderid": data["orderid"]}, 200
    else:
        return {
            "status": "error",
            "message": response_data.get("emsg", "Failed to modify order"),
        }, response.status


def cancel_all_orders_api(data, auth):
    # Get the order book

    AUTH_TOKEN = auth

    order_book_response = get_order_book(AUTH_TOKEN)
    # logger.info(f"{order_book_response}")
    if order_book_response is None:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [
        order for order in order_book_response if order["status"] in ["OPEN", "TRIGGER PENDING"]
    ]
    # logger.info(f"{orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order["norenordno"]
        cancel_response, status_code = cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
