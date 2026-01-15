#!/bin/bash

# OpenAlgo Docker Installation Script
# Simplified installation for Docker deployment with custom domain

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# OpenAlgo Banner
echo -e "${BLUE}"
echo "  ██████╗ ██████╗ ███████╗███╗   ██╗ █████╗ ██╗      ██████╗  ██████╗ "
echo " ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║     ██╔════╝ ██╔═══██╗"
echo " ██║   ██║██████╔╝███████╗██╔██╗ ██║███████║██║     ██║  ███╗██║   ██║"
echo " ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██║██║     ██║   ██║██║   ██║"
echo " ╚██████╔╝██╗     ███████╗██║ ╚████║██║  ██║███████╗╚██████╔╝╚██████╔╝"
echo "  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝ "      
echo "                    DOCKER INSTALLATION                                 "
echo -e "${NC}"

# Function to log messages
log() {
    echo -e "${2}${1}${NC}"
}

# Function to check command status
check_status() {
    if [ $? -ne 0 ]; then
        log "Error: $1" "$RED"
        exit 1
    fi
}

# Function to generate random hex string
generate_hex() {
    python3 -c "import secrets; print(secrets.token_hex(32))"
}

# Function to validate broker
validate_broker() {
    local broker=$1
    local valid_brokers="fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,definedge,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,ibulls,iifl,indmoney,jainamxts,kotak,motilal,mstock,paytm,pocketful,samco,shoonya,tradejini,upstox,wisdom,zebu,zerodha"
    [[ $valid_brokers == *"$broker"* ]]
}

# Function to check if broker is XTS based
is_xts_broker() {
    local broker=$1
    local xts_brokers="fivepaisaxts,compositedge,ibulls,iifl,jainamxts,wisdom"
    [[ $xts_brokers == *"$broker"* ]]
}

# Start installation
log "Starting OpenAlgo Docker Installation..." "$GREEN"
log "========================================" "$GREEN"

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   log "WARNING: Running as root user is not recommended for production." "$YELLOW"
   log "For better security, consider creating a non-root user with sudo privileges." "$YELLOW"
   read -p "Do you want to continue as root? (y/n): " continue_as_root
   if [[ ! $continue_as_root =~ ^[Yy]$ ]]; then
       log "Installation cancelled. Create a non-root user with:" "$BLUE"
       log "  adduser yourusername" "$BLUE"
       log "  usermod -aG sudo yourusername" "$BLUE"
       log "  su - yourusername" "$BLUE"
       exit 0
   fi
   log "Continuing as root user..." "$YELLOW"
   SUDO=""
else
   SUDO="sudo"
fi

# Check OS
if [ ! -f /etc/os-release ]; then
    log "Unsupported operating system" "$RED"
    exit 1
fi

OS_TYPE=$(grep -w "ID" /etc/os-release | cut -d "=" -f 2 | tr -d '"')
log "Detected OS: $OS_TYPE" "$BLUE"

