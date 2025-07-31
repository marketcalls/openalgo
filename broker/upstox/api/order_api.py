import json
import os
import httpx
from utils.httpx_client import get_httpx_client
from database.auth_db import get_auth_token
from database.token_db import get_token, get_br_symbol, get_symbol
from broker.upstox.mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="GET", payload=''):
    """
    A wrapper to send requests to the Upstox API and handle responses.
    Args:
        endpoint (str): The API endpoint to call.
        auth (str): The authentication token.
        method (str): The HTTP method (GET, POST, PUT, DELETE).
        payload (str): The JSON payload for POST and PUT requests.
    Returns:
        dict: The JSON response from the API, or an error dictionary.
    """
    logger.debug(f"Requesting {method} on endpoint: {endpoint}")
    try:
        api_key = os.getenv('BROKER_API_KEY')
        if not api_key:
            logger.error("BROKER_API_KEY environment variable not set.")
            return {'status': 'error', 'message': 'BROKER_API_KEY not set'}

        client = get_httpx_client()
        headers = {
            'Authorization': f'Bearer {auth}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        url = f"https://api.upstox.com{endpoint}"

        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, headers=headers, content=payload)
        elif method == "PUT":
            response = client.put(url, headers=headers, content=payload)
        elif method == "DELETE":
            response = client.delete(url, headers=headers)
        else:
            logger.error(f"Unsupported HTTP method: {method}")
            return {'status': 'error', 'message': f'Unsupported HTTP method: {method}'}

        response.raise_for_status()
        response_data = response.json()
        logger.debug(f"API response for {endpoint}: {response_data}")
        return response_data

    except httpx.HTTPStatusError as e:
        error_response = e.response.text
        logger.exception(f"HTTP error on {endpoint}: {error_response}")
        try:
            return e.response.json()
        except json.JSONDecodeError:
            return {'status': 'error', 'message': f'HTTP error: {error_response}'}
    except Exception as e:
        logger.exception(f"Unexpected error on {endpoint}")
        return {'status': 'error', 'message': str(e)}


def get_order_book(auth):
    """Fetches the order book."""
    return get_api_response("/v2/order/retrieve-all", auth)


def get_trade_book(auth):
    """Fetches the trade book."""
    return get_api_response("/v2/order/trades/get-trades-for-day", auth)


def get_positions(auth):
    """Fetches short-term positions."""
    return get_api_response("/v2/portfolio/short-term-positions", auth)


def get_holdings(auth):
    """Fetches long-term holdings."""
    return get_api_response("/v2/portfolio/long-term-holdings", auth)


def get_open_position(tradingsymbol, exchange, product, auth):
    """
    Gets the net quantity of an open position for a given symbol.
    """
    logger.debug(f"Getting open position for {tradingsymbol} on {exchange} with product {product}")
    try:
        br_symbol = get_br_symbol(tradingsymbol, exchange)
        positions_data = get_positions(auth)
        net_qty = '0'

        if positions_data and positions_data.get('status') == 'success' and positions_data.get('data'):
            for position in positions_data['data']:
                if position.get('tradingsymbol') == br_symbol and position.get('exchange') == exchange and position.get('product') == product:
                    net_qty = position.get('quantity', '0')
                    logger.debug(f"Found open position for {tradingsymbol}: {net_qty}")
                    break
        elif positions_data.get('status') == 'error':
            logger.error(f"Failed to get positions: {positions_data.get('message')}")

        return net_qty
    except Exception as e:
        logger.exception(f"Error getting open position for {tradingsymbol}")
        return '0'


