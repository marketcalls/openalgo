from flask import Blueprint, render_template, session, redirect, url_for
from database.auth_db import get_auth_token
from services.funds_service import get_funds
from utils.session import check_session_validity
from utils.logging import get_logger

logger = get_logger(__name__)

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
    
    # Use the centralized funds service
    success, response, status_code = get_funds(auth_token=AUTH_TOKEN, broker=broker)
    
    if not success:
        logger.error(f"Failed to get funds data: {response.get('message', 'Unknown error')}")
        if status_code == 404:
            return "Failed to import broker module", 500
        return redirect(url_for('auth.logout'))
    
    margin_data = response.get('data', {})
    
    # Check if margin_data is empty (authentication failed)
    if not margin_data:
        logger.error(f"Failed to get margin data for user {login_username} - authentication may have expired")
        return redirect(url_for('auth.logout'))
    
    # Check if all values are zero (but don't log warning during known service hours)
    if (margin_data.get('availablecash') == '0.00' and 
        margin_data.get('collateral') == '0.00' and
        margin_data.get('utiliseddebits') == '0.00'):
        # This could be service hours or authentication issue
        # The service already logs the appropriate message
        logger.debug(f"All margin data values are zero for user {login_username}")
    
    return render_template('dashboard.html', margin_data=margin_data)
