import os
import requests

def authenticate_broker(access_token=None):
    try:
        # For Pocketful, access token is generated directly from their dashboard
        # and passed to this function or retrieved from environment variable
        if not access_token:
            access_token = os.getenv('BROKER_ACCESS_TOKEN')
        
        # If no access token provided or found in environment, return error
        if not access_token:
            return None, None, None, "No access token provided. Please generate an access token from the Pocketful dashboard."
            
        # Pocketful's base URL for API calls
        base_url = 'https://trade.pocketful.in'
        
        # Endpoint to validate the access token
        validate_url = f"{base_url}/user"
        
        # Setting the headers with the access token
        headers = {
            'Authorization': f'Bearer {access_token}'
        }
        
        # Performing a GET request to validate the token
        response = requests.get(validate_url, headers=headers)
        
        if response.status_code != 200:
            # Token validation failed
            try:
                error_detail = response.json()
                error_message = error_detail.get('message', 'Authentication failed. Please check your access token.')
            except:
                error_message = f"Authentication failed with status code: {response.status_code}"
            
            return None, None, None, f"API error: {error_message}"
        
        # Token is valid, now fetch the client_id from trading_info endpoint
        trading_info_url = f"{base_url}/api/v1/user/trading_info"
        
        # Make request to trading_info endpoint
        try:
            info_response = requests.get(trading_info_url, headers=headers)
            info_response.raise_for_status()  # Raise exception for non-200 status codes
            
            # Parse the response JSON
            info_data = info_response.json()
            
            if info_data.get('status') != 'success':
                return access_token, None, None, f"Failed to fetch client ID: {info_data.get('message', 'Unknown error')}"
            
            # Extract client_id from the response
            client_id = info_data.get('data', {}).get('client_id')
            
            if not client_id:
                return access_token, None, None, "Client ID not found in response"
            
            # Return token, None for feed_token (not used by Pocketful), and client_id
            return access_token, None, client_id, None
            
        except requests.exceptions.RequestException as e:
            return access_token, None, None, f"Error fetching client ID: {str(e)}"
            
    except Exception as e:
        # Exception handling
        return None, None, None, f"An exception occurred: {str(e)}"
