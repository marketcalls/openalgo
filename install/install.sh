#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# openalgo Installation Banner
echo -e "${BLUE}"
echo "  ██████╗ ██████╗ ███████╗███╗   ██╗ █████╗ ██╗      ██████╗  ██████╗ "
echo " ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║     ██╔════╝ ██╔═══██╗"
echo " ██║   ██║██████╔╝███████╗██╔██╗ ██║███████║██║     ██║  ███╗██║   ██║"
echo " ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██║██║     ██║   ██║██║   ██║"
echo " ╚██████╔╝██╗     ███████╗██║ ╚████║██║  ██║███████╗╚██████╔╝╚██████╔╝"
echo "  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝ "      
echo "                                                                        "
echo -e "${NC}"

# OpenAlgo Installation and Configuration Script



# Create logs directory if it doesn't exist
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOGS_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOGS_DIR"

# Generate unique log file name for this deployment
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOGS_DIR/install_${TIMESTAMP}.log"

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

# Function to check current timezone
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

# Function to generate random hex string
generate_hex() {
    python3 -c "import secrets; print(secrets.token_hex(32))"
}




# Function to validate broker name
validate_broker() {
    local broker=$1

    local valid_brokers="fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,definedge,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,ibulls,iifl,indmoney,kotak,paytm,pocketful,shoonya,tradejini,upstox,wisdom,zebu,zerodha"

    if [[ $valid_brokers == *"$broker"* ]]; then
        return 0
    else
        return 1
    fi
}

# Function to check if broker is XTS based
is_xts_broker() {
    local broker=$1
    local xts_brokers="fivepaisaxts,compositedge,ibulls,iifl,wisdom"
    if [[ $xts_brokers == *"$broker"* ]]; then
        return 0
    else
        return 1
    fi
}

# Function to check and handle existing files/directories
handle_existing() {
    local path=$1
    local type=$2
    local name=$3

    if [ -e "$path" ]; then
        log_message "Warning: $name already exists at $path" "$YELLOW"
        read -p "Would you like to backup the existing $type? (y/n): " backup_choice
        if [[ $backup_choice =~ ^[Yy]$ ]]; then
            backup_path="${path}_backup_$(date +%Y%m%d_%H%M%S)"
            log_message "Creating backup at $backup_path" "$BLUE"
            sudo mv "$path" "$backup_path"
            check_status "Failed to create backup of $name"
            return 0
        else
            read -p "Would you like to remove the existing $type? (y/n): " remove_choice
            if [[ $remove_choice =~ ^[Yy]$ ]]; then
                log_message "Removing existing $type..." "$BLUE"
                if [ -d "$path" ]; then
                    sudo rm -rf "$path"
                else
                    sudo rm -f "$path"
                fi
                check_status "Failed to remove existing $type"
                return 0
            else
                log_message "Installation cannot proceed without handling existing $type" "$RED"
                exit 1
            fi
        fi
    fi
    return 0
}

