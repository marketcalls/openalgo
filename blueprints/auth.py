from flask import Blueprint, request, redirect, url_for, render_template, session, jsonify, make_response, flash, current_app
from flask_wtf.csrf import generate_csrf
from limiter import limiter  # Import the limiter instance
from extensions import socketio
import os
from database.auth_db import upsert_auth, auth_cache, feed_token_cache
from database.user_db import authenticate_user, User, db_session, find_user_by_username, find_user_by_email  # Import the function
from database.settings_db import get_smtp_settings, set_smtp_settings
from utils.email_utils import send_test_email, send_password_reset_email
from utils.email_debug import debug_smtp_connection
import re
from utils.session import check_session_validity
import secrets
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Access environment variables
LOGIN_RATE_LIMIT_MIN = os.getenv("LOGIN_RATE_LIMIT_MIN", "5 per minute")
LOGIN_RATE_LIMIT_HOUR = os.getenv("LOGIN_RATE_LIMIT_HOUR", "25 per hour")
RESET_RATE_LIMIT = os.getenv("RESET_RATE_LIMIT", "15 per hour")  # Password reset rate limit

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

@auth_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(error="Rate limit exceeded"), 429


@auth_bp.route('/csrf-token', methods=['GET'])
def get_csrf_token():
    """Return a CSRF token for React SPA to use in form submissions."""
    token = generate_csrf()
    return jsonify({'csrf_token': token})


@auth_bp.route('/broker-config', methods=['GET'])
def get_broker_config():
    """Return broker configuration for React SPA."""
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Not authenticated'}), 401

    BROKER_API_KEY = os.getenv('BROKER_API_KEY')
    REDIRECT_URL = os.getenv('REDIRECT_URL')

    # Extract broker name from redirect URL
    match = re.search(r'/([^/]+)/callback$', REDIRECT_URL)
    broker_name = match.group(1) if match else None

    if not broker_name:
        return jsonify({'status': 'error', 'message': 'Broker not configured'}), 500

    return jsonify({
        'status': 'success',
        'broker_name': broker_name,
        'broker_api_key': BROKER_API_KEY,
        'redirect_url': REDIRECT_URL
    })


@auth_bp.route('/check-setup', methods=['GET'])
def check_setup_required():
    """Check if initial setup is required (no users exist)."""
    needs_setup = find_user_by_username() is None
    return jsonify({
        'status': 'success',
        'needs_setup': needs_setup
    })


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def login():
    # Handle POST requests first (for React SPA / AJAX login)
    if request.method == 'POST':
        # Check if setup is required
        if find_user_by_username() is None:
            return jsonify({'status': 'error', 'message': 'Please complete initial setup first.', 'redirect': '/setup'}), 400

        # Check if already logged in
        if 'user' in session:
            return jsonify({'status': 'success', 'message': 'Already logged in', 'redirect': '/broker'}), 200

        if session.get('logged_in'):
            return jsonify({'status': 'success', 'message': 'Already logged in', 'redirect': '/dashboard'}), 200

        username = request.form['username']
        password = request.form['password']

        if authenticate_user(username, password):
            session['user'] = username  # Set the username in the session
            logger.info(f"Login success for user: {username}")
            # Redirect to broker login without marking as fully logged in
            return jsonify({'status': 'success'}), 200
        else:
            return jsonify({'status': 'error', 'message': 'Invalid credentials'}), 401

    # Handle GET requests (for traditional form page)
    if find_user_by_username() is None:
        return redirect(url_for('core_bp.setup'))

    if 'user' in session:
        return redirect(url_for('auth.broker_login'))

    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))

    return render_template('login.html')

