from flask import Blueprint, jsonify, render_template, request, session, redirect, url_for
from itsdangerous import URLSafeTimedSerializer
from database.auth_db import upsert_api_key, get_api_key
from utils.session import check_session_validity
import os
import logging

logger = logging.getLogger(__name__)

api_key_bp = Blueprint('api_key_bp', __name__, url_prefix='/')

app_secret_key = os.getenv('APP_KEY')

def generate_api_key(user_id):
    serializer = URLSafeTimedSerializer(app_secret_key)
    return serializer.dumps(user_id, salt='api_key')

@api_key_bp.route('/apikey', methods=['GET', 'POST'])
@check_session_validity
def manage_api_key():
    if request.method == 'GET':
        login_username = session['user']
        current_api_key = get_api_key(login_username)
        logger.info(f"Fetching API key for user: {login_username}")
        return render_template('apikey.html', login_username=login_username, api_key=current_api_key)
    else:
        user_id = request.json.get('user_id')
        if not user_id:
            logger.error("API key update attempted without user ID")
            return jsonify({'error': 'User ID is required'}), 400
        
        api_key = generate_api_key(user_id)
        key_id = upsert_api_key(user_id, api_key)
        
        if key_id is not None:
            logger.info(f"API key updated successfully for user: {user_id}")
            return jsonify({'message': 'API key updated successfully', 'api_key': api_key, 'key_id': key_id})
        else:
            logger.error(f"Failed to update API key for user: {user_id}")
            return jsonify({'error': 'Failed to update API key'}), 500
