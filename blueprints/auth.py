# auth.py

from flask import Blueprint, request, redirect, url_for, render_template, session, jsonify, make_response
from flask import current_app as app
from limiter import limiter  # Import the limiter instance
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
import os
import pyotp
import http.client
import json
from threading import Thread
from database.auth_db import upsert_auth
from database.master_contract_db import master_contract_download

# Load environment variables
load_dotenv()

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

def async_master_contract_download(user):
    """
    Asynchronously download the master contract and emit a WebSocket event upon completion.
    """
    master_contract_status = master_contract_download()  # Assuming this is a blocking call
    return master_contract_status
    



def get_session_expiry_time():
    now_utc = datetime.now(pytz.timezone('UTC'))
    now_ist = now_utc.astimezone(pytz.timezone('Asia/Kolkata'))
    print(now_ist)
    target_time_ist = now_ist.replace(hour=3, minute=00, second=0, microsecond=0)
    if now_ist > target_time_ist:
        target_time_ist += timedelta(days=1)
    remaining_time = target_time_ist - now_ist
    return remaining_time

@auth_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(error="Rate limit exceeded"), 429


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
@limiter.limit("25 per hour")
def login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))

    
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
                session['logged_in'] = True

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

                session.modified = True

                

                #writing to database
                
                inserted_id = upsert_auth(login_username, AUTH_TOKEN)
                if inserted_id is not None:
                    print(f"Database Upserted record with ID: {inserted_id}")
                    thread = Thread(target=async_master_contract_download, args=(session['user'],))
                    thread.start()
                    # Send a response that indicates a successful login and an immediate redirect
                    return jsonify({'status': 'success', 'message': 'Login successful'})

                else:
                    print("Failed to upsert auth token")

                

        
            except Exception as e:
                
                return jsonify({
                    'status': 'error',
                    'message': str(e)
                })
        else:
            # (implement error messaging as needed)
            return "Invalid credentials", 401
        


@auth_bp.route('/logout')
def logout():
        if session.get('logged_in'):
            username = os.getenv('LOGIN_USERNAME')
            
            #writing to database      
            inserted_id = upsert_auth(username, "", revoke=True)
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
        return redirect(url_for('auth.login'))

