from flask import Blueprint, request, render_template, redirect, url_for, session, flash, jsonify
from database.user_db import User, db_session
from database.broker_db import get_broker_config
from utils.config import get_login_rate_limit_min, get_login_rate_limit_hour
from utils.session import clear_session, set_session_login_time
from limiter import limiter
import os
import re

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# Rate limits
LOGIN_RATE_LIMIT_MIN = get_login_rate_limit_min()
LOGIN_RATE_LIMIT_HOUR = get_login_rate_limit_hour()
RESET_RATE_LIMIT = "3 per hour"

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))

    if request.method == 'GET':
        return render_template('login.html')
    
    username = request.form.get('username')
    password = request.form.get('password')
    
    if not username or not password:
        return jsonify({'status': 'error', 'message': 'Missing username or password'}), 400
    
    user = User.query.filter_by(username=username).first()
    
    if user and user.check_password(password):
        session['user'] = {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'is_admin': user.is_admin
        }
        session['logged_in'] = True
        set_session_login_time()  # Set the login time
        print("login success")
        return jsonify({'status': 'success', 'redirect': url_for('auth.broker_login')}), 200
    else:
        return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401

@auth_bp.route('/broker')
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def broker_login():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    
    # Get all broker configurations for the current user
    broker_configs = {}
    for broker in ['zerodha', 'fivepaisa']:  # Add more brokers as needed
        config = get_broker_config(session['user']['id'], broker)
        if config:
            broker_configs[broker] = config
    
    return render_template('broker.html', broker_configs=broker_configs)

@auth_bp.route('/change-password', methods=['GET', 'POST'])
@limiter.limit(RESET_RATE_LIMIT)
def change_password():
    if 'user' not in session:
        return redirect(url_for('auth.login'))
    
    if request.method == 'GET':
        return render_template('change_password.html')
    
    current_password = request.form.get('current_password')
    new_password = request.form.get('new_password')
    confirm_password = request.form.get('confirm_password')
    
    if not all([current_password, new_password, confirm_password]):
        return jsonify({'status': 'error', 'message': 'All fields are required'}), 400
    
    if new_password != confirm_password:
        return jsonify({'status': 'error', 'message': 'New passwords do not match'}), 400
    
    user = User.query.filter_by(id=session['user']['id']).first()
    if not user or not user.check_password(current_password):
        return jsonify({'status': 'error', 'message': 'Current password is incorrect'}), 401
    
    user.set_password(new_password)
    db_session.commit()
    
    return jsonify({'status': 'success', 'message': 'Password changed successfully'}), 200

@auth_bp.route('/reset-password', methods=['GET', 'POST'])
@limiter.limit(RESET_RATE_LIMIT)  # More restrictive rate limit for password reset
def reset_password():
    if request.method == 'GET':
        return render_template('reset_password.html')
    
    email = request.form.get('email')
    if not email:
        return jsonify({'status': 'error', 'message': 'Email is required'}), 400
    
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'status': 'error', 'message': 'No account found with this email'}), 404
    
    # TODO: Implement password reset logic
    # 1. Generate reset token
    # 2. Send reset email
    # 3. Save token in database with expiry
    
    return jsonify({'status': 'success', 'message': 'Password reset instructions sent to your email'}), 200

@auth_bp.route('/logout')
def logout():
    clear_session()
    return redirect(url_for('auth.login'))
