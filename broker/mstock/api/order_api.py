import httpx
import json
import os
from utils.httpx_client import get_httpx_client
from broker.mstock.mapping.transform_data import transform_data, transform_modify_order_data
from broker.mstock.mapping.order_data import transform_order_data, transform_tradebook_data
from utils.logging import get_logger
logger = get_logger(__name__)

def get_api_response(endpoint, auth, method="GET", payload=''):
    auth_token = auth
    api_key = os.getenv('BROKER_API_KEY')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
        'Content-Type': 'application/json',
    }
    
    url = f"https://api.mstock.trade/openapi/typea{endpoint}"
    
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
        logger.info(f"data from {endpoint}: {response.text}")
        return json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse JSON response from {endpoint}: {response.text}")
        return {}

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

def get_order_book(auth):
    return get_api_response("/orders",auth)

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
    
def get_positions(auth):
    return get_api_response("/portfolio/positions",auth)

def get_holdings(auth):
    return get_api_response("/portfolio/holdings",auth)