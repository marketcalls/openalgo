import os
from utils.httpx_client import get_httpx_client

def get_holdings(api_key, access_token):
    """
    Retrieves the holdings for the mstock account.
    """
    try:
        url = 'https://api.mstock.trade/openapi/typea/portfolio/holdings'
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
            return None, response_data.get('message', 'Failed to fetch holdings.')
    except Exception as e:
        return None, f"An exception occurred while fetching holdings: {str(e)}"

def get_positions(api_key, access_token):
    """
    Retrieves the net positions for the mstock account.
    """
    try:
        url = 'https://api.mstock.trade/openapi/typea/portfolio/positions'
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
            return None, response_data.get('message', 'Failed to fetch positions.')
    except Exception as e:
        return None, f"An exception occurred while fetching positions: {str(e)}"
