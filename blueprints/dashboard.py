from flask import Blueprint, render_template, session, redirect, url_for, g, jsonify, request
from database.auth_db import get_auth_token
from importlib import import_module
import multiprocessing
import sys

# Import the launch_trading_app function from fastscalper.py
from blueprints.fastscalper import launch_trading_app

def dynamic_import(broker):
    try:
        module_path = f'broker.{broker}.api.funds'
        module = import_module(module_path)
        get_margin_data = getattr(module, 'get_margin_data')
        return get_margin_data
    except ImportError as e:
        print(f"Error importing module: {e}")
        return None

dashboard_bp = Blueprint('dashboard_bp', __name__, url_prefix='/')
scalper_process = None

@dashboard_bp.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    login_username = session['user']
    AUTH_TOKEN = get_auth_token(login_username)
    
    if AUTH_TOKEN is None:
        return redirect(url_for('auth.logout'))

    broker = session.get('broker')
    if not broker:
        return "Broker not set in session", 400
    
    get_margin_data_func = dynamic_import(broker)
    if get_margin_data_func is None:
        return "Failed to import broker module", 500

    margin_data = get_margin_data_func(AUTH_TOKEN)
    return render_template('dashboard.html', margin_data=margin_data)

@dashboard_bp.route('/launch', methods=['POST'])
def launch_trading_tool():
    global scalper_process

    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))
    
    login_username = session['user']
    AUTH_TOKEN = get_auth_token(login_username)
    
    if AUTH_TOKEN is None:
        return redirect(url_for('auth.logout'))

    broker = session.get('broker')
    if not broker:
        return "Broker not set in session", 400

    # Terminate the previous process if it is still running
    if scalper_process and scalper_process.is_alive():
        scalper_process.terminate()
        scalper_process.join()

    if sys.platform.startswith('win'):
        multiprocessing.freeze_support()

    scalper_process = multiprocessing.Process(target=launch_trading_app)
    scalper_process.start()
    return jsonify({"message": "FastScalper Launched"}), 200