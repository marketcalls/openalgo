#!/bin/bash
echo "[OpenAlgo] Starting up..."

# ============================================
# RAILWAY/CLOUD ENVIRONMENT DETECTION & .env GENERATION
# ============================================

# Determine writable .env location
ENV_FILE="/app/.env"

GENERATED_MARK="# Auto-generated from environment variables"

# Keys the platform's variables supply; those are never copied to KEYS_FILE
PLATFORM_KEYS=" "
for key_name in APP_KEY API_KEY_PEPPER FERNET_SALT; do
    if [ -n "$(printenv "$key_name")" ]; then
        PLATFORM_KEYS="$PLATFORM_KEYS$key_name "
    fi
done

# The main database file, from DATABASE_URL when it is SQLite:
# sqlite:///db/x.db is relative to /app, sqlite:////data/x.db is absolute.
# Empty for any other database (Postgres and so on), which cannot be checked here.
DB_URL="${DATABASE_URL:-sqlite:///db/openalgo.db}"
case "$DB_URL" in
    sqlite:////*) SQLITE_DB="/${DB_URL#sqlite:////}" ;;
    sqlite:///*) SQLITE_DB="/app/${DB_URL#sqlite:///}" ;;
    *) SQLITE_DB="" ;;
esac

# Security keys this script generated, or copied from a .env it generated, are
# kept beside the database, so a redeploy finds them again on whichever volume
# holds it: /app/db by default, or the folder a SQLite DATABASE_URL names.
if [ -n "$SQLITE_DB" ]; then
    KEYS_DIR=$(dirname "$SQLITE_DB")
else
    KEYS_DIR="/app/db"
fi
KEYS_FILE="$KEYS_DIR/.openalgo-keys"

# True when a database already exists: the SQLite file named by DATABASE_URL,
# or any db/*.db in /app/db
has_database() {
    local db_file
    [ -n "$SQLITE_DB" ] && [ -f "$SQLITE_DB" ] && return 0
    for db_file in /app/db/*.db; do
        [ -f "$db_file" ] && return 0
    done
    return 1
}

# Copy APP_KEY, API_KEY_PEPPER and FERNET_SALT from a .env this script
# generated into KEYS_FILE. A key already saved there is never replaced; a
# different value is reported and left alone.
save_generated_keys() {
    local env_file=$1 key_name value saved
    [ -f "$env_file" ] && grep -qF "$GENERATED_MARK" "$env_file" || return 0
    [ -f "$KEYS_FILE" ] || has_database || return 0
    for key_name in APP_KEY API_KEY_PEPPER FERNET_SALT; do
        case "$PLATFORM_KEYS" in *" $key_name "*) continue ;; esac
        value=$(sed -n "s/^${key_name} *= *'\([0-9a-fA-F]\{32,\}\)'.*/\1/p" "$env_file" | head -n 1)
        [ -n "$value" ] || continue
        saved=""
        if [ -f "$KEYS_FILE" ]; then
            saved=$(sed -n "s/^${key_name}=//p" "$KEYS_FILE" | head -n 1)
        fi
        if [ -z "$saved" ]; then
            if ( umask 077 && printf '%s=%s\n' "$key_name" "$value" >> "$KEYS_FILE" ) 2>/dev/null; then
                echo "[OpenAlgo] Kept a copy of $key_name in $KEYS_FILE, so the next redeploy finds it."
            else
                echo "[OpenAlgo] Could not keep a copy of $key_name in $KEYS_DIR. Set $key_name in the platform's"
                echo "[OpenAlgo] variables (its value is in /app/.env in this container), or the next redeploy"
                echo "[OpenAlgo] cannot read your saved passwords and broker keys."
            fi
        elif [ "$saved" != "$value" ]; then
            echo "[OpenAlgo] Warning: $key_name in /app/.env differs from the copy in $KEYS_FILE; the copy was left as it is."
        fi
    done
    return 0
}

