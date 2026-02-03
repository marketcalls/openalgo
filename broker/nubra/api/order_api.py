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
    return get_api_response("/rest/secure/angelbroking/order/v1/getOrderBook", auth)


def get_trade_book(auth):
    return get_api_response("/rest/secure/angelbroking/order/v1/getTradeBook", auth)


def get_positions(auth):
    return get_api_response("/rest/secure/angelbroking/order/v1/getPosition", auth)


def get_holdings(auth):
    return get_api_response("/rest/secure/angelbroking/portfolio/v1/getAllHolding", auth)


def get_open_position(tradingsymbol, exchange, producttype, auth):
    # Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    positions_data = get_positions(auth)

    logger.debug(f"{positions_data}")

    net_qty = "0"

    if positions_data and positions_data.get("status") and positions_data.get("data"):
        for position in positions_data["data"]:
            if (
                position.get("tradingsymbol") == tradingsymbol
                and position.get("exchange") == exchange
                and position.get("producttype") == producttype
            ):
                net_qty = position.get("netqty", "0")
                break  # Assuming you need the first match

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
    # Fetch the current open positions
    AUTH_TOKEN = auth

    positions_response = get_positions(AUTH_TOKEN)

    # Check if the positions data is null or empty
    if positions_response["data"] is None or not positions_response["data"]:
        return {"message": "No Open Positions Found"}, 200

    if positions_response["status"]:
        # Loop through each position to close
        for position in positions_response["data"]:
            # Skip if net quantity is zero
            if int(position["netqty"]) == 0:
                continue

            # Determine action based on net quantity
            action = "SELL" if int(position["netqty"]) > 0 else "BUY"
            quantity = abs(int(position["netqty"]))

            # get openalgo symbol to send to placeorder function
            symbol = get_symbol(position["symboltoken"], position["exchange"])
            logger.info(f"The Symbol is {symbol}")

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position["exchange"],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position["producttype"]),
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
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    api_key = os.getenv("BROKER_API_KEY")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    # Set up the request headers
    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "CLIENT_LOCAL_IP",
        "X-ClientPublicIP": "CLIENT_PUBLIC_IP",
        "X-MACAddress": "MAC_ADDRESS",
        "X-PrivateKey": api_key,
    }

    # Prepare the payload
    payload = json.dumps(
        {
            "variety": "NORMAL",
            "orderid": orderid,
        }
    )

    # Make the request using the shared client
    response = client.post(
        "https://apiconnect.angelbroking.com/rest/secure/angelbroking/order/v1/cancelOrder",
        headers=headers,
        content=payload,
    )

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    data = json.loads(response.text)

    # Check if the request was successful
    if data.get("status"):
        # Return a success response
        return {"status": "success", "orderid": orderid}, 200
    else:
        # Return an error response
        return {
            "status": "error",
            "message": data.get("message", "Failed to cancel order"),
        }, response.status


def modify_order(data, auth):
    # Assuming you have a function to get the authentication token
    AUTH_TOKEN = auth
    api_key = os.getenv("BROKER_API_KEY")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    token = get_token(data["symbol"], data["exchange"])
    data["symbol"] = get_br_symbol(data["symbol"], data["exchange"])

    transformed_data = transform_modify_order_data(
        data, token
    )  # You need to implement this function
    # Set up the request headers
    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": "CLIENT_LOCAL_IP",
        "X-ClientPublicIP": "CLIENT_PUBLIC_IP",
        "X-MACAddress": "MAC_ADDRESS",
        "X-PrivateKey": api_key,
    }
    payload = json.dumps(transformed_data)

    # Make the request using the shared client
    response = client.post(
        "https://apiconnect.angelbroking.com/rest/secure/angelbroking/order/v1/modifyOrder",
        headers=headers,
        content=payload,
    )

    # Add status attribute for compatibility with the existing codebase
    response.status = response.status_code

    data = json.loads(response.text)

    if data.get("status") == "true" or data.get("message") == "SUCCESS":
        return {"status": "success", "orderid": data["data"]["orderid"]}, 200
    else:
        return {
            "status": "error",
            "message": data.get("message", "Failed to modify order"),
        }, response.status


def cancel_all_orders_api(data, auth):
    # Get the order book

    AUTH_TOKEN = auth

    order_book_response = get_order_book(AUTH_TOKEN)
    # logger.info(f"{order_book_response}")
    if order_book_response["status"] != True:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [
        order
        for order in order_book_response.get("data", [])
        if order["status"] in ["open", "trigger pending"]
    ]
    # logger.info(f"{orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []

    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order["orderid"]
        cancel_response, status_code = cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
