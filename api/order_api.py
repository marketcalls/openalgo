import http.client
import json
import os
from database.auth_db import get_auth_token

def get_api_response(endpoint):
    login_username = os.getenv('LOGIN_USERNAME')
    AUTH_TOKEN = get_auth_token(login_username)
    api_key = os.getenv('BROKER_API_KEY')

    conn = http.client.HTTPSConnection("apiconnect.angelbroking.com")
    headers = {
      'Authorization': f'Bearer {AUTH_TOKEN}',
      'Content-Type': 'application/json',
      'Accept': 'application/json',
      'X-UserType': 'USER',
      'X-SourceID': 'WEB',
      'X-ClientLocalIP': 'CLIENT_LOCAL_IP',
      'X-ClientPublicIP': 'CLIENT_PUBLIC_IP',
      'X-MACAddress': 'MAC_ADDRESS',
      'X-PrivateKey': api_key
    }
    conn.request("GET", endpoint, '', headers)
    res = conn.getresponse()
    data = res.read()
    return json.loads(data.decode("utf-8"))

def get_order_book():
    return get_api_response("/rest/secure/angelbroking/order/v1/getOrderBook")

def get_trade_book():
    return get_api_response("/rest/secure/angelbroking/order/v1/getTradeBook")

def get_positions():
    return get_api_response("/rest/secure/angelbroking/order/v1/getPosition")

def get_holdings():
    return get_api_response("/rest/secure/angelbroking/portfolio/v1/getAllHolding")
