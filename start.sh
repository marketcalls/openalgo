#!/bin/bash
echo "[OpenAlgo] Starting up..."

# ============================================
# RAILWAY/CLOUD ENVIRONMENT DETECTION & .env GENERATION
# ============================================

# Determine writable .env location
ENV_FILE="/app/.env"

# Check if .env exists, is readable, and has content (not empty)
if [ -f "$ENV_FILE" ] && [ -r "$ENV_FILE" ] && [ -s "$ENV_FILE" ]; then
    echo "[OpenAlgo] Using existing .env file"
else
    echo "[OpenAlgo] No .env file found or file is empty. Checking for environment variables..."
    
    # Check if we're on Railway/Cloud (HOST_SERVER is the key indicator)
    if [ -n "$HOST_SERVER" ]; then
        echo "[OpenAlgo] Environment variables detected. Generating .env file..."
        
        # Extract domain without https:// for WebSocket URL
        HOST_DOMAIN="${HOST_SERVER#https://}"
        HOST_DOMAIN="${HOST_DOMAIN#http://}"
        
        # Try to write to /app/.env, fallback to /tmp/.env if permission denied
        if ! touch "$ENV_FILE" 2>/dev/null; then
            echo "[OpenAlgo] Cannot write to /app/.env, using /tmp/.env"
            ENV_FILE="/tmp/.env"
        fi
        
        # Use Railway's PORT, default to 5000 for local development
        APP_PORT="${PORT:-5000}"
        
        cat > "$ENV_FILE" << EOF
# OpenAlgo Environment Configuration File
# Auto-generated from environment variables
ENV_CONFIG_VERSION = '${ENV_CONFIG_VERSION:-1.0.4}'

# Broker Configuration
BROKER_API_KEY = '${BROKER_API_KEY}'
BROKER_API_SECRET = '${BROKER_API_SECRET}'

# Market Data Configuration (XTS Brokers only)
BROKER_API_KEY_MARKET = '${BROKER_API_KEY_MARKET:-}'
BROKER_API_SECRET_MARKET = '${BROKER_API_SECRET_MARKET:-}'

# Redirect URL
REDIRECT_URL = '${REDIRECT_URL}'

# Valid Brokers Configuration
VALID_BROKERS = '${VALID_BROKERS:-fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,dhan,dhan_sandbox,definedge,firstock,flattrade,fyers,groww,ibulls,iifl,indmoney,jainamxts,kotak,motilal,mstock,paytm,pocketful,samco,shoonya,tradejini,upstox,wisdom,zebu,zerodha}'

# Security Configuration
APP_KEY = '${APP_KEY}'
API_KEY_PEPPER = '${API_KEY_PEPPER}'

# Database Configuration
DATABASE_URL = '${DATABASE_URL:-sqlite:///db/openalgo.db}'
LATENCY_DATABASE_URL = '${LATENCY_DATABASE_URL:-sqlite:///db/latency.db}'
LOGS_DATABASE_URL = '${LOGS_DATABASE_URL:-sqlite:///db/logs.db}'
SANDBOX_DATABASE_URL = '${SANDBOX_DATABASE_URL:-sqlite:///db/sandbox.db}'

# Ngrok - Disabled for cloud deployment
NGROK_ALLOW = '${NGROK_ALLOW:-FALSE}'

# Host Server
HOST_SERVER = '${HOST_SERVER}'

# Flask Configuration - Use Railway's PORT
FLASK_HOST_IP = '0.0.0.0'
FLASK_PORT = '${APP_PORT}'
FLASK_DEBUG = '${FLASK_DEBUG:-False}'
FLASK_ENV = '${FLASK_ENV:-production}'

# WebSocket Configuration
WEBSOCKET_HOST = '0.0.0.0'
WEBSOCKET_PORT = '${WEBSOCKET_PORT:-8765}'
WEBSOCKET_URL = '${WEBSOCKET_URL:-wss://${HOST_DOMAIN}/ws}'

