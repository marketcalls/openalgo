"""
Example blueprint showing how to use the WebSocket service layer
for internal UI components without authentication overhead.
"""

from flask import Blueprint, render_template, request, jsonify, session, current_app
from extensions import socketio
from flask_socketio import emit, join_room, leave_room
from utils.session import check_session_validity
from services.websocket_service import (
    get_websocket_status,
    get_websocket_subscriptions,
    subscribe_to_symbols,
    unsubscribe_from_symbols,
    unsubscribe_all,
    get_market_data
)
from services.market_data_service import (
    get_market_data_service,
    subscribe_to_market_updates,
    unsubscribe_from_market_updates
)
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Create blueprint
websocket_bp = Blueprint('websocket', __name__)

# Track Socket.IO subscriber IDs per session
socketio_subscribers = {}

def get_username_from_session():
    """Get username from current session"""
    username = session.get('user')
    if username:
        logger.info(f"Debug: username='{username}'")
        
        # Check if API key exists for this user (using username directly)
        from database.auth_db import get_api_key_for_tradingview
        api_key = get_api_key_for_tradingview(username)
        logger.info(f"Debug: API key found for username '{username}': {bool(api_key)}")
        
        return username
    else:
        logger.warning("Debug: No username in session")
    return None

@websocket_bp.route('/websocket/dashboard')
@check_session_validity
def websocket_dashboard():
    """Render WebSocket dashboard for testing"""
    return render_template('websocket/dashboard.html')

@websocket_bp.route('/websocket/test')
@check_session_validity
def websocket_test():
    """Render WebSocket test page for RELIANCE and TCS"""
    return render_template('websocket/test_market_data.html')

# REST endpoints for UI (no additional auth needed - page is already protected)
@websocket_bp.route('/api/websocket/status', methods=['GET'])
def api_websocket_status():
    """Get WebSocket connection status for current user"""
    username = get_username_from_session()
    if not username:
        return jsonify({
            'status': 'error', 
            'message': 'Session not found - please refresh page',
            'connected': False,
            'authenticated': False
        }), 200
    
    success, data, status_code = get_websocket_status(username)
    return jsonify(data), status_code

@websocket_bp.route('/api/websocket/subscriptions', methods=['GET'])
def api_websocket_subscriptions():
    """Get current subscriptions for current user"""
    username = get_username_from_session()
    if not username:
        return jsonify({
            'status': 'error', 
            'message': 'Session not found - please refresh page',
            'subscriptions': []
        }), 200
    
    success, data, status_code = get_websocket_subscriptions(username)
    return jsonify(data), status_code

@websocket_bp.route('/api/websocket/subscribe', methods=['POST'])
def api_websocket_subscribe():
    """Subscribe to symbols for current user"""
    username = get_username_from_session()
    if not username:
        return jsonify({'status': 'error', 'message': 'Session not found - please refresh page'}), 200
    
    data = request.get_json()
    
    symbols = data.get('symbols', [])
    mode = data.get('mode', 'Quote')
    broker = data.get('broker')  # Optional, will be fetched if not provided
    
    success, result, status_code = subscribe_to_symbols(username, broker, symbols, mode)
    return jsonify(result), status_code

@websocket_bp.route('/api/websocket/unsubscribe', methods=['POST'])
def api_websocket_unsubscribe():
    """Unsubscribe from symbols for current user"""
    username = get_username_from_session()
    if not username:
        return jsonify({'status': 'error', 'message': 'Session not found - please refresh page'}), 200
    
    data = request.get_json()
    
    symbols = data.get('symbols', [])
    mode = data.get('mode', 'Quote')
    broker = data.get('broker')
    
    success, result, status_code = unsubscribe_from_symbols(username, broker, symbols, mode)
    return jsonify(result), status_code

@websocket_bp.route('/api/websocket/unsubscribe-all', methods=['POST'])
def api_websocket_unsubscribe_all():
    """Unsubscribe from all symbols for current user"""
    username = get_username_from_session()
    if not username:
        return jsonify({'status': 'error', 'message': 'Session not found - please refresh page'}), 200
    
    broker = request.get_json().get('broker') if request.get_json() else None
    
    success, result, status_code = unsubscribe_all(username, broker)
    return jsonify(result), status_code

@websocket_bp.route('/api/websocket/market-data', methods=['GET'])
def api_websocket_market_data():
    """Get cached market data"""
    username = get_username_from_session()
    if not username:
        return jsonify({'status': 'error', 'message': 'Session not found - please refresh page'}), 200
    
    symbol = request.args.get('symbol')
    exchange = request.args.get('exchange')
    
    success, data, status_code = get_market_data(username, symbol, exchange)
    return jsonify(data), status_code

@websocket_bp.route('/api/websocket/apikey', methods=['GET'])
def api_get_websocket_apikey():
    """Get API key for WebSocket authentication"""
    username = get_username_from_session()
    if not username:
        return jsonify({'status': 'error', 'message': 'Session not found - please refresh page'}), 401
    
    from database.auth_db import get_api_key_for_tradingview
    api_key = get_api_key_for_tradingview(username)
    
    if not api_key:
        return jsonify({'status': 'error', 'message': 'No API key found. Please generate an API key first.'}), 404
    
    return jsonify({'status': 'success', 'api_key': api_key}), 200