# Support Ubuntu/Debian for now
if [[ "$OS_TYPE" != "ubuntu" && "$OS_TYPE" != "debian" ]]; then
    log "This script currently supports Ubuntu/Debian. Detected: $OS_TYPE" "$YELLOW"
    read -p "Do you want to continue anyway? (y/n): " continue_anyway
    if [[ ! $continue_anyway =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Collect installation information
log "\n=== Installation Configuration ===" "$BLUE"

# Get domain name
while true; do
    read -p "Enter your domain name (e.g., demo.openalgo.in): " DOMAIN
    if [ -z "$DOMAIN" ]; then
        log "Error: Domain name is required" "$RED"
        continue
    fi
    if [[ ! $DOMAIN =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$ ]]; then
        log "Error: Invalid domain format" "$RED"
        continue
    fi
    break
done

# Get broker name
while true; do
    log "\nValid brokers:" "$BLUE"
    echo "fivepaisa, fivepaisaxts, aliceblue, angel, compositedge, definedge,"
    echo "dhan, dhan_sandbox, firstock, flattrade, fyers, groww, ibulls, iifl,"
    echo "indmoney, jainamxts, kotak, motilal, mstock, paytm, pocketful,"
    echo "samco, shoonya, tradejini, upstox, wisdom, zebu, zerodha,"
    echo ""
    read -p "Enter your broker name: " BROKER_NAME
    if validate_broker "$BROKER_NAME"; then
        break
    else
        log "Invalid broker name. Please choose from the list above." "$RED"
    fi
done

# Show redirect URL
log "\n=== Broker API Setup ===" "$YELLOW"
log "Redirect URL for broker developer portal:" "$BLUE"
log "https://$DOMAIN/$BROKER_NAME/callback" "$GREEN"
log "\nUse this URL in your broker's developer portal to get API credentials." "$BLUE"
echo ""

# Get broker API credentials
read -p "Enter your broker API key: " BROKER_API_KEY
read -p "Enter your broker API secret: " BROKER_API_SECRET

if [ -z "$BROKER_API_KEY" ] || [ -z "$BROKER_API_SECRET" ]; then
    log "Error: Broker API credentials are required" "$RED"
    exit 1
fi

# Check if XTS broker and get additional credentials
BROKER_API_KEY_MARKET=""
BROKER_API_SECRET_MARKET=""
if is_xts_broker "$BROKER_NAME"; then
    log "\nThis broker requires additional market data credentials." "$YELLOW"
    read -p "Enter your broker market data API key: " BROKER_API_KEY_MARKET
    read -p "Enter your broker market data API secret: " BROKER_API_SECRET_MARKET
    
    if [ -z "$BROKER_API_KEY_MARKET" ] || [ -z "$BROKER_API_SECRET_MARKET" ]; then
        log "Error: Market data API credentials are required for XTS brokers" "$RED"
        exit 1
    fi
fi

# Get email for SSL certificate
read -p "Enter your email for SSL certificate notifications: " ADMIN_EMAIL
if [ -z "$ADMIN_EMAIL" ]; then
    ADMIN_EMAIL="admin@${DOMAIN#*.}"
fi

# Generate security keys
log "\nGenerating security keys..." "$BLUE"
APP_KEY=$(generate_hex)
API_KEY_PEPPER=$(generate_hex)

# Set installation path
INSTALL_PATH="/opt/openalgo"

log "\n=== Installation Summary ===" "$YELLOW"
log "Domain: $DOMAIN" "$BLUE"
log "Broker: $BROKER_NAME" "$BLUE"
log "Installation Path: $INSTALL_PATH" "$BLUE"
log "Email: $ADMIN_EMAIL" "$BLUE"
echo ""

read -p "Proceed with installation? (y/n): " proceed
if [[ ! $proceed =~ ^[Yy]$ ]]; then
    log "Installation cancelled." "$YELLOW"
    exit 0
fi

# Update system
log "\n=== Updating System ===" "$BLUE"
$SUDO apt-get update -y
$SUDO apt-get upgrade -y
check_status "System update failed"

# Install required packages
log "\n=== Installing Required Packages ===" "$BLUE"
$SUDO apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    nginx \
    certbot \
    python3-certbot-nginx \
    ufw
check_status "Package installation failed"

# Install Docker
log "\n=== Installing Docker ===" "$BLUE"
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    $SUDO sh get-docker.sh
    $SUDO usermod -aG docker $USER
    rm get-docker.sh
    check_status "Docker installation failed"
else
    log "Docker already installed" "$GREEN"
fi

# Verify Docker Compose
if ! docker compose version &> /dev/null; then
    log "Error: Docker Compose not found" "$RED"
    exit 1
fi
log "Docker Compose version: $(docker compose version --short)" "$GREEN"

# Clone OpenAlgo repository
log "\n=== Cloning OpenAlgo Repository ===" "$BLUE"
if [ -d "$INSTALL_PATH" ]; then
    log "Warning: $INSTALL_PATH already exists" "$YELLOW"
    read -p "Remove existing installation? (y/n): " remove_existing
    if [[ $remove_existing =~ ^[Yy]$ ]]; then
        $SUDO rm -rf $INSTALL_PATH
    else
        log "Installation cancelled" "$RED"
        exit 1
    fi
fi

$SUDO git clone https://github.com/marketcalls/openalgo.git $INSTALL_PATH
check_status "Git clone failed"

cd $INSTALL_PATH

# Create required directories
log "\n=== Creating Required Directories ===" "$BLUE"
$SUDO mkdir -p log logs keys db strategies/scripts strategies/examples
$SUDO chown -R 1000:1000 log logs strategies
$SUDO chmod -R 755 strategies log
$SUDO chmod 700 keys
check_status "Directory creation failed"

# Configure environment file
log "\n=== Configuring Environment File ===" "$BLUE"
$SUDO cp .sample.env .env

# Update .env file
$SUDO sed -i "s|YOUR_BROKER_API_KEY|$BROKER_API_KEY|g" .env
$SUDO sed -i "s|YOUR_BROKER_API_SECRET|$BROKER_API_SECRET|g" .env
$SUDO sed -i "s|http://127.0.0.1:5000|https://$DOMAIN|g" .env
$SUDO sed -i "s|<broker>|$BROKER_NAME|g" .env
$SUDO sed -i "s|3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952e93d88bf07ea84|$APP_KEY|g" .env
$SUDO sed -i "s|a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772|$API_KEY_PEPPER|g" .env

# Update XTS market data credentials if applicable
if is_xts_broker "$BROKER_NAME"; then
    $SUDO sed -i "s|YOUR_BROKER_MARKET_API_KEY|$BROKER_API_KEY_MARKET|g" .env
    $SUDO sed -i "s|YOUR_BROKER_MARKET_API_SECRET|$BROKER_API_SECRET_MARKET|g" .env
fi

# Update WebSocket and host configurations
$SUDO sed -i "s|WEBSOCKET_URL='.*'|WEBSOCKET_URL='wss://$DOMAIN/ws'|g" .env
$SUDO sed -i "s|WEBSOCKET_HOST='127.0.0.1'|WEBSOCKET_HOST='0.0.0.0'|g" .env
$SUDO sed -i "s|ZMQ_HOST='127.0.0.1'|ZMQ_HOST='0.0.0.0'|g" .env
$SUDO sed -i "s|FLASK_HOST_IP='127.0.0.1'|FLASK_HOST_IP='0.0.0.0'|g" .env
$SUDO sed -i "s|CORS_ALLOWED_ORIGINS = '.*'|CORS_ALLOWED_ORIGINS = 'https://$DOMAIN'|g" .env
$SUDO sed -i "s|CSP_CONNECT_SRC = \"'self'.*\"|CSP_CONNECT_SRC = \"'self' wss://$DOMAIN https://$DOMAIN wss: ws: https://cdn.socket.io\"|g" .env

check_status "Environment configuration failed"

# Create docker-compose.yaml
log "\n=== Creating Docker Compose Configuration ===" "$BLUE"
$SUDO tee docker-compose.yaml > /dev/null << 'EOF'
services:
  openalgo:
    image: openalgo:latest
    build:
      context: .
      dockerfile: Dockerfile

    container_name: openalgo-web

    ports:
      - "127.0.0.1:5000:5000"
      - "127.0.0.1:8765:8765"

    # Use named volumes to avoid permission issues with non-root container user
    volumes:
      - openalgo_db:/app/db
      - openalgo_logs:/app/logs
      - openalgo_log:/app/log
      - openalgo_strategies:/app/strategies
      - openalgo_keys:/app/keys
      - ./.env:/app/.env:ro

    environment:
      - FLASK_ENV=production
      - FLASK_DEBUG=0
      - APP_MODE=standalone

    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

    restart: unless-stopped

# Named volumes for data persistence with proper permissions
volumes:
  openalgo_db:
    driver: local
  openalgo_logs:
    driver: local
  openalgo_log:
    driver: local
  openalgo_strategies:
    driver: local
  openalgo_keys:
    driver: local
EOF

check_status "Docker Compose configuration failed"

# Configure firewall
log "\n=== Configuring Firewall ===" "$BLUE"
$SUDO ufw --force enable
$SUDO ufw default deny incoming
$SUDO ufw default allow outgoing
$SUDO ufw allow ssh
$SUDO ufw allow 80/tcp
$SUDO ufw allow 443/tcp
check_status "Firewall configuration failed"

# Initial Nginx configuration
log "\n=== Configuring Nginx (Initial) ===" "$BLUE"
$SUDO tee /etc/nginx/sites-available/$DOMAIN > /dev/null << EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }
    
    location / {
        return 301 https://\$server_name\$request_uri;
    }
}
EOF

