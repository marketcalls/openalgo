import http.client
import json
import urllib.parse
from database.auth_db import get_auth_token
from database.token_db import get_token, get_br_symbol, get_symbol
from broker.definedge.mapping.transform_data import transform_data, map_product_type, reverse_map_product_type, transform_modify_order_data, reverse_map_exchange, map_exchange
from utils.logging import get_logger

logger = get_logger(__name__)

def get_api_response(endpoint, auth_token, method="GET", payload=''):
    """Generic API response handler for DefinedGe Securities"""
    api_session_key, susertoken, api_token = auth_token.split(":::")

    conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

    headers = {
        'Authorization': api_session_key,
        'Content-Type': 'application/json'
    }

    conn.request(method, f"/dart/v1{endpoint}", payload, headers)
    res = conn.getresponse()
    data = res.read()
    logger.info(f"API Response: {data.decode('utf-8')}")

    return json.loads(data.decode("utf-8"))

def get_order_book(auth_token):
    """Get order book from DefinedGe Securities"""
    return get_api_response("/orders", auth_token)

def get_trade_book(auth_token):
    """Get trade book from DefinedGe Securities"""
    return get_api_response("/trades", auth_token)

def get_positions(auth_token):
    """Get positions from DefinedGe Securities"""
    return get_api_response("/positions", auth_token)

def get_holdings(auth_token):
    """Get holdings from DefinedGe Securities"""
    return get_api_response("/holdings", auth_token)

def get_open_position(tradingsymbol, exchange, producttype, auth_token):
    """Get open position for a specific symbol"""
    # Convert Trading Symbol from OpenAlgo Format to Broker Format
    tradingsymbol = get_br_symbol(tradingsymbol, exchange)
    positions_data = get_positions(auth_token)
    logger.info(f"Positions data: {positions_data}")

    net_qty = '0'
    exchange = reverse_map_exchange(exchange)

    if positions_data.get('status') == 'SUCCESS' and positions_data.get('positions'):
        for position in positions_data['positions']:
            if (position.get('tradingsymbol') == tradingsymbol and
                position.get('exchange') == exchange and
                position.get('product_type') == producttype):

                net_qty = int(position.get('net_quantity', 0))
                break

    return net_qty

def place_order_api(data, auth_token):
    """Place order with DefinedGe Securities"""
    api_session_key, susertoken, api_token = auth_token.split(":::")

    conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

    # Transform data to DefinedGe format
    token_id = get_token(data['symbol'], data['exchange'])
    newdata = transform_data(data, token_id)

    payload = json.dumps(newdata)

    headers = {
        'Authorization': api_session_key,
        'Content-Type': 'application/json'
    }

    conn.request("POST", "/dart/v1/placeorder", payload, headers)

    try:
        res = conn.getresponse()
        response_data = json.loads(res.read().decode("utf-8"))

        orderid = response_data.get('order_id') if response_data.get('status') == 'SUCCESS' else None
        return res, response_data, orderid

    except Exception as e:
        logger.error(f"Error in place_order_api: {e}")
        return None, {"status": "FAILED", "error": str(e)}, None

def place_smartorder_api(data, auth_token):
    """Place smart order - delegates to regular order placement"""
    return place_order_api(data, auth_token)

def close_all_positions(current_api_key, auth_token):
    """Close all open positions"""
    try:
        positions_data = get_positions(auth_token)

        if positions_data.get('status') == 'SUCCESS' and positions_data.get('positions'):
            for position in positions_data['positions']:
                net_qty = int(position.get('net_quantity', 0))

                if net_qty != 0:
                    # Determine order type based on position
                    order_type = "SELL" if net_qty > 0 else "BUY"
                    quantity = abs(net_qty)

                    # Create order data for closing position
                    close_order_data = {
                        'symbol': get_symbol(position['tradingsymbol'], position['exchange']),
                        'exchange': map_exchange(position['exchange']),
                        'quantity': str(quantity),
                        'action': order_type,
                        'product': position['product_type'],
                        'pricetype': 'MARKET',
                        'price': '0'
                    }

                    # Place closing order
                    place_order_api(close_order_data, auth_token)

        return {"status": "success", "message": "All positions closed"}

    except Exception as e:
        logger.error(f"Error closing positions: {e}")
        return {"status": "error", "message": str(e)}

def cancel_order(orderid, auth_token):
    """Cancel an order"""
    api_session_key, susertoken, api_token = auth_token.split(":::")

    conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

    payload = json.dumps({"order_id": orderid})

    headers = {
        'Authorization': api_session_key,
        'Content-Type': 'application/json'
    }

    conn.request("POST", "/dart/v1/cancel", payload, headers)

    try:
        res = conn.getresponse()
        response_data = json.loads(res.read().decode("utf-8"))
        return response_data

    except Exception as e:
        logger.error(f"Error canceling order: {e}")
        return {"status": "FAILED", "error": str(e)}

def modify_order(data, auth_token):
    """Modify an existing order"""
    api_session_key, susertoken, api_token = auth_token.split(":::")

    conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

    # Transform modify order data
    newdata = transform_modify_order_data(data)
    payload = json.dumps(newdata)

    headers = {
        'Authorization': api_session_key,
        'Content-Type': 'application/json'
    }

    conn.request("POST", "/dart/v1/modify", payload, headers)

    try:
        res = conn.getresponse()
        response_data = json.loads(res.read().decode("utf-8"))
        return response_data

    except Exception as e:
        logger.error(f"Error modifying order: {e}")
        return {"status": "FAILED", "error": str(e)}

def cancel_all_orders_api(data, auth_token):
    """Cancel all open orders"""
    try:
        orders_data = get_order_book(auth_token)

        if orders_data.get('status') == 'SUCCESS' and orders_data.get('orders'):
            for order in orders_data['orders']:
                if order.get('order_status') in ['OPEN', 'PENDING']:
                    cancel_order(order['order_id'], auth_token)

        return {"status": "success", "message": "All orders cancelled"}

    except Exception as e:
        logger.error(f"Error cancelling all orders: {e}")
        return {"status": "error", "message": str(e)}
