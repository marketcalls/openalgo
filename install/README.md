# OpenAlgo Installation Guide

## Prerequisites

### System Requirements
- **Supported Linux Distributions:**
  - **Debian-based:** Ubuntu (22.04+ LTS), Debian, Raspbian, Pop!_OS, Linux Mint, Zorin OS
  - **RHEL-based:** CentOS, RHEL, Fedora, Rocky Linux, AlmaLinux, Amazon Linux, Oracle Linux
  - **Arch-based:** Arch Linux, Manjaro, EndeavourOS, CachyOS
- Minimum 2GB RAM (script will configure swap if needed)
- Clean installation recommended

### Domain and DNS Setup (Required)
1. **Cloudflare Account Setup**
   - Create a Cloudflare account if you don't have one
   - Add your domain to Cloudflare
   - Update your domain's nameservers to Cloudflare's nameservers

2. **DNS Configuration**
   - Add an A record pointing to your server's IP address
     ```
     Type: A
     Name: yourdomain.com
     Content: YOUR_SERVER_IP
     Proxy status: Proxied
     ```
   - Add a CNAME record for www subdomain
     ```
     Type: CNAME
     Name: www
     Content: yourdomain.com
     Proxy status: Proxied
     ```

3. **SSL/TLS Configuration in Cloudflare**
   - Go to SSL/TLS section
   - Set encryption mode to "Full (strict)"

### Broker Setup (Required)
- Choose your broker from the supported list:
  ```
  fivepaisa, aliceblue, angel, dhan, fyers, icici, kotak, shoonya, upstox, zebu, zerodha
  ```
- Obtain your broker's API credentials:
  - API Key
  - API Secret

## Installation Steps

### 1. Download Installation Script
```bash
# Connect to your Linux server via SSH
ssh user@your_server_ip

# Create a directory for installation
mkdir -p ~/openalgo-install
cd ~/openalgo-install

# Download the installation script
wget https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install.sh

# Or using curl
curl -O https://raw.githubusercontent.com/marketcalls/openalgo/main/install/install.sh

# Make the script executable
chmod +x install.sh
```

### 2. Run Installation Script
```bash
# Execute the installation script
sudo ./install.sh
```

The script will interactively prompt you for:
- Your domain name (supports both root domains and subdomains)
- Broker selection
- Broker API credentials

The installation process will:
- **Detect your Linux distribution** and use appropriate package managers
- Install required packages (Python, Nginx, Git, Certbot, UV)
- Configure system swap memory if needed (for systems with <2GB RAM)
- Set timezone to IST (optional)
- Configure firewall (UFW for Debian/Arch, firewalld for RHEL)
- **Auto-configure SELinux** on RHEL-based systems
- Obtain and install Let's Encrypt SSL certificate
- Configure Nginx with SSL and WebSocket support
- Set up the OpenAlgo application with unique deployment name
- Create systemd service with unique name based on domain and broker
- Generate detailed installation logs in the logs directory

#### Multi-Domain Deployment
The installation script supports deploying multiple instances on the same server:
- Each deployment gets a unique service name (e.g., openalgo-yourdomain-broker)
- Separate configuration files and directories for each deployment
- Individual log files for each installation in the logs directory
- Independent SSL certificates for each domain
- Isolated Python virtual environments

Example of running multiple deployments:
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

Each deployment will:
- Have its own systemd service
- Use separate configuration files
- Store logs in unique timestamped files
- Run independently of other deployments

### 3. Verify Installation

After installation completes, verify each deployment:

1. **Check Service Status**
   ```bash
   # Example for Fyers deployment
   sudo systemctl status openalgo-fyers-yourdomain-fyers
   
   # Example for Zerodha deployment
   sudo systemctl status openalgo-zerodha-yourdomain-zerodha
   ```