# ZeroMQ Configuration
ZMQ_HOST = '0.0.0.0'
ZMQ_PORT = '${ZMQ_PORT:-5555}'

# Logging Configuration
LOG_TO_FILE = '${LOG_TO_FILE:-True}'
LOG_LEVEL = '${LOG_LEVEL:-INFO}'
LOG_DIR = '${LOG_DIR:-log}'
LOG_FORMAT = '${LOG_FORMAT:-[%(asctime)s] %(levelname)s in %(module)s: %(message)s}'
LOG_RETENTION = '${LOG_RETENTION:-14}'
LOG_COLORS = '${LOG_COLORS:-True}'
FORCE_COLOR = '${FORCE_COLOR:-1}'

# Rate Limit Settings
LOGIN_RATE_LIMIT_MIN = '${LOGIN_RATE_LIMIT_MIN:-5 per minute}'
LOGIN_RATE_LIMIT_HOUR = '${LOGIN_RATE_LIMIT_HOUR:-25 per hour}'
RESET_RATE_LIMIT = '${RESET_RATE_LIMIT:-15 per hour}'
API_RATE_LIMIT = '${API_RATE_LIMIT:-50 per second}'
ORDER_RATE_LIMIT = '${ORDER_RATE_LIMIT:-10 per second}'
SMART_ORDER_RATE_LIMIT = '${SMART_ORDER_RATE_LIMIT:-2 per second}'
WEBHOOK_RATE_LIMIT = '${WEBHOOK_RATE_LIMIT:-100 per minute}'
STRATEGY_RATE_LIMIT = '${STRATEGY_RATE_LIMIT:-200 per minute}'

# API Configuration
SMART_ORDER_DELAY = '${SMART_ORDER_DELAY:-0.5}'
SESSION_EXPIRY_TIME = '${SESSION_EXPIRY_TIME:-03:00}'

# CORS Configuration
CORS_ENABLED = '${CORS_ENABLED:-TRUE}'
CORS_ALLOWED_ORIGINS = '${CORS_ALLOWED_ORIGINS:-${HOST_SERVER}}'
CORS_ALLOWED_METHODS = '${CORS_ALLOWED_METHODS:-GET,POST,DELETE,PUT,PATCH}'
CORS_ALLOWED_HEADERS = '${CORS_ALLOWED_HEADERS:-Content-Type,Authorization,X-Requested-With}'
CORS_EXPOSED_HEADERS = '${CORS_EXPOSED_HEADERS:-}'
CORS_ALLOW_CREDENTIALS = '${CORS_ALLOW_CREDENTIALS:-FALSE}'
CORS_MAX_AGE = '${CORS_MAX_AGE:-86400}'

# CSP Configuration
CSP_ENABLED = '${CSP_ENABLED:-TRUE}'
CSP_REPORT_ONLY = '${CSP_REPORT_ONLY:-FALSE}'
CSP_DEFAULT_SRC = '${CSP_DEFAULT_SRC:-"'"'"'self'"'"'"}'
CSP_SCRIPT_SRC = '${CSP_SCRIPT_SRC:-"'"'"'self'"'"' '"'"'unsafe-inline'"'"' https://cdn.socket.io https://static.cloudflareinsights.com"}'
CSP_STYLE_SRC = '${CSP_STYLE_SRC:-"'"'"'self'"'"' '"'"'unsafe-inline'"'"'"}'
CSP_IMG_SRC = '${CSP_IMG_SRC:-"'"'"'self'"'"' data:"}'
CSP_CONNECT_SRC = '${CSP_CONNECT_SRC:-"'"'"'self'"'"' wss://${HOST_DOMAIN} wss: ws: https://cdn.socket.io"}'
CSP_FONT_SRC = '${CSP_FONT_SRC:-"'"'"'self'"'"'"}'
CSP_OBJECT_SRC = '${CSP_OBJECT_SRC:-"'"'"'none'"'"'"}'
CSP_MEDIA_SRC = '${CSP_MEDIA_SRC:-"'"'"'self'"'"' data: https://*.amazonaws.com https://*.cloudfront.net"}'
CSP_FRAME_SRC = '${CSP_FRAME_SRC:-"'"'"'self'"'"'"}'
CSP_FORM_ACTION = '${CSP_FORM_ACTION:-"'"'"'self'"'"'"}'
CSP_FRAME_ANCESTORS = '${CSP_FRAME_ANCESTORS:-"'"'"'self'"'"'"}'
CSP_BASE_URI = '${CSP_BASE_URI:-"'"'"'self'"'"'"}'
CSP_UPGRADE_INSECURE_REQUESTS = '${CSP_UPGRADE_INSECURE_REQUESTS:-TRUE}'
CSP_REPORT_URI = '${CSP_REPORT_URI:-}'

