from flask import session, redirect, url_for, render_template
from flask import current_app as app
from threading import Thread
from utils.session import get_session_expiry_time
from database.auth_db import upsert_auth
#from database.master_contract_db import master_contract_download

def async_master_contract_download(user):
    """
    Asynchronously download the master contract and emit a WebSocket event upon completion.
    """
    #master_contract_status = master_contract_download()  # Assuming this is a blocking call
    
    print("Processing Master Contract Download")
    return True

    #return master_contract_status



def handle_auth_success(auth_token, user_session_key):
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

    inserted_id = upsert_auth(user_session_key, auth_token)
    if inserted_id:
        print(f"Database record upserted with ID: {inserted_id}")
        thread = Thread(target=async_master_contract_download, args=(user_session_key,))
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


