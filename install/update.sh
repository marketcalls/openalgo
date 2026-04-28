#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# OpenAlgo Update Banner
echo -e "${BLUE}"
echo "  ██████╗ ██████╗ ███████╗███╗   ██╗ █████╗ ██╗      ██████╗  ██████╗ "
echo " ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║     ██╔════╝ ██╔═══██╗"
echo " ██║   ██║██████╔╝███████╗██╔██╗ ██║███████║██║     ██║  ███╗██║   ██║"
echo " ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██║██║     ██║   ██║██║   ██║"
echo " ╚██████╔╝██╗     ███████╗██║ ╚████║██║  ██║███████╗╚██████╔╝╚██████╔╝"
echo "  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝ "
echo "                          UPDATE  SCRIPT                                "
echo -e "${NC}"

# OpenAlgo Update Script
# Updates an existing OpenAlgo installation to the latest version using the UV method.
# Supports both server deployments (installed via install.sh) and local development setups.

# Create logs directory if it doesn't exist
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOGS_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOGS_DIR"

# Generate unique log file name
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOGS_DIR/update_${TIMESTAMP}.log"

# Function to log messages to both console and log file
log_message() {
    local message="$1"
    local color="$2"
    echo -e "${color}${message}${NC}" | tee -a "$LOG_FILE"
}

# Function to check if command was successful
check_status() {
    if [ $? -ne 0 ]; then
        log_message "Error: $1" "$RED"
        exit 1
    fi
}

# Start logging
log_message "Starting OpenAlgo update log at: $LOG_FILE" "$BLUE"
log_message "----------------------------------------" "$BLUE"

# Detect OS type
OS_TYPE=$(grep -w "ID" /etc/os-release | cut -d "=" -f 2 | tr -d '"')

# Handle OS variants - map to base distributions
case "$OS_TYPE" in
    "pop"|"linuxmint"|"zorin")
        OS_TYPE="ubuntu"
        ;;
    "manjaro"|"manjaro-arm"|"endeavouros"|"cachyos")
        OS_TYPE="arch"
        ;;
    "rocky"|"almalinux"|"ol")
        OS_TYPE="rhel"
        ;;
esac

# Detect web server user and Python command based on OS
case "$OS_TYPE" in
    ubuntu|debian|raspbian)
        WEB_USER="www-data"
        WEB_GROUP="www-data"
        PYTHON_CMD="python3"
        ;;
    centos|fedora|rhel|amzn)
        WEB_USER="nginx"
        WEB_GROUP="nginx"
        PYTHON_CMD="python3"
        ;;
    arch)
        WEB_USER="http"
        WEB_GROUP="http"
        PYTHON_CMD="python"
        ;;
    *)
        log_message "Warning: Unrecognized OS ($OS_TYPE). Defaulting to python3." "$YELLOW"
        WEB_USER="www-data"
        WEB_GROUP="www-data"
        PYTHON_CMD="python3"
        ;;
esac

log_message "Detected OS: $OS_TYPE" "$BLUE"
log_message "Python command: $PYTHON_CMD" "$BLUE"

# Detect uv command
detect_uv() {
    if command -v uv >/dev/null 2>&1; then
        UV_CMD="uv"
    elif $PYTHON_CMD -m uv --version >/dev/null 2>&1; then
        UV_CMD="$PYTHON_CMD -m uv"
    else
        log_message "Error: uv is not installed." "$RED"
        log_message "Install with: pip install uv" "$YELLOW"
        exit 1
    fi
    log_message "Using uv: $UV_CMD" "$GREEN"
}

# Find server deployments installed via install.sh
DEPLOY_BASE="/var/python/openalgo-flask"
SERVER_MODE=false
STASHED=false

