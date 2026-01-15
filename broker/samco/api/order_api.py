import json
import os
import httpx
from database.token_db import get_token, get_br_symbol, get_symbol, get_oa_symbol
from broker.samco.mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Samco API base URL
BASE_URL = "https://tradeapi.samco.in"


def get_api_response(endpoint, auth, method="GET", payload=None):
    """
    Generic API response handler for Samco endpoints.
    """
    client = get_httpx_client()

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'x-session-token': auth
    }

    url = f"{BASE_URL}{endpoint}"

    if method == "GET":
        response = client.get(url, headers=headers)
    elif method == "POST":
        response = client.post(url, headers=headers, json=payload)
    else:
        response = client.request(method, url, headers=headers, json=payload)

    response.status = response.status_code

    if not response.text:
        return {}

    try:
        return json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from {endpoint}: {response.text}")
        return {}


def get_order_book(auth):
    """Get order book from Samco."""
    response = get_api_response("/order/orderBook", auth)
    logger.info(f"Samco order book response: {response}")
    return response


def get_trade_book(auth):
    """Get trade book from Samco."""
    response = get_api_response("/trade/tradeBook", auth)
    logger.info(f"Samco trade book response: {response}")
    return response


def get_positions(auth):
    """Get positions from Samco."""
    client = get_httpx_client()
    headers = {
        'Accept': 'application/json',
        'x-session-token': auth
    }
    response = client.get(
        f"{BASE_URL}/position/getPositions",
        headers=headers,
        params={"positionType": "DAY"}
    )
    response_data = response.json() if response.text else {}
    logger.info(f"Samco positions response: {response_data}")
    return response_data


def get_holdings(auth):
    """Get holdings from Samco."""
    response = get_api_response("/holding/getHoldings", auth)
    logger.info(f"Samco holdings response: {response}")
    return response


def get_open_position(tradingsymbol, exchange, producttype, auth):
    """
    Get open position for a specific symbol.
    Samco returns netQuantity as positive and uses transactionType to indicate direction.
    """
    br_symbol = get_br_symbol(tradingsymbol, exchange)
    positions_data = get_positions(auth)

    logger.info(f"Looking for position: symbol={br_symbol}, exchange={exchange}, product={producttype}")
    logger.debug(f"Positions data: {positions_data}")

    net_qty = '0'

    if positions_data and positions_data.get('status') == 'Success' and positions_data.get('positionDetails'):
        for position in positions_data['positionDetails']:
            if (position.get('tradingSymbol') == br_symbol and
                position.get('exchange') == exchange and
                position.get('productCode') == producttype):
                qty = int(position.get('netQuantity', 0))
                transaction_type = position.get('transactionType', '')
                # Make quantity negative for SELL (short) positions
                if transaction_type == 'SELL' and qty > 0:
                    qty = -qty
                net_qty = str(qty)
                logger.info(f"Found position: netQuantity={qty}, transactionType={transaction_type}")
                break

    return net_qty


def place_order_api(data, auth):
    """
    Place an order with Samco.
    """
    token = get_token(data['symbol'], data['exchange'])
    newdata = transform_data(data, token)

    client = get_httpx_client()

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'x-session-token': auth
    }

    payload = {
        "symbolName": newdata['symbolName'],
        "exchange": newdata['exchange'],
        "transactionType": newdata['transactionType'],
        "orderType": newdata['orderType'],
        "quantity": newdata['quantity'],
        "disclosedQuantity": newdata.get('disclosedQuantity', '0'),
        "orderValidity": newdata.get('orderValidity', 'DAY'),
        "productType": newdata['productType'],
        "afterMarketOrderFlag": newdata.get('afterMarketOrderFlag', 'NO')
    }

    # Add price for limit orders
    if 'price' in newdata:
        payload['price'] = newdata['price']

    # Add trigger price for stop loss orders
    if 'triggerPrice' in newdata:
        payload['triggerPrice'] = newdata['triggerPrice']

    logger.info(f"Samco place order payload: {payload}")

    response = client.post(
        f"{BASE_URL}/order/placeOrder",
        headers=headers,
        json=payload
    )

    response.status = response.status_code

    response_data = response.json()
    logger.info(f"Samco place order response: {response_data}")

    if response_data.get('status') == 'Success':
        orderid = response_data.get('orderNumber')
    else:
        orderid = None

    return response, response_data, orderid


