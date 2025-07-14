# blueprints/broker_setup.py

from flask import Blueprint, request, redirect, url_for, render_template, session, jsonify, flash
from limiter import limiter
from database.broker_config_db import (
    create_broker_config, get_user_brokers, get_broker_config, 
    delete_broker_config, update_connection_status, get_broker_templates
)
from utils.broker_credentials import (
    validate_broker_credentials, test_broker_connection, 
    is_xts_broker, format_redirect_url, mask_credentials
)
from utils.logging import get_logger
import os

# Initialize logger
logger = get_logger(__name__)

broker_setup_bp = Blueprint('broker_setup', __name__, url_prefix='/broker')

@broker_setup_bp.before_request
def require_login():
    """Require user to be logged in for all broker setup routes"""
    if 'user' not in session:
        return redirect(url_for('auth.login'))

@broker_setup_bp.route('/setup')
def setup_wizard():
    """Broker setup wizard - main entry point"""
    user_id = session.get('user')
    
    # Get available broker templates
    templates = get_broker_templates(active_only=True)
    
    # Get user's existing brokers
    user_brokers = get_user_brokers(user_id)
    
    # Mark which brokers are already configured
    configured_brokers = {broker['broker_name'] for broker in user_brokers}
    
    return render_template('broker_setup.html', 
                         templates=templates,
                         user_brokers=user_brokers,
                         configured_brokers=configured_brokers)

@broker_setup_bp.route('/configure/<broker_name>')
def configure_broker(broker_name):
    """Configure specific broker"""
    user_id = session.get('user')
    
    # Get broker template
    templates = get_broker_templates(active_only=True)
    template = next((t for t in templates if t['broker_name'] == broker_name), None)
    
    if not template:
        flash(f'Broker {broker_name} not supported', 'error')
        return redirect(url_for('broker_setup.setup_wizard'))
    
    # Get existing configuration if any
    existing_config = get_broker_config(user_id, broker_name)
    
    # Generate redirect URL
    redirect_url = format_redirect_url(broker_name)
    
    return render_template('broker_configure.html',
                         template=template,
                         existing_config=existing_config,
                         redirect_url=redirect_url,
                         broker_name=broker_name)

@broker_setup_bp.route('/save', methods=['POST'])
@limiter.limit("5 per minute")
def save_configuration():
    """Save broker configuration"""
    try:
        user_id = session.get('user')
        broker_name = request.form.get('broker_name')
        
        if not broker_name:
            return jsonify({'success': False, 'message': 'Broker name is required'}), 400
        
        # Get form data
        api_key = request.form.get('api_key', '').strip()
        api_secret = request.form.get('api_secret', '').strip()
        market_api_key = request.form.get('market_api_key', '').strip() or None
        market_api_secret = request.form.get('market_api_secret', '').strip() or None
        redirect_url = request.form.get('redirect_url', '').strip() or None
        is_default = request.form.get('is_default') == 'on'
        
        # Validate required fields
        if not api_key or not api_secret:
            return jsonify({'success': False, 'message': 'API key and secret are required'}), 400
        
        # Validate XTS broker requirements
        if is_xts_broker(broker_name):
            if not market_api_key or not market_api_secret:
                return jsonify({'success': False, 'message': 'Market data credentials are required for XTS brokers'}), 400
        
        # Check if this is an update to existing credentials
        existing_config = get_broker_config(user_id, broker_name)
        credentials_changed = False
        
        if existing_config:
            # Check if any critical credentials have changed
            if (existing_config.get('api_key') != api_key or 
                existing_config.get('api_secret') != api_secret or
                existing_config.get('market_api_key') != market_api_key or
                existing_config.get('market_api_secret') != market_api_secret):
                credentials_changed = True
                logger.info(f"Credentials changed for {user_id}/{broker_name} - will trigger logout")
        
        # Prepare credentials
        credentials = {
            'api_key': api_key,
            'api_secret': api_secret,
            'market_api_key': market_api_key,
            'market_api_secret': market_api_secret,
            'redirect_url': redirect_url
        }
        
        # Validate credentials structure
        is_valid, error_msg = validate_broker_credentials(credentials, broker_name)
        if not is_valid:
            return jsonify({'success': False, 'message': error_msg}), 400
        
        # Get client IP for audit
        client_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        user_agent = request.headers.get('User-Agent')
        
        # Save configuration
        config_id = create_broker_config(
            user_id=user_id,
            broker_name=broker_name,
            api_key=api_key,
            api_secret=api_secret,
            market_api_key=market_api_key,
            market_api_secret=market_api_secret,
            redirect_url=redirect_url,
            is_default=is_default,
            ip_address=client_ip,
            user_agent=user_agent
        )
        
        logger.info(f"Saved broker configuration for {user_id}/{broker_name}")
        
        # If credentials changed, clear auth tokens and trigger logout
        if credentials_changed:
            # Clear auth tokens from database
            from database.auth_db import Auth, db
            Auth.query.filter_by(userid=user_id).delete()
            db.session.commit()
            logger.info(f"Cleared auth tokens for {user_id} due to credential change")
            
            # Clear session data
            session.clear()
            
            return jsonify({
                'success': True, 
                'message': 'Configuration saved successfully',
                'config_id': config_id,
                'logout_required': True,
                'logout_url': url_for('auth.login')
            })
        
        return jsonify({
            'success': True, 
            'message': 'Configuration saved successfully',
            'config_id': config_id,
            'logout_required': False
        })
        
    except Exception as e:
        logger.error(f"Error saving broker configuration: {e}")
        return jsonify({'success': False, 'message': 'Failed to save configuration'}), 500

