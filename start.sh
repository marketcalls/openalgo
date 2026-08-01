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
VALID_BROKERS = '${VALID_BROKERS:-fivepaisa,fivepaisaxts,aliceblue,angel,arrow,compositedge,definedge,deltaexchange,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,hdfcsky,ibulls,iifl,iiflcapital,indmoney,jainamxts,kotak,motilal,mstock,nubra,paytm,pocketful,rmoney,samco,shoonya,tradejini,tradesmart,upstox,wisdom,zebu,zerodha}'

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
# 0.0.0.0 is required on Railway/cloud so the platform proxy can reach the port.
WEBSOCKET_HOST = '0.0.0.0'
WEBSOCKET_PORT = '${WEBSOCKET_PORT:-8765}'
WEBSOCKET_URL = '${WEBSOCKET_URL:-wss://${HOST_DOMAIN}/ws}'

# ZeroMQ Configuration
# Internal message bus — always loopback. Broker adapters and the WS proxy run
# in the same process; exposing ZMQ would leak the raw tick feed.
ZMQ_HOST = '127.0.0.1'
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
SMART_ORDER_RATE_LIMIT = '${SMART_ORDER_RATE_LIMIT:-10 per second}'
WEBHOOK_RATE_LIMIT = '${WEBHOOK_RATE_LIMIT:-100 per minute}'
STRATEGY_RATE_LIMIT = '${STRATEGY_RATE_LIMIT:-200 per minute}'

# API Configuration
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
    chmod -R 755 db log strategies 2>/dev/null || echo "Skipping chmod (may be mounted volume or permission restricted)"
    # Set restrictive permissions for keys directory (only owner can access)
    chmod 700 keys 2>/dev/null || true
else
    echo "Running with restricted permissions (mounted volume detected)"
fi

# Ensure Python can create directories at runtime if needed
export PYTHONDONTWRITEBYTECODE=1

cd /app

# ============================================
# PRE-FLIGHT: COMPROMISED-KEY DETECTION
# ============================================
# Issue context: every Docker user installed before v2.0.0.6 has the publicly
# known sample APP_KEY / API_KEY_PEPPER baked into their host .env (the install
# script didn't rewrite those fields until 0162ce3a5). v2.0.0.6+ ships an
# auto-rotation in utils/env_check.py that fixes this in-place — but if the
# .env mount is read-only or the file isn't owned by appuser (UID 1000), the
# rotation crashes the worker with `Permission denied: .env.tmp` and gunicorn
# enters a restart loop. Catch that here, before gunicorn starts, with an
# unmissable message instead of a buried 12-line stack trace.
PLACEHOLDER_APP_KEY="OPENALGO_PLACEHOLDER_APP_KEY_REGENERATE_BEFORE_USE"
PLACEHOLDER_PEPPER="OPENALGO_PLACEHOLDER_API_KEY_PEPPER_REGENERATE_BEFORE_USE"
LEAKED_APP_KEY="3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952729a991d8e2417"
LEAKED_PEPPER="a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772"

if [ -f "/app/.env" ]; then
    CURRENT_APP_KEY=$(grep '^APP_KEY' /app/.env 2>/dev/null | sed -E "s/.*=\s*'([^']*)'.*/\1/" | head -n1)
    CURRENT_PEPPER=$(grep '^API_KEY_PEPPER' /app/.env 2>/dev/null | sed -E "s/.*=\s*'([^']*)'.*/\1/" | head -n1)

    KEY_COMPROMISED=0
    case "$CURRENT_APP_KEY" in
        "$PLACEHOLDER_APP_KEY"|"$LEAKED_APP_KEY") KEY_COMPROMISED=1 ;;
    esac
    case "$CURRENT_PEPPER" in
        "$PLACEHOLDER_PEPPER"|"$LEAKED_PEPPER") KEY_COMPROMISED=1 ;;
    esac

    if [ "$KEY_COMPROMISED" -eq 1 ]; then
        if ! touch /app/.env.permcheck 2>/dev/null; then
            cat <<'PREFLIGHT_ERR' >&2

