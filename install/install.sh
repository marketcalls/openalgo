#!/bin/bash

# OpenAlgo Installation and Configuration Script

# Color codes for better readability
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to check if command was successful
check_status() {
    if [ $? -ne 0 ]; then
        echo -e "${RED}Error: $1${NC}"
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
    local valid_brokers="fivepaisa,aliceblue,angel,dhan,fyers,icici,kotak,shoonya,upstox,zebu,zerodha"
    if [[ $valid_brokers == *"$broker"* ]]; then
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
        echo -e "${YELLOW}Warning: $name already exists at $path${NC}"
        read -p "Would you like to backup the existing $type? (y/n): " backup_choice
        if [[ $backup_choice =~ ^[Yy]$ ]]; then
            backup_path="${path}_backup_$(date +%Y%m%d_%H%M%S)"
            echo -e "${BLUE}Creating backup at $backup_path${NC}"
            sudo mv "$path" "$backup_path"
            check_status "Failed to create backup of $name"
            return 0
        else
            read -p "Would you like to remove the existing $type? (y/n): " remove_choice
            if [[ $remove_choice =~ ^[Yy]$ ]]; then
                echo -e "${BLUE}Removing existing $type...${NC}"
                if [ -d "$path" ]; then
                    sudo rm -rf "$path"
                else
                    sudo rm -f "$path"
                fi
                check_status "Failed to remove existing $type"
                return 0
            else
                echo -e "${RED}Installation cannot proceed without handling existing $type${NC}"
                exit 1
            fi
        fi
    fi
    return 0
}

# Collect installation parameters
echo -e "${BLUE}OpenAlgo Installation Configuration${NC}"
echo "----------------------------------------"

# Get domain name
while true; do
    read -p "Enter your domain name (e.g., opendash.app): " DOMAIN
    if [ -z "$DOMAIN" ]; then
        echo -e "${RED}Error: Domain name is required${NC}"
        continue
    fi
    # Basic domain validation
    if [[ ! $DOMAIN =~ ^[a-zA-Z0-9][a-zA-Z0-9-]{1,61}[a-zA-Z0-9]\.[a-zA-Z]{2,}$ ]]; then
        echo -e "${RED}Error: Invalid domain format. Please enter a valid domain name${NC}"
        continue
    fi
    break
done

# Get broker name
while true; do
    echo -e "\nValid brokers: fivepaisa, aliceblue, angel, dhan, fyers, icici, kotak, shoonya, upstox, zebu, zerodha"
    read -p "Enter your broker name: " BROKER_NAME
    if validate_broker "$BROKER_NAME"; then
        break
    else
        echo -e "${RED}Invalid broker name. Please choose from the list above.${NC}"
    fi
done

# Get broker API credentials
read -p "Enter your broker API key: " BROKER_API_KEY
read -p "Enter your broker API secret: " BROKER_API_SECRET

if [ -z "$BROKER_API_KEY" ] || [ -z "$BROKER_API_SECRET" ]; then
    echo -e "${RED}Error: Broker API credentials are required${NC}"
    exit 1
fi

# Generate random keys
APP_KEY=$(generate_hex)
API_KEY_PEPPER=$(generate_hex)

# Installation paths
OPENALGO_PATH="/var/python/openalgo-flask"
VENV_PATH="$OPENALGO_PATH/venv"
SOCKET_PATH="$OPENALGO_PATH"
SOCKET_FILE="$SOCKET_PATH/openalgo.sock"

echo -e "\n${YELLOW}Starting OpenAlgo installation...${NC}"

# Update system packages
echo -e "\n${BLUE}Updating system packages...${NC}"
sudo apt-get update && sudo apt-get upgrade -y
check_status "Failed to update system packages"

# Install required packages including Certbot
echo -e "\n${BLUE}Installing required packages...${NC}"
sudo apt-get install -y python3 python3-venv python3-pip nginx git software-properties-common
check_status "Failed to install required packages"

# Install Certbot
echo -e "\n${BLUE}Installing Certbot...${NC}"
sudo apt-get install -y certbot python3-certbot-nginx
check_status "Failed to install Certbot"

# Check and handle existing OpenAlgo installation
handle_existing "$OPENALGO_PATH" "installation directory" "OpenAlgo directory"

# Create OpenAlgo directory and clone repository
echo -e "\n${BLUE}Creating OpenAlgo directory and cloning repository...${NC}"
sudo mkdir -p $OPENALGO_PATH
sudo git clone https://github.com/marketcalls/openalgo.git $OPENALGO_PATH
check_status "Failed to clone OpenAlgo repository"

# Create and activate virtual environment
echo -e "\n${BLUE}Setting up Python virtual environment...${NC}"
if [ -d "$VENV_PATH" ]; then
    echo -e "${YELLOW}Warning: Virtual environment already exists, removing...${NC}"
    sudo rm -rf "$VENV_PATH"
fi
sudo python3 -m venv $VENV_PATH
check_status "Failed to create virtual environment"

# Install Python dependencies
echo -e "\n${BLUE}Installing Python dependencies...${NC}"
sudo $VENV_PATH/bin/pip install eventlet gunicorn
check_status "Failed to install Python dependencies"

# Configure .env file
echo -e "\n${BLUE}Configuring environment file...${NC}"
handle_existing "$OPENALGO_PATH/.env" "environment file" ".env file"

