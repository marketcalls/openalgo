import http.client
import json
import os
from utils.logging import get_logger

logger = get_logger(__name__)

def totp_login(mobile_number, ucc, totp, access_token):
    """
    Step 2a: TOTP Login - Authenticate with mobile, UCC and TOTP
    Returns view token and view sid for MPIN validation
    
    Endpoint: POST https://mis.kotaksecurities.com/login/1.0/tradeApiLogin
    """
    try:
        logger.info(f"TOTP Login for UCC: {ucc}, Mobile: {mobile_number[:6]}***")
        
        conn = http.client.HTTPSConnection("mis.kotaksecurities.com")
        payload = json.dumps({
            "mobileNumber": mobile_number,  # Format: +91XXXXXXXXXX
            "ucc": ucc,                     # 5-character client code
            "totp": totp                    # 6-digit TOTP from authenticator
        })
        headers = {
            'Authorization': access_token,   # Plain access token (no Bearer)
            'neo-fin-key': 'neotradeapi',   # Static value
            'Content-Type': 'application/json'
        }
        
        logger.debug(f"Making TOTP login request to: https://mis.kotaksecurities.com/login/1.0/tradeApiLogin")
        conn.request("POST", "/login/1.0/tradeApiLogin", payload, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")
        
        logger.info(f"TOTP Login Response Status: {res.status}")
        logger.debug(f"TOTP Login Response: {data}")
        
        data_dict = json.loads(data)
        
        # Check for successful response
        if (data_dict.get('data') and 
            data_dict['data'].get('status') == 'success' and 
            data_dict['data'].get('kType') == 'View'):
            
            view_token = data_dict['data']['token']  # Save as VIEW_TOKEN
            view_sid = data_dict['data']['sid']      # Save as VIEW_SID
            
            logger.info("TOTP Login successful - received view tokens")
            return view_token, view_sid, None
        else:
            error_msg = data_dict.get('message', 'TOTP login failed')
            logger.error(f"TOTP Login failed: {error_msg}")
            return None, None, error_msg
            
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON response in TOTP login: {e}")
        return None, None, f"Invalid response format: {e}"
    except Exception as e:
        logger.error(f"Error in TOTP login: {e}")
        return None, None, str(e)

def mpin_validate(mpin, access_token, view_token, view_sid):
    """
    Step 2b: MPIN Validation - Complete authentication with MPIN
    Returns trading token, trading sid, and base URL
    
    Endpoint: POST https://mis.kotaksecurities.com/login/1.0/tradeApiValidate
    """
    try:
        logger.info("MPIN Validation - upgrading to trading access")
        
        conn = http.client.HTTPSConnection("mis.kotaksecurities.com")
        payload = json.dumps({
            "mpin": mpin  # 6-digit MPIN
        })
        headers = {
            'Authorization': access_token,   # Same access token from Step 1
            'neo-fin-key': 'neotradeapi',   # Static value
            'sid': view_sid,                # VIEW_SID from Step 2a
            'Auth': view_token,             # VIEW_TOKEN from Step 2a
            'Content-Type': 'application/json'
        }
        
        logger.debug(f"Making MPIN validation request to: https://mis.kotaksecurities.com/login/1.0/tradeApiValidate")
        conn.request("POST", "/login/1.0/tradeApiValidate", payload, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")
        
        logger.info(f"MPIN Validate Response Status: {res.status}")
        logger.info(f"MPIN Validate Response: {data}")
        
        data_dict = json.loads(data)
        
        # Check for successful response
        if (data_dict.get('data') and 
            data_dict['data'].get('status') == 'success' and 
            data_dict['data'].get('kType') == 'Trade'):
            
            trading_token = data_dict['data']['token']      # Save as TRADING_TOKEN
            trading_sid = data_dict['data']['sid']          # Save as TRADING_SID  
            api_base_url = data_dict['data']['baseUrl']     # Base URL from API response
            user_id = data_dict['data'].get('ucc', '')      # User's UCC
            
            logger.info(f"MPIN Validation successful - API returned baseUrl: {api_base_url}")
            
            # Use the API-returned baseUrl as per documentation
            # The baseUrl is dynamic and should always come from the API response
            use_base_url = api_base_url
            
            logger.info(f"Using API-returned baseUrl: {use_base_url}")
            logger.info(f"Full API response data: {data_dict['data']}")
            
            # Create auth string: trading_token:::trading_sid:::use_base_url:::access_token
            auth_string = f"{trading_token}:::{trading_sid}:::{use_base_url}:::{access_token}"
            logger.info(f"AUTH TOKEN CREATED: {trading_token[:10]}...:::{trading_sid}:::{use_base_url}:::{access_token[:10]}...")
            return auth_string, user_id, None
        else:
            error_msg = data_dict.get('message', 'MPIN validation failed')
            logger.error(f"MPIN Validation failed: {error_msg}")
            return None, None, error_msg
            
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON response in MPIN validation: {e}")
        return None, None, f"Invalid response format: {e}"
    except Exception as e:
        logger.error(f"Error in MPIN validation: {e}")
        return None, None, str(e)

def authenticate_broker(mobile_number, ucc, totp, mpin, access_token):
    """
    Complete two-step authentication process for Kotak Neo API v2
    Returns: (auth_token_string, user_id, error_message)
    
    Auth token format: trading_token:::trading_sid:::base_url:::access_token
    """
    try:
        logger.info("Starting Kotak Neo API v2 authentication process")
        
        # Step 1: TOTP Login - Get view tokens
        logger.info("Step 1: TOTP Login")
        view_token, view_sid, error = totp_login(mobile_number, ucc, totp, access_token)
        if error:
            logger.error(f"TOTP Login failed: {error}")
            return None, None, error
            
        logger.info("TOTP Login successful, proceeding to MPIN validation")
        
        # Step 2: MPIN Validation - Get trading tokens and base URL
        logger.info("Step 2: MPIN Validation")
        auth_token, user_id, error = mpin_validate(mpin, access_token, view_token, view_sid)
        if error:
            logger.error(f"MPIN Validation failed: {error}")
            return None, None, error
            
        logger.info("Authentication completed successfully")
        return auth_token, user_id, None
        
    except Exception as e:
        logger.error(f"Error in authenticate_broker: {e}")
        return None, None, str(e)