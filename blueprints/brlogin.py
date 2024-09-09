from flask import Blueprint, request, redirect, url_for, render_template, session, jsonify, make_response
from flask import current_app as app
from limiter import limiter  # Import the limiter instance
from utils.config import get_broker_api_key, get_broker_api_secret, get_login_rate_limit_min, get_login_rate_limit_hour
from utils.auth_utils import handle_auth_success, handle_auth_failure
import http.client
import json
import jwt
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
    if session.get('logged_in'):
        # Store broker in session and g
        session['broker'] = broker
        return redirect(url_for('dashboard_bp.dashboard'))

    broker_auth_functions = app.broker_auth_functions
    auth_function = broker_auth_functions.get(f'{broker}_auth')

    if not auth_function:
        return jsonify(error="Broker authentication function not found."), 404
    
    if broker == 'fivepaisa':
        if request.method == 'GET':
            if 'user' not in session:
                return redirect(url_for('auth.login'))
            return render_template('5paisa.html')
        
        elif request.method == 'POST':
            clientcode = request.form.get('clientid')
            broker_pin = request.form.get('pin')
            totp_code = request.form.get('totp')

            auth_token, error_message = auth_function(clientcode, broker_pin, totp_code)
            forward_url = '5paisa.html'

    elif broker == 'angel':
        if request.method == 'GET':
            if 'user' not in session:
                return redirect(url_for('auth.login'))
            return render_template('angel.html')
        
        elif request.method == 'POST':
            clientcode = request.form.get('clientid')
            broker_pin = request.form.get('pin')
            totp_code = request.form.get('totp')
            auth_token, error_message = auth_function(clientcode, broker_pin, totp_code)
            forward_url = 'angel.html'
    
    elif broker == 'aliceblue':
        if request.method == 'GET':
            if 'user' not in session:
                return redirect(url_for('auth.login'))
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

    elif broker=='dhan':
        code = 'dhan'
        print(f'The code is {code}')
        auth_token, error_message = auth_function(code)
        forward_url = 'broker.html'

    elif broker == 'zebu':  
        if request.method == 'GET':
            if 'user' not in session:
                return redirect(url_for('auth.login'))
            return render_template('zebu.html')
        
        elif request.method == 'POST':
            userid = request.form.get('userid')
            password = request.form.get('password')
            totp_code = request.form.get('totp')

            auth_token, error_message = auth_function(userid, password, totp_code)
            forward_url = 'zebu.html'

    elif broker=='kotak':
        print(f"The Broker is {broker}")
        if request.method == 'GET':
            if 'user' not in session:
                return redirect(url_for('auth.login'))
            return render_template('kotak.html')
        

        elif request.method == 'POST':
            otp = request.form.get('otp')
            token = request.form.get('token')
            sid = request.form.get('sid')
            userid = request.form.get('userid')
            api_secret = get_broker_api_secret()

            auth_token, error_message = auth_function(otp,token,sid,userid,api_secret)

            forward_url = 'kotak.html'

   

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
            #token = request.args.get('request_token')
            auth_token = f'{BROKER_API_KEY}:{auth_token}'
        if broker == 'dhan':
            #token = request.args.get('request_token')
            auth_token = f'{auth_token}'
        return handle_auth_success(auth_token, session['user'],broker)
    else:
        return handle_auth_failure(error_message, forward_url=forward_url)
    


@brlogin_bp.route('/<broker>/loginflow', methods=['POST','GET'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def broker_loginflow(broker):
    if broker == 'kotak':
        mobilenumber = request.form.get('mobilenumber')
        password = request.form.get('password')
        conn = http.client.HTTPSConnection("gw-napi.kotaksecurities.com")
        payload = json.dumps({
            "mobileNumber": mobilenumber,
            "password": password
        })
        api_secret = get_broker_api_secret()
        headers = {
            'accept': '*/*',
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_secret}'
        }
        conn.request("POST", "/login/1.0/login/v2/validate", payload, headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")

        data_dict = json.loads(data)
        print(data_dict)

        if 'data' in data_dict:
            token = data_dict['data']['token']
            sid = data_dict['data']['sid']
            decode_jwt = jwt.decode(token, options={"verify_signature": False})
            userid = decode_jwt.get("sub")

            para = {
                "token": token,
                "sid": sid,
                "userid": userid
            }
            getKotakOTP(userid, api_secret)
            return render_template('kotakotp.html', para=para)
        else:
            error_message = data_dict.get('message', 'Unknown error occurred')
            return render_template('kotak.html', error_message=error_message)
        
    return


def getKotakOTP(userid,token):
    conn = http.client.HTTPSConnection("gw-napi.kotaksecurities.com")
    payload = json.dumps({
    "userId": userid,
    "sendEmail": True,
    "isWhitelisted": True
    })
    headers = {
    'accept': '*/*',
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {token}'
    }
    conn.request("POST", "/login/1.0/login/otp/generate", payload, headers)
    res = conn.getresponse()
    data = res.read()
    
    return 'success'