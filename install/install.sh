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

# Function to wait for dpkg lock to be released (Ubuntu/Debian)
wait_for_dpkg_lock() {
    local max_wait=300  # 5 minutes max wait
    local waited=0

    while sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || \
          sudo fuser /var/lib/dpkg/lock >/dev/null 2>&1 || \
          sudo fuser /var/lib/apt/lists/lock >/dev/null 2>&1; do

        if [ $waited -eq 0 ]; then
            log_message "Package manager is locked (unattended-upgrades running)" "$YELLOW"
            log_message "Waiting for it to complete... (max 5 minutes)" "$YELLOW"
        fi

        if [ $waited -ge $max_wait ]; then
            log_message "Timeout waiting for package manager lock" "$RED"
            log_message "Please run: sudo killall unattended-upgr && sudo rm /var/lib/dpkg/lock*" "$YELLOW"
            exit 1
        fi

        printf "."
        sleep 5
        waited=$((waited + 5))
    done

    if [ $waited -gt 0 ]; then
        echo ""
        log_message "Package manager is now available" "$GREEN"
    fi
}

# Function to generate random hex string
generate_hex() {
    $PYTHON_CMD -c "import secrets; print(secrets.token_hex(32))"
}




# Function to validate broker name
validate_broker() {
    local broker=$1

    local valid_brokers="fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,definedge,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,ibulls,iifl,indmoney,kotak,motilal,paytm,pocketful,shoonya,tradejini,upstox,wisdom,zebu,zerodha"

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

# Detect OS type and version
OS_TYPE=$(grep -w "ID" /etc/os-release | cut -d "=" -f 2 | tr -d '"')

# Handle OS variants - map to base distributions
case "$OS_TYPE" in
    "pop")
        OS_TYPE="ubuntu"
        log_message "Detected Pop!_OS, using Ubuntu packages" "$BLUE"
        ;;
    "linuxmint")
        OS_TYPE="ubuntu"
        log_message "Detected Linux Mint, using Ubuntu packages" "$BLUE"
        ;;
    "zorin")
        OS_TYPE="ubuntu"
        log_message "Detected Zorin OS, using Ubuntu packages" "$BLUE"
        ;;
    "manjaro" | "manjaro-arm" | "endeavouros" | "cachyos")
        OS_TYPE="arch"
        log_message "Detected $OS_TYPE, using Arch Linux packages" "$BLUE"
        ;;
    "rocky" | "almalinux" | "ol")
        OS_TYPE="rhel"
        log_message "Detected $OS_TYPE, using RHEL-compatible packages" "$BLUE"
        ;;
esac

# Get OS version
if [ "$OS_TYPE" = "arch" ]; then
    OS_VERSION="rolling"
else
    OS_VERSION=$(grep -w "VERSION_ID" /etc/os-release | cut -d "=" -f 2 | tr -d '"')
fi

# Validate supported OS
case "$OS_TYPE" in
    arch | ubuntu | debian | raspbian | centos | fedora | rhel | rocky | almalinux | amzn)
        log_message "Detected OS: $OS_TYPE $OS_VERSION" "$GREEN"
        ;;
    *)
        log_message "Error: Unsupported operating system: $OS_TYPE" "$RED"
        log_message "Supported: Ubuntu, Debian, Raspbian, CentOS, Fedora, RHEL, Rocky, AlmaLinux, Amazon Linux, Arch Linux" "$YELLOW"
        exit 1
        ;;
esac

# Detect web server user and Python command based on OS
case "$OS_TYPE" in
    ubuntu | debian | raspbian)
        WEB_USER="www-data"
        WEB_GROUP="www-data"
        PYTHON_CMD="python3"
        ;;
    centos | fedora | rhel | amzn)
        WEB_USER="nginx"
        WEB_GROUP="nginx"
        PYTHON_CMD="python3"
        ;;
    arch)
        WEB_USER="http"
        WEB_GROUP="http"
        PYTHON_CMD="python"
        ;;
esac

