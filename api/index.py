from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask import session
import os
from dotenv import load_dotenv
import http.client
import mimetypes
import pyotp
import json
import time
import pytz

app = Flask(__name__)
load_dotenv()

# Environment variables
app.secret_key = os.getenv('APP_KEY')

@app.route('/login', methods=['GET', 'POST'])
def login():
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
                session['user'] = username 
                
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

                # Store tokens in session for later use
                session['refreshToken'] = refreshToken
                session['AUTH_TOKEN'] = AUTH_TOKEN
                session['FEED_TOKEN'] = FEED_TOKEN
                
                # Redirect or display tokens (for educational purposes, adjust as needed)
                return redirect(url_for('login')) 
                
            except Exception as e:
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })
        else:
            # (implement error messaging as needed)
            return "Invalid credentials", 401

        
@app.route('/logout')
def logout():
    # Remove tokens and user information from session
    session.pop('refreshToken', None)
    session.pop('AUTH_TOKEN', None)
    session.pop('FEED_TOKEN', None)
    session.pop('user', None)  # Remove 'user' from session if exists

    # Redirect to login page after logout
    return redirect(url_for('login'))

@app.route('/placeorder', methods=['POST'])
def place_order():
    try:
        # Extracting form data or JSON data from the POST request
        data = request.json if request.is_json else request.form
        
        # Retrieve AUTH_TOKEN and API_KEY from session or environment
        AUTH_TOKEN = session.get('AUTH_TOKEN') or os.getenv('AUTH_TOKEN')
        api_key = os.getenv('BROKER_API_KEY')
        
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
            'X-PrivateKey': api_key
        }

        # Preparing the payload with data received from the request
        payload = json.dumps({
            "variety": data.get('variety', 'NORMAL'),
            "tradingsymbol": data['tradingsymbol'],
            "symboltoken": data['symboltoken'],
            "transactiontype": data['transactiontype'],
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


if __name__ == '__main__':
    app.run(debug=True)