@websocket_bp.route('/api/websocket/config', methods=['GET'])
def api_get_websocket_config():
    """Get WebSocket configuration including URL"""
    username = get_username_from_session()
    if not username:
        return jsonify({'status': 'error', 'message': 'Session not found - please refresh page'}), 401
    
    import os
    from flask import request
    
    websocket_url = os.getenv('WEBSOCKET_URL', 'ws://localhost:8765')
    
    # If the current request is HTTPS and the WebSocket URL is WS, upgrade to WSS
    if request.is_secure and websocket_url.startswith('ws://'):
        websocket_url = websocket_url.replace('ws://', 'wss://')
        logger.info(f"Upgraded WebSocket URL to secure: {websocket_url}")
    
    return jsonify({
        'status': 'success',
        'websocket_url': websocket_url,
        'is_secure': request.is_secure,
        'original_url': os.getenv('WEBSOCKET_URL', 'ws://localhost:8765')
    }), 200

# Socket.IO events for real-time updates
@socketio.on('connect', namespace='/market')
def handle_connect(auth):
    """Handle client connection"""
    username = get_username_from_session()
    if not username:
        return False  # Reject connection
    
    # Join user-specific room
    join_room(f'user_{username}')
    
    emit('connected', {'status': 'Connected to market data stream'})
    logger.info(f"User {username} connected to market data stream")

@socketio.on('disconnect', namespace='/market')
def handle_disconnect():
    """Handle client disconnection"""
    username = get_username_from_session()
    if username:
        leave_room(f'user_{username}')
        
        # Clean up any subscriptions if needed
        if request.sid in socketio_subscribers:
            del socketio_subscribers[request.sid]
        
        logger.info(f"User {username} disconnected from market data stream")

@socketio.on('subscribe', namespace='/market')
def handle_subscribe(data):
    """Handle subscription request via Socket.IO"""
    username = get_username_from_session()
    if not username:
        emit('error', {'message': 'Not authenticated'})
        return
    
    symbols = data.get('symbols', [])
    mode = data.get('mode', 'Quote')
    broker = data.get('broker')
    
    success, result, _ = subscribe_to_symbols(username, broker, symbols, mode)
    
    if success:
        emit('subscription_success', result)
    else:
        emit('subscription_error', result)

@socketio.on('unsubscribe', namespace='/market')
def handle_unsubscribe(data):
    """Handle unsubscription request via Socket.IO"""
    username = get_username_from_session()
    if not username:
        emit('error', {'message': 'Not authenticated'})
        return
    
    symbols = data.get('symbols', [])
    mode = data.get('mode', 'Quote')
    broker = data.get('broker')
    
    success, result, _ = unsubscribe_from_symbols(username, broker, symbols, mode)
    
    if success:
        emit('unsubscription_success', result)
    else:
        emit('unsubscription_error', result)

@socketio.on('get_ltp', namespace='/market')
def handle_get_ltp(data):
    """Get LTP for a symbol"""
    symbol = data.get('symbol')
    exchange = data.get('exchange')
    
    if not symbol or not exchange:
        emit('error', {'message': 'Symbol and exchange are required'})
        return
    
    market_service = get_market_data_service()
    ltp_data = market_service.get_ltp(symbol, exchange)
    
    emit('ltp_data', {
        'symbol': symbol,
        'exchange': exchange,
        'data': ltp_data
    })

@socketio.on('get_quote', namespace='/market')
def handle_get_quote(data):
    """Get quote for a symbol"""
    symbol = data.get('symbol')
    exchange = data.get('exchange')
    
    if not symbol or not exchange:
        emit('error', {'message': 'Symbol and exchange are required'})
        return
    
    market_service = get_market_data_service()
    quote_data = market_service.get_quote(symbol, exchange)
    
    emit('quote_data', {
        'symbol': symbol,
        'exchange': exchange,
        'data': quote_data
    })

@socketio.on('get_depth', namespace='/market')
def handle_get_depth(data):
    """Get market depth for a symbol"""
    symbol = data.get('symbol')
    exchange = data.get('exchange')
    
    if not symbol or not exchange:
        emit('error', {'message': 'Symbol and exchange are required'})
        return
    
    market_service = get_market_data_service()
    depth_data = market_service.get_market_depth(symbol, exchange)
    
    emit('depth_data', {
        'symbol': symbol,
        'exchange': exchange,
        'data': depth_data
    })

# Example usage in other parts of the application
def example_usage():
    """
    Example of how to use the WebSocket service layer in other parts of the app
    """
    # Example 1: Subscribe to symbols for a user
    user_id = 123
    symbols = [
        {'symbol': 'RELIANCE', 'exchange': 'NSE'},
        {'symbol': 'TCS', 'exchange': 'NSE'}
    ]
    success, result, status = subscribe_to_symbols(user_id, 'zerodha', symbols, 'Quote')
    
    # Example 2: Get LTP directly from cache
    market_service = get_market_data_service()
    ltp = market_service.get_ltp('RELIANCE', 'NSE')
    
    # Example 3: Subscribe to updates
    def my_callback(data):
        print(f"Received update: {data}")
    
    subscriber_id = subscribe_to_market_updates('ltp', my_callback, {'NSE:RELIANCE', 'NSE:TCS'})
    
    # Example 4: Get market data for a user
    success, data, status = get_market_data(user_id, 'RELIANCE', 'NSE')