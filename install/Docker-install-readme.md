# OpenAlgo Docker Installation Script

## Quick Start

This script provides a simplified, automated installation of OpenAlgo using Docker on Ubuntu/Debian systems with custom domain and SSL.

### One-Line Installation

```bash
wget https://raw.githubusercontent.com/marketcalls/openalgo/refs/heads/main/install/install-docker.sh && chmod +x install-docker.sh && ./install-docker.sh
```

### Prerequisites

- Fresh Ubuntu 20.04+ or Debian 11+ server
- Root access OR non-root user with sudo privileges
- Domain name pointed to your server IP
- Server with at least 1GB RAM (2GB recommended)

### Installation Steps

#### Option 1: As Non-Root User (Recommended)

```bash
# If you're logged in as root, create a non-root user first
adduser openalgo
usermod -aG sudo openalgo
su - openalgo

# Download and run the script
wget https://raw.githubusercontent.com/marketcalls/openalgo/refs/heads/main/install/install-docker.sh
chmod +x install-docker.sh
./install-docker.sh
```

#### Option 2: As Root User

```bash
# Download and run directly
wget https://raw.githubusercontent.com/marketcalls/openalgo/refs/heads/main/install/install-docker.sh
chmod +x install-docker.sh
./install-docker.sh
# (Confirm when prompted to proceed as root)
```

**Note:** While the script works as root, using a non-root user is recommended for better security in production environments.

### Follow the Prompts

The script will ask you for:
- Domain name (e.g., demo.openalgo.in)
- Broker name from the supported list
- Broker API credentials (key and secret)
- Market data credentials (for XTS brokers only)
- Email for SSL certificate notifications
- Confirmation to proceed

### What the Script Does

1. ✅ Updates system packages
2. ✅ Installs Docker & Docker Compose
3. ✅ Installs Nginx web server
4. ✅ Installs Certbot for SSL
5. ✅ Clones OpenAlgo repository to `/opt/openalgo`
6. ✅ Configures environment variables
7. ✅ Sets up firewall (UFW)
8. ✅ Obtains SSL certificate from Let's Encrypt
9. ✅ Configures Nginx with SSL and WebSocket support
10. ✅ Builds and starts Docker container
11. ✅ Creates management helper scripts

**Installation typically takes 5-10 minutes.**

### After Installation

1. Visit `https://yourdomain.com` in your browser
2. Create your admin account
3. Login to OpenAlgo
4. Complete broker authentication using OAuth

### Management Commands

The installation creates these helper commands:

```bash
# View application status
openalgo-status

# View live logs (follow mode)
openalgo-logs

# Restart application
openalgo-restart

# Create backup
openalgo-backup
```

### Docker Commands

```bash
# Navigate to installation directory
cd /opt/openalgo

# Restart container
sudo docker compose restart

# Stop container
sudo docker compose stop

# Start container
sudo docker compose start

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
| Application Logs | `/opt/openalgo/log` |
| Broker Logs | `/opt/openalgo/logs` |
| Nginx Config | `/etc/nginx/sites-available/yourdomain.com` |
| SSL Certificates | `/etc/letsencrypt/live/yourdomain.com/` |
| Backups | `/opt/openalgo-backups/` |

### Updating OpenAlgo

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

### Troubleshooting

**Container not starting:**
```bash
# Check container status
sudo docker ps -a

# View detailed logs
sudo docker compose logs -f

# Check container health
sudo docker inspect openalgo-web --format='{{.State.Health.Status}}'
```

**Permission errors with logs:**
```bash
# Fix log directory permissions
cd /opt/openalgo
sudo chown -R 1000:1000 log logs
sudo docker compose restart
```

**WebSocket connection issues:**
```bash
# Check if ports are listening
sudo netstat -tlnp | grep -E ':(5000|8765)'

# Test WebSocket connection
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  https://yourdomain.com/ws
```

**Nginx issues:**
```bash
# Test configuration
sudo nginx -t