2. **Verify Nginx Configuration**
   ```bash
   # Test overall Nginx configuration
   sudo nginx -t

   # Check specific site configurations
   # For Debian/Ubuntu (sites-enabled):
   ls -l /etc/nginx/sites-enabled/
   cat /etc/nginx/sites-enabled/fyers.yourdomain.com

   # For RHEL/CentOS/Arch (conf.d):
   ls -l /etc/nginx/conf.d/
   cat /etc/nginx/conf.d/fyers.yourdomain.com.conf
   ```

3. **Access Web Interfaces**
   Test each deployment in your web browser:
   ```
   https://fyers.yourdomain.com
   https://zerodha.yourdomain.com
   ```

4. **Check Installation Logs**
   ```bash
   # View the installation log for your deployment
   cat install/logs/install_YYYYMMDD_HHMMSS.log
   ```

## Troubleshooting

### Common Issues

1. **SSL Certificate Issues**
   ```bash
   # Check Certbot logs
   sudo journalctl -u certbot
   
   # Example: Manually run certificate installation for trading.yourdomain.com
   sudo certbot --nginx -d trading.yourdomain.com
   
   # Example: Manually run certificate installation for multiple subdomains
   sudo certbot --nginx -d fyers.yourdomain.com -d zerodha.yourdomain.com
   ```

2. **Application Not Starting**
   Example scenario: Managing multiple broker deployments
   ```bash
   # Example 1: Fyers deployment on fyers.yourdomain.com
   sudo journalctl -u openalgo-fyers-yourdomain-fyers    # View logs
   sudo systemctl restart openalgo-fyers-yourdomain-fyers # Restart service
   
   # Example 2: Zerodha deployment on zerodha.yourdomain.com
   sudo journalctl -u openalgo-zerodha-yourdomain-zerodha # View logs
   sudo systemctl restart openalgo-zerodha-yourdomain-zerodha # Restart service
   ```

3. **Nginx Issues**
   ```bash
   # Check Nginx error logs for all deployments
   sudo tail -f /var/log/nginx/error.log
   
   # Check access logs for specific domains
   sudo tail -f /var/log/nginx/fyers.yourdomain.com.access.log
   sudo tail -f /var/log/nginx/zerodha.yourdomain.com.access.log
   ```

4. **Installation Logs**
   Example: Checking installation logs for multiple deployments
   ```bash
   # List all installation logs
   ls -l install/logs/
   
   # View latest installation log
   cat install/logs/$(ls -t install/logs/ | head -1)
   
   # Example: View specific deployment logs
   cat install/logs/install_20240101_120000.log  # Fyers installation
   cat install/logs/install_20240101_143000.log  # Zerodha installation
   ```

### Distribution-Specific Troubleshooting

#### Arch Linux

1. **Nginx not listening on port 443**
   ```bash
   # Check if conf.d is included in nginx.conf
   grep "conf.d" /etc/nginx/nginx.conf

   # If missing, add it manually
   sudo sed -i '/http {/a\    include /etc/nginx/conf.d/*.conf;' /etc/nginx/nginx.conf
   sudo systemctl restart nginx
   ```

2. **UV installation issues**
   ```bash
   # Install via pacman
   sudo pacman -Sy python-uv

   # Or use pip with system packages override
   sudo python -m pip install --break-system-packages uv
   ```

#### RHEL/CentOS/Fedora

1. **SELinux blocking Nginx**
   ```bash
   # Check SELinux status
   getenforce

   # View SELinux denials
   sudo ausearch -m avc -ts recent

   # The script auto-configures SELinux, but if issues persist:
   sudo setsebool -P httpd_can_network_connect on
   sudo semanage fcontext -a -t httpd_sys_rw_content_t "/var/python/openalgo-flask(/.*)?"
   sudo restorecon -Rv /var/python/openalgo-flask
   ```

2. **Firewalld not configured**
   ```bash
   # Check firewall status
   sudo firewall-cmd --list-all

   # Manually add rules if needed
   sudo firewall-cmd --permanent --add-service=http
   sudo firewall-cmd --permanent --add-service=https
   sudo firewall-cmd --reload
   ```

#### Cloudflare 521 Error

