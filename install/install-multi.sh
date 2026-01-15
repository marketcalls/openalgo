#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# OpenAlgo Multi-Instance Installation Banner
echo -e "${BLUE}"
echo "  ██████╗ ██████╗ ███████╗███╗   ██╗ █████╗ ██╗      ██████╗  ██████╗ "
echo " ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║     ██╔════╝ ██╔═══██╗"
echo " ██║   ██║██████╔╝███████╗██╔██╗ ██║███████║██║     ██║  ███╗██║   ██║"
echo " ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██║██║     ██║   ██║██║   ██║"
echo " ╚██████╔╝██╗     ███████╗██║ ╚████║██║  ██║███████╗╚██████╔╝╚██████╔╝"
echo "  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝ "
echo "                      MULTI-INSTANCE INSTALLER                          "
echo -e "${NC}"

# Create logs directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOGS_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOGS_DIR"

# Generate unique log file
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOGS_DIR/install_multi_${TIMESTAMP}.log"

# Function to log messages
log_message() {
    local message="$1"
    local color="$2"
    echo -e "${color}${message}${NC}" | tee -a "$LOG_FILE"
}

# Function to check command status
check_status() {
    if [ $? -ne 0 ]; then
        log_message "Error: $1" "$RED"
        exit 1
    fi
}

# Function to generate random hex string
generate_hex() {
    python3 -c "import secrets; print(secrets.token_hex(32))"
}

# Function to validate broker name
validate_broker() {
    local broker=$1
    local valid_brokers="fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,definedge,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,ibulls,iifl,indmoney,jainamxts,kotak,motilal,mstock,paytm,pocketful,samco,shoonya,tradejini,upstox,wisdom,zebu,zerodha"

    if [[ $valid_brokers == *"$broker"* ]]; then
        return 0
    else
        return 1
    fi
}

# Function to check if broker is XTS based
is_xts_broker() {
    local broker=$1
    local xts_brokers="fivepaisaxts,compositedge,ibulls,iifl,jainamxts,wisdom"
    if [[ $xts_brokers == *"$broker"* ]]; then
        return 0
    else
        return 1
    fi
}

# Function to check timezone
check_timezone() {
    current_tz=$(timedatectl | grep "Time zone" | awk '{print $3}')
    log_message "Current timezone: $current_tz" "$BLUE"

    if [[ "$current_tz" == "Asia/Kolkata" ]]; then
        log_message "Server is already set to IST timezone." "$GREEN"
        return 0
    fi

    log_message "Server is not set to IST timezone." "$YELLOW"
    read -p "Would you like to change the timezone to IST? (y/n): " change_tz
    if [[ $change_tz =~ ^[Yy]$ ]]; then
        log_message "Changing timezone to IST..." "$BLUE"
        sudo timedatectl set-timezone Asia/Kolkata
        check_status "Failed to change timezone"
        log_message "Timezone successfully changed to IST" "$GREEN"
    else
        log_message "Keeping current timezone: $current_tz" "$YELLOW"
    fi
}

# Start logging
log_message "Starting OpenAlgo Multi-Instance installation" "$BLUE"
log_message "Log file: $LOG_FILE" "$BLUE"
log_message "----------------------------------------" "$BLUE"

# Check timezone
check_timezone

# Ask number of instances
while true; do
    read -p "How many OpenAlgo instances do you want to set up? " INSTANCES
    if [[ "$INSTANCES" =~ ^[0-9]+$ ]] && [ "$INSTANCES" -gt 0 ]; then
        break
    else
        log_message "❌ Invalid number. Please enter a positive integer." "$RED"
    fi
done

log_message "Setting up $INSTANCES OpenAlgo instances" "$GREEN"

# Base configuration
BASE_DIR="/var/python/openalgo-flask"
REPO_URL="https://github.com/marketcalls/openalgo.git"
FLASK_PORT_BASE=5000
WS_PORT_BASE=8765
ZMQ_PORT_BASE=5555