# View error logs
sudo tail -f /var/log/nginx/yourdomain.com_error.log

# Restart Nginx
sudo systemctl restart nginx
```

**SSL certificate issues:**
```bash
# Test renewal
sudo certbot renew --dry-run

# Force renewal
sudo certbot renew --force-renewal

# Check certificate status
sudo certbot certificates
```

**Docker issues:**
```bash
# Check Docker status
sudo systemctl status docker

# Restart Docker
sudo systemctl restart docker

# View Docker logs
sudo journalctl -u docker -f
```

### Firewall Configuration

The script automatically configures UFW:
- **Port 22** (SSH) - Open
- **Port 80** (HTTP) - Open (for SSL renewal)
- **Port 443** (HTTPS) - Open
- **Ports 5000, 8765** - Only accessible via localhost (Docker ports)

### Security Best Practices

1. **Change default credentials** immediately after first login
2. **Keep system updated**: 
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```
3. **Monitor logs regularly**:
   ```bash
   openalgo-logs
   ```
4. **Setup automated backups**: Create a cron job
   ```bash
   # Backup daily at 2 AM
   crontab -e
   # Add: 0 2 * * * /usr/local/bin/openalgo-backup
   ```
5. **Use strong passwords** for your OpenAlgo account
6. **Never share broker credentials** with anyone
7. **Review firewall rules periodically**:
   ```bash
   sudo ufw status
   ```

### Cloudflare Setup (Optional)

For additional security and CDN benefits:

1. **Add domain to Cloudflare**
   - Sign up at cloudflare.com
   - Add your domain

2. **Update DNS**
   - In Cloudflare DNS settings:
   - Create A record pointing to your server IP
   - Enable proxy (orange cloud icon)

3. **Configure SSL/TLS**
   - Go to SSL/TLS settings
   - Set mode to **"Full (strict)"**
   - Enable "Always Use HTTPS"

4. **Enable WebSockets**
   - Go to Network settings
   - Enable "WebSockets"
   - Enable "HTTP/2"

5. **Security Settings** (Optional)
   - Enable "Under Attack Mode" if needed
   - Set up Page Rules for caching
   - Configure Firewall Rules

### Backup and Restore

**Create Backup:**
```bash
openalgo-backup
```
Backups are stored in `/opt/openalgo-backups/` and include:
- Database
- Configuration (.env file)
- Strategy files
- Last 7 backups are kept automatically

**Restore from Backup:**
```bash
# Stop container
cd /opt/openalgo
sudo docker compose stop

# Extract backup (replace TIMESTAMP with actual value)
sudo tar -xzf /opt/openalgo-backups/openalgo_backup_TIMESTAMP.tar.gz -C /opt/openalgo

# Fix permissions
sudo chown -R 1000:1000 log logs

# Start container
sudo docker compose start

# Verify
openalgo-status
```

### Complete Uninstallation

```bash
# Stop and remove container
cd /opt/openalgo
sudo docker compose down -v

# Remove installation directory
sudo rm -rf /opt/openalgo

# Remove backups (optional)
sudo rm -rf /opt/openalgo-backups

# Remove Nginx configuration
sudo rm /etc/nginx/sites-available/yourdomain.com
sudo rm /etc/nginx/sites-enabled/yourdomain.com
sudo systemctl reload nginx

# Remove SSL certificate
sudo certbot delete --cert-name yourdomain.com

# Remove management scripts
sudo rm /usr/local/bin/openalgo-*

# Optional: Remove Docker (if not needed for other apps)
sudo apt remove -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo rm -rf /var/lib/docker
```

### Getting Help

- **Documentation**: https://docs.openalgo.in
- **Discord Community**: https://discord.com/invite/UPh7QPsNhP
- **GitHub Issues**: https://github.com/marketcalls/openalgo/issues
- **YouTube Tutorials**: https://youtube.com/@openalgoHQ
- **Website**: https://openalgo.in

