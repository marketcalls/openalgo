from flask import Flask, request, Response, jsonify, redirect, render_template , session, url_for,  render_template_string, send_from_directory
import requests
import os
from dotenv import load_dotenv
import http.client
import mimetypes
import pyotp
import json
import time
import pytz
import pandas as pd
from datetime import datetime, timedelta
import psycopg2

import sys
from pathlib import Path

# Add the parent directory to sys.path to find the database module
sys.path.append(str(Path(__file__).resolve().parents[1]))

# Now you can do a direct import
from database.auth_db import upsert_auth, get_auth_token, ensure_auth_table_exists
from database.token_db import get_token


app = Flask(__name__)

def get_session_expiry_time():
    now_utc = datetime.now(pytz.timezone('UTC'))
    now_ist = now_utc.astimezone(pytz.timezone('Asia/Kolkata'))
    print(now_ist)
    target_time_ist = now_ist.replace(hour=3, minute=00, second=0, microsecond=0)
    if now_ist > target_time_ist:
        target_time_ist += timedelta(days=1)
    remaining_time = target_time_ist - now_ist
    return remaining_time


load_dotenv()



# Environment variables
app.secret_key = os.getenv('APP_KEY')


# Initialize the placeholder as None
token_df = None


@app.route('/')
def home():
    return render_template('index.html')

@app.route('/docs/')
def docs():
    return send_from_directory('../docs', 'index.html')

@app.route('/docs/<path:filename>')
def docs_file(filename):
    return send_from_directory('../docs', filename)



@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    
    if request.method == 'GET':
        # Render the login form when the route is accessed with GET
        return render_template('login.html')
    elif request.method == 'POST':
        # Process form submission
        username = request.form['username']
        password = request.form['password']
        login_username = os.getenv('LOGIN_USERNAME')
        login_password = os.getenv('LOGIN_PASSWORD')
        
        if username == login_username and password == login_password:
            try:
                session['user'] = login_username 

                # Dynamically set session lifetime to time until 03:00 AM IST
                app.config['PERMANENT_SESSION_LIFETIME'] = get_session_expiry_time()
                session.permanent = True  # Make the session permanent to use the custom lifetime

                
                # New login method
                api_key = os.getenv('BROKER_API_KEY')
                clientcode = os.getenv('BROKER_USERNAME')
                broker_pin = os.getenv('BROKER_PIN')
                token = os.getenv('BROKER_TOKEN')  # Assuming TOTP_CODE is stored in BROKER_TOKEN
                totp = pyotp.TOTP(token).now()

                conn = http.client.HTTPSConnection("apiconnect.angelbroking.com")
                payload = json.dumps({
                    "clientcode": clientcode,
                    "password": broker_pin,
                    "totp": totp
                })
                headers = {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'X-UserType': 'USER',
                    'X-SourceID': 'WEB',
                    'X-ClientLocalIP': 'CLIENT_LOCAL_IP',  # These values should be replaced with actual data or handled accordingly
                    'X-ClientPublicIP': 'CLIENT_PUBLIC_IP',
                    'X-MACAddress': 'MAC_ADDRESS',
                    'X-PrivateKey': api_key
                }

                conn.request("POST", "/rest/auth/angelbroking/user/v1/loginByPassword", payload, headers)
                res = conn.getresponse()
                data = res.read()
                mydata = data.decode("utf-8")

                data_dict = json.loads(mydata)

                
                refreshToken = data_dict['data']['refreshToken']
                AUTH_TOKEN = data_dict['data']['jwtToken']
                FEED_TOKEN = data_dict['data']['feedToken']

                #check for existence of the table
                if not ensure_auth_table_exists():
                    return jsonify({
                        'status': 'error',
                        'message': 'Failed to ensure auth table exists'
                    }), 500

                #writing to database
                
                inserted_id = upsert_auth(login_username, AUTH_TOKEN)
                if inserted_id is not None:
                    print(f"Database Upserted record with ID: {inserted_id}")
                else:
                    print("Failed to upsert auth token")

                # Store tokens in session for later use
                session['refreshToken'] = refreshToken
                session['AUTH_TOKEN'] = AUTH_TOKEN
                session['FEED_TOKEN'] = FEED_TOKEN
                session['logged_in'] = True

                app.config['AUTH_TOKEN'] = AUTH_TOKEN
                
                # Redirect or display tokens (for educational purposes, adjust as needed)
                return redirect(url_for('dashboard'))
                            
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })
        else:
            # (implement error messaging as needed)
            return "Invalid credentials", 401


