import json
import os
import urllib.parse

import httpx

from broker.kotak.mapping.transform_data import (
    map_exchange,
    map_product_type,
    reverse_map_exchange,
    reverse_map_product_type,
    transform_data,
    transform_modify_order_data,
)
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_symbol, get_token
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth_token, method="GET", payload=""):
    """
    Updated for Kotak Neo API v2 - uses dynamic baseUrl, httpx connection pooling, and new header structure
    """
    session_token, session_sid, base_url, access_token = auth_token.split(":::")

    # Debug logging for baseUrl
    logger.info(f"ORDER API - Using baseUrl: {base_url}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        "accept": "application/json",
        "Sid": session_sid,
        "Auth": session_token,
        "neo-fin-key": "neotradeapi",
    }

    # Construct full URL
    url = f"{base_url}{endpoint}"

    # Make request using httpx
    response = client.request(method, url, headers=headers, content=payload if payload else None)

    logger.info(f"ORDER API Response: {response.text}")

    return json.loads(response.text)


def get_order_book(auth_token):
    return get_api_response("/quick/user/orders", auth_token)


def get_trade_book(auth_token):
    return get_api_response("/quick/user/trades", auth_token)


def get_positions(auth_token):
    return get_api_response("/quick/user/positions", auth_token)


def get_holdings(auth_token):
    return get_api_response("/portfolio/v1/holdings", auth_token)


def get_open_position(tradingsymbol, exchange, producttype, auth_token):
    # Convert Trading Symbol from OpenAlgo Format to Broker Format Before Search in OpenPosition
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    positions_data = get_positions(auth_token)
    logger.info(f"{positions_data}")

    net_qty = "0"
    exchange = reverse_map_exchange(exchange)

    if positions_data.get("data"):
        for position in positions_data["data"]:
            if (
                position.get("trdSym") == tradingsymbol
                and position.get("exSeg") == exchange
                and position.get("prod") == producttype
            ):
                net_qty = (int(position.get("flBuyQty", 0)) - int(position.get("flSellQty", 0))) + (
                    int(position.get("cfBuyQty", 0)) - int(position.get("cfSellQty", 0))
                )
                break  # Assuming you need the first match

    return net_qty


