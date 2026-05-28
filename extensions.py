from flask_socketio import SocketIO

# Use async_mode="eventlet" to match the gunicorn worker class.
# With async_mode="threading", Socket.IO cannot complete the WebSocket upgrade
# handshake under gunicorn+eventlet and falls back to HTTP long-polling.
# Each poll holds the connection for ~ping_timeout seconds, serialising all
# requests through the single worker and causing severe UI latency.
# See: https://flask-socketio.readthedocs.io/en/latest/deployment.html
socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode="eventlet",
    ping_timeout=10,  # Time in seconds before considering the connection lost
    ping_interval=5,  # Interval in seconds between pings
    logger=False,  # Disable built-in logging to avoid noise from disconnection errors
    engineio_logger=False,  # Disable engine.io logging
)
