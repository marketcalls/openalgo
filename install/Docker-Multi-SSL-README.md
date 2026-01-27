# OpenAlgo Advanced Docker Installation (Multi-Instance & Custom SSL)

This guide covers the advanced installation script (`install-docker-multi-custom-ssl.sh`), which is designed for power users who need:
- **Multiple OpenAlgo instances** on a single server.
- **Custom SSL Certificates** (e.g., Wildcard SSLs).
- **Portainer** for container management.
- **Robust Healthchecks** and automatic error recovery.

## Quick Start

Run the following command on your Ubuntu 20.04+ or Debian 11+ server:

```bash
wget https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install-docker-multi-custom-ssl.sh
chmod +x install-docker-multi-custom-ssl.sh
./install-docker-multi-custom-ssl.sh
```

## Prerequisites

- **OS**: Ubuntu 20.04+ LTS (Recommended: Ubuntu 24.04 LTS for Azure ARM64)
- **Permissions**: Root access or `sudo` privileges.
- **Domain**: A valid domain pointed to your server IP.
- **Ports**: 80, 443 (Server), 9000 (Portainer - Optional), 22 (SSH).

## Installation Features

When you run the script, it will interactively prompt you for:

1.  **Instance Name**:
    - You can give each installation a unique name (e.g., `algo1`, `fyers-bot`).
    - This allows you to run multiple independent copies of OpenAlgo side-by-side.

2.  **Domain & Broker**:
    - Choose your domain (e.g., `bot1.example.com`).
    - Select your broker and provide API credentials.

3.  **SSL Configuration**:
    - **Let's Encrypt**: Auto-generate free SSL certificates.
    - **Custom SSL**: Provide paths to your existing `.pem` and `.key` files (Great for Wildcard SSLs).

4.  **Portainer Management UI**:
    - Option to install Portainer to manage your Docker containers visually.
    - Can be exposed on a subdomain (e.g., `portainer.example.com`) or via IP (`http://IP:9000`).

## Setting Up Portainer (Important)

If you chose to install Portainer, follow these steps immediately after installation:

1.  **Access Portainer**:
    - Open your browser and navigate to the domain you configured (e.g., `https://portainer.example.com`) or `http://YOUR_SERVER_IP:9000`.

2.  **Create Admin User**:
    - You will be asked to create an initial admin username and password.
    - **Note:** For security, Portainer creates a timeout window for this initial setup.

### **Restarting Portainer (If Setup Times Out)**

If you wait too long to configure Portainer after installation, you may be locked out of the initial setup screen. To fix this, you must restart the container to reset the setup window:

```bash
# Restart the Portainer container
docker restart portainer
```

After running this command, refresh your browser immediately and set up your username and password.

## Managing Multiple Instances

Since this script supports multiple instances, docker compose commands need to be run in the specific instance directory.

**Directory Structure:**
```
/opt/
  ├── openalgo-algo1/       # Instance 1
  │   ├── docker-compose.yaml
  │   └── .env
  └── openalgo-fyers-bot/   # Instance 2 (Different Broker/Strategy)
      ├── docker-compose.yaml
      └── .env
```

**Managing a Specific Instance:**
```bash
# Go to the instance directory
cd /opt/openalgo-algo1

# Start/Stop/Restart
docker compose up -d
docker compose stop
docker compose restart

# View Logs
docker compose logs -f
```

## Updating Existing Instances

When you run the script with existing domains, it will detect them and offer smart update options:

```
Instance for domain.com already exists. Update code only? (y=update, n=skip, r=reinstall):
```

| Option | Behavior |
|--------|----------|
| **y (Update)** | Pulls latest code, preserves `.env` file (passwords remain valid), skips all config prompts |
| **n (Skip)** | Skips this domain entirely |
| **r (Reinstall)** | Fresh install with new config (⚠️ regenerates security keys, invalidates existing passwords) |

### What Gets Preserved During Updates

When you choose **Update (y)**:
- ✅ `.env` file (APP_KEY, PEPPER, broker credentials)
- ✅ User passwords and login sessions
- ✅ SSL certificates
- ✅ Database (stored in Docker volumes)

### Portainer Smart Detection

If Portainer is already running, the script will:
1. Detect the existing installation
2. Offer to check for version updates
3. Skip redundant configuration prompts

## Troubleshooting

1.  **Healthcheck Failures**:
    - If the container shows `unhealthy`, ensure your `Dockerfile` includes `curl`. This script automatically patches standard Dockerfiles to include it.

2.  **SSL Errors**:
    - If using Custom SSL, ensure your `.pem` file supports the full chain and your `.key` file is unencrypted.
    - Check Nginx logs: `tail -f /var/log/nginx/error.log`

3.  **WebSocket 403 Errors**:
    - If you experience disconnects after broker re-login, restart the specific instance:
      ```bash
      cd /opt/openalgo-INSTANCE_NAME
      docker compose restart
      ```
