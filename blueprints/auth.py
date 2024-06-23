from flask import Blueprint, request, redirect, url_for, render_template, session, jsonify, make_response, flash
from limiter import limiter  # Import the limiter instance
from dotenv import load_dotenv
from extensions import socketio
import os
from database.auth_db import upsert_auth
from database.user_db import authenticate_user, User, db_session, find_user_by_username  # Import the function

# Load environment variables
load_dotenv()

# Access environment variables
LOGIN_RATE_LIMIT_MIN = os.getenv("LOGIN_RATE_LIMIT_MIN", "5 per minute")
LOGIN_RATE_LIMIT_HOUR = os.getenv("LOGIN_RATE_LIMIT_HOUR", "25 per hour")

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(error="Rate limit exceeded"), 429

@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def login():

    if find_user_by_username() is None:
        return redirect(url_for('core_bp.setup'))

    if 'user' in session:
            return redirect(url_for('auth.broker_login'))
    
    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))

    if request.method == 'GET':
        return render_template('login.html')
    elif request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        

        if authenticate_user(username, password):
            session['user'] = username  # Set the username in the session
            print("login success")
            # Redirect to broker login without marking as fully logged in
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401

@auth_bp.route('/broker', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def broker_login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))
    if request.method == 'GET':
        if 'user' not in session:
            # Environment variables
            return redirect(url_for('auth.login'))
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        REDIRECT_URL = os.getenv('REDIRECT_URL')
        return render_template('broker.html', broker_api_key=BROKER_API_KEY, broker_api_secret=BROKER_API_SECRET,
                               redirect_url=REDIRECT_URL)

@auth_bp.route('/change', methods=['GET', 'POST'])
def change_password():
    if 'user' not in session:
        # If the user is not logged in, redirect to login page
        flash('You must be logged in to change your password.', 'warning')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        username = session['user']
        old_password = request.form['old_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(old_password):
            if new_password == confirm_password:
                # Here, you should also ensure the new password meets your policy before updating
                user.set_password(new_password)
                db_session.commit()
                # Use flash to notify the user of success
                flash('Your password has been changed successfully.', 'success')
                # Redirect to a page where the user can see this confirmation, or stay on the same page
                return redirect(url_for('auth.change_password'))
            else:
                flash('New password and confirm password do not match.', 'error')
        else:
            flash('Old Password is incorrect.', 'error')
            # Optionally, redirect to the same page to let the user try again
            return redirect(url_for('auth.change_password'))

    return render_template('profile.html', username=session['user'])

@auth_bp.route('/logout')
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def logout():
    if session.get('logged_in'):
        username = session['user']
        
        #writing to database      
        inserted_id = upsert_auth(username, "", "", revoke=True)
        if inserted_id is not None:
            print(f"Database Upserted record with ID: {inserted_id}")
            print(f'Auth Revoked in the Database')
        else:
            print("Failed to upsert auth token")
        
        # Remove tokens and user information from session
        session.pop('user', None)  # Remove 'user' from session if exists
        session.pop('broker', None)  # Remove 'user' from session if exists
        session.pop('logged_in', None)

    # Redirect to login page after logout
    return redirect(url_for('auth.login'))
