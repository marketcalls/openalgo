# Make sure to include the correct import path based on your project structure
from flask import Blueprint, render_template, session, redirect, url_for, g
from database.auth_db import get_auth_token

from importlib import import_module


def dynamic_import(broker):
    try:
        # Construct module path dynamically
        module_path = f'broker.{broker}.api.funds'
        # Import the module
        module = import_module(module_path)
        # Now, you can access get_margin_data or any other function directly
        get_margin_data = getattr(module, 'get_margin_data')
        return get_margin_data
    except ImportError as e:
        # Handle the error if module doesn't exist
        print(f"Error importing module: {e}")
        return None


dashboard_bp = Blueprint('dashboard_bp', __name__, url_prefix='/')

@dashboard_bp.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    login_username = session['user']
    AUTH_TOKEN = get_auth_token(login_username)
    

    if AUTH_TOKEN is None:
        return redirect(url_for('auth.logout'))
    print(AUTH_TOKEN)

    # Ensure the broker is set in the session
    broker = session.get('broker')
    if not broker:
        # Handle the case where the broker is not set
        return "Broker not set in session", 400
    
    # Dynamically import the get_margin_data function based on the broker
    get_margin_data_func = dynamic_import(broker)
    if get_margin_data_func is None:
        # Handle the case where the dynamic import failed
        return "Failed to import broker module", 500

    # Use the dynamically imported get_margin_data function
    margin_data = get_margin_data_func(AUTH_TOKEN)

    # Render the dashboard template with the margin data
    return render_template('dashboard.html', margin_data=margin_data)