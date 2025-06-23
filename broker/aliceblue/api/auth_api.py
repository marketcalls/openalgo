import os
import hashlib
import json
import base64
import httpx
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def authenticate_broker(userid, encKey):
    try:
        # Fetching the necessary credentials from environment variables
        BROKER_API_KEY = os.environ.get("BROKER_API_KEY")
        BROKER_API_SECRET = os.environ.get("BROKER_API_SECRET")

        if not BROKER_API_SECRET or not BROKER_API_KEY:
            logger.error("API keys not found in environment variables")
            return None, "API keys not set in environment variables"
        
        logger.debug(f"Authenticating with AliceBlue for user {userid}")
        
        # Proper AliceBlue API authentication flow according to V2 API docs:        
        # Step 1: Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        # Step 2: Generate SHA-256 hash using the combination of User ID + API Key + Encryption Key
        # This is the pattern specified in their API docs
        logger.debug(f"Generating checksum for authentication")
        # The AliceBlue API V2 documentation specifies: User ID + API Key + Encryption Key
        # This is the official order specified in their documentation
        checksum_input = f"{userid}{BROKER_API_SECRET}{encKey}"
        logger.debug(f"Checksum input pattern: userId + apiSecret + encKey")
        checksum = hashlib.sha256(checksum_input.encode()).hexdigest()
        
        # Step 3: Prepare request payload with exact parameters matching their API documentation
        payload = {
                "userId": userid,
                "userData": checksum,
                "source": "WEB"
                }
        
        # Set the headers exactly as expected by their API
        headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            }
        
        # Step 4: Make the API request to get session ID
        logger.debug(f"Making getUserSID request to AliceBlue API")
        url = "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/customer/getUserSID"
        response = client.post(url, json=payload, headers=headers)
        
        logger.debug(f"AliceBlue API response status: {response.status_code}")
        data_dict = response.json()
        
        # Log full response for debugging
        logger.info(f"AliceBlue API response: {json.dumps(data_dict, indent=2)}")
        
        # Extract the session ID from the response
        # Handle all possible response formats from AliceBlue API
        
        # Case 1: Check if response has sessionID field (typical success case)
        if data_dict.get('sessionID'):
            logger.info(f"Authentication successful for user {userid}")
            return data_dict.get('sessionID'), None
            
        # Case 2: Check for specific error messages and handle them
        if 'emsg' in data_dict and data_dict['emsg']:
            error_msg = data_dict['emsg']
            # Special case handling for common errors
            if "User does not login" in error_msg:
                logger.error(f"User not logged in: {error_msg}")
                return None, f"User is not logged in. Please login to the AliceBlue platform first and then try again."
            elif "Invalid Input" in error_msg:
                logger.error(f"Invalid input error: {error_msg}")
                return None, f"Invalid input. Please check your user ID and API credentials."
            else:
                logger.error(f"API error: {error_msg}")
                return None, f"API error: {error_msg}"
                
        # Case 3: Handle status field
        if data_dict.get('stat') == 'Not ok':
            error_msg = data_dict.get('emsg', 'Unknown error occurred')
            logger.error(f"API returned Not ok status: {error_msg}")
            return None, f"API error: {error_msg}"
            
        # Case 4: Try to find any field that might contain the session token
        for field_name in ['sessionID', 'session_id', 'sessionId', 'token']:
            if field_name in data_dict and data_dict[field_name]:
                session_id = data_dict[field_name]
                logger.info(f"Found session ID in field {field_name}")
                return session_id, None
                
        # Case 5: If we got this far, we couldn't find a session ID
        logger.error(f"Couldn't extract session ID from response: {data}")
        return None, f"Failed to extract session ID from response. Please check API credentials and try again."
            
    except json.JSONDecodeError:
        # Handle invalid JSON response
        return None, "Invalid response format from AliceBlue API."
    except httpx.HTTPError as e:
        # Handle HTTPX connection errors
        return None, f"HTTP connection error: {str(e)}"
    except Exception as e:
        # General exception handling
        return None, f"An exception occurred: {str(e)}"