# Test connection route removed - OAuth 2.0 brokers require manual authentication
# Keeping route commented for potential future use with non-OAuth brokers
# @broker_setup_bp.route('/test', methods=['POST'])
# @limiter.limit("3 per minute")
# def test_connection():
#     """Test broker connection - DISABLED: OAuth 2.0 brokers require manual auth"""
#     return jsonify({'success': False, 'message': 'Connection testing disabled for OAuth 2.0 brokers'}), 400

@broker_setup_bp.route('/manage')
def manage_brokers():
    """Manage existing broker configurations"""
    user_id = session.get('user')
    
    # Get user's brokers with details
    user_brokers = get_user_brokers(user_id)
    
    # Add masked credentials for display
    for broker in user_brokers:
        config = get_broker_config(user_id, broker['broker_name'])
        if config:
            broker['masked_credentials'] = mask_credentials(config)
            broker['redirect_url'] = config.get('redirect_url')
        
    return render_template('broker_manage.html', brokers=user_brokers)

@broker_setup_bp.route('/delete/<broker_name>', methods=['POST'])
@limiter.limit("3 per minute")
def delete_configuration(broker_name):
    """Delete broker configuration"""
    try:
        user_id = session.get('user')
        client_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        
        success = delete_broker_config(user_id, broker_name, client_ip)
        
        if success:
            logger.info(f"Deleted broker configuration for {user_id}/{broker_name}")
            flash(f'Broker {broker_name} configuration deleted successfully', 'success')
        else:
            flash(f'Failed to delete broker {broker_name} configuration', 'error')
        
        return redirect(url_for('broker_setup.manage_brokers'))
        
    except Exception as e:
        logger.error(f"Error deleting broker configuration: {e}")
        flash('Failed to delete broker configuration', 'error')
        return redirect(url_for('broker_setup.manage_brokers'))

@broker_setup_bp.route('/set-default/<broker_name>', methods=['POST'])
@limiter.limit("5 per minute")
def set_default_broker(broker_name):
    """Set broker as default"""
    try:
        user_id = session.get('user')
        
        # Get existing config
        config = get_broker_config(user_id, broker_name)
        if not config:
            return jsonify({'success': False, 'message': 'Broker configuration not found'}), 404
        
        # Update to set as default
        client_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        user_agent = request.headers.get('User-Agent')
        
        create_broker_config(
            user_id=user_id,
            broker_name=broker_name,
            api_key=config['api_key'],
            api_secret=config['api_secret'],
            market_api_key=config.get('market_api_key'),
            market_api_secret=config.get('market_api_secret'),
            redirect_url=config.get('redirect_url'),
            is_default=True,
            ip_address=client_ip,
            user_agent=user_agent
        )
        
        logger.info(f"Set {broker_name} as default broker for {user_id}")
        
        return jsonify({'success': True, 'message': f'{broker_name} set as default broker'})
        
    except Exception as e:
        logger.error(f"Error setting default broker: {e}")
        return jsonify({'success': False, 'message': 'Failed to set default broker'}), 500

@broker_setup_bp.route('/api/templates')
def api_get_templates():
    """API endpoint to get broker templates"""
    try:
        templates = get_broker_templates(active_only=True)
        return jsonify({'success': True, 'templates': templates})
    except Exception as e:
        logger.error(f"Error getting broker templates: {e}")
        return jsonify({'success': False, 'message': 'Failed to get templates'}), 500

@broker_setup_bp.route('/api/user-brokers')
def api_get_user_brokers():
    """API endpoint to get user's broker configurations"""
    try:
        user_id = session.get('user')
        brokers = get_user_brokers(user_id)
        return jsonify({'success': True, 'brokers': brokers})
    except Exception as e:
        logger.error(f"Error getting user brokers: {e}")
        return jsonify({'success': False, 'message': 'Failed to get brokers'}), 500