def place_smartorder_api(data, auth):
    """
    Place a smart order that manages position sizing automatically.
    """
    res = None

    symbol = data.get("symbol")
    exchange = data.get("exchange")
    product = data.get("product")
    position_size = int(data.get("position_size", "0"))

    # Get current open position for the symbol
    current_position = int(get_open_position(symbol, exchange, map_product_type(product), auth))

    logger.info(f"SmartOrder - Symbol: {symbol}, Exchange: {exchange}, Product: {product}")
    logger.info(f"SmartOrder - Target position_size: {position_size}, Current position: {current_position}")

    action = None
    quantity = 0

    # If both position_size and current_position are 0, place order if quantity > 0
    if position_size == 0 and current_position == 0 and int(data['quantity']) != 0:
        action = data['action']
        quantity = data['quantity']
        logger.info(f"SmartOrder - No position, placing new order: {action} {quantity}")
        res, response, orderid = place_order_api(data, auth)
        return res, response, orderid

    elif position_size == current_position:
        if int(data['quantity']) == 0:
            response = {"status": "success", "message": "No OpenPosition Found. Not placing Exit order."}
        else:
            response = {"status": "success", "message": "No action needed. Position size matches current position"}
        logger.info(f"SmartOrder - {response['message']}")
        orderid = None
        return res, response, orderid

    # Determine action based on position_size and current_position
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
        logger.info(f"SmartOrder - Calculated action: {action}, quantity: {quantity}")
        order_data = data.copy()
        order_data["action"] = action
        order_data["quantity"] = str(quantity)

        res, response, orderid = place_order_api(order_data, auth)
        logger.info(f"SmartOrder response: {response}")
        logger.info(f"SmartOrder orderid: {orderid}")

        return res, response, orderid


def close_all_positions(current_api_key, auth):
    """
    Close all open positions.
    """
    positions_response = get_positions(auth)

    if not positions_response.get('positionDetails'):
        return {"message": "No Open Positions Found"}, 200

    if positions_response.get('status') == 'Success':
        for position in positions_response['positionDetails']:
            # Get net quantity and handle Samco's direction via transactionType
            net_qty = int(position.get('netQuantity', 0))
            if net_qty == 0:
                continue

            transaction_type = position.get('transactionType', '')

            # Samco returns positive qty with transactionType indicating direction
            # BUY position -> SELL to close, SELL position -> BUY to close
            if transaction_type == 'SELL':
                action = 'BUY'  # Close short position
            else:
                action = 'SELL'  # Close long position

            quantity = abs(net_qty)

            # Get OpenAlgo symbol using tradingSymbol and exchange
            symbol = get_oa_symbol(position.get('tradingSymbol'), position.get('exchange'))
            logger.info(f"Close position: symbol={symbol}, action={action}, qty={quantity}")

            place_order_payload = {
                "apikey": current_api_key,
                "strategy": "Squareoff",
                "symbol": symbol,
                "action": action,
                "exchange": position['exchange'],
                "pricetype": "MARKET",
                "product": reverse_map_product_type(position.get('productCode')),
                "quantity": str(quantity)
            }

            logger.info(f"Close position payload: {place_order_payload}")

            res, response, orderid = place_order_api(place_order_payload, auth)

    return {'status': 'success', "message": "All Open Positions SquaredOff"}, 200


def cancel_order(orderid, auth):
    """
    Cancel an order by order ID.
    """
    client = get_httpx_client()

    headers = {
        'Accept': 'application/json',
        'x-session-token': auth
    }

    logger.info(f"Samco cancel order request for orderid: {orderid}")

    response = client.delete(
        f"{BASE_URL}/order/cancelOrder",
        headers=headers,
        params={"orderNumber": orderid}
    )

    response.status = response.status_code

    data = json.loads(response.text) if response.text else {}
    logger.info(f"Samco cancel order response: {data}")

    if data.get("status") == "Success":
        return {"status": "success", "orderid": orderid}, 200
    else:
        return {"status": "error", "message": data.get("statusMessage", "Failed to cancel order")}, response.status


def modify_order(data, auth):
    """
    Modify an existing order.
    """
    client = get_httpx_client()

    orderid = data['orderid']
    transformed_data = transform_modify_order_data(data)

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'x-session-token': auth
    }

    logger.info(f"Samco modify order payload: {transformed_data}")

    response = client.put(
        f"{BASE_URL}/order/modifyOrder/{orderid}",
        headers=headers,
        json=transformed_data
    )

    response.status = response.status_code

    response_data = json.loads(response.text) if response.text else {}
    logger.info(f"Samco modify order response: {response_data}")

    if response_data.get("status") == "Success":
        return {"status": "success", "orderid": response_data.get("orderNumber")}, 200
    else:
        return {"status": "error", "message": response_data.get("statusMessage", "Failed to modify order")}, response.status


def cancel_all_orders_api(data, auth):
    """
    Cancel all open orders.
    """
    order_book_response = get_order_book(auth)

    if order_book_response.get('status') != 'Success':
        return [], []

    # Filter orders that are in open or pending state (handle different casing)
    orders_to_cancel = [
        order for order in order_book_response.get('orderBookDetails', [])
        if order.get('orderStatus', '').lower() in ['open', 'pending', 'trigger pending']
    ]

    logger.info(f"Orders to cancel: {[order['orderNumber'] for order in orders_to_cancel]}")

    canceled_orders = []
    failed_cancellations = []

    for order in orders_to_cancel:
        orderid = order['orderNumber']
        cancel_response, status_code = cancel_order(orderid, auth)
        if status_code == 200:
            canceled_orders.append(orderid)
        else:
            failed_cancellations.append(orderid)

    return canceled_orders, failed_cancellations
