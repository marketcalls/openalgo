from flask import Blueprint, jsonify, render_template, request, session, redirect, url_for
import os
import logging
import secrets
from argon2 import PasswordHasher
from database.auth_db import upsert_api_key, get_api_key, verify_api_key
from utils.session import check_session_validity

logger = logging.getLogger(__name__)

api_key_bp = Blueprint('api_key_bp', __name__, url_prefix='/')

# Initialize Argon2 hasher
ph = PasswordHasher()

def generate_api_key():
    """Generate a secure random API key"""
    # Generate 32 bytes of random data and encode as hex
    return secrets.token_hex(32)

@api_key_bp.route('/apikey', methods=['GET', 'POST'])
@check_session_validity
def manage_api_key():
    if request.method == 'GET':
        login_username = session['user']
        # We don't show the actual API key after creation for security
        has_api_key = get_api_key(login_username) is not None
        logger.info(f"Checking API key status for user: {login_username}")
        return render_template('apikey.html', login_username=login_username, has_api_key=has_api_key)
    else:
        user_id = request.json.get('user_id')
        if not user_id:
            logger.error("API key update attempted without user ID")
            return jsonify({'error': 'User ID is required'}), 400
        
        # Generate new API key
        api_key = generate_api_key()
        
        # Store the API key (auth_db will handle both hashing and encryption)
        key_id = upsert_api_key(user_id, api_key)
        
        if key_id is not None:
            logger.info(f"API key updated successfully for user: {user_id}")
            # Return the unhashed key to user - this is the only time they'll see it
            return jsonify({
                'message': 'API key updated successfully. Please save this key as it won\'t be shown again.',
                'api_key': api_key,
                'key_id': key_id
            })
        else:
            logger.error(f"Failed to update API key for user: {user_id}")
            return jsonify({'error': 'Failed to update API key'}), 500