$SUDO ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/
$SUDO rm -f /etc/nginx/sites-enabled/default
$SUDO nginx -t
check_status "Nginx configuration test failed"

$SUDO systemctl enable nginx
$SUDO systemctl reload nginx
check_status "Nginx reload failed"

# Obtain SSL certificate
log "\n=== Obtaining SSL Certificate ===" "$BLUE"
log "Please wait while we obtain SSL certificate from Let's Encrypt..." "$YELLOW"
$SUDO certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email $ADMIN_EMAIL
check_status "SSL certificate obtention failed"

# Final Nginx configuration with SSL
log "\n=== Configuring Nginx (Production with SSL) ===" "$BLUE"
$SUDO tee /etc/nginx/sites-available/$DOMAIN > /dev/null << EOF
# Rate limiting zones
limit_req_zone \$binary_remote_addr zone=api_limit:10m rate=50r/s;
limit_req_zone \$binary_remote_addr zone=general_limit:10m rate=10r/s;

# Upstream definitions
upstream openalgo_flask {
    server 127.0.0.1:5000;
    keepalive 64;
}

upstream openalgo_websocket {
    server 127.0.0.1:8765;
    keepalive 64;
}

# HTTP - Redirect to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    # Allow Certbot renewals
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # WebSocket paths
    location = /ws {
        return 301 https://\$host\$request_uri;
    }

    location /ws/ {
        return 301 https://\$host\$request_uri;
    }

    # All other HTTP traffic
    location / {
        return 301 https://\$host\$request_uri;
    }
}

