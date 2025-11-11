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
    api_key = os.getenv('BROKER_API_SECRET')

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

def place_order(auth_token, data):
    """
    Places an order with the broker.
    """
    api_key = os.getenv('BROKER_API_SECRET')
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

def modify_order(auth_token, data):
    """
    Modifies an existing order.
    """
    api_key = os.getenv('BROKER_API_SECRET')
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

def cancel_order(auth_token, order_id, variety):
    """
    Cancels an existing order.
    """
    api_key = os.getenv('BROKER_API_SECRET')
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
    order_data = get_api_response("/orders", auth)
    if (
        order_data
        and isinstance(order_data, dict)
        and "status" in order_data
        and "data" in order_data
        and isinstance(order_data["data"], list)
    ):
        for order in order_data["data"]:
            tradingsymbol = str(order.get("tradingsymbol", "")).upper()
            if tradingsymbol.endswith("CE") or tradingsymbol.endswith("PE"):
                if order.get("exchange", "").upper() == "NSE":
                    order["exchange"] = "NFO"

        return {
            "status": order_data["status"],
            "data": order_data["data"]
        }

    # fallback if structure invalid
    return {
        "status": order_data.get("status", "error") if isinstance(order_data, dict) else "error",
        "data": []
    }

def get_trade_book(auth):
    trades_data = get_api_response("/typea/tradebook", auth)

    if (
        trades_data
        and isinstance(trades_data, dict)
        and "status" in trades_data
        and "data" in trades_data
        and isinstance(trades_data["data"], list)
    ):
        for trade in trades_data["data"]:
            tradingsymbol = str(trade.get("tradingsymbol", "")).upper()
            if tradingsymbol.endswith("CE") or tradingsymbol.endswith("PE"):
                if trade.get("exchange", "").upper() == "NSE":
                    trade["exchange"] = "NFO"

        return {
            "status": trades_data["status"],
            "data": trades_data["data"]
        }

    # fallback if structure invalid
    return {
        "status": trades_data.get("status", "error") if isinstance(trades_data, dict) else "error",
        "data": []
    }
    
def get_positions(auth):
    positions_data = get_api_response("/portfolio/positions", auth)
    
    if (
        positions_data
        and isinstance(positions_data, dict)
        and "status" in positions_data
        and "data" in positions_data
        and isinstance(positions_data["data"], dict)
        and "net" in positions_data["data"]
    ):

        for position in positions_data["data"]["net"]:
            tradingsymbol = str(position.get("tradingsymbol", "")).upper()
            if tradingsymbol.endswith("CE") or tradingsymbol.endswith("PE"):
                if position.get("exchange", "").upper() == "NSE":
                    position["exchange"] = "NFO"

        return {
            "status": positions_data["status"],
            "data": positions_data["data"]["net"]
        }
    
    # If data missing or malformed, still preserve status if possible
    return {
        "status": positions_data.get("status", "error") if isinstance(positions_data, dict) else "error",
        "data": []
    }

def get_holdings(auth):
    return get_api_response("/portfolio/holdings",auth)