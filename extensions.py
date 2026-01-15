from flask_socketio import SocketIO

# Disable eventlet to prevent greenlet threading errors
# This fixes concurrent order placement issues in Docker
# Added error handling for disconnected sessions
socketio = SocketIO(
    cors_allowed_origins='*', 
    async_mode='threading',
    ping_timeout=10,  # Time in seconds before considering the connection lost
    ping_interval=5,  # Interval in seconds between pings
    logger=False,  # Disable built-in logging to avoid noise from disconnection errors
    engineio_logger=False  # Disable engine.io logging
)
