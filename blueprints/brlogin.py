from flask import Blueprint, request, redirect, url_for, render_template, session, jsonify, make_response
from flask import current_app as app
from limiter import limiter  # Import the limiter instance
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pytz
import os
import json
from threading import Thread
import requests
from utils import get_session_expiry_time

from broker.angel.api.auth_api import authenticate_broker as angel_auth
from broker.upstox.api.auth_api import authenticate_broker as upstox_auth
from broker.zerodha.api.auth_api import authenticate_broker as zerodha_auth
from database.auth_db import upsert_auth
#from database.master_contract_db import master_contract_download





# Load environment variables
load_dotenv()

#Get Broker Key
BROKER_API_KEY = os.getenv('BROKER_API_KEY')


# Access environment variables
LOGIN_RATE_LIMIT_MIN = os.getenv("LOGIN_RATE_LIMIT_MIN", "5 per minute")
LOGIN_RATE_LIMIT_HOUR = os.getenv("LOGIN_RATE_LIMIT_HOUR", "25 per hour")


brlogin_bp = Blueprint('brlogin', __name__, url_prefix='/')



def async_master_contract_download(user):
    """
    Asynchronously download the master contract and emit a WebSocket event upon completion.
    """
    #master_contract_status = master_contract_download()  # Assuming this is a blocking call
    
    print("Processing Master Contract Download")
    return True

    #return master_contract_status
    


@brlogin_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(error="Rate limit exceeded"), 429


@brlogin_bp.route('/callback/angel', methods=['GET', 'POST'])
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

        print(clientcode)

        auth_token, error_message = angel_auth(clientcode, broker_pin, totp_code)
        print(auth_token)
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





@brlogin_bp.route('/upstox/callback', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def upstox_callback():
    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))
    code = request.args.get('code')
    if code:
        auth_token, error_message = upstox_auth(code)
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
                return render_template('broker.html', error_message="Failed to store authentication token. Please try again.")
        else:
            # Use the error message returned from the authenticate_broker function
            print(f"Authentication error: {error_message}")
            return render_template('broker.html', error_message="Broker Authentication Failed")
    return "No code received", 400




@brlogin_bp.route('/zerodha/callback', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def zerodha_callback():
    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))
    request_token = request.args.get('request_token')
    if request_token:
        auth_token, error_message = zerodha_auth(request_token)
        auth_token = f'{BROKER_API_KEY}:{auth_token}'
        #print(auth_token)
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
                return render_template('broker.html', error_message="Failed to store authentication token. Please try again.")
        else:
            # Use the error message returned from the authenticate_broker function
            print(f"Authentication error: {error_message}")
            return render_template('broker.html', error_message="Broker Authentication Failed")
    return "No code received", 400





