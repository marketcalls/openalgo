import http.client
import json
from utils.logging import get_logger

logger = get_logger(__name__)

def authenticate_broker(api_token, api_secret, otp):
    """
    Authenticate with DefinedGe Securities broker
    Returns: (auth_token, error_message)
    """
    try:
        from broker.definedge.api.auth_api import authenticate_broker as auth_broker
        return auth_broker(api_token, api_secret, otp)
    except Exception as e:
        logger.error(f"Authentication failed: {e}")
        return None, str(e)

def get_quotes(symbol, exchange, auth_token):
    """Get real-time quotes for a symbol"""
    try:
        api_session_key, susertoken, api_token = auth_token.split(":::")

        conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

        # Get token for the symbol
        from database.token_db import get_token
        token_id = get_token(symbol, exchange)

        headers = {
            'Authorization': api_session_key,
            'Content-Type': 'application/json'
        }

        # DefinedGe uses token-based quote requests
        payload = json.dumps({
            "exchange": exchange,
            "token": token_id
        })

        conn.request("POST", "/dart/v1/quotes", payload, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")

        return json.loads(data)

    except Exception as e:
        logger.error(f"Error getting quotes: {e}")
        return {"status": "error", "message": str(e)}

def get_security_info(symbol, exchange, auth_token):
    """Get security information"""
    try:
        api_session_key, susertoken, api_token = auth_token.split(":::")

        conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

        headers = {
            'Authorization': api_session_key,
            'Content-Type': 'application/json'
        }

        payload = json.dumps({
            "exchange": exchange,
            "tradingsymbol": symbol
        })

        conn.request("POST", "/dart/v1/security_info", payload, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")

        return json.loads(data)

    except Exception as e:
        logger.error(f"Error getting security info: {e}")
        return {"status": "error", "message": str(e)}

def get_margin_info(auth_token):
    """Get margin information"""
    try:
        api_session_key, susertoken, api_token = auth_token.split(":::")

        conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

        headers = {
            'Authorization': api_session_key,
            'Content-Type': 'application/json'
        }

        conn.request("GET", "/dart/v1/margin", '', headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")

        return json.loads(data)

    except Exception as e:
        logger.error(f"Error getting margin info: {e}")
        return {"status": "error", "message": str(e)}

def get_limits(auth_token):
    """Get account limits"""
    try:
        api_session_key, susertoken, api_token = auth_token.split(":::")

        conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

        headers = {
            'Authorization': api_session_key,
            'Content-Type': 'application/json'
        }

        conn.request("GET", "/dart/v1/limits", '', headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")

        return json.loads(data)

    except Exception as e:
        logger.error(f"Error getting limits: {e}")
        return {"status": "error", "message": str(e)}
