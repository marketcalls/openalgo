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
from api.auth_api import authenticate_broker

# Load environment variables
load_dotenv()

# Access environment variables
LOGIN_RATE_LIMIT_MIN = os.getenv("LOGIN_RATE_LIMIT_MIN", "5 per minute")
LOGIN_RATE_LIMIT_HOUR = os.getenv("LOGIN_RATE_LIMIT_HOUR", "25 per hour")

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
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def login():

    if 'user' in session:
            return redirect(url_for('auth.angel_login'))
    
    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))

    if request.method == 'GET':
        return render_template('login.html')
    elif request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        login_username = os.getenv('LOGIN_USERNAME')
        login_password = os.getenv('LOGIN_PASSWORD')

        if username == login_username and password == login_password:
            session['user'] = login_username  # Set the username in the session
            print("login success")
            # Redirect to broker login without marking as fully logged in
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401


@auth_bp.route('/angel', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def angel_login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))
    if request.method == 'GET':
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        return render_template('angel.html')
    elif request.method == 'POST':
        # Extract broker credentials from the form
        clientcode = request.form['clientid']
        broker_pin = request.form['pin']
        totp_code = request.form['totp']  

        auth_token, error_message = authenticate_broker(clientcode, broker_pin, totp_code)
        
        if auth_token:    
                        
            # Set session parameters for full authentication
            session['logged_in'] = True
            app.config['PERMANENT_SESSION_LIFETIME'] = get_session_expiry_time()
            session.permanent = True
            session['AUTH_TOKEN'] = auth_token  # Store the auth token in the session for further use

            # Store the auth token in the database
            inserted_id = upsert_auth(session['user'], auth_token)
            if inserted_id:
                print(f"Database record upserted with ID: {inserted_id}")
                # Start async master contract download
                thread = Thread(target=async_master_contract_download, args=(session['user'],))
                thread.start()
                return redirect(url_for('dashboard_bp.dashboard'))
            else:
                print("Failed to upsert auth token")
                return render_template('angel.html', error_message="Failed to store authentication token. Please try again.")
        else:
            # Use the error message returned from the authenticate_broker function
            print(f"Authentication error: {error_message}")
            return render_template('angel.html', error_message="Broker Authentication Failed")


@auth_bp.route('/logout')
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
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

