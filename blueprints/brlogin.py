from flask import Blueprint, request, redirect, url_for, render_template, session, jsonify, make_response, flash
from flask import current_app as app
from limiter import limiter
from utils.auth_utils import handle_auth_success, handle_auth_failure
from database.broker_db import get_broker_config, save_broker_config, delete_broker_config
from utils.config import get_login_rate_limit_min, get_login_rate_limit_hour
from utils.session import check_session_validity
import http.client
import json
import jwt
import base64
import hashlib

brlogin_bp = Blueprint('brlogin', __name__, url_prefix='/')

@brlogin_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(error="Rate limit exceeded"), 429

@brlogin_bp.route('/broker/login')
@check_session_validity
def broker_login():
    # Get all broker configurations for the current user
    broker_configs = {}
    for broker in ['zerodha', 'fivepaisa']:  # Add more brokers as needed
        config = get_broker_config(session['user']['id'], broker)
        if config:
            broker_configs[broker] = config
    
    return render_template('broker.html', broker_configs=broker_configs)

@brlogin_bp.route('/broker/config/<broker>', methods=['GET', 'POST'])
@check_session_validity
def broker_config(broker):
    if request.method == 'GET':
        config = get_broker_config(session['user']['id'], broker)
        return render_template('broker_config.html', broker_name=broker, config=config)
    
    return redirect(url_for('brlogin.broker_login'))

@brlogin_bp.route('/broker/config/<broker>/save', methods=['POST'])
@check_session_validity
def save_broker_config_route(broker):
    api_key = request.form.get('api_key')
    api_secret = request.form.get('api_secret')
    redirect_url = request.form.get('redirect_url')
    
    if not all([api_key, api_secret, redirect_url]):
        flash('All fields are required', 'error')
        return redirect(url_for('brlogin.broker_config', broker=broker))
    
    try:
        save_broker_config(
            session['user']['id'],
            broker,
            api_key,
            api_secret,
            redirect_url
        )
        flash('Broker configuration saved successfully!', 'success')
        return redirect(url_for('brlogin.broker_login'))
            
    except Exception as e:
        flash(f'Error saving configuration: {str(e)}', 'error')
    
    return redirect(url_for('brlogin.broker_config', broker=broker))

@brlogin_bp.route('/broker/config/<broker>/delete', methods=['GET'])
@check_session_validity
def delete_broker_config_route(broker):
    try:
        if delete_broker_config(session['user']['id'], broker):
            flash('Broker configuration deleted successfully!', 'success')
            
            # If user was logged in with this broker, log them out
            if session.get('broker') == broker:
                session.pop('broker', None)
                session.pop('logged_in', None)
        else:
            flash('No configuration found to delete.', 'info')
    except Exception as e:
        flash(f'Error deleting configuration: {str(e)}', 'error')
    
    return redirect(url_for('brlogin.broker_login'))

@brlogin_bp.route('/<broker>/callback', methods=['POST','GET'])
@limiter.limit(f"{get_login_rate_limit_min()}")
@limiter.limit(f"{get_login_rate_limit_hour()}")
@check_session_validity
def broker_callback(broker,para=None):
    # Check if broker is configured
    config = get_broker_config(session['user']['id'], broker)
    if not config:
        flash('Please configure your broker settings first.', 'error')
        return redirect(url_for('brlogin.broker_config', broker=broker))

    if session.get('logged_in'):
        session['broker'] = broker
        return redirect(url_for('dashboard_bp.dashboard'))

    broker_auth_functions = app.broker_auth_functions
    auth_function = broker_auth_functions.get(f'{broker}_auth')

    if not auth_function:
        flash('Unsupported broker.', 'error')
        return redirect(url_for('brlogin.broker_login'))

    try:
        result = auth_function(request, config)
        if result.get('success'):
            handle_auth_success(result)
            session['broker'] = broker
            return redirect(url_for('dashboard_bp.dashboard'))
        else:
            handle_auth_failure(result)
            return redirect(url_for('brlogin.broker_login'))
    except Exception as e:
        flash(f'Authentication failed: {str(e)}', 'error')
        return redirect(url_for('brlogin.broker_login'))