log_message "Web server user: $WEB_USER:$WEB_GROUP" "$BLUE"
log_message "Python command: $PYTHON_CMD" "$BLUE"

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

    log_message "\nValid brokers: fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,definedge,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,ibulls,iifl,indmoney,kotak,motilal,paytm,pocketful,shoonya,tradejini,upstox,wisdom,zebu,zerodha" "$BLUE"

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

# Set Nginx configuration paths based on OS
case "$OS_TYPE" in
    ubuntu | debian | raspbian)
        NGINX_AVAILABLE="/etc/nginx/sites-available"
        NGINX_ENABLED="/etc/nginx/sites-enabled"
        NGINX_CONFIG_MODE="sites"
        ;;
    centos | fedora | rhel | amzn | arch)
        NGINX_AVAILABLE="/etc/nginx/conf.d"
        NGINX_ENABLED="/etc/nginx/conf.d"
        NGINX_CONFIG_MODE="confd"
        # Create conf.d directory if it doesn't exist (Arch Linux)
        sudo mkdir -p "$NGINX_AVAILABLE"
        ;;
esac
NGINX_CONFIG_FILE="$NGINX_AVAILABLE/$DOMAIN.conf"

log_message "\nStarting OpenAlgo installation for $DEPLOY_NAME..." "$YELLOW"

# Update system packages
log_message "\nUpdating system packages..." "$BLUE"
case "$OS_TYPE" in
    ubuntu | debian | raspbian)
        # Wait for any running package manager operations to complete
        wait_for_dpkg_lock
        sudo apt-get update && sudo apt-get upgrade -y
        check_status "Failed to update system packages"
        ;;
    centos | fedora | rhel | amzn)
        if ! command -v dnf >/dev/null 2>&1; then
            sudo yum update -y
        else
            sudo dnf update -y
        fi
        check_status "Failed to update system packages"
        ;;
    arch)
        sudo pacman -Syu --noconfirm
        check_status "Failed to update system packages"
        ;;
esac

# Install required packages including Certbot
log_message "\nInstalling required packages..." "$BLUE"
case "$OS_TYPE" in
    ubuntu | debian | raspbian)
        # Wait for any running package manager operations to complete
        wait_for_dpkg_lock
        sudo apt-get install -y python3 python3-venv python3-pip nginx git software-properties-common
        # Try to install python3-full if available (Ubuntu 23.04+)
        sudo apt-get install -y python3-full 2>/dev/null || log_message "python3-full not available, skipping" "$YELLOW"
        # Try to install snapd, but don't fail if unavailable
        sudo apt-get install -y snapd 2>/dev/null || log_message "snapd not available, will use pip for uv installation" "$YELLOW"
        check_status "Failed to install required packages"
        ;;
    centos | fedora | rhel | amzn)
        if ! command -v dnf >/dev/null 2>&1; then
            sudo yum install -y python3 python3-pip nginx git epel-release
            # Install SELinux management tools for RHEL-based systems
            sudo yum install -y policycoreutils-python-utils 2>/dev/null || log_message "SELinux tools already installed" "$YELLOW"
            # Try to install snapd, but don't fail if unavailable (we use pip for uv anyway)
            sudo yum install -y snapd 2>/dev/null || log_message "snapd not available, will use pip for uv installation" "$YELLOW"
        else
            # Install EPEL repository first for access to additional packages
            sudo dnf install -y epel-release 2>/dev/null || log_message "EPEL repository already installed or not available" "$YELLOW"
            sudo dnf install -y python3 python3-pip nginx git
            # Install SELinux management tools for RHEL-based systems
            sudo dnf install -y policycoreutils-python-utils 2>/dev/null || log_message "SELinux tools already installed" "$YELLOW"
            # Try to install snapd, but don't fail if unavailable (we use pip for uv anyway)
            sudo dnf install -y snapd 2>/dev/null || log_message "snapd not available, will use pip for uv installation" "$YELLOW"
        fi
        check_status "Failed to install required packages"
        # Enable and start snapd if it was successfully installed
        if command -v snap >/dev/null 2>&1; then
            sudo systemctl enable --now snapd.socket
        fi
        ;;
    arch)
        sudo pacman -Sy --noconfirm --needed python python-pip nginx git
        # Try to install snapd, but don't fail if unavailable (we use pip for uv anyway)
        sudo pacman -Sy --noconfirm --needed snapd 2>/dev/null || log_message "snapd not available, will use pip for uv installation" "$YELLOW"
        check_status "Failed to install required packages"
        # Enable and start snapd if it was successfully installed
        if command -v snap >/dev/null 2>&1; then
            sudo systemctl enable --now snapd.socket
        fi
        ;;