### Supported Brokers

| Broker | Code | XTS API |
|--------|------|---------|
| 5paisa | `fivepaisa` | No |
| 5paisa XTS | `fivepaisaxts` | Yes |
| AliceBlue | `aliceblue` | No |
| Angel One | `angel` | No |
| Compositedge | `compositedge` | Yes |
| Definedge | `definedge` | No |
| Dhan | `dhan` | No |
| Dhan Sandbox | `dhan_sandbox` | No |
| Firstock | `firstock` | No |
| Flattrade | `flattrade` | No |
| Fyers | `fyers` | No |
| Groww | `groww` | No |
| IBulls | `ibulls` | Yes |
| IIFL | `iifl` | Yes |
| IndMoney | `indmoney` | No |
| Kotak | `kotak` | No |
| Motilal Oswal | `motilal` | No |
| Paytm Money | `paytm` | No |
| Pocketful | `pocketful` | No |
| Shoonya | `shoonya` | No |
| Tradejini | `tradejini` | No |
| Upstox | `upstox` | No |
| Wisdom Capital | `wisdom` | Yes |
| Zebu | `zebu` | No |
| Zerodha | `zerodha` | No |

**Note:** XTS API brokers require additional market data API credentials during installation.

### System Requirements

**Minimum:**
- 1 vCPU
- 1GB RAM
- 10GB disk space
- Ubuntu 20.04+ or Debian 11+
- Internet connection

**Recommended:**
- 2 vCPU
- 2GB RAM
- 20GB SSD storage
- Ubuntu 22.04 LTS
- Stable internet connection

### Architecture

```
┌─────────────────┐
│   Internet      │
└────────┬────────┘
         │ HTTPS (443)
         │
┌────────▼────────┐
│   Nginx         │ ← SSL/TLS, Rate Limiting
│   Reverse Proxy │
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
│ Database │   (openalgo_db)
└──────────┘
```

### FAQ

**Q: Can I use this on a server with existing Nginx?**
A: Yes, but you may need to manually merge configurations to avoid conflicts.

**Q: Can I use a different port instead of 443?**
A: Yes, but you'll need to modify the Nginx configuration manually.

**Q: Will this work with a subdomain?**
A: Yes, the script supports both root domains and subdomains.

**Q: Can I run multiple OpenAlgo instances?**
A: Not with this script. Each installation assumes it's the only instance.

**Q: How do I change my broker after installation?**
A: Edit `/opt/openalgo/.env`, update broker credentials, then run `sudo docker compose restart`.

**Q: Is my broker data secure?**
A: Yes, all data is encrypted in transit (HTTPS/WSS) and stored locally on your server.

**Q: Can I use this in production?**
A: Yes, this script is designed for production use with SSL, security headers, and proper firewall configuration.

**Q: What if my domain doesn't have an A record yet?**
A: Wait for DNS propagation (usually 5-60 minutes) before running the script.

### Changelog

**Version 1.1.0** (October 19, 2024)
- Added support for running as root user (with warning)
- Fixed permission issues with docker-compose.yaml creation
- Improved error handling
- Enhanced management scripts

**Version 1.0.0** (Initial Release)
- Complete automated installation
- SSL certificate automation
- Docker containerization
- Management helper scripts

### License

OpenAlgo is released under the **AGPL V3.0 License**.

### Contributing

Contributions are welcome! Please see our [Contributing Guide](../CONTRIBUTING.md).

---

**Note**: This script is designed for fresh server installations. If you have an existing OpenAlgo installation or other applications on the server, please review the script and make necessary adjustments to avoid conflicts.

For production deployments, we strongly recommend:
1. Using a non-root user
2. Setting up automated backups
3. Monitoring logs regularly
4. Keeping the system updated
5. Using Cloudflare or similar CDN/DDoS protection

**Need help?** Join our [Discord community](https://discord.com/invite/UPh7QPsNhP) for support and discussions!