find_deployments() {
    local deployments=()
    if [ -d "$DEPLOY_BASE" ]; then
        for dir in "$DEPLOY_BASE"/*/; do
            if [ -d "${dir}openalgo/.git" ]; then
                deploy_name=$(basename "$dir")
                deployments+=("$deploy_name")
            fi
        done
    fi
    echo "${deployments[@]}"
}

# Check for server deployments
DEPLOYMENTS=($(find_deployments))

if [ ${#DEPLOYMENTS[@]} -gt 0 ]; then
    SERVER_MODE=true
    log_message "Found ${#DEPLOYMENTS[@]} server deployment(s):" "$GREEN"

    for i in "${!DEPLOYMENTS[@]}"; do
        log_message "  $((i+1)). ${DEPLOYMENTS[$i]}" "$BLUE"
    done

    if [ ${#DEPLOYMENTS[@]} -eq 1 ]; then
        SELECTED_DEPLOY="${DEPLOYMENTS[0]}"
        log_message "\nAuto-selected: $SELECTED_DEPLOY" "$GREEN"
    else
        echo ""
        while true; do
            read -p "Select deployment to update (1-${#DEPLOYMENTS[@]}): " choice
            if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#DEPLOYMENTS[@]} ]; then
                SELECTED_DEPLOY="${DEPLOYMENTS[$((choice-1))]}"
                break
            else
                log_message "Invalid choice. Please enter a number between 1 and ${#DEPLOYMENTS[@]}." "$RED"
            fi
        done
    fi

    # Derive paths from deployment name
    BASE_PATH="$DEPLOY_BASE/$SELECTED_DEPLOY"
    OPENALGO_PATH="$BASE_PATH/openalgo"
    VENV_PATH="$BASE_PATH/venv"
    SERVICE_NAME="openalgo-$SELECTED_DEPLOY"

    log_message "\nUpdating deployment: $SELECTED_DEPLOY" "$BLUE"
    log_message "Path: $OPENALGO_PATH" "$BLUE"
    log_message "Service: $SERVICE_NAME" "$BLUE"
else
    # Check if we're in or near an openalgo git repo (local development)
    if [ -d ".git" ] && [ -f "app.py" ]; then
        OPENALGO_PATH="$(pwd)"
    elif [ -d "$SCRIPT_DIR/../.git" ] && [ -f "$SCRIPT_DIR/../app.py" ]; then
        OPENALGO_PATH="$(cd "$SCRIPT_DIR/.." && pwd)"
    else
        log_message "Error: No OpenAlgo deployment found." "$RED"
        log_message "For server deployments, ensure install.sh was run first." "$YELLOW"
        log_message "For local development, run this script from the openalgo directory." "$YELLOW"
        exit 1
    fi

    log_message "Detected local development setup at: $OPENALGO_PATH" "$GREEN"
fi

# Detect uv
detect_uv

# Get current version info before update
cd "$OPENALGO_PATH"
if [ "$SERVER_MODE" = true ]; then
    CURRENT_COMMIT=$(sudo git -C "$OPENALGO_PATH" rev-parse --short HEAD 2>/dev/null || echo "unknown")
    CURRENT_BRANCH=$(sudo git -C "$OPENALGO_PATH" branch --show-current 2>/dev/null || echo "main")
else
    CURRENT_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    CURRENT_BRANCH=$(git branch --show-current 2>/dev/null || echo "main")
fi
log_message "\nCurrent version: $CURRENT_COMMIT (branch: $CURRENT_BRANCH)" "$BLUE"

# ============================================
# Step 1: Stop service (server mode only)
# ============================================
if [ "$SERVER_MODE" = true ]; then
    log_message "\n[Step 1/7] Stopping service: $SERVICE_NAME..." "$BLUE"
    if sudo systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        sudo systemctl stop "$SERVICE_NAME"
        check_status "Failed to stop $SERVICE_NAME"
        log_message "Service stopped successfully" "$GREEN"
    else
        log_message "Service is not currently running" "$YELLOW"
    fi
else
    log_message "\n[Step 1/7] Skipping service stop (local development mode)" "$BLUE"
fi

# ============================================
# Step 2: Backup databases
# ============================================
log_message "\n[Step 2/7] Backing up databases..." "$BLUE"
BACKUP_DIR="$OPENALGO_PATH/db/backup_${TIMESTAMP}"
BACKUP_COUNT=0

if [ -d "$OPENALGO_PATH/db" ]; then
    if [ "$SERVER_MODE" = true ]; then
        sudo mkdir -p "$BACKUP_DIR"
    else
        mkdir -p "$BACKUP_DIR"
    fi

    # Backup SQLite databases
    for db_file in openalgo.db logs.db latency.db sandbox.db; do
        if [ -f "$OPENALGO_PATH/db/$db_file" ]; then
            if [ "$SERVER_MODE" = true ]; then
                sudo cp "$OPENALGO_PATH/db/$db_file" "$BACKUP_DIR/$db_file"
            else
                cp "$OPENALGO_PATH/db/$db_file" "$BACKUP_DIR/$db_file"
            fi
            log_message "  Backed up: $db_file" "$GREEN"
            BACKUP_COUNT=$((BACKUP_COUNT + 1))
        fi
    done

    # Backup DuckDB database
    if [ -f "$OPENALGO_PATH/db/historify.duckdb" ]; then
        if [ "$SERVER_MODE" = true ]; then
            sudo cp "$OPENALGO_PATH/db/historify.duckdb" "$BACKUP_DIR/historify.duckdb"
        else
            cp "$OPENALGO_PATH/db/historify.duckdb" "$BACKUP_DIR/historify.duckdb"
        fi
        log_message "  Backed up: historify.duckdb" "$GREEN"
        BACKUP_COUNT=$((BACKUP_COUNT + 1))
    fi

    if [ $BACKUP_COUNT -eq 0 ]; then
        log_message "  No databases found to backup (fresh installation)" "$YELLOW"
        if [ "$SERVER_MODE" = true ]; then
            sudo rmdir "$BACKUP_DIR" 2>/dev/null
        else
            rmdir "$BACKUP_DIR" 2>/dev/null
        fi
    else
        log_message "  Backup location: $BACKUP_DIR ($BACKUP_COUNT files)" "$GREEN"
    fi
else
    log_message "  No database directory found (fresh installation)" "$YELLOW"
fi

# ============================================
# Step 3: Pull latest code
# ============================================
log_message "\n[Step 3/7] Pulling latest code from repository..." "$BLUE"
cd "$OPENALGO_PATH"

# Check for local modifications (excluding untracked files)
if [ "$SERVER_MODE" = true ]; then
    LOCAL_CHANGES=$(sudo git -C "$OPENALGO_PATH" status --porcelain 2>/dev/null | grep -v "^??" | head -20)
else
    LOCAL_CHANGES=$(git status --porcelain 2>/dev/null | grep -v "^??" | head -20)
fi

if [ -n "$LOCAL_CHANGES" ]; then
    log_message "Local modifications detected:" "$YELLOW"
    echo "$LOCAL_CHANGES" | tee -a "$LOG_FILE"
    log_message "\nStashing local changes..." "$YELLOW"
    if [ "$SERVER_MODE" = true ]; then
        sudo git -C "$OPENALGO_PATH" stash push -m "auto-stash before update $TIMESTAMP"
    else
        git stash push -m "auto-stash before update $TIMESTAMP"
    fi
    STASHED=true
fi

# Pull latest code
if [ "$SERVER_MODE" = true ]; then
    sudo git -C "$OPENALGO_PATH" pull origin "$CURRENT_BRANCH"
else
    git pull origin "$CURRENT_BRANCH"
fi
check_status "Failed to pull latest code. Please resolve any conflicts and try again"

# Get new commit hash
if [ "$SERVER_MODE" = true ]; then
    NEW_COMMIT=$(sudo git -C "$OPENALGO_PATH" rev-parse --short HEAD 2>/dev/null || echo "unknown")
else
    NEW_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
fi

if [ "$CURRENT_COMMIT" = "$NEW_COMMIT" ]; then
    log_message "Already up to date ($CURRENT_COMMIT)" "$GREEN"
else
    log_message "Updated: $CURRENT_COMMIT -> $NEW_COMMIT" "$GREEN"
fi

if [ "$STASHED" = true ]; then
    log_message "Note: Local changes were stashed. Use 'git stash pop' to restore if needed." "$YELLOW"
fi

# ============================================
# Step 4: Check environment configuration
# ============================================
log_message "\n[Step 4/7] Checking environment configuration..." "$BLUE"

if [ -f "$OPENALGO_PATH/.env" ] && [ -f "$OPENALGO_PATH/.sample.env" ]; then
    # Extract variable names from both files and compare
    SAMPLE_VARS=$(grep -oP "^[A-Z_][A-Z_0-9]+ *=" "$OPENALGO_PATH/.sample.env" 2>/dev/null | sed 's/ *=$//' | sort -u)
    CURRENT_VARS=$(grep -oP "^[A-Z_][A-Z_0-9]+ *=" "$OPENALGO_PATH/.env" 2>/dev/null | sed 's/ *=$//' | sort -u)

    NEW_VARS=$(comm -23 <(echo "$SAMPLE_VARS") <(echo "$CURRENT_VARS") 2>/dev/null)

    if [ -n "$NEW_VARS" ]; then
        log_message "New environment variables found in .sample.env:" "$YELLOW"
        while IFS= read -r var; do
            [ -n "$var" ] && log_message "  + $var" "$YELLOW"
        done <<< "$NEW_VARS"
        log_message "Please review .sample.env and add these to your .env if needed." "$YELLOW"
    else
        log_message "Environment configuration is up to date" "$GREEN"
    fi
elif [ ! -f "$OPENALGO_PATH/.env" ]; then
    log_message "Warning: No .env file found. Creating from .sample.env..." "$YELLOW"
    if [ "$SERVER_MODE" = true ]; then
        sudo cp "$OPENALGO_PATH/.sample.env" "$OPENALGO_PATH/.env"
    else
        cp "$OPENALGO_PATH/.sample.env" "$OPENALGO_PATH/.env"
    fi

    # Generate fresh APP_KEY and API_KEY_PEPPER and substitute the placeholders.
    # Without this, the new .env would carry the public sample placeholder values
    # — the app's startup check would then auto-rotate them, which works, but
    # generating here keeps update.sh symmetric with install.sh and avoids the
    # noisy "first-run setup" message after what the user thinks is just an update.
    NEW_APP_KEY=$($PYTHON_CMD -c "import secrets; print(secrets.token_hex(32))")
    NEW_PEPPER=$($PYTHON_CMD -c "import secrets; print(secrets.token_hex(32))")
    if [ "$SERVER_MODE" = true ]; then
        sudo sed -i "s|OPENALGO_PLACEHOLDER_APP_KEY_REGENERATE_BEFORE_USE|$NEW_APP_KEY|g" "$OPENALGO_PATH/.env"
        sudo sed -i "s|OPENALGO_PLACEHOLDER_API_KEY_PEPPER_REGENERATE_BEFORE_USE|$NEW_PEPPER|g" "$OPENALGO_PATH/.env"
        sudo chmod 600 "$OPENALGO_PATH/.env"
    else
        sed -i.bak "s|OPENALGO_PLACEHOLDER_APP_KEY_REGENERATE_BEFORE_USE|$NEW_APP_KEY|g" "$OPENALGO_PATH/.env" && rm -f "$OPENALGO_PATH/.env.bak"
        sed -i.bak "s|OPENALGO_PLACEHOLDER_API_KEY_PEPPER_REGENERATE_BEFORE_USE|$NEW_PEPPER|g" "$OPENALGO_PATH/.env" && rm -f "$OPENALGO_PATH/.env.bak"
        chmod 600 "$OPENALGO_PATH/.env"
    fi
    log_message "Generated fresh APP_KEY and API_KEY_PEPPER in $OPENALGO_PATH/.env" "$GREEN"
    log_message "Please edit $OPENALGO_PATH/.env with your broker credentials and settings." "$RED"
fi

# ============================================
# Step 4b: Existing-install hardening
# ============================================
# Two one-time fixups for deployments that predate the v2.0.0.6 security
# release: they may carry world-readable .env perms (the old install.sh did
# `chmod -R 755`) and they don't have TRUST_PROXY_HEADERS set so the
# default-secure value of FALSE would silently disable IP-based features
# behind their nginx proxy.
if [ -f "$OPENALGO_PATH/.env" ]; then
    # Tighten .env to mode 0o600 if it isn't already (server mode only —
    # the file is owned by the web user and gunicorn runs as that user, so
    # owner-only read is correct).
    if [ "$SERVER_MODE" = true ]; then
        ENV_PERMS=$(stat -c '%a' "$OPENALGO_PATH/.env" 2>/dev/null || stat -f '%Lp' "$OPENALGO_PATH/.env" 2>/dev/null)
        if [ "$ENV_PERMS" != "600" ]; then
            sudo chmod 600 "$OPENALGO_PATH/.env"
            log_message "Tightened .env perms: $ENV_PERMS -> 600 (owner-only)" "$GREEN"
        fi
    fi

    # Add TRUST_PROXY_HEADERS to .env if missing. Auto-detect whether nginx
    # is configured for this deployment so the default matches reality.
    if ! grep -q "^TRUST_PROXY_HEADERS" "$OPENALGO_PATH/.env"; then
        # Detect nginx in front of openalgo: any sites-enabled/ or conf.d/
        # config that mentions a unix-socket proxy_pass or the deployment name.
        BEHIND_NGINX="false"
        if [ -d /etc/nginx/sites-enabled ]; then
            if find /etc/nginx/sites-enabled -type f -o -type l 2>/dev/null | xargs grep -l "unix:.*\.sock\|openalgo\|gunicorn" 2>/dev/null | head -1 | grep -q .; then
                BEHIND_NGINX="true"
            fi
        fi
        if [ "$BEHIND_NGINX" = "false" ] && [ -d /etc/nginx/conf.d ]; then
            if find /etc/nginx/conf.d -type f -name "*.conf" 2>/dev/null | xargs grep -l "unix:.*\.sock\|openalgo\|gunicorn" 2>/dev/null | head -1 | grep -q .; then
                BEHIND_NGINX="true"
            fi
        fi
        if [ "$BEHIND_NGINX" = "true" ]; then
            echo "" | sudo tee -a "$OPENALGO_PATH/.env" >/dev/null
            echo "# Auto-added by update.sh — nginx reverse proxy detected." | sudo tee -a "$OPENALGO_PATH/.env" >/dev/null
            echo "TRUST_PROXY_HEADERS = 'TRUE'" | sudo tee -a "$OPENALGO_PATH/.env" >/dev/null
            log_message "Added TRUST_PROXY_HEADERS=TRUE to .env (nginx reverse proxy detected)" "$GREEN"
        else
            echo "" | sudo tee -a "$OPENALGO_PATH/.env" >/dev/null
            echo "# Auto-added by update.sh — set to TRUE only if behind a reverse proxy" | sudo tee -a "$OPENALGO_PATH/.env" >/dev/null
            echo "# that strips client-supplied X-Forwarded-For / CF-Connecting-IP / X-Real-IP." | sudo tee -a "$OPENALGO_PATH/.env" >/dev/null
            echo "TRUST_PROXY_HEADERS = 'FALSE'" | sudo tee -a "$OPENALGO_PATH/.env" >/dev/null
            log_message "Added TRUST_PROXY_HEADERS=FALSE to .env (no proxy detected)" "$YELLOW"
        fi
    fi
fi

# ============================================
# Step 5: Update Python dependencies
# ============================================
log_message "\n[Step 5/7] Updating Python dependencies..." "$BLUE"

if [ "$SERVER_MODE" = true ]; then
    # Server mode: use uv pip install with the deployment venv
    sudo $UV_CMD pip install --python "$VENV_PATH/bin/python" -r "$OPENALGO_PATH/requirements-nginx.txt"
    check_status "Failed to update Python dependencies"

    # Ensure gunicorn and eventlet are installed
    ACTIVATE_CMD="source $VENV_PATH/bin/activate"
    if ! sudo bash -c "$ACTIVATE_CMD && pip freeze | grep -q 'gunicorn=='"; then
        log_message "  Installing gunicorn..." "$YELLOW"
        sudo $UV_CMD pip install --python "$VENV_PATH/bin/python" "gunicorn>=25.0,<26"
    fi
    if ! sudo bash -c "$ACTIVATE_CMD && pip freeze | grep -q 'eventlet=='"; then
        log_message "  Installing eventlet..." "$YELLOW"
        sudo $UV_CMD pip install --python "$VENV_PATH/bin/python" eventlet
    fi
else
    # Local mode: use uv sync (reads pyproject.toml)
    cd "$OPENALGO_PATH"
    $UV_CMD sync
    check_status "Failed to update Python dependencies"
fi

log_message "Dependencies updated successfully" "$GREEN"

# ============================================
# Step 6: Set permissions (server mode) and run database migrations
# ============================================
if [ "$SERVER_MODE" = true ]; then
    log_message "\n[Step 6/7] Setting permissions and running database migrations..." "$BLUE"

    # Fix ownership and permissions before running migrations
    sudo chown -R "$WEB_USER:$WEB_GROUP" "$BASE_PATH"
    sudo chmod -R 755 "$BASE_PATH"

    # Ensure required directories exist with correct ownership
    sudo mkdir -p "$OPENALGO_PATH/db"
    sudo mkdir -p "$OPENALGO_PATH/tmp/numba_cache"
    sudo mkdir -p "$OPENALGO_PATH/tmp/matplotlib"
    sudo mkdir -p "$OPENALGO_PATH/strategies/scripts"
    sudo mkdir -p "$OPENALGO_PATH/strategies/examples"
    sudo mkdir -p "$OPENALGO_PATH/log/strategies"
    sudo mkdir -p "$OPENALGO_PATH/keys"
    sudo chown -R "$WEB_USER:$WEB_GROUP" "$OPENALGO_PATH"
    sudo chmod 700 "$OPENALGO_PATH/keys"

    log_message "Permissions set successfully" "$GREEN"

    # Run migrations as the web user (database files are owned by web user)
    if [ -f "$OPENALGO_PATH/upgrade/migrate_all.py" ]; then
        log_message "Running database migrations..." "$BLUE"
        sudo -u "$WEB_USER" bash -c "source $VENV_PATH/bin/activate && cd $OPENALGO_PATH && python upgrade/migrate_all.py" 2>&1 | tee -a "$LOG_FILE"
        if [ ${PIPESTATUS[0]} -ne 0 ]; then
            log_message "Retrying migrations with elevated permissions..." "$YELLOW"
            sudo bash -c "source $VENV_PATH/bin/activate && cd $OPENALGO_PATH && python upgrade/migrate_all.py" 2>&1 | tee -a "$LOG_FILE"
        fi
        log_message "Database migrations completed" "$GREEN"
    else
        log_message "No migration script found (upgrade/migrate_all.py)" "$YELLOW"
    fi
else
    log_message "\n[Step 6/7] Running database migrations..." "$BLUE"
    if [ -f "$OPENALGO_PATH/upgrade/migrate_all.py" ]; then
        cd "$OPENALGO_PATH"
        $UV_CMD run upgrade/migrate_all.py 2>&1 | tee -a "$LOG_FILE"
        log_message "Database migrations completed" "$GREEN"
    else
        log_message "No migration script found (upgrade/migrate_all.py)" "$YELLOW"
    fi
fi

# ============================================
# Step 7: Restart services (server mode) or finish (local mode)
# ============================================
if [ "$SERVER_MODE" = true ]; then
    log_message "\n[Step 7/7] Restarting services..." "$BLUE"

    # Reload systemd in case service file changed
    sudo systemctl daemon-reload

    # Start the OpenAlgo service
    sudo systemctl start "$SERVICE_NAME"
    check_status "Failed to start $SERVICE_NAME"

    # Reload Nginx
    sudo systemctl reload nginx
    check_status "Failed to reload Nginx"

    log_message "Services restarted successfully" "$GREEN"

    # Verify service is running
    sleep 3
    if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
        log_message "Service $SERVICE_NAME is running" "$GREEN"
    else
        log_message "Warning: Service $SERVICE_NAME may not have started correctly" "$RED"
        log_message "Check logs with: sudo journalctl -u $SERVICE_NAME -n 50" "$YELLOW"
    fi
else
    log_message "\n[Step 7/7] Finalizing update..." "$BLUE"

    # Build frontend if dist/ directory is missing and npm is available
    if [ ! -d "$OPENALGO_PATH/frontend/dist" ]; then
        if command -v npm >/dev/null 2>&1; then
            log_message "Building React frontend (dist/ not found)..." "$BLUE"
            cd "$OPENALGO_PATH/frontend"
            npm install && npm run build
            if [ $? -eq 0 ]; then
                log_message "Frontend built successfully" "$GREEN"
            else
                log_message "Frontend build failed. Run manually: cd frontend && npm install && npm run build" "$YELLOW"
            fi
        else
            log_message "Warning: frontend/dist/ not found and Node.js is not installed." "$YELLOW"
            log_message "Install Node.js and run: cd frontend && npm install && npm run build" "$YELLOW"
        fi
    fi

    log_message "Update finalized" "$GREEN"
fi

# ============================================
# Summary
# ============================================
log_message "\n========================================" "$GREEN"
log_message "  OpenAlgo Update Summary" "$GREEN"
log_message "========================================" "$GREEN"
log_message "Version: $CURRENT_COMMIT -> $NEW_COMMIT" "$BLUE"
log_message "Branch: $CURRENT_BRANCH" "$BLUE"
log_message "Path: $OPENALGO_PATH" "$BLUE"
if [ -d "$BACKUP_DIR" ]; then
    log_message "Database Backup: $BACKUP_DIR" "$BLUE"
fi
if [ "$SERVER_MODE" = true ]; then
    log_message "Service: $SERVICE_NAME" "$BLUE"
    log_message "Mode: Server (Nginx + Gunicorn)" "$BLUE"
else
    log_message "Mode: Local Development" "$BLUE"
fi
log_message "Update Log: $LOG_FILE" "$BLUE"

if [ "$SERVER_MODE" = true ]; then
    log_message "\nUseful Commands:" "$YELLOW"
    log_message "  Check status:  sudo systemctl status $SERVICE_NAME" "$BLUE"
    log_message "  View logs:     sudo journalctl -u $SERVICE_NAME -n 50" "$BLUE"
    log_message "  Restart:       sudo systemctl restart $SERVICE_NAME" "$BLUE"
else
    log_message "\nNext Steps:" "$YELLOW"
    log_message "  Start application: uv run app.py" "$BLUE"
    log_message "  API documentation: http://127.0.0.1:5000/api/docs" "$BLUE"
fi

if [ -n "$NEW_VARS" ]; then
    log_message "\nReminder: New environment variables were found. Please review .sample.env." "$YELLOW"
fi

if [ "$STASHED" = true ]; then
    log_message "\nReminder: Local changes were stashed. Run 'git stash pop' to restore." "$YELLOW"
fi

log_message "\nUpdate completed successfully!" "$GREEN"