esac

# Install uv package installer
log_message "\nInstalling uv package installer..." "$BLUE"
case "$OS_TYPE" in
    ubuntu | debian | raspbian)
        # Use snap for Ubuntu/Debian (native support)
        if command -v snap >/dev/null 2>&1; then
            if [ ! -e /snap ] && [ -d /var/lib/snapd/snap ]; then
                sudo ln -s /var/lib/snapd/snap /snap
            fi
            sleep 2
            if sudo snap install astral-uv --classic 2>/dev/null; then
                log_message "uv installed via snap" "$GREEN"
            else
                log_message "Snap installation failed, using pip fallback" "$YELLOW"
                sudo $PYTHON_CMD -m pip install uv
            fi
        else
            sudo $PYTHON_CMD -m pip install uv
        fi
        check_status "Failed to install uv"
        ;;
    centos | fedora | rhel | amzn)
        # Use pip for RHEL (more reliable than snap)
        log_message "Installing uv via pip for better compatibility..." "$BLUE"
        sudo $PYTHON_CMD -m pip install uv
        check_status "Failed to install uv"
        ;;
    arch)
        # Try pacman first, then pip with --break-system-packages for Arch
        log_message "Installing uv for Arch Linux..." "$BLUE"
        if sudo pacman -Sy --noconfirm --needed python-uv 2>/dev/null; then
            log_message "uv installed via pacman" "$GREEN"
        else
            log_message "uv not available in pacman, using pip..." "$YELLOW"
            sudo $PYTHON_CMD -m pip install --break-system-packages uv
            check_status "Failed to install uv"
        fi
        ;;
esac

# Install Certbot
log_message "\nInstalling Certbot..." "$BLUE"
case "$OS_TYPE" in
    ubuntu | debian | raspbian)
        # Wait for any running package manager operations to complete
        wait_for_dpkg_lock
        sudo apt-get install -y certbot python3-certbot-nginx
        check_status "Failed to install Certbot"
        ;;
    centos | fedora | rhel | amzn)
        # Try to install from package manager first
        CERTBOT_INSTALLED=false
        if ! command -v dnf >/dev/null 2>&1; then
            if sudo yum install -y certbot python3-certbot-nginx >/dev/null 2>&1; then
                CERTBOT_INSTALLED=true
                log_message "Certbot installed via yum" "$GREEN"
            fi
        else
            if sudo dnf install -y certbot python3-certbot-nginx >/dev/null 2>&1; then
                CERTBOT_INSTALLED=true
                log_message "Certbot installed via dnf" "$GREEN"
            fi
        fi

        # If package manager installation failed, try snap
        if [ "$CERTBOT_INSTALLED" = false ]; then
            log_message "Certbot not available in repositories, trying snap installation..." "$YELLOW"
            if command -v snap >/dev/null 2>&1; then
                if sudo snap install --classic certbot >/dev/null 2>&1; then
                    CERTBOT_INSTALLED=true
                    # Create symlink if installed via snap
                    sudo ln -sf /snap/bin/certbot /usr/bin/certbot 2>/dev/null || true
                    log_message "Certbot installed via snap" "$GREEN"
                fi
            fi
        fi

        # If still not installed, use pip as last resort
        if [ "$CERTBOT_INSTALLED" = false ]; then
            log_message "Installing Certbot via pip..." "$YELLOW"
            sudo $PYTHON_CMD -m pip install certbot certbot-nginx >/dev/null 2>&1
            if [ $? -eq 0 ]; then
                CERTBOT_INSTALLED=true
                log_message "Certbot installed via pip" "$GREEN"
            fi
        fi

        if [ "$CERTBOT_INSTALLED" = false ]; then
            log_message "Failed to install Certbot via all methods" "$RED"
            exit 1
        fi
        ;;
    arch)
        sudo pacman -Sy --noconfirm --needed certbot certbot-nginx
        check_status "Failed to install Certbot"
        ;;
