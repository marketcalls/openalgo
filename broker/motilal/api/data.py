import httpx
import json
import os
import pandas as pd
from datetime import datetime, timedelta
import urllib.parse
from database.token_db import get_br_symbol, get_token, get_oa_symbol
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_api_response(endpoint, auth, method="GET", payload=''):
    """Helper function to make API calls to Motilal Oswal"""
    AUTH_TOKEN = auth
    api_key = os.getenv('BROKER_API_SECRET')

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        'Authorization': AUTH_TOKEN,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'User-Agent': 'MOSL/V.1.1.0',
        'ApiKey': api_key,
        'ClientLocalIp': '1.2.3.4',
        'ClientPublicIp': '1.2.3.4',
        'MacAddress': '00:00:00:00:00:00',
        'SourceId': 'WEB',
        'OsName': 'Windows',
        'OsVersion': '10',
        'AppName': 'OpenAlgo',
        'AppVersion': '1.0.0'
    }

    if isinstance(payload, dict):
        payload = json.dumps(payload)

    url = f"https://openapi.motilaloswal.com{endpoint}"

    try:
        if method == "GET":
            response = client.get(url, headers=headers)
        elif method == "POST":
            response = client.post(url, headers=headers, content=payload)
        else:
            response = client.request(method, url, headers=headers, content=payload)

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        if response.status_code == 403:
            logger.debug(f"API returned 403 Forbidden. Headers: {headers}")
            logger.debug(f"Response text: {response.text}")
            raise Exception("Authentication failed. Please check your API key and auth token.")

        return json.loads(response.text)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse response. Status code: {response.status_code}")
        logger.debug(f"Response text: {response.text}")
        raise Exception(f"Failed to parse API response (status {response.status_code})")

class BrokerData:
    def __init__(self, auth_token):
        """Initialize Motilal Oswal data handler with authentication token"""
        self.auth_token = auth_token

    def get_quotes(self, symbol: str, exchange: str) -> dict:
        """
        Get real-time quotes for given symbol from Motilal Oswal.

        Args:
            symbol: Trading symbol (OpenAlgo format)
            exchange: Exchange (NSE, BSE, NFO, BFO, CDS, MCX)

        Returns:
            dict: Quote data with required fields
            {
                'bid': float,
                'ask': float,
                'open': float,
                'high': float,
                'low': float,
                'ltp': float,
                'prev_close': float,
                'volume': int,
                'oi': int
            }
        """
        try:
            # Get token for the symbol
            token = get_token(symbol, exchange)

            if not token:
                raise Exception(f"Token not found for symbol: {symbol}, exchange: {exchange}")

            # Map OpenAlgo exchange to Motilal exchange
            from broker.motilal.mapping.transform_data import map_exchange
            motilal_exchange = map_exchange(exchange)

            # Prepare payload for Motilal's LTP API
            payload = {
                "exchange": motilal_exchange,
                "scripcode": int(token)
            }

            logger.debug(f"Fetching quotes for {symbol} ({token}) on {motilal_exchange}")

            # Make API call using the helper function
            response = get_api_response("/rest/report/v1/getltpdata",
                                      self.auth_token,
                                      "POST",
                                      payload)

            # Check response status
            if response.get('status') != 'SUCCESS':
                raise Exception(f"Error from Motilal API: {response.get('message', 'Unknown error')}, errorcode: {response.get('errorcode', '')}")

            # Extract quote data from response
            data = response.get('data', {})
            if not data:
                raise Exception("No quote data received from Motilal API")

            # IMPORTANT: Motilal returns values in paisa, convert to rupees (divide by 100)
            # Handle the case where values might be 0 or None
            def convert_paisa_to_rupees(value):
                """Convert paisa to rupees, handling None and 0 values"""
                if value is None or value == 0:
                    return 0.0
                return float(value) / 100.0

            # Return quote in OpenAlgo common format
            return {
                'bid': convert_paisa_to_rupees(data.get('bid', 0)),
                'ask': convert_paisa_to_rupees(data.get('ask', 0)),
                'open': convert_paisa_to_rupees(data.get('open', 0)),
                'high': convert_paisa_to_rupees(data.get('high', 0)),
                'low': convert_paisa_to_rupees(data.get('low', 0)),
                'ltp': convert_paisa_to_rupees(data.get('ltp', 0)),
                'prev_close': convert_paisa_to_rupees(data.get('close', 0)),  # Motilal uses 'close' for previous close
                'volume': int(data.get('volume', 0)),
                'oi': 0  # Motilal LTP API doesn't provide OI data
            }

        except Exception as e:
            logger.error(f"Error fetching quotes for {symbol} on {exchange}: {str(e)}")
            raise Exception(f"Error fetching quotes: {str(e)}")
