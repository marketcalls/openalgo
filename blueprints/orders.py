from flask import Blueprint, jsonify, request, render_template, session, redirect, url_for
from database.token_db import get_token
from database.auth_db import get_auth_token
import http.client
import json
import os

# Define the blueprint
orders_bp = Blueprint('orders_bp', __name__, url_prefix='/')



@orders_bp.route('/orderbook')
def orderbook():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
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
    conn.request("GET", "/rest/secure/angelbroking/order/v1/getOrderBook", '', headers)
    res = conn.getresponse()
    data = res.read()
    order_data = json.loads(data.decode("utf-8"))

    # Check if 'data' is None
    if order_data['data'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        order_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        order_data = order_data['data']
        
    
        # Initialize counters
    total_buy_orders = total_sell_orders = total_completed_orders = total_open_orders = total_rejected_orders = 0

    if order_data:
        for order in order_data:
            if order['transactiontype'] == 'BUY':
                total_buy_orders += 1
            elif order['transactiontype'] == 'SELL':
                total_sell_orders += 1
            
            if order['status'] == 'complete':
                total_completed_orders += 1
            elif order['status'] == 'open':
                total_open_orders += 1
            elif order['status'] == 'rejected':
                total_rejected_orders += 1


    # Pass the data (or lack thereof) to the orderbook.html template
    return render_template('orderbook.html', order_data=order_data, total_buy_orders=total_buy_orders, 
                           total_sell_orders=total_sell_orders, total_completed_orders=total_completed_orders,
                             total_open_orders=total_open_orders, total_rejected_orders=total_rejected_orders)


@orders_bp.route('/tradebook')
def tradebook():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
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
    conn.request("GET", "/rest/secure/angelbroking/order/v1/getTradeBook", '', headers)

    res = conn.getresponse()
    data = res.read()
    tradebook_data = json.loads(data.decode("utf-8"))

    # Check if 'data' is None
    if tradebook_data['data'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        tradebook_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        tradebook_data = tradebook_data['data']


    return render_template('tradebook.html', tradebook_data=tradebook_data)


@orders_bp.route('/positions')
def positions():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
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
    conn.request("GET", "/rest/secure/angelbroking/order/v1/getPosition", '', headers)

    res = conn.getresponse()
    data = res.read()
    positions_data = json.loads(data.decode("utf-8"))

        # Check if 'data' is None
    if positions_data['data'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        positions_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        positions_data = positions_data['data']

    return render_template('positions.html', positions_data=positions_data)

@orders_bp.route('/holdings')
def holdings():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
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
    conn.request("GET", "/rest/secure/angelbroking/portfolio/v1/getAllHolding", '', headers)

    res = conn.getresponse()
    data = res.read()
    holdings_data = json.loads(data.decode("utf-8"))

            # Check if 'data' is None
    if holdings_data['data'] is None:
        # Handle the case where there is no data
        # For example, you might want to display a message to the user
        # or pass an empty list or dictionary to the template.
        print("No data available.")
        holdings_data = {}  # or set it to an empty list if it's supposed to be a list
    else:
        holdings_data = holdings_data['data']

    return render_template('holdings.html', holdings_data=holdings_data)


