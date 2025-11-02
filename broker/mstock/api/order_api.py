import os
from utils.httpx_client import get_httpx_client

def place_order(api_key, access_token, variety, tradingsymbol, exchange, transaction_type, order_type, quantity, product, validity, price=None, tag=None):
    """
    Places an order with mstock.
    """
    try:
        url = f'https://api.mstock.trade/openapi/typea/orders/{variety}'
        headers = {
            'X-Mirae-Version': '1',
            'Authorization': f'token {api_key}:{access_token}',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        data = {
            'tradingsymbol': tradingsymbol,
            'exchange': exchange,
            'transaction_type': transaction_type,
            'order_type': order_type,
            'quantity': quantity,
            'product': product,
            'validity': validity,
        }
        if price:
            data['price'] = price
        if tag:
            data['tag'] = tag

        client = get_httpx_client()
        response = client.post(url, headers=headers, data=data)
        response.raise_for_status()
        response_data = response.json()
        if response_data.get('status') == 'success':
            return response_data['data'], None
        else:
            return None, response_data.get('message', 'Order placement failed.')
    except Exception as e:
        return None, f"An exception occurred during order placement: {str(e)}"

def modify_order(api_key, access_token, order_id, order_type=None, quantity=None, price=None, validity=None, disclosed_quantity=None, trigger_price=None):
    """
    Modifies a pending order.
    """
    try:
        url = f'https://api.mstock.trade/openapi/typea/orders/regular/{order_id}'
        headers = {
            'X-Mirae-Version': '1',
            'Authorization': f'token {api_key}:{access_token}',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        data = {}
        if order_type:
            data['order_type'] = order_type
        if quantity:
            data['quantity'] = quantity
        if price:
            data['price'] = price
        if validity:
            data['validity'] = validity
        if disclosed_quantity:
            data['disclosed_quantity'] = disclosed_quantity
        if trigger_price:
            data['trigger_price'] = trigger_price

        client = get_httpx_client()
        response = client.put(url, headers=headers, data=data)
        response.raise_for_status()
        response_data = response.json()
        if response_data.get('status') == 'success':
            return response_data['data'], None
        else:
            return None, response_data.get('message', 'Order modification failed.')
    except Exception as e:
        return None, f"An exception occurred during order modification: {str(e)}"

def cancel_order(api_key, access_token, order_id):
    """
    Cancels a pending order.
    """
    try:
        url = f'https://api.mstock.trade/openapi/typea/orders/regular/{order_id}'
        headers = {
            'X-Mirae-Version': '1',
            'Authorization': f'token {api_key}:{access_token}',
        }
        client = get_httpx_client()
        response = client.delete(url, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        if response_data.get('status') == 'success':
            return response_data['data'], None
        else:
            return None, response_data.get('message', 'Order cancellation failed.')
    except Exception as e:
        return None, f"An exception occurred during order cancellation: {str(e)}"

def get_order_book(api_key, access_token):
    """
    Retrieves the order book.
    """
    try:
        url = 'https://api.mstock.trade/openapi/typea/orders'
        headers = {
            'X-Mirae-Version': '1',
            'Authorization': f'token {api_key}:{access_token}',
        }
        client = get_httpx_client()
        response = client.get(url, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        if response_data.get('status') == 'success':
            return response_data['data'], None
        else:
            return None, response_data.get('message', 'Failed to fetch order book.')
    except Exception as e:
        return None, f"An exception occurred while fetching the order book: {str(e)}"