# HTTPS - Main Configuration
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    
    server_name $DOMAIN;
    
    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
    
    # Security Headers
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    
    # Client settings
    client_max_body_size 100M;
    client_body_timeout 300s;
    
    # Logging
    access_log /var/log/nginx/${DOMAIN}_access.log;
    error_log /var/log/nginx/${DOMAIN}_error.log;

    # WebSocket Proxy Server (Port 8765)
    location = /ws {
        proxy_pass http://openalgo_websocket;
        proxy_http_version 1.1;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_connect_timeout 60s;
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_redirect off;
    }

    location /ws/ {
        proxy_pass http://openalgo_websocket/;
        proxy_http_version 1.1;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_connect_timeout 60s;
        proxy_buffering off;
        proxy_cache off;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_redirect off;
    }

    # Socket.IO WebSocket
    location /socket.io/ {
        proxy_pass http://openalgo_flask/socket.io/;
        proxy_http_version 1.1;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
        proxy_connect_timeout 60s;
        proxy_buffering off;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_redirect off;
    }

    # API Endpoints
    location /api/ {
        limit_req zone=api_limit burst=100 nodelay;
        limit_req_status 429;
        proxy_pass http://openalgo_flask;
        proxy_http_version 1.1;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_set_header Connection "";
        proxy_redirect off;
    }

    # Static Files
    location /static/ {
        proxy_pass http://openalgo_flask;
        proxy_http_version 1.1;
        proxy_cache_valid 200 1d;
        proxy_cache_bypass \$http_pragma \$http_authorization;
        expires 1d;
        add_header Cache-Control "public, max-age=86400";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # Main Application
    location / {
        limit_req zone=general_limit burst=20 nodelay;
        proxy_pass http://openalgo_flask;
        proxy_http_version 1.1;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_buffering off;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header X-Forwarded-Host \$host;
        proxy_set_header X-Forwarded-Port \$server_port;
        proxy_set_header Connection "";
        proxy_redirect off;
    }

    # Deny hidden files
    location ~ /\. {
        deny all;
        access_log off;
        log_not_found off;
    }

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml text/javascript 
               application/json application/javascript application/xml+rss 
               application/x-javascript;
}
EOF

$SUDO nginx -t
check_status "Nginx configuration test failed"

$SUDO systemctl reload nginx
check_status "Nginx reload failed"

# Build and start Docker container
log "\n=== Building Docker Image ===" "$BLUE"
log "This may take several minutes..." "$YELLOW"
sudo docker compose build
check_status "Docker build failed"

log "\n=== Starting Docker Container ===" "$BLUE"
sudo docker compose up -d
check_status "Docker container start failed"

# Wait for container to be healthy
log "\nWaiting for container to be healthy..." "$YELLOW"
sleep 10

# Check container status
CONTAINER_STATUS=$(sudo docker ps --filter "name=openalgo-web" --format "{{.Status}}")
if [[ $CONTAINER_STATUS == *"Up"* ]]; then
    log "Container started successfully!" "$GREEN"
else
    log "Warning: Container may not have started correctly" "$YELLOW"
    log "Check logs with: sudo docker compose logs -f" "$BLUE"
fi

# Create management scripts
log "\n=== Creating Management Scripts ===" "$BLUE"

# Status script
$SUDO tee /usr/local/bin/openalgo-status > /dev/null << 'EOFSCRIPT'
#!/bin/bash
echo "=========================================="
echo "OpenAlgo Status"
echo "=========================================="
echo ""
echo "Container Status:"
sudo docker ps --filter "name=openalgo-web" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""
echo "Container Health:"
sudo docker inspect openalgo-web --format='{{.State.Health.Status}}' 2>/dev/null || echo "Container not found"
echo ""
echo "Recent Logs:"
sudo docker compose -f /opt/openalgo/docker-compose.yaml logs --tail=30
EOFSCRIPT