# Function to check and configure swap memory
check_and_configure_swap() {
    # Get total RAM in MB
    TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    TOTAL_RAM_MB=$((TOTAL_RAM_KB / 1024))
    TOTAL_RAM_GB=$((TOTAL_RAM_MB / 1024))
    
    log_message "System RAM: ${TOTAL_RAM_MB}MB (${TOTAL_RAM_GB}GB)" "$BLUE"
    
    # Check if RAM is less than 2GB
    if [ $TOTAL_RAM_MB -lt 2048 ]; then
        log_message "System has less than 2GB RAM. Checking swap configuration..." "$YELLOW"
        
        # Check current swap
        SWAP_TOTAL=$(free -m | grep Swap | awk '{print $2}')
        log_message "Current swap: ${SWAP_TOTAL}MB" "$BLUE"
        
        if [ $SWAP_TOTAL -lt 3072 ]; then
            log_message "Insufficient swap memory. Creating 3GB swap file..." "$YELLOW"
            
            # Check available disk space
            AVAILABLE_SPACE=$(df / | tail -1 | awk '{print $4}')
            REQUIRED_SPACE=3145728  # 3GB in KB
            
            if [ $AVAILABLE_SPACE -lt $REQUIRED_SPACE ]; then
                log_message "Error: Not enough disk space for swap file" "$RED"
                log_message "Available: ${AVAILABLE_SPACE}KB, Required: ${REQUIRED_SPACE}KB" "$RED"
                exit 1
            fi
            
            # Create swap file
            log_message "Creating 3GB swap file at /swapfile..." "$BLUE"
            sudo fallocate -l 3G /swapfile
            if [ $? -ne 0 ]; then
                # Fallback to dd if fallocate fails
                log_message "fallocate failed, using dd instead..." "$YELLOW"
                sudo dd if=/dev/zero of=/swapfile bs=1M count=3072 status=progress
            fi
            check_status "Failed to create swap file"
            
            # Set permissions
            sudo chmod 600 /swapfile
            check_status "Failed to set swap file permissions"
            
            # Setup swap
            sudo mkswap /swapfile
            check_status "Failed to setup swap"
            
            # Enable swap
            sudo swapon /swapfile
            check_status "Failed to enable swap"
            
            # Make swap permanent
            if ! grep -q "/swapfile" /etc/fstab; then
                echo "/swapfile none swap sw 0 0" | sudo tee -a /etc/fstab
                log_message "Swap file added to /etc/fstab for persistence" "$GREEN"
            fi
            
            # Verify swap is active
            NEW_SWAP=$(free -m | grep Swap | awk '{print $2}')
            log_message "Swap configured successfully. Total swap: ${NEW_SWAP}MB" "$GREEN"
            
            # Configure swappiness for better performance
            sudo sysctl vm.swappiness=10
            echo "vm.swappiness=10" | sudo tee -a /etc/sysctl.conf
            log_message "Swappiness set to 10 for better performance" "$GREEN"
        else
            log_message "Sufficient swap already exists: ${SWAP_TOTAL}MB" "$GREEN"
        fi
    else
        log_message "System has sufficient RAM (${TOTAL_RAM_GB}GB)" "$GREEN"
        
        # Still check swap for optimal performance
        SWAP_TOTAL=$(free -m | grep Swap | awk '{print $2}')
        if [ $SWAP_TOTAL -eq 0 ]; then
            log_message "No swap configured. Consider adding swap for optimal performance." "$YELLOW"
        else
            log_message "Swap configured: ${SWAP_TOTAL}MB" "$GREEN"
        fi
    fi
}

# Start logging
log_message "Starting OpenAlgo installation log at: $LOG_FILE" "$BLUE"
log_message "----------------------------------------" "$BLUE"

# Check system requirements (RAM and swap)
log_message "Checking system requirements..." "$BLUE"
check_and_configure_swap

# Check timezone before proceeding with installation
check_timezone

# Collect installation parameters
log_message "OpenAlgo Installation Configuration" "$BLUE"
log_message "----------------------------------------" "$BLUE"

# Get domain name
while true; do
    read -p "Enter your domain name (e.g., yourdomain.com or sub.yourdomain.com): " DOMAIN
    if [ -z "$DOMAIN" ]; then
        log_message "Error: Domain name is required" "$RED"
        continue
    fi
    # Domain validation that accepts subdomains
    if [[ ! $DOMAIN =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$ ]]; then
        log_message "Error: Invalid domain format. Please enter a valid domain name" "$RED"
        continue
    fi

    # Check if it's a subdomain
    if [[ $DOMAIN =~ ^[^.]+\.[^.]+\.[^.]+$ ]]; then
        IS_SUBDOMAIN=true
    else
        IS_SUBDOMAIN=false
    fi
    break
done

# Get broker name
while true; do

    log_message "\nValid brokers: fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,definedge,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,ibulls,iifl,indmoney,kotak,paytm,pocketful,shoonya,tradejini,upstox,wisdom,zebu,zerodha" "$BLUE"

    read -p "Enter your broker name: " BROKER_NAME
    if validate_broker "$BROKER_NAME"; then
        break
    else
        log_message "Invalid broker name. Please choose from the list above." "$RED"
    fi
done

