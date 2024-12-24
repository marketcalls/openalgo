import requests
import hashlib
import json
import os

def sha256_hash(text):
    """Generate SHA256 hash."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def authenticate_broker(code, password=None, totp_code=None):
    """
    Authenticate with Flattrade using OAuth flow
    """
    try:
        full_api_key = os.getenv('BROKER_API_KEY')
        print(f"Full API Key: {full_api_key}")  # Debug print
        
        # Split the API key to get the actual key part
        BROKER_API_KEY = full_api_key.split(':::')[1]
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        
        print(f"Using API Key: {BROKER_API_KEY}")  # Debug print
        print(f"Request Code: {code}")  # Debug print
        
        # Create the security hash as per Flattrade docs
        hash_input = f"{BROKER_API_KEY}{code}{BROKER_API_SECRET}"
        security_hash = hashlib.sha256(hash_input.encode()).hexdigest()
        
        print(f"Hash Input: {hash_input}")  # Debug print
        print(f"Security Hash: {security_hash}")  # Debug print
        
        url = 'https://authapi.flattrade.in/trade/apitoken'
        data = {
            'api_key': BROKER_API_KEY,
            'request_code': code,
            'api_secret': security_hash
        }
        
        print(f"Request Data: {data}")  # Debug print
        
        response = requests.post(url, json=data)
        
        print(f"Response Status: {response.status_code}")  # Debug print
        print(f"Response Content: {response.text}")  # Debug print
        
        if response.status_code == 200:
            response_data = response.json()
            if response_data.get('stat') == 'Ok' and 'token' in response_data:
                return response_data['token'], None
            else:
                error_msg = response_data.get('emsg', 'Authentication failed without specific error')
                print(f"Auth Error: {error_msg}")  # Debug print
                return None, error_msg
        else:
            try:
                error_detail = response.json()
                error_msg = f"API error: {error_detail.get('emsg', 'Unknown error')}"
            except:
                error_msg = f"API error: Status {response.status_code}, Response: {response.text}"
            print(f"Request Error: {error_msg}")  # Debug print
            return None, error_msg
            
    except Exception as e:
        print(f"Exception: {str(e)}")  # Debug print
        return None, f"An exception occurred: {str(e)}"

def authenticate_broker_oauth(code):
    try:
        BROKER_API_KEY = os.getenv('BROKER_API_KEY').split(':::')[1]  # Get only the API key part
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        
        # Create the security hash as per Flattrade docs
        # api_secret:SHA-256 hash of (api_key + request_token + api_secret)
        hash_input = f"{BROKER_API_KEY}{code}{BROKER_API_SECRET}"
        security_hash = hashlib.sha256(hash_input.encode()).hexdigest()
        
        url = 'https://authapi.flattrade.in/trade/apitoken'
        data = {
            'api_key': BROKER_API_KEY,
            'request_code': code,
            'api_secret': security_hash
        }
        
        response = requests.post(url, json=data)
        
        if response.status_code == 200:
            response_data = response.json()
            if response_data.get('stat') == 'Ok' and 'token' in response_data:
                return response_data['token'], None
            else:
                return None, response_data.get('emsg', 'Authentication failed without specific error')
        else:
            error_detail = response.json()
            return None, f"API error: {error_detail.get('emsg', 'Unknown error')}"
            
    except Exception as e:
        return None, f"An exception occurred: {str(e)}"