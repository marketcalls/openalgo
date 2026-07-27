#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# OpenAlgo Domain Change Banner
echo -e "${BLUE}"
echo "  ██████╗ ██████╗ ███████╗███╗   ██╗ █████╗ ██╗      ██████╗  ██████╗ "
echo " ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║     ██╔════╝ ██╔═══██╗"
echo " ██║   ██║██████╔╝███████╗██╔██╗ ██║███████║██║     ██║  ███╗██║   ██║"
echo " ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██║██║     ██║   ██║██║   ██║"
echo " ╚██████╔╝██╗     ███████╗██║ ╚████║██║  ██║███████╗╚██████╔╝╚██████╔╝"
echo "  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝ "
echo "                      DOMAIN  CHANGE  SCRIPT                             "
echo -e "${NC}"

# OpenAlgo Domain Change Script
# Changes the domain for an existing OpenAlgo server deployment.
# Updates .env, Nginx config, and obtains a new SSL certificate.

# Create logs directory if it doesn't exist
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOGS_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOGS_DIR"

# Generate unique log file name
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOGS_DIR/change_domain_${TIMESTAMP}.log"

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
log_message "Starting OpenAlgo domain change log at: $LOG_FILE" "$BLUE"
log_message "----------------------------------------" "$BLUE"

# ============================================
# Step 1: Detect OS and set variables
# ============================================
OS_TYPE=$(grep -w "ID" /etc/os-release | cut -d "=" -f 2 | tr -d '"')

# Handle OS variants
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

# Set Nginx config paths based on OS
case "$OS_TYPE" in
    ubuntu|debian|raspbian)
        NGINX_AVAILABLE="/etc/nginx/sites-available"
        NGINX_ENABLED="/etc/nginx/sites-enabled"
        NGINX_CONFIG_MODE="sites"
        ;;
    centos|fedora|rhel|amzn|arch)
        NGINX_AVAILABLE="/etc/nginx/conf.d"
        NGINX_ENABLED="/etc/nginx/conf.d"
        NGINX_CONFIG_MODE="confd"
        ;;
    *)
        log_message "Warning: Unrecognized OS ($OS_TYPE). Defaulting to sites-available." "$YELLOW"
        NGINX_AVAILABLE="/etc/nginx/sites-available"
        NGINX_ENABLED="/etc/nginx/sites-enabled"
        NGINX_CONFIG_MODE="sites"
        ;;
esac

log_message "Detected OS: $OS_TYPE" "$GREEN"

# ============================================
# Step 2: Discover existing deployments
# ============================================
DEPLOY_BASE="/var/python/openalgo-flask"

if [ ! -d "$DEPLOY_BASE" ]; then
    log_message "Error: No OpenAlgo deployment directory found at $DEPLOY_BASE" "$RED"
    log_message "This script is for server deployments installed via install.sh" "$YELLOW"
    exit 1
fi

