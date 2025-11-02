import os
from utils.httpx_client import get_httpx_client
from typing import List

def get_market_ohlc(api_key: str, access_token: str, instruments: List[str]):
    """
    Fetches OHLC market data for given instruments.
    """
    try:
        url = 'https://api.mstock.trade/openapi/typea/instruments/quote/ohlc'
        headers = {
            'X-Mirae-Version': '1',
            'Authorization': f'token {api_key}:{access_token}',
        }
        params = {'i': instruments}
        client = get_httpx_client()
        response = client.get(url, headers=headers, params=params)
        response.raise_for_status()
        response_data = response.json()
        if response_data.get('status') == 'success':
            return response_data['data'], None
        else:
            return None, response_data.get('message', 'Failed to fetch OHLC data.')
    except Exception as e:
        return None, f"An exception occurred while fetching OHLC data: {str(e)}"

def get_market_ltp(api_key: str, access_token: str, instruments: List[str]):
    """
    Fetches LTP market data for given instruments.
    """
    try:
        url = 'https://api.mstock.trade/openapi/typea/instruments/quote/ltp'
        headers = {
            'X-Mirae-Version': '1',
            'Authorization': f'token {api_key}:{access_token}',
        }
        params = {'i': instruments}
        client = get_httpx_client()
        response = client.get(url, headers=headers, params=params)
        response.raise_for_status()
        response_data = response.json()
        if response_data.get('status') == 'success':
            return response_data['data'], None
        else:
            return None, response_data.get('message', 'Failed to fetch LTP data.')
    except Exception as e:
        return None, f"An exception occurred while fetching LTP data: {str(e)}"

def get_historical_data(api_key: str, access_token: str, exchange: str, instrument_token: str, interval: str, from_date: str, to_date: str):
    """
    Fetches historical candle data.
    """
    try:
        url = f'https://api.mstock.trade/openapi/typea/instruments/historical/{exchange}/{instrument_token}/{interval}'
        headers = {
            'X-Mirae-Version': '1',
            'Authorization': f'token {api_key}:{access_token}',
        }
        params = {
            'from': from_date,
            'to': to_date
        }
        client = get_httpx_client()
        response = client.get(url, headers=headers, params=params)
        response.raise_for_status()
        response_data = response.json()
        if response_data.get('status') == 'success':
            return response_data['data'], None
        else:
            return None, response_data.get('message', 'Failed to fetch historical data.')
    except Exception as e:
        return None, f"An exception occurred while fetching historical data: {str(e)}"