1. **Set SSL/TLS mode to "Full (strict)"**
   - Go to Cloudflare Dashboard → SSL/TLS → Overview
   - Change encryption mode from "Flexible" to "Full (strict)"

2. **Temporarily disable proxy for testing**
   - Go to DNS tab
   - Click orange cloud icon → turns grey (DNS only)
   - Test your site directly
   - Re-enable proxy after confirming server works

### Managing Multiple Deployments

1. **Service Management Examples**
   ```bash
   # List all OpenAlgo services
   systemctl list-units "openalgo-*"
   
   # Example outputs:
   # openalgo-fyers-yourdomain-fyers.service    loaded active running
   # openalgo-zerodha-yourdomain-zerodha.service loaded active running
   
   # Restart specific deployment
   sudo systemctl restart openalgo-fyers-yourdomain-fyers
   
   # Check status of specific deployment
   sudo systemctl status openalgo-zerodha-yourdomain-zerodha
   ```

2. **Log Management Examples**
   ```bash
   # View real-time logs for Fyers deployment
   sudo journalctl -f -u openalgo-fyers-yourdomain-fyers
   
   # View last 100 lines of Zerodha deployment logs
   sudo journalctl -n 100 -u openalgo-zerodha-yourdomain-zerodha
   
   # View logs since last hour for specific deployment
   sudo journalctl --since "1 hour ago" -u openalgo-fyers-yourdomain-fyers
   ```

3. **Nginx Configuration Examples**
   ```bash
   # View Nginx configs for different deployments
   sudo nano /etc/nginx/sites-available/fyers.yourdomain.com
   sudo nano /etc/nginx/sites-available/zerodha.yourdomain.com
   
   # Test Nginx configuration
   sudo nginx -t
   
   # Reload Nginx after config changes
   sudo systemctl reload nginx
   ```

4. **Installation Directory Examples**
   ```bash
   # List deployment directories
   ls -l /var/python/openalgo-flask/
   
   # Example structure:
   # /var/python/openalgo-flask/fyers-yourdomain-fyers/
   # /var/python/openalgo-flask/zerodha-yourdomain-zerodha/
   
   # Check specific deployment files
   ls -l /var/python/openalgo-flask/fyers-yourdomain-fyers/
   ```

## Security Notes

1. **Firewall**
   - **Debian/Ubuntu/Arch:** Configures UFW to allow only HTTP, HTTPS, and SSH
   - **RHEL/CentOS/Fedora:** Configures firewalld to allow only HTTP, HTTPS, and SSH
   - Additional ports can be opened if needed:
     ```bash
     # For UFW (Debian/Ubuntu/Arch)
     sudo ufw allow <port_number>

     # For firewalld (RHEL/CentOS/Fedora)
     sudo firewall-cmd --permanent --add-port=<port_number>/tcp
     sudo firewall-cmd --reload
     ```

2. **SELinux (RHEL-based systems)**
   - The installation script **automatically configures SELinux** for OpenAlgo
   - Sets correct contexts for application directories
   - Enables httpd network connections
   - Creates custom policies if needed
   - No manual SELinux configuration required!

3. **SSL/TLS**
   - Certificates are automatically renewed by Certbot
   - The installation configures modern SSL parameters
   - Regular updates are recommended:
     ```bash
     # For Debian/Ubuntu
     sudo apt update && sudo apt upgrade -y

     # For RHEL/CentOS/Fedora
     sudo dnf update -y
     # or on older systems
     sudo yum update -y

     # For Arch Linux
     sudo pacman -Syu
     ```

## Post-Installation

1. Configure your broker settings in the web interface
2. Set up monitoring and alerts if needed
3. Regularly check logs for any issues
4. Keep the system updated with security patches

## Support

For issues and support:
- Check the [GitHub repository](https://github.com/marketcalls/openalgo)
- Review the logs using commands provided above
- Contact support with relevant log information

Remember to:
- Regularly backup your configuration
- Monitor system resources
- Keep the system updated
- Review security best practices