@auth_bp.route('/broker', methods=['GET', 'POST'])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def broker_login():
    if session.get('logged_in'):
        return redirect(url_for('dashboard_bp.dashboard'))
    if request.method == 'GET':
        if 'user' not in session:
            return redirect(url_for('auth.login'))
            
        # Get broker configuration (already validated at startup)
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        REDIRECT_URL = os.getenv('REDIRECT_URL')
        broker_name = re.search(r'/([^/]+)/callback$', REDIRECT_URL).group(1)
        
        # Import mask function for credential security
        from utils.auth_utils import mask_api_credential
            
        return render_template('broker.html', 
                             broker_api_key=BROKER_API_KEY,  # Keep original for OAuth redirects
                             broker_api_key_masked=mask_api_credential(BROKER_API_KEY),
                             broker_api_secret=BROKER_API_SECRET,  # Keep original for OAuth redirects  
                             broker_api_secret_masked=mask_api_credential(BROKER_API_SECRET),
                             redirect_url=REDIRECT_URL,
                             broker_name=broker_name)

@auth_bp.route('/reset-password', methods=['GET', 'POST'])
@limiter.limit(RESET_RATE_LIMIT)  # Password reset rate limit
def reset_password():
    if request.method == 'GET':
        return render_template('reset_password.html', email_sent=False)

    step = request.form.get('step')

    # Debug logging for CSRF issues
    logger.debug(f"Password reset step: {step}, Session: {session.keys()}")
    
    if step == 'email':
        email = request.form.get('email')
        user = find_user_by_email(email)
        
        # Always show the same response to prevent user enumeration
        if user:
            session['reset_email'] = email
        
        # Show method selection regardless of whether email exists
        return render_template('reset_password.html', 
                             email_sent=True, 
                             method_selected=False,
                             email=email)
    
    elif step == 'select_totp':
        email = request.form.get('email')
        session['reset_method'] = 'totp'
        
        return render_template('reset_password.html',
                             email_sent=True,
                             method_selected='totp',
                             totp_verified=False,
                             email=email)
    
    elif step == 'select_email':
        email = request.form.get('email')
        user = find_user_by_email(email)
        session['reset_method'] = 'email'
        
        # Check if SMTP is configured
        smtp_settings = get_smtp_settings()
        if not smtp_settings or not smtp_settings.get('smtp_server'):
            flash('Email reset is not available. Please use TOTP authentication.', 'error')
            return render_template('reset_password.html',
                                 email_sent=True,
                                 method_selected=False,
                                 email=email)
        
        if user:
            try:
                # Generate a secure token for the email reset
                token = secrets.token_urlsafe(32)
                session['reset_token'] = token
                session['reset_email'] = email
                
                # Create reset link
                reset_link = url_for('auth.reset_password_email', token=token, _external=True)
                send_password_reset_email(email, reset_link, user.username)
                logger.info(f"Password reset email sent to {email}")
                
            except Exception as e:
                logger.error(f"Failed to send password reset email to {email}: {e}")
                flash('Failed to send reset email. Please try TOTP authentication instead.', 'error')
                return render_template('reset_password.html',
                                     email_sent=True,
                                     method_selected=False,
                                     email=email)
        
        return render_template('reset_password.html',
                             email_sent=True,
                             method_selected='email',
                             email_verified=False,
                             email=email)
            
    elif step == 'totp':
        email = request.form.get('email')
        totp_code = request.form.get('totp_code')
        user = find_user_by_email(email)
        
        if user and user.verify_totp(totp_code):
            # Generate a secure token for the password reset
            token = secrets.token_urlsafe(32)
            session['reset_token'] = token
            session['reset_email'] = email
            
            return render_template('reset_password.html',
                                 email_sent=True,
                                 method_selected='totp',
                                 totp_verified=True,
                                 email=email,
                                 token=token)
        else:
            flash('Invalid TOTP code. Please try again.', 'error')
            return render_template('reset_password.html',
                                 email_sent=True,
                                 method_selected='totp',
                                 totp_verified=False,
                                 email=email)
            
    elif step == 'password':
        email = request.form.get('email')
        token = request.form.get('token')
        password = request.form.get('password')

        # Verify token from session (handles both TOTP and email reset tokens)
        valid_token = (token == session.get('reset_token') or token == session.get('email_reset_token'))
        if not valid_token or email != session.get('reset_email'):
            flash('Invalid or expired reset token.', 'error')
            return redirect(url_for('auth.reset_password'))

        # Validate password strength
        from utils.auth_utils import validate_password_strength
        is_valid, error_message = validate_password_strength(password)
        if not is_valid:
            flash(error_message, 'error')
            # Re-render the password form with the same state
            method = session.get('reset_method', 'totp')
            if method == 'totp':
                return render_template('reset_password.html',
                                     email_sent=True,
                                     method_selected='totp',
                                     totp_verified=True,
                                     email=email,
                                     token=token)
            else:  # email method
                return render_template('reset_password.html',
                                     email_sent=True,
                                     method_selected='email',
                                     email_verified=True,
                                     email=email,
                                     token=token)

        user = find_user_by_email(email)
        if user:
            user.set_password(password)
            db_session.commit()

            # Clear reset session data for security
            session.pop('reset_token', None)
            session.pop('reset_email', None)
            session.pop('reset_method', None)
            session.pop('email_reset_token', None)

            flash('Your password has been reset successfully.', 'success')
            return redirect(url_for('auth.login'))
        else:
            flash('Error resetting password.', 'error')
            return redirect(url_for('auth.reset_password'))
    
    return render_template('reset_password.html', email_sent=False)