def place_order_api(data, auth_token):
    session_token, session_sid, base_url, access_token = auth_token.split(":::")

    # Debug logging for baseUrl
    logger.info(f"PLACE ORDER API - Using baseUrl: {base_url}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    token_id = get_token(data["symbol"], data["exchange"])
    newdata = transform_data(data, token_id)

    json_string = json.dumps(newdata)
    payload = f"jData={urllib.parse.quote(json_string)}"

    headers = {
        "accept": "application/json",
        "Sid": session_sid,
        "Auth": session_token,
        "neo-fin-key": "neotradeapi",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # Construct full URL
    url = f"{base_url}/quick/order/rule/ms/place"

    try:
        response = client.post(url, headers=headers, content=payload)

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        response_data = json.loads(response.text)

        orderid = response_data["nOrdNo"] if response_data["stat"] == "Ok" else None
        return response, response_data, orderid
    except httpx.HTTPError as e:
        logger.error(f"HTTP error in place_order_api: {e}")
        return None, {"stat": "NotOk", "error": str(e)}, None
    except Exception as e:
        logger.error(f"Error in place_order_api: {e}")
        return None, {"stat": "NotOk", "error": str(e)}, None


def place_smartorder_api(data, auth_token):
    # If no API call is made in this function then res will return None
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
        res, response, orderid = place_order_api(data, auth_token)
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
        res, response, orderid = place_order_api(order_data, auth_token)
        # logger.info(f"{res}")
        logger.info(f"{response}")
        logger.info(f"{orderid}")

        return res, response, orderid


def close_all_positions(current_api_key, auth_token):
    # Fetch the current open positions
    positions_response = get_positions(auth_token)
    # logger.info(f"{positions_response}")
    # Check if the positions data is null or empty
    if positions_response["data"] is None or not positions_response["data"]:
        return {"message": "No Open Positions Found"}, 200

    if positions_response["data"]:
        # Loop through each position to close
        for position in positions_response["data"]:
            # Skip if net quantity is zero
            net_qty = (int(position.get("flBuyQty", 0)) - int(position.get("flSellQty", 0))) + (
                int(position.get("cfBuyQty", 0)) - int(position.get("cfSellQty", 0))
            )
            if net_qty == 0:
                continue

            # Determine action based on net quantity
            action = "SELL" if net_qty > 0 else "BUY"
            quantity = abs(net_qty)

            # get openalgo symbol to send to placeorder function
            symboltoken = position["tok"]
            exchange = map_exchange(position["exSeg"])
            position["exSeg"] = exchange

            # Use the get_symbol function to fetch the symbol from the database
            symbol = get_symbol(symboltoken, exchange)

            logger.info(f"The Symbol is {symbol}")

            # Prepare the order payload
            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position["exSeg"],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position["prod"]),
                "quantity": str(quantity),
            }

            logger.info(f"{place_order_payload}")

            # Place the order to close the position
            res, response, orderid = place_order_api(place_order_payload, auth_token)

            # logger.info(f"{res}")
            logger.info(f"{response}")
            # logger.info(f"{orderid}")

            # Note: Ensure place_order_api handles any errors and logs accordingly

    return {"status": "success", "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth_token):
    session_token, session_sid, base_url, access_token = auth_token.split(":::")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    payload = f"jData={urllib.parse.quote(json.dumps({'on': orderid, 'am': 'NO'}))}"

    headers = {
        "accept": "application/json",
        "Sid": session_sid,
        "Auth": session_token,
        "neo-fin-key": "neotradeapi",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # Construct full URL
    url = f"{base_url}/quick/order/cancel"

    try:
        response = client.post(url, headers=headers, content=payload)
        response_data = json.loads(response.text)

        if response_data.get("stat") == "Ok":
            return {"status": "success", "orderid": response_data.get("nOrdNo")}, 200
        return {
            "status": "error",
            "message": response_data.get("emsg", "Failed to cancel order"),
        }, response.status_code
    except httpx.HTTPError as e:
        logger.error(f"HTTP error in cancel_order: {e}")
        return {"status": "error", "message": str(e)}, 500
    except Exception as e:
        logger.error(f"Error in cancel_order: {e}")
        return {"status": "error", "message": str(e)}, 500


def modify_order(data, auth_token):
    session_token, session_sid, base_url, access_token = auth_token.split(":::")

    # Debug logging for baseUrl
    logger.info(f"MODIFY ORDER API - Using baseUrl: {base_url}")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    token_id = get_token(data["symbol"], data["exchange"])
    newdata = transform_modify_order_data(data, token_id)

    logger.info(f"MODIFY ORDER - Transformed data: {newdata}")

    payload = f"jData={urllib.parse.quote(json.dumps(newdata))}"

    headers = {
        "accept": "application/json",
        "Sid": session_sid,
        "Auth": session_token,
        "neo-fin-key": "neotradeapi",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # Construct full URL
    url = f"{base_url}/quick/order/vr/modify"

    logger.info(f"MODIFY ORDER - Making POST request to: {url}")

    try:
        response = client.post(url, headers=headers, content=payload)

        logger.info(f"MODIFY ORDER - Response status: {response.status_code}")
        logger.info(f"MODIFY ORDER - Response: {response.text}")

        response_data = json.loads(response.text)

        if response_data.get("stat") == "Ok":
            return {"status": "success", "orderid": response_data["nOrdNo"]}, 200
        return {
            "status": "error",
            "message": response_data.get("emsg", "Failed to modify order"),
        }, response.status_code
    except httpx.HTTPError as e:
        logger.error(f"HTTP error in modify_order: {e}")
        return {"status": "error", "message": f"HTTP error: {str(e)}"}, 500
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in modify_order: {e}")
        return {"status": "error", "message": f"JSON decode error: {str(e)}"}, 500
    except Exception as e:
        logger.error(f"Error in modify_order: {e}")
        return {"status": "error", "message": str(e)}, 500


def cancel_all_orders_api(data, auth_token):
    # Get the order book
    order_book_response = get_order_book(auth_token)

    if order_book_response["data"] is None:
        return [], []  # Return empty lists indicating failure to retrieve the order book

    # Filter orders that are in 'open' or 'trigger_pending' state
    orders_to_cancel = [
        order
        for order in order_book_response.get("data", [])
        if order["ordSt"] in ["open", "trigger pending"]
    ]
    # logger.info(f"{orders_to_cancel}")
    canceled_orders = []
    failed_cancellations = []
    logger.info(f"{orders_to_cancel}")
    # Cancel the filtered orders
    for order in orders_to_cancel:
        orderid = order["nOrdNo"]
        cancel_response, status_code = cancel_order(orderid, auth_token)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
