
from flask import Blueprint, jsonify, render_template, request, session, redirect, url_for
from itsdangerous import URLSafeTimedSerializer
from database.auth_db import upsert_api_key , get_api_key
import os


api_key_bp = Blueprint('api_key_bp', __name__, url_prefix='/')

app_secret_key = os.getenv('APP_KEY')

def generate_api_key(user_id):
    serializer = URLSafeTimedSerializer(app_secret_key)
    return serializer.dumps(user_id, salt='api_key')

@api_key_bp.route('/apikey', methods=['GET', 'POST'])
def manage_api_key():
    if not session.get('logged_in'):
        return redirect(url_for('auth.login'))  
    
    if request.method == 'GET':
        login_username = session['user']
        current_api_key = get_api_key(login_username)
        # Placeholder for fetching the user's current API key if needed
        return render_template('apikey.html', login_username=login_username,api_key=current_api_key)
    else:
        user_id = request.json.get('user_id')
        if not user_id:
            return jsonify({'error': 'User ID is required'}), 400
        
        api_key = generate_api_key(user_id)
        key_id = upsert_api_key(user_id, api_key)
        
        if key_id is not None:
            return jsonify({'message': 'API key updated successfully', 'api_key': api_key, 'key_id': key_id})
        else:
            return jsonify({'error': 'Failed to update API key'}), 500