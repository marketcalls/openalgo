from flask import session, redirect, url_for, render_template
from flask import current_app as app
from threading import Thread
from utils.session import get_session_expiry_time, set_session_login_time
from database.auth_db import upsert_auth, get_feed_token as db_get_feed_token
from database.master_contract_status_db import init_broker_status, update_status
import importlib
from utils.logging import get_logger

logger = get_logger(__name__)

def mask_api_credential(credential, show_chars=4):
    """
    Mask API credentials for display purposes, showing only the first few characters.
    
    Args:
        credential (str): The credential to mask
        show_chars (int): Number of characters to show from the beginning
    
    Returns:
        str: Masked credential string
    """
    if not credential or len(credential) <= show_chars:
        return '*' * 8  # Return generic mask for short/empty credentials
    
    return credential[:show_chars] + '*' * (len(credential) - show_chars)

def async_master_contract_download(broker):
    """
    Asynchronously download the master contract and emit a WebSocket event upon completion,
    with the 'broker' parameter specifying the broker for which to download the contract.
    """
    # Update status to downloading
    update_status(broker, 'downloading', 'Master contract download in progress')
    
    # Dynamically construct the module path based on the broker
    module_path = f'broker.{broker}.database.master_contract_db'
    
    # Dynamically import the module
    try:
        master_contract_module = importlib.import_module(module_path)
    except ImportError as error:
        logger.error(f"Error importing {module_path}: {error}")
        update_status(broker, 'error', f'Failed to import master contract module: {str(error)}')
        return {'status': 'error', 'message': 'Failed to import master contract module'}

    # Use the dynamically imported module's master_contract_download function
    try:
        master_contract_status = master_contract_module.master_contract_download()
        
        # Most brokers return the socketio.emit result, we need to check completion
        # by looking at the module's actual completion
        
        # Try to get the symbol count from the database
        try:
            from database.token_db import get_symbol_count
            total_symbols = get_symbol_count()
        except:
            total_symbols = None
            
        # Since socketio.emit doesn't return a meaningful value, we check if no exception was raised
        update_status(broker, 'success', 'Master contract download completed successfully', total_symbols)
        logger.info(f"Master contract download completed for {broker}")
        
        # Load symbols into memory cache after successful download
        try:
            from database.master_contract_cache_hook import hook_into_master_contract_download
            logger.info(f"Loading symbols into memory cache for broker: {broker}")
            hook_into_master_contract_download(broker)
        except Exception as cache_error:
            logger.error(f"Failed to load symbols into cache: {cache_error}")
            # Don't fail the whole process if cache loading fails
            
    except Exception as e:
        logger.error(f"Error during master contract download for {broker}: {str(e)}")
        update_status(broker, 'error', f'Master contract download error: {str(e)}')
        return {'status': 'error', 'message': str(e)}
    
    logger.info("Master Contract Database Processing Completed")
    
    return master_contract_status

def handle_auth_success(auth_token, user_session_key, broker, feed_token=None, user_id=None):
    """
    Handles common tasks after successful authentication.
    - Sets session parameters
    - Stores auth token in the database
    - Initiates asynchronous master contract download
    """
    # Set session parameters
    session['logged_in'] = True
    session['AUTH_TOKEN'] = auth_token
    if feed_token:
        session['FEED_TOKEN'] = feed_token  # Store feed token in session if available
    if user_id:
        session['USER_ID'] = user_id  # Store user ID in session if available
    session['user_session_key'] = user_session_key
    session['broker'] = broker
    
    # Set session expiry and login time
    app.config['PERMANENT_SESSION_LIFETIME'] = get_session_expiry_time()
    session.permanent = True
    set_session_login_time()  # Set the login timestamp
    
    logger.info(f"User {user_session_key} logged in successfully with broker {broker}")

    # Store auth token in database
    inserted_id = upsert_auth(user_session_key, auth_token, broker, feed_token=feed_token, user_id=user_id)
    if inserted_id:
        logger.info(f"Database record upserted with ID: {inserted_id}")
        # Initialize master contract status for this broker
        init_broker_status(broker)
        thread = Thread(target=async_master_contract_download, args=(broker,))
        thread.start()
        return redirect(url_for('dashboard_bp.dashboard'))
    else:
        logger.error(f"Failed to upsert auth token for user {user_session_key}")
        return render_template('broker.html', error_message="Failed to store authentication token. Please try again.")

def handle_auth_failure(error_message, forward_url='broker.html'):
    """
    Handles common tasks after failed authentication.
    """
    logger.error(f"Authentication error: {error_message}")
    return render_template(forward_url, error_message=error_message)

def get_feed_token():
    """
    Get the feed token from session or database.
    Returns None if feed token doesn't exist or broker doesn't support it.
    """
    if 'FEED_TOKEN' in session:
        return session['FEED_TOKEN']
    
    # If not in session but user is logged in, try to get from database
    if 'logged_in' in session and session['logged_in'] and 'user_session_key' in session:
        return db_get_feed_token(session['user_session_key'])
    
    return None
