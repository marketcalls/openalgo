import httpx
import json
import os
from utils.httpx_client import get_httpx_client

def place_order(api_key, auth_token, variety, tradingsymbol, exchange, transaction_type, quantity, product, order_type, price=0, trigger_price=0, squareoff=0, stoploss=0, trailing_stoploss=0, disclosed_quantity=0, validity='DAY', amo='NO', ret='DAY'):
    """
    Places an order with the broker.
    """
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
        'Content-Type': 'application/json',
    }

    order_params = {
        "variety": variety,
        "tradingsymbol": tradingsymbol,
        "transactiontype": transaction_type,
        "exchange": exchange,
        "ordertype": order_type,
        "producttype": product,
        "duration": validity,
        "price": str(price),
        "squareoff": str(squareoff),
        "stoploss": str(stoploss),
        "quantity": str(quantity)
    }

    try:
        client = get_httpx_client()
        response = client.post(
            'https://api.mstock.trade/openapi/typea/orders',
            headers=headers,
            json=order_params
        )
        response.raise_for_status()
        return response.json(), None
    except httpx.HTTPStatusError as e:
        return None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return None, str(e)

def modify_order(api_key, auth_token, order_id, variety, tradingsymbol, exchange, transaction_type, quantity, product, order_type, price=0, trigger_price=0):
    """
    Modifies an existing order.
    """
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
        'Content-Type': 'application/json',
    }

    order_params = {
        "orderId": order_id,
        "variety": variety,
        "tradingsymbol": tradingsymbol,
        "transactiontype": transaction_type,
        "exchange": exchange,
        "ordertype": order_type,
        "producttype": product,
        "duration": "DAY",
        "price": str(price),
        "quantity": str(quantity)
    }

    try:
        client = get_httpx_client()
        response = client.put(
            f'https://api.mstock.trade/openapi/typea/orders',
            headers=headers,
            json=order_params
        )
        response.raise_for_status()
        return response.json(), None
    except httpx.HTTPStatusError as e:
        return None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return None, str(e)

def cancel_order(api_key, auth_token, order_id, variety):
    """
    Cancels an existing order.
    """
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
    }

    try:
        client = get_httpx_client()
        response = client.delete(
            f'https://api.mstock.trade/openapi/typea/orders/{order_id}?variety={variety}',
            headers=headers,
        )
        response.raise_for_status()
        return response.json(), None
    except httpx.HTTPStatusError as e:
        return None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return None, str(e)

def get_order_book(api_key, auth_token):
    """
    Retrieves the order book.
    """
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
    }

    try:
        client = get_httpx_client()
        response = client.get(
            'https://api.mstock.trade/openapi/typea/orders',
            headers=headers,
        )
        response.raise_for_status()
        return response.json(), None
    except httpx.HTTPStatusError as e:
        return None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return None, str(e)

def get_trade_book(api_key, auth_token):
    """
    Retrieves the trade book.
    """
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
    }

    try:
        client = get_httpx_client()
        response = client.get(
            'https://api.mstock.trade/openapi/typea/trades',
            headers=headers,
        )
        response.raise_for_status()
        return response.json(), None
    except httpx.HTTPStatusError as e:
        return None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return None, str(e)