# Arrays to store instance configurations
declare -a DOMAINS
declare -a BROKERS
declare -a API_KEYS
declare -a API_SECRETS
declare -a API_KEYS_MARKET
declare -a API_SECRETS_MARKET
declare -a IS_XTS

# Collect information for all instances
log_message "\n=== COLLECTING INSTANCE CONFIGURATIONS ===" "$YELLOW"

for ((i=1; i<=INSTANCES; i++)); do
    log_message "\n--- Instance $i Configuration ---" "$BLUE"

    # Get domain
    while true; do
        read -p "Enter subdomain for instance $i (e.g., trade$i.example.com): " domain
        if [ -z "$domain" ]; then
            log_message "Error: Domain name is required" "$RED"
            continue
        fi
        # Simplified domain validation: must contain at least one dot and end with valid TLD
        if [[ ! $domain =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.([a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?))+$ ]]; then
            log_message "Error: Invalid domain format (e.g., subdomain.example.com)" "$RED"
            continue
        fi
        DOMAINS+=("$domain")
        break
    done

    # Get broker
    while true; do
        log_message "\nValid brokers: fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,definedge,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,ibulls,iifl,indmoney,jainamxts,kotak,motilal,mstock,paytm,pocketful,samco,shoonya,tradejini,upstox,wisdom,zebu,zerodha" "$BLUE"
        read -p "Enter broker name for instance $i: " broker
        if validate_broker "$broker"; then
            BROKERS+=("$broker")
            break
        else
            log_message "Invalid broker name" "$RED"
        fi
    done

    # Show redirect URL
    log_message "\nRedirect URL for broker portal: https://${domain}/${broker}/callback" "$GREEN"
    echo ""

    # Get API credentials
    read -p "Enter broker API key for instance $i: " api_key
    read -p "Enter broker API secret for instance $i: " api_secret

    if [ -z "$api_key" ] || [ -z "$api_secret" ]; then
        log_message "Error: API credentials are required" "$RED"
        exit 1
    fi

    API_KEYS+=("$api_key")
    API_SECRETS+=("$api_secret")

    # Check for XTS broker
    if is_xts_broker "$broker"; then
        IS_XTS+=("true")
        log_message "\nThis broker ($broker) requires market data credentials" "$YELLOW"
        read -p "Enter market data API key: " market_key
        read -p "Enter market data API secret: " market_secret

        if [ -z "$market_key" ] || [ -z "$market_secret" ]; then
            log_message "Error: Market data credentials required for XTS brokers" "$RED"
            exit 1
        fi

        API_KEYS_MARKET+=("$market_key")
        API_SECRETS_MARKET+=("$market_secret")
    else
        IS_XTS+=("false")
        API_KEYS_MARKET+=("")
        API_SECRETS_MARKET+=("")
    fi

    log_message "✅ Instance $i configuration collected" "$GREEN"
done

# System packages installation (one-time)
log_message "\n=== INSTALLING SYSTEM PACKAGES ===" "$YELLOW"
sudo apt-get update && sudo apt-get upgrade -y
check_status "Failed to update system"

sudo apt-get install -y python3 python3-venv python3-pip python3-full nginx git software-properties-common snapd ufw certbot python3-certbot-nginx
check_status "Failed to install packages"

# Install uv
log_message "\nInstalling uv package manager..." "$BLUE"
sudo snap install astral-uv --classic
check_status "Failed to install uv"

# Configure firewall (one-time)
log_message "\nConfiguring firewall..." "$BLUE"
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
check_status "Failed to configure firewall"

# Create base directory
sudo mkdir -p "$BASE_DIR"

# Install each instance
log_message "\n=== INSTALLING INSTANCES ===" "$YELLOW"