# CSRF Configuration
CSRF_ENABLED = '${CSRF_ENABLED:-TRUE}'
CSRF_TIME_LIMIT = '${CSRF_TIME_LIMIT:-}'

# Cookie Configuration
SESSION_COOKIE_NAME = '${SESSION_COOKIE_NAME:-session}'
CSRF_COOKIE_NAME = '${CSRF_COOKIE_NAME:-csrf_token}'
EOF

        echo "[OpenAlgo] .env file generated at $ENV_FILE"
        echo "[OpenAlgo] Configuration: HOST_SERVER=${HOST_SERVER}"
        
        # If we wrote to /tmp, create symlink to /app/.env (or copy if symlink fails)
        if [ "$ENV_FILE" = "/tmp/.env" ]; then
            ln -sf /tmp/.env /app/.env 2>/dev/null || cp /tmp/.env /app/.env 2>/dev/null || true
            echo "[OpenAlgo] Linked .env to /app/.env"
        fi
    else
        echo "============================================"
        echo "Error: .env file not found."
        echo "Solution: Copy .sample.env to .env and configure your settings"
        echo ""
        echo "For cloud deployment (Railway/Render), set these environment variables:"
        echo "  - HOST_SERVER (your app domain, e.g., https://your-app.up.railway.app)"
        echo "  - REDIRECT_URL (your broker callback URL)"
        echo "  - BROKER_API_KEY"
        echo "  - BROKER_API_SECRET"
        echo "  - APP_KEY (generate with: python -c \"import secrets; print(secrets.token_hex(32))\")"
        echo "  - API_KEY_PEPPER (generate another one)"
        echo "============================================"
        exit 1
    fi
fi

# ============================================
# DIRECTORY SETUP (Original functionality)
# ============================================
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

# ============================================
# WEBSOCKET PROXY SERVER
# ============================================
echo "[OpenAlgo] Starting WebSocket proxy server on port 8765..."
/app/.venv/bin/python -m websocket_proxy.server &
WEBSOCKET_PID=$!
echo "[OpenAlgo] WebSocket proxy server started with PID $WEBSOCKET_PID"

# ============================================
# CLEANUP HANDLER
# ============================================
cleanup() {
    echo "[OpenAlgo] Shutting down..."
    if [ ! -z "$WEBSOCKET_PID" ]; then
        kill $WEBSOCKET_PID 2>/dev/null
    fi
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# ============================================
# START MAIN APPLICATION
# ============================================
# Use PORT env var if set (Railway/cloud), otherwise default to 5000
APP_PORT="${PORT:-5000}"

echo "[OpenAlgo] Starting application on port ${APP_PORT} with eventlet..."
exec /app/.venv/bin/gunicorn \
    --worker-class eventlet \
    --workers 1 \
    --bind 0.0.0.0:${APP_PORT} \
    --timeout 120 \
    --graceful-timeout 30 \
    --log-level warning \
    app:app