@auth_bp.route('/reset-password-email/<token>', methods=['GET'])
def reset_password_email(token):
    """Handle password reset via email link"""
    try:
        # Validate the token format
        if not token or len(token) != 43:  # URL-safe base64 tokens are 43 chars for 32 bytes
            flash('Invalid reset link.', 'error')
            return redirect(url_for('auth.reset_password'))
        
        # Check if this token was issued (stored in session during email send)
        if token != session.get('reset_token'):
            flash('Invalid or expired reset link.', 'error')
            return redirect(url_for('auth.reset_password'))
        
        # Get the email associated with this reset token
        reset_email = session.get('reset_email')
        if not reset_email:
            flash('Reset session expired. Please start again.', 'error')
            return redirect(url_for('auth.reset_password'))
        
        # Set up session for password reset (email verification counts as verified)
        session['email_reset_token'] = token
        
        # Show password reset form
        return render_template('reset_password.html',
                             email_sent=True,
                             method_selected='email',
                             email_verified=True,  # Email link click counts as verification
                             email=reset_email,
                             token=token)
                             
    except Exception as e:
        logger.error(f"Error processing email reset link: {e}")
        flash('Invalid or expired reset link.', 'error') 
        return redirect(url_for('auth.reset_password'))

@auth_bp.route('/change', methods=['GET', 'POST'])
@check_session_validity
def change_password():
    if 'user' not in session:
        # If the user is not logged in, redirect to login page
        flash('You must be logged in to change your password.', 'warning')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        username = session['user']
        old_password = request.form['old_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(old_password):
            if new_password == confirm_password:
                # Validate password strength
                from utils.auth_utils import validate_password_strength
                is_valid, error_message = validate_password_strength(new_password)
                if not is_valid:
                    flash(error_message, 'error')
                    return redirect(url_for('auth.change_password'))

                user.set_password(new_password)
                db_session.commit()
                # Use flash to notify the user of success
                flash('Your password has been changed successfully.', 'success')
                # Redirect to a page where the user can see this confirmation, or stay on the same page
                return redirect(url_for('auth.change_password'))
            else:
                flash('New password and confirm password do not match.', 'error')
        else:
            flash('Old Password is incorrect.', 'error')
            # Optionally, redirect to the same page to let the user try again
            return redirect(url_for('auth.change_password'))

    # Get SMTP settings for display
    smtp_settings = get_smtp_settings()
    
    # Generate TOTP QR code for the current user
    try:
        username = session['user']
        user = User.query.filter_by(username=username).first()
        
        qr_code = None
        totp_secret = None
        
        if user:
            # Generate QR code
            import qrcode
            import io
            import base64
            
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(user.get_totp_uri())
            qr.make(fit=True)
            
            # Create QR code image
            img_buffer = io.BytesIO()
            qr.make_image(fill_color="black", back_color="white").save(img_buffer, format='PNG')
            qr_code = base64.b64encode(img_buffer.getvalue()).decode()
            totp_secret = user.totp_secret
            
    except Exception as e:
        logger.error(f"Error generating TOTP QR code for user {session['user']}: {e}")
        qr_code = None
        totp_secret = None
    
    return render_template('profile.html', 
                         username=session['user'],
                         smtp_settings=smtp_settings,
                         qr_code=qr_code,
                         totp_secret=totp_secret)

@auth_bp.route('/smtp-config', methods=['POST'])
@check_session_validity
def configure_smtp():
    if 'user' not in session:
        flash('You must be logged in to configure SMTP settings.', 'warning')
        return redirect(url_for('auth.login'))

    try:
        smtp_server = request.form.get('smtp_server')
        smtp_port = int(request.form.get('smtp_port', 587))
        smtp_username = request.form.get('smtp_username')
        smtp_password = request.form.get('smtp_password')
        smtp_use_tls = request.form.get('smtp_use_tls') == 'on'
        smtp_from_email = request.form.get('smtp_from_email')
        smtp_helo_hostname = request.form.get('smtp_helo_hostname')

        # Only update password if provided
        if smtp_password and smtp_password.strip():
            set_smtp_settings(
                smtp_server=smtp_server,
                smtp_port=smtp_port,
                smtp_username=smtp_username,
                smtp_password=smtp_password,
                smtp_use_tls=smtp_use_tls,
                smtp_from_email=smtp_from_email,
                smtp_helo_hostname=smtp_helo_hostname
            )
        else:
            # Update without password change
            set_smtp_settings(
                smtp_server=smtp_server,
                smtp_port=smtp_port,
                smtp_username=smtp_username,
                smtp_use_tls=smtp_use_tls,
                smtp_from_email=smtp_from_email,
                smtp_helo_hostname=smtp_helo_hostname
            )

        flash('SMTP settings updated successfully.', 'success')
        logger.info(f"SMTP settings updated by user: {session['user']}")
        
    except Exception as e:
        flash(f'Error updating SMTP settings: {str(e)}', 'error')
        logger.error(f"Error updating SMTP settings: {str(e)}")

    return redirect(url_for('auth.change_password') + '?tab=smtp')

@auth_bp.route('/test-smtp', methods=['POST'])
@check_session_validity
def test_smtp():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'You must be logged in to test SMTP settings.'}), 401

    try:
        test_email = request.form.get('test_email')
        if not test_email:
            return jsonify({'success': False, 'message': 'Please provide a test email address.'}), 400
        
        # Validate email format
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, test_email):
            return jsonify({'success': False, 'message': 'Please provide a valid email address.'}), 400
        
        # Send test email
        result = send_test_email(test_email, sender_name=session['user'])
        
        if result['success']:
            logger.info(f"Test email sent successfully by user: {session['user']} to {test_email}")
            return jsonify({
                'success': True, 
                'message': result['message']
            }), 200
        else:
            logger.warning(f"Test email failed for user: {session['user']} - {result['message']}")
            return jsonify({
                'success': False, 
                'message': result['message']
            }), 400
            
    except Exception as e:
        error_msg = f'Error sending test email: {str(e)}'
        logger.error(f"Test email error for user {session['user']}: {e}")
        return jsonify({
            'success': False, 
            'message': error_msg
        }), 500

