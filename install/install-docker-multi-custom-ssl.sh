#!/bin/bash

# OpenAlgo Docker Multi-Instance Installation with Custom SSL
# Supports deploying multiple instances with existing SSL certificates (including Wildcards)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Base Configuration
INSTALL_BASE="/opt/openalgo"
START_FLASK_PORT=5000
START_WS_PORT=8765

# Script Banner
echo -e "${BLUE}"
echo "  ██████╗ ██████╗ ███████╗███╗   ██╗ █████╗ ██╗      ██████╗  ██████╗ "
echo " ██╔═══██╗██╔══██╗██╔════╝████╗  ██║██╔══██╗██║     ██╔════╝ ██╔═══██╗"
echo " ██║   ██║██████╔╝███████╗██╔██╗ ██║███████║██║     ██║  ███╗██║   ██║"
echo " ██║   ██║██╔═══╝ ██╔══╝  ██║╚██╗██║██╔══██║██║     ██║   ██║██║   ██║"
echo " ╚██████╔╝██╗     ███████╗██║ ╚████║██║  ██║███████╗╚██████╔╝╚██████╔╝"
echo "  ╚═════╝ ╚═╝     ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚══════╝ ╚═════╝  ╚═════╝ "
echo "             MULTI-INSTANCE DOCKER + CUSTOM SSL INSTALLER               "
echo -e "${NC}"

# -----------------
# Helper Functions
# -----------------

log() {
    echo -e "${2}${1}${NC}"
}

check_status() {
    if [ $? -ne 0 ]; then
        log "Error: $1" "$RED"
        exit 1
    fi
}

generate_hex() {
    python3 -c "import secrets; print(secrets.token_hex(32))"
}

validate_broker() {
    local broker=$1
    local valid_brokers="fivepaisa,fivepaisaxts,aliceblue,angel,compositedge,definedge,dhan,dhan_sandbox,firstock,flattrade,fyers,groww,ibulls,iifl,indmoney,jainamxts,kotak,motilal,mstock,nubra,paytm,pocketful,samco,shoonya,tradejini,upstox,wisdom,zebu,zerodha"
    [[ $valid_brokers == *"$broker"* ]]
}

is_xts_broker() {
    local broker=$1
    local xts_brokers="fivepaisaxts,compositedge,ibulls,iifl,jainamxts,wisdom"
    if [[ ",$xts_brokers," == *",$broker,"* ]]; then
        return 0
    else
        return 1
    fi
}

sanitize_domain() {
    echo "$1" | tr '.' '-'
}

get_next_ports() {
    # Scan existing docker-compose files to find highest used ports
    local max_flask=$((START_FLASK_PORT - 1))
    local max_ws=$((START_WS_PORT - 1))
    
    # Check if base directory exists
    if [ -d "$INSTALL_BASE" ]; then
        # Find all docker-compose.yaml files
        while IFS= read -r file; do
            # Extract ports using grep/sed (simple parsing)
            local f_port=$(grep -A 5 "ports:" "$file" | grep ":5000" | cut -d: -f2)
            local w_port=$(grep -A 5 "ports:" "$file" | grep ":8765" | cut -d: -f2)
            
            # Update max if higher
            if [ ! -z "$f_port" ] && [ "$f_port" -gt "$max_flask" ]; then
                max_flask=$f_port
            fi
            if [ ! -z "$w_port" ] && [ "$w_port" -gt "$max_ws" ]; then
                max_ws=$w_port
            fi
        done < <(find "$INSTALL_BASE" -name "docker-compose.yaml")
    fi

    # Return next available pair
    echo "$((max_flask + 1)) $((max_ws + 1))"
}

# -----------------
# System Prep
# -----------------

# Check root
if [[ $EUID -ne 0 ]]; then
   log "This script must be run as root" "$RED" 
   exit 1
fi

log "\n=== System Preparation ===" "$BLUE"

# Update system
log "Updating system packages..." "$YELLOW"
apt-get update -y && apt-get upgrade -y
check_status "System update failed"

# Install basics
log "Installing dependencies..." "$YELLOW"
apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    nginx \
    ufw \
    python3-full \
    python3-pip
check_status "Package installation failed"

# Host Timezone Check
log "Checking Host Timezone..." "$YELLOW"
CURRENT_TZ=$(timedatectl show --property=Timezone --value 2>/dev/null || cat /etc/timezone)
if [[ "$CURRENT_TZ" != *"Asia/Kolkata"* ]]; then
    log "Setting Host Timezone to Asia/Kolkata..." "$YELLOW"
    timedatectl set-timezone Asia/Kolkata
    check_status "Failed to set timezone"
    log "Timezone set to Asia/Kolkata" "$GREEN"
else
    log "Host Timezone is already Asia/Kolkata." "$GREEN"
fi

# Install Docker
if ! command -v docker &> /dev/null; then
    log "Installing Docker..." "$YELLOW"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sh get-docker.sh
    rm get-docker.sh
    check_status "Docker installation failed"
else
    log "Docker already installed" "$GREEN"
fi

# Install uv (if not present, though Docker installs it inside container, we might need it for utilities)
if ! command -v uv &> /dev/null; then
     log "Installing uv..." "$YELLOW"
     curl -LsSf https://astral.sh/uv/install.sh | sh
     if [ -f "$HOME/.cargo/env" ]; then
         source "$HOME/.cargo/env"
     fi
fi


# -----------------
# Configuration Collection
# -----------------

log "\n=== Configuration ===" "$BLUE"