sudo cp $OPENALGO_PATH/.sample.env $OPENALGO_PATH/.env
sudo sed -i "s|YOUR_BROKER_API_KEY|$BROKER_API_KEY|g" $OPENALGO_PATH/.env
sudo sed -i "s|YOUR_BROKER_API_SECRET|$BROKER_API_SECRET|g" $OPENALGO_PATH/.env
sudo sed -i "s|http://127.0.0.1:5000|https://$DOMAIN|g" $OPENALGO_PATH/.env
sudo sed -i "s|3daa0403ce2501ee7432b75bf100048e3cf510d63d2754f952e93d88bf07ea84|$APP_KEY|g" $OPENALGO_PATH/.env
sudo sed -i "s|a25d94718479b170c16278e321ea6c989358bf499a658fd20c90033cef8ce772|$API_KEY_PEPPER|g" $OPENALGO_PATH/.env
check_status "Failed to configure environment file"

# Check and handle existing Nginx configuration
handle_existing "/etc/nginx/sites-available/$DOMAIN" "Nginx configuration" "Nginx config file"

# Configure initial Nginx for SSL certificate obtention
echo -e "\n${BLUE}Configuring initial Nginx setup...${NC}"
sudo tee /etc/nginx/sites-available/$DOMAIN > /dev/null << EOL
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN www.$DOMAIN;
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
echo -e "\n${BLUE}Testing and reloading Nginx...${NC}"
sudo nginx -t && sudo systemctl reload nginx
check_status "Failed to reload Nginx"

# Configure UFW firewall
echo -e "\n${BLUE}Configuring firewall rules...${NC}"
sudo apt-get install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
check_status "Failed to configure firewall"

# Obtain SSL certificate
echo -e "\n${BLUE}Obtaining SSL certificate...${NC}"
sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN --non-interactive --agree-tos --email admin@$DOMAIN
check_status "Failed to obtain SSL certificate"

# Configure final Nginx setup with SSL and socket
echo -e "\n${BLUE}Configuring final Nginx setup...${NC}"
sudo tee /etc/nginx/sites-available/$DOMAIN > /dev/null << EOL
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN www.$DOMAIN;

    location / {
        return 301 https://\$host\$request_uri;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    
    server_name $DOMAIN www.$DOMAIN;
    
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
    
    location / {
        proxy_pass http://unix:$SOCKET_FILE;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_redirect off;
        
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOL

# Test Nginx configuration
echo -e "\n${BLUE}Testing Nginx configuration...${NC}"
sudo nginx -t
check_status "Failed to validate Nginx configuration"

# Check and handle existing systemd service
handle_existing "/etc/systemd/system/openalgo.service" "systemd service" "OpenAlgo service file"

# Create systemd service
echo -e "\n${BLUE}Creating systemd service...${NC}"
sudo tee /etc/systemd/system/openalgo.service > /dev/null << EOL
[Unit]
Description=OpenAlgo Gunicorn Daemon
After=network.target

[Service]
WorkingDirectory=$OPENALGO_PATH
Environment="PATH=$VENV_PATH/bin"
ExecStart=$VENV_PATH/bin/gunicorn \
    --worker-class eventlet \
    -w 1 \
    --bind unix:$SOCKET_FILE \
    app:app

[Install]
WantedBy=multi-user.target
EOL
check_status "Failed to create systemd service"

# Set correct permissions
echo -e "\n${BLUE}Setting permissions...${NC}"
sudo chown -R www-data:www-data $OPENALGO_PATH
sudo chmod -R 755 $OPENALGO_PATH
sudo touch $SOCKET_FILE
sudo chown www-data:www-data $SOCKET_FILE
sudo chmod 660 $SOCKET_FILE
check_status "Failed to set permissions"

# Reload systemd and start services
echo -e "\n${BLUE}Starting services...${NC}"
sudo systemctl daemon-reload
sudo systemctl enable openalgo
sudo systemctl start openalgo
sudo systemctl restart nginx
check_status "Failed to start services"

echo -e "\n${GREEN}Installation completed successfully!${NC}"
echo -e "\n${YELLOW}Installation Summary:${NC}"
echo -e "${BLUE}Domain:${NC} $DOMAIN"
echo -e "${BLUE}Broker:${NC} $BROKER_NAME"
echo -e "${BLUE}Installation Directory:${NC} $OPENALGO_PATH"
echo -e "${BLUE}Environment File:${NC} $OPENALGO_PATH/.env"
echo -e "${BLUE}Socket File:${NC} $SOCKET_FILE"
echo -e "${BLUE}Nginx Config:${NC} /etc/nginx/sites-available/$DOMAIN"
echo -e "${BLUE}SSL:${NC} Enabled with Let's Encrypt"

echo -e "\n${YELLOW}Next Steps:${NC}"
echo -e "1. ${GREEN}Visit https://$DOMAIN to access your OpenAlgo instance${NC}"
echo -e "2. ${GREEN}Configure your broker settings in the web interface${NC}"
echo -e "3. ${GREEN}Review the logs using: sudo journalctl -u openalgo${NC}"
echo -e "4. ${GREEN}Monitor the application status: sudo systemctl status openalgo${NC}"

echo -e "\n${YELLOW}Useful Commands:${NC}"
echo -e "${BLUE}Restart OpenAlgo:${NC} sudo systemctl restart openalgo"
echo -e "${BLUE}View Logs:${NC} sudo journalctl -u openalgo"
echo -e "${BLUE}Check Status:${NC} sudo systemctl status openalgo"
