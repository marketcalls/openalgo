from flask import session, redirect, url_for, render_template
from flask import current_app as app
from threading import Thread
from utils.session import get_session_expiry_time
from database.auth_db import upsert_auth
import importlib  # Import the importlib module for dynamic import

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
        print(f"Error importing {module_path}: {error}")
        return {'status': 'error', 'message': 'Failed to import master contract module'}

    # Use the dynamically imported module's master_contract_download function
    master_contract_status = master_contract_module.master_contract_download()
    
    print("Master Contract Database Processing Completed")
    
    return master_contract_status



def handle_auth_success(auth_token, user_session_key,broker):
    """
    Handles common tasks after successful authentication.
    - Sets session parameters
    - Stores auth token in the database
    - Initiates asynchronous master contract download
    """
    session['logged_in'] = True
    app.config['PERMANENT_SESSION_LIFETIME'] = get_session_expiry_time()
    session.permanent = True
    session['AUTH_TOKEN'] = auth_token  # Store the auth token in the session

    inserted_id = upsert_auth(user_session_key, auth_token,broker)
    if inserted_id:
        print(f"Database record upserted with ID: {inserted_id}")
        print('Upserted Auth Token, Username and Broker')
        thread = Thread(target=async_master_contract_download, args=(broker,))
        thread.start()
        return redirect(url_for('dashboard_bp.dashboard'))
    else:
        print("Failed to upsert auth token")
        return render_template('broker.html', error_message="Failed to store authentication token. Please try again.")

def handle_auth_failure(error_message,forward_url='broker.html',):
    """
    Handles common tasks after failed authentication.
    """
    print(f"Authentication error: {error_message}")
    return render_template(forward_url, error_message="Broker Authentication Failed")


