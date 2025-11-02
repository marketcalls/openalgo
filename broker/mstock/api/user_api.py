import os
from utils.httpx_client import get_httpx_client

def get_fund_summary(api_key, access_token):
    """
    Fetches the fund summary for the user.
    """
    try:
        url = 'https://api.mstock.trade/openapi/typea/user/fundsummary'
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
            return None, response_data.get('message', 'Failed to fetch fund summary.')
    except Exception as e:
        return None, f"An exception occurred while fetching fund summary: {str(e)}"

def get_mstock_user_details(api_key, access_token):
    """
    Orchestrates fetching mstock user details.
    """
    try:
        if not access_token:
            return None, "Access token not provided. Please authenticate first."

        funds, error = get_fund_summary(api_key, access_token)
        if error:
            return None, error

        # The mstock API doesn't seem to have a separate user profile endpoint,
        # so for now, we'll just return the fund summary.
        return {'funds': funds}, None

    except Exception as e:
        return None, f"An exception occurred while fetching mstock user details: {str(e)}"