$SUDO chmod +x /usr/local/bin/openalgo-status

# Restart script
$SUDO tee /usr/local/bin/openalgo-restart > /dev/null << 'EOFSCRIPT'
#!/bin/bash
echo "Restarting OpenAlgo..."
cd /opt/openalgo
sudo docker compose restart
sleep 10
echo "Container Status:"
sudo docker ps --filter "name=openalgo-web"
EOFSCRIPT

$SUDO chmod +x /usr/local/bin/openalgo-restart

# Logs script
$SUDO tee /usr/local/bin/openalgo-logs > /dev/null << 'EOFSCRIPT'
#!/bin/bash
cd /opt/openalgo
sudo docker compose logs -f --tail=100
EOFSCRIPT

$SUDO chmod +x /usr/local/bin/openalgo-logs

# Backup script
$SUDO tee /usr/local/bin/openalgo-backup > /dev/null << 'EOFSCRIPT'
#!/bin/bash
BACKUP_DIR="/opt/openalgo-backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/openalgo_backup_$TIMESTAMP.tar.gz"
mkdir -p $BACKUP_DIR
echo "Creating backup..."
cd /opt/openalgo

# Backup .env file and Docker volume data
echo "Backing up configuration and volume data..."
sudo docker compose stop

# Create temp directory for volume exports
TEMP_DIR=$(mktemp -d)

# Export data from Docker volumes
sudo docker run --rm -v openalgo_db:/data -v $TEMP_DIR:/backup alpine tar -czf /backup/db.tar.gz -C /data . 2>/dev/null
sudo docker run --rm -v openalgo_strategies:/data -v $TEMP_DIR:/backup alpine tar -czf /backup/strategies.tar.gz -C /data . 2>/dev/null

# Create final backup
sudo tar -czf $BACKUP_FILE .env -C $TEMP_DIR db.tar.gz strategies.tar.gz 2>/dev/null

# Cleanup temp directory
sudo rm -rf $TEMP_DIR

sudo docker compose start
echo "Backup created: $BACKUP_FILE"

# Keep only last 7 backups
cd $BACKUP_DIR
ls -t openalgo_backup_*.tar.gz 2>/dev/null | tail -n +8 | xargs -r rm
echo "Backup completed!"
EOFSCRIPT

$SUDO chmod +x /usr/local/bin/openalgo-backup

log "Management scripts created successfully!" "$GREEN"

# Setup SSL auto-renewal
log "\n=== Setting Up SSL Auto-Renewal ===" "$BLUE"
$SUDO mkdir -p /etc/letsencrypt/renewal-hooks/deploy
$SUDO tee /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh > /dev/null << 'EOFSCRIPT'
#!/bin/bash
systemctl reload nginx
EOFSCRIPT
$SUDO chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

# Installation complete
log "\n============================================" "$GREEN"
log "OpenAlgo Docker Installation Complete!" "$GREEN"
log "============================================" "$GREEN"

log "\nInstallation Summary:" "$YELLOW"
log "Domain: https://$DOMAIN" "$BLUE"
log "Broker: $BROKER_NAME" "$BLUE"
log "Installation Path: $INSTALL_PATH" "$BLUE"
log "Container: openalgo-web" "$BLUE"

log "\nNext Steps:" "$YELLOW"
log "1. Visit https://$DOMAIN to access OpenAlgo" "$GREEN"
log "2. Create your admin account and login" "$GREEN"
log "3. Configure your broker settings" "$GREEN"

log "\nUseful Commands:" "$YELLOW"
log "View status:  openalgo-status" "$BLUE"
log "View logs:    openalgo-logs" "$BLUE"
log "Restart:      openalgo-restart" "$BLUE"
log "Backup:       openalgo-backup" "$BLUE"

log "\nDocker Commands:" "$YELLOW"
log "Restart:      cd $INSTALL_PATH && sudo docker compose restart" "$BLUE"
log "Stop:         cd $INSTALL_PATH && sudo docker compose stop" "$BLUE"
log "Start:        cd $INSTALL_PATH && sudo docker compose start" "$BLUE"
log "Rebuild:      cd $INSTALL_PATH && sudo docker compose down && sudo docker compose build --no-cache && sudo docker compose up -d" "$BLUE"

log "\nFor support, visit: https://discord.com/invite/UPh7QPsNhP" "$BLUE"

log "\n============================================" "$GREEN"
log "Installation completed successfully!" "$GREEN"
log "============================================" "$GREEN"
