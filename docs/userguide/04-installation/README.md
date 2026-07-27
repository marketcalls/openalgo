# 04 - Installation Guide

## Introduction

This guide walks you through installing OpenAlgo on your system. We'll cover Windows, Ubuntu, and macOS installations.

## Quick Install (All Platforms)

If you're comfortable with command line, here's the fastest way:

```bash
# 1. Clone the repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# 2. Install UV package manager
pip install uv

# 3. Create configuration
cp .sample.env .env

# 4. Run OpenAlgo
uv run app.py
```

Open `http://127.0.0.1:5000` in your browser. That's it!

## Detailed Installation

### Windows Installation

#### Step 1: Install Python

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download Python 3.12 (or 3.11/3.13)
3. **Important**: Check "Add Python to PATH" during installation
4. Click "Install Now"

**Verify installation**:
```cmd
python --version
# Should show: Python 3.12.x
```

#### Step 2: Install Git

1. Go to [git-scm.com](https://git-scm.com/download/win)
2. Download and install with default options

**Verify installation**:
```cmd
git --version
# Should show: git version 2.x.x
```

#### Step 3: Download OpenAlgo

Open Command Prompt (search "cmd") and run:

```cmd
# Navigate to where you want OpenAlgo
cd C:\Users\YourName\Documents

# Clone the repository
git clone https://github.com/marketcalls/openalgo.git

# Enter the folder
cd openalgo
```

#### Step 4: Install UV Package Manager

```cmd
pip install uv
```

#### Step 5: Configure Environment

```cmd
# Create configuration file
copy .sample.env .env
```

**Edit the .env file** (use Notepad):
- Right-click `.env` → Open with → Notepad
- We'll configure this in the next chapter

#### Step 6: Run OpenAlgo

```cmd
uv run app.py
```

You should see:
```
* Running on http://127.0.0.1:5000
```

Open your browser and go to `http://127.0.0.1:5000`

### Ubuntu/Linux Installation

#### Step 1: Update System

```bash
sudo apt update && sudo apt upgrade -y
```

#### Step 2: Install Python and Dependencies

```bash
# Install Python and pip
sudo apt install python3.12 python3.12-venv python3-pip git -y

# Verify
python3.12 --version
```

#### Step 3: Download OpenAlgo

```bash
# Clone repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo
```

#### Step 4: Install UV and Configure

```bash
# Install UV
pip install uv

# Create configuration
cp .sample.env .env
```

#### Step 5: Run OpenAlgo

```bash
uv run app.py
```

Access at `http://your-server-ip:5000`

### macOS Installation

#### Step 1: Install Homebrew (if not installed)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

#### Step 2: Install Python and Git

```bash
brew install python@3.12 git
```

#### Step 3: Download and Run OpenAlgo

```bash
# Clone repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# Install UV
pip3 install uv

# Configure
cp .sample.env .env

# Run
uv run app.py
```

## Docker Local Development

For local development using Docker:

### Prerequisites

- Docker Engine
- Docker Compose
- Git

### Essential .env Changes for Docker

Update your `.env` file with these settings:

```ini
# Change from 127.0.0.1 to 0.0.0.0 for Docker
FLASK_HOST_IP='0.0.0.0'
FLASK_PORT='5000'

# WebSocket configuration
WEBSOCKET_HOST='0.0.0.0'
WEBSOCKET_PORT='8765'
WEBSOCKET_URL='ws://localhost:8765'

# ZeroMQ configuration
ZMQ_HOST='0.0.0.0'
ZMQ_PORT='5555'
```

**Why 0.0.0.0?**
- `127.0.0.1` only allows connections from within the container
- `0.0.0.0` allows connections from outside the container (host machine)

### Quick Start

```bash
# Clone repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# Create environment file
cp .sample.env .env
# Edit .env with the Docker settings above

# Build and start
docker-compose up --build
```

Access at `http://localhost:5000`

### Common Commands

```bash
# Start development server
docker-compose up

# Start in detached mode
docker-compose up -d

# View logs
docker-compose logs -f

# Stop containers
docker-compose down

# Rebuild after dependency changes
docker-compose up --build

# Enter container shell
docker-compose exec web bash
```

### Development Features

- Hot reload enabled (code changes reflect immediately)
- Debug mode active
- Console logging
- Volume mounting for live code updates

### Troubleshooting Docker

**Port Already In Use:**
```bash
sudo lsof -i :5000
docker-compose down
docker-compose up
```

**Database Issues:**
```bash
chmod -R 777 db/
```

**Rebuild Without Cache:**
```bash
docker-compose build --no-cache
docker-compose up
```

**Note**: This configuration is for development. For production, use the Docker Production Deployment section below or the Ubuntu Server installation

## Verifying Installation

### Check 1: Web Interface

Open browser → Go to `http://127.0.0.1:5000`

You should see the OpenAlgo login page.

### Check 2: API Docs

Go to `http://127.0.0.1:5000/api/docs`

You should see Swagger API documentation.

### Check 3: No Errors

Check terminal/command prompt for errors. Common issues:

**Port in use**:
```
Error: Address already in use
```
Solution: Change port in `.env` or stop other applications

**Python not found**:
```
'python' is not recognized
```
Solution: Reinstall Python with "Add to PATH" checked

## Folder Structure After Installation

```
openalgo/
├── app.py              # Main application
├── .env                # Your configuration (edit this)
├── .sample.env         # Example configuration
├── broker/             # Broker integrations
├── blueprints/         # Application routes
├── frontend/           # React frontend
├── database/           # Database models
├── db/                 # Database files (created on first run)
├── logs/               # Log files
└── ...
```

## Configuration Overview

The `.env` file contains all your settings. Key sections:

```ini
# Application Settings
FLASK_HOST=127.0.0.1
FLASK_PORT=5000

# Security (CHANGE THESE!)
APP_KEY=your-secret-key-here
API_KEY_PEPPER=your-pepper-here

# Broker Selection
BROKER=zerodha

# Broker Credentials
BROKER_API_KEY=your-api-key
BROKER_API_SECRET=your-api-secret
```

**Important**: Generate new APP_KEY and API_KEY_PEPPER:
```bash
uv run python -c "import secrets; print(secrets.token_hex(32))"
```

Run this twice - once for APP_KEY, once for API_KEY_PEPPER.

## Running OpenAlgo

### Development Mode (Default)

```bash
uv run app.py
```

Access at `http://127.0.0.1:5000`

## Production Deployment (Ubuntu Server)

For production use, deploy OpenAlgo on an Ubuntu server using the automated `install.sh` script. This is the **recommended approach** for live trading.

**Important**: The install script configures everything automatically:
- Nginx reverse proxy with SSL/TLS
- Let's Encrypt certificates (auto-renewal)
- Security headers (HSTS, X-Frame-Options, etc.)
- Firewall (UFW)
- Systemd service management

### Prerequisites

#### System Requirements

- Ubuntu Server (22.04 LTS or later recommended)
- Minimum 0.5GB RAM
- Clean installation recommended

#### Domain and DNS Setup (Required)

1. **Cloudflare Account Setup**
   - Create a Cloudflare account if you don't have one
   - Add your domain to Cloudflare
   - Update your domain's nameservers to Cloudflare's nameservers

2. **DNS Configuration**
   - Add an A record pointing to your server's IP address:
   ```
   Type: A
   Name: yourdomain.com
   Content: YOUR_SERVER_IP
   Proxy status: Proxied
   ```
   - Add a CNAME record for www (optional):
   ```
   Type: CNAME
   Name: www
   Content: yourdomain.com
   Proxy status: Proxied
   ```

3. **SSL/TLS Configuration in Cloudflare**
   - Go to SSL/TLS section
   - Set encryption mode to "Full (strict)"

#### Broker Setup (Required)

Prepare your broker credentials:
- API Key
- API Secret
- Redirection URL based on your domain and broker:

```
# Example: domain is yourdomain.com, broker is zerodha
https://yourdomain.com/zerodha/callback

# Example: domain is sub.yourdomain.com, broker is angel
https://sub.yourdomain.com/angel/callback
```

### Installation Steps

#### 1. Connect to Your Server

```bash
ssh user@your_server_ip
```

#### 2. Download Installation Script

```bash
mkdir -p ~/openalgo-install
cd ~/openalgo-install

wget https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install.sh

chmod +x install.sh
```

#### 3. Run Installation Script

```bash
sudo ./install.sh
```

The script will prompt you for:
- Your domain name (supports both root domains and subdomains)
- Broker selection
- Broker API credentials

### Multi-Domain Deployment

The installation script supports deploying multiple instances on the same server:

```bash
# First deployment
sudo ./install.sh
# Enter domain: trading1.yourdomain.com
# Enter broker: fyers

# Second deployment
sudo ./install.sh
# Enter domain: trading2.yourdomain.com
# Enter broker: zerodha
```

Each deployment gets:
- Unique service name (e.g., openalgo-yourdomain-broker)
- Separate configuration files and directories
- Individual log files
- Independent SSL certificates
- Isolated Python virtual environments

### Verify Installation

1. **Check Service Status**
   ```bash
   sudo systemctl status openalgo-yourdomain-broker
   ```

2. **Verify Nginx Configuration**
   ```bash
   sudo nginx -t
   ls -l /etc/nginx/sites-enabled/
   ```

3. **Access Web Interface**
   ```
   https://yourdomain.com
   ```

4. **Check Installation Logs**
   ```bash
   cat install/logs/install_YYYYMMDD_HHMMSS.log
   ```

### Managing Production Deployments

#### Service Management

```bash
# List all OpenAlgo services
systemctl list-units "openalgo-*"

# Restart specific deployment
sudo systemctl restart openalgo-yourdomain-broker

# View real-time logs
sudo journalctl -f -u openalgo-yourdomain-broker

# View last 100 lines of logs
sudo journalctl -n 100 -u openalgo-yourdomain-broker
```

#### Nginx Management

```bash
# View Nginx config
sudo nano /etc/nginx/sites-available/yourdomain.com

# Test Nginx configuration
sudo nginx -t

# Reload Nginx after config changes
sudo systemctl reload nginx
```

### Troubleshooting Production

#### SSL Certificate Issues

```bash
# Check Certbot logs
sudo journalctl -u certbot

# Manually run certificate installation
sudo certbot --nginx -d yourdomain.com
```

#### Application Not Starting

```bash
# View service logs
sudo journalctl -u openalgo-yourdomain-broker

# Restart service
sudo systemctl restart openalgo-yourdomain-broker
```

#### Nginx Issues

```bash
# Check Nginx error logs
sudo tail -f /var/log/nginx/error.log

# Check access logs
sudo tail -f /var/log/nginx/yourdomain.com.access.log
```

### Security (Auto-Configured)

The `install.sh` script automatically configures:

| Security Feature | Status |
|-----------------|--------|
| SSL/TLS (Let's Encrypt) | Auto-configured |
| Security Headers (HSTS, X-Frame-Options) | Auto-configured |
| Firewall (UFW - ports 22, 80, 443 only) | Auto-configured |
| Strong SSL ciphers (TLS 1.2/1.3) | Auto-configured |
| Random encryption keys | Auto-generated |
| File permissions | Auto-configured |

**Your tasks after installation**:
1. Set a strong login password
2. Enable Two-Factor Authentication
3. Keep your API key private

### Webhook Tunneling (Optional)

If you need to receive webhooks from TradingView, GoCharting, or ChartInk but don't have a domain, you can use tunneling services **for webhooks only**:

| Service | Command | Documentation |
|---------|---------|---------------|
| **ngrok** | `ngrok http 5000` | [ngrok.com](https://ngrok.com) |
| **devtunnel** (Microsoft) | `devtunnel host -p 5000` | [devtunnels.ms](https://aka.ms/devtunnels) |
| **Cloudflare Tunnel** | `cloudflared tunnel --url http://localhost:5000` | [cloudflare.com](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/) |

**Important**: Tunneling is **only for webhooks**. Always run OpenAlgo on your own server with proper domain setup for production use. Don't run the entire application through a tunnel.

```
┌────────────────────────────────────────────────────────────────┐
│              Production Deployment Model                        │
│                                                                 │
│  Your Ubuntu Server (install.sh)                               │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  Nginx (HTTPS) → Gunicorn → OpenAlgo                     │ │
│  │  • Dashboard access: https://yourdomain.com              │ │
│  │  • API access: https://yourdomain.com/api/v1/*           │ │
│  │  • WebSocket: wss://yourdomain.com/ws                    │ │
│  └──────────────────────────────────────────────────────────┘ │
│                           ▲                                    │
│                           │ Webhooks                           │
│               ┌───────────┴───────────┐                       │
│               │  TradingView          │                       │
│               │  GoCharting           │                       │
│               │  ChartInk             │                       │
│               │  Flow                 │                       │
│               └───────────────────────┘                       │
└────────────────────────────────────────────────────────────────┘
```

## Docker Deployment (Alternative)

OpenAlgo can also be deployed using Docker with custom domain and SSL. This is useful if you prefer containerized deployments.

### Quick Start

```bash
wget https://raw.githubusercontent.com/marketcalls/openalgo/refs/heads/main/install/install-docker.sh
chmod +x install-docker.sh
./install-docker.sh
```

### Prerequisites

- Ubuntu 20.04+ or Debian 11+
- Root access or sudo privileges
- Domain name pointed to your server IP
- Minimum 1GB RAM (2GB recommended)

### Installation Steps

**Option 1: Non-Root User (Recommended)**

```bash
# Create a non-root user if running as root
adduser openalgo
usermod -aG sudo openalgo
su - openalgo

# Download and run
wget https://raw.githubusercontent.com/marketcalls/openalgo/refs/heads/main/install/install-docker.sh
chmod +x install-docker.sh
./install-docker.sh
```

**Option 2: As Root User**

```bash
wget https://raw.githubusercontent.com/marketcalls/openalgo/refs/heads/main/install/install-docker.sh
chmod +x install-docker.sh
./install-docker.sh
```

The script will prompt you for:
- Domain name
- Broker selection
- API credentials
- Email for SSL notifications

### What the Script Does

1. Updates system packages
2. Installs Docker & Docker Compose
3. Installs Nginx web server
4. Installs Certbot for SSL
5. Clones OpenAlgo to `/opt/openalgo`
6. Configures environment variables
7. Sets up firewall (UFW)
8. Obtains SSL certificate
9. Configures Nginx with SSL and WebSocket support
10. Builds and starts Docker container

### Management Commands

```bash
# View application status
openalgo-status

# View live logs
openalgo-logs

# Restart application
openalgo-restart

# Create backup
openalgo-backup
```

### Docker Commands

```bash
cd /opt/openalgo

# Restart container
sudo docker compose restart

# View logs
sudo docker compose logs -f

# Rebuild from scratch
sudo docker compose down
sudo docker compose build --no-cache
sudo docker compose up -d
```

### File Locations

| Item | Location |
|------|----------|
| Installation | `/opt/openalgo` |
| Configuration | `/opt/openalgo/.env` |
| Database | Docker volume `openalgo_db` |
| Nginx Config | `/etc/nginx/sites-available/yourdomain.com` |
| SSL Certificates | `/etc/letsencrypt/live/yourdomain.com/` |
| Backups | `/opt/openalgo-backups/` |

### Architecture

```
┌─────────────────┐
│   Internet      │
└────────┬────────┘
         │ HTTPS (443)
         │
┌────────▼────────┐
│   Nginx         │ ← SSL/TLS, Reverse Proxy
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌───────┐ ┌──────────┐
│ Flask │ │WebSocket │ ← Docker Container
│ :5000 │ │  :8765   │   (openalgo-web)
└───────┘ └──────────┘
    │
    ▼
┌──────────┐
│ SQLite   │ ← Docker Volume
│ Database │
└──────────┘
```

### Updating Docker Deployment

```bash
cd /opt/openalgo

# Create backup first
openalgo-backup

# Stop container
sudo docker compose down

# Pull latest code
sudo git pull origin main

# Rebuild and restart
sudo docker compose build --no-cache
sudo docker compose up -d

# Verify
openalgo-status
```

## Raspberry Pi Installation

OpenAlgo can run on Raspberry Pi models 3, 4, or 5 (4GB+ RAM), preferably with Ubuntu 24.04+ server edition.

### Hardware Requirements

| Component | Requirement |
|-----------|-------------|
| Raspberry Pi Model | 3, 4, or 5 (minimum 4GB RAM) |
| SD Card | 128GB recommended, 64GB minimum |
| Operating System | Ubuntu 24.04+ Server edition |
| Power Supply | Official RPi adapter recommended |

### Initial System Preparation

#### 1. Flash OS to SD Card

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/) to prepare your SD card. Configure initial user, password, and Wi-Fi details.

#### 2. First Boot & Access

Connect via HDMI/keyboard or SSH:
```bash
ssh username@raspberry-pi-ip
```

#### 3. Setup Swap (Recommended: 2-4GB)

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Installation Options

#### Option 1: Official Install Script

Use the same `install.sh` script as Ubuntu Server:

```bash
mkdir -p ~/openalgo-install
cd ~/openalgo-install
wget https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install.sh
chmod +x install.sh
sudo ./install.sh
```

#### Option 2: Docker-Based Setup

**Install Docker:**
```bash
sudo apt-get update
sudo apt-get install ca-certificates curl gnupg
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```

**Clone and Build:**
```bash
git clone https://github.com/marketcalls/openalgo
cd openalgo
cp .sample.env .env
# Edit .env with your broker credentials
docker build -t openalgo:latest .
docker-compose up -d
```

### Securing Your Raspberry Pi

**Install fail2ban:**
```bash
sudo apt-get install fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

**Configure Firewall:**
```bash
sudo apt-get install iptables
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 443 -j ACCEPT
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
sudo iptables -A INPUT -j DROP
```

### Cloudflare Integration (Recommended)

For external access:
1. Register at [Cloudflare](https://www.cloudflare.com/)
2. Add your domain and point DNS to Cloudflare
3. Enable proxy status for your domain
4. Configure SSL/TLS to "Full (strict)"
5. Enable WAF and rate limiting for security

## Updating OpenAlgo

To get the latest version:

```bash
cd openalgo

# Stop OpenAlgo first

# Pull latest changes
git pull origin main

# Sync dependencies
uv sync

# Restart OpenAlgo
uv run app.py
```

## Troubleshooting Installation

### Issue: "Module not found"

```bash
# Sync dependencies
uv sync
```

### Issue: "Permission denied"

```bash
# Linux/Mac
chmod +x app.py
```

### Issue: "Database locked"

Close all OpenAlgo instances and restart.

### Issue: "Port 5000 in use"

```bash
# Find what's using port 5000
# Windows
netstat -ano | findstr :5000

# Linux/Mac
lsof -i :5000

# Either stop that process or change port in .env
```

## Next Steps

Installation complete! Now:

1. **First-Time Setup**: Configure your credentials
2. **Connect Broker**: Link your trading account
3. **Test with Analyzer**: Practice with sandbox capital

---

**Previous**: [03 - System Requirements](../03-system-requirements/README.md)

**Next**: [05 - First-Time Setup](../05-first-time-setup/README.md)