@auth_bp.route('/debug-smtp', methods=['POST'])
@check_session_validity
def debug_smtp():
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'You must be logged in to debug SMTP settings.'}), 401

    try:
        logger.info(f"SMTP debug requested by user: {session['user']}")
        result = debug_smtp_connection()
        
        return jsonify({
            'success': result['success'],
            'message': result['message'],
            'details': result['details']
        }), 200
        
    except Exception as e:
        error_msg = f'Error debugging SMTP: {str(e)}'
        logger.error(f"SMTP debug error for user {session['user']}: {e}")
        return jsonify({
            'success': False, 
            'message': error_msg,
            'details': [f"Unexpected error: {e}"]
        }), 500


@auth_bp.route('/session-status', methods=['GET'])
def get_session_status():
    """Return current session status for React SPA."""
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Not authenticated', 'authenticated': False}), 401

    # If session claims to be logged in with broker, validate the auth token exists
    if session.get('logged_in') and session.get('broker'):
        from database.auth_db import get_auth_token, get_api_key_for_tradingview
        auth_token = get_auth_token(session.get('user'))
        if auth_token is None:
            logger.warning(f"Session status: stale session detected for user {session.get('user')} - no auth token")
            # Clear the stale session
            session.clear()
            return jsonify({'status': 'error', 'message': 'Session expired', 'authenticated': False}), 401

        # Get API key for the user
        api_key = get_api_key_for_tradingview(session.get('user'))

        return jsonify({
            'status': 'success',
            'authenticated': True,
            'logged_in': session.get('logged_in', False),
            'user': session.get('user'),
            'broker': session.get('broker'),
            'api_key': api_key
        })

    return jsonify({
        'status': 'success',
        'authenticated': True,
        'logged_in': session.get('logged_in', False),
        'user': session.get('user'),
        'broker': session.get('broker')
    })