# Dashboard route, loads after successful login
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    login_username = os.getenv('LOGIN_USERNAME')

    AUTH_TOKEN = get_auth_token(login_username)
    if AUTH_TOKEN is not None:
        print(f"The auth value for {login_username} is: {AUTH_TOKEN}")
    else:
        print(f"No record found for {login_username}.")
        


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
    conn.request("GET", "/rest/secure/angelbroking//user/v1/getRMS", '', headers)

    res = conn.getresponse()
    data = res.read()
    margin_data = json.loads(data.decode("utf-8"))

    # Print the type and content of margin_data['data']
    print(f"Type: {type(margin_data['data'])}")
    print(f"Content: {margin_data['data']}")

    # Assuming margin_data['data'] is a dictionary as it should be
    for key, value in margin_data['data'].items():
        if value is not None and isinstance(value, str):
            try:
                # Only try to convert strings that represent numbers
                margin_data['data'][key] = "{:.2f}".format(float(value))
            except ValueError:
                # If there is a ValueError, it means the value can't be converted to a float
                pass


    return render_template('dashboard.html', margin_data=margin_data['data'])

        
@app.route('/logout')
def logout():
        if session.get('logged_in'):
            username = os.getenv('LOGIN_USERNAME')
            
            #writing to database      
            inserted_id = upsert_auth(username, "")
            if inserted_id is not None:
                print(f"Database Upserted record with ID: {inserted_id}")
            else:
                print("Failed to upsert auth token")
            
            # Remove tokens and user information from session
            session.pop('refreshToken', None)
            session.pop('AUTH_TOKEN', None)
            session.pop('FEED_TOKEN', None)
            session.pop('user', None)  # Remove 'user' from session if exists
            session.pop('logged_in', None)
    
            # Redirect to login page after logout
        return redirect(url_for('login'))

