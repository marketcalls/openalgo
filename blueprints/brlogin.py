from flask import Blueprint, request, redirect, url_for, render_template, session, jsonify, make_response
from flask import current_app as app
from limiter import limiter  # Import the limiter instance
from utils.config import get_broker_api_key, get_login_rate_limit_min, get_login_rate_limit_hour
from utils.auth_utils import handle_auth_success, handle_auth_failure

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
def broker_callback(broker):
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
