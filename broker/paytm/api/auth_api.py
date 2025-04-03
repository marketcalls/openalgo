import os
from utils.httpx_client import get_httpx_client

def authenticate_broker(request_token):
    """
    Authenticate with Paytm Money broker API.
    
    The authentication flow works as follows:
    1. Navigate to Paytm Money API endpoint: https://login.paytmmoney.com/merchant-login?apiKey={api_key}&state={state_key}
    2. After successful login, a request_token is returned as URL parameter to the registered redirect URL
    3. Use the request_token to generate an access_token
    
    Args:
        code: The request token received from the redirect URL after successful login
    
    Returns:
        tuple: (access_token, error_message)
            - access_token: The token to use for subsequent API calls
            - error_message: Error details if authentication fails, None on success
    """
    try:
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        
        url = 'https://developer.paytmmoney.com/accounts/v2/gettoken'
        data = {
            'api_key': BROKER_API_KEY,
            'api_secret_key': BROKER_API_SECRET,
            'request_token': request_token
        }
        headers = {'Content-Type': 'application/json'}
        client = get_httpx_client()
        response = client.post(url, json=data, headers=headers)

        if response.status_code == 200:
            response_data = response.json()
            if 'access_token' in response_data:
                return response_data['access_token'], None
            else:
                return None, "Authentication succeeded but no access token was returned. Please check the response."
        else:
            # Parsing the error message from the API response
            error_detail = response.json()  # Assuming the error is in JSON format
            error_messages = error_detail.get('errors', [])
            detailed_error_message = "; ".join([error['message'] for error in error_messages])
            return None, f"API error: {error_messages}" if detailed_error_message else "Authentication failed. Please try again."
    except Exception as e:
        return None, f"An exception occurred: {str(e)}"