# 0. Git Repository Selection
DEFAULT_REPO="https://github.com/marketcalls/openalgo.git"
read -p "Enter Git Repository URL [Default: $DEFAULT_REPO]: " REPO_URL
REPO_URL=${REPO_URL:-$DEFAULT_REPO}
log "Using Repository: $REPO_URL" "$GREEN"

# 1. Get Domains
while true; do
    read -p "Enter domain names separated by SPACE (e.g., domain.com zerodha.domain.com): " -a DOMAINS_INPUT
    if [ ${#DOMAINS_INPUT[@]} -eq 0 ]; then
        log "Error: At least one domain is required" "$RED"
        continue
    fi
    break
done

# 2. First Pass: Determine which domains are updates vs fresh installs
declare -a NEW_DOMAINS
declare -a UPDATE_DOMAINS

for DOMAIN in "${DOMAINS_INPUT[@]}"; do
    INSTANCE_DIR="$INSTALL_BASE/$DOMAIN"
    if [ -d "$INSTANCE_DIR" ] && [ -d "$INSTANCE_DIR/.git" ] && [ -f "$INSTANCE_DIR/.env" ]; then
        log "Found existing installation: $DOMAIN" "$GREEN"
        UPDATE_DOMAINS+=("$DOMAIN")
    else
        NEW_DOMAINS+=("$DOMAIN")
    fi
done

log "Update domains: ${#UPDATE_DOMAINS[@]}, New domains: ${#NEW_DOMAINS[@]}" "$BLUE"

# 3. Wildcard SSL Check - Only ask if there are NEW domains to configure
WILDCARD_CERT_PATH=""
WILDCARD_KEY_PATH=""
USE_WILDCARD_SSL="n"

if [ ${#NEW_DOMAINS[@]} -gt 0 ]; then
    log "\n${#NEW_DOMAINS[@]} new domain(s) detected. SSL configuration required." "$YELLOW"
    read -p "Do you have a WILDCARD SSL certificate for these domains? (y/n): " USE_WILDCARD_SSL

    if [[ $USE_WILDCARD_SSL =~ ^[Yy]$ ]]; then
        while true; do
            read -e -p "Enter path to Wildcard FULL CHAIN .pem file: " WILDCARD_CERT_PATH
            if [ ! -f "$WILDCARD_CERT_PATH" ]; then
                log "Error: File not found at $WILDCARD_CERT_PATH" "$RED"
                continue
            fi
            break
        done

        while true; do
            read -e -p "Enter path to Wildcard PRIVATE KEY .key file: " WILDCARD_KEY_PATH
            if [ ! -f "$WILDCARD_KEY_PATH" ]; then
                log "Error: File not found at $WILDCARD_KEY_PATH" "$RED"
                continue
            fi
            break
        done
    fi
else
    log "\nAll domains are existing installations - SSL configuration will be preserved." "$GREEN"
fi

# Arrays to store config
declare -a CONF_DOMAINS
declare -a CONF_BROKERS
declare -a CONF_API_KEYS
declare -a CONF_API_SECRETS
declare -a CONF_MARKET_KEYS
declare -a CONF_MARKET_SECRETS
declare -a CONF_SSL_CERTS
declare -a CONF_SSL_KEYS
declare -a UPDATE_MODE  # Track update vs fresh install per domain

# Helper function to extract value from .env file
extract_env_value() {
    local env_file="$1"
    local key="$2"
    grep "^${key}" "$env_file" 2>/dev/null | head -1 | cut -d"'" -f2 | tr -d "'" || echo ""
}

# 3. Iterate Domains for Config
for DOMAIN in "${DOMAINS_INPUT[@]}"; do
    log "\n--- Configuring Instance: $DOMAIN ---" "$YELLOW"

    # Check existing installation
    INSTANCE_DIR="$INSTALL_BASE/$DOMAIN"
    IS_UPDATE="false"
    
    if [ -d "$INSTANCE_DIR" ] && [ -d "$INSTANCE_DIR/.git" ]; then
        read -p "Instance for $DOMAIN already exists. Update code only? (y=update, n=skip, r=reinstall): " UPDATE_CHOICE
        case "$UPDATE_CHOICE" in
            [Yy]*)
                IS_UPDATE="true"
                log "Update mode: Will pull latest code and preserve configuration." "$GREEN"
                
                # Load existing configuration from .env
                EXISTING_ENV="$INSTANCE_DIR/.env"
                if [ -f "$EXISTING_ENV" ]; then
                    log "Loading existing configuration from .env..." "$GREEN"
                    EXISTING_BROKER=$(extract_env_value "$EXISTING_ENV" "REDIRECT_URL" | sed 's|.*/\([^/]*\)/callback|\1|')
                    EXISTING_API_KEY=$(extract_env_value "$EXISTING_ENV" "BROKER_API_KEY")
                    EXISTING_API_SECRET=$(extract_env_value "$EXISTING_ENV" "BROKER_API_SECRET")
                    EXISTING_M_KEY=$(extract_env_value "$EXISTING_ENV" "BROKER_API_KEY_MARKET")
                    EXISTING_M_SECRET=$(extract_env_value "$EXISTING_ENV" "BROKER_API_SECRET_MARKET")
                    
                    # Use existing values
                    CONF_DOMAINS+=("$DOMAIN")
                    CONF_BROKERS+=("$EXISTING_BROKER")
                    CONF_API_KEYS+=("$EXISTING_API_KEY")
                    CONF_API_SECRETS+=("$EXISTING_API_SECRET")
                    CONF_MARKET_KEYS+=("${EXISTING_M_KEY:-}")
                    CONF_MARKET_SECRETS+=("${EXISTING_M_SECRET:-}")
                    UPDATE_MODE+=("true")
                    
                    # SSL already configured, get existing paths
                    SSL_DIR="/etc/nginx/ssl/$DOMAIN"
                    if [ -f "$SSL_DIR/fullchain.pem" ]; then
                        CONF_SSL_CERTS+=("$SSL_DIR/fullchain.pem")
                        CONF_SSL_KEYS+=("$SSL_DIR/privkey.pem")
                    else
                        log "Warning: SSL certs not found, will need reconfiguration" "$YELLOW"
                        CONF_SSL_CERTS+=("EXISTING")
                        CONF_SSL_KEYS+=("EXISTING")
                    fi
                    
                    log "Loaded: Broker=$EXISTING_BROKER" "$GREEN"
                    continue  # Skip interactive prompts for this domain
                else
                    log "Warning: No .env found, treating as fresh install" "$YELLOW"
                    IS_UPDATE="false"
                fi
                ;;
            [Nn]*)
                log "Skipping $DOMAIN" "$YELLOW"
                continue
                ;;
            [Rr]*)
                log "Reinstall mode: Will ask for all configuration again." "$YELLOW"
                log "Warning: This will regenerate security keys and invalidate existing passwords!" "$RED"
                read -p "Are you sure you want to reinstall? (yes to confirm): " CONFIRM_REINSTALL
                if [ "$CONFIRM_REINSTALL" != "yes" ]; then
                    log "Skipping $DOMAIN" "$YELLOW"
                    continue
                fi
                ;;
            *)
                log "Invalid choice. Skipping $DOMAIN" "$RED"
                continue
                ;;
        esac
    fi
    
    # Mark as fresh install if not update mode
    UPDATE_MODE+=("$IS_UPDATE")

    CONF_DOMAINS+=("$DOMAIN")

    # Broker
    while true; do
        read -p "Enter BROKER for $DOMAIN: " BROKER
        if validate_broker "$BROKER"; then
            CONF_BROKERS+=("$BROKER")
            break
        else
            log "Invalid broker path. See documentation for list." "$RED"
        fi
    done

    # Credentials
    log "Redirect URL: https://$DOMAIN/$BROKER/callback" "$GREEN"
    # Credentials
    log "Redirect URL: https://$DOMAIN/$BROKER/callback" "$GREEN"
    while true; do
        read -p "Enter API Key: " API_KEY
        if [ ! -z "$API_KEY" ]; then
            CONF_API_KEYS+=("$API_KEY")
            break
        else
            log "API Key cannot be empty." "$RED"
        fi
    done

    while true; do
        read -p "Enter API Secret: " API_SECRET
        if [ ! -z "$API_SECRET" ]; then
            CONF_API_SECRETS+=("$API_SECRET")
            break
        else
            log "API Secret cannot be empty." "$RED"
        fi
    done

    # XTS Check
    if is_xts_broker "$BROKER"; then
        read -p "Enter Market Data API Key: " M_KEY
        read -p "Enter Market Data API Secret: " M_SECRET
        CONF_MARKET_KEYS+=("$M_KEY")
        CONF_MARKET_SECRETS+=("$M_SECRET")
    else
        CONF_MARKET_KEYS+=("")
        CONF_MARKET_SECRETS+=("")
    fi

    # SSL Config
    if [[ $USE_WILDCARD_SSL =~ ^[Yy]$ ]]; then
        CONF_SSL_CERTS+=("$WILDCARD_CERT_PATH")
        CONF_SSL_KEYS+=("$WILDCARD_KEY_PATH")
    else
        log "SSL Configuration for $DOMAIN" "$BLUE"
        echo "Select SSL Type:"
        echo "1) Custom SSL (You have your own .pem/.key files)"
        echo "2) Let's Encrypt (Automated via Certbot)"
         read -p "Enter choice [1/2] (Default: 1): " SSL_CHOICE
        SSL_CHOICE=${SSL_CHOICE:-1}

        if [ "$SSL_CHOICE" == "2" ]; then
             # Let's Encrypt
             CONF_SSL_CERTS+=("LETSENCRYPT_AUTO")
             CONF_SSL_KEYS+=("LETSENCRYPT_AUTO")
        else
             # Custom SSL with default suggestion
             DEFAULT_CERT_PATH="/etc/ssl/certs/${DOMAIN}.pem" # Example default
             DEFAULT_KEY_PATH="/etc/ssl/private/${DOMAIN}.key" # Example default
             
             # Try to find if user has a standard 'certs' folder in home or root
             if [ -d "$HOME/certs" ]; then
                 DEFAULT_CERT_PATH="$HOME/certs/${DOMAIN}.crt"
                 DEFAULT_KEY_PATH="$HOME/certs/${DOMAIN}.key"
             elif [ -d "/root/certs" ]; then
                 DEFAULT_CERT_PATH="/root/certs/${DOMAIN}.crt"
                 DEFAULT_KEY_PATH="/root/certs/${DOMAIN}.key"
             fi

             while true; do
                 read -e -p "Enter path to SSL Certificate [Default: $DEFAULT_CERT_PATH]: " CERT_PATH
                 CERT_PATH=${CERT_PATH:-$DEFAULT_CERT_PATH}
                 if [ ! -f "$CERT_PATH" ]; then
                     log "Error: File not found at $CERT_PATH" "$RED"
                     continue
                 fi
                 break
             done

             while true; do
                 read -e -p "Enter path to SSL Private Key [Default: $DEFAULT_KEY_PATH]: " KEY_PATH
                 KEY_PATH=${KEY_PATH:-$DEFAULT_KEY_PATH}
                 if [ ! -f "$KEY_PATH" ]; then
                     log "Error: File not found at $KEY_PATH" "$RED"
                     continue
                 fi
                 break
             done
             CONF_SSL_CERTS+=("$CERT_PATH")
             CONF_SSL_KEYS+=("$KEY_PATH")
         fi
    fi
