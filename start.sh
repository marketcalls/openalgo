#!/bin/bash

echo "[OpenAlgo] Starting up..."

# Try to create directories, but don't fail if they already exist or can't be created
# This handles both mounted volumes and permission issues
for dir in db log log/strategies strategies strategies/scripts keys; do
    mkdir -p "$dir" 2>/dev/null || true
done

# Try to set permissions if possible, but continue regardless
# This will work for local directories but skip for mounted volumes
if [ -w "." ]; then
    # Set more permissive permissions for directories
    chmod -R 755 db log strategies 2>/dev/null || echo "⚠️  Skipping chmod (may be mounted volume or permission restricted)"
    # Set restrictive permissions for keys directory (only owner can access)
    chmod 700 keys 2>/dev/null || true
else
    echo "⚠️  Running with restricted permissions (mounted volume detected)"
fi

# Ensure Python can create directories at runtime if needed
export PYTHONDONTWRITEBYTECODE=1

cd /app

# Start WebSocket proxy server in background
echo "[OpenAlgo] Starting WebSocket proxy server on port 8765..."
/app/.venv/bin/python -m websocket_proxy.server &
WEBSOCKET_PID=$!
echo "[OpenAlgo] WebSocket proxy server started with PID $WEBSOCKET_PID"

# Function to cleanup on exit
cleanup() {
    echo "[OpenAlgo] Shutting down..."
    if [ ! -z "$WEBSOCKET_PID" ]; then
        kill $WEBSOCKET_PID 2>/dev/null
    fi
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# Run main application with gunicorn using eventlet for WebSocket support
echo "[OpenAlgo] Starting application on port 5000 with eventlet..."
exec /app/.venv/bin/gunicorn \
    --worker-class eventlet \
    --workers 1 \
    --bind 0.0.0.0:5000 \
    --timeout 120 \
    --graceful-timeout 30 \
    --log-level warning \
    app:app
