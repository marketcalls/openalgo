from flask import Blueprint, render_template, session, redirect, url_for, g, jsonify, request
from database.auth_db import get_auth_token
from importlib import import_module
from utils.session import check_session_validity
import multiprocessing
import sys
import logging

logger = logging.getLogger(__name__)

def dynamic_import(broker):
    try:
        module_path = f'broker.{broker}.api.funds'
        module = import_module(module_path)
        get_margin_data = getattr(module, 'get_margin_data')
        return get_margin_data
    except ImportError as e:
        logger.error(f"Error importing module: {e}")
        return None

dashboard_bp = Blueprint('dashboard_bp', __name__, url_prefix='/')
scalper_process = None

@dashboard_bp.route('/dashboard')
@check_session_validity
def dashboard():
    login_username = session['user']
    AUTH_TOKEN = get_auth_token(login_username)
    
    if AUTH_TOKEN is None:
        logger.warning(f"No auth token found for user {login_username}")
        return redirect(url_for('auth.logout'))

    broker = session.get('broker')
    if not broker:
        logger.error("Broker not set in session")
        return "Broker not set in session", 400
    
    get_margin_data_func = dynamic_import(broker)
    if get_margin_data_func is None:
        logger.error(f"Failed to import broker module for {broker}")
        return "Failed to import broker module", 500

    margin_data = get_margin_data_func(AUTH_TOKEN)
    return render_template('dashboard.html', margin_data=margin_data)