============================================================
[OpenAlgo] STARTUP BLOCKED — compromised APP_KEY detected
============================================================

Your .env contains the publicly-known sample APP_KEY (and
possibly API_KEY_PEPPER). OpenAlgo v2.0.0.6+ tries to
auto-rotate these on first run, but the .env file is not
writable from inside the container, so the rotation cannot
run.

This typically happens when upgrading a Docker install from
v2.0.0.5 or earlier.

Fix on the HOST machine (not inside the container):

  cd /path/to/openalgo
  docker compose down

  # 1. Generate a fresh APP_KEY only
  APP_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sed -i "s|^APP_KEY *=.*|APP_KEY = '$APP_KEY'|" .env

  # 2. Make .env writable by the container's appuser (UID 1000)
  sudo chown 1000:1000 .env
  sudo chmod 600 .env

  docker compose up -d

After this, OpenAlgo will start cleanly. Existing browser
sessions will need to log in again — APP_KEY rotation
invalidates session cookies, by design.

============================================================
[OpenAlgo] DO NOT regenerate API_KEY_PEPPER
============================================================

If you have ANY existing data (users, broker logins,
TradingView API keys), do NOT change API_KEY_PEPPER. The
pepper feeds Argon2 password hashing and the Fernet KDF for
encrypting broker auth/feed tokens. Rotating it invalidates
every stored password hash AND every encrypted token in the
database — none of which can be recovered.

If you genuinely need to rotate the pepper, use the dedicated
migration which handles re-encryption + password reset:

  uv run python upgrade/rotate_pepper.py

The auto-rotation built into the app already declines to
rotate PEPPER on a populated database for the same reason.
Only rotate it manually if your install is fresh and has no
users yet.

============================================================
PREFLIGHT_ERR
            exit 1
        fi
        rm -f /app/.env.permcheck
    fi
fi

# ============================================
# DATABASE MIGRATIONS
# ============================================
# Run migrations automatically on startup (idempotent - safe to run multiple times)
if [ -f "/app/upgrade/migrate_all.py" ]; then
    echo "[OpenAlgo] Running database migrations..."
    /app/.venv/bin/python /app/upgrade/migrate_all.py || echo "[OpenAlgo] Migration completed (some may have been skipped)"
else
    echo "[OpenAlgo] No migrations found, skipping..."
fi

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
# Forward the signal to both children and wait for them to exit, rather than
# killing the proxy and exiting immediately. Gunicorn needs its graceful
# window to drain in-flight requests.
GUNICORN_PID=""
SHUTTING_DOWN=0

cleanup() {
    SHUTTING_DOWN=1
    echo "[OpenAlgo] Shutting down..."
    if [ -n "$GUNICORN_PID" ]; then
        kill -TERM "$GUNICORN_PID" 2>/dev/null
    fi
    if [ -n "$WEBSOCKET_PID" ]; then
        kill -TERM "$WEBSOCKET_PID" 2>/dev/null
    fi
    # Give gunicorn its --graceful-timeout (30s) plus a small margin.
    for _ in $(seq 1 35); do
        kill -0 "$GUNICORN_PID" 2>/dev/null || break
        sleep 1
    done
    kill -KILL "$GUNICORN_PID" 2>/dev/null
    kill -KILL "$WEBSOCKET_PID" 2>/dev/null
    wait 2>/dev/null
    echo "[OpenAlgo] Shutdown complete"
    exit 0
}

# Set up signal handlers
trap cleanup SIGTERM SIGINT

# ============================================
# START MAIN APPLICATION
# ============================================
# Use PORT env var if set (Railway/cloud), otherwise default to 5000
APP_PORT="${PORT:-5000}"

# Decide which Gunicorn worker to run. Defaults to eventlet; a user opts into
# gthread by setting OPENALGO_WORKER_CLASS in the .env that every Docker install
# already bind-mounts at /app/.env, so the choice survives `docker pull` and
# needs no compose regeneration.
# shellcheck source=install/lib/gunicorn_runtime.sh
. /app/install/lib/gunicorn_runtime.sh
resolve_gunicorn_runtime "$ENV_FILE"

