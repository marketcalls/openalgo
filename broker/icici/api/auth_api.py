from breeze_connect import BreezeConnect
import os

def login_breeze(api_key: str, api_secret: str, totp: str = None) -> dict:
    """
    Authenticates to Breeze API and returns the session object or error.
    
    Parameters:
    - api_key: Breeze App Key
    - api_secret: Breeze API Secret
    - totp: Optional TOTP (if enabled)

    Returns:
    - dict: Session info or error message
    """
    try:
        breeze = BreezeConnect(api_key=api_key)
        
        # Generate session
        session_resp = breeze.generate_session(api_secret=api_secret)
        
        # Optionally, set TOTP (not always required)
        if totp:
            breeze.set_totp(totp)

        # Return session details
        return {
            "success": True,
            "session_token": breeze.session_token,
            "api_key": api_key,
            "status": session_resp.get("Status", "Unknown")
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }
