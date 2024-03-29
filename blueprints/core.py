from flask import Blueprint, current_app, send_from_directory 
from flask import render_template, redirect, request, url_for
from database.user_db import add_user

import os

core_bp = Blueprint('core_bp', __name__)

@core_bp.route('/')
def home():
    return render_template('index.html')

@core_bp.route('/setup', methods=['GET', 'POST'])
def setup():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        mobile_number = request.form['mobile_number']
        # Add the new admin user
        if add_user(username, email, password, mobile_number, is_admin=True):
            return redirect(url_for('auth.login'))
        else:
            # If the user already exists or an error occurred, show an error message
            return 'User already exists or an error occurred'
    return render_template('setup.html')

@core_bp.route('/docs/')
def docs():
    docs_dir = os.path.join(current_app.root_path, 'docs')
    return send_from_directory(docs_dir, 'index.html')

@core_bp.route('/docs/<path:filename>')
def docs_file(filename):
    docs_dir = os.path.join(current_app.root_path, 'docs')
    return send_from_directory(docs_dir, filename)
