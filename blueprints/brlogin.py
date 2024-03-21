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
from api.auth_api import authenticate_broker
from database.auth_db import upsert_auth
from database.master_contract_db import master_contract_download





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
    



@brlogin_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(error="Rate limit exceeded"), 429

@brlogin_bp.route('/zerodha/callback', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def upstox_callback():
    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))
    request_token = request.args.get('request_token')
    if request_token:
        auth_token, error_message = authenticate_broker(request_token)
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
                return render_template('zerodha.html', error_message="Failed to store authentication token. Please try again.")
        else:
            # Use the error message returned from the authenticate_broker function
            print(f"Authentication error: {error_message}")
            return render_template('zerodha.html', error_message="Broker Authentication Failed")
    return "No code received", 400





