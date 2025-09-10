#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# OpenAlgo Installation Banner
echo -e "${BLUE}"
echo "  ██████╗ ██████╗ ███████╗███╗   ██╗ █████╗ ██╗      ██████╗  ██████╗ "
echo " ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║     ██╔════╝ ██╔═══██╗"
echo " ██║   ██║██████╔╝███████╗██╔██╗ ██║███████║██║     ██║  ███╗██║   ██║"
echo " ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██║██║     ██║   ██║██║   ██║"
echo " ╚██████╔╝██╗     ███████╗██║ ╚████║██║  ██║███████╗╚██████╔╝╚██████╔╝"
echo "  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝ "      
echo "                                                                        "
echo -e "${NC}"
echo -e "${YELLOW}Simple HTTP Installation (No Nginx)${NC}"
echo ""

# Create logs directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOGS_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOGS_DIR"

# Log file
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOGS_DIR/install_${TIMESTAMP}.log"

# Function to log messages
log_message() {
    local message="$1"
    local color="$2"
    echo -e "${color}${message}${NC}" | tee -a "$LOG_FILE"
}

# Function to check status
check_status() {
    if [ $? -ne 0 ]; then
        log_message "Error: $1" "$RED"
        exit 1
    fi
}

# Function to generate random hex
generate_hex() {
    python3 -c "import secrets; print(secrets.token_hex(32))"
}

# Function to validate broker
validate_broker() {
    local broker=$1
    local valid_brokers="fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,iifl,kotak,jainam,jainampro,paytm,pocketful,shoonya,tradejini,upstox,wisdom,zebu,zerodha"
    if [[ $valid_brokers == *"$broker"* ]]; then
        return 0
    else
        return 1
    fi
}

# Function to check XTS broker
is_xts_broker() {
    local broker=$1
    local xts_brokers="fivepaisaxts,compositedge,iifl,jainam,jainampro,wisdom"
    if [[ $xts_brokers == *"$broker"* ]]; then
        return 0
    else
        return 1
    fi
}