# A host .env that did not exist when the container started arrives as a
# folder: Docker creates a missing bind-mount source as a directory. Nothing
# can start from that, so say what happened and how to put it right.
if [ -d "$ENV_FILE" ]; then
    echo "============================================"
    echo "Error: the OpenAlgo settings file (.env) is a folder, not a file."
    echo "The .env file did not exist on this computer when the container"
    echo "started, so Docker created an empty folder named .env in its place."
    echo ""
    echo "Solution: stop the container, delete that empty .env folder next to"
    echo "docker-compose.yaml, then run the OpenAlgo install script (or"
    echo "./docker-build.sh) again. It creates the .env file with new security keys."
    echo "============================================"
    exit 1
fi

# Check if .env exists, is readable, and has content (not empty)
if [ -f "$ENV_FILE" ] && [ -r "$ENV_FILE" ] && [ -s "$ENV_FILE" ]; then
    echo "[OpenAlgo] Using existing .env file"
    # A .env this script generated lives only as long as this container; keep
    # its keys (including a salt the app added) for the next redeploy.
    save_generated_keys "$ENV_FILE"
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

        # The configuration version this image ships, so the generated file is
        # never older than the .sample.env it was built from.
        SAMPLE_ENV_VERSION=$(sed -n "s/^ENV_CONFIG_VERSION *= *'\([^']*\)'.*/\1/p" /app/.sample.env 2>/dev/null | head -n 1)

        # Security keys. A value set in the platform's variables always wins.
        # Otherwise the keys an earlier start generated are reused from
        # KEYS_DIR, so they survive a redeploy whenever that folder is a persistent
        # volume. API_KEY_PEPPER and FERNET_SALT are generated only for a new
        # install (default database, not created yet): a new pepper or salt
        # would make every saved password and broker key unreadable. APP_KEY
        # only signs browser sessions, so a new one is always safe.
        # A new install: SQLite (so it can be checked) and no database yet
        NEW_INSTALL=0
        if [ -n "$SQLITE_DB" ] && ! has_database; then
            NEW_INSTALL=1
        fi
        resolve_key() {
            local name=$1 bytes=$2 value=$3
            if [ -z "$value" ] && [ -f "$KEYS_FILE" ]; then
                value=$(sed -n "s/^${name}=//p" "$KEYS_FILE" | head -n 1)
            fi
            if [ -z "$value" ] && { [ "$name" = "APP_KEY" ] || [ "$NEW_INSTALL" -eq 1 ]; }; then
                value=$(/app/.venv/bin/python -c "import secrets; print(secrets.token_hex($bytes))" 2>/dev/null)
                if [ -n "$value" ]; then
                    if ( umask 077 && printf '%s=%s\n' "$name" "$value" >> "$KEYS_FILE" ) 2>/dev/null; then
                        echo "[OpenAlgo] Generated a new $name and kept a copy in $KEYS_FILE" >&2
                    else
                        echo "[OpenAlgo] Generated a new $name, but could not keep a copy in $KEYS_DIR." >&2
                        echo "[OpenAlgo] Set $name in the platform's variables, or it changes on the next deploy." >&2
                    fi
                fi
            fi
            printf '%s' "$value"
        }
        APP_KEY=$(resolve_key APP_KEY 32 "$APP_KEY")
        API_KEY_PEPPER=$(resolve_key API_KEY_PEPPER 32 "$API_KEY_PEPPER")
        FERNET_SALT=$(resolve_key FERNET_SALT 16 "$FERNET_SALT")

        # An existing database without its keys cannot be read. Say exactly
        # which variables to set rather than start with keys that do not fit.
        # Values are never printed: logs are not the place for them.
        if [ -z "$API_KEY_PEPPER" ] && [ -z "$SQLITE_DB" ]; then
            # DATABASE_URL is not SQLite: whether it already holds data cannot
            # be checked from here, so no keys are made up for it
            echo "============================================"
            echo "Error: DATABASE_URL points to a database OpenAlgo cannot check from"
            echo "here, so it does not create security keys for it."
            echo ""
            echo "Set these variables in your platform (for example Railway > Variables),"
            echo "then redeploy:"
            echo "  APP_KEY"
            echo "  API_KEY_PEPPER"
            echo "  FERNET_SALT"
            echo "For a new database use new random values, for example from:"
            echo "  python3 -c \"import secrets; print(secrets.token_hex(32))\""
            echo "For a database that already has data, use the values it was created with."
            echo "============================================"
            exit 1
        fi
        if [ -z "$API_KEY_PEPPER" ]; then
            echo "============================================"
            echo "Error: this deployment already has a database, but its security keys"
            echo "are not available: they are not in the platform's variables and no"
            echo "copy was kept in $KEYS_DIR."
            echo ""
            echo "Set these variables in your platform (for example Railway > Variables)"
            echo "to the values this deployment used before, then redeploy:"
            echo "  APP_KEY"
            echo "  API_KEY_PEPPER"
            echo "  FERNET_SALT"
            echo "They are in the earlier container's /app/.env, or in your backup of it."
            echo "New keys would make the saved passwords and broker keys unreadable, so"
            echo "OpenAlgo does not start without them."
            echo "============================================"
            exit 1
        fi
        if [ -z "$FERNET_SALT" ]; then
            echo "[OpenAlgo] FERNET_SALT is not in the platform's variables and no copy was kept in $KEYS_DIR."
            echo "[OpenAlgo] If OpenAlgo stops with a message about FERNET_SALT, set it to the value this"
            echo "[OpenAlgo] deployment used before. If OpenAlgo creates one now, a copy is kept for the next redeploy."
        fi
        # No salt known for an existing database: leave the line out so the
        # app's own check decides (it refuses to start rather than guess).
        FERNET_SALT_LINE=""
        if [ -n "$FERNET_SALT" ]; then
            FERNET_SALT_LINE="FERNET_SALT = '$FERNET_SALT'"
        fi

        cat > "$ENV_FILE" << EOF