@app.route('/placeorder', methods=['POST'])
def place_order():
    
    try:
        # Extracting form data or JSON data from the POST request
        data = request.json

        login_username = os.getenv('LOGIN_USERNAME')

        AUTH_TOKEN = get_auth_token(login_username)
        if AUTH_TOKEN is not None:
            print(f"The auth value for {login_username} is: {AUTH_TOKEN}")
        else:
            print(f"No record found for {login_username}.")
        
        # Retrieve AUTH_TOKEN and API_KEY from session or environment
        
        print(f'Auth Token : {AUTH_TOKEN}')
        print(f'API Request : {data}')
        
        
        # Prepare headers with the AUTH_TOKEN and other details
        headers = {
            'Authorization': f'Bearer {AUTH_TOKEN}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'X-UserType': 'USER',
            'X-SourceID': 'WEB',
            'X-ClientLocalIP': 'CLIENT_LOCAL_IP',  # These values should be dynamically determined or managed accordingly
            'X-ClientPublicIP': 'CLIENT_PUBLIC_IP',
            'X-MACAddress': 'MAC_ADDRESS',
            'X-PrivateKey': data['apikey']
        }

        token = get_token(data['tradingsymbol'],data['exchange'])

        # Preparing the payload with data received from the request
        payload = json.dumps({
            "variety": data.get('variety', 'NORMAL'),
            "tradingsymbol": data['tradingsymbol'],
            "symboltoken": token,
            "transactiontype": data['transactiontype'].upper(),
            "exchange": data['exchange'],
            "ordertype": data.get('ordertype', 'MARKET'),
            "producttype": data.get('producttype', 'INTRADAY'),
            "duration": data.get('duration', 'DAY'),
            "price": data.get('price', '0'),
            "squareoff": data.get('squareoff', '0'),
            "stoploss": data.get('stoploss', '0'),
            "quantity": data['quantity']
        })

        # Making the HTTP request to place the order
        conn = http.client.HTTPSConnection("apiconnect.angelbroking.com")
        conn.request("POST", "/rest/secure/angelbroking/order/v1/placeOrder", payload, headers)
        
        # Processing the response
        res = conn.getresponse()
        data = res.read()
        response_data = json.loads(data.decode("utf-8"))
        
        # Check if the 'data' field is not null and the order was successfully placed
        if res.status == 200 and response_data.get('data'):
            order_id = response_data['data'].get('orderid')  # Extracting the orderid from response
            if order_id:
                return jsonify({
                    'status': 'success',
                    'orderid': order_id
                })
            else:
                # In case 'orderid' is not in the 'data'
                return jsonify({
                    'status': 'error',
                    'message': 'Order placed but order ID not found in response',
                    'details': response_data
                }), 500
        else:
            # If 'data' is null or status is not 200, extract the message and return as error
            message = response_data.get('message', 'Failed to place order')
            return jsonify({
                'status': 'error',
                'message': message,
                
            }), res.status if res.status != 200 else 500  # Use the API's status code, unless it's 200 but 'data' is null
    
    except KeyError as e:
        return jsonify({'status': 'error', 'message': f'Missing mandatory field: {e}'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Order placement failed: {e}"}), 500
    

# Search page
@app.route('/token')
def token():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    
    global token_df
    # Fetch data from the URL
    url = 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
    data = requests.get(url).json()
    
    # Convert the JSON data to a pandas DataFrame
    token_df = pd.DataFrame.from_dict(data)

    return render_template('token.html')


@app.route('/search')
def search():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    symbol = request.args.get('symbol')
    results = token_df[token_df['symbol'].str.contains(symbol, case=False)]
    if results.empty:
        return "No matching symbols found."
    else:
        # Change to render_template and pass results to the template
        return render_template('search.html', results=results)

@app.route('/orderbook')
def orderbook():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    login_username = os.getenv('LOGIN_USERNAME')

    AUTH_TOKEN = get_auth_token(login_username)
    if AUTH_TOKEN is not None:
        print(f"The auth value for {login_username} is: {AUTH_TOKEN}")
    else:
        print(f"No record found for {login_username}.")

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

    # Pass the data (or lack thereof) to the orderbook.html template
    return render_template('orderbook.html', order_data=order_data)


@app.route('/tradebook')
def tradebook():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    login_username = os.getenv('LOGIN_USERNAME')

    AUTH_TOKEN = get_auth_token(login_username)
    if AUTH_TOKEN is not None:
        print(f"The auth value for {login_username} is: {AUTH_TOKEN}")
    else:
        print(f"No record found for {login_username}.")
        


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


@app.route('/positions')
def positions():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    login_username = os.getenv('LOGIN_USERNAME')

    AUTH_TOKEN = get_auth_token(login_username)
    if AUTH_TOKEN is not None:
        print(f"The auth value for {login_username} is: {AUTH_TOKEN}")
    else:
        print(f"No record found for {login_username}.")
        


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

@app.route('/holdings')
def holdings():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    login_username = os.getenv('LOGIN_USERNAME')

    AUTH_TOKEN = get_auth_token(login_username)
    if AUTH_TOKEN is not None:
        print(f"The auth value for {login_username} is: {AUTH_TOKEN}")
    else:
        print(f"No record found for {login_username}.")
        


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





if __name__ == '__main__':
    app.run(debug=True)