# Function to wait for apt locks to be released
wait_for_apt() {
    while sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || sudo fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do
        log_message "Waiting for other package managers to finish..." "$YELLOW"
        sleep 5
    done
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

# Get server IP
SERVER_IP=$(ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v '127.0.0.1' | head -n1)
if [ -z "$SERVER_IP" ]; then
    log_message "Could not detect server IP automatically" "$YELLOW"
    read -p "Please enter your server IP address: " SERVER_IP
fi

# Start logging
log_message "Starting OpenAlgo Simple HTTP installation" "$BLUE"
log_message "Server IP: $SERVER_IP" "$BLUE"
log_message "----------------------------------------" "$BLUE"

# Check system requirements (RAM and swap)
log_message "Checking system requirements..." "$BLUE"
check_and_configure_swap

# Check timezone before proceeding
check_timezone

# Get broker configuration FIRST
log_message "\nOpenAlgo Configuration" "$BLUE"
log_message "----------------------------------------" "$BLUE"

# Get broker name
while true; do
    log_message "\nValid brokers: fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,iifl,kotak,jainam,jainampro,paytm,pocketful,shoonya,tradejini,upstox,wisdom,zebu,zerodha" "$BLUE"
    read -p "Enter your broker name: " BROKER_NAME
    if validate_broker "$BROKER_NAME"; then
        break
    else
        log_message "Invalid broker name. Please choose from the list above." "$RED"
    fi
done

# Show redirect URL
log_message "\nRedirect URL for broker developer portal:" "$YELLOW"
log_message "http://$SERVER_IP/$BROKER_NAME/callback" "$GREEN"
log_message "\nPlease use this URL in your broker's developer portal to generate API credentials." "$BLUE"
log_message "Once you have the credentials, you can proceed with the installation." "$BLUE"
echo ""

# Get API credentials
read -p "Enter your broker API key: " BROKER_API_KEY
read -p "Enter your broker API secret: " BROKER_API_SECRET

if [ -z "$BROKER_API_KEY" ] || [ -z "$BROKER_API_SECRET" ]; then
    log_message "Error: Broker API credentials are required" "$RED"
    exit 1
fi

# Check for XTS broker
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

# Generate keys
APP_KEY=$(generate_hex)
API_KEY_PEPPER=$(generate_hex)

# Now proceed with installation
log_message "\nStarting OpenAlgo installation..." "$YELLOW"

# Basic security setup
log_message "\nApplying basic security settings..." "$BLUE"

# Wait for any running package managers to finish
wait_for_apt

# Update system
log_message "Updating system packages..." "$BLUE"
sudo apt-get update && sudo apt-get upgrade -y
check_status "Failed to update system"

# Install essential packages
log_message "Installing essential packages..." "$BLUE"
wait_for_apt
sudo apt-get install -y python3 python3-venv python3-pip python3-full git ufw fail2ban snapd software-properties-common
check_status "Failed to install packages"

# Install uv using snap for faster package installation
log_message "Installing uv package manager..." "$BLUE"
wait_for_apt
sudo snap install astral-uv --classic
check_status "Failed to install uv"

# Configure UFW firewall
log_message "Setting up firewall..." "$BLUE"
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 80/tcp
sudo ufw allow 8765/tcp  # WebSocket port
sudo ufw --force enable
check_status "Failed to configure firewall"

# Basic fail2ban configuration
log_message "Configuring fail2ban..." "$BLUE"
cat << EOF | sudo tee /etc/fail2ban/jail.local
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
EOF

sudo systemctl restart fail2ban
check_status "Failed to configure fail2ban"

# Installation paths
BASE_PATH="/var/python/openalgo"
VENV_PATH="$BASE_PATH/venv"
SERVICE_NAME="openalgo"

# Check existing installation
if [ -d "$BASE_PATH" ]; then
    log_message "Warning: OpenAlgo already installed at $BASE_PATH" "$YELLOW"
    read -p "Remove existing installation? (y/n): " remove_choice
    if [[ $remove_choice =~ ^[Yy]$ ]]; then
        log_message "Removing existing installation..." "$BLUE"
        sudo systemctl stop $SERVICE_NAME 2>/dev/null
        sudo systemctl disable $SERVICE_NAME 2>/dev/null
        sudo rm -rf "$BASE_PATH"
    else
        log_message "Installation aborted" "$RED"
        exit 1
    fi
fi

# Create directory structure
log_message "\nCreating installation directory..." "$BLUE"
sudo mkdir -p /var/python
sudo mkdir -p $BASE_PATH
check_status "Failed to create directory"

# Clone repository
log_message "Cloning OpenAlgo repository..." "$BLUE"
sudo git clone https://github.com/marketcalls/openalgo.git $BASE_PATH
check_status "Failed to clone repository"

# Create virtual environment using uv
log_message "Creating Python virtual environment with uv..." "$BLUE"
sudo uv venv $VENV_PATH
check_status "Failed to create virtual environment"

# Install dependencies using uv (much faster)
log_message "Installing Python dependencies with uv..." "$BLUE"
ACTIVATE_CMD="source $VENV_PATH/bin/activate"
sudo bash -c "$ACTIVATE_CMD && uv pip install -r $BASE_PATH/requirements-nginx.txt"
check_status "Failed to install dependencies"

# Ensure gunicorn and eventlet are installed
log_message "Ensuring gunicorn and eventlet are installed..." "$BLUE"
sudo bash -c "$ACTIVATE_CMD && uv pip install gunicorn eventlet"
check_status "Failed to install gunicorn/eventlet"

# Configure .env file
log_message "Configuring environment..." "$BLUE"
sudo cp $BASE_PATH/.sample.env $BASE_PATH/.env
sudo sed -i "s|YOUR_BROKER_API_KEY|$BROKER_API_KEY|g" $BASE_PATH/.env
sudo sed -i "s|YOUR_BROKER_API_SECRET|$BROKER_API_SECRET|g" $BASE_PATH/.env

# Update market data credentials for XTS
if is_xts_broker "$BROKER_NAME"; then
    sudo sed -i "s|YOUR_BROKER_MARKET_API_KEY|$BROKER_API_KEY_MARKET|g" $BASE_PATH/.env
    sudo sed -i "s|YOUR_BROKER_MARKET_API_SECRET|$BROKER_API_SECRET_MARKET|g" $BASE_PATH/.env
fi

sudo sed -i "s|http://127.0.0.1:5000|http://$SERVER_IP|g" $BASE_PATH/.env
sudo sed -i "s|<broker>|$BROKER_NAME|g" $BASE_PATH/.env
sudo sed -i "s|3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952e93d88bf07ea84|$APP_KEY|g" $BASE_PATH/.env
sudo sed -i "s|a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772|$API_KEY_PEPPER|g" $BASE_PATH/.env

# Update WebSocket URL for IP-based deployment
sudo sed -i "s|WEBSOCKET_URL='.*'|WEBSOCKET_URL='ws://$SERVER_IP:8765'|g" $BASE_PATH/.env

check_status "Failed to configure environment"

# Create systemd service
log_message "Creating systemd service..." "$BLUE"
sudo tee /etc/systemd/system/$SERVICE_NAME.service > /dev/null << EOL
[Unit]
Description=OpenAlgo Trading Platform
After=network.target

[Service]
Type=exec
User=www-data
Group=www-data
WorkingDirectory=$BASE_PATH
Environment="PATH=$VENV_PATH/bin"
ExecStart=$VENV_PATH/bin/gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:80 --timeout 120 app:app
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOL
check_status "Failed to create service"

# Create required directories for all features
log_message "Creating required directories..." "$BLUE"
sudo mkdir -p $BASE_PATH/db
sudo mkdir -p $BASE_PATH/tmp
# Create directories for Python strategy feature
sudo mkdir -p $BASE_PATH/strategies/scripts
sudo mkdir -p $BASE_PATH/log/strategies
sudo mkdir -p $BASE_PATH/keys

# Set correct permissions
log_message "Setting permissions..." "$BLUE"

# Set ownership to www-data (web server user)
sudo chown -R www-data:www-data $BASE_PATH
sudo chmod -R 755 $BASE_PATH

# Set more restrictive permissions for sensitive directories
sudo chmod 700 $BASE_PATH/keys

# Ensure virtual environment has correct permissions
sudo chown -R www-data:www-data $VENV_PATH
sudo chmod -R 755 $VENV_PATH

# Grant capability to bind to port 80
log_message "Granting permission to bind to port 80..." "$BLUE"
# Find the real python executable (not symlink)
REAL_PYTHON=$(readlink -f $VENV_PATH/bin/python3)
sudo setcap 'cap_net_bind_service=+ep' $REAL_PYTHON
check_status "Failed to set port binding capability"

# Verify permissions
log_message "Verifying permissions..." "$BLUE"
ls -la $BASE_PATH
check_status "Failed to set permissions"

# Start service
log_message "Starting OpenAlgo service..." "$BLUE"
sudo systemctl daemon-reload
sudo systemctl enable $SERVICE_NAME
sudo systemctl start $SERVICE_NAME
check_status "Failed to start service"

# Wait for service to start
sleep 3

# Check if service is running
if sudo systemctl is-active --quiet $SERVICE_NAME; then
    log_message "\nOpenAlgo is running successfully!" "$GREEN"
else
    log_message "\nWarning: Service may not have started properly" "$YELLOW"
    log_message "Check logs with: sudo journalctl -u $SERVICE_NAME -n 50" "$YELLOW"
fi

# Installation complete
log_message "\n========================================" "$GREEN"
log_message "Installation Complete!" "$GREEN"
log_message "========================================" "$GREEN"

log_message "\nAccess Details:" "$YELLOW"
log_message "URL: http://$SERVER_IP" "$GREEN"
log_message "Broker: $BROKER_NAME" "$GREEN"
log_message "Installation: $BASE_PATH" "$GREEN"

log_message "\nSecurity Status:" "$YELLOW"
log_message "✓ Firewall: Enabled (SSH + HTTP)" "$GREEN"
log_message "✓ Fail2ban: Active (SSH protection)" "$GREEN"
log_message "✓ Service: Running as isolated systemd unit" "$GREEN"

log_message "\nUseful Commands:" "$YELLOW"
log_message "View logs: sudo journalctl -u $SERVICE_NAME -f" "$BLUE"
log_message "Restart: sudo systemctl restart $SERVICE_NAME" "$BLUE"
log_message "Status: sudo systemctl status $SERVICE_NAME" "$BLUE"
log_message "Firewall: sudo ufw status" "$BLUE"
log_message "Fail2ban: sudo fail2ban-client status sshd" "$BLUE"

log_message "\nRecommendations:" "$YELLOW"
log_message "1. Test the installation by visiting http://$SERVER_IP" "$BLUE"
log_message "2. Monitor logs for any errors" "$BLUE"
log_message "3. Consider using a reverse proxy for production" "$BLUE"
log_message "4. Set up regular backups of $BASE_PATH/db" "$BLUE"

log_message "\nLog saved to: $LOG_FILE" "$GREEN"