# OpenAlgo Environment Configuration File
# Auto-generated from environment variables
ENV_CONFIG_VERSION = '${ENV_CONFIG_VERSION:-${SAMPLE_ENV_VERSION:-1.0.7}}'

# Broker Configuration
BROKER_API_KEY = '${BROKER_API_KEY}'
BROKER_API_SECRET = '${BROKER_API_SECRET}'

# Market Data Configuration (XTS Brokers only)
BROKER_API_KEY_MARKET = '${BROKER_API_KEY_MARKET:-}'
BROKER_API_SECRET_MARKET = '${BROKER_API_SECRET_MARKET:-}'

# Redirect URL
REDIRECT_URL = '${REDIRECT_URL}'

# Valid Brokers Configuration
VALID_BROKERS = '${VALID_BROKERS:-fivepaisa,fivepaisaxts,aliceblue,angel,arrow,compositedge,definedge,deltaexchange,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,hdfcsecurities,hdfcsky,ibulls,iifl,iiflcapital,indmoney,jainamxts,kotak,motilal,mstock,nubra,paytm,pocketful,rmoney,rupeezy,sahi,samco,shoonya,tradejini,tradesmart,upstox,wisdom,zebu,zerodha}'

# Security Configuration
APP_KEY = '${APP_KEY}'
API_KEY_PEPPER = '${API_KEY_PEPPER}'
${FERNET_SALT_LINE}

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
        echo "For cloud deployment (Railway/Render), set this environment variable:"
        echo "  - HOST_SERVER (your app domain, e.g., https://your-app.up.railway.app)"
        echo ""
        echo "APP_KEY, API_KEY_PEPPER and FERNET_SALT are created on the first start"
        echo "and kept in $KEYS_DIR. Attach a persistent volume at $KEYS_DIR, or set all"
        echo "three as environment variables, so a redeploy keeps your data readable."
        echo "No broker is needed here: sign in to OpenAlgo and add your broker keys"
        echo "in Broker Configuration."
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
# KEEP A SALT THE APP ADDS
# ============================================
# On its first start against an older database the app writes a FERNET_SALT
# into a generated .env, which dies with this container. Watch for it for ten
# minutes and keep a copy in KEYS_DIR, so the next redeploy can still read the
# saved passwords and broker keys.
if [ -f /app/.env ] && grep -qF "$GENERATED_MARK" /app/.env 2>/dev/null \
    && ! grep -q '^FERNET_SALT=' "$KEYS_FILE" 2>/dev/null \
    && { [ -f "$KEYS_FILE" ] || has_database; }; then
    (
        for _ in $(seq 1 60); do
            if grep -qE "^FERNET_SALT *= *'[0-9a-fA-F]{32,}'" /app/.env 2>/dev/null; then
                save_generated_keys /app/.env
                break
            fi
            sleep 10
        done
    ) &
