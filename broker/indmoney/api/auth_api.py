import httpx
import json
import os
from utils.httpx_client import get_httpx_client
from broker.indmoney.api.baseurl import get_url, BASE_URL



def authenticate_broker(code):
    try:
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        REDIRECT_URL = os.getenv('REDIRECT_URL')
        
        # For IndMoney, the access token is directly provided in BROKER_API_SECRET
        # No OAuth flow needed - just return the access token
        if BROKER_API_SECRET:
            return BROKER_API_SECRET, None
        else:
            return None, "No access token found in BROKER_API_SECRET environment variable"
            
    except Exception as e:
        return None, f"An exception occurred: {str(e)}"

