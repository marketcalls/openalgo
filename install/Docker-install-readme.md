# OpenAlgo Docker Installation Script

## Quick Start

This script provides a simplified, automated installation of OpenAlgo using Docker on Ubuntu/Debian systems with custom domain and SSL.

### Prerequisites

- Fresh Ubuntu 20.04+ or Debian 11+ server
- Root or sudo access
- Domain name pointed to your server IP
- Server with at least 1GB RAM (2GB recommended)

### Installation Steps

1. **Download the script:**
```bash
wget https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install-docker.sh
chmod +x install-docker.sh
```

2. **Run the installation:**
```bash
./install-docker.sh
```

3. **Follow the prompts:**
   - Enter your domain name (e.g., demo.openalgo.in)
   - Select your broker from the list
   - Enter broker API credentials
   - Enter email for SSL notifications
   - Confirm installation

### What the Script Does

1. ✅ Updates system packages
2. ✅ Installs Docker & Docker Compose
3. ✅ Installs Nginx web server
4. ✅ Installs Certbot for SSL
5. ✅ Clones OpenAlgo repository
6. ✅ Configures environment variables
7. ✅ Sets up firewall (UFW)
8. ✅ Obtains SSL certificate
9. ✅ Configures Nginx with SSL
10. ✅ Builds and starts Docker container
11. ✅ Creates management scripts

### After Installation

Visit `https://yourdomain.com` to:
1. Create your admin account
2. Login to OpenAlgo
3. Complete broker authentication

### Management Commands

```bash
# View status
openalgo-status

# View logs (follow mode)
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

- **Installation**: `/opt/openalgo`
- **Configuration**: `/opt/openalgo/.env`
- **Database**: Docker volume `openalgo_db`
- **Logs**: `/opt/openalgo/log` and `/opt/openalgo/logs`
- **Nginx Config**: `/etc/nginx/sites-available/yourdomain.com`
- **SSL Certs**: `/etc/letsencrypt/live/yourdomain.com/`
- **Backups**: `/opt/openalgo-backups/`

### Updating OpenAlgo

```bash
cd /opt/openalgo

# Stop container
sudo docker compose down

# Backup current installation
openalgo-backup

# Pull latest code
sudo git pull origin main

# Rebuild and restart
sudo docker compose build --no-cache
sudo docker compose up -d
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

**WebSocket connection issues:**
```bash
# Check if ports are listening
sudo netstat -tlnp | grep -E ':(5000|8765)'

# Test WebSocket
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

**Permission errors:**
```bash
# Fix log directory permissions
cd /opt/openalgo
sudo chown -R 1000:1000 log logs
sudo docker compose restart
```

**SSL certificate renewal:**
```bash
# Test renewal
sudo certbot renew --dry-run

# Force renewal
sudo certbot renew --force-renewal
```

### Firewall Configuration

The script automatically configures UFW:
- Port 22 (SSH) - Open
- Port 80 (HTTP) - Open (for SSL renewal)
- Port 443 (HTTPS) - Open
- Ports 5000, 8765 - Only accessible via localhost

### Security Notes

1. **Change default credentials** immediately after first login
2. **Keep system updated**: `sudo apt update && sudo apt upgrade`
3. **Monitor logs** regularly: `openalgo-logs`
4. **Backup regularly**: Set up cron job for `openalgo-backup`
5. **Use strong API keys** - never share your broker credentials

### Cloudflare Setup (Optional)

After installation, you can add Cloudflare:

1. Add your domain to Cloudflare
2. Update DNS to Cloudflare nameservers
3. In Cloudflare DNS:
   - Set A record to your server IP
   - Enable proxy (orange cloud)
4. In Cloudflare SSL/TLS:
   - Set mode to "Full (strict)"
   - Enable "Always Use HTTPS"
5. In Cloudflare Network:
   - Enable "WebSockets"

### Backup and Restore

**Create backup:**
```bash
openalgo-backup
```

**Restore from backup:**
```bash
cd /opt/openalgo
sudo docker compose stop

# Extract backup (replace TIMESTAMP)
sudo tar -xzf /opt/openalgo-backups/openalgo_backup_TIMESTAMP.tar.gz -C /opt/openalgo

# Fix permissions
sudo chown -R 1000:1000 log logs

# Restart
sudo docker compose start
```

### Uninstallation

```bash
# Stop and remove container
cd /opt/openalgo
sudo docker compose down -v

# Remove installation
sudo rm -rf /opt/openalgo

# Remove Nginx configuration
sudo rm /etc/nginx/sites-available/yourdomain.com
sudo rm /etc/nginx/sites-enabled/yourdomain.com
sudo systemctl reload nginx

# Remove SSL certificate
sudo certbot delete --cert-name yourdomain.com

# Remove management scripts
sudo rm /usr/local/bin/openalgo-*

# Optional: Remove Docker
sudo apt remove docker-ce docker-ce-cli containerd.io
```

### Getting Help

- **Documentation**: https://docs.openalgo.in
- **Discord**: https://discord.com/invite/UPh7QPsNhP
- **GitHub Issues**: https://github.com/marketcalls/openalgo/issues
- **YouTube**: https://youtube.com/@openalgoHQ

### Supported Brokers

- 5paisa, 5paisa XTS, AliceBlue, Angel One
- Compositedge, Definedge, Dhan, Dhan Sandbox
- Firstock, Flattrade, Fyers, Groww
- IBulls, IIFL, IndMoney, Kotak
- Motilal Oswal, Paytm, Pocketful, Shoonya
- Tradejini, Upstox, Wisdom Capital, Zebu, Zerodha

### System Requirements

**Minimum:**
- 1 vCPU
- 1GB RAM (2GB with swap recommended)
- 10GB disk space
- Ubuntu 20.04+ or Debian 11+

**Recommended:**
- 2 vCPU
- 2GB RAM
- 20GB disk space
- SSD storage

### License

OpenAlgo is released under the AGPL V3.0 License.

---

**Note**: This script is designed for fresh installations. If you have an existing OpenAlgo installation, backup your data before running this script.