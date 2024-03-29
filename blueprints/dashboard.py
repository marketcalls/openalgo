# Make sure to include the correct import path based on your project structure
from flask import Blueprint, render_template, session, redirect, url_for
from database.auth_db import get_auth_token
from api.funds import get_margin_data
import os

dashboard_bp = Blueprint('dashboard_bp', __name__, url_prefix='/')

@dashboard_bp.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    login_username = session['user']
    AUTH_TOKEN = get_auth_token(login_username)

    if AUTH_TOKEN is None:
        return redirect(url_for('auth.logout'))
        
    # Use the get_margin_data function from funds.py
    margin_data = get_margin_data(AUTH_TOKEN)

    # Now margin_data is directly usable here
    return render_template('dashboard.html', margin_data=margin_data)
