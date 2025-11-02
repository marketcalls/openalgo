import httpx
from utils.httpx_client import get_httpx_client
from broker.mstock.mapping.transform_data import transform_data, transform_modify_order_data
from broker.mstock.mapping.order_data import transform_order_data, transform_tradebook_data

def place_order(api_key, auth_token, data):
    """
    Places an order with the broker.
    """
    order_params = transform_data(data)
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
        'Content-Type': 'application/json',
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

def modify_order(api_key, auth_token, data):
    """
    Modifies an existing order.
    """
    order_params = transform_modify_order_data(data)
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
        'Content-Type': 'application/json',
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
        order_book = response.json()
        return transform_order_data(order_book), None
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
        trade_book = response.json()
        return transform_tradebook_data(trade_book), None
    except httpx.HTTPStatusError as e:
        return None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return None, str(e)
