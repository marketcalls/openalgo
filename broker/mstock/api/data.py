import httpx
import json
import os
from utils.httpx_client import get_httpx_client

def get_positions(api_key, auth_token):
    """
    Retrieves the user's positions.
    """
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
    }

    try:
        client = get_httpx_client()
        response = client.get(
            'https://api.mstock.trade/openapi/typea/portfolio/positions',
            headers=headers,
        )
        response.raise_for_status()
        return response.json(), None
    except httpx.HTTPStatusError as e:
        return None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return None, str(e)

def get_holdings(api_key, auth_token):
    """
    Retrieves the user's holdings.
    """
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
    }

    try:
        client = get_httpx_client()
        response = client.get(
            'https://api.mstock.trade/openapi/typea/portfolio/holdings',
            headers=headers,
        )
        response.raise_for_status()
        return response.json(), None
    except httpx.HTTPStatusError as e:
        return None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return None, str(e)

def get_funds(api_key, auth_token):
    """
    Retrieves the user's funds.
    """
    headers = {
        'X-Mirae-Version': '1',
        'Authorization': f'token {api_key}:{auth_token}',
    }

    try:
        client = get_httpx_client()
        response = client.get(
            'https://api.mstock.trade/openapi/typea/user/fundsummary',
            headers=headers,
        )
        response.raise_for_status()
        return response.json(), None
    except httpx.HTTPStatusError as e:
        return None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return None, str(e)