# Show redirect URL for broker setup
log_message "\nRedirect URL for broker developer portal:" "$YELLOW"
log_message "https://$DOMAIN/$BROKER_NAME/callback" "$GREEN"
log_message "\nPlease use this URL in your broker's developer portal to generate API credentials." "$BLUE"
log_message "Once you have the credentials, you can proceed with the installation." "$BLUE"
echo ""

# Get broker API credentials
read -p "Enter your broker API key: " BROKER_API_KEY
read -p "Enter your broker API secret: " BROKER_API_SECRET

if [ -z "$BROKER_API_KEY" ] || [ -z "$BROKER_API_SECRET" ]; then
    log_message "Error: Broker API credentials are required" "$RED"
    exit 1
fi

# Check if the broker is XTS-based and ask for additional credentials if needed
BROKER_API_KEY_MARKET=""
BROKER_API_SECRET_MARKET=""
if is_xts_broker "$BROKER_NAME"; then
    log_message "\nThis broker ($BROKER_NAME) is XTS API-based and requires additional market data credentials." "$YELLOW"
    read -p "Enter your broker market data API key: " BROKER_API_KEY_MARKET
    read -p "Enter your broker market data API secret: " BROKER_API_SECRET_MARKET
    
    if [ -z "$BROKER_API_KEY_MARKET" ] || [ -z "$BROKER_API_SECRET_MARKET" ]; then
        log_message "Error: Market data API credentials are required for XTS-based brokers" "$RED"
        exit 1
    fi
fi

# Generate random keys
APP_KEY=$(generate_hex)
API_KEY_PEPPER=$(generate_hex)

# Installation paths with unique deployment name
DEPLOY_NAME="${DOMAIN/./-}-${BROKER_NAME}"  # e.g., opendash-app-fyers
BASE_PATH="/var/python/openalgo-flask/$DEPLOY_NAME"
OPENALGO_PATH="$BASE_PATH/openalgo"
VENV_PATH="$BASE_PATH/venv"
SOCKET_PATH="$BASE_PATH"
SOCKET_FILE="$SOCKET_PATH/openalgo.sock"
SERVICE_NAME="openalgo-$DEPLOY_NAME"

log_message "\nStarting OpenAlgo installation for $DEPLOY_NAME..." "$YELLOW"

# Update system packages
log_message "\nUpdating system packages..." "$BLUE"
sudo apt-get update && sudo apt-get upgrade -y
check_status "Failed to update system packages"

# Install required packages including Certbot
log_message "\nInstalling required packages..." "$BLUE"
sudo apt-get install -y python3 python3-venv python3-pip python3-full nginx git software-properties-common snapd
check_status "Failed to install required packages"

# Install uv using snap (global installation)
log_message "\nInstalling uv package installer using snap..." "$BLUE"
sudo snap install astral-uv --classic
check_status "Failed to install uv via snap"

# Install Certbot
log_message "\nInstalling Certbot..." "$BLUE"
sudo apt-get install -y certbot python3-certbot-nginx
check_status "Failed to install Certbot"

# Check and handle existing OpenAlgo installation
handle_existing "$BASE_PATH" "installation directory" "OpenAlgo directory for $DEPLOY_NAME"

# Create base directory
log_message "\nCreating base directory..." "$BLUE"
sudo mkdir -p $BASE_PATH
check_status "Failed to create base directory"

# Clone repository
log_message "\nCloning OpenAlgo repository..." "$BLUE"
sudo git clone https://github.com/marketcalls/openalgo.git $OPENALGO_PATH
check_status "Failed to clone OpenAlgo repository"

# Create virtual environment using uv
log_message "\nSetting up Python virtual environment with uv..." "$BLUE"
if [ -d "$VENV_PATH" ]; then
    log_message "Warning: Virtual environment already exists, removing..." "$YELLOW"
    sudo rm -rf "$VENV_PATH"
fi
# Create directory if it doesn't exist
sudo mkdir -p $(dirname $VENV_PATH)
# Create virtual environment using uv
sudo uv venv $VENV_PATH
check_status "Failed to create virtual environment with uv"

