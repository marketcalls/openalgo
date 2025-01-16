from flask import session, redirect, url_for, render_template, flash
from flask import current_app as app
from threading import Thread
from utils.session import get_session_expiry_time, set_session_login_time
from database.auth_db import upsert_auth
from database.broker_db import get_broker_config
import importlib
import logging
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

def check_broker_config(user_id, broker):
    """
    Check if broker is configured for the user.
    Returns True if configured, False otherwise.
    """
    config = get_broker_config(user_id, broker)
    if not config:
        flash('Please configure your broker settings first.', 'error')
        return False
    return True

def async_master_contract_download(broker):
    """
    Asynchronously download the master contract and emit a WebSocket event upon completion,
    with the 'broker' parameter specifying the broker for which to download the contract.
    """
    # Dynamically construct the module path based on the broker
    module_path = f'broker.{broker}.database.master_contract_db'
    
    # Dynamically import the module
    try:
        master_contract_module = importlib.import_module(module_path)
    except ImportError as error:
        logger.error(f"Error importing {module_path}: {error}")
        return {'status': 'error', 'message': 'Failed to import master contract module'}

    # Use the dynamically imported module's master_contract_download function
    master_contract_status = master_contract_module.master_contract_download()
    
    logger.info("Master Contract Database Processing Completed")
    
    return master_contract_status

def handle_auth_success(auth_token, user_session_key, broker):
    """
    Handles common tasks after successful authentication.
    - Sets session parameters
    - Stores auth token in the database
    - Initiates asynchronous master contract download
    """
    # Check if broker is configured
    if not check_broker_config(user_session_key['id'], broker):
        return redirect(url_for('brlogin.broker_config', broker=broker))

    # Set session parameters
    session['logged_in'] = True
    session['AUTH_TOKEN'] = auth_token
    session['user_session_key'] = user_session_key
    session['broker'] = broker
    
    # Set session expiry and login time
    app.config['PERMANENT_SESSION_LIFETIME'] = get_session_expiry_time()
    session.permanent = True
    set_session_login_time()  # Set the login timestamp
    
    logger.info(f"User {user_session_key} logged in successfully with broker {broker}")

    # Store auth token in database
    inserted_id = upsert_auth(user_session_key, auth_token, broker)
    if inserted_id:
        logger.info(f"Database record upserted with ID: {inserted_id}")
        thread = Thread(target=async_master_contract_download, args=(broker,))
        thread.start()
        return redirect(url_for('dashboard_bp.dashboard'))
    else:
        logger.error(f"Failed to upsert auth token for user {user_session_key}")
        flash("Failed to store authentication token. Please try again.", "error")
        return redirect(url_for('brlogin.broker_login'))

def handle_auth_failure(error_message, forward_url='broker.html'):
    """
    Handles common tasks after failed authentication.
    """
    logger.error(f"Authentication error: {error_message}")
    flash("Broker Authentication Failed", "error")
    return render_template(forward_url, error_message="Broker Authentication Failed")
