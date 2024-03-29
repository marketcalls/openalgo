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

@brlogin_bp.route('/callback/angel', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def angel_callback():

    broker_auth_functions = app.broker_auth_functions

    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))
    if request.method == 'GET':
        if 'user' not in session:
            return redirect(url_for('auth.login'))
        return render_template('angel.html')
    elif request.method == 'POST':
        clientcode = request.form['clientid']
        broker_pin = request.form['pin']
        totp_code = request.form['totp']     
        angel_authenticate = broker_auth_functions.get('angel_auth')    
        auth_token, error_message = angel_authenticate(clientcode, broker_pin, totp_code)
        if auth_token:
            return handle_auth_success(auth_token, session['user'])
        else:
            return handle_auth_failure(error_message,forward_url='angel.html')



@brlogin_bp.route('/upstox/callback', methods=['POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def upstox_callback():

    broker_auth_functions = app.broker_auth_functions

    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))

    code = request.args.get('code')
    if code:
        upstox_authenticate = broker_auth_functions.get('upstox_auth')  
        auth_token, error_message = upstox_authenticate(code)
        if auth_token:
            return handle_auth_success(auth_token, session['user'])
        else:
            return handle_auth_failure(error_message)
    else:
        return "No code received", 400



@brlogin_bp.route('/zerodha/callback', methods=['POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def zerodha_callback():

    broker_auth_functions = app.broker_auth_functions

    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))

    request_token = request.args.get('request_token')
    if request_token:
        zerodha_authenticate = broker_auth_functions.get('upstox_auth')  
        auth_token, error_message = zerodha_authenticate(request_token)
        if auth_token:
            auth_token = f'{BROKER_API_KEY}:{auth_token}'  # Concatenating with the broker key, specific to Zerodha
            return handle_auth_success(auth_token, session['user'])
        else:
            return handle_auth_failure(error_message)
    else:
        return "No request token received", 400