# Install Python dependencies using uv (faster installation)
log_message "\nInstalling Python dependencies with uv..." "$BLUE"
# First activate the virtual environment path for uv
ACTIVATE_CMD="source $VENV_PATH/bin/activate"
# Install dependencies using uv within the virtual environment context
sudo bash -c "$ACTIVATE_CMD && uv pip install -r $OPENALGO_PATH/requirements-nginx.txt"
check_status "Failed to install Python dependencies"

# Verify gunicorn and eventlet installation
log_message "\nVerifying gunicorn and eventlet installation..." "$BLUE"
if ! sudo bash -c "$ACTIVATE_CMD && pip freeze | grep -q 'gunicorn=='"; then
    log_message "Installing gunicorn..." "$YELLOW"
    sudo bash -c "$ACTIVATE_CMD && uv pip install gunicorn"
    check_status "Failed to install gunicorn"
fi
if ! sudo bash -c "$ACTIVATE_CMD && pip freeze | grep -q 'eventlet=='"; then
    log_message "Installing eventlet..." "$YELLOW"
    sudo bash -c "$ACTIVATE_CMD && uv pip install eventlet"
    check_status "Failed to install eventlet"
fi

# Configure .env file
log_message "\nConfiguring environment file..." "$BLUE"
handle_existing "$OPENALGO_PATH/.env" "environment file" ".env file"

sudo cp $OPENALGO_PATH/.sample.env $OPENALGO_PATH/.env
sudo sed -i "s|YOUR_BROKER_API_KEY|$BROKER_API_KEY|g" $OPENALGO_PATH/.env
sudo sed -i "s|YOUR_BROKER_API_SECRET|$BROKER_API_SECRET|g" $OPENALGO_PATH/.env

# Update market data API credentials if the broker is XTS-based
if is_xts_broker "$BROKER_NAME"; then
    sudo sed -i "s|YOUR_BROKER_MARKET_API_KEY|$BROKER_API_KEY_MARKET|g" $OPENALGO_PATH/.env
    sudo sed -i "s|YOUR_BROKER_MARKET_API_SECRET|$BROKER_API_SECRET_MARKET|g" $OPENALGO_PATH/.env
fi

sudo sed -i "s|http://127.0.0.1:5000|https://$DOMAIN|g" $OPENALGO_PATH/.env
sudo sed -i "s|<broker>|$BROKER_NAME|g" $OPENALGO_PATH/.env
sudo sed -i "s|3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952e93d88bf07ea84|$APP_KEY|g" $OPENALGO_PATH/.env
sudo sed -i "s|a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772|$API_KEY_PEPPER|g" $OPENALGO_PATH/.env

# Update WebSocket URL for production
sudo sed -i "s|WEBSOCKET_URL='.*'|WEBSOCKET_URL='wss://$DOMAIN/ws'|g" $OPENALGO_PATH/.env

check_status "Failed to configure environment file"

# Check and handle existing Nginx configuration
handle_existing "/etc/nginx/sites-available/$DOMAIN" "Nginx configuration" "Nginx config file"

# Configure initial Nginx for SSL certificate obtention
log_message "\nConfiguring initial Nginx setup..." "$BLUE"
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

# Enable site and remove default configuration
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/$DOMAIN /etc/nginx/sites-enabled/
check_status "Failed to enable Nginx site"

# Reload Nginx for initial configuration
log_message "\nTesting and reloading Nginx..." "$BLUE"
sudo nginx -t && sudo systemctl reload nginx
check_status "Failed to reload Nginx"

# Configure UFW firewall
log_message "\nConfiguring firewall rules..." "$BLUE"
sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
check_status "Failed to configure firewall"