esac

# Verify certbot is accessible
if ! command -v certbot >/dev/null 2>&1; then
    log_message "Error: Certbot installation failed - command not found" "$RED"
    exit 1
fi
log_message "Certbot installed successfully" "$GREEN"

# Check if OpenAlgo installation already exists
if [ -d "$OPENALGO_PATH" ] && [ -d "$OPENALGO_PATH/.git" ]; then
    log_message "\nExisting OpenAlgo installation detected at $OPENALGO_PATH" "$YELLOW"
    read -p "Would you like to update the existing installation? (y/n): " update_choice
    if [[ $update_choice =~ ^[Yy]$ ]]; then
        log_message "Updating existing installation..." "$BLUE"
        
        # Get current commit
        cd "$OPENALGO_PATH"
        CURRENT_BRANCH=$(sudo -u $WEB_USER git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
        CURRENT_COMMIT=$(sudo -u $WEB_USER git rev-parse HEAD 2>/dev/null)
        
        log_message "Current branch: $CURRENT_BRANCH" "$BLUE"
        log_message "Current commit: ${CURRENT_COMMIT:0:8}..." "$BLUE"
        
        # Fetch latest changes
        log_message "Fetching latest changes..." "$BLUE"
        sudo -u $WEB_USER git fetch origin 2>&1
        check_status "Failed to fetch from remote"
        
        # Check for uncommitted changes
        if [ -n "$(sudo -u $WEB_USER git status --porcelain 2>/dev/null)" ]; then
            log_message "Warning: Uncommitted changes detected. Stashing changes..." "$YELLOW"
            sudo -u $WEB_USER git stash push -m "Auto-stash before install update $(date +%Y%m%d_%H%M%S)" 2>/dev/null || {
                log_message "Error: Could not stash changes. Please commit or discard changes manually." "$RED"
                exit 1
            }
        fi
        
        # Pull latest changes
        log_message "Pulling latest changes..." "$BLUE"
        sudo -u $WEB_USER git pull origin ${CURRENT_BRANCH:-main} 2>&1
        check_status "Failed to pull latest changes"
        
        # Restore stashed changes if any
        if sudo -u $WEB_USER git stash list | grep -q "Auto-stash before install update"; then
            log_message "Restoring stashed changes..." "$YELLOW"
            sudo -u $WEB_USER git stash pop 2>/dev/null || log_message "Warning: Could not restore stashed changes" "$YELLOW"
        fi
        
        NEW_COMMIT=$(sudo -u $WEB_USER git rev-parse HEAD)
        log_message "Updated to commit: ${NEW_COMMIT:0:8}..." "$GREEN"
        log_message "Repository updated successfully" "$GREEN"
        SKIP_CLONE=true
    else
        handle_existing "$BASE_PATH" "installation directory" "OpenAlgo directory for $DEPLOY_NAME"
        SKIP_CLONE=false
    fi
else
    handle_existing "$BASE_PATH" "installation directory" "OpenAlgo directory for $DEPLOY_NAME"
    SKIP_CLONE=false
fi

# Create base directory
log_message "\nCreating base directory..." "$BLUE"
sudo mkdir -p $BASE_PATH
check_status "Failed to create base directory"

# Clone repository if needed
if [ "$SKIP_CLONE" != "true" ]; then
    log_message "\nCloning OpenAlgo repository..." "$BLUE"
    sudo git clone https://github.com/marketcalls/openalgo.git $OPENALGO_PATH
    check_status "Failed to clone OpenAlgo repository"
fi

# Create virtual environment using uv
log_message "\nSetting up Python virtual environment with uv..." "$BLUE"
if [ -d "$VENV_PATH" ]; then
    log_message "Warning: Virtual environment already exists, removing..." "$YELLOW"
    sudo rm -rf "$VENV_PATH"
fi
# Create directory if it doesn't exist
sudo mkdir -p $(dirname $VENV_PATH)

# Detect how uv is installed and set the appropriate command
if command -v uv >/dev/null 2>&1; then
    # uv is available as a standalone command (snap or astral installer)
    UV_CMD="uv"
    log_message "Using standalone uv command" "$GREEN"
elif $PYTHON_CMD -m uv --version >/dev/null 2>&1; then
    # uv is available as a Python module
    UV_CMD="$PYTHON_CMD -m uv"
    log_message "Using uv as Python module" "$GREEN"
else
    log_message "Error: uv is not available" "$RED"
    exit 1
fi

# Create virtual environment using uv
sudo $UV_CMD venv $VENV_PATH
check_status "Failed to create virtual environment with uv"

# Install Python dependencies using uv (faster installation)
log_message "\nInstalling Python dependencies with uv..." "$BLUE"
# First activate the virtual environment path for uv
ACTIVATE_CMD="source $VENV_PATH/bin/activate"
# Install dependencies using uv
sudo $UV_CMD pip install --python $VENV_PATH/bin/python -r $OPENALGO_PATH/requirements-nginx.txt
check_status "Failed to install Python dependencies"

# Verify gunicorn and eventlet installation
log_message "\nVerifying gunicorn and eventlet installation..." "$BLUE"
if ! sudo bash -c "$ACTIVATE_CMD && pip freeze | grep -q 'gunicorn=='"; then
    log_message "Installing gunicorn..." "$YELLOW"
    sudo $UV_CMD pip install --python $VENV_PATH/bin/python gunicorn
    check_status "Failed to install gunicorn"
fi
if ! sudo bash -c "$ACTIVATE_CMD && pip freeze | grep -q 'eventlet=='"; then
    log_message "Installing eventlet..." "$YELLOW"
    sudo $UV_CMD pip install --python $VENV_PATH/bin/python eventlet
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

# Update host bindings to allow external connections
sudo sed -i "s|WEBSOCKET_HOST='127.0.0.1'|WEBSOCKET_HOST='0.0.0.0'|g" $OPENALGO_PATH/.env
sudo sed -i "s|ZMQ_HOST='127.0.0.1'|ZMQ_HOST='0.0.0.0'|g" $OPENALGO_PATH/.env

check_status "Failed to configure environment file"

# Check and handle existing Nginx configuration
handle_existing "$NGINX_CONFIG_FILE" "Nginx configuration" "Nginx config file"

# Fix Arch Linux nginx.conf to include conf.d directory
if [ "$OS_TYPE" = "arch" ]; then
    if ! grep -q "include.*conf.d/\*.conf" /etc/nginx/nginx.conf; then
        log_message "Adding conf.d include to nginx.conf for Arch Linux..." "$YELLOW"
        sudo sed -i '/http {/a\    include /etc/nginx/conf.d/*.conf;' /etc/nginx/nginx.conf
        log_message "conf.d include added to nginx.conf" "$GREEN"
    fi
fi

# Configure initial Nginx for SSL certificate obtention
log_message "\nConfiguring initial Nginx setup..." "$BLUE"
sudo tee $NGINX_CONFIG_FILE > /dev/null << EOL
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
if [ "$NGINX_CONFIG_MODE" = "sites" ]; then
    sudo rm -f /etc/nginx/sites-enabled/default
    sudo ln -sf $NGINX_CONFIG_FILE /etc/nginx/sites-enabled/
    check_status "Failed to enable Nginx site"
else
    # For conf.d mode, config is already active, just remove default if it exists
    sudo rm -f /etc/nginx/conf.d/default.conf
fi

# Start or reload Nginx for initial configuration
log_message "\nTesting and starting/reloading Nginx..." "$BLUE"
sudo nginx -t
check_status "Failed to validate Nginx configuration"

# Check if nginx is running, start or reload accordingly
if sudo systemctl is-active --quiet nginx; then
    sudo systemctl reload nginx
    log_message "Nginx reloaded successfully" "$GREEN"
else
    sudo systemctl enable nginx
    sudo systemctl start nginx
    log_message "Nginx started successfully" "$GREEN"
fi
check_status "Failed to start/reload Nginx"

# Configure firewall
log_message "\nConfiguring firewall rules..." "$BLUE"
case "$OS_TYPE" in
    ubuntu | debian | raspbian)
        # Wait for any running package manager operations to complete
        wait_for_dpkg_lock
        sudo apt-get install -y ufw
        sudo ufw default deny incoming
        sudo ufw default allow outgoing
        sudo ufw allow ssh
        sudo ufw allow 'Nginx Full'
        sudo ufw --force enable
        check_status "Failed to configure firewall"
        ;;
    centos | fedora | rhel | amzn)
        # Install and configure firewalld
        if ! command -v firewall-cmd >/dev/null 2>&1; then
            if ! command -v dnf >/dev/null 2>&1; then
                sudo yum install -y firewalld
            else
                sudo dnf install -y firewalld
            fi
        fi
        sudo systemctl enable firewalld
        sudo systemctl start firewalld
        sudo firewall-cmd --permanent --add-service=ssh
        sudo firewall-cmd --permanent --add-service=http
        sudo firewall-cmd --permanent --add-service=https
        sudo firewall-cmd --reload
        check_status "Failed to configure firewall"
        ;;
    arch)
        # Install ufw on Arch
        if ! command -v ufw >/dev/null 2>&1; then
            sudo pacman -Sy --noconfirm --needed ufw
        fi
        sudo systemctl enable ufw
        sudo systemctl start ufw
        sudo ufw default deny incoming
        sudo ufw default allow outgoing
        sudo ufw allow ssh
        # Use direct port rules instead of application profile on Arch
        sudo ufw allow 80/tcp
        sudo ufw allow 443/tcp
        sudo ufw --force enable
        check_status "Failed to configure firewall"
        ;;