def place_order_api(data, auth):
    """
    Places an order using the Upstox API.
    Returns a tuple: (httpx.Response, response_data_dict, order_id_str)
    """
    logger.info(f"Placing order with data: {data}")
    try:
        api_key = os.getenv('BROKER_API_KEY')
        if not api_key:
            logger.error("BROKER_API_KEY not set. Cannot place order.")
            return None, {"status": "error", "message": "BROKER_API_KEY not set"}, None

        token = get_token(data['symbol'], data['exchange'])
        if not token:
            logger.error(f"Instrument token not found for {data['symbol']}. Cannot place order.")
            return None, {"status": "error", "message": "Instrument token not found"}, None

        newdata = transform_data(data, token)
        payload = json.dumps({
            "quantity": newdata['quantity'],
            "product": newdata.get('product', 'I'),
            "validity": newdata.get('validity', 'DAY'),
            "price": newdata.get('price', '0'),
            "tag": newdata.get('tag', 'string'),
            "instrument_token": newdata['instrument_token'],
            "order_type": newdata.get('order_type', 'MARKET'),
            "transaction_type": newdata['transaction_type'],
            "disclosed_quantity": newdata.get('disclosed_quantity', '0'),
            "trigger_price": newdata.get('trigger_price', '0'),
            "is_amo": newdata.get('is_amo', False)
        })
        logger.debug(f"Placing order with payload: {payload}")

        client = get_httpx_client()
        headers = {'Authorization': f'Bearer {auth}', 'Content-Type': 'application/json', 'Accept': 'application/json'}
        response = client.post("https://api.upstox.com/v2/order/place", headers=headers, content=payload)
        response.raise_for_status()
        
        # Add status attribute to make response compatible with place_order_service.py
        # as the rest of the codebase expects .status instead of .status_code
        response.status = response.status_code

        response_data = response.json()
        logger.debug(f"Place order API response: {response_data}")

        if response_data.get('status') == 'success':
            order_id = response_data.get('data', {}).get('order_id')
            logger.info(f"Successfully placed order. Order ID: {order_id}")
            return response, response_data, order_id
        else:
            error_msg = response_data.get('message', 'Failed to place order.')
            logger.error(f"Failed to place order: {error_msg} | Response: {response_data}")
            return response, response_data, None

    except httpx.HTTPStatusError as e:
        logger.exception(f"HTTP error placing order: {e.response.text}")
        return e.response, e.response.json(), None
    except Exception as e:
        logger.exception("Unexpected error in place_order_api")
        return None, {"status": "error", "message": str(e)}, None


def place_smartorder_api(data, auth):
    """
    Places a smart order by comparing the desired position size with the current open position.
    """
    logger.info(f"Placing smart order with data: {data}")
    try:
        symbol = data.get("symbol")
        exchange = data.get("exchange")
        product = data.get("product")
        position_size = int(data.get("position_size", "0"))

        current_position = int(get_open_position(symbol, exchange, map_product_type(product), auth))
        logger.debug(f"Desired position size: {position_size}, Current position: {current_position}")

        if position_size == 0 and current_position == 0 and int(data.get('quantity', 0)) != 0:
            logger.info("No existing position and quantity is specified. Placing a new order.")
            return place_order_api(data, auth)

        if position_size == current_position:
            msg = "No action needed. Position size matches current position."
            if int(data.get('quantity', 0)) == 0:
                msg = "No open position found. Not placing exit order."
            logger.info(msg)
            return None, {"status": "success", "message": msg}, None

        action, quantity = None, 0
        if position_size > current_position:
            action, quantity = "BUY", position_size - current_position
        else:
            action, quantity = "SELL", current_position - position_size

        logger.info(f"Determined action: {action}, Quantity: {quantity}")

        order_data = data.copy()
        order_data["action"] = action
        order_data["quantity"] = str(quantity)

        return place_order_api(order_data, auth)

    except Exception as e:
        logger.exception("Unexpected error in place_smartorder_api")
        return None, {"status": "error", "message": str(e)}, None


