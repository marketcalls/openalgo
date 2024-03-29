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
    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))

    broker_auth_functions = app.broker_auth_functions
    auth_function = broker_auth_functions.get(f'{broker}_auth')

    if not auth_function:
        return jsonify(error="Broker authentication function not found."), 404

    if broker == 'angel':
        # Assume similar handling for other brokers as needed
        clientcode = request.form.get('clientid')
        broker_pin = request.form.get('pin')
        totp_code = request.form.get('totp')
        auth_token, error_message = auth_function(clientcode, broker_pin, totp_code)
        forward_url = 'angel.html'
    else:
        # Generic handling for other brokers (e.g., upstox, zerodha)
        code = request.args.get('code') or request.args.get('request_token')
        auth_token, error_message = auth_function(code)
        forward_url = 'broker.html'
    
    if auth_token:
        if broker == 'zerodha':
            token = request.args.get('request_token')
            code = f'{BROKER_API_KEY}:{token}'
            print(code)
        return handle_auth_success(auth_token, session['user'])
    else:
        return handle_auth_failure(error_message, forward_url=forward_url)