done

# -----------------
# Deployment Loop
# -----------------

log "\n=== Starting Deployment ===" "$BLUE"

# Calculate dynamic resource limits based on system specs and number of instances
TOTAL_RAM_MB=$(($(grep MemTotal /proc/meminfo | awk '{print $2}') / 1024))
CPU_CORES=$(nproc 2>/dev/null || echo 2)
NUM_INSTANCES=${#CONF_DOMAINS[@]}

# Calculate per-instance RAM (divide total by number of instances)
RAM_PER_INSTANCE=$((TOTAL_RAM_MB / NUM_INSTANCES))
log "System: ${TOTAL_RAM_MB}MB RAM, ${CPU_CORES} cores, ${NUM_INSTANCES} instances" "$BLUE"
log "Per-instance allocation: ~${RAM_PER_INSTANCE}MB" "$BLUE"

# shm_size: 25% of per-instance RAM (min 128MB, max 1GB for multi-instance)
SHM_SIZE_MB=$((RAM_PER_INSTANCE / 4))
[ $SHM_SIZE_MB -lt 128 ] && SHM_SIZE_MB=128
[ $SHM_SIZE_MB -gt 1024 ] && SHM_SIZE_MB=1024

# Thread limits based on per-instance RAM (conservative)
# <2GB: 1 thread | 2-4GB: 2 threads | 4GB+: max(2, min(4, cores/instances))
if [ $RAM_PER_INSTANCE -lt 2000 ]; then
    THREAD_LIMIT=1
elif [ $RAM_PER_INSTANCE -lt 4000 ]; then
    THREAD_LIMIT=2
else
    CORES_PER_INSTANCE=$((CPU_CORES / NUM_INSTANCES))
    THREAD_LIMIT=$((CORES_PER_INSTANCE < 2 ? 2 : CORES_PER_INSTANCE))
    [ $THREAD_LIMIT -gt 4 ] && THREAD_LIMIT=4
fi

# Strategy memory limit based on per-instance RAM
# <2GB: 256MB | 2-4GB: 512MB | 4GB+: 1024MB
if [ $RAM_PER_INSTANCE -lt 2000 ]; then
    STRATEGY_MEM_LIMIT=256
elif [ $RAM_PER_INSTANCE -lt 4000 ]; then
    STRATEGY_MEM_LIMIT=512
else
    STRATEGY_MEM_LIMIT=1024
fi

log "Config: shm=${SHM_SIZE_MB}MB, threads=${THREAD_LIMIT}, strategy_mem=${STRATEGY_MEM_LIMIT}MB" "$BLUE"

# Base Dir
mkdir -p "$INSTALL_BASE"
chmod 755 "$INSTALL_BASE"

# Firewall Init (Open standard ports)
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Optional Portainer Installation - Smart Detection
PORTAINER_RUNNING=$(docker ps -q -f name=portainer)
PORTAINER_EXISTS=$(docker ps -aq -f name=portainer)
INSTALL_PORTAINER="n"
PORTAINER_DOMAIN=""

if [ ! -z "$PORTAINER_RUNNING" ]; then
    # Portainer is already running
    CURRENT_IMAGE=$(docker inspect portainer --format '{{.Config.Image}}' 2>/dev/null || echo "unknown")
    log "Portainer is already running (Image: $CURRENT_IMAGE)" "$GREEN"
    
    read -p "Check for Portainer updates? (y/n): " CHECK_PORTAINER_UPDATE
    if [[ $CHECK_PORTAINER_UPDATE =~ ^[Yy]$ ]]; then
        log "Checking for Portainer updates..." "$YELLOW"
        docker pull portainer/portainer-ce:latest
        
        NEW_IMAGE_ID=$(docker inspect portainer/portainer-ce:latest --format '{{.Id}}' 2>/dev/null | cut -c8-19)
        OLD_IMAGE_ID=$(docker inspect portainer --format '{{.Image}}' 2>/dev/null | cut -c8-19)
        
        if [ "$NEW_IMAGE_ID" != "$OLD_IMAGE_ID" ] && [ ! -z "$NEW_IMAGE_ID" ]; then
            log "New Portainer version available. Updating..." "$YELLOW"
            
            # Get current binding (preserve domain/IP configuration)
            CURRENT_BIND=$(docker port portainer 9000 2>/dev/null | cut -d: -f1)
            BIND_IP="${CURRENT_BIND:-127.0.0.1}"
            
            docker stop portainer && docker rm portainer
            docker run -d -p $BIND_IP:9000:9000 --name portainer --restart=always \
                -v /var/run/docker.sock:/var/run/docker.sock \
                -v portainer_data:/data \
                portainer/portainer-ce:latest
            log "Portainer updated successfully!" "$GREEN"
        else
            log "Portainer is already at latest version." "$GREEN"
        fi
    fi
    
    # Skip all further Portainer prompts - already configured
    INSTALL_PORTAINER="skip"
    
elif [ ! -z "$PORTAINER_EXISTS" ]; then
    # Portainer container exists but is stopped
    log "Portainer container exists but is stopped." "$YELLOW"
    read -p "Start existing Portainer? (y/n): " START_PORTAINER
    if [[ $START_PORTAINER =~ ^[Yy]$ ]]; then
        docker start portainer
        log "Portainer started." "$GREEN"
    fi
    INSTALL_PORTAINER="skip"
    
else
    # Fresh install option
    read -p "Do you want to install Portainer (Docker Management UI)? (y/n): " INSTALL_PORTAINER
fi

if [[ $INSTALL_PORTAINER =~ ^[Yy]$ ]]; then
    read -p "Enter Domain for Portainer (Leave EMPTY to use IP:9000): " PORTAINER_DOMAIN
    
    log "\nInstalling Portainer..." "$BLUE"
    
    # 1. Install Portainer Container
    if [ ! "$(docker ps -q -f name=portainer)" ]; then
        if [ "$(docker ps -aq -f status=exited -f name=portainer)" ]; then
            docker rm portainer
        fi
        
        docker volume create portainer_data
        # Run on localhost:9000 only if using Nginx, otherwise 0.0.0.0:9000
        if [ ! -z "$PORTAINER_DOMAIN" ]; then
            BIND_IP="127.0.0.1"
            log "Configuring Portainer for domain: $PORTAINER_DOMAIN" "$GREEN"
        else
            BIND_IP="0.0.0.0"
            ufw allow 9000/tcp
            log "Configuring Portainer for IP Access (Port 9000)" "$YELLOW"
        fi
        
        docker run -d -p $BIND_IP:9000:9000 --name portainer --restart=always \
            -v /var/run/docker.sock:/var/run/docker.sock \
            -v portainer_data:/data \
            portainer/portainer-ce:latest
            
    else
        log "Portainer is already running." "$YELLOW"
    fi

    # 2. Configure Nginx for Portainer (If domain provided)
    if [ ! -z "$PORTAINER_DOMAIN" ]; then
        # SSL Selection for Portainer
        P_SSL_CERT=""
        P_SSL_KEY=""
        P_SSL_MODE="none"
        
        echo "Select SSL Type for Portainer:"
        echo "1) Custom SSL (You have your own .pem/.key files)"
        echo "2) Let's Encrypt (Automated via Certbot)"
        echo "3) None (HTTP only - Not Recommended)"
        read -p "Enter choice [1/2/3] (Default: 1): " P_SSL_CHOICE
        P_SSL_CHOICE=${P_SSL_CHOICE:-1}

        if [ "$P_SSL_CHOICE" == "2" ]; then
             P_SSL_MODE="letsencrypt"
             P_SSL_CERT="LETSENCRYPT_AUTO"
             P_SSL_KEY="LETSENCRYPT_AUTO"
        elif [ "$P_SSL_CHOICE" == "1" ]; then
             P_SSL_MODE="custom"
             
             # Check for Wildcard match
             if [[ $USE_WILDCARD_SSL =~ ^[Yy]$ ]]; then
                 read -p "Use the same Wildcard SSL for Portainer? (y/n): " USE_WC_PORTAINER
                 if [[ $USE_WC_PORTAINER =~ ^[Yy]$ ]]; then
                     P_SSL_CERT="$WILDCARD_CERT_PATH"
                     P_SSL_KEY="$WILDCARD_KEY_PATH"
                 fi
             fi
             
             if [ -z "$P_SSL_CERT" ]; then
                 # Custom SSL with default suggestion
                 DEFAULT_P_CERT="/etc/ssl/certs/${PORTAINER_DOMAIN}.pem"
                 DEFAULT_P_KEY="/etc/ssl/private/${PORTAINER_DOMAIN}.key"
                 
                 if [ -d "$HOME/certs" ]; then
                     DEFAULT_P_CERT="$HOME/certs/${PORTAINER_DOMAIN}.crt"
                     DEFAULT_P_KEY="$HOME/certs/${PORTAINER_DOMAIN}.key"
                 elif [ -d "/root/certs" ]; then
                     DEFAULT_P_CERT="/root/certs/${PORTAINER_DOMAIN}.crt"
                     DEFAULT_P_KEY="/root/certs/${PORTAINER_DOMAIN}.key"
                 fi

                 while true; do
                     read -e -p "Enter path to Portainer SSL Certificate [Default: $DEFAULT_P_CERT]: " P_SSL_CERT
                     P_SSL_CERT=${P_SSL_CERT:-$DEFAULT_P_CERT}
                     if [ ! -f "$P_SSL_CERT" ]; then
                         log "Error: File not found at $P_SSL_CERT" "$RED"
                         continue
                     fi
                     break
                 done

                while true; do
                    read -e -p "Enter path to Portainer SSL Private Key [Default: $DEFAULT_P_KEY]: " P_SSL_KEY
                    P_SSL_KEY=${P_SSL_KEY:-$DEFAULT_P_KEY}
                    if [ ! -f "$P_SSL_KEY" ]; then
                        log "Error: File not found at $P_SSL_KEY" "$RED"
                        continue
                    fi
                    break
                done
            fi
        else
            log "Warning: Portainer will be deployed without SSL." "$YELLOW"
        fi

        
        # Setup SSL Dir
        P_SSL_DIR="/etc/nginx/ssl/$PORTAINER_DOMAIN"
        mkdir -p "$P_SSL_DIR"

        if [ "$P_SSL_CERT" == "LETSENCRYPT_AUTO" ]; then
             log "Generating Let's Encrypt SSL for Portainer ($PORTAINER_DOMAIN)..." "$YELLOW"
             
             # Ensure Certbot installed
             if ! command -v certbot &> /dev/null; then
                 apt-get install -y certbot
             fi
             
             systemctl stop nginx 2>/dev/null
             
             certbot certonly --standalone -d "$PORTAINER_DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email
             
             LE_CERT="/etc/letsencrypt/live/$PORTAINER_DOMAIN/fullchain.pem"
             LE_KEY="/etc/letsencrypt/live/$PORTAINER_DOMAIN/privkey.pem"
             
            if [ -f "$LE_CERT" ]; then
                log "Portainer SSL Generated Successfully" "$GREEN"
                cp -L "$LE_CERT" "$P_SSL_DIR/fullchain.pem"
                cp -L "$LE_KEY" "$P_SSL_DIR/privkey.pem"
            else
                log "Error: Portainer Let's Encrypt generation failed." "$RED"
                # Fallback or exit? user might want to continue. Let's exit to be safe.
                exit 1
            fi
        else
            cp "$P_SSL_CERT" "$P_SSL_DIR/fullchain.pem"
            cp "$P_SSL_KEY" "$P_SSL_DIR/privkey.pem"
        fi
        
        chmod 600 "$P_SSL_DIR/privkey.pem"
        chmod 644 "$P_SSL_DIR/fullchain.pem"

        # Create Nginx Config
        cat <<EOF > "/etc/nginx/sites-available/$PORTAINER_DOMAIN"
server {
    listen 80;
    server_name $PORTAINER_DOMAIN;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $PORTAINER_DOMAIN;

    ssl_certificate $P_SSL_DIR/fullchain.pem;
    ssl_certificate_key $P_SSL_DIR/privkey.pem;
    
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers EECDH+AESGCM:EDH+AESGCM;
    ssl_prefer_server_ciphers on;
    
    location / {
        proxy_pass http://127.0.0.1:9000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
        ln -sf "/etc/nginx/sites-available/$PORTAINER_DOMAIN" "/etc/nginx/sites-enabled/"
        log "Portainer Nginx configuration created." "$GREEN"
    fi
fi

for i in "${!CONF_DOMAINS[@]}"; do
    DOMAIN="${CONF_DOMAINS[$i]}"
    BROKER="${CONF_BROKERS[$i]}"
    API_KEY="${CONF_API_KEYS[$i]}"
    API_SECRET="${CONF_API_SECRETS[$i]}"
    M_KEY="${CONF_MARKET_KEYS[$i]}"
    M_SECRET="${CONF_MARKET_SECRETS[$i]}"
    SSL_CERT="${CONF_SSL_CERTS[$i]}"
    SSL_KEY="${CONF_SSL_KEYS[$i]}"

    log "\nDeploying $DOMAIN..." "$BLUE"

    # 1. Allocation
    INSTANCE_DIR="$INSTALL_BASE/$DOMAIN"
    PORTS=($(get_next_ports))
    FLASK_PORT=${PORTS[0]}
    WS_PORT=${PORTS[1]}
    SANITIZED_NAME=$(sanitize_domain "$DOMAIN")
    PROJECT_NAME="openalgo-${SANITIZED_NAME}"

    log " -> Ports: Flask=$FLASK_PORT, WS=$WS_PORT" "$GREEN"
    log " -> Dir: $INSTANCE_DIR" "$GREEN"

    # 3. SSL Setup
    SSL_DIR="/etc/nginx/ssl/$DOMAIN"
    mkdir -p "$SSL_DIR"

    if [ "$SSL_CERT" == "LETSENCRYPT_AUTO" ]; then
        log "Generating Let's Encrypt SSL for $DOMAIN..." "$YELLOW"
        
        # Ensure Certbot installed
        if ! command -v certbot &> /dev/null; then
            log "Installing Certbot..." "$YELLOW"
            apt-get install -y certbot
        fi

        # Stop Nginx for standalone mode
        systemctl stop nginx 2>/dev/null
        
        # Run Certbot
        certbot certonly --standalone -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email
        
        LE_CERT="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"
        LE_KEY="/etc/letsencrypt/live/$DOMAIN/privkey.pem"
        
        if [ -f "$LE_CERT" ]; then
            log "Let's Encrypt Certificate Generated Successfully" "$GREEN"
            cp -L "$LE_CERT" "$SSL_DIR/fullchain.pem"
            cp -L "$LE_KEY" "$SSL_DIR/privkey.pem"
        else
            log "Error: Let's Encrypt generation failed." "$RED"
            exit 1
        fi
    else
        # Custom SSL
        cp "$SSL_CERT" "$SSL_DIR/fullchain.pem"
        cp "$SSL_KEY" "$SSL_DIR/privkey.pem"
    fi

    chmod 600 "$SSL_DIR/privkey.pem"
    chmod 644 "$SSL_DIR/fullchain.pem"
    
    # 4. Clone/Update Repo
    if [ ! -d "$INSTANCE_DIR/.git" ]; then
        if [ -d "$INSTANCE_DIR" ]; then
            log "Directory exists but is not a valid git repo. Backing up and re-cloning..." "$YELLOW"
            mv "$INSTANCE_DIR" "${INSTANCE_DIR}_backup_$(date +%s)"
        fi
        git clone "$REPO_URL" "$INSTANCE_DIR"
    else
        log "Updating existing repository..." "$GREEN"
        cd "$INSTANCE_DIR"
        # Force sync with the selected repo URL to pick up Dockerfile fixes
        git remote set-url origin "$REPO_URL"
        git fetch origin
        git reset --hard origin/main
    fi
    
    mkdir -p "$INSTANCE_DIR"/{log,logs,keys,db,strategies/scripts,strategies/examples}
    
    # 5. Env Config - CRITICAL: Preserve .env during updates to maintain passwords
    IS_UPDATE_MODE="${UPDATE_MODE[$i]}"
    ENV_FILE="$INSTANCE_DIR/.env"
    
    if [ "$IS_UPDATE_MODE" == "true" ] && [ -f "$ENV_FILE" ]; then
        log "Preserving existing .env file (keeps APP_KEY, PEPPER, and passwords valid)" "$GREEN"
        
        # Only update connectivity settings if needed (in case domain changed)
        # These are safe to update without breaking authentication
        sed -i "s|WEBSOCKET_URL='.*'|WEBSOCKET_URL='wss://$DOMAIN/ws'|g" "$ENV_FILE"
        
        # CORS: Add domain if not already present (preserves custom domains like chart.domain.com)
        # NOTE: Flask-CORS expects comma-separated origins (see cors.py line 25)
        if ! grep "CORS_ALLOWED_ORIGINS" "$ENV_FILE" | grep -q "https://$DOMAIN"; then
            # Extract current CORS value and append new domain with comma
            CURRENT_CORS=$(grep "CORS_ALLOWED_ORIGINS" "$ENV_FILE" | sed "s/.*= '\\(.*\\)'/\\1/")
            if [ -n "$CURRENT_CORS" ]; then
                NEW_CORS="$CURRENT_CORS,https://$DOMAIN"
                # Remove duplicates while preserving comma format
                NEW_CORS=$(echo "$NEW_CORS" | tr ',' '\n' | sort -u | tr '\n' ',' | sed 's/,$//')
                sed -i "s|CORS_ALLOWED_ORIGINS = '.*'|CORS_ALLOWED_ORIGINS = '$NEW_CORS'|g" "$ENV_FILE"
            fi
        fi
        
        # CSP: Add domain if not already present (preserves custom domains)
        if ! grep "CSP_CONNECT_SRC" "$ENV_FILE" | grep -q "https://$DOMAIN"; then
            CURRENT_CSP=$(grep "CSP_CONNECT_SRC" "$ENV_FILE" | sed 's/.*= "\\(.*\\)"/\\1/')
            if [ -n "$CURRENT_CSP" ] && ! echo "$CURRENT_CSP" | grep -q "https://$DOMAIN"; then
                NEW_CSP="$CURRENT_CSP https://$DOMAIN wss://$DOMAIN"
                sed -i "s|CSP_CONNECT_SRC = \".*\"|CSP_CONNECT_SRC = \"$NEW_CSP\"|g" "$ENV_FILE"
            fi
        fi
        
        log "Updated connectivity settings (preserved custom domains)" "$GREEN"
    else
        log "Creating new .env configuration..." "$YELLOW"
        cp "$INSTANCE_DIR/.sample.env" "$ENV_FILE"
        
        APP_KEY=$(generate_hex)
        PEPPER=$(generate_hex)
        
        sed -i "s|YOUR_BROKER_API_KEY|$API_KEY|g" "$ENV_FILE"
        sed -i "s|YOUR_BROKER_API_SECRET|$API_SECRET|g" "$ENV_FILE"
        sed -i "s|http://127.0.0.1:5000|https://$DOMAIN|g" "$ENV_FILE"
        sed -i "s|<broker>|$BROKER|g" "$ENV_FILE"
        sed -i "s|3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952e93d88bf07ea84|$APP_KEY|g" "$ENV_FILE"
        sed -i "s|a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772|$PEPPER|g" "$ENV_FILE"
        
        # XTS
        if [ ! -z "$M_KEY" ]; then
            sed -i "s|YOUR_BROKER_MARKET_API_KEY|$M_KEY|g" "$ENV_FILE"
            sed -i "s|YOUR_BROKER_MARKET_API_SECRET|$M_SECRET|g" "$ENV_FILE"
        fi
        
        # Connectivity
        sed -i "s|WEBSOCKET_URL='.*'|WEBSOCKET_URL='wss://$DOMAIN/ws'|g" "$ENV_FILE"
        sed -i "s|WEBSOCKET_HOST='127.0.0.1'|WEBSOCKET_HOST='0.0.0.0'|g" "$ENV_FILE"
        sed -i "s|ZMQ_HOST='127.0.0.1'|ZMQ_HOST='0.0.0.0'|g" "$ENV_FILE"
        sed -i "s|FLASK_HOST_IP='127.0.0.1'|FLASK_HOST_IP='0.0.0.0'|g" "$ENV_FILE"
        sed -i "s|CORS_ALLOWED_ORIGINS = '.*'|CORS_ALLOWED_ORIGINS = 'https://$DOMAIN'|g" "$ENV_FILE"
        sed -i "s|CSP_CONNECT_SRC = \"'self'.*\"|CSP_CONNECT_SRC = \"'self' wss://$DOMAIN https://$DOMAIN wss: ws: https://cdn.socket.io\"|g" "$ENV_FILE"
        
        log "New .env created with fresh security keys" "$GREEN"
    fi

    # 6. Docker Compose
    cat <<EOF > "$INSTANCE_DIR/docker-compose.yaml"
services:
  openalgo:
    image: ${PROJECT_NAME}:latest
    build:
      context: .
      dockerfile: Dockerfile
    container_name: ${PROJECT_NAME}-web
    ports:
      - "127.0.0.1:${FLASK_PORT}:5000"
      - "127.0.0.1:${WS_PORT}:8765"
    volumes:
      - openalgo_db:/app/db
      - openalgo_log:/app/log
      - openalgo_strategies:/app/strategies
      - openalgo_keys:/app/keys
      - openalgo_tmp:/app/tmp
      - ./.env:/app/.env:ro
    environment:
      - FLASK_ENV=production
      - FLASK_DEBUG=0
      - APP_MODE=standalone
      - TZ=Asia/Kolkata
      # Resource limits auto-calculated for multi-instance deployment
      # See: https://github.com/marketcalls/openalgo/issues/822
      - OPENBLAS_NUM_THREADS=${THREAD_LIMIT}
      - OMP_NUM_THREADS=${THREAD_LIMIT}
      - MKL_NUM_THREADS=${THREAD_LIMIT}
      - NUMEXPR_NUM_THREADS=${THREAD_LIMIT}
      - NUMBA_NUM_THREADS=${THREAD_LIMIT}
      - STRATEGY_MEMORY_LIMIT_MB=${STRATEGY_MEM_LIMIT}
    shm_size: '${SHM_SIZE_MB}m'
    healthcheck:
      test: ["CMD", "curl", "-f", "http://127.0.0.1:5000/auth/check-setup"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    restart: unless-stopped

volumes:
  openalgo_db:
    driver: local
  openalgo_log:
    driver: local
  openalgo_strategies:
    driver: local
  openalgo_keys:
    driver: local
  openalgo_tmp:
    driver: local
EOF

    # 7. Nginx Config
    cat <<EOF > "/etc/nginx/sites-available/$DOMAIN"
upstream openalgo_flask_${SANITIZED_NAME} {
    server 127.0.0.1:${FLASK_PORT};
    keepalive 64;
}

upstream openalgo_websocket_${SANITIZED_NAME} {
    server 127.0.0.1:${WS_PORT};
    keepalive 64;
}

server {
    listen 80;
    server_name $DOMAIN;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $DOMAIN;

    ssl_certificate $SSL_DIR/fullchain.pem;
    ssl_certificate_key $SSL_DIR/privkey.pem;
    
    # Modern SSL Config
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers EECDH+AESGCM:EDH+AESGCM;
    ssl_prefer_server_ciphers on;
    ssl_session_timeout 1d;
    ssl_session_cache shared:SSL:10m;
    
    # Security Headers
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    
    client_max_body_size 50M;

    # Logic: WebSocket
    location = /ws {
        proxy_pass http://openalgo_websocket_${SANITIZED_NAME};
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 86400s;
    }
    location /ws/ {
        proxy_pass http://openalgo_websocket_${SANITIZED_NAME}/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_read_timeout 86400s;
    }

    # Logic: Main App
    location / {
        proxy_pass http://openalgo_flask_${SANITIZED_NAME};
        proxy_http_version 1.1;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;

        # Increased buffer sizes for large headers (auth tokens, session cookies)
        proxy_buffer_size 128k;
        proxy_buffers 4 256k;
        proxy_busy_buffers_size 256k;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
    
    # Activate Nginx
    ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/"
    
    # 8. Service Start
    log "Starting Container for $DOMAIN..." "$BLUE"
    log "Building Docker image (includes automated frontend build, may take 2-5 minutes)..." "$YELLOW"
    cd "$INSTANCE_DIR"
    docker compose build
    docker compose up -d
    
done

# Restart Nginx to load new configs
log "Reloading Nginx..." "$YELLOW"
nginx -t && systemctl reload nginx
check_status "Nginx reload failed"


# -----------------
# Management Tool
# -----------------

cat <<'EOF' > /usr/local/bin/openalgo-ctl
#!/bin/bash
# OpenAlgo Manager

INSTALL_BASE="/opt/openalgo"

cmd=$1
target=$2

list_instances() {
    echo "INSTALLED INSTANCES:"
    echo "--------------------"
    for d in $INSTALL_BASE/*/; do
        [ -d "$d" ] || continue
        dom=$(basename "$d")
        # skip backup folders
        if [[ "$dom" == *"_backup_"* ]]; then
             continue
        fi
        status=$(cd "$d" && docker compose ps --format "{{.Status}}" 2>/dev/null)
        echo "$dom : ${status:-STOPPED}"
    done
}

usage() {
    echo "Usage: openalgo-ctl <command> [domain]"
    echo "Commands:"
    echo "  list              - List all instances"
    echo "  restart <domain>  - Restart specific instance"
    echo "  logs <domain>     - Show logs for instance"
    echo "  status <domain>   - Show status"
}

if [ "$cmd" == "list" ]; then
    list_instances
    exit 0
fi

if [ -z "$target" ]; then
    usage
    exit 1
fi

TARGET_DIR="$INSTALL_BASE/$target"
if [ ! -d "$TARGET_DIR" ]; then
    echo "Error: Instance $target not found."
    exit 1
fi

case "$cmd" in
    restart)
        cd "$TARGET_DIR" && docker compose restart
        ;;
    logs)
        cd "$TARGET_DIR" && docker compose logs -f --tail=100
        ;;
    status)
        cd "$TARGET_DIR" && docker compose ps
        ;;
    stop)
        cd "$TARGET_DIR" && docker compose stop
        ;;
    start)
        cd "$TARGET_DIR" && docker compose start
        ;;
    *)
        usage
        exit 1
        ;;
esac
EOF

chmod +x /usr/local/bin/openalgo-ctl


log "\n==============================================" "$GREEN"
log " INSTALLATION COMPLETE" "$GREEN"
log "==============================================" "$GREEN"
log "Management Command: openalgo-ctl" "$BLUE"
log "  openalgo-ctl list" "$BLUE"
log "  openalgo-ctl restart <domain.com>" "$BLUE"
log "  openalgo-ctl logs <domain.com>" "$BLUE"

log "\n[IMPORTANT] CLOUD FIREWALL SETTINGS:" "$YELLOW"
log "Ensure the following Inbound Ports are OPEN in your Azure NSG / AWS Security Group:" "$RED"
log "  - TCP 80 (HTTP)" "$NC"
log "  - TCP 443 (HTTPS)" "$NC"
log "  - TCP 22 (SSH)" "$NC"
if [[ $INSTALL_PORTAINER =~ ^[Yy]$ ]]; then
    if [ -z "$PORTAINER_DOMAIN" ]; then
        log "  - TCP 9000 (Portainer UI)" "$NC"
    fi
fi
log "\nAccess your instances via their respective HTTPS domains." "$GREEN"