if [ "$GUNICORN_WORKER_CLASS" = "gthread" ]; then
    echo "[OpenAlgo] Starting application on port ${APP_PORT} with gthread (${GUNICORN_THREADS} threads)..."
    echo "[OpenAlgo] NOTE: gthread is opt-in and not yet the default. Report results at"
    echo "[OpenAlgo]       https://github.com/marketcalls/openalgo/issues"
else
    echo "[OpenAlgo] Starting application on port ${APP_PORT} with eventlet..."
fi

# Create gunicorn worker temp directory (must be inside container, not mounted volume)
mkdir -p /tmp/gunicorn_workers

# NOTE: gunicorn runs in the BACKGROUND, not via exec.
#
# `exec` replaces this shell, which destroys the trap installed above. The
# result was that SIGTERM never reached the WebSocket proxy, an unexpected
# proxy exit was never noticed, and the container health check only probed
# Flask -- so a container could report healthy with market data dead.
#
# This shell stays alive as a minimal supervisor: it forwards signals to both
# children, restarts the proxy if it dies, and exits when gunicorn exits.
# $GUNICORN_WORKER_ARGS is deliberately unquoted so it splits into separate
# arguments. Its contents are validated by the resolver (a fixed worker name
# and a digits-only thread count), so there is nothing here to word-split on.
# shellcheck disable=SC2086
/app/.venv/bin/gunicorn \
    $GUNICORN_WORKER_ARGS \
    --workers 1 \
    --bind 0.0.0.0:${APP_PORT} \
    --timeout 300 \
    --graceful-timeout 30 \
    --worker-tmp-dir /tmp/gunicorn_workers \
    --no-control-socket \
    --log-level warning \
    app:app &
GUNICORN_PID=$!
echo "[OpenAlgo] Gunicorn started with PID $GUNICORN_PID"

# ============================================
# SUPERVISOR LOOP
# ============================================
# Bounded proxy restarts: a proxy that cannot stay up is a real failure and
# should surface as a container exit, not an infinite restart spin.
WS_RESTARTS=0
WS_MAX_RESTARTS="${WEBSOCKET_MAX_RESTARTS:-5}"

while true; do
    sleep 2

    [ "$SHUTTING_DOWN" -eq 1 ] && break

    # Gunicorn exiting is terminal: propagate its status and let the container
    # restart policy decide what happens next.
    if ! kill -0 "$GUNICORN_PID" 2>/dev/null; then
        wait "$GUNICORN_PID"
        GUNICORN_STATUS=$?
        echo "[OpenAlgo] Gunicorn exited with status $GUNICORN_STATUS, stopping proxy"
        kill -TERM "$WEBSOCKET_PID" 2>/dev/null
        wait "$WEBSOCKET_PID" 2>/dev/null
        exit "$GUNICORN_STATUS"
    fi

    # The proxy dying silently is the failure this supervisor exists to catch.
    if ! kill -0 "$WEBSOCKET_PID" 2>/dev/null; then
        wait "$WEBSOCKET_PID" 2>/dev/null
        WS_RESTARTS=$((WS_RESTARTS + 1))
        if [ "$WS_RESTARTS" -gt "$WS_MAX_RESTARTS" ]; then
            echo "[OpenAlgo] WebSocket proxy failed $WS_RESTARTS times, giving up" >&2
            kill -TERM "$GUNICORN_PID" 2>/dev/null
            wait "$GUNICORN_PID" 2>/dev/null
            exit 1
        fi
        echo "[OpenAlgo] WebSocket proxy died, restarting ($WS_RESTARTS/$WS_MAX_RESTARTS)..." >&2
        /app/.venv/bin/python -m websocket_proxy.server &
        WEBSOCKET_PID=$!
        echo "[OpenAlgo] WebSocket proxy restarted with PID $WEBSOCKET_PID"
    fi
done