fi

# ============================================
# DATABASE MIGRATIONS
# ============================================
# Run migrations automatically on startup (idempotent - safe to run multiple times)
if [ -f "/app/upgrade/migrate_all.py" ]; then
    echo "[OpenAlgo] Running database migrations..."
    if ! /app/.venv/bin/python /app/upgrade/migrate_all.py; then
        echo "[OpenAlgo] Database migrations failed; startup aborted."
        exit 1
    fi
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

# Web server: eventlet, exactly as below, unless .env (or the container
# environment) sets OPENALGO_WORKER_CLASS = 'gthread'. Only then does the
# container start through the launcher. See docs/gthread/README.md.
OPENALGO_WORKER_REQUESTED="default"
if [ -f /app/install/lib/resolve_runtime.py ]; then
    OPENALGO_WORKER_REQUESTED="$(/app/.venv/bin/python /app/install/lib/resolve_runtime.py --env-file "$ENV_FILE" --print requested)" \
        || OPENALGO_WORKER_REQUESTED="default"
fi
if [ "$OPENALGO_WORKER_REQUESTED" = "gthread" ] && [ -f /app/install/openalgo-gunicorn.sh ]; then
    echo "[OpenAlgo] Starting application on port ${APP_PORT} with gthread..."
    mkdir -p /tmp/gunicorn_workers
    # This shell stays in front of the web server instead of handing over to
    # it, to look after the WebSocket proxy started above. With --proxy-mode
    # external the web server never starts one itself, so if the proxy dies
    # nothing else brings it back and live market data stops until the
    # container is restarted. Here it is started again after a pause that
    # doubles on each quick failure (1 second up to 30), and only once the
    # previous one has exited, so two never run at once. A stop signal is
    # passed on to the web server; once it has finished, the proxy is stopped
    # too (5 seconds, then forced) and the container exits with the web
    # server's status. No proxy is started again after a stop begins.
    GTHREAD_STOPPING=0
    GTHREAD_SIGNAL=TERM
    GUNICORN_PID=""
    gthread_forward() {
        GTHREAD_STOPPING=1
        GTHREAD_SIGNAL="$1"
        if [ -n "$GUNICORN_PID" ]; then
            kill -s "$1" "$GUNICORN_PID" 2>/dev/null
        fi
    }
    trap 'gthread_forward TERM' TERM
    trap 'gthread_forward INT' INT

    # A stop gets 30 seconds for open requests, beside the strategies and
    # OpenScript runs stopping. Docker kills a container 10 seconds after the
    # stop signal unless docker-compose.yaml sets stop_grace_period, so the
    # gthread switch steps require stop_grace_period: 45s. See
    # docs/gthread/README.md.
    /bin/bash /app/install/openalgo-gunicorn.sh \
        --app-dir /app \
        --venv /app/.venv \
        --env-file "$ENV_FILE" \
        --bind "0.0.0.0:${APP_PORT}" \
        --proxy-mode external \
        --timeout 300 \
        --graceful-timeout 30 \
        --worker-tmp-dir /tmp/gunicorn_workers \
        --log-level warning &
    GUNICORN_PID=$!
    # A stop that arrived while it was being started is passed on now.
    if [ "$GTHREAD_STOPPING" -ne 0 ]; then
        kill -s "$GTHREAD_SIGNAL" "$GUNICORN_PID" 2>/dev/null
    fi

    # Sleep in the background and wait for it, so a stop signal is handled at
    # once rather than after the sleep.
    gthread_pause() {
        sleep "$1" &
        local pause_pid=$!
        if ! wait "$pause_pid" 2>/dev/null; then
            kill "$pause_pid" 2>/dev/null
            wait "$pause_pid" 2>/dev/null
        fi
    }

    PROXY_BACKOFF=1
    PROXY_STARTED_AT=$(date +%s)
    while kill -0 "$GUNICORN_PID" 2>/dev/null; do
        if [ "$GTHREAD_STOPPING" -eq 0 ] && [ -n "${WEBSOCKET_PID:-}" ] \
            && ! kill -0 "$WEBSOCKET_PID" 2>/dev/null; then
            wait "$WEBSOCKET_PID" 2>/dev/null
            PROXY_STATUS=$?
            # A proxy that ran for a minute was not failing quickly.
            if [ $(( $(date +%s) - PROXY_STARTED_AT )) -ge 60 ]; then
                PROXY_BACKOFF=1
            fi
            echo "[OpenAlgo] The WebSocket proxy server stopped (exit status $PROXY_STATUS). Live market data is paused; starting it again in $PROXY_BACKOFF seconds."
            gthread_pause "$PROXY_BACKOFF"
            if [ "$GTHREAD_STOPPING" -ne 0 ] || ! kill -0 "$GUNICORN_PID" 2>/dev/null; then
                break
            fi
            /app/.venv/bin/python -m websocket_proxy.server &
            WEBSOCKET_PID=$!
            PROXY_STARTED_AT=$(date +%s)
            echo "[OpenAlgo] WebSocket proxy server started again with PID $WEBSOCKET_PID"
            PROXY_BACKOFF=$(( PROXY_BACKOFF * 2 ))
            if [ "$PROXY_BACKOFF" -gt 30 ]; then
                PROXY_BACKOFF=30
            fi
        fi
        gthread_pause 1
    done

    # The web server has exited: collect its status, then stop the proxy.
    wait "$GUNICORN_PID" 2>/dev/null
    GUNICORN_STATUS=$?
    while kill -0 "$GUNICORN_PID" 2>/dev/null; do
        # wait was cut short by a second stop signal; the web server is still
        # finishing, so keep waiting for it.
        wait "$GUNICORN_PID" 2>/dev/null
        GUNICORN_STATUS=$?
    done
    if [ -n "${WEBSOCKET_PID:-}" ] && kill -0 "$WEBSOCKET_PID" 2>/dev/null; then
        echo "[OpenAlgo] Stopping the WebSocket proxy server..."
        kill -TERM "$WEBSOCKET_PID" 2>/dev/null
        for _ in 1 2 3 4 5 6 7 8 9 10; do
            kill -0 "$WEBSOCKET_PID" 2>/dev/null || break
            gthread_pause 0.5
        done
        kill -KILL "$WEBSOCKET_PID" 2>/dev/null
        wait "$WEBSOCKET_PID" 2>/dev/null
    fi
    exit "$GUNICORN_STATUS"
fi

echo "[OpenAlgo] Starting application on port ${APP_PORT} with eventlet..."

# Create gunicorn worker temp directory (must be inside container, not mounted volume)
mkdir -p /tmp/gunicorn_workers

exec /app/.venv/bin/gunicorn \
    --worker-class eventlet \
    --workers 1 \
    --bind 0.0.0.0:${APP_PORT} \
    --timeout 300 \
    --graceful-timeout 30 \
    --worker-tmp-dir /tmp/gunicorn_workers \
    --no-control-socket \
    --log-level warning \
    app:app