esac

# Obtain SSL certificate
log_message "\nObtaining SSL certificate..." "$BLUE"
if [ "$IS_SUBDOMAIN" = true ]; then
    sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email admin@${DOMAIN#*.}
else
    sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN
fi

# Check if certificate was obtained (even if auto-install failed)
if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    log_message "Failed to obtain SSL certificate" "$RED"
    exit 1
else
    log_message "SSL certificate obtained successfully" "$GREEN"
fi

# Configure final Nginx setup with SSL and socket
log_message "\nConfiguring final Nginx setup..." "$BLUE"
# Remove old config files to ensure clean write (with and without .conf extension)
sudo rm -f $NGINX_CONFIG_FILE
sudo rm -f ${NGINX_AVAILABLE}/${DOMAIN}
if [ "$NGINX_CONFIG_MODE" = "sites" ]; then
    sudo rm -f /etc/nginx/sites-enabled/${DOMAIN}
    sudo rm -f /etc/nginx/sites-enabled/${DOMAIN}.conf
fi
# Write the new configuration
sudo tee $NGINX_CONFIG_FILE > /dev/null << EOL
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

# Recreate symlink for sites-enabled if needed
if [ "$NGINX_CONFIG_MODE" = "sites" ]; then
    sudo ln -sf $NGINX_CONFIG_FILE /etc/nginx/sites-enabled/
    log_message "Recreated nginx symlink" "$GREEN"
fi

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
User=$WEB_USER
Group=$WEB_GROUP
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
sudo chown -R $WEB_USER:$WEB_GROUP $BASE_PATH
sudo chmod -R 755 $BASE_PATH

# Create and set permissions for required directories
sudo mkdir -p $OPENALGO_PATH/db
sudo mkdir -p $OPENALGO_PATH/tmp
# Create directories for Python strategy feature
sudo mkdir -p $OPENALGO_PATH/strategies/scripts
sudo mkdir -p $OPENALGO_PATH/log/strategies
sudo mkdir -p $OPENALGO_PATH/keys
# Set ownership and permissions
sudo chown -R $WEB_USER:$WEB_GROUP $OPENALGO_PATH
sudo chmod -R 755 $OPENALGO_PATH
# Set more restrictive permissions for sensitive directories
sudo chmod 700 $OPENALGO_PATH/keys

# Remove existing socket file if it exists
[ -S "$SOCKET_FILE" ] && sudo rm -f $SOCKET_FILE

# Ensure socket directory is accessible to nginx
sudo chmod 755 $SOCKET_PATH

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

# Configure SELinux for RHEL-based systems
if [ "$OS_TYPE" = "centos" ] || [ "$OS_TYPE" = "fedora" ] || [ "$OS_TYPE" = "rhel" ] || [ "$OS_TYPE" = "amzn" ]; then
    if command -v getenforce >/dev/null 2>&1 && [ "$(getenforce)" != "Disabled" ]; then
        log_message "\nConfiguring SELinux permissions..." "$BLUE"

        # Set SELinux context for the application directory
        sudo semanage fcontext -a -t httpd_sys_rw_content_t "$BASE_PATH(/.*)?" 2>/dev/null || true
        sudo restorecon -Rv $BASE_PATH >/dev/null 2>&1

        # Enable httpd network connections
        sudo setsebool -P httpd_can_network_connect on 2>/dev/null || true

        # Check for SELinux denials and create policy if needed
        if sudo ausearch -m avc -ts recent 2>/dev/null | grep -q "httpd_t.*initrc_t.*unix_stream_socket"; then
            log_message "Creating SELinux policy for nginx-gunicorn connection..." "$YELLOW"

            # Generate and install SELinux policy for httpd to connect to gunicorn socket
            sudo ausearch -m avc -ts recent 2>/dev/null | sudo audit2allow -M httpd_gunicorn 2>/dev/null || true
            if [ -f httpd_gunicorn.pp ]; then
                sudo semodule -i httpd_gunicorn.pp 2>/dev/null || true
                sudo rm -f httpd_gunicorn.pp httpd_gunicorn.te 2>/dev/null || true
                log_message "SELinux policy installed successfully" "$GREEN"

                # Restart nginx to apply new policy
                sudo systemctl restart nginx
            fi
        fi

        log_message "SELinux configuration completed" "$GREEN"
    fi
fi

log_message "\nInstallation completed successfully!" "$GREEN"
log_message "\nInstallation Summary:" "$YELLOW"
log_message "Operating System: $OS_TYPE $OS_VERSION" "$BLUE"
log_message "Deployment Name: $DEPLOY_NAME" "$BLUE"
log_message "Domain: $DOMAIN" "$BLUE"
log_message "Broker: $BROKER_NAME" "$BLUE"
log_message "Installation Directory: $OPENALGO_PATH" "$BLUE"
log_message "Environment File: $OPENALGO_PATH/.env" "$BLUE"
log_message "Socket File: $SOCKET_FILE" "$BLUE"
log_message "Service Name: $SERVICE_NAME" "$BLUE"
log_message "Nginx Config: $NGINX_CONFIG_FILE" "$BLUE"
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
log_message "\nUpdate Commands:" "$YELLOW"
log_message "Update this installation: cd $OPENALGO_PATH && sudo -u $WEB_USER git pull origin main" "$BLUE"
log_message "Use update script (recommended): sudo bash $OPENALGO_PATH/install/update.sh" "$BLUE"
log_message "Update specific installation: sudo bash $OPENALGO_PATH/install/update.sh $BASE_PATH" "$BLUE"

# Ask about automated updates
log_message "\nAutomated Updates:" "$YELLOW"
read -p "Would you like to set up automated daily git pulls? (y/n): " auto_update_choice
if [[ $auto_update_choice =~ ^[Yy]$ ]]; then
    log_message "Setting up automated daily updates..." "$BLUE"
    
    # Create update script wrapper for this specific installation
    UPDATE_SCRIPT_WRAPPER="$BASE_PATH/update-openalgo.sh"
    sudo tee "$UPDATE_SCRIPT_WRAPPER" > /dev/null << EOUPDATESCRIPT
#!/bin/bash
# Auto-generated update script for $DEPLOY_NAME
# This script updates this specific OpenAlgo installation

cd "$OPENALGO_PATH"
sudo -u $WEB_USER git fetch origin
CURRENT_BRANCH=\$(sudo -u $WEB_USER git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
CURRENT_COMMIT=\$(sudo -u $WEB_USER git rev-parse HEAD)
REMOTE_COMMIT=\$(sudo -u $WEB_USER git rev-parse origin/\${CURRENT_BRANCH})

if [ "\$CURRENT_COMMIT" != "\$REMOTE_COMMIT" ]; then
    echo "[$(date)] Updating $DEPLOY_NAME from \${CURRENT_COMMIT:0:8} to \${REMOTE_COMMIT:0:8}..."
    
    # Stash any local changes
    sudo -u $WEB_USER git stash push -m "Auto-stash before scheduled update \$(date +%Y%m%d_%H%M%S)" 2>/dev/null
    
    # Pull updates
    sudo -u $WEB_USER git pull origin \${CURRENT_BRANCH} > /dev/null 2>&1
    
    if [ \$? -eq 0 ]; then
        # Get the new commit after pull
        NEW_COMMIT=\$(sudo -u $WEB_USER git rev-parse HEAD)
        
        # Check if requirements changed and update dependencies if needed
        if [ -f "$VENV_PATH/bin/activate" ]; then
            if sudo -u $WEB_USER git diff --name-only \$CURRENT_COMMIT \$NEW_COMMIT | grep -q "requirements"; then
                # Detect uv command
                if command -v uv >/dev/null 2>&1; then
                    UV_CMD="uv"
                elif python3 -m uv --version >/dev/null 2>&1; then
                    UV_CMD="python3 -m uv"
                fi
                
                if [ -n "\$UV_CMD" ]; then
                    sudo \$UV_CMD pip install --python $VENV_PATH/bin/python -r $OPENALGO_PATH/requirements-nginx.txt > /dev/null 2>&1
                fi
            fi
        fi
        
        # Restart service
        systemctl restart $SERVICE_NAME > /dev/null 2>&1
        echo "[$(date)] Update completed successfully for $DEPLOY_NAME"
    else
        echo "[$(date)] Error: Failed to update $DEPLOY_NAME"
        # Restore stashed changes on failure
        sudo -u $WEB_USER git stash pop 2>/dev/null
    fi
else
    echo "[$(date)] $DEPLOY_NAME is already up to date"
fi
EOUPDATESCRIPT
    
    sudo chmod +x "$UPDATE_SCRIPT_WRAPPER"
    sudo chown $WEB_USER:$WEB_GROUP "$UPDATE_SCRIPT_WRAPPER"
    
    # Create systemd timer for daily updates
    TIMER_NAME="openalgo-update-$DEPLOY_NAME"
    TIMER_SERVICE="${TIMER_NAME}.timer"
    TIMER_PATH="/etc/systemd/system/${TIMER_SERVICE}"
    
    sudo tee "$TIMER_PATH" > /dev/null << EOTIMER
[Unit]
Description=Daily update timer for OpenAlgo ($DEPLOY_NAME)
Requires=${TIMER_NAME}.service

[Timer]
OnCalendar=daily
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
EOTIMER
    
    # Create corresponding service
    SERVICE_PATH="/etc/systemd/system/${TIMER_NAME}.service"
    sudo tee "$SERVICE_PATH" > /dev/null << EOSERVICE
[Unit]
Description=Update OpenAlgo ($DEPLOY_NAME)
After=network.target

[Service]
Type=oneshot
ExecStart=$UPDATE_SCRIPT_WRAPPER
User=root

[Install]
WantedBy=multi-user.target
EOSERVICE
    
    # Enable and start timer
    sudo systemctl daemon-reload
    sudo systemctl enable "$TIMER_SERVICE"
    sudo systemctl start "$TIMER_SERVICE"
    
    check_status "Failed to set up automated updates"
    log_message "Automated daily updates configured" "$GREEN"
    log_message "Update script: $UPDATE_SCRIPT_WRAPPER" "$BLUE"
    log_message "Timer service: $TIMER_SERVICE" "$BLUE"
    log_message "Check timer status: sudo systemctl status $TIMER_SERVICE" "$BLUE"
    log_message "Check last run: sudo journalctl -u ${TIMER_NAME}.service -n 20" "$BLUE"
fi
