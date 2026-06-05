from flask_socketio import SocketIO

# Disable eventlet to prevent greenlet threading errors
# This fixes concurrent order placement issues in Docker
# Added error handling for disconnected sessions
socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode="threading",
    # engine.io defaults. The previous 10s/5s was too tight for the single
    # gunicorn+eventlet worker: when that one worker is busy (placing orders,
    # webhook signals, DB queries), the heartbeat green thread is starved and
    # can't answer within 10s, so engine.io drops the connection and the
    # browser enters a disconnect/reconnect loop. 60s/25s gives ~6x more grace
    # before a busy-but-alive connection is declared dead (#1419).
    ping_timeout=60,  # Time in seconds before considering the connection lost
    ping_interval=25,  # Interval in seconds between pings
    logger=False,  # Disable built-in logging to avoid noise from disconnection errors
    engineio_logger=False,  # Disable engine.io logging
)