def close_all_positions(current_api_key, auth):
    """
    Closes all open positions.
    """
    logger.info("Attempting to close all open positions.")
    try:
        positions_response = get_positions(auth)
        if positions_response.get('status') != 'success' or not positions_response.get('data'):
            logger.info("No open positions found to close.")
            return {"message": "No Open Positions Found"}, 200

        for position in positions_response['data']:
            if int(position.get('quantity', 0)) == 0:
                continue

            action = 'SELL' if int(position['quantity']) > 0 else 'BUY'
            quantity = abs(int(position['quantity']))
            symbol = get_symbol(position['instrument_token'], position['exchange'])

            if not symbol:
                logger.warning(f"Could not find symbol for instrument token {position['instrument_token']}. Skipping position.")
                continue

            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position['exchange'],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position['exchange'], position['product']),
                "quantity": str(quantity)
            }
            logger.debug(f"Closing position with payload: {place_order_payload}")
            _, api_response, _ = place_order_api(place_order_payload, auth)
            logger.info(f"Close position response for {symbol}: {api_response}")

        logger.info("Successfully initiated closing of all open positions.")
        return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200

    except Exception as e:
        logger.exception("An error occurred while closing all positions.")
        return {"status": "error", "message": "Failed to close all positions"}, 500


def cancel_order(orderid, auth):
    """
    Cancels a specific order by its ID.
    """
    logger.info(f"Attempting to cancel order ID: {orderid}")
    try:
        response_data = get_api_response(f"/v2/order/cancel?order_id={orderid}", auth, method="DELETE")

        if response_data.get("status") == "success":
            canceled_id = response_data.get('data', {}).get('order_id')
            logger.info(f"Successfully canceled order ID: {canceled_id}")
            return {"status": "success", "orderid": canceled_id}, 200
        else:
            error_msg = response_data.get("message", "Failed to cancel order")
            logger.error(f"Failed to cancel order {orderid}: {error_msg} | Response: {response_data}")
            return {"status": "error", "message": error_msg}, 400

    except Exception as e:
        logger.exception(f"Unexpected error canceling order {orderid}")
        return {"status": "error", "message": str(e)}, 500


def modify_order(data, auth):
    """
    Modifies an existing order.
    """
    logger.info(f"Attempting to modify order with data: {data}")
    try:
        transformed_order_data = transform_modify_order_data(data)
        payload = json.dumps(transformed_order_data)
        logger.debug(f"Modify order payload: {payload}")

        response_data = get_api_response("/v2/order/modify", auth, method="PUT", payload=payload)

        if response_data.get("status") == "success":
            modified_id = response_data.get('data', {}).get('order_id')
            logger.info(f"Successfully modified order. New Order ID: {modified_id}")
            return {"status": "success", "orderid": modified_id}, 200
        else:
            error_msg = response_data.get("message", "Failed to modify order")
            logger.error(f"Failed to modify order: {error_msg} | Response: {response_data}")
            return {"status": "error", "message": error_msg}, 400

    except Exception as e:
        logger.exception("Unexpected error modifying order")
        return {"status": "error", "message": str(e)}, 500


def cancel_all_orders_api(data, auth):
    """
    Cancels all open and trigger-pending orders.
    """
    logger.info("Attempting to cancel all open orders.")
    try:
        order_book_response = get_order_book(auth)
        if order_book_response.get('status') != 'success':
            logger.error(f"Failed to retrieve order book to cancel orders: {order_book_response.get('message')}")
            return [], []

        orders_to_cancel = [
            order for order in order_book_response.get('data', [])
            if order.get('status') in ['open', 'trigger pending']
        ]

        if not orders_to_cancel:
            logger.info("No open orders to cancel.")
            return [], []

        logger.debug(f"Found {len(orders_to_cancel)} orders to cancel: {[o['order_id'] for o in orders_to_cancel]}")
        canceled_orders, failed_cancellations = [], []

        for order in orders_to_cancel:
            orderid = order['order_id']
            cancel_response, status_code = cancel_order(orderid, auth)
            if status_code == 200:
                canceled_orders.append(orderid)
            else:
                failed_cancellations.append(orderid)
        
        logger.info(f"Canceled {len(canceled_orders)} orders. Failed to cancel {len(failed_cancellations)} orders.")
        return canceled_orders, failed_cancellations

    except Exception as e:
        logger.exception("An error occurred while canceling all orders.")
        return [], []