# Find all deployments
DEPLOYMENTS=()
for dir in "$DEPLOY_BASE"/*/; do
    if [ -d "${dir}openalgo" ] && [ -f "${dir}openalgo/.env" ]; then
        deploy_name=$(basename "$dir")
        DEPLOYMENTS+=("$deploy_name")
    fi
done

if [ ${#DEPLOYMENTS[@]} -eq 0 ]; then
    log_message "Error: No OpenAlgo deployments found in $DEPLOY_BASE" "$RED"
    exit 1
fi

log_message "Found ${#DEPLOYMENTS[@]} deployment(s):" "$GREEN"
for i in "${!DEPLOYMENTS[@]}"; do
    log_message "  $((i+1)). ${DEPLOYMENTS[$i]}" "$BLUE"
done

if [ ${#DEPLOYMENTS[@]} -eq 1 ]; then
    SELECTED_DEPLOY="${DEPLOYMENTS[0]}"
    log_message "\nAuto-selected: $SELECTED_DEPLOY" "$GREEN"
else
    echo ""
    while true; do
        read -p "Select deployment to change domain for (1-${#DEPLOYMENTS[@]}): " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le ${#DEPLOYMENTS[@]} ]; then
            SELECTED_DEPLOY="${DEPLOYMENTS[$((choice-1))]}"
            break
        else
            log_message "Invalid choice." "$RED"
        fi
    done
fi

# Derive paths
BASE_PATH="$DEPLOY_BASE/$SELECTED_DEPLOY"
OPENALGO_PATH="$BASE_PATH/openalgo"
SOCKET_FILE="$BASE_PATH/openalgo.sock"
SERVICE_NAME="openalgo-$SELECTED_DEPLOY"
ENV_FILE="$OPENALGO_PATH/.env"

# ============================================
# Step 3: Extract current domain from .env
# ============================================
log_message "\n--- Discovering current configuration ---" "$BLUE"

# Extract current domain from HOST_SERVER in .env
CURRENT_DOMAIN=""
if [ -f "$ENV_FILE" ]; then
    CURRENT_DOMAIN=$(sudo grep -oP "HOST_SERVER\s*=\s*'https?://\K[^']+" "$ENV_FILE" 2>/dev/null)
fi

if [ -z "$CURRENT_DOMAIN" ]; then
    log_message "Error: Could not extract current domain from $ENV_FILE" "$RED"
    log_message "Expected HOST_SERVER = 'https://yourdomain.com' in .env" "$YELLOW"
    exit 1
fi

log_message "Current domain: $CURRENT_DOMAIN" "$GREEN"

# ============================================
# Step 4: Discover all related config files
# ============================================

# Find Nginx config
NGINX_CONFIG_FILE=""
if [ -f "$NGINX_AVAILABLE/$CURRENT_DOMAIN.conf" ]; then
    NGINX_CONFIG_FILE="$NGINX_AVAILABLE/$CURRENT_DOMAIN.conf"
elif [ -f "$NGINX_AVAILABLE/$CURRENT_DOMAIN" ]; then
    NGINX_CONFIG_FILE="$NGINX_AVAILABLE/$CURRENT_DOMAIN"
fi

# Find SSL certificate
SSL_CERT_PATH=""
if [ -d "/etc/letsencrypt/live/$CURRENT_DOMAIN" ]; then
    SSL_CERT_PATH="/etc/letsencrypt/live/$CURRENT_DOMAIN"
fi

# Find systemd service
SERVICE_FILE=""
if [ -f "/etc/systemd/system/$SERVICE_NAME.service" ]; then
    SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
fi

# Extract domain-related values from .env
CURRENT_HOST_SERVER=$(sudo grep -oP "HOST_SERVER\s*=\s*'\K[^']+" "$ENV_FILE" 2>/dev/null)
CURRENT_WEBSOCKET_URL=$(sudo grep -oP "WEBSOCKET_URL\s*=\s*'\K[^']+" "$ENV_FILE" 2>/dev/null)
CURRENT_REDIRECT_URL=$(sudo grep -oP "REDIRECT_URL\s*=\s*'\K[^']+" "$ENV_FILE" 2>/dev/null)
CURRENT_CORS_ORIGINS=$(sudo grep -oP "CORS_ALLOWED_ORIGINS\s*=\s*'\K[^']+" "$ENV_FILE" 2>/dev/null)

# ============================================
# Step 5: Display discovered configuration
# ============================================
log_message "\n========================================" "$YELLOW"
log_message "  Current Deployment Configuration" "$YELLOW"
log_message "========================================" "$YELLOW"
log_message "" ""
log_message "Deployment Name:    $SELECTED_DEPLOY" "$BLUE"
log_message "Install Path:       $OPENALGO_PATH" "$BLUE"
log_message "Service Name:       $SERVICE_NAME" "$BLUE"
log_message "Socket File:        $SOCKET_FILE" "$BLUE"
log_message "" ""
log_message "--- .env Settings ---" "$YELLOW"
log_message "HOST_SERVER:        $CURRENT_HOST_SERVER" "$BLUE"
log_message "WEBSOCKET_URL:      $CURRENT_WEBSOCKET_URL" "$BLUE"
log_message "REDIRECT_URL:       $CURRENT_REDIRECT_URL" "$BLUE"
log_message "CORS_ALLOWED_ORIGINS: $CURRENT_CORS_ORIGINS" "$BLUE"
log_message "" ""
log_message "--- Nginx ---" "$YELLOW"
if [ -n "$NGINX_CONFIG_FILE" ]; then
    log_message "Config File:        $NGINX_CONFIG_FILE" "$BLUE"
else
    log_message "Config File:        NOT FOUND (will create new)" "$RED"
fi
if [ "$NGINX_CONFIG_MODE" = "sites" ] && [ -n "$NGINX_CONFIG_FILE" ]; then
    SYMLINK="$NGINX_ENABLED/$(basename $NGINX_CONFIG_FILE)"
    if [ -L "$SYMLINK" ]; then
        log_message "Sites-Enabled:      $SYMLINK (symlink exists)" "$BLUE"
    else
        log_message "Sites-Enabled:      NOT FOUND" "$RED"
    fi
fi
log_message "" ""
log_message "--- SSL Certificate ---" "$YELLOW"
if [ -n "$SSL_CERT_PATH" ]; then
    log_message "Certificate Path:   $SSL_CERT_PATH" "$BLUE"
    # Show certificate expiry
    CERT_EXPIRY=$(sudo openssl x509 -enddate -noout -in "$SSL_CERT_PATH/fullchain.pem" 2>/dev/null | cut -d= -f2)
    if [ -n "$CERT_EXPIRY" ]; then
        log_message "Certificate Expiry: $CERT_EXPIRY" "$BLUE"
    fi
else
    log_message "Certificate Path:   NOT FOUND" "$RED"
fi
log_message "" ""
log_message "--- Systemd Service ---" "$YELLOW"
if [ -n "$SERVICE_FILE" ]; then
    SERVICE_STATUS=$(sudo systemctl is-active "$SERVICE_NAME" 2>/dev/null)
    log_message "Service File:       $SERVICE_FILE" "$BLUE"
    log_message "Service Status:     $SERVICE_STATUS" "$BLUE"
else
    log_message "Service File:       NOT FOUND" "$RED"
fi
log_message "========================================" "$YELLOW"

# ============================================
# Step 6: Get new domain from user
# ============================================
echo ""
while true; do
    read -p "Enter the NEW domain name (e.g., newalgo.example.com): " NEW_DOMAIN
    if [ -z "$NEW_DOMAIN" ]; then
        log_message "Error: Domain name is required" "$RED"
        continue
    fi
    # Domain validation (same as install.sh)
    if [[ ! $NEW_DOMAIN =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$ ]]; then
        log_message "Error: Invalid domain format. Please enter a valid domain name" "$RED"
        continue
    fi
    if [ "$NEW_DOMAIN" = "$CURRENT_DOMAIN" ]; then
        log_message "Error: New domain is the same as the current domain" "$RED"
        continue
    fi
    break
done

# Check if it's a subdomain
if [[ $NEW_DOMAIN =~ ^[^.]+\.[^.]+\.[^.]+$ ]]; then
    IS_SUBDOMAIN=true
else
    IS_SUBDOMAIN=false
fi

# ============================================
# Step 7: Show changes and ask for confirmation
# ============================================
log_message "\n========================================" "$YELLOW"
log_message "  Planned Changes" "$YELLOW"
log_message "========================================" "$YELLOW"
log_message "" ""
log_message "Domain Change: $CURRENT_DOMAIN  -->  $NEW_DOMAIN" "$GREEN"
log_message "" ""
log_message "--- .env Updates ---" "$YELLOW"
log_message "HOST_SERVER:          https://$CURRENT_DOMAIN  -->  https://$NEW_DOMAIN" "$BLUE"
log_message "WEBSOCKET_URL:        wss://$CURRENT_DOMAIN/ws  -->  wss://$NEW_DOMAIN/ws" "$BLUE"
if echo "$CURRENT_REDIRECT_URL" | grep -q "$CURRENT_DOMAIN"; then
    log_message "REDIRECT_URL:         .../$CURRENT_DOMAIN/...  -->  .../$NEW_DOMAIN/..." "$BLUE"
fi
if echo "$CURRENT_CORS_ORIGINS" | grep -q "$CURRENT_DOMAIN"; then
    log_message "CORS_ALLOWED_ORIGINS: https://$CURRENT_DOMAIN  -->  https://$NEW_DOMAIN" "$BLUE"
fi
log_message "" ""
log_message "--- Nginx ---" "$YELLOW"
NEW_NGINX_CONFIG="$NGINX_AVAILABLE/$NEW_DOMAIN.conf"
if [ -n "$NGINX_CONFIG_FILE" ]; then
    log_message "Rename:  $(basename $NGINX_CONFIG_FILE)  -->  $NEW_DOMAIN.conf" "$BLUE"
else
    log_message "Create:  $NEW_NGINX_CONFIG" "$BLUE"
fi
log_message "Update:  server_name, ssl_certificate paths" "$BLUE"
log_message "" ""
log_message "--- SSL Certificate ---" "$YELLOW"
log_message "Obtain new Let's Encrypt certificate for: $NEW_DOMAIN" "$BLUE"
log_message "" ""
log_message "--- Services ---" "$YELLOW"
log_message "Stop:    $SERVICE_NAME (before changes)" "$BLUE"
log_message "Restart: $SERVICE_NAME + nginx (after changes)" "$BLUE"
log_message "" ""
log_message "--- Broker Redirect URL ---" "$YELLOW"
# Extract broker from redirect URL or deploy name
BROKER_NAME=$(echo "$CURRENT_REDIRECT_URL" | grep -oP 'https?://[^/]+/\K[^/]+')
if [ -n "$BROKER_NAME" ]; then
    log_message "Update your broker developer portal redirect URL to:" "$YELLOW"
    log_message "  https://$NEW_DOMAIN/$BROKER_NAME/callback" "$GREEN"
fi
log_message "" ""
log_message "Note: The deployment directory ($SELECTED_DEPLOY) and" "$YELLOW"
log_message "service name ($SERVICE_NAME) will NOT be renamed." "$YELLOW"
log_message "This is cosmetic only and does not affect functionality." "$YELLOW"
log_message "========================================" "$YELLOW"

echo ""
read -p "Do you want to proceed with these changes? (y/n): " confirm
if [[ ! $confirm =~ ^[Yy]$ ]]; then
    log_message "Domain change cancelled by user." "$YELLOW"
    exit 0
fi

# ============================================
# Step 8: Stop the service
# ============================================
log_message "\n[Step 1/6] Stopping service: $SERVICE_NAME..." "$BLUE"
if sudo systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    sudo systemctl stop "$SERVICE_NAME"
    check_status "Failed to stop $SERVICE_NAME"
    log_message "Service stopped successfully" "$GREEN"
else
    log_message "Service is not currently running" "$YELLOW"
fi

# ============================================
# Step 9: Backup current configs
# ============================================
log_message "\n[Step 2/6] Backing up current configuration..." "$BLUE"

BACKUP_DIR="$OPENALGO_PATH/db/domain_change_backup_${TIMESTAMP}"
sudo mkdir -p "$BACKUP_DIR"

# Backup .env
sudo cp "$ENV_FILE" "$BACKUP_DIR/.env.backup"
log_message "  Backed up: .env" "$GREEN"

# Backup nginx config
if [ -n "$NGINX_CONFIG_FILE" ] && [ -f "$NGINX_CONFIG_FILE" ]; then
    sudo cp "$NGINX_CONFIG_FILE" "$BACKUP_DIR/nginx_$(basename $NGINX_CONFIG_FILE).backup"
    log_message "  Backed up: nginx config" "$GREEN"
fi

log_message "Backup location: $BACKUP_DIR" "$GREEN"

# ============================================
# Step 10: Update .env file
# ============================================
log_message "\n[Step 3/6] Updating .env file..." "$BLUE"

# Replace all occurrences of old domain with new domain in .env
sudo sed -i "s|$CURRENT_DOMAIN|$NEW_DOMAIN|g" "$ENV_FILE"

# Explicitly ensure critical variables are correct
sudo sed -i "s|HOST_SERVER = '.*'|HOST_SERVER = 'https://$NEW_DOMAIN'|g" "$ENV_FILE"
sudo sed -i "s|WEBSOCKET_URL='.*'|WEBSOCKET_URL='wss://$NEW_DOMAIN/ws'|g" "$ENV_FILE"
# Handle WEBSOCKET_URL with spaces around =
sudo sed -i "s|WEBSOCKET_URL = '.*'|WEBSOCKET_URL = 'wss://$NEW_DOMAIN/ws'|g" "$ENV_FILE"
check_status "Failed to update .env file"

# Verify the changes
VERIFY_HOST=$(sudo grep -oP "HOST_SERVER\s*=\s*'\K[^']+" "$ENV_FILE")
VERIFY_WS=$(sudo grep -oP "WEBSOCKET_URL\s*=\s*'\K[^']+" "$ENV_FILE")
log_message "  HOST_SERVER:    $VERIFY_HOST" "$GREEN"
log_message "  WEBSOCKET_URL:  $VERIFY_WS" "$GREEN"
log_message ".env updated successfully" "$GREEN"

# ============================================
# Step 11: Set up temporary Nginx for Certbot
# ============================================
log_message "\n[Step 4/6] Obtaining SSL certificate for $NEW_DOMAIN..." "$BLUE"

# Remove old nginx config and symlinks
if [ -n "$NGINX_CONFIG_FILE" ] && [ -f "$NGINX_CONFIG_FILE" ]; then
    sudo rm -f "$NGINX_CONFIG_FILE"
fi
if [ "$NGINX_CONFIG_MODE" = "sites" ]; then
    sudo rm -f "$NGINX_ENABLED/$CURRENT_DOMAIN.conf"
    sudo rm -f "$NGINX_ENABLED/$CURRENT_DOMAIN"
fi

# Create temporary Nginx config for certbot HTTP challenge
sudo tee "$NEW_NGINX_CONFIG" > /dev/null << EOL
server {
    listen 80;
    listen [::]:80;
    server_name $NEW_DOMAIN;
    root /var/www/html;

    location / {
        try_files \$uri \$uri/ =404;
    }
}
EOL

# Enable the temporary config
if [ "$NGINX_CONFIG_MODE" = "sites" ]; then
    sudo ln -sf "$NEW_NGINX_CONFIG" "$NGINX_ENABLED/"
fi

# Reload nginx with temporary config
sudo nginx -t
check_status "Failed to validate temporary Nginx configuration"
sudo systemctl reload nginx
check_status "Failed to reload Nginx"

# Obtain new SSL certificate
log_message "Running Certbot for $NEW_DOMAIN..." "$BLUE"
if [ "$IS_SUBDOMAIN" = true ]; then
    sudo certbot --nginx -d "$NEW_DOMAIN" --non-interactive --agree-tos --email admin@${NEW_DOMAIN#*.}
else
    sudo certbot --nginx -d "$NEW_DOMAIN" -d "www.$NEW_DOMAIN" --non-interactive --agree-tos --email admin@$NEW_DOMAIN
fi

# Verify certificate was obtained
if [ ! -f "/etc/letsencrypt/live/$NEW_DOMAIN/fullchain.pem" ]; then
    log_message "Error: Failed to obtain SSL certificate for $NEW_DOMAIN" "$RED"
    log_message "" ""
    log_message "Possible causes:" "$YELLOW"
    log_message "  1. DNS for $NEW_DOMAIN does not point to this server's IP" "$YELLOW"
    log_message "  2. Port 80 is not reachable from the internet" "$YELLOW"
    log_message "  3. Let's Encrypt rate limit reached" "$YELLOW"
    log_message "" ""
    log_message "Restoring backup..." "$YELLOW"
    sudo cp "$BACKUP_DIR/.env.backup" "$ENV_FILE"
    if [ -f "$BACKUP_DIR/nginx_"*".backup" ]; then
        sudo cp "$BACKUP_DIR/nginx_"*".backup" "$NGINX_CONFIG_FILE"
        if [ "$NGINX_CONFIG_MODE" = "sites" ]; then
            sudo rm -f "$NGINX_ENABLED/$(basename $NEW_NGINX_CONFIG)"
            sudo ln -sf "$NGINX_CONFIG_FILE" "$NGINX_ENABLED/"
        fi
    fi
    sudo rm -f "$NEW_NGINX_CONFIG"
    sudo nginx -t && sudo systemctl reload nginx
    sudo systemctl start "$SERVICE_NAME" 2>/dev/null
    log_message "Backup restored. Original configuration is active." "$GREEN"
    exit 1
fi
log_message "SSL certificate obtained successfully" "$GREEN"

# ============================================
# Step 12: Write final Nginx config
# ============================================
log_message "\n[Step 5/6] Configuring final Nginx setup..." "$BLUE"

# Remove the temporary config
sudo rm -f "$NEW_NGINX_CONFIG"
if [ "$NGINX_CONFIG_MODE" = "sites" ]; then
    sudo rm -f "$NGINX_ENABLED/$(basename $NEW_NGINX_CONFIG)"
fi

# Write full production nginx config
sudo tee "$NEW_NGINX_CONFIG" > /dev/null << EOL
server {
    listen 80;
    listen [::]:80;
    server_name $NEW_DOMAIN;

    # WebSocket path exceptions to avoid 301 redirect loop
    location = /ws {
        return 301 https://\$host\$request_uri;
    }

    location /ws/ {
        return 301 https://\$host\$request_uri;
    }

    # All other HTTP requests get redirected to HTTPS
    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;

    server_name $NEW_DOMAIN;

    ssl_certificate /etc/letsencrypt/live/$NEW_DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$NEW_DOMAIN/privkey.pem;

    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers EECDH+AESGCM:EDH+AESGCM;
    ssl_ecdh_curve secp384r1;
    ssl_session_timeout 10m;
    ssl_session_cache shared:SSL:10m;
    ssl_session_tickets off;
    ssl_stapling on;
    ssl_stapling_verify on;

    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=63072000" always;

    # WebSocket without trailing slash
    location = /ws {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;

        # Extended timeouts for long-running connections (up to 24 hours)
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;

        # Disable proxy buffering for real-time data
        proxy_buffering off;

        # WebSocket headers
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # Other headers
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
    }

    # WebSocket with trailing slash
    location /ws/ {
        proxy_pass http://127.0.0.1:8765/;
        proxy_http_version 1.1;

        # Extended timeouts for long-running connections (up to 24 hours)
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;

        # Disable proxy buffering for real-time data
        proxy_buffering off;

        # WebSocket headers
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # Other headers
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
    }

    # Main app (Gunicorn UDS)
    location / {
        proxy_pass http://unix:$SOCKET_FILE;
        proxy_http_version 1.1;

        # Extended timeouts for broker authentication (cold start can take 60-90s)
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;

        # Increased buffer sizes for large headers (auth tokens, session cookies)
        proxy_buffer_size 128k;
        proxy_buffers 4 256k;
        proxy_busy_buffers_size 256k;

        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_redirect off;
    }
}
EOL

# Enable the new config
if [ "$NGINX_CONFIG_MODE" = "sites" ]; then
    sudo ln -sf "$NEW_NGINX_CONFIG" "$NGINX_ENABLED/"
fi

# Test nginx configuration
sudo nginx -t
check_status "Failed to validate final Nginx configuration"
log_message "Nginx configuration updated successfully" "$GREEN"

# ============================================
# Step 13: Restart services
# ============================================
log_message "\n[Step 6/6] Restarting services..." "$BLUE"

sudo systemctl reload nginx
check_status "Failed to reload Nginx"
log_message "Nginx reloaded" "$GREEN"

sudo systemctl start "$SERVICE_NAME"
check_status "Failed to start $SERVICE_NAME"
log_message "Service $SERVICE_NAME started" "$GREEN"

# Verify service is running
sleep 3
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    log_message "Service $SERVICE_NAME is running" "$GREEN"
else
    log_message "Warning: Service $SERVICE_NAME may not have started correctly" "$RED"
    log_message "Check logs with: sudo journalctl -u $SERVICE_NAME -n 50" "$YELLOW"
fi

# ============================================
# Summary
# ============================================
log_message "\n========================================" "$GREEN"
log_message "  Domain Change Summary" "$GREEN"
log_message "========================================" "$GREEN"
log_message "" ""
log_message "Domain Changed:  $CURRENT_DOMAIN  -->  $NEW_DOMAIN" "$GREEN"
log_message "" ""
log_message "Updated Files:" "$BLUE"
log_message "  .env:          $ENV_FILE" "$BLUE"
log_message "  Nginx:         $NEW_NGINX_CONFIG" "$BLUE"
log_message "  SSL Cert:      /etc/letsencrypt/live/$NEW_DOMAIN/" "$BLUE"
log_message "" ""
log_message "Backup Location: $BACKUP_DIR" "$BLUE"
log_message "Change Log:      $LOG_FILE" "$BLUE"
log_message "" ""

if [ -n "$BROKER_NAME" ]; then
    log_message "========================================" "$RED"
    log_message "  ACTION REQUIRED: Update Broker Portal" "$RED"
    log_message "========================================" "$RED"
    log_message "" ""
    log_message "Update your broker's developer portal redirect URL to:" "$YELLOW"
    log_message "  https://$NEW_DOMAIN/$BROKER_NAME/callback" "$GREEN"
    log_message "" ""
    log_message "Without this change, broker login/authentication will fail!" "$RED"
    log_message "" ""
fi

log_message "Your OpenAlgo instance is now available at:" "$GREEN"
log_message "  https://$NEW_DOMAIN" "$GREEN"
log_message "" ""

log_message "Useful Commands:" "$YELLOW"
log_message "  Check status:  sudo systemctl status $SERVICE_NAME" "$BLUE"
log_message "  View logs:     sudo journalctl -u $SERVICE_NAME -n 50" "$BLUE"
log_message "  Restart:       sudo systemctl restart $SERVICE_NAME" "$BLUE"
log_message "" ""
log_message "Domain change completed successfully!" "$GREEN"
