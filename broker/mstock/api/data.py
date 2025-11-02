from utils.httpx_client import get_httpx_client
from broker.mstock.mapping.order_data import transform_positions_data, transform_holdings_data

def get_positions(auth_token):
    api_key = os.getenv('BROKER_API_KEY')
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
        positions = response.json()
        return transform_positions_data(positions), None
    except Exception as e:
        return None, str(e)

def get_holdings(auth_token):
    api_key = os.getenv('BROKER_API_KEY')
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
        holdings = response.json()
        return transform_holdings_data(holdings), None
    except Exception as e:
        return None, str(e)
