from flask import Flask, request, Response, jsonify, redirect, render_template , session, url_for,  render_template_string
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
from database.auth_db import upsert_auth, get_auth_token



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
    return render_template('dashboard.html')

        
@app.route('/logout')
def logout():
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

        # Preparing the payload with data received from the request
        payload = json.dumps({
            "variety": data.get('variety', 'NORMAL'),
            "tradingsymbol": data['tradingsymbol'],
            "symboltoken": data['symboltoken'],
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
        
        # Check if the order was successfully placed and return the response
        if res.status == 200:
            return jsonify({
                'status': 'success',
                'data': response_data
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to place order',
                'details': response_data
            }), res.status
    except KeyError as e:
        return jsonify({'status': 'error', 'message': f'Missing mandatory field: {e}'}), 400
    except Exception as e:
        return jsonify({'status': 'error', 'message': f"Order placement failed: {e}"}), 500
    
@app.route('/download')
def download_data():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    global token_df
    # Fetch data from the URL
    url = 'https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json'
    data = requests.get(url).json()
    
    # Convert the JSON data to a pandas DataFrame
    token_df = pd.DataFrame.from_dict(data)
    
    # Save the DataFrame to a file or do other processing if needed
    
    # Render the download.html template
    return render_template('download.html')

# Search page
@app.route('/token')
def token():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
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

    # Pass the data to the orderbook.html template
    return render_template('orderbook.html', order_data=order_data['data'])



if __name__ == '__main__':
    app.run(debug=True)
