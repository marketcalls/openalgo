# 12 - Ubuntu Server Installation

## Overview

This guide covers deploying OpenAlgo on an Ubuntu server (20.04/22.04 LTS) with Nginx reverse proxy, systemd services, and SSL configuration for production use.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Ubuntu Server Architecture                            │
└──────────────────────────────────────────────────────────────────────────────┘

                         Internet
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Nginx (Reverse Proxy)                               │
│                          Port 80/443                                         │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  - SSL termination (Let's Encrypt)                                   │   │
│  │  - HTTP → HTTPS redirect                                             │   │
│  │  - WebSocket upgrade support                                         │   │
│  │  - Static file serving                                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                    │                       │
                    ▼                       ▼
┌─────────────────────────────────────────────────────┐
│           OpenAlgo (Gunicorn + WebSocket)           │
│                                                     │
│  Flask App ─────────── localhost:5000               │
│  WebSocket Thread ──── localhost:8765               │
│                                                     │
│  systemd: openalgo                                  │
└─────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          File System                                         │
│                                                                              │
│  /opt/openalgo/                                                             │
│  ├── .venv/              # Virtual environment                              │
│  ├── db/                 # SQLite databases                                 │
│  ├── log/                # Application logs                                 │
│  ├── strategies/         # User strategies                                  │
│  ├── .env                # Configuration                                    │
│  └── app.py              # Main application                                 │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Prerequisites

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install required packages
sudo apt install -y python3.12 python3.12-venv python3-pip \
                    nginx certbot python3-certbot-nginx \
                    git curl build-essential

# Install Node.js (for frontend build)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

## Installation Steps

### 1. Clone Repository

```bash
# Create application directory
sudo mkdir -p /opt/openalgo
sudo chown $USER:$USER /opt/openalgo

# Clone repository
cd /opt/openalgo
git clone https://github.com/marketcalls/openalgo.git .
```

### 2. Setup Python Environment

```bash
# Install uv package manager
pip install uv

# Create virtual environment and install dependencies
uv venv .venv
source .venv/bin/activate
uv sync

# Install production dependencies
uv pip install gunicorn eventlet==0.35.2
```

### 3. Configure Environment

```bash
# Copy sample environment file
cp .sample.env .env

# Generate secure keys
python -c "import secrets; print(secrets.token_hex(32))"
# Copy output to APP_KEY and API_KEY_PEPPER in .env

# Edit configuration
nano .env
```

### 4. Build Frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

### 5. Create Systemd Service

**Note:** The WebSocket server runs as a thread inside the main app (port 8765), so only ONE systemd service is needed.

```bash
sudo nano /etc/systemd/system/openalgo.service
```

```ini
[Unit]
Description=OpenAlgo Trading Platform
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/openalgo
Environment="PATH=/opt/openalgo/.venv/bin"
ExecStart=/opt/openalgo/.venv/bin/gunicorn \
    --worker-class eventlet \
    -w 1 \
    --bind 127.0.0.1:5000 \
    --timeout 120 \
    app:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Important:** Use `-w 1` (single worker) for WebSocket compatibility.

### 6. Set Permissions

```bash
# Set ownership
sudo chown -R www-data:www-data /opt/openalgo

# Set permissions
sudo chmod -R 755 /opt/openalgo
sudo chmod 700 /opt/openalgo/keys
sudo chmod 600 /opt/openalgo/.env
```

### 7. Configure Nginx

```bash
sudo nano /etc/nginx/sites-available/openalgo
```

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL certificates (Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

    # SSL configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;

    # Main application
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support for Socket.IO
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }

    # WebSocket proxy
    location /ws {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }

    # Static files
    location /static {
        alias /opt/openalgo/static;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

### 8. Enable Service

```bash
# Enable Nginx site
sudo ln -s /etc/nginx/sites-available/openalgo /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx

# Enable and start OpenAlgo service
sudo systemctl daemon-reload
sudo systemctl enable openalgo
sudo systemctl start openalgo
```

### 9. Setup SSL (Let's Encrypt)

```bash
sudo certbot --nginx -d your-domain.com
```

## Service Management

```bash
# Check status
sudo systemctl status openalgo

# View logs
sudo journalctl -u openalgo -f

# Restart service
sudo systemctl restart openalgo

# Stop service
sudo systemctl stop openalgo
```

## Firewall Configuration

```bash
# Enable firewall
sudo ufw enable

# Allow required ports
sudo ufw allow 22/tcp     # SSH
sudo ufw allow 80/tcp     # HTTP
sudo ufw allow 443/tcp    # HTTPS

# Check status
sudo ufw status
```

## Update Procedure

```bash
# Stop service
sudo systemctl stop openalgo

# Pull updates
cd /opt/openalgo
git pull origin main

# Update dependencies
source .venv/bin/activate
uv sync

# Rebuild frontend
cd frontend
npm install
npm run build
cd ..

# Start service
sudo systemctl start openalgo
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| 502 Bad Gateway | Check if OpenAlgo service is running: `systemctl status openalgo` |
| WebSocket fails | Check Nginx /ws proxy config and service logs |
| Permission denied | Verify www-data ownership: `chown -R www-data:www-data /opt/openalgo` |
| SSL error | Renew certificates: `sudo certbot renew` |

## Key Files Reference

| File | Purpose |
|------|---------|
| `/etc/systemd/system/openalgo.service` | Main service (includes WebSocket) |
| `/etc/nginx/sites-available/openalgo` | Nginx config |
| `/opt/openalgo/.env` | Application config |
| `/var/log/nginx/` | Nginx logs |

**Note:** There is no separate `openalgo-ws.service`. The WebSocket server runs as a thread inside the main Flask application on port 8765.
