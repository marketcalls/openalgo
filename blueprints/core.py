from flask import Blueprint, render_template, redirect, request, url_for, session
from database.user_db import add_user, find_user_by_username
from utils.session import check_session_validity
import logging

logger = logging.getLogger(__name__)

core_bp = Blueprint('core_bp', __name__)

@core_bp.route('/')
def home():
    return render_template('index.html')

@core_bp.route('/download')
def download():
    return render_template('download.html')

@core_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    if find_user_by_username() is not None:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        mobile_number = request.form['mobile_number']
        # Add the new admin user
        if add_user(username, email, password, mobile_number, is_admin=True):
            logger.info(f"New admin user {username} created successfully")
            return redirect(url_for('auth.login'))
        else:
            # If the user already exists or an error occurred, show an error message
            logger.error(f"Failed to create admin user {username}")
            return 'User already exists or an error occurred'
    return render_template('setup.html')