# Obtain SSL certificate
log_message "\nObtaining SSL certificate..." "$BLUE"
if [ "$IS_SUBDOMAIN" = true ]; then
    sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email admin@${DOMAIN#*.}
else
    sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN
fi
check_status "Failed to obtain SSL certificate"

# Configure final Nginx setup with SSL and socket
log_message "\nConfiguring final Nginx setup..." "$BLUE"
sudo tee /etc/nginx/sites-available/$DOMAIN > /dev/null << EOL
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

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

# Test Nginx configuration
log_message "\nTesting Nginx configuration..." "$BLUE"
sudo nginx -t
check_status "Failed to validate Nginx configuration"

# Check and handle existing systemd service
handle_existing "/etc/systemd/system/$SERVICE_NAME.service" "systemd service" "OpenAlgo service file"

# Create systemd service with unique name
log_message "\nCreating systemd service..." "$BLUE"
sudo tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null << EOL
[Unit]
Description=OpenAlgo Gunicorn Daemon ($DEPLOY_NAME)
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=$OPENALGO_PATH
# Simplified approach to ensure Python environment is properly loaded
ExecStart=/bin/bash -c 'source $VENV_PATH/bin/activate && $VENV_PATH/bin/gunicorn \
    --worker-class eventlet \
    -w 1 \
    --bind unix:$SOCKET_FILE \
    --log-level info \
    app:app'
# Restart settings
Restart=always
RestartSec=5
TimeoutSec=60

[Install]
WantedBy=multi-user.target
EOL
check_status "Failed to create systemd service"

# Set correct permissions
log_message "\nSetting permissions..." "$BLUE"

# Set permissions for base directory
sudo chown -R www-data:www-data $BASE_PATH
sudo chmod -R 755 $BASE_PATH

# Create and set permissions for required directories
sudo mkdir -p $OPENALGO_PATH/db
sudo mkdir -p $OPENALGO_PATH/tmp
# Create directories for Python strategy feature
sudo mkdir -p $OPENALGO_PATH/strategies/scripts
sudo mkdir -p $OPENALGO_PATH/log/strategies
sudo mkdir -p $OPENALGO_PATH/keys
# Set ownership and permissions
sudo chown -R www-data:www-data $OPENALGO_PATH
sudo chmod -R 755 $OPENALGO_PATH
# Set more restrictive permissions for sensitive directories
sudo chmod 700 $OPENALGO_PATH/keys

# Remove existing socket file if it exists
[ -S "$SOCKET_FILE" ] && sudo rm -f $SOCKET_FILE

# Verify permissions
log_message "\nVerifying permissions..." "$BLUE"
ls -la $OPENALGO_PATH
check_status "Failed to set permissions"

# Reload systemd and start services
log_message "\nStarting services..." "$BLUE"
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
sudo systemctl start $SERVICE_NAME
sudo systemctl restart nginx
check_status "Failed to start services"

log_message "\nInstallation completed successfully!" "$GREEN"
log_message "\nInstallation Summary:" "$YELLOW"
log_message "Deployment Name: $DEPLOY_NAME" "$BLUE"
log_message "Domain: $DOMAIN" "$BLUE"
log_message "Broker: $BROKER_NAME" "$BLUE"
log_message "Installation Directory: $OPENALGO_PATH" "$BLUE"
log_message "Environment File: $OPENALGO_PATH/.env" "$BLUE"
log_message "Socket File: $SOCKET_FILE" "$BLUE"
log_message "Service Name: $SERVICE_NAME" "$BLUE"
log_message "Nginx Config: /etc/nginx/sites-available/$DOMAIN" "$BLUE"
log_message "SSL: Enabled with Let's Encrypt" "$BLUE"
log_message "Installation Log: $LOG_FILE" "$BLUE"

log_message "\nNext Steps:" "$YELLOW"
log_message "1. Visit https://$DOMAIN to access your OpenAlgo instance" "$GREEN"
log_message "2. Configure your broker settings in the web interface" "$GREEN"
log_message "3. Review the logs using: sudo journalctl -u $SERVICE_NAME" "$GREEN"
log_message "4. Monitor the application status: sudo systemctl status $SERVICE_NAME" "$GREEN"

log_message "\nUseful Commands:" "$YELLOW"
log_message "Restart OpenAlgo: sudo systemctl restart $SERVICE_NAME" "$BLUE"
log_message "View Logs: sudo journalctl -u $SERVICE_NAME" "$BLUE"
log_message "Check Status: sudo systemctl status $SERVICE_NAME" "$BLUE"
log_message "View Installation Log: cat $LOG_FILE" "$BLUE"
