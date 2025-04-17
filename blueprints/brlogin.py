from flask import Blueprint, request, redirect, url_for, render_template, session, jsonify, make_response
from flask import current_app as app
from limiter import limiter  # Import the limiter instance
from utils.config import get_broker_api_key, get_broker_api_secret, get_login_rate_limit_min, get_login_rate_limit_hour
from utils.auth_utils import handle_auth_success, handle_auth_failure
import http.client
import json
import jwt
import base64
import hashlib

BROKER_API_KEY = get_broker_api_key()
LOGIN_RATE_LIMIT_MIN = get_login_rate_limit_min()
LOGIN_RATE_LIMIT_HOUR = get_login_rate_limit_hour()

brlogin_bp = Blueprint('brlogin', __name__, url_prefix='/')

@brlogin_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(error="Rate limit exceeded"), 429

@brlogin_bp.route('/<broker>/callback', methods=['POST','GET'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def broker_callback(broker,para=None):
    print(f'Broker is {broker}')
    # Check if user is not in session first
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    if session.get('logged_in'):
        # Store broker in session and g
        session['broker'] = broker
        return redirect(url_for('dashboard_bp.dashboard'))

    broker_auth_functions = app.broker_auth_functions
    auth_function = broker_auth_functions.get(f'{broker}_auth')

    if not auth_function:
        return jsonify(error="Broker authentication function not found."), 404
    
    # Initialize feed_token to None by default
    feed_token = None
    
    if broker == 'fivepaisa':
        if request.method == 'GET':
            return render_template('5paisa.html')
        
        elif request.method == 'POST':
            clientcode = request.form.get('clientid')
            broker_pin = request.form.get('pin')
            totp_code = request.form.get('totp')

            auth_token, error_message = auth_function(clientcode, broker_pin, totp_code)
            forward_url = '5paisa.html'
        
    elif broker == 'angel':
        if request.method == 'GET':
            return render_template('angel.html')
        
        elif request.method == 'POST':
            clientcode = request.form.get('clientid')
            broker_pin = request.form.get('pin')
            totp_code = request.form.get('totp')
            auth_token, feed_token, error_message = auth_function(clientcode, broker_pin, totp_code)
            forward_url = 'angel.html'
    
    elif broker == 'aliceblue':
        if request.method == 'GET':
            return render_template('aliceblue.html')
        
        elif request.method == 'POST':
            print('Aliceblue Login Flow')
            userid = request.form.get('userid')
            conn = http.client.HTTPSConnection("ant.aliceblueonline.com")
            payload = json.dumps({
                "userId": userid
            })
            headers = {
                'Content-Type': 'application/json'
            }
            try:
                conn.request("POST", "/rest/AliceBlueAPIService/api/customer/getAPIEncpkey", payload, headers)
                res = conn.getresponse()
                data = res.read().decode("utf-8")
                data_dict = json.loads(data)
                print(data_dict)
                auth_token, error_message = auth_function(userid, data_dict['encKey'])
                forward_url = 'aliceblue.html'
            
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    elif broker=='fivepaisaxts':
        code = 'fivepaisaxts'
        print(f'The code is {code}')  
               
        # Fetch auth token, feed token and user ID
        auth_token, feed_token, user_id, error_message = auth_function(code)
        forward_url = 'broker.html'


    elif broker=='compositedge':
        try:
            # Get the raw data from the request
            if request.method == 'POST':
                # Handle form data
                if request.headers.get('Content-Type') == 'application/x-www-form-urlencoded':
                    raw_data = request.get_data().decode('utf-8')
                    
                    
                    # Extract session data from form
                    if raw_data.startswith('session='):
                        from urllib.parse import unquote
                        session_data = unquote(raw_data[8:])  # Remove 'session=' and URL decode
                        
                    else:
                        session_data = raw_data
                else:
                    session_data = request.get_data().decode('utf-8')
                
            else:
                session_data = request.args.get('session')
                
                
            if not session_data:
                
                return jsonify({"error": "No session data received"}), 400

            # Parse the session data
            try:
                             
                # Try to clean the data if it's malformed
                if isinstance(session_data, str):
                    # Remove any leading/trailing whitespace
                    session_data = session_data.strip()
                    
                    session_json = json.loads(session_data)
                    
                    # Handle double-encoded JSON
                    if isinstance(session_json, str):
                        session_json = json.loads(session_json)
                        
                else:
                    session_json = session_data
                    
                    
            except json.JSONDecodeError as e:
                
                return jsonify({
                    "error": f"Invalid JSON format: {str(e)}", 
                    "raw_data": session_data
                }), 400

            # Extract access token
            access_token = session_json.get('accessToken')
            #print(f'Access token is {access_token}')
            
            if not access_token:
                
                return jsonify({"error": "No access token found"}), 400
                
            # Fetch auth token, feed token and user ID
            auth_token, feed_token, user_id, error_message = auth_function(access_token)

            #print(f'Auth token is {auth_token}')
            #print(f'Feed token is {feed_token}')
            #print(f'User ID is {user_id}')
            forward_url = 'broker.html'

        except Exception as e:
            #print(f"Error in compositedge callback: {str(e)}")
            return jsonify({"error": f"Error processing request: {str(e)}"}), 500

    elif broker=='fyers':
        code = request.args.get('auth_code')
        print(f'The code is {code}')
        auth_token, error_message = auth_function(code)
        forward_url = 'broker.html'

    elif broker=='icici':
        full_url = request.full_path
        print(f'Full URL: {full_url}') 
        code = request.args.get('apisession')
        print(f'The code is {code}')
        auth_token, error_message = auth_function(code)
        forward_url = 'broker.html'

    elif broker=='iifl':
        code = 'iifl'
        print(f'The code is {code}')  
               
        # Fetch auth token, feed token and user ID
        auth_token, feed_token, user_id, error_message = auth_function(code)
        forward_url = 'broker.html'
    
    elif broker=='jainam':
        code = 'jainam'
        print(f'The code is {code}')  
               
        # Fetch auth token, feed token and user ID
        auth_token, feed_token, user_id, error_message = auth_function(code)
        forward_url = 'broker.html'

    elif broker=='jainampro':
        code = 'jainampro'
        print(f'The code is {code}')  
               
        # Fetch auth token, feed token and user ID
        auth_token, feed_token, user_id, error_message = auth_function(code)
        forward_url = 'broker.html'

    elif broker=='dhan':
        code = 'dhan'
        print(f'The code is {code}')
        auth_token, error_message = auth_function(code)
        forward_url = 'broker.html'

    elif broker == 'wisdom':
        code = 'wisdom'
        print(f'The code is {code}')
        auth_token, feed_token, user_id, error_message = auth_function(code)
        forward_url = 'broker.html'

    elif broker == 'zebu':  
        if request.method == 'GET':
            return render_template('zebu.html')
        
        elif request.method == 'POST':
            userid = request.form.get('userid')
            password = request.form.get('password')
            totp_code = request.form.get('totp')

            auth_token, error_message = auth_function(userid, password, totp_code)
            forward_url = 'zebu.html'

    elif broker == 'shoonya':  
        if request.method == 'GET':
            return render_template('shoonya.html')
        
        elif request.method == 'POST':
            userid = request.form.get('userid')
            password = request.form.get('password')
            totp_code = request.form.get('totp')

            auth_token, error_message = auth_function(userid, password, totp_code)
            forward_url = 'shoonya.html'

    elif broker == 'firstock':
        if request.method == 'GET':
            return render_template('firstock.html')
        
        elif request.method == 'POST':
            userid = request.form.get('userid')
            password = request.form.get('password')
            totp_code = request.form.get('totp')

            auth_token, error_message = auth_function(userid, password, totp_code)
            forward_url = 'firstock.html'

    elif broker == 'flattrade':
        code = request.args.get('code')
        client = request.args.get('client')  # Flattrade returns client ID as well
        print(f'The code is {code} for client {client}')
        auth_token, error_message = auth_function(code)  # Only pass the code parameter
        forward_url = 'broker.html'

    elif broker=='kotak':
        print(f"The Broker is {broker}")
        if request.method == 'GET':
            return render_template('kotak.html')
        
        elif request.method == 'POST':
            otp = request.form.get('otp')
            token = request.form.get('token')
            sid = request.form.get('sid')
            userid = request.form.get('userid')
            access_token = request.form.get('access_token')
            hsServerId = request.form.get('hsServerId')
            
            auth_token, error_message = auth_function(otp,token,sid,userid,access_token,hsServerId)
            forward_url = 'kotak.html'

    elif broker == 'paytm':
         request_token = request.args.get('requestToken')
         print(f'The request token is {request_token}')
         auth_token, error_message = auth_function(request_token)

    elif broker == 'pocketful':
        # Handle the OAuth2 authorization code from the callback
        auth_code = request.args.get('code')
        state = request.args.get('state')
        error = request.args.get('error')
        error_description = request.args.get('error_description')
        
        # Check if there was an error in the OAuth process
        if error:
            error_msg = f"OAuth error: {error}. {error_description if error_description else ''}"
            print(error_msg)
            return handle_auth_failure(error_msg, forward_url='broker.html')
        
        # Check if authorization code was provided
        if not auth_code:
            error_msg = "Authorization code not provided"
            print(error_msg)
            return handle_auth_failure(error_msg, forward_url='broker.html')
            
        print(f'Received authorization code: {auth_code}')
        # Exchange auth code for access token and fetch client_id
        auth_token, feed_token, user_id, error_message = auth_function(auth_code, state)
        forward_url = 'broker.html'
        

    else:
        code = request.args.get('code') or request.args.get('request_token')
        print(f'The code is {code}')
        auth_token, error_message = auth_function(code)
        forward_url = 'broker.html'
    
    if auth_token:
        # Store broker in session
        session['broker'] = broker
        print(f'Connected broker: {broker}')
        if broker == 'zerodha':
            auth_token = f'{BROKER_API_KEY}:{auth_token}'
        if broker == 'dhan':
            auth_token = f'{auth_token}'
        
        # For compositedge and pocketful, we have the user_id from authenticate_broker
        if broker == 'compositedge' or broker == 'pocketful':
            # Pass the feed token and user_id to handle_auth_success
            return handle_auth_success(auth_token, session['user'], broker, feed_token=feed_token, user_id=user_id)
        else:
            # Pass just the feed token to handle_auth_success (other brokers don't have user_id)
            return handle_auth_success(auth_token, session['user'], broker, feed_token=feed_token)
    else:
        return handle_auth_failure(error_message, forward_url=forward_url)
    

@brlogin_bp.route('/<broker>/loginflow', methods=['POST','GET'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def broker_loginflow(broker):
    # Check if user is not in session first
    if 'user' not in session:
        return redirect(url_for('auth.login'))

    if broker == 'kotak':
        # Get form data
        mobile_number = request.form.get('mobilenumber', '')
        password = request.form.get('password')

        # Strip any existing prefix and add +91
        mobile_number = mobile_number.replace('+91', '').strip()
        if not mobile_number.startswith('+91'):
            mobile_number = f'+91{mobile_number}'
        
        # First get the access token
        api_secret = get_broker_api_secret()
        auth_string = base64.b64encode(f"{BROKER_API_KEY}:{api_secret}".encode()).decode('utf-8')
        # Define the connection
        conn = http.client.HTTPSConnection("napi.kotaksecurities.com")

        # Define the payload
        payload = json.dumps({
            'grant_type': 'client_credentials'
        })

        # Define the headers with Basic Auth
        headers = {
            'accept': '*/*',
            'Content-Type': 'application/json',
            'Authorization': f'Basic {auth_string}'
        }

        # Make API request
        conn.request("POST", "/oauth2/token", payload, headers)

        # Get the response
        res = conn.getresponse()
        data = json.loads(res.read().decode("utf-8"))

        if 'access_token' in data:
            access_token = data['access_token']
            # Login with mobile number and password
            conn = http.client.HTTPSConnection("gw-napi.kotaksecurities.com")
            payload = json.dumps({
                "mobileNumber": mobile_number,
                "password": password
            })
            headers = {
                'accept': '*/*',
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {access_token}'
            }
            conn.request("POST", "/login/1.0/login/v2/validate", payload, headers)
            res = conn.getresponse()
            data = res.read().decode("utf-8")

            data_dict = json.loads(data)

            if 'data' in data_dict:
                token = data_dict['data']['token']
                sid = data_dict['data']['sid']
                hsServerId = data_dict['data']['hsServerId']
                decode_jwt = jwt.decode(token, options={"verify_signature": False})
                userid = decode_jwt.get("sub")

                para = {
                    "access_token": access_token,
                    "token": token,
                    "sid": sid,
                    "hsServerId": hsServerId,
                    "userid": userid
                }
                getKotakOTP(userid, access_token)
                return render_template('kotakotp.html', para=para)
            else:
                error_message = data_dict.get('message', 'Unknown error occurred')
                return render_template('kotak.html', error_message=error_message)
        
    return


def getKotakOTP(userid,access_token):
    conn = http.client.HTTPSConnection("gw-napi.kotaksecurities.com")
    payload = json.dumps({
    "userId": userid,
    "sendEmail": True,
    "isWhitelisted": True
    })
    headers = {
    'accept': '*/*',
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {access_token}'
    }
    conn.request("POST", "/login/1.0/login/otp/generate", payload, headers)
    res = conn.getresponse()
    data = res.read()
    
    return 'success'