for ((i=1; i<=INSTANCES; i++)); do
    idx=$((i-1))
    DOMAIN="${DOMAINS[$idx]}"
    BROKER="${BROKERS[$idx]}"
    API_KEY="${API_KEYS[$idx]}"
    API_SECRET="${API_SECRETS[$idx]}"
    API_KEY_MARKET="${API_KEYS_MARKET[$idx]}"
    API_SECRET_MARKET="${API_SECRETS_MARKET[$idx]}"
    IS_XTS_INSTANCE="${IS_XTS[$idx]}"

    log_message "\n--- Installing Instance $i: $DOMAIN ($BROKER) ---" "$BLUE"

    # Paths
    DEPLOY_NAME="${DOMAIN/./-}-${BROKER}"
    INSTANCE_DIR="$BASE_DIR/openalgo$i"
    VENV_PATH="$INSTANCE_DIR/venv"
    SOCKET_FILE="$INSTANCE_DIR/openalgo.sock"
    SERVICE_NAME="openalgo$i"

    # Ports
    FLASK_PORT=$((FLASK_PORT_BASE + i - 1))
    WS_PORT=$((WS_PORT_BASE + i - 1))
    ZMQ_PORT=$((ZMQ_PORT_BASE + i - 1))

    # Clone or update repository
    if [ ! -d "$INSTANCE_DIR" ]; then
        log_message "📥 Cloning repository to $INSTANCE_DIR" "$BLUE"
        sudo git clone "$REPO_URL" "$INSTANCE_DIR"
        check_status "Failed to clone repository"
    else
        log_message "⚠️ Directory exists, skipping clone" "$YELLOW"
    fi

    # Create virtual environment
    log_message "Setting up virtual environment..." "$BLUE"
    if [ -d "$VENV_PATH" ]; then
        sudo rm -rf "$VENV_PATH"
    fi
    sudo uv venv "$VENV_PATH"
    check_status "Failed to create venv"

    # Install dependencies
    log_message "Installing Python dependencies..." "$BLUE"
    ACTIVATE_CMD="source $VENV_PATH/bin/activate"
    sudo bash -c "$ACTIVATE_CMD && uv pip install -r $INSTANCE_DIR/requirements-nginx.txt"
    check_status "Failed to install dependencies"

    # Ensure gunicorn and eventlet
    sudo bash -c "$ACTIVATE_CMD && uv pip install gunicorn eventlet"

    # Configure .env file
    log_message "Configuring environment file..." "$BLUE"
    ENV_FILE="$INSTANCE_DIR/.env"

    if [ -f "$ENV_FILE" ]; then
        sudo mv "$ENV_FILE" "${ENV_FILE}.backup_$(date +%Y%m%d_%H%M%S)"
    fi

    sudo cp "$INSTANCE_DIR/.sample.env" "$ENV_FILE"

    # Generate keys
    APP_KEY=$(generate_hex)
    API_KEY_PEPPER=$(generate_hex)

    # Database paths
    DB_PATH="sqlite:///db/openalgo${i}.db"
    LATENCY_DB="sqlite:///db/latency${i}.db"
    LOGS_DB="sqlite:///db/logs${i}.db"

    # Session/CSRF cookie names
    SESSION_COOKIE="session${i}"
    CSRF_COOKIE="csrf_token${i}"

    # Update .env file
    # IMPORTANT: Order matters! Update broker and domain BEFORE ports

    # 1. Replace broker placeholder first
    sudo sed -i "s|<broker>|$BROKER|g" "$ENV_FILE"

    # 2. Replace domain URLs (before port changes)
    sudo sed -i "s|http://127.0.0.1:5000|https://$DOMAIN|g" "$ENV_FILE"
    sudo sed -i "s|CORS_ALLOWED_ORIGINS = '.*'|CORS_ALLOWED_ORIGINS = 'https://$DOMAIN'|g" "$ENV_FILE"

    # 3. Update ports (these stay as localhost for internal communication)
    sudo sed -i "s|FLASK_PORT='[0-9]*'|FLASK_PORT='$FLASK_PORT'|g" "$ENV_FILE"
    sudo sed -i "s|WEBSOCKET_PORT='[0-9]*'|WEBSOCKET_PORT='$WS_PORT'|g" "$ENV_FILE"
    sudo sed -i "s|ZMQ_PORT='[0-9]*'|ZMQ_PORT='$ZMQ_PORT'|g" "$ENV_FILE"

    # 4. Update WebSocket URL for production (secure WebSocket through nginx)
    sudo sed -i "s|WEBSOCKET_URL='.*'|WEBSOCKET_URL='wss://$DOMAIN/ws'|g" "$ENV_FILE"

    # 5. Update host bindings to allow external connections
    sudo sed -i "s|WEBSOCKET_HOST='127.0.0.1'|WEBSOCKET_HOST='0.0.0.0'|g" "$ENV_FILE"
    sudo sed -i "s|ZMQ_HOST='127.0.0.1'|ZMQ_HOST='0.0.0.0'|g" "$ENV_FILE"

    # 6. Update API credentials
    sudo sed -i "s|YOUR_BROKER_API_KEY|$API_KEY|g" "$ENV_FILE"
    sudo sed -i "s|YOUR_BROKER_API_SECRET|$API_SECRET|g" "$ENV_FILE"

    # 7. Update security keys
    sudo sed -i "s|3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952e93d88bf07ea84|$APP_KEY|g" "$ENV_FILE"
    sudo sed -i "s|a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772|$API_KEY_PEPPER|g" "$ENV_FILE"

    # 8. Update database paths (unique per instance)
    sudo sed -i "s|DATABASE_URL = '.*'|DATABASE_URL = '$DB_PATH'|g" "$ENV_FILE"
    sudo sed -i "s|LATENCY_DATABASE_URL = '.*'|LATENCY_DATABASE_URL = '$LATENCY_DB'|g" "$ENV_FILE"
    sudo sed -i "s|LOGS_DATABASE_URL = '.*'|LOGS_DATABASE_URL = '$LOGS_DB'|g" "$ENV_FILE"

    # 9. Update session/CSRF cookies (CRITICAL for instance isolation)
    sudo sed -i "s|SESSION_COOKIE_NAME = '.*'|SESSION_COOKIE_NAME = '$SESSION_COOKIE'|g" "$ENV_FILE"
    sudo sed -i "s|CSRF_COOKIE_NAME = '.*'|CSRF_COOKIE_NAME = '$CSRF_COOKIE'|g" "$ENV_FILE"

    # 10. Update Flask host IP binding (internal only)
    sudo sed -i "s|FLASK_HOST_IP='.*'|FLASK_HOST_IP='127.0.0.1'|g" "$ENV_FILE"

    # XTS broker credentials
    if [ "$IS_XTS_INSTANCE" = "true" ]; then
        sudo sed -i "s|YOUR_BROKER_MARKET_API_KEY|$API_KEY_MARKET|g" "$ENV_FILE"
        sudo sed -i "s|YOUR_BROKER_MARKET_API_SECRET|$API_SECRET_MARKET|g" "$ENV_FILE"
    fi

    # Set permissions
    log_message "Setting permissions..." "$BLUE"
    sudo mkdir -p "$INSTANCE_DIR/db"
    sudo mkdir -p "$INSTANCE_DIR/tmp"
    # Create directories for Python strategy feature
    sudo mkdir -p "$INSTANCE_DIR/strategies/scripts"
    sudo mkdir -p "$INSTANCE_DIR/strategies/examples"
    sudo mkdir -p "$INSTANCE_DIR/log/strategies"
    sudo mkdir -p "$INSTANCE_DIR/keys"
    sudo chown -R www-data:www-data "$INSTANCE_DIR"
    sudo chmod -R 755 "$INSTANCE_DIR"
    # Set more restrictive permissions for sensitive directories
    sudo chmod 700 "$INSTANCE_DIR/keys"
    [ -S "$SOCKET_FILE" ] && sudo rm -f "$SOCKET_FILE"

    # Configure Nginx (initial for SSL)
    log_message "Configuring Nginx for SSL..." "$BLUE"
    sudo tee /etc/nginx/sites-available/$DOMAIN > /dev/null << EOL
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    root /var/www/html;

    location / {
        try_files \$uri \$uri/ =404;
    }
}
EOL

    sudo ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/

    # Remove default on first instance
    if [ $i -eq 1 ]; then
        sudo rm -f /etc/nginx/sites-enabled/default
    fi

    # Reload Nginx
    sudo nginx -t && sudo systemctl reload nginx
    check_status "Failed to reload Nginx"

    # Obtain SSL certificate
    log_message "Obtaining SSL certificate for $DOMAIN..." "$BLUE"
    sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email admin@${DOMAIN#*.}
    check_status "Failed to obtain SSL certificate"

    # Configure final Nginx with SSL and WebSocket
    log_message "Configuring final Nginx setup..." "$BLUE"
    sudo tee /etc/nginx/sites-available/$DOMAIN > /dev/null << EOL
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    # WebSocket redirect exceptions
    location = /ws {
        return 301 https://\$host\$request_uri;
    }

    location /ws/ {
        return 301 https://\$host\$request_uri;
    }

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;

    server_name $DOMAIN;

    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;

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

    # WebSocket endpoints
    location = /ws {
        proxy_pass http://127.0.0.1:$WS_PORT;
        proxy_http_version 1.1;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_buffering off;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:$WS_PORT/;
        proxy_http_version 1.1;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_buffering off;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Main app via Unix socket
    location / {
        proxy_pass http://unix:$SOCKET_FILE;
        proxy_http_version 1.1;

        # Extended timeouts for broker authentication (cold start can take 60-90s)
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;

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

    sudo nginx -t
    check_status "Failed to validate Nginx config"

    # Create systemd service
    log_message "Creating systemd service..." "$BLUE"
    sudo tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null << EOL
[Unit]
Description=OpenAlgo Instance $i ($DOMAIN - $BROKER)
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=$INSTANCE_DIR
ExecStart=/bin/bash -c 'source $VENV_PATH/bin/activate && $VENV_PATH/bin/gunicorn \\
    --worker-class eventlet \\
    -w 1 \\
    --bind unix:$SOCKET_FILE \\
    --log-level info \\
    app:app'
Restart=always
RestartSec=5
TimeoutSec=60

[Install]
WantedBy=multi-user.target
EOL

    # Enable and start service
    log_message "Starting service..." "$BLUE"
    sudo systemctl daemon-reload
    sudo systemctl enable $SERVICE_NAME
    sudo systemctl start $SERVICE_NAME
    check_status "Failed to start service"

    log_message "✅ Instance $i installed successfully!" "$GREEN"
    log_message "   URL: https://$DOMAIN" "$BLUE"
    log_message "   Flask:$FLASK_PORT | WS:$WS_PORT | ZMQ:$ZMQ_PORT" "$BLUE"
    log_message "   Service: $SERVICE_NAME" "$BLUE"
done

# Final Nginx reload
log_message "\nReloading Nginx..." "$BLUE"
sudo systemctl reload nginx

# Summary
log_message "\n╔════════════════════════════════════════════════════════╗" "$GREEN"
log_message "║          MULTI-INSTANCE INSTALLATION COMPLETE          ║" "$GREEN"
log_message "╚════════════════════════════════════════════════════════╝" "$GREEN"

log_message "\n📋 INSTANCE SUMMARY:" "$YELLOW"
for ((i=1; i<=INSTANCES; i++)); do
    idx=$((i-1))
    log_message "\nInstance $i:" "$BLUE"
    log_message "  Domain: https://${DOMAINS[$idx]}" "$GREEN"
    log_message "  Broker: ${BROKERS[$idx]}" "$BLUE"
    log_message "  Service: openalgo$i" "$BLUE"
    log_message "  Directory: $BASE_DIR/openalgo$i" "$BLUE"
done

log_message "\n📚 USEFUL COMMANDS:" "$YELLOW"
log_message "View all services: systemctl list-units 'openalgo*'" "$BLUE"
log_message "Restart instance: sudo systemctl restart openalgo<N>" "$BLUE"
log_message "View logs: sudo journalctl -u openalgo<N> -f" "$BLUE"
log_message "Check status: sudo systemctl status openalgo<N>" "$BLUE"

log_message "\n📝 Installation log saved to: $LOG_FILE" "$BLUE"
log_message "\n🎉 All instances are ready to use!" "$GREEN"
