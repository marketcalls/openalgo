from flask_socketio import SocketIO

# Disable eventlet to prevent greenlet threading errors
# This fixes concurrent order placement issues in Docker
socketio = SocketIO(cors_allowed_origins='*', async_mode='threading')