@auth_bp.route('/app-info', methods=['GET'])
def get_app_info():
    """Return app information including version for React SPA."""
    from utils.version import get_version
    return jsonify({
        'status': 'success',
        'version': get_version(),
        'name': 'OpenAlgo'
    })


@auth_bp.route('/analyzer-mode', methods=['GET'])
@check_session_validity
def get_analyzer_mode_status():
    """Return current analyzer mode status for React SPA."""
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Not authenticated'}), 401

    try:
        from database.settings_db import get_analyze_mode

        current_mode = get_analyze_mode()

        return jsonify({
            'status': 'success',
            'data': {
                'mode': 'analyze' if current_mode else 'live',
                'analyze_mode': current_mode
            }
        })
    except Exception as e:
        logger.error(f"Error getting analyzer mode: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@auth_bp.route('/analyzer-toggle', methods=['POST'])
@check_session_validity
def toggle_analyzer_mode_session():
    """Toggle analyzer mode for React SPA using session authentication."""
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Not authenticated'}), 401

    if not session.get('logged_in'):
        return jsonify({'status': 'error', 'message': 'Broker not connected'}), 401

    try:
        from database.settings_db import get_analyze_mode, set_analyze_mode

        # Get current mode and toggle it
        current_mode = get_analyze_mode()
        new_mode = not current_mode

        # Set the new mode
        set_analyze_mode(new_mode)

        # Start/stop execution engine and squareoff scheduler based on mode
        from sandbox.execution_thread import start_execution_engine, stop_execution_engine
        from sandbox.squareoff_thread import start_squareoff_scheduler, stop_squareoff_scheduler

        if new_mode:
            # Analyzer mode ON - start both threads
            start_execution_engine()
            start_squareoff_scheduler()

            # Run catch-up settlement for any missed settlements while app was stopped
            from sandbox.position_manager import catchup_missed_settlements
            try:
                catchup_missed_settlements()
                logger.info("Catch-up settlement check completed")
            except Exception as e:
                logger.error(f"Error in catch-up settlement: {e}")

            logger.info("Analyzer mode enabled - Execution engine and square-off scheduler started")
        else:
            # Analyzer mode OFF - stop both threads
            stop_execution_engine()
            stop_squareoff_scheduler()
            logger.info("Analyzer mode disabled - Execution engine and square-off scheduler stopped")

        return jsonify({
            'status': 'success',
            'data': {
                'mode': 'analyze' if new_mode else 'live',
                'analyze_mode': new_mode,
                'message': f'Switched to {"Analyze" if new_mode else "Live"} mode'
            }
        })

    except Exception as e:
        logger.error(f"Error toggling analyzer mode: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@auth_bp.route('/dashboard-data', methods=['GET'])
@check_session_validity
def get_dashboard_data():
    """Return dashboard funds data using session authentication for React SPA."""
    if 'user' not in session:
        return jsonify({'status': 'error', 'message': 'Not authenticated'}), 401

    if not session.get('logged_in'):
        return jsonify({'status': 'error', 'message': 'Broker not connected'}), 401

    login_username = session['user']
    broker = session.get('broker')

    if not broker:
        return jsonify({'status': 'error', 'message': 'Broker not set in session'}), 400

    try:
        from database.auth_db import get_auth_token, get_api_key_for_tradingview
        from database.settings_db import get_analyze_mode
        from services.funds_service import get_funds

        AUTH_TOKEN = get_auth_token(login_username)

        if AUTH_TOKEN is None:
            logger.warning(f"No auth token found for user {login_username}")
            return jsonify({'status': 'error', 'message': 'Session expired'}), 401

        # Check if in analyze mode
        if get_analyze_mode():
            api_key = get_api_key_for_tradingview(login_username)
            if api_key:
                success, response, status_code = get_funds(api_key=api_key)
            else:
                return jsonify({'status': 'error', 'message': 'API key required for analyze mode'}), 400
        else:
            success, response, status_code = get_funds(auth_token=AUTH_TOKEN, broker=broker)

        if not success:
            logger.error(f"Failed to get funds data: {response.get('message', 'Unknown error')}")
            return jsonify({'status': 'error', 'message': response.get('message', 'Failed to get funds')}), status_code

        margin_data = response.get('data', {})

        if not margin_data:
            logger.error(f"Failed to get margin data for user {login_username}")
            return jsonify({'status': 'error', 'message': 'Failed to get margin data'}), 500

        return jsonify({
            'status': 'success',
            'data': margin_data
        })

    except Exception as e:
        logger.error(f"Error fetching dashboard data: {e}")
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500


@auth_bp.route('/logout', methods=['GET', 'POST'])
def logout():
    if session.get('logged_in'):
        username = session['user']
        
        # Clear cache entries before database update to prevent stale data access
        cache_key_auth = f"auth-{username}"
        cache_key_feed = f"feed-{username}"
        if cache_key_auth in auth_cache:
            del auth_cache[cache_key_auth]
            logger.info(f"Cleared auth cache for user: {username}")
        if cache_key_feed in feed_token_cache:
            del feed_token_cache[cache_key_feed]
            logger.info(f"Cleared feed token cache for user: {username}")
            
        # Clear symbol cache on logout
        try:
            from database.master_contract_cache_hook import clear_cache_on_logout
            clear_cache_on_logout()
            logger.info("Cleared symbol cache on logout")
        except Exception as cache_error:
            logger.error(f"Error clearing symbol cache on logout: {cache_error}")
        
        #writing to database      
        inserted_id = upsert_auth(username, "", "", revoke=True)
        if inserted_id is not None:
            logger.info(f"Database Upserted record with ID: {inserted_id}")
            logger.info(f'Auth Revoked in the Database for user: {username}')
        else:
            logger.error(f"Failed to upsert auth token for user: {username}")
        
        # Clear entire session to ensure complete logout
        session.clear()
        logger.info(f"Session cleared for user: {username}")

    # For POST requests (AJAX from React), return JSON
    if request.method == 'POST':
        return jsonify({'status': 'success', 'message': 'Logged out successfully'})

    # For GET requests (traditional), redirect to login page
    return redirect(url_for('auth.